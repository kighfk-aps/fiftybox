---
name: fiftybox-execute
description: TDD execution pipeline — Claude writes tests, Pi CLI implements in parallel, Claude reviews. Use when user has already done design/planning and wants to hand off build+deploy to Pi CLI with test-first discipline.
---

# Fiftybox Execute

Skip exploration, clarification, and design phases — go straight to implementation and deployment using a TDD pipeline.

**Core loop:** Claude writes failing tests (Red) → Pi CLI implements to pass them (Green) → Claude reviews (Refactor gate)

**Parallel execution:** Independent tasks run in parallel via separate Pi CLI instances. Claude reviews each batch before proceeding to the next.

## Prerequisites

The user must provide:
1. **Task description** — what to build
2. **Design document** — either a file path or inline content

## Invocation

```
/fiftybox-execute "<task description>"
```

If no task is provided, ask for it.

## Workflow

### Step 1: Collect Design

Ask the user for the design document. Accept any of:

- A file path (e.g., `./design.md`, `./PRD.md`, `./plan.md`)
- Inline text in the conversation
- "Use current directory context" — read relevant files and summarize into a design

Write the design to `<artifactDir>/design.md`.

If the user also has an intent summary or scope document, write it to `<artifactDir>/intent-summary.md`. Otherwise, generate a minimal one from the design:

```markdown
## Objective
<extracted from design>

## In Scope
<extracted from design>

## Out of Scope
- (not specified)

## Constraints
<extracted from design>

## Success Criteria
<extracted from design>
```

### Step 2: Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<task>" --cwd "$(pwd)"
```

Read JSON output. Keep `artifactDir` and `worktree`.

Copy the design and intent files into the artifact directory.

### Step 3: Task Decomposition & Dependency Analysis

Before implementation, analyze the design document and extract discrete tasks:

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

Write the decomposition to `<artifactDir>/task-batches.md`:

```markdown
## Task Batches

### Batch 1 (parallel)
- Task A: <description> — files: [list]
- Task B: <description> — files: [list]

### Batch 2 (parallel, after Batch 1)
- Task D: <description> — files: [list], depends on: [Task A]

### Batch 3 (sequential, after Batch 2)
- Task F: <description> — files: [list], depends on: [Task D, Task E]
```

If the design has only a single task or all tasks are tightly coupled, skip parallelism and fall through to sequential mode (legacy behavior).

### Step 4: Claude Writes Tests (Red Phase)

**Claude directly writes failing tests for each task in the current batch.** This is the "Red" phase of TDD — tests define the acceptance criteria before any implementation exists.

For each task:

1. **Analyze the task spec** — extract expected behavior, inputs, outputs, edge cases
2. **Determine test location** — follow project conventions (e.g., `tests/`, `__tests__/`, `*_test.py`)
3. **Write test files** — using the project's test framework

**Test writing rules:**
- Test behavior, not implementation — tests should not assume internal structure
- Cover the happy path, edge cases, and error cases from the spec
- Each task's tests must be runnable independently
- Use descriptive test names that read as acceptance criteria
- Import/reference functions and classes that **don't exist yet** — they will be created by Pi CLI

**Write tests to `<artifactDir>/tests/` AND to the actual project test directory.**

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
# Run the tests — they MUST fail because implementation doesn't exist yet
<project test command> <test files>
```

If tests pass before implementation, they're testing nothing useful. Rewrite them.

### Step 5: Parallel Implement (Phase 5 — Green Phase)

For each batch, dispatch all tasks in the batch simultaneously using the Agent tool:

```
For each task in current batch:
  Agent({
    description: "Implement: <task name>",
    prompt: <implementer prompt with task context + test files>,
    run_in_background: true   // parallel execution
  })
```

Each agent runs its own Pi CLI instance:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<specific task description>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --provider cursor --model composer-2.5 --skip-verify
```

`--skip-verify` is required: fiftybox-execute does design/verification externally
and skips the orchestrate verify-design phase, so implement must not depend
on it.

**Agent prompt must include:**
- Full task description (not a file path — paste the text)
- Relevant context from the design document
- Which files this task should touch
- Boundaries: files this agent must NOT modify (owned by sibling tasks)
- **The full content of the test file(s) for this task** — paste the tests inline
- **Explicit instruction: "Make these tests pass. Do not modify the test files. Run the tests after implementation to verify."**

**Wait for all agents in the batch to complete before proceeding.**

On any agent failure, report and present choices:
1. Retry that task with feedback
2. Abort the batch

### Step 6: Claude Review Gate

After each batch completes, Claude (not a subagent) performs a three-stage review:

#### Stage 1: Test Results (Green Check)

- Run all tests written in Step 4 for this batch
- Every test must pass — if any fail, dispatch a fix agent with the failure output
- **Pi CLI must not have modified test files** — if it did, revert test changes and re-run

#### Stage 2: Spec Compliance

For each completed task in the batch:
- Read the actual code changes (git diff or file reads)
- Compare against the task specification line by line
- Check for missing requirements, extra work, or misunderstandings

#### Stage 3: Integration Check

Since parallel tasks ran independently:
- Verify no conflicting edits (merge conflicts, duplicate definitions)
- Check cross-task interfaces match (function signatures, shared types)
- Ensure no accidental coupling was introduced

**If issues found:**
1. Dispatch a fix agent for the specific task with the review findings
2. Re-run tests + re-review after fix
3. On second failure, escalate to user with choices

**If all clear:** proceed to next batch (repeat Steps 4-6) or to Phase 6 if all batches done.

### Step 7: Review + Test (Phase 6)

After all batches pass the Claude Review Gate:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

On first failure, **automatically retry** the failing task's Phase 5 once with Codex feedback:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<failing task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --provider cursor --model composer-2.5 --skip-verify \
  --is-retry --feedback "<codex feedback>"

python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --is-retry
```

On second failure, report and present choices:
1. Manual fix then rerun Phase 6
2. Commit as-is without merge
3. Abort

### Step 8: Complete (Phase 7)

Run only after Phase 7 succeeds:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

### Step 9: Deploy (Phase 7b)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --provider cursor --model composer-2.5
```

If the user specified a deploy command, pass `--deploy-command "<command>"`.

Skipped automatically if no deployment config is detected.

### Step 10: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

Report `summary.json` final status.

## Parallel Execution Rules

### Dispatch Rules

- **One Agent tool call per task** — each task gets its own isolated agent
- **All agents in a batch dispatched in a single message** — use multiple Agent tool calls to maximize parallelism
- **`run_in_background: true`** for all agents in a batch — don't block on individual completions
- **Never dispatch next batch until current batch passes review**

### File Ownership

Each task in a parallel batch owns specific files. Agents must:
- Only modify files listed in their task specification
- Treat all other files as read-only context
- Report immediately if they need to touch a file outside their ownership

### Conflict Resolution

If two agents in the same batch accidentally touch the same file:
1. Detect via `git diff` after batch completion
2. The task that owns the file keeps its changes
3. The other task's changes are re-applied by a fix agent

### When NOT to Parallelize

Fall back to sequential execution when:
- All tasks share the same files
- Task count is 1
- Tasks have strict linear dependencies (A→B→C with no branching)
- The design explicitly requires sequential execution

## Model Unavailable Error

Pi CLI 페이즈(implement, pi-deploy)가 실패하고 JSON에 `"model_unavailable": true`가 포함된 경우:

1. 사용자에게 다음 형식으로 표시한다:

```
[페이즈명] 모델 [triedModel]에 접근할 수 없습니다.
사유: <error 필드 요약 1줄>

현재 사용 가능한 모델:
1. <availableModels[0]>
2. <availableModels[1]>
...

어떤 모델로 재시도할까요? (번호 또는 "취소")
```

2. 사용자 응답 처리:
   - 번호 선택 → 해당 페이즈를 `--model <선택> --skip-verify`로 재실행
   - "취소" → 기존 실패 보고 흐름으로 진행 (Failure Report Format 참조)

3. `availableModels`가 빈 목록인 경우: "사용 가능한 모델이 없습니다. `pi --list-models <provider>`로 확인하세요." 메시지 표시 후 취소와 동일하게 처리한다.

## Failure Report Format

```markdown
**Batch N, Task M (NAME) 실패**

**오류:** <specific error message>
**원인:** <brief analysis>
**영향:** <impact on sibling tasks in batch, if any>

**추천 행동:**
1. <option 1>
2. <option 2>
3. <option 3>
```

## Safety Contract

Inherits from /fiftybox-orchestration:

- No direct file edits outside `.omx/artifacts/` while active
- No force push, force merge, reset hard, or `-D` branch delete
- No push before Phase 7
- Pi CLI must not commit or push
- Single auto-retry: per-task Phase 5→6 once only
- On failure: present choices, never silently recover
- **Parallel-specific:** agents must not edit files outside their ownership boundary
- **Parallel-specific:** Claude reviews every batch before next batch starts
- **TDD-specific:** Pi CLI must NOT modify test files written by Claude
- **TDD-specific:** if Pi CLI modifies tests, revert test changes before review

## Deploy-Only Mode

If the user says `/fiftybox-execute deploy` or asks to "just deploy":

1. Skip Steps 1-8 entirely
2. Ensure the current branch is up to date with main
3. Run Phase 7b (deploy) directly using the project root
4. No worktree or artifact setup needed for deploy-only

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --provider cursor --model composer-2.5
```

For deploy-only, create a minimal artifact dir and summary.json with `complete.status: "success"` so the deploy phase gate passes.

## Sequential Fallback

When parallelism is not applicable (single task, tightly coupled), the workflow collapses to:

1. Collect Design → 2. Setup → 3. Skip decomposition → 4. Claude writes tests → 5. Single Implement (must pass tests) → 6. Claude review gate → 7. Review+Test → 8. Complete → 9. Deploy → 10. Cleanup

The TDD cycle (Claude writes tests → Pi CLI implements → Claude verifies) always applies, even in sequential mode.
