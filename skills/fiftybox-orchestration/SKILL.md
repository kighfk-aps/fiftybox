---
name: fiftybox-orchestration
description: Multi-agent orchestration harness with TDD. Explores via Pi CLI, clarifies intent, designs architecture, verifies with Codex, Claude writes failing tests, Pi CLI implements in parallel to pass them, Claude reviews, then commits, merges, pushes, and cleans up. Use when user invokes /fiftybox-orchestration or wants the full agent pipeline.
---

# Orchestrate Harness

## Overview

Drive a full development lifecycle through Pi CLI, Claude Code, and Codex in an isolated git worktree with TDD discipline.

**Core loop:** Claude writes failing tests (Red) → Pi CLI implements to pass them in parallel (Green) → Claude reviews (Refactor gate)

Every phase writes artifacts under `.omx/artifacts/orchestrate/<timestamp>/`; failures stop with a concrete report and recommended choices, except the single automatic Phase 5 retry after a Phase 6 failure.

## Invocation

User runs:

```bash
/fiftybox-orchestration "<task description>"
```

The task description must be passed unchanged to every helper phase.

## Interop Contract

When orchestrate needs to communicate with OMX (oh-my-codex) team workers:

1. **Never use legacy `team_*` MCP tools.** They are hard-deprecated and return `deprecated_cli_only`.
2. **Never use `interop_send_omx_message` without explicit env flags.** The direct bridge requires `OMX_OMC_INTEROP_ENABLED=1`, `OMC_INTEROP_TOOLS_ENABLED=1`, and `OMX_OMC_INTEROP_MODE=active` — all off by default.
3. **Use CLI interop for team mutations:** `omx team api <operation> --input '<json>' --json`
4. **Read-only interop tools** (`interop_read_omx_messages`, `interop_read_omx_tasks`, `interop_list_omx_teams`) work without the direct bridge flag and are safe to use for observation.

If a reject error contains `Direct OMX mailbox writes are disabled` — the direct bridge flags are missing.
If a reject error contains `deprecated_cli_only` — a legacy MCP path was attempted.
If interop tools are not visible at all — `OMC_INTEROP_TOOLS_ENABLED=1` is not set.

## Phase 0: SETUP

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase setup --task "<task>" --cwd "$(pwd)"
```

Read the JSON output and keep `artifactDir` and `worktree` for later phases. If setup fails, report the failure and stop.

### Auto-resume (optional)

If the user invoked `/fiftybox-orchestration --auto-resume "<task>"`, pass `--auto-resume`
to the setup command:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase setup --task "<task>" --cwd "$(pwd)" --auto-resume
```

This writes `<artifactDir>/resume-state.json` and spawns a detached
`orchestrate_watcher.py` daemon. If the Claude Code 5h usage limit interrupts
the run, the watcher waits for the window to reopen and relaunches
`/orchestrate --resume <artifactDir>` automatically. The daemon is killed in
Phase 8 CLEANUP.

## Checkpointing (auto-resume only)

When auto-resume is armed, every helper phase call refreshes
`resume-state.json` (heartbeat + next phase) automatically — no extra action is
required. The heartbeat tells the watcher the session is still alive; a stale
heartbeat plus a usage-limited probe is what triggers a relaunch.

## Phase 1: EXPLORE

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase explore --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

Exploration is read-only and runs on the lightweight `deepseek-v4-flash`
model by default (~30s on a real repo) instead of the heavy
`deepseek-v4-pro` (~290s, which routinely hit the timeout). Override with
`--explore-model`/`--explore-timeout` only if exploration quality is
insufficient.

On success, read `<artifactDir>/explore-report.md`.

## Phase 2: ROUTE + CLARIFY

### 2a. Complexity Assessment

Read `<artifactDir>/explore-report.md`. Apply the rubric below — if **2 or more** criteria are met, the task is **complex**:

- 5 or more files will be affected
- A new subsystem or module is being created from scratch
- Security, authentication, or permissions are involved
- Breaking changes to public interfaces or APIs
- Cross-cutting concerns span multiple layers (data flow, error handling, logging)
- Existing patterns are unclear or conflicting in the explore report

Write `<artifactDir>/route-decision.md`:

```markdown
## Route Decision

**Route:** [A or B]
**Criteria matched:** [list matched criteria, or "none — default Route B"]
**Reasoning:** [1–2 sentences]
```

### 2b. Routing

**If simple (0–1 criteria matched) → Route B:** Proceed directly to the Route B section below without notifying the user.

**If complex (2+ criteria matched) → ask the user:**

```
이 태스크는 복잡도가 높아 보입니다.
근거: <matched criteria, comma-separated>

Opus 풀모드(Phase 2 질문 설계 + 의도 합성 + 설계)로 전환할까요?
1. 예 — Opus 풀모드 (Route A, 토큰 ~3x)
2. 아니오 — 기본 모드 유지 (Route B)
```

Wait for user response. 1 → Route A. 2 → Route B.

---

### Route B (Simple / Default)

Using `explore-report.md`, clarify intent with the user:

- Ask one question at a time.
- Prefer multiple choice when possible.
- Focus on scope, constraints, success criteria, and edge cases.
- Stop when ambiguity is low enough or the user says enough.

Write `<artifactDir>/intent-summary.md` with:

- agreed objective
- in scope
- out of scope
- constraints
- success criteria
- non-goals

Write `<artifactDir>/logs/phase-2-clarify.log`.

---

### Route A (Complex / Opus Full Mode)

**Step 1 — Opus generates clarifying questions:**

```
Agent({
  model: "opus",
  description: "Generate clarifying questions",
  prompt: "Task: <task>\n\nRead <artifactDir>/explore-report.md.\n\nGenerate 3–6 prioritized clarifying questions. Focus on scope boundaries, architectural decisions, constraints, and edge cases. Prefer multiple-choice questions where possible.\n\nWrite to <artifactDir>/questions.md:\n\n## Clarifying Questions\n1. <question> (options: A / B / C if applicable)\n2. ...\n"
})
```

**Step 2 — Sonnet relays questions to user:**

Read `<artifactDir>/questions.md`. Ask each question to the user one at a time. Collect answers.

Write `<artifactDir>/qa-answers.md`:

```markdown
## Q&A Answers

**Q1:** <question text>
**A:** <user answer>

**Q2:** ...
```

**Step 3 — Opus synthesizes intent summary:**

```
Agent({
  model: "opus",
  description: "Synthesize intent summary from Q&A",
  prompt: "Task: <task>\n\nRead:\n- <artifactDir>/explore-report.md\n- <artifactDir>/qa-answers.md\n\nWrite <artifactDir>/intent-summary.md with these sections:\n- agreed objective\n- in scope\n- out of scope\n- constraints\n- success criteria\n- non-goals\n"
})
```

Write `<artifactDir>/logs/phase-2-clarify.log`.

## Phase 3: DESIGN

Delegate to an Opus sub-agent:

```
Agent({
  model: "opus",
  description: "Write architecture design",
  prompt: "Task: <task>\n\nRead:\n- <artifactDir>/explore-report.md\n- <artifactDir>/intent-summary.md\n\nWrite <artifactDir>/design.md containing:\n\n## Architecture Overview\n[2–4 paragraph description of the overall approach]\n\n## Components and Responsibilities\n[List each component with its single responsibility]\n\n## Data Flow\n[How data moves through the system]\n\n## File Changes\n[Exact file paths to create or modify, with one-line description of each]\n\n## Interface Contracts\n[Function signatures, types, or API shapes that cross component boundaries]\n\n## Error Handling Approach\n[How errors propagate and are surfaced]\n\n## Verification Plan\n[How to verify the implementation is correct — test cases, commands, expected output]\n"
})
```

After the agent completes, write `<artifactDir>/logs/phase-3-design.log`.

## Phase 4: VERIFY-DESIGN

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

The helper invokes Codex with a read-only design review prompt, writes `codex-design-review.md`, and requires a first-line `APPROVED:` or `REJECTED:` verdict.

The Codex design review is **advisory**. After running, read `codex-design-review.md`. If the verdict is REJECTED or UNCLEAR:
- Summarize the specific concerns for the user (1-3 bullet points)
- Proceed to the next phase by default
- Only stop and ask the user if the concerns indicate a fundamental design flaw (e.g., security vulnerability, data loss risk, approach is technically infeasible)

## Phase 4.5: WRITE TESTS (Red)

**Claude writes failing tests** before any implementation begins. This defines the acceptance criteria as executable code.

### Task Decomposition

Analyze `design.md` and extract discrete implementation tasks:

1. **Extract tasks** — parse the design into atomic implementation units
2. **Map dependencies** — identify which tasks depend on others (shared files, function calls, data flow)
3. **Build execution batches** — group independent tasks into parallel batches

```
Batch 1: [Task A, Task B, Task C]  ← no overlap, run in parallel
Batch 2: [Task D, Task E]          ← depend on Batch 1, run in parallel with each other
Batch 3: [Task F]                  ← depends on Batch 2, run alone
```

**Independence criteria** — two tasks are independent when they:
- Touch different files (no shared file edits)
- Have no data/function dependency between them
- Can be tested in isolation

Write the decomposition to `<artifactDir>/task-batches.md`.

### task-batches.md JSON Block

At the end of `task-batches.md`, embed a machine-readable JSON block that lists every
implementation task in document order (batches flattened into a single sequential
list — the harness runs them one at a time, not in parallel):

```json
{
  "tasks": [
    {
      "name": "Task A",
      "description": "Full task description from the batch breakdown",
      "files": ["src/foo.py", "src/bar.py"]
    },
    {
      "name": "Task B",
      "description": "Full task description from the batch breakdown",
      "files": ["tests/test_foo.py"]
    }
  ]
}
```

- `name` — short label for the task (required)
- `description` — full task text including what to implement (required)
- `files` — list of file paths this task owns; only these may be modified (empty list = no file constraint)
- Tasks are executed sequentially in the order listed, regardless of batch grouping in the Markdown above
- If the design has only a single task or all tasks are tightly coupled, either use a single-entry list for sequential execution or omit the JSON block entirely to fall back to single-call mode

### Test Writing

For each task, Claude directly writes test files:

1. **Analyze the task spec** — extract expected behavior, inputs, outputs, edge cases
2. **Determine test location** — follow project conventions (e.g., `tests/`, `__tests__/`, `*_test.py`)
3. **Write test files** — using the project's test framework

**Test writing rules:**
- Test behavior, not implementation — tests should not assume internal structure
- Cover the happy path, edge cases, and error cases from the spec
- Each task's tests must be runnable independently
- Use descriptive test names that read as acceptance criteria
- Import/reference functions and classes that **don't exist yet** — they will be created by Pi CLI

Write tests to the actual project test directory (inside the worktree) AND save copies to `<artifactDir>/tests/`.

Save a test manifest to `<artifactDir>/test-manifest.md`:

```markdown
## Test Manifest

### Task A
- File: `tests/test_feature_a.py`
- Tests: 5 (3 happy path, 1 edge case, 1 error case)
- Acceptance criteria covered: [list]

### Task B
- File: `tests/test_feature_b.py`
- Tests: 3 (2 happy path, 1 edge case)
- Acceptance criteria covered: [list]
```

**Verify tests fail (Red):**

```bash
<project test command> <test files>
```

If tests pass before implementation, they're testing nothing useful. Rewrite them.

## Phase 5: IMPLEMENT (Green)

### Parallel Mode

For each batch, dispatch all tasks simultaneously using the Agent tool:

```
For each task in current batch:
  Agent({
    description: "Implement: <task name>",
    prompt: <implementer prompt with task context + test file content>,
    run_in_background: true
  })
```

Each agent runs its own Pi CLI instance:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase implement --task "<specific task description>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --model deepseek-v4-pro
```

**Agent prompt must include:**
- Full task description (paste the text, not a file path)
- Relevant context from the design document
- Which files this task should touch
- Boundaries: files this agent must NOT modify (owned by sibling tasks)
- **The full content of the test file(s) for this task**
- **Explicit instruction: "Make these tests pass. Do not modify the test files. Run the tests after implementation to verify."**

**Wait for all agents in the batch to complete before proceeding.**

### Sequential Mode

When parallelism is not applicable (single task or tightly coupled):

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --model deepseek-v4-pro
```

The Pi CLI agent receives the test files and must make them pass without modifying them.

### File Ownership (parallel only)

Each task in a parallel batch owns specific files. Agents must:
- Only modify files listed in their task specification
- Treat all other files as read-only context
- Report immediately if they need to touch a file outside their ownership

Pi CLI must edit only the worktree and must not commit, push, deploy, reset, or run destructive git operations.

On any agent failure, report and present choices:
1. Retry that task with feedback
2. Abort the batch

## Phase 5.5: CLAUDE REVIEW GATE

> **Note:** This Claude Review Gate is the primary blocking check for implementation quality. Codex (Phase 6) provides a secondary advisory opinion and does not block the pipeline.

After each batch (or single implementation) completes, Claude performs a three-stage review:

### Stage 1: Test Results (Green Check)

- Run all tests written in Phase 4.5 for this batch
- Every test must pass — if any fail, dispatch a fix agent with the failure output
- **Pi CLI must not have modified test files** — if it did, revert test changes and re-run

### Stage 2: Spec Compliance

For each completed task:
- Read the actual code changes (git diff or file reads)
- Compare against the task specification line by line
- Check for missing requirements, extra work, or misunderstandings

### Stage 3: Integration Check (parallel only)

Since parallel tasks ran independently:
- Verify no conflicting edits (merge conflicts, duplicate definitions)
- Check cross-task interfaces match (function signatures, shared types)
- Ensure no accidental coupling was introduced

**If issues found:**
1. Dispatch a fix agent for the specific task with the review findings
2. Re-run tests + re-review after fix
3. On second failure, escalate to user with choices

**If all clear:** proceed to next batch (repeat Phase 5 → 5.5) or to Phase 6 if all batches done.

## Phase 6: REVIEW + TEST

Run after all batches pass the Claude Review Gate:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase review-test --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

The helper runs the detected or provided test command, writes `test-results.md`, asks Codex for a read-only implementation review, writes `codex-review.md`, and requires an `APPROVED:` verdict.

**If tests fail** (non-zero exit code): automatically retry the failing task's Phase 5 once with the test failure output as feedback:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase implement --task "<failing task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --model deepseek-v4-pro \
  --is-retry --feedback "<test failure output>"

python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase review-test --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --is-retry
```

On second failure, stop and report choices:

1. Manual fix then rerun Phase 6.
2. Return to Phase 3 design.
3. Commit as-is without merge.
4. Abort.

**If Codex review is REJECTED or UNCLEAR** (but tests pass): The Codex review is advisory. Read `codex-review.md` and:
- Summarize the specific concerns for the user (1-3 bullet points)
- Offer 3 choices:
  1. Apply Codex feedback and re-run Phase 5 (fix first)
  2. Proceed to Phase 7 as-is (ignore Codex feedback)
  3. Abort

## Phase 7: COMPLETE

Run only after Phase 6 status is `success`:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase complete --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

The helper commits in the task worktree with a Lore-style message, creates a detached merge worktree from `main`, merges the feature branch there, and pushes `HEAD:main`. It must not change the user's root checkout. On merge conflict or push failure, report the exact failure and preserve the merge worktree for inspection. Do not force or auto-abort conflicts.

## Phase 8: CLEANUP

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase cleanup --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

Report `summary.json` final status.

## Resume Mode

When invoked as `/fiftybox-orchestration --resume <artifactDir>` (typically by the
watcher), recover the in-flight run:

1. Read the next helper phase:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase resume --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

   Use the printed `task` and `nextPhase`. If `finalStatus` is `success` or
   `aborted`, the run is already done — report and stop.

2. **Verify Claude-side artifacts before running `nextPhase`.** The helper only
   tracks helper phases. Before running the returned phase, confirm the
   Claude-side steps that precede it exist in `<artifactDir>`:
   - before `verify_design`: `intent-summary.md`, `design.md`, and `route-decision.md`
   - before `implement`: `test-manifest.md` and the test files
   If a required artifact is missing, redo that Claude-side step first (clarify
   → design → write tests), then continue.

3. Resume the normal phase sequence from `nextPhase` and run to completion with
   full autonomy, pausing only where a phase genuinely needs the user (clarify
   Q&A, design approval).

## Failure Report Format

Use this shape:

```markdown
**Phase N (NAME) 실패**

**오류:** <specific error message>
**원인:** <brief analysis>

**추천 행동:**
1. <option 1>
2. <option 2>
3. <option 3>
```

### API Error vs. Rejection

When a Codex phase fails, check the JSON output for `"retriable": true`. If present, the failure is a transient API error (usage limit, auth error, rate limit), not a genuine design rejection or review failure. Present the user with:

1. Retry the same phase (the API issue may have resolved).
2. Skip Codex verification and proceed.
3. Abort.

Do NOT present "Revise design" as an option for API errors — the design was never reviewed.

### No Changes After Implementation

When Phase 5 (implement) returns `no_changes` with `"claimedSuccess": true` and `"outOfRepoHints": true`, the implementation agent made changes outside the git worktree. Present:

1. Accept the out-of-repo changes and skip commit/merge (task is filesystem-level, not code-level).
2. Retry with explicit instructions to write a script inside the worktree.
3. Abort.

## Safety Contract

- Never auto-recover from failures except the single Phase 5 retry on test failures from Phase 6.
- Never force push, force merge, reset hard, or delete branches with `-D`.
- Never push before Phase 7.
- Never allow Pi CLI implementation agents to commit or push.
- Keep implementation changes inside the generated worktree.
- Use artifact files for all handoffs because agents do not share session memory.
- **TDD-specific:** Pi CLI must NOT modify test files written by Claude in Phase 4.5.
- **TDD-specific:** If Pi CLI modifies tests, revert test changes before review.
- **Parallel-specific:** Agents must not edit files outside their ownership boundary.
- **Parallel-specific:** Claude reviews every batch before next batch starts.
- **Auto-resume:** the watcher only relaunches after a probe confirms the
  account was usage-limited and then reopened; a run that was never limited
  (e.g. the user quit) is never relaunched.
- **Auto-resume:** relaunches are bounded by `--max-relaunch` (default 3); on
  the cap the watcher writes `resume-give-up.md` and exits.
- **Auto-resume:** Phase 8 CLEANUP must kill the watcher (`kill_watcher`) so no
  daemon outlives a finished or aborted run.
- Never use legacy `team_*` MCP tools for OMX team mutations — they are hard-deprecated.
- Never call `interop_send_omx_message` unless all three bridge flags are confirmed active.
- For OMX team mutations, use `omx team api <operation> --input '<json>' --json` exclusively.
