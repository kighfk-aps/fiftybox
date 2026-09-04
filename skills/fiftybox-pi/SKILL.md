---
name: fiftybox-pi
description: Pi CLI-native multi-agent orchestration harness with TDD and tiered model routing. Explores on a cheap model, clarifies intent, designs on a top-tier session model (GLM/Grok), writes failing tests, implements on free lanes (OpenRouter free, NVIDIA NIM, Groq, Modal Qwen) via detached orchestrate.py dispatch, reviews, then commits, merges, pushes, and cleans up. No Claude Code required. Use when the user invokes /fiftybox-pi or /skill:fiftybox-pi.
disable-model-invocation: true
metadata:
  plan: docs/plans/2026-09-04-fiftybox-pi-port.md
---

# Fiftybox Pi Harness

## Overview

Drive a full development lifecycle entirely inside a Pi CLI session with tiered
model routing:

- **Top tier** (session model): explore analysis, intent clarification,
  architecture design, failing tests (Red), review gates.
  Preferred: `zai-coding/glm-5.3`, `xai-auth/grok-4.6`.
- **Cheap tier**: read-only exploration dispatch.
- **Free tier** (implement children): OpenRouter `:free`, NVIDIA NIM
  (`nvidia-nim`), Groq, Modal Qwen 3.8-27B, TurboFieldfare — in that priority
  order. **Never fall back to a paid provider for implementation.**

**Core loop:** session writes failing tests (Red) → free-lane children
implement to pass them (Green) → session reviews (gate) → commit, merge, push.

The state machine is the shared `orchestrate.py` engine (unchanged behavior,
same artifacts, same safety contract). Every phase writes artifacts under
`.omx/artifacts/orchestrate/<timestamp>/`; agents never share session memory —
artifact files are the only handoff medium.

## Invocation

User runs:

```
/skill:fiftybox-pi "<task description>"
```

Pass the task description unchanged to every helper phase.

### Session Preflight (mandatory, before Phase 0)

1. Run `echo "$PI_PROVIDER/$PI_MODEL"` (the bash tool injects both). If the
   ref is **not** in `session.preferred` from the config, warn in Korean and
   continue only after the user confirms:

   ```
   ⚠️ 현재 세션 모델이 top-tier가 아닙니다: <ref>
   설계·테스트 작성·리뷰 품질이 저하될 수 있습니다.
   계속할까요? 1) 계속  2) 모델 변경 후 재시작
   ```

2. Resolve config: `python3 skills/fiftybox-pi/scripts/fiftybox_config.py --print`
   (path: `$FIFTYBOX_PI_CONFIG` > `~/.pi/agent/fiftybox-config.json` > defaults;
   a `_config_error` key means the user file was malformed — report and continue
   on defaults).

3. Locate the engine and fail fast if missing:

   ```bash
   ORCHESTRATE="${FIFTYBOX_ORCHESTRATE:-$HOME/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py}"
   test -f "$ORCHESTRATE" || { echo "orchestrate.py not found at $ORCHESTRATE"; exit 1; }
   ```

**Rule: never rely on engine defaults.** `orchestrate.py --provider` defaults to
`opencode-go --model deepseek-v4-flash`, which no longer exists in this
machine's model catalog. Every dispatch in every phase passes an explicit
(agent, provider, model) triple.

### Lane Preflight (mandatory, before Phase 5; skip if the run has no implement phase)

Build the healthy free-lane list for this run — the smoke contract and the
healthy criterion are defined in `references/failure-classification.md`
(§3: a model is healthy only if the **tool-call smoke** passes; an "OK"
single-turn reply is not sufficient):

```bash
python3 skills/fiftybox-pi/scripts/fiftybox_config.py --print   # read lanes
# for each candidate (provider, model) in priority order, run the tool-call
# smoke via the structured runner (timeout 120s):
python3 skills/fiftybox-pi/scripts/pi_runner.py --provider <p> --model <m> \
  --tools read --timeout 120 \
  --task 'Use the read tool to read README.md (limit 3 lines). Output ONLY its first line.'
```

- Record results to `<artifactDir>/lane-health.json` (per model: ok, error
  class, duration). Only healthy models may receive implement dispatch.
- `openrouter-free`: the model list is discovered fresh each run — never trust
  a cached list; `:free` models rotate and 429-flap.
- `modal-qwen38`: run the Keychain wake-up ping first (t+75/120/150s checks,
  dispatch timeout 1800s), then smoke.
- `turbofieldfare` is last resort: parallelism 1, requires explicit user
  confirmation before dispatch.
- `groq`/`cerebras` are inactive unless their API key exists **and** preflight
  passes.
- If **zero** lanes are healthy → Emergency Stop (see below).

## Phase 0: SETUP

```bash
python3 "$ORCHESTRATE" --phase setup --task "<task>" --cwd "$(pwd)" \
  --agent-config "$HOME/.pi/agent/fiftybox-pi-agents"
```

`--agent-config` points the engine's agent registry at the pi-native location
(a directory containing `config.json`; falls back to the shared
`~/.claude/skills/orchestrate` when omitted). Read the JSON output and keep
`artifactDir` and `worktree`. On failure, report and stop. There is **no**
auto-resume watcher in fiftybox-pi; long interruptions recover through Resume
Mode only.

## Phase 1: EXPLORE

```bash
python3 "$ORCHESTRATE" --phase explore --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --explore-provider zai-coding --explore-model glm-5.3-flash
```

Read-only. Use the first healthy cheap-tier model from `explore.fallback`.
On success read `<artifactDir>/explore-report.md`.

## Phase 2: ROUTE + CLARIFY

### 2a. Complexity Assessment

Apply the rubric to `explore-report.md` — **2 or more** criteria = complex:

- 5 or more files affected
- A new subsystem or module from scratch
- Security, authentication, or permissions involved
- Breaking changes to public interfaces or APIs
- Cross-cutting concerns span multiple layers
- Existing patterns unclear or conflicting in the explore report

Write `<artifactDir>/route-decision.md` (Route, criteria matched, reasoning).

### 2b. Clarify (single session — no sub-agents in MVP)

Ask the user one question at a time (multiple choice when possible), covering
scope, constraints, success criteria, edge cases. If the ambiguity judgment is
uncertain, delegate question generation to a top-tier child via `pi_runner`
(`--provider zai-coding --model glm-5.3 --timeout 300`), then relay.

Write `<artifactDir>/intent-summary.md` (agreed objective, in scope, out of
scope, constraints, success criteria, non-goals) and
`<artifactDir>/logs/phase-2-clarify.log`.

## Phase 3: DESIGN

The session model writes `<artifactDir>/design.md` directly (session is
top-tier by preflight): Architecture Overview, Components and Responsibilities,
Data Flow, File Changes (exact paths), Interface Contracts, Error Handling
Approach, Verification Plan. Write `<artifactDir>/logs/phase-3-design.log`.

## Phase 4: VERIFY-DESIGN (skipped by default; opt-in cross-check)

Record an advisory pass so implement can proceed:

```bash
python3 "$ORCHESTRATE" --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

For a genuinely complex architecture run an opt-in **cross-model** review with
a different top-tier family than the session model (session GLM → reviewer
Grok and vice versa), advisory unless `--strict-review`:

```bash
python3 "$ORCHESTRATE" --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --design-review-agent pi --design-review-provider xai-auth --design-review-model grok-4.6
```

REJECTED/UNCLEAR verdicts are surfaced to the user but do not stop the
pipeline (unless `--strict-review`).

## Phase 4.5: WRITE TESTS (Red) — session model, non-delegable

Decompose `design.md` into atomic tasks, map dependencies, build batches
(independence = different files ∧ no data dependency ∧ isolatable). Write
`<artifactDir>/task-batches.md` ending with the machine-readable JSON block
(`tasks[]` of `name`/`description`/`files` ownership) — tasks execute
sequentially in listed order.

Write failing tests per task into the worktree's project test directory AND
copy to `<artifactDir>/tests/`; write `<artifactDir>/test-manifest.md`.
Run the project test command and **verify Red** (tests must fail). Tests that
pass before implementation are testing nothing — rewrite them.

The session model writes tests itself. Do not delegate test authorship to a
free-lane child.

## Phase 5: IMPLEMENT (Green) — free lanes, detached, sequential

For each task in `task-batches.md` order:

1. Pick the next model from the healthy lane list (rotate distinct models
   across tasks in a round, per `references/routing.md`).
2. Dispatch detached (never foreground — a single child can legally run for
   many minutes and the session must stay responsive):

   ```bash
   nohup python3 "$ORCHESTRATE" --phase implement \
     --task "<full task description>" --cwd "$(pwd)" \
     --artifact-dir "<artifactDir>" \
     --implement-agent pi --provider <provider> --model <model> \
     > "<artifactDir>/implement-task-<N>.out" 2>&1 &
   echo $!   # poll the .out file for the EXIT_CODE= sentinel
   ```

   For the `modal-qwen38` lane use `--implement-agent piqwen`.
3. The child prompt must include: the full task text (paste, not a path),
   relevant design context, owned files, forbidden files (sibling ownership),
   the full content of the task's test files, and this instruction verbatim:
   "Make these tests pass. Do not modify the test files. Run the tests after
   implementation to verify."
4. On failure classification (read `.out` + `references/failure-classification.md`):
   `model`/`model_busy` → swap within lane (does not consume the retry
   budget); `timeout`/`unknown` → one task-local retry; `auth`/`window`/
   `credit` → close the lane, never swap models, continue with the next lane.

### Emergency Stop (all free lanes exhausted)

Never escalate to paid automatically. Report and present:

```
모든 무료 구현 레인이 소진되었습니다 (<models tried>).
1. 유료 모델로 1회만 구현 승인 (어떤 모델로 할지 지정)
2. 여기서 중단 (아티팩트 보존, Resume로 재개 가능)
3. 세션 top-tier 모델로 직접 구현 (비용 없음, 세션 토큰 소모)
```

Wait for the user's choice. Option 1 is a one-shot approval scoped to the
current task, never a config change.

## Phase 5.5: SESSION REVIEW GATE (blocking)

After each task (or batch): (1) run the task's tests — all green or dispatch a
fix child with the failure output; (2) read the actual diff and compare line
by line against the task spec; (3) verify the child did **not** modify test
files (`git diff --stat -- <test files>` must be empty — revert if it did);
(4) for parallel batches, check cross-task interfaces. Two fix failures →
escalate to the user.

## Phase 6: REVIEW + TEST (objective gate)

```bash
python3 "$ORCHESTRATE" --phase review-test --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

No LLM review runs here. On test failure, retry the failing task's Phase 5
**once** with `--is-retry --feedback "<test failure output>"`, then re-run
review-test with `--is-retry`. On second failure stop and present:
1. 수동 수정 후 Phase 6 재실행
2. Phase 3 설계로 회귀
3. 병합 없이 커밋만
4. 중단

Optional advisory diff review (top tier, different family preferred):

```bash
python3 skills/fiftybox-pi/scripts/diff_review_pi.py \
  --diff <task.diff> --spec <artifactDir>/design.md --test <test files>... \
  --task-name <task> --out <artifactDir>/reviews \
  --provider zai-coding --model glm-5.3 --audit <artifactDir>/audit.jsonl
```

Exit-code contract 2–6 and verdict routing (APPROVED/REVISE/BLOCKED/UNKNOWN)
match the original diff_review tooling; verdicts are advisory.

## Phase 7: COMPLETE

Only after Phase 6 `success`:

```bash
python3 "$ORCHESTRATE" --phase complete --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

The engine commits in the worktree, creates a detached merge worktree from
main, merges, and pushes `HEAD:main`. Never the user's root checkout. Merge
conflict or push failure → report exactly, preserve the merge worktree, no
force, no auto-abort.

## Phase 8: CLEANUP

```bash
python3 "$ORCHESTRATE" --phase cleanup --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

Report `summary.json` final status. Include child-call statistics
(`lane-health.json`, dispatch count per model) in the final report.

## Resume Mode

`/skill:fiftybox-pi --resume <artifactDir>`: run `--phase resume`, verify the
session-side artifacts required by the returned phase exist (see
`references/phase-contract.md`), redo any missing session-side step, then
continue the sequence.

## Failure Report Format

```markdown
**Phase N (NAME) 실패**

**오류:** <specific error message>
**원인:** <scope classification + brief analysis>

**추천 행동:**
1. <option 1>
2. <option 2>
3. <option 3>
```

## Safety Contract

- Never auto-recover from failures except the single Phase 5 retry after a
  Phase 6 test failure.
- Never force push, force merge, reset hard, or delete branches with `-D`.
- Never push before Phase 7. Implement children are prompt-blocked from
  committing; the review gates catch violations after the fact.
- Keep implementation changes inside the generated worktree.
- The orchestrator (session) never writes implementation code; children never
  touch test files; parallel tasks never edit outside their ownership.
- Never dispatch implement to a paid provider (`neverPaidFallbackFromFree`);
  Emergency Stop option 1 is the only paid path and requires explicit approval.
- Never dispatch implement to a model that has not passed the tool-call smoke
  this run.
- Every dispatch carries an explicit (agent, provider, model) triple.
- Enforce runner wall-clock timeouts (`timeouts` in config) — pi's internal
  retry policy can stall a single child for many minutes.
