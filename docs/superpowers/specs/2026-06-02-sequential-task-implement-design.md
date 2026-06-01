# Sequential Task Implementation Design

**Date:** 2026-06-02  
**Status:** Approved  
**Scope:** `skills/orchestrate/scripts/orchestrate.py` — `phase_implement()` only

---

## Problem

`phase_implement()` currently sends the entire design spec (12–14 KB) to Pi CLI in a single call. For tasks involving 5+ files, Pi CLI (`deepseek-v4-pro`) routinely exceeds the 600-second `--implementation-timeout`, causing the implement phase to fail and requiring manual intervention.

---

## Solution

When `task-batches.md` exists in the artifact directory, `phase_implement()` parses it into an ordered task list and runs Pi CLI once per task **sequentially**. Each Pi call receives a narrowed prompt scoped to that task's files. Without `task-batches.md`, the existing single-call behavior is preserved unchanged.

---

## Architecture

```
phase_implement() entry
  ↓
task-batches.md present in artifact_dir?
  ├─ YES → parse_task_batches() → [task1, task2, ...]
  │         for each task (sequential):
  │           build_task_prompt(task, design, intent)
  │           run Pi CLI  ← args.implementation_timeout per task
  │           on failure: stop loop, report which task failed
  │           on success: append changed files to running set
  │         write implement-log.md (aggregate)
  └─ NO  → existing single-call path (unchanged)
```

No changes to SKILL.md, argument interface, or any other phase.

---

## task-batches.md Parsing

Phase 4.5 writes task-batches.md in this format:

```markdown
## Batch 1
- Task A: <description>
  - Files: src/foo.py, src/bar.py
- Task B: <description>
  - Files: tests/test_foo.py
```

`parse_task_batches()` extracts tasks in document order (batches flattened into a sequential list). Each task entry captures:
- `name`: task label
- `description`: full task text
- `files`: list of owned file paths (empty list if not specified)

Parsing is best-effort with regex. If parsing yields zero tasks, fall back to single-call behavior and log a warning.

---

## Per-Task Prompt

Each Pi call receives:

```
## Design Specification
<full design.md content>

## Intent Summary
<intent-summary.md content>

## Current Task
<task name and description from task-batches.md>

## File Ownership
This task owns: <comma-separated file list>
Modify ONLY these files. All other files are read-only context.

## Constraints
- Edit workspace files directly to implement this task only.
- Do NOT implement other tasks in this prompt.
- Do NOT commit, push, deploy, reset, or run destructive git operations.
- If a required file does not yet exist, create it.

## Final Response
- List all changed/created files.
- State what verification you ran or why you could not run it.
```

`design.md` is included in full so Pi understands interface contracts between tasks.

---

## Artifact Output

| File | Contents |
|------|----------|
| `implement-log-task-{n}.md` | Pi stdout + changed files for task N |
| `implement-log.md` | Aggregate: all changed files across tasks + per-task status |
| `implement-prompt-task-{n}.md` | Prompt sent for task N (for debugging) |

Existing `implement-log.md` naming is preserved for downstream phases (review-test reads it).

---

## Failure Handling

- If any task's Pi call times out or returns non-zero: **stop the loop immediately**.
- Report which task failed (task name + index).
- Partial changes from completed tasks remain on disk (not reverted).
- `summary.json` records `"failed_task_index": N` so that a retry run can resume from the failed task rather than re-running all tasks.
- Return the same `fail_json` shape as the current implement phase so SKILL.md retry logic applies unchanged.

---

## Retry Resume

When `--is-retry` is set and `summary.json` contains `"failed_task_index": N`, the loop skips tasks 0…N-1 (already completed) and starts from task N. This prevents re-implementing files that were already successfully written.

---

## Timeout

Each task uses `args.implementation_timeout` (default 600s). A task touching 1–2 files should complete well within this window with `deepseek-v4-pro`.

---

## Backward Compatibility

- No `task-batches.md` → single-call path runs exactly as before.
- All CLI arguments unchanged.
- `--is-retry` and `--feedback` apply to the retry of the failed task only (not the whole batch).

---

## Out of Scope

- Parallel execution (future option; sequential is the target here).
- Per-task model selection.
- Reverting completed tasks on partial failure.
- Changes to any phase other than `phase_implement()`.
