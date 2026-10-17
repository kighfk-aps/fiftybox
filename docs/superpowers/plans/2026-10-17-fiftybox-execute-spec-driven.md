# fiftybox-execute Spec-Driven Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `fiftybox-execute` carry a finished plan to one subscription model and deploy it, without the session writing tests or judging the diff.

**Architecture:** Add `--skip-verification` to `orchestrate.py` so `review-test` records success without running tests or a reviewer, and so `complete` does not claim tests passed. Rewrite `skills/fiftybox-execute/SKILL.md` to the approved spec. Copy both files onto the installed skill paths the session actually runs.

**Tech Stack:** Python 3, pytest, Markdown skill docs, existing `orchestrate.py` phase records.

**Spec:** `docs/superpowers/specs/2026-10-17-fiftybox-execute-spec-driven-design.md`

## Global Constraints

- The session running the skill does not write project source or test files, does not judge diffs, does not rewrite or re-split the plan, and does not pick a stronger model by task difficulty.
- One `implement` process per run. No per-task detached calls and no parallelism. `parallelGroup` is not added to orchestrate.
- No flags: `pi` / `zai-coding` / `glm-5.3`. `--provider` only: that provider's existing default model (`commandcode` → `meta/muse-spark-1.2-contributor`, `codex-write` → `gpt-5.6-luna`, `grok` → `grok-4.6`, `pi` and `zai-coding` → `glm-5.3`). `--model` only: `pi` / `zai-coding` / that model. Both flags: current Model Resolution. Never rewrite a named provider into the glm pair.
- A valid `tasks[]` JSON block in the plan is copied verbatim to `task-batches.md`. Otherwise that file is not created and the whole plan is one implement. The session does not repair the JSON.
- `no_changes` (exit 3 or phase status `no_changes`) and a failed task inside the list do not proceed to `complete` or `deploy`.
- Do not change `opus-plan`, `fiftybox-local`, `diff_review.py`, or `lane_priority` schema. Do not delete `diff_review.py`.
- Without `--skip-verification`, `review-test` still runs the test command and a failing command still blocks `complete`.
- Do not satisfy the gate with `--test-command true`.
- Irreversible changes get no extra pause. The skill does not revert.
- Repo files are canonical. After each code or skill edit, the installed copy must match: `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py` and `~/.claude/skills/fiftybox-execute/SKILL.md` (the vibeproxy path is the same directory).
- SKILL.md `description` states when to use the skill, not the step order.

## Review Focus

- A package whose `npm test` fails must still fail `review-test` when `--skip-verification` is absent. Task 1 pins this.
- The same package must not execute that script when `--skip-verification` is present, and the commit line must not say tests passed. Task 1 pins this.
- SKILL.md must not bring back Red-phase test writing, `lane_priority`, or `diff_review.py`. Task 2 pins this.
- `--provider commandcode` with no model must stay on `meta/muse-spark-1.2-contributor`, not `glm-5.3`. Task 2 pins this.
- `no_changes` must be written as a stop before `complete` and `deploy`. Task 2 pins this.

## File Structure

- Modify `skills/fiftybox-orchestration/scripts/orchestrate.py`: parse `--skip-verification`; short-circuit `phase_review_test`; add `review_test_commit_line` and use it in `phase_complete` only.
- Modify `skills/fiftybox-orchestration/tests/test_orchestrate.py`: tests for the flag, the unchanged failure path, and the commit line.
- Modify `skills/fiftybox-execute/SKILL.md`: spec-driven workflow.
- Create `skills/fiftybox-execute/tests/test_skill_contract.py`: required and forbidden skill text.
- Install copies of the two runtime files, not the tests.

---

### Task 1: Skip verification without lying that tests passed

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py` (`parse_args`, `phase_review_test`, `phase_complete` commit message)
- Test: `skills/fiftybox-orchestration/tests/test_orchestrate.py`

**Interfaces:**
- Consumes: existing `phase_record`, `ensure_summary`, `write_json`, `parse_args`
- Produces: CLI flag `--skip-verification` (`args.skip_verification: bool`, default `False`). On that flag, `phase_review_test` writes `summary["phases"]["review_test"]` with `status="success"` and `verificationSkipped=True`, returns `0`, and does not call `detect_test_command`, `run_test_command`, or `codex_exec`. `review_test_commit_line(review_phase: dict) -> str` returns the exact skipped line or the existing tested line.

- [ ] **Step 1: Write the failing tests**

Add these tests to `skills/fiftybox-orchestration/tests/test_orchestrate.py`. They must fail before the implementation because `skip_verification` and `review_test_commit_line` do not exist.

```python
def _review_summary(artifact: Path, worktree: Path) -> None:
    (artifact / "summary.json").write_text(
        json.dumps({"worktree": str(worktree), "phases": {"implement": {"status": "success"}}}),
        encoding="utf-8",
    )


def test_skip_verification_defaults_false():
    args = orchestrate.parse_args(
        ["--phase", "review-test", "--task", "t", "--artifact-dir", "/tmp/x"]
    )
    assert args.skip_verification is False


def test_review_test_without_skip_still_fails_when_tests_fail(tmp_path):
    artifact = tmp_path / "artifact"
    worktree = tmp_path / "work"
    artifact.mkdir()
    worktree.mkdir()
    _review_summary(artifact, worktree)
    args = orchestrate.parse_args([
        "--phase", "review-test", "--task", "t",
        "--artifact-dir", str(artifact),
        "--test-command", "false",
        "--skip-codex-review",
    ])
    code = orchestrate.phase_review_test(tmp_path, artifact, args)
    summary = json.loads((artifact / "summary.json").read_text(encoding="utf-8"))
    phase = summary["phases"]["review_test"]
    assert code != 0
    assert phase["status"] == "test_failed"
    assert phase.get("verificationSkipped") is not True


def test_skip_verification_does_not_run_detected_tests(tmp_path):
    artifact = tmp_path / "artifact"
    worktree = tmp_path / "work"
    artifact.mkdir()
    worktree.mkdir()
    (worktree / "package.json").write_text(
        json.dumps({"scripts": {"test": "exit 1"}}), encoding="utf-8"
    )
    _review_summary(artifact, worktree)
    args = orchestrate.parse_args([
        "--phase", "review-test", "--task", "t",
        "--artifact-dir", str(artifact),
        "--skip-verification",
    ])
    with patch("orchestrate.run_test_command") as run_tests, \
         patch("orchestrate.codex_exec") as codex, \
         patch("orchestrate.detect_test_command") as detect:
        code = orchestrate.phase_review_test(tmp_path, artifact, args)
    run_tests.assert_not_called()
    codex.assert_not_called()
    detect.assert_not_called()
    summary = json.loads((artifact / "summary.json").read_text(encoding="utf-8"))
    phase = summary["phases"]["review_test"]
    assert code == 0
    assert phase["status"] == "success"
    assert phase["verificationSkipped"] is True
    assert not (artifact / "codex-review.md").exists()


def test_commit_line_skips_claim_when_verification_skipped():
    assert orchestrate.review_test_commit_line({"verificationSkipped": True, "testCommand": "npm test"}) == (
        "Tested: verification skipped; the user accepts after deploy"
    )


def test_commit_line_keeps_test_claim_otherwise():
    assert orchestrate.review_test_commit_line({"testCommand": "npm test"}) == (
        "Tested: Phase 7 review-test passed via npm test"
    )
    assert orchestrate.review_test_commit_line({}) == (
        "Tested: Phase 7 review-test passed via review gate"
    )
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `python3 -m pytest skills/fiftybox-orchestration/tests/test_orchestrate.py::test_skip_verification_defaults_false skills/fiftybox-orchestration/tests/test_orchestrate.py::test_review_test_without_skip_still_fails_when_tests_fail skills/fiftybox-orchestration/tests/test_orchestrate.py::test_skip_verification_does_not_run_detected_tests skills/fiftybox-orchestration/tests/test_orchestrate.py::test_commit_line_skips_claim_when_verification_skipped skills/fiftybox-orchestration/tests/test_orchestrate.py::test_commit_line_keeps_test_claim_otherwise -v`

Expected: FAIL because `skip_verification` or `review_test_commit_line` is missing. The no-flag failure test may also fail until `phase_review_test` is unchanged and import works; if that one passes already, leave it as the regression pin.

- [ ] **Step 3: Implement the flag and the commit line**

In `parse_args`, add `--skip-verification` as `store_true`, default false. Help text: skip the test command and the reviewer in `review-test`, record `review_test` success with `verificationSkipped`, and do not claim tests passed.

Add `review_test_commit_line(review_phase: dict) -> str` next to `phase_complete`. Exact returns are the two strings in the tests above. `verificationSkipped` truthy selects the skipped line. Otherwise use `testCommand` or `review gate`, matching the current f-string.

At the start of `phase_review_test`, after `logger.start` and before `detect_test_command`: if `args.skip_verification` and not `args.dry_run`, write the success phase record with `verificationSkipped=True`, do not call `detect_test_command`, `run_test_command`, or `codex_exec`, do not write `codex-review.md`, `write_json` the summary, print the usual success JSON, and return `0`. Dry-run keeps the existing dry-run path.

In `phase_complete`, replace only the `Tested:` line with `review_test_commit_line(summary.get("phases", {}).get("review_test", {}))`. Do not change `phase_pi_complete`. Do not change the `status != "success"` block.

- [ ] **Step 4: Run the tests and confirm they pass**

Run the same pytest command as Step 2.

Expected: PASS, 5 tests.

- [ ] **Step 5: Copy the script to the installed path and commit the repo files**

```bash
cp skills/fiftybox-orchestration/scripts/orchestrate.py \
  ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py
diff -q skills/fiftybox-orchestration/scripts/orchestrate.py \
  ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py
git add skills/fiftybox-orchestration/scripts/orchestrate.py \
  skills/fiftybox-orchestration/tests/test_orchestrate.py
git commit -m "$(cat <<'EOF'
feat(orchestrate): skip verification without claiming tests passed

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

Expected: `diff -q` prints nothing and exits 0.

---

### Task 2: Rewrite fiftybox-execute as the spec courier

**Files:**
- Modify: `skills/fiftybox-execute/SKILL.md`
- Create: `skills/fiftybox-execute/tests/test_skill_contract.py`

**Interfaces:**
- Consumes: `--skip-verification` from Task 1. The skill calls it on `--phase review-test` and does not pass `--test-command true`.
- Produces: the skill text the session loads. No new Python API.

- [ ] **Step 1: Write the failing contract test**

Create `skills/fiftybox-execute/tests/test_skill_contract.py`:

```python
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"

REQUIRED = [
    "Use when a finished plan already exists and should be implemented and deployed by one subscription model. Also when the user invokes /fiftybox-execute.",
    "--skip-verification",
    "glm-5.3",
    "meta/muse-spark-1.2-contributor",
    "gpt-5.6-luna",
    "grok-4.6",
    "--model만 주면 pi / zai-coding / 그 모델이다.",
    "no_changes이면 complete와 deploy로 가지 않는다.",
    "task-batches.md",
    "implement.out",
    "구현 프로세스는 하나다",
    "세션은 구현 파일을 쓰지 않는다",
    "세션은 테스트 파일을 만들지 않는다",
    "diff를 읽고 판정하지 않는다",
    "요약하지 않는다",
    "다른 레인으로 넘어가지 않는다",
    "다른 모델을 해결책으로 제시하지 않는다",
    "이 스킬은 되돌리지 않는다",
    "되돌리기 어려운 변경도 따로 멈추지 않는다",
    "코드가 계획과 맞다는 문장은 넣지 않는다",
    "~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py",
    "--phase deploy",
    "미리 물어보고 멈추지 않는다",
    "incomplete_commit",
    "산문에 «parallel»이라고 적혀 있어도 무시한다.",
    "그냥 배포만",
]

FORBIDDEN = [
    "Claude가 실패하는 테스트 작성",
    "lane_priority",
    "diff_review.py",
    "implement-task-N.out",
    "--test-command true",
]


def test_skill_contains_the_spec_contract():
    text = SKILL.read_text(encoding="utf-8")
    missing = [item for item in REQUIRED if item not in text]
    assert missing == []


def test_skill_does_not_restore_the_old_loop():
    text = SKILL.read_text(encoding="utf-8")
    present = [item for item in FORBIDDEN if item in text]
    assert present == []


def test_review_test_invocation_skips_verification():
    text = SKILL.read_text(encoding="utf-8")
    blocks = re.findall(r"--phase review-test\b.{0,400}", text, re.S)
    assert blocks, "review-test command missing"
    assert all("--skip-verification" in block for block in blocks)


def test_commandcode_default_is_not_glm():
    text = SKILL.read_text(encoding="utf-8")
    assert "commandcode" in text
    window = text[text.index("commandcode"): text.index("commandcode") + 180]
    assert "meta/muse-spark-1.2-contributor" in window
    assert "glm-5.3" not in window
```

- [ ] **Step 2: Run the contract test and confirm it fails**

Run: `python3 -m pytest skills/fiftybox-execute/tests/test_skill_contract.py -v`

Expected: FAIL. The current skill still contains `Claude가 실패하는 테스트 작성` and `lane_priority`.

- [ ] **Step 3: Rewrite `SKILL.md` to the spec**

Replace the workflow so a reader who follows only this file does what the spec says. Keep the YAML `name: fiftybox-execute`. Set `description` to the first `REQUIRED` string and nothing else about steps. Use «세션» for the orchestrator, not «Claude» as a pinned model. Include every `REQUIRED` sentence verbatim. The first literal `commandcode` in the file must sit within 180 characters of `meta/muse-spark-1.2-contributor`, and that window must not contain `glm-5.3`. Include the single implement command (`implement.out`, `--skip-verify`), the verbatim `task-batches.md` copy rule, the `review-test` command with `--skip-verification`, complete then deploy then cleanup with no confirmation pause, deploy-only, the failure table, and the safety contract. Do not document `diff_review.py`, `lane_priority`, or Red-phase test writing. Do not tell the session to write tests or judge diffs.

- [ ] **Step 4: Run the contract test and confirm it passes**

Run: `python3 -m pytest skills/fiftybox-execute/tests/test_skill_contract.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 5: Copy the skill to the installed path and commit the repo files**

```bash
cp skills/fiftybox-execute/SKILL.md ~/.claude/skills/fiftybox-execute/SKILL.md
diff -q skills/fiftybox-execute/SKILL.md ~/.claude/skills/fiftybox-execute/SKILL.md
git add skills/fiftybox-execute/SKILL.md skills/fiftybox-execute/tests/test_skill_contract.py
git commit -m "$(cat <<'EOF'
feat(fiftybox-execute): carry a finished plan through deploy

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

Expected: `diff -q` prints nothing and exits 0.
