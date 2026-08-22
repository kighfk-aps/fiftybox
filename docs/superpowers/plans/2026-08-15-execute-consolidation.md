# fiftybox-execute / fiftybox-local Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse five near-duplicate implementation-execution skills (`fiftybox-execute`, `fiftybox-cc-execute`, `fiftybox-free-execute` in the `fiftybox` repo, and `pi-execute` in the `claude-code-config` repo) into two provider-parameterized skills — `fiftybox-execute` (paid/cloud, batch-parallel) and `fiftybox-local` (local/free, dynamically parallel) — add Grok Build as a new provider, and switch the design/plan review default model from `gpt-5.6-terra` to `gpt-5.6-sol`.

**Architecture:** `orchestrate.py`'s `--implement-agent`/`--model` flags already generalize the "which CLI implements this task" question — the skill layer just hard-coded them per-skill. The two new skills expose those flags directly and delete the duplicated Step 1–10 workflow text, keeping one copy of the workflow (cc-execute's, the most complete) as the shared base. `fiftybox-local` additionally gets a model-discovery step (moved from `fiftybox-free-execute`) whose candidate count drives batch size, and a Modal-Qwen wake-up hook (moved from `pi-execute --local`).

**Tech Stack:** Bash (skills, tests), Python 3 (`orchestrate.py`, `gpt_review.py`, `diff_review.py`, `discover_free_models.py`), Markdown (SKILL.md / slash commands).

**Spec:** `docs/superpowers/specs/2026-08-15-execute-consolidation-design.md`

## Global Constraints

- Claude never writes implementation files directly — only test files and artifact documents (carried into both new SKILL.md files verbatim from the existing skills).
- `--provider`/`--model` values pass through to `orchestrate.py` unchanged — no skill-layer reinterpretation.
- Advisory diff review (codex/`gpt-5.6-*` only) is opt-in via natural language in the invocation, never a hard default — omit entirely when not mentioned.
- `fiftybox-local`'s batch size for a round equals the number of currently-healthy distinct candidate models; each task in a batch is pinned to a different model.
- `commandcode`/`opencode`/`pi`/`grok` (via `--implement-agent`) must not commit or push; only `--phase complete` commits.
- Design/plan review default model becomes `gpt-5.6-sol` / effort `high`; the cc-execute-derived advisory diff-review script keeps `gpt-5.6-terra` as its own internal default (different role, explicitly out of scope for the sol swap).
- `skills/fiftybox-local-execute*` and its install.sh/gitignore wiring are untouched — only the `fiftybox-local` (no `-execute` suffix) name is being reclaimed.

---

### Task 1: Switch design/plan review default to gpt-5.6-sol

**Files:**
- Modify: `skills/fiftybox-gpt-review/scripts/gpt_review.py:32-33`
- Modify: `skills/fiftybox-gpt-review/SKILL.md:33,102`
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (help text at the `--design-review-model`/`--design-review-agent` argparse block, and the two inline mentions in `run_design_review_agent`'s docstring and the `phase_verify_design` SKIP note)
- Test: `tests/test_sol_default.sh` (new)

**Interfaces:**
- Produces: `gpt_review.py`'s `DEFAULT_MODEL = "gpt-5.6-sol"` (was `"gpt-5.6-terra"`), `DEFAULT_EFFORT` unchanged (`"high"`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_sol_default.sh`:

```bash
#!/usr/bin/env bash
# Tests that design/plan review defaults to gpt-5.6-sol, not gpt-5.6-terra
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPT_REVIEW="$SCRIPT_DIR/skills/fiftybox-gpt-review/scripts/gpt_review.py"
GPT_REVIEW_SKILL="$SCRIPT_DIR/skills/fiftybox-gpt-review/SKILL.md"
ORCH="$SCRIPT_DIR/skills/fiftybox-orchestration/scripts/orchestrate.py"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

has() {
    if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi
}
lacks() {
    if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi
}

has "$GPT_REVIEW" 'DEFAULT_MODEL = "gpt-5.6-sol"' "gpt_review.py defaults to gpt-5.6-sol"
lacks "$GPT_REVIEW" 'DEFAULT_MODEL = "gpt-5.6-terra"' "gpt_review.py no longer defaults to gpt-5.6-terra"

has "$GPT_REVIEW_SKILL" "gpt-5.6-sol" "fiftybox-gpt-review SKILL.md documents the sol default"

# orchestrate.py Phase4 design review: help text / SKIP note / docstring should
# now point at sol, not terra
has "$ORCH" "gpt-5.6-sol" "orchestrate.py mentions gpt-5.6-sol for design review"
lacks "$ORCH" "gpt-5.6-terra" "orchestrate.py no longer mentions gpt-5.6-terra anywhere"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

```bash
chmod +x tests/test_sol_default.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_sol_default.sh`
Expected: FAIL — `gpt_review.py` still has `gpt-5.6-terra`, `orchestrate.py` still mentions `gpt-5.6-terra` (design-review help/docstring/SKIP note) and has no `gpt-5.6-sol` occurrence.

- [ ] **Step 3: Apply the changes**

`skills/fiftybox-gpt-review/scripts/gpt_review.py` line 32:
```python
DEFAULT_MODEL = "gpt-5.6-sol"
```

`skills/fiftybox-gpt-review/SKILL.md` line 33, change:
```
기본값은 `gpt-5.6-terra` / `high`다. 사용자가 모델을 지정하지 않으면 그대로 쓴다.
```
to:
```
기본값은 `gpt-5.6-sol` / `high`다. 사용자가 모델을 지정하지 않으면 그대로 쓴다.
```

Line 102 (파이프라인에서 쓰기 절):
```
--design-review-agent codex --design-review-model gpt-5.6-terra
```
to:
```
--design-review-agent codex --design-review-model gpt-5.6-sol
```

In `skills/fiftybox-orchestration/scripts/orchestrate.py`, replace every remaining
literal `gpt-5.6-terra` with `gpt-5.6-sol` in these three spots (all are help/log
text, not a hardcoded default — the flag itself has no default, it stays opt-in):
1. `run_design_review_agent`'s docstring: `` `--design-review-agent codex --design-review-model gpt-5.6-terra`) ``
2. `phase_verify_design`'s SKIP note string: `"or --design-review-agent codex --design-review-model gpt-5.6-terra "`
3. The `--design-review-agent` argparse `help=` string: `"the configured explore agent with --design-review-provider."` — this one has no terra mention, skip it. Confirm by grep — only the two above need editing.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_sol_default.sh`
Expected: PASS (all 5 assertions)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-gpt-review/scripts/gpt_review.py skills/fiftybox-gpt-review/SKILL.md \
  skills/fiftybox-orchestration/scripts/orchestrate.py tests/test_sol_default.sh
git commit -m "feat(gpt-review): switch design/plan review default to gpt-5.6-sol"
```

---

### Task 2: Add `grok` as a BUILTIN_AGENTS provider

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py:82-97` (`BUILTIN_AGENTS` dict)
- Test: `tests/test_grok_agent.sh` (new — mirrors `tests/test_cc_agent.sh`)

**Interfaces:**
- Produces: `BUILTIN_AGENTS["grok"]["cmd"] == ["grok", "-p", "{prompt}\n{task}", "--model", "{model}", "--permission-mode", "bypassPermissions", "--output-format", "json"]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_grok_agent.sh` (copy `tests/test_cc_agent.sh` and adapt):

```bash
#!/usr/bin/env bash
# Tests for the grok agent entry in orchestrate.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCH="$SCRIPT_DIR/skills/fiftybox-orchestration/scripts/orchestrate.py"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

run_py() {
    ORCH_PATH="$ORCH" python3 - "$@" <<'PY'
import importlib.util, json, os, sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("orch", os.environ["ORCH_PATH"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

what = sys.argv[1]
if what == "has-agent":
    print("yes" if "grok" in mod.BUILTIN_AGENTS else "no")
elif what == "argv":
    cfg = {"agents": dict(mod.BUILTIN_AGENTS)}
    argv = mod.build_agent_cmd(
        "grok", cfg,
        prompt="PROMPT", task="TASK", model="grok-4.6",
        provider="SHOULD_NOT_APPEAR", adapters_dir=Path("/tmp"),
    )
    print(json.dumps(argv))
elif what == "cli-route":
    import argparse
    ns = argparse.Namespace(implement_agent="grok")
    cfg = mod.resolve_agent_config(Path("/nonexistent-skill-dir"), ns)
    print(cfg["implement_agent"])
PY
}

[[ "$(run_py has-agent)" == "yes" ]] \
    && pass "grok agent registered in BUILTIN_AGENTS" \
    || fail "grok agent missing from BUILTIN_AGENTS"

ARGV="$(run_py argv 2>/dev/null || echo '[]')"
EXPECTED='["grok", "-p", "PROMPT\nTASK", "--model", "grok-4.6", "--permission-mode", "bypassPermissions", "--output-format", "json"]'
NORMALISED="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$ARGV")"
EXPECTED_NORM="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$EXPECTED")"
[[ "$NORMALISED" == "$EXPECTED_NORM" ]] \
    && pass "grok argv matches the specified flag set" \
    || fail "grok argv mismatch: $ARGV"

[[ "$ARGV" != *SHOULD_NOT_APPEAR* ]] \
    && pass "provider value not passed to grok" \
    || fail "provider value leaked into grok argv: $ARGV"

[[ "$(run_py cli-route 2>/dev/null || echo FAILED)" == "grok" ]] \
    && pass "--implement-agent override resolves to grok" \
    || fail "resolve_agent_config did not honour --implement-agent grok"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

```bash
chmod +x tests/test_grok_agent.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_grok_agent.sh`
Expected: FAIL on "grok agent registered" (grok not in `BUILTIN_AGENTS` yet).

- [ ] **Step 3: Add the BUILTIN_AGENTS entry**

In `skills/fiftybox-orchestration/scripts/orchestrate.py`, inside the `BUILTIN_AGENTS` dict (currently lines 82-97), add after the `"commandcode"` entry:

```python
    "grok": {"cmd": ["grok", "-p", "{prompt}\n{task}", "--model", "{model}",
                     "--permission-mode", "bypassPermissions",
                     "--output-format", "json"]},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_grok_agent.sh`
Expected: PASS (all 4 assertions)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-orchestration/scripts/orchestrate.py tests/test_grok_agent.sh
git commit -m "feat(orchestrate): add grok as a BUILTIN_AGENTS provider"
```

---

### Task 3: Reclaim the `fiftybox-local` name in `.gitignore`

**Files:**
- Modify: `.gitignore:10-13`

**Interfaces:**
- Produces: `skills/fiftybox-local/` and `commands/fiftybox-local.md` are no longer git-ignored; `skills/fiftybox-local-execute*` and `commands/fiftybox-local-execute*.md` remain ignored.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gitignore_local.sh`:

```bash
#!/usr/bin/env bash
# fiftybox-local (no suffix) must be trackable; fiftybox-local-execute stays ignored
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

if git check-ignore -q "skills/fiftybox-local/SKILL.md"; then
    fail "skills/fiftybox-local/SKILL.md is still git-ignored"
else
    pass "skills/fiftybox-local/SKILL.md is trackable"
fi

if git check-ignore -q "commands/fiftybox-local.md"; then
    fail "commands/fiftybox-local.md is still git-ignored"
else
    pass "commands/fiftybox-local.md is trackable"
fi

if git check-ignore -q "skills/fiftybox-local-execute/SKILL.md"; then
    pass "skills/fiftybox-local-execute/SKILL.md remains git-ignored"
else
    fail "skills/fiftybox-local-execute/SKILL.md is no longer git-ignored"
fi

if git check-ignore -q "commands/fiftybox-local-execute.md"; then
    pass "commands/fiftybox-local-execute.md remains git-ignored"
else
    fail "commands/fiftybox-local-execute.md is no longer git-ignored"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

```bash
chmod +x tests/test_gitignore_local.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_gitignore_local.sh`
Expected: FAIL on the first two assertions (current `.gitignore` wildcards `fiftybox-local*` catch the plain name too).

- [ ] **Step 3: Narrow the gitignore patterns**

In `.gitignore`, replace lines 10-13:
```
# Local-only Claude command/skill variants that may contain private endpoints
commands/fiftybox-local*.md
skills/fiftybox-local*/
skills/fiftybox-local*.md
```
with:
```
# Local-only Claude command/skill variants that may contain private endpoints
# (fiftybox-local itself was reclaimed 2026-08-15 for the consolidated
# execute skill and is tracked; only the -execute variant stays private)
commands/fiftybox-local-execute*.md
skills/fiftybox-local-execute*/
skills/fiftybox-local-execute*.md
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_gitignore_local.sh`
Expected: PASS (all 4 assertions)

- [ ] **Step 5: Commit**

```bash
git add .gitignore tests/test_gitignore_local.sh
git commit -m "chore: reclaim fiftybox-local from gitignore for the consolidated skill"
```

---

### Task 4: Move and generalize the advisory diff-review script

**Files:**
- Create: `skills/fiftybox-execute/scripts/diff_review.py` (copied from `skills/fiftybox-cc-execute/scripts/cc_diff_review.py`, same content — this script is already provider-agnostic on its input side, it only talks to `codex`/`gpt-5.6-*`, which matches the "codex-only advisory review" scope decision)
- Create: `skills/fiftybox-execute/scripts/cc_preflight.py` (copied from `skills/fiftybox-cc-execute/scripts/cc_preflight.py`, unchanged — still commandcode-specific, only invoked when `--provider commandcode`)
- Delete (end of Task 10): `skills/fiftybox-cc-execute/scripts/cc_diff_review.py`, `skills/fiftybox-cc-execute/scripts/cc_preflight.py`
- Test: `tests/test_diff_review_moved.sh` (new)

**Interfaces:**
- Produces: `skills/fiftybox-execute/scripts/diff_review.py` — same CLI contract as `cc_diff_review.py` (`--diff --spec --test --context --task-name --out --model --effort`), same exit codes (2/3/4/5/6), same `DEFAULT_MODEL = "gpt-5.6-terra"` (unchanged — advisory diff review is out of the sol migration's scope per the design doc)

- [ ] **Step 1: Write the failing test**

Create `tests/test_diff_review_moved.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

[[ -f "$SCRIPT_DIR/skills/fiftybox-execute/scripts/diff_review.py" ]] \
    && pass "diff_review.py exists under fiftybox-execute/scripts" \
    || fail "diff_review.py missing"

[[ -f "$SCRIPT_DIR/skills/fiftybox-execute/scripts/cc_preflight.py" ]] \
    && pass "cc_preflight.py exists under fiftybox-execute/scripts" \
    || fail "cc_preflight.py missing"

grep -qF 'DEFAULT_MODEL = "gpt-5.6-terra"' "$SCRIPT_DIR/skills/fiftybox-execute/scripts/diff_review.py" \
    && pass "diff_review.py keeps gpt-5.6-terra as its own default (out of sol scope)" \
    || fail "diff_review.py default model changed unexpectedly"

python3 -c "
import argparse, importlib.util, sys
spec = importlib.util.spec_from_file_location('dr', '$SCRIPT_DIR/skills/fiftybox-execute/scripts/diff_review.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert callable(getattr(mod, 'main', None)) or True
" && pass "diff_review.py imports without syntax errors" \
    || fail "diff_review.py fails to import"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

```bash
chmod +x tests/test_diff_review_moved.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_diff_review_moved.sh`
Expected: FAIL — `skills/fiftybox-execute/scripts/` doesn't exist yet.

- [ ] **Step 3: Copy the scripts**

```bash
mkdir -p skills/fiftybox-execute/scripts
cp skills/fiftybox-cc-execute/scripts/cc_diff_review.py skills/fiftybox-execute/scripts/diff_review.py
cp skills/fiftybox-cc-execute/scripts/cc_preflight.py skills/fiftybox-execute/scripts/cc_preflight.py
```

No content edits — `cc_diff_review.py`'s CLI contract, exit codes, and `DEFAULT_MODEL`
are already provider-agnostic in the sense that matters here (it always talks to
codex regardless of which provider implemented the diff being reviewed).

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_diff_review_moved.sh`
Expected: PASS (all 4 assertions)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-execute/scripts/diff_review.py skills/fiftybox-execute/scripts/cc_preflight.py \
  tests/test_diff_review_moved.sh
git commit -m "feat(fiftybox-execute): add advisory diff-review and cc preflight scripts"
```

---

### Task 5: Rewrite `fiftybox-execute/SKILL.md` as the unified paid/cloud skill

**Files:**
- Modify: `skills/fiftybox-execute/SKILL.md` (full rewrite)
- Modify: `commands/fiftybox-execute.md` (description update)
- Test: `tests/test_execute_skill_doc.sh` (new — replaces the assertions `tests/test_cc_skill_doc.sh` made against the old `fiftybox-cc-execute`)

**Interfaces:**
- Consumes: `BUILTIN_AGENTS["grok"]` (Task 2), `BUILTIN_AGENTS["commandcode"]` (pre-existing), `skills/fiftybox-execute/scripts/diff_review.py` + `cc_preflight.py` (Task 4)
- Produces: `/fiftybox-execute "<task>" [--provider <id>] [--model <id>]` invocation contract that later tasks (install.sh, README) reference by this exact flag spelling

- [ ] **Step 1: Write the failing test**

Create `tests/test_execute_skill_doc.sh`:

```bash
#!/usr/bin/env bash
# Structure tests for the unified fiftybox-execute skill
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-execute/SKILL.md"
COMMAND="$SCRIPT_DIR/commands/fiftybox-execute.md"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }
lacks() { if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

# --- invocation surface ---------------------------------------------------
has "$SKILL" "--provider <id>" "SKILL.md documents --provider"
has "$SKILL" "--model <id>" "SKILL.md documents --model"
has "$SKILL" "opencode-go" "SKILL.md keeps opencode-go/deepseek-v4-flash as the fallback default"
has "$SKILL" "deepseek-v4-flash" "SKILL.md names the fallback model"
has "$SKILL" "grok" "SKILL.md lists grok as a provider option"
has "$SKILL" "commandcode" "SKILL.md lists commandcode as a provider option"
has "$SKILL" "--implement-agent" "SKILL.md passes --implement-agent through to orchestrate.py"

# --- absorbed cc-execute contract -----------------------------------------
has "$SKILL" "design.md는 필수" "SKILL.md states design.md is mandatory"
has "$SKILL" "Out of Scope" "SKILL.md names the design doc's scope section"
has "$SKILL" "Red 페이즈 테스트 파일이 예외임을 명시한다" "SKILL.md instructs carving out Red-phase tests"
has "$SKILL" "--skip-codex-review" "SKILL.md passes --skip-codex-review to review-test"
has "$SKILL" "nohup" "SKILL.md requires detached implement runs"
has "$SKILL" "incomplete_commit" "SKILL.md warns about incomplete_commit before cleanup"
has "$SKILL" "~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py" \
    "SKILL.md uses the correct orchestrate.py path"

# --- advisory review: opt-in via natural language, no default ------------
has "$SKILL" "diff_review.py" "SKILL.md runs the generalized diff review script"
has "$SKILL" "자연어" "SKILL.md documents the natural-language opt-in trigger"
has "$SKILL" "advisory" "SKILL.md marks the review as advisory"
has "$SKILL" "테스트 실행은 Claude" "SKILL.md keeps test execution with Claude"
has "$SKILL" "Claude 폴백" "SKILL.md documents the Claude fallback"
has "$SKILL" "pathspec" "SKILL.md scopes the task diff with a pathspec"

# --- prohibitions ----------------------------------------------------------
lacks "$SKILL" "skills/orchestrate/scripts" "SKILL.md avoids the non-existent orchestrate path"
lacks "$SKILL" "errorClass" "SKILL.md omits the unimplemented errorClass table"
lacks "$SKILL" "--commit-message" "SKILL.md does not document the nonexistent --commit-message flag"

# --- slash command ----------------------------------------------------------
has "$COMMAND" "skills/fiftybox-execute/SKILL.md" "slash command points at the skill body"
has "$COMMAND" '$ARGUMENTS' "slash command forwards \$ARGUMENTS"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

```bash
chmod +x tests/test_execute_skill_doc.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_execute_skill_doc.sh`
Expected: FAIL on most assertions — current `fiftybox-execute/SKILL.md` has none of the provider/grok/advisory-review content.

- [ ] **Step 3: Rewrite the SKILL.md**

Base the rewrite on `skills/fiftybox-cc-execute/SKILL.md` (the most complete existing
version — has the batch-parallel workflow, failure classification table, and the
Step 6a/6b advisory review pattern this unified skill needs). Apply these exact
changes on top of that base:

1. **Frontmatter**: `name: fiftybox-execute`, description updated to mention
   provider parameterization (opencode-go/commandcode/pi/grok) instead of only
   CommandCode.
2. **Invocation section**: replace
   ```
   /fiftybox-cc-execute "<작업 설명>" [--model <id>]
   ```
   with
   ```
   /fiftybox-execute "<작업 설명>" [--provider <id>] [--model <id>]
   ```
   Document: `--provider`/`--model` pass straight through to `orchestrate.py`'s
   `--implement-agent`/`--model` with no reinterpretation. Omitted →
   `--provider opencode-go --model deepseek-v4-flash` (the old plain
   `fiftybox-execute` default, preserved for backward compatibility).
3. **모델 티어 section**: replace the CommandCode-only tier table with a plain
   reference table (not enforced, informational):
   ```markdown
   ## Provider 참고

   | provider | 비고 |
   |---|---|
   | `opencode-go` (기본, `--model deepseek-v4-flash`) | 별도 인증 불필요 |
   | `commandcode` | `cmd` 요금제 필요. Step 0 preflight로 확인 |
   | `pi` | Pi CLI. `--model glm-5.2` 등 |
   | `grok` | Grok Build. SuperGrok 요금제 필요, `grok inspect`로 로그인 확인 |

   CommandCode의 simple/complex tier 판정(Step 3)은 참고용으로 남기되 강제하지
   않는다 — `--model`을 직접 지정하면 그 tier 로직은 건너뛴다.
   ```
4. **Step 0 (Preflight)**: make it conditional — only run `cc_preflight.py` when
   `--provider commandcode` (or no `--provider`, defaulting away from
   commandcode, meaning preflight is skipped entirely). For `grok`, add an
   equivalent check: `grok inspect` must show `Project trusted: yes`; if not,
   tell the user to run `grok login` and stop. For `pi`/`opencode-go`, no
   preflight (matches current plain `fiftybox-execute` behavior).
5. **Step 5 (병렬 구현)**: generalize the per-task dispatch command from
   ```
   --implement-agent commandcode --model "<tier 모델>"
   ```
   to
   ```
   --implement-agent "<provider>" --model "<model>"
   ```
   using the values resolved at invocation time (Step "Model Resolution",
   new — copy the parsing pattern from `pi-execute`'s "Model Resolution"
   section: parse `--provider`/`--model` once at invocation, store, reuse for
   every `--phase implement` and `--phase deploy` call).
6. **Step 6 (advisory review, was Step 6a/6b)**: change the trigger from
   "always run for CommandCode" to natural-language opt-in:
   ```markdown
   ### Step 6 — 리뷰 게이트 (선택적 advisory diff 리뷰 → Claude 최종)

   **advisory diff 리뷰는 opt-in이다.** 사용자가 호출 문장에 리뷰 provider/model을
   자연어로 언급했을 때만 수행한다(예: "sol로 리뷰까지 해줘", "gpt-5.6-terra로
   검토해줘"). 언급이 없으면 이 절 전체를 건너뛰고 곧장 Claude 최종 게이트(아래
   6b에 해당하는 ①③)로 간다. 언급했는데 모델이 불분명하면 한 번 물어본다.

   리뷰를 수행할 때는 `diff_review.py`(과거 `cc_diff_review.py`)를 그대로 쓴다.
   ```
   Keep everything else in this section (pathspec requirement, exit-code table,
   Claude 폴백, verdict routing, 통합 검사 staying with Claude, `reviewPath`
   from JSON not reconstructed) verbatim — only the trigger condition and the
   script filename (`cc_diff_review.py` → `diff_review.py`, path
   `~/.claude/skills/fiftybox-execute/scripts/diff_review.py`) change.
7. Every other section (Step 1–4, Step 7–10, 실패 처리, 안전 계약) — copy
   verbatim from `fiftybox-cc-execute/SKILL.md`, replacing only the skill name
   in prose (`cc-execute` → `execute`) and the script path prefix
   (`fiftybox-cc-execute/scripts/` → `fiftybox-execute/scripts/` where it
   appears for `cc_preflight.py`/`diff_review.py`).

Update `commands/fiftybox-execute.md`:

```markdown
---
name: fiftybox-execute
description: TDD execution pipeline — Claude writes tests, a chosen provider (opencode-go/commandcode/pi/grok) implements in parallel, Claude reviews
---

Load and follow the fiftybox-execute skill instructions at `skills/fiftybox-execute/SKILL.md`.

Task: $ARGUMENTS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_execute_skill_doc.sh`
Expected: PASS (all assertions)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-execute/SKILL.md commands/fiftybox-execute.md tests/test_execute_skill_doc.sh
git commit -m "feat(fiftybox-execute): unify provider selection, absorb cc-execute workflow"
```

---

### Task 6: Create `fiftybox-local/SKILL.md` — unified local/free skill

**Files:**
- Create: `skills/fiftybox-local/SKILL.md`
- Create: `skills/fiftybox-local/scripts/discover_free_models.py` (moved from `fiftybox-free-execute`)
- Create: `commands/fiftybox-local.md`
- Test: `tests/test_local_skill_doc.sh` (new)

**Interfaces:**
- Consumes: `discover_free_models.py`'s existing stdout JSON contract (candidates with `smoke: ok|rate_limited|...`), the Modal-Qwen wake-up bash snippet (copied from `claude-code-config/skills/pi-execute/SKILL.md`'s "Local Mode" section)
- Produces: `/fiftybox-local "<task>" [--provider <id> --model <id> ...]` invocation contract

- [ ] **Step 1: Write the failing test**

Create `tests/test_local_skill_doc.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-local/SKILL.md"
COMMAND="$SCRIPT_DIR/commands/fiftybox-local.md"
DISCOVER="$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_free_models.py"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

[[ -f "$DISCOVER" ]] && pass "discover_free_models.py moved into fiftybox-local" \
    || fail "discover_free_models.py missing from fiftybox-local"

has "$SKILL" "name: fiftybox-local" "SKILL.md frontmatter declares its name"
has "$SKILL" "discover_free_models.py" "SKILL.md runs the free-model discovery script"
has "$SKILL" "modal-qwen38" "SKILL.md includes the Modal Qwen candidate"
has "$SKILL" "qwen3.8-27b-q4_k_m" "SKILL.md names the Modal Qwen model id"
has "$SKILL" "piqwen" "SKILL.md uses the piqwen agent for Modal Qwen"
has "$SKILL" "75" "SKILL.md documents the wake-up check timing"
has "$SKILL" "120" "SKILL.md documents the wake-up check timing"
has "$SKILL" "150" "SKILL.md documents the wake-up check timing"
has "$SKILL" "1800" "SKILL.md documents the 1800s local implementation timeout"

# dynamic parallelism rule
has "$SKILL" "후보 모델 수" "SKILL.md ties batch size to candidate model count"
has "$SKILL" "서로 다른" "SKILL.md requires distinct models per parallel task"

has "$SKILL" "smoke" "SKILL.md checks discovery smoke status"
has "$SKILL" "유료 모델로 임의 전환하지 않는다" "SKILL.md refuses to fall back to paid models"

has "$SKILL" "Claude는 구현 파일을 직접 쓰거나 고치지 않는다" \
    "SKILL.md carries the no-direct-write prohibition"

has "$COMMAND" "skills/fiftybox-local/SKILL.md" "slash command points at the skill body"
has "$COMMAND" '$ARGUMENTS' "slash command forwards \$ARGUMENTS"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

```bash
chmod +x tests/test_local_skill_doc.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_local_skill_doc.sh`
Expected: FAIL — `skills/fiftybox-local/` doesn't exist yet.

- [ ] **Step 3: Build the skill**

```bash
mkdir -p skills/fiftybox-local/scripts
cp skills/fiftybox-free-execute/scripts/discover_free_models.py skills/fiftybox-local/scripts/discover_free_models.py
```

Write `skills/fiftybox-local/SKILL.md`. Structure (base workflow Steps 1-2, 4,
9-12 copied verbatim from `fiftybox-free-execute/SKILL.md` — design collection,
setup, Red-phase tests, complete/deploy/cleanup are unaffected by this change):

```markdown
---
name: fiftybox-local
description: 로컬·무료 provider(opencode 무료 티어, Modal Qwen3.8-27B)로 구현하는 동적 병렬 TDD 실행 파이프라인 — 가용 모델 수만큼 병렬도를 조절한다. Claude가 테스트를 쓰고 provider가 구현하고 Claude가 리뷰한다. 비용 없이(또는 최소 비용으로) 구현을 돌리고 싶을 때 사용한다.
---

# Fiftybox Local

로컬·무료 provider로 구현 페이즈를 돌린다. 후보는 매 실행 실측 탐색한다 —
무료 티어는 제공 모델과 할당량이 수시로 바뀐다.

**핵심 루프:** Claude가 실패하는 테스트 작성(Red) → provider가 통과시킴(Green) → Claude 리뷰

**실행 방식:** 동적 병렬. 이번 실행에서 가용한(healthy) distinct 모델 수가
배치의 최대 동시 실행 수다. 모델 1개면 순차, N개면 최대 N개 병렬 — 배치 내
각 태스크는 서로 다른 모델에 배정한다(같은 모델에 태스크를 몰지 않는다 —
무료 티어 분당 요청 제한, Modal 컨테이너 자원 경합을 피한다).

---

## ⛔ 절대 금지

**Claude는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다. Claude가 이
스킬에서 쓸 수 있는 파일은 두 가지뿐이다:
1. 테스트 파일 (Red 페이즈)
2. 아티팩트 문서 (`<artifactDir>/design.md` 등)

orchestrate.py가 실패하면 사용자에게 보고한다. 대신 구현하지 않는다.

## 호출

```
/fiftybox-local "<작업 설명>" [--provider <id> --model <id> ...]
```

`--provider`/`--model`을 명시하면 탐색을 건너뛰고 그 목록만 후보로 쓴다(수동
모드). 생략하면 아래 후보 풀 구성대로 매번 탐색한다.

## 후보 풀 구성

1. `discover_free_models.py`로 opencode Zen 무료 티어를 실측 탐색한다
   (각 후보에 실제 호출 1회 — 수십 초 걸릴 수 있다). `smoke: ok`인 것만
   후보로 삼는다.
2. **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
   `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만 가용성
   자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).
3. `metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

   > opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로
   > 진행하며 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

4. `smoke: ok` 후보(opencode 무료 + modal-qwen38 항상 포함)가 하나도 없으면
   중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.**

수동 모드(`--provider`/`--model` 직접 지정)에서는 이 탐색 전체를 건너뛰고
지정된 provider/model 쌍들을 그대로 후보로 쓴다.

## Modal Qwen 웨이크업 절차

`modal-qwen38`이 이번 배치에 포함될 때만 그 레인 앞에 적용한다. 다른 레인의
진행을 막지 않는다 — 독립 detached 프로세스이므로.

Modal serverless(ap-south)는 유휴 시 컨테이너가 0으로 스케일된다. 배치
implement 디스패치, fix 재시도, Phase 6 auto-retry, Phase 7b deploy — **매
디스패치 전에** 웨이크업한다:

```bash
nohup bash -c '
  token="$(security find-generic-password -a "$USER" -s pi-modal-qwen38-proxy-token -w)" || exit 1
  curl --silent --output /dev/null --write-out "%{http_code}" \
    --connect-timeout 15 --max-time 900 --retry 8 --retry-all-errors --retry-delay 2 --fail \
    -H "Authorization: Bearer $token" \
    https://kighfk--modal-qwen38-27b-serve.ap-south.modal.run/v1/models
' > "<artifactDir>/modal-wake-<N>.out" 2>&1 &
```

**정확히 세 번**, t+75초/t+120초/t+150초에 확인한다(루프로 폴링하지 않는다).
쉘 명령 타임아웃은 최소 180초로 잡는다:

```bash
wake="<artifactDir>/modal-wake-<N>.out"
elapsed=0
for extra in 75 45 30; do
  sleep "$extra"
  elapsed=$((elapsed + extra))
  code="$(tr -d '[:space:]' < "$wake" 2>/dev/null || true)"
  echo "wake-check t+${elapsed}s: ${code:-<empty>}"
  if [ "$code" = "200" ]; then echo READY; break; fi
done
```

`200`이 나오면 즉시 디스패치한다(남은 체크를 기다리지 않는다). 세 번째
체크 후에도 `200`이 아니면 디스패치하지 않고 보고한다 — 토큰/Keychain
문제는 `account`로, 그 외는 엔드포인트 실패로 분류한다. 모델 교체를
제안하지 않는다.

`--phase implement`/`--phase deploy` 호출에 `--implement-agent piqwen
--implementation-timeout 1800`을 추가한다. `--phase setup`에도
`--implement-agent piqwen`을 넘겨 미지의 에이전트 이름을 setup 단계에서
먼저 걸러낸다.

## 워크플로

### Step 1-4: 설계 수집, Setup, 태스크 분해

`fiftybox-free-execute`와 동일 — 단, 태스크 분해는 배치 크기가 후보 모델
수에 좌우되므로 **배치 단위**로 만든다(순수 순차 목록이 아니다):

```markdown
## Task Batches (동적 병렬 — 후보 3개 기준 예시)

### Round 1 (최대 3개 병렬, 서로 다른 모델)
- Task A → opencode/nemotron-3-ultra-free
- Task B → opencode/mimo-v2.5-free
- Task C → modal-qwen38

### Round 2 (남은 태스크, 다시 최대 3개 병렬)
- Task D → opencode/nemotron-3-ultra-free
```

### Step 5: Claude가 테스트 작성 (Red)

`fiftybox-free-execute`의 Step 6과 동일(라운드의 각 태스크에 대해 병렬로
작성).

### Step 6: 구현 (Green) — 라운드 병렬

라운드 내 각 태스크를 배정된 모델로 동시에 디스패치한다(cc-execute의 Agent
+ detached orchestrate.py 패턴과 동일). `modal-qwen38`이 배정된 레인은
디스패치 전 웨이크업 절차를 거친다.

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<배정된 provider>" --model "<배정된 model>" --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

라운드 내 모든 태스크가 끝날 때까지 기다린다.

### Step 7: Claude 리뷰 게이트

`fiftybox-free-execute`의 Step 8과 동일(테스트 결과 → 테스트 무력화 검사 →
명세 준수 → 통합 확인). 문제 없으면 다음 라운드로(Step 5-7 반복), 라운드가
모두 끝났으면 Step 8로.

Advisory diff 리뷰는 `fiftybox-execute`와 동일한 자연어 opt-in 트리거를
따른다(`~/.claude/skills/fiftybox-execute/scripts/diff_review.py` 재사용).

### Step 8-11: Review+Test, Complete, Deploy, Cleanup

`fiftybox-free-execute`의 Step 9-12와 동일 — `--implement-agent`/`--model`을
실패한 태스크에 배정됐던 값으로 재시도한다.

## 모델 소진 처리

라운드 중 한 모델이 소진되면 그 모델이 담당하던 태스크만 재탐색된 다른
후보로 재배정한다. 형제 레인(다른 모델)은 계속 진행한다. `smoke: ok` 후보가
하나도 안 남으면 중단하고 보고한다.

## 안전 계약

`fiftybox-free-execute`/`fiftybox-execute`와 동일 — Claude는 구현 코드를
직접 쓰지 않는다, provider는 테스트 파일을 수정하지 않는다, force
push/reset hard/branch -D 금지, Phase 7 이전 push 금지, 자동 재시도는
태스크당 1회, 실패 시 선택지 제시.
```

Write `commands/fiftybox-local.md`:

```markdown
---
name: fiftybox-local
description: 로컬·무료 provider로 구현하는 동적 병렬 TDD 실행 파이프라인
---

Load and follow the fiftybox-local skill instructions at `skills/fiftybox-local/SKILL.md`.

Task: $ARGUMENTS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_local_skill_doc.sh`
Expected: PASS (all assertions)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-local/ commands/fiftybox-local.md tests/test_local_skill_doc.sh
git commit -m "feat: add fiftybox-local — dynamic-parallel local/free execute skill"
```

---

### Task 7: Update `install.sh` wiring

**Files:**
- Modify: `install.sh`

**Interfaces:**
- Consumes: `skills/fiftybox-execute/` (Task 5 content), `skills/fiftybox-local/` (Task 6 content, now unconditionally tracked per Task 3)
- Produces: install.sh copies `fiftybox-execute/scripts/` (including the two new scripts) and `fiftybox-local/` unconditionally; drops the cc-execute/free-execute blocks; the old conditional `fiftybox-local` block (select_remote_model.sh/openai.yaml) is replaced

- [ ] **Step 1: Write the failing test**

This extends `tests/test_install.sh` in place (existing file, not new) —
add these assertions after the existing `fiftybox-execute` block and replace
the whole `fiftybox-local` conditional block (lines ~124-159 per current
numbering) and the `fiftybox-cc-execute`/`fiftybox-free-execute` blocks. Since
`tests/test_install.sh` is one file exercised as a whole, "failing" here means:
run it now, confirm it fails once you've deleted the old cc-execute/free-execute
assertions in Step 3 below (belt-and-suspenders — the real red/green cycle for
this task is Step 2 vs Step 4).

Edit `tests/test_install.sh`:
1. Remove the `CC_EXECUTE_SKILL_DIR`/`FREE_EXECUTE_SKILL_DIR` variable
   declarations (lines 21-22) and their `[[ -f ... ]]` assertion blocks
   (the `fiftybox-free-execute` SKILL.md/discover_free_models.py checks,
   the `fiftybox-cc-execute` SKILL.md/cc_preflight.py checks, and their
   slash-command checks — currently around lines 84-102).
2. Remove the entire `if [[ -f "$SCRIPT_DIR/skills/fiftybox-local/SKILL.md" ]]`
   conditional block (lines ~127-159) and replace with unconditional
   assertions (fiftybox-local is now always present and tracked):
   ```bash
   [[ -f "$LOCAL_SKILL_DIR/SKILL.md" ]] \
       && pass "fiftybox-local skill installed" \
       || fail "fiftybox-local skill not installed"

   [[ -f "$LOCAL_SKILL_DIR/scripts/discover_free_models.py" ]] \
       && pass "fiftybox-local discover_free_models.py installed" \
       || fail "fiftybox-local discover_free_models.py missing"

   [[ -f "$COMMANDS_DIR/fiftybox-local.md" ]] \
       && pass "fiftybox-local slash command installed" \
       || fail "fiftybox-local slash command not installed"
   ```
   Drop the `CODEX_LOCAL_SKILL_DIR` assertions in this block (openai.yaml,
   Codex install) — the new fiftybox-local has no Codex variant.
3. Add assertions for the new `fiftybox-execute` scripts:
   ```bash
   [[ -f "$SKILLS_DIR_EXECUTE/scripts/diff_review.py" ]] \
       && pass "fiftybox-execute diff_review.py installed" \
       || fail "fiftybox-execute diff_review.py missing"

   [[ -f "$SKILLS_DIR_EXECUTE/scripts/cc_preflight.py" ]] \
       && pass "fiftybox-execute cc_preflight.py installed" \
       || fail "fiftybox-execute cc_preflight.py missing"
   ```
   (add `SKILLS_DIR_EXECUTE="$INSTALL_ROOT/.claude/skills/fiftybox-execute"`
   near the top alongside the other `*_DIR` variables)
4. Leave the `fiftybox-local-execute` conditional block (lines ~161-177)
   untouched — out of scope, still gated on source presence.

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_install.sh`
Expected: FAIL — `install.sh` still installs the old cc-execute/free-execute
skills and doesn't yet copy `fiftybox-execute/scripts/*.py` or
`fiftybox-local/SKILL.md` unconditionally (still gated on the old private
content's absence).

- [ ] **Step 3: Update install.sh**

Find and remove the `fiftybox-cc-execute` and `fiftybox-free-execute` install
blocks entirely (skill dir copy, scripts copy, slash command copy).

Find the `fiftybox-execute` install block; extend it to also copy the
`scripts/` directory (it currently only copies `SKILL.md` since the old
`fiftybox-execute` had no scripts):

```bash
mkdir -p "$SKILLS_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-execute/SKILL.md" "$SKILLS_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-execute/scripts/"*.py "$SKILLS_DIR/scripts/"
```//adjust variable name to match whatever install.sh currently calls the
fiftybox-execute skill dir.

Find the `if [[ -f "$SCRIPT_DIR/skills/fiftybox-local/SKILL.md" ]]` block
(the one gated on the old private skill's presence, with
`select_remote_model.sh`/`stop_remote_model.sh`/Codex `openai.yaml` copies)
and replace its body with an unconditional install (no more `if`, since
`fiftybox-local` is now always present in the tracked source tree):

```bash
mkdir -p "$LOCAL_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-local/SKILL.md" "$LOCAL_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_free_models.py" "$LOCAL_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-local → $LOCAL_SKILL_DIR"

mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/commands/fiftybox-local.md" "$COMMANDS_DIR/fiftybox-local.md"
```

Drop the Codex-specific copies for `fiftybox-local` (`CODEX_LOCAL_SKILL_DIR`,
`agents/openai.yaml`) — the new skill has no Codex variant. Leave the
`fiftybox-local-execute` block (both Claude and Codex sides) exactly as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_install.sh`
Expected: PASS (all assertions)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "chore(install): wire up unified fiftybox-execute/fiftybox-local, drop cc/free-execute"
```

---

### Task 8: Delete `fiftybox-cc-execute` and `fiftybox-free-execute`

**Files:**
- Delete: `skills/fiftybox-cc-execute/` (entire directory)
- Delete: `skills/fiftybox-free-execute/` (entire directory)
- Delete: `commands/fiftybox-cc-execute.md`
- Delete: `commands/fiftybox-free-execute.md`
- Delete: `tests/test_cc_agent.sh` — **do not delete**, see note below
- Delete: `tests/test_cc_preflight.sh`, `tests/test_cc_skill_doc.sh`

**Interfaces:**
- None — pure deletion, verified by absence + no dangling references (Task 9 does the reference sweep)

`tests/test_cc_agent.sh` tests `BUILTIN_AGENTS["commandcode"]` in
`orchestrate.py` directly — that agent entry is kept (still a valid
`--provider commandcode` for `fiftybox-execute`). **Keep this test file.**
`tests/test_cc_preflight.sh` and `tests/test_cc_skill_doc.sh` test the old
skill's own files, which are being deleted — remove them.

- [ ] **Step 1: Confirm the replacement tests already pass**

Run: `bash tests/test_execute_skill_doc.sh && bash tests/test_local_skill_doc.sh && bash tests/test_diff_review_moved.sh`
Expected: PASS for all three (they were made green in Tasks 4-6, before this
deletion — this step just re-confirms nothing regressed).

- [ ] **Step 2: Delete the old skills and their dedicated tests**

```bash
git rm -r skills/fiftybox-cc-execute skills/fiftybox-free-execute \
  commands/fiftybox-cc-execute.md commands/fiftybox-free-execute.md \
  tests/test_cc_preflight.sh tests/test_cc_skill_doc.sh
```

- [ ] **Step 3: Run the full test suite**

Run: `for t in tests/test_*.sh; do echo "=== $t ==="; bash "$t" || echo "FAILED: $t"; done`
Expected: no `FAILED:` lines. `test_cc_agent.sh` still passes (tests
`orchestrate.py`, untouched). `test_9b_spec_smoke.sh`/`test_readme_commands.sh`
may need the follow-up in Task 9-10 before they're green — note any failures
here for those tasks, don't fix them in this task.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove fiftybox-cc-execute and fiftybox-free-execute (absorbed into fiftybox-execute/fiftybox-local)"
```

---

### Task 9: Update README and sweep for stale references

**Files:**
- Modify: `README.md`
- Test: `tests/test_readme_commands.sh` (existing — run, fix any new failures)

**Interfaces:**
- None

- [ ] **Step 1: Run the existing README test**

Run: `bash tests/test_readme_commands.sh`
Expected: FAIL if `README.md` still lists `fiftybox-cc-execute`/
`fiftybox-free-execute` as commands (check the test's actual assertions
first — it may only check that every `commands/*.md` file is documented, in
which case removing those two `commands/*.md` files in Task 8 already fixes
it and this step instead confirms fiftybox-local's new `commands/fiftybox-local.md`
needs a README entry).

- [ ] **Step 2: Update README.md**

Remove any `fiftybox-cc-execute`/`fiftybox-free-execute` mentions. Add
`fiftybox-local` to the skill list with a one-line description matching its
SKILL.md frontmatter description. Update `fiftybox-execute`'s description to
mention provider parameterization.

- [ ] **Step 3: Grep sweep for stale references**

```bash
grep -rn "fiftybox-cc-execute\|fiftybox-free-execute" --include="*.md" --include="*.sh" --include="*.py" . \
  | grep -v "^./docs/superpowers/" | grep -v "^./plans/"
```

Expected: no output (docs/plans directories are historical records and are
allowed to still mention the old names). Fix any hits outside those
directories.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_readme_commands.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: update README for fiftybox-execute/fiftybox-local consolidation"
```

---

### Task 10: Full fiftybox repo test suite verification

**Files:** none (verification-only task)

- [ ] **Step 1: Run every test file**

```bash
for t in tests/test_*.sh; do
  echo "=== $t ==="
  bash "$t" || echo "FAILED: $t"
done
```

Expected: no `FAILED:` lines.

- [ ] **Step 2: If any orchestrate.py pytest suite exists, run it too**

```bash
find skills/fiftybox-orchestration/tests -name "test_*.py" -exec python3 -m pytest {} + 2>&1 | tail -30
```

Expected: all pass. If this reveals a gap the earlier tasks' bash-level tests
didn't catch (e.g. a Python-level `resolve_reviewer`/`BUILTIN_AGENTS` test
suite with its own terra/grok assertions), fix it here — do not leave a
failing suite for a later task to discover.

- [ ] **Step 3: Report status**

No commit for this task unless Step 2 required a fix (then commit that fix
with an appropriate message).

---

### Task 11: Remove `pi-execute` from the `claude-code-config` repository

> This task operates in `/Users/tanpapa/Desktop/develop-a/claude-code-config`,
> a different git repository from Tasks 1-10. Do not run these commands from
> the `fiftybox` checkout.

**Files (in `claude-code-config`):**
- Delete: `skills/pi-execute/`
- Delete: `commands/pi-execute.md` (if it exists)
- Modify: that repo's `install.sh` and test files that reference `pi-execute`

**Interfaces:** none — pure deletion, verified by absence

- [ ] **Step 1: Inventory references before touching anything**

```bash
cd /Users/tanpapa/Desktop/develop-a/claude-code-config
git status --short
grep -rln "pi-execute" --include="*.sh" --include="*.md" --include="*.py" --include="*.json" . \
  | grep -v "^./skills/pi-execute/" | grep -v "^./docs/superpowers/" | grep -v "^./plans/"
```

Read `git status --short` output carefully — this repo already has
uncommitted deletions of `fiftybox-local`/`fiftybox-local-execute` from
unrelated prior work (observed 2026-08-15). **Do not touch, stage, commit, or
revert those** — they are out of scope for this task. Only act on
`pi-execute`-related paths.

- [ ] **Step 2: Delete the skill and command**

```bash
git rm -r skills/pi-execute
[[ -f commands/pi-execute.md ]] && git rm commands/pi-execute.md
```

- [ ] **Step 3: Fix install.sh and test references**

For each file the Step 1 grep listed (outside `skills/pi-execute/` and the
docs/plans history dirs), open it and remove the `pi-execute`-specific
install/test block, following the same pattern used for
`fiftybox-cc-execute`/`fiftybox-free-execute` removal in Task 7-8 of this
plan (delete the block, don't leave a dangling reference).

- [ ] **Step 4: Run that repo's test suite**

```bash
for t in tests/test_*.sh; do echo "=== $t ==="; bash "$t" || echo "FAILED: $t"; done
```

Expected: no `FAILED:` lines related to `pi-execute`. (Failures related to the
pre-existing uncommitted `fiftybox-local` deletions from Step 1 are not this
task's responsibility — report them, don't fix them.)

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: remove pi-execute (absorbed into fiftybox repo's fiftybox-execute/fiftybox-local)"
```

Only stage the `pi-execute`-related paths explicitly (`git add <specific
paths>` before this commit, not `git add -A`) so the pre-existing unrelated
uncommitted deletions are not swept into this commit.

---

## Self-Review Notes

- **Spec coverage:** all six spec sections (스킬 인벤토리 변경, fiftybox-execute,
  fiftybox-local, sol 마이그레이션, 테스트/검증, Out of Scope) map to tasks
  1-11 above. Out-of-Scope items (claude-code-config's stale orchestrate.py
  copy, its pre-existing uncommitted deletions, the `orchestrate` legacy dir
  name) are explicitly called out as untouched in Task 11 rather than silently
  ignored.
- **Naming collision:** the original spec assumed `fiftybox-local` was a free
  name. Task 3 discovered and resolved a real collision with a pre-existing
  gitignored private skill of the same name (confirmed with the user: reclaim
  the name, narrow `.gitignore` to only protect `fiftybox-local-execute`).
- **Type/interface consistency:** `--provider`/`--model` spelling is used
  identically across Tasks 5, 6, 7 (never `--implement-agent` at the
  slash-command layer, always at the `orchestrate.py` call layer). `piqwen`/
  `modal-qwen38`/`1800` timeout values match verbatim across Task 6's SKILL.md
  and the source `pi-execute` material they were copied from.
