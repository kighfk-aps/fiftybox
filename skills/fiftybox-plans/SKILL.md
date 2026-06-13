---
name: fiftybox-plans
description: Fiftybox planning workflow for /fiftybox-plans. Use when the user wants to run the planning front half of /fiftybox-orchestration, review the produced plan, and save a final Markdown plan under a plans folder before implementation or resume handoff.
---

# fiftybox-plans

Create and review a Fiftybox implementation plan without starting implementation. Preserve compatibility with `/fiftybox-orchestration --resume <artifactDir>` by keeping all orchestration artifacts under `.omx/artifacts/orchestrate/<timestamp>/`, and also save the user-facing plan to `plans/YYYY-MM-DD-<task-slug>.md` in the current project.

## Invocation

```text
/fiftybox-plans "<task description>"
```

Pass the task description unchanged to every helper phase.

## Resolve The Helper Script

Use the first existing path:

1. `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`
2. `./skills/fiftybox-orchestration/scripts/orchestrate.py`

If neither exists, report that fiftybox-orchestration is not installed and stop.

## Phase 1: Setup

Run:

```bash
python3 <orchestrate.py> --phase setup --task "<task>" --cwd "$(pwd)"
```

Read the JSON output and keep `artifactDir` and `worktree`.

## Phase 2: Explore

Run:

```bash
python3 <orchestrate.py> --phase explore --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --explore-model deepseek-v4-flash
```

Read `<artifactDir>/explore-report.md`.

If exploration fails, retry once with `--explore-timeout 300`. If it still fails, write a short failure report with the exact error and preserve `artifactDir`.

## Phase 3: Clarify And Route

Use the complexity rubric from `/fiftybox-orchestration`:

- 5 or more files likely affected
- New subsystem or module
- Security, authentication, or permissions
- Breaking API or public interface change
- Cross-layer behavior
- Conflicting or unclear existing patterns

Write `<artifactDir>/route-decision.md`:

```markdown
## Route Decision

**Route:** [A or B]
**Criteria matched:** [list, or "none - default Route B"]
**Reasoning:** [1-2 sentences]
```

Ask only the minimum questions needed to make the plan executable. For straightforward tasks, proceed without questions and record assumptions in `<artifactDir>/intent-summary.md`.

Write `<artifactDir>/intent-summary.md`:

```markdown
## Intent Summary

**Agreed objective:** ...
**In scope:** ...
**Out of scope:** ...
**Constraints:** ...
**Success criteria:** ...
**Non-goals:** ...
```

## Phase 4: Design And Draft Plan

Run the existing orchestration design-plan phase:

```bash
python3 <orchestrate.py> --phase design-plan --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --claude-model claude-opus-4-6
```

This must produce at least:

- `<artifactDir>/design.md`
- `<artifactDir>/architecture.md`
- `<artifactDir>/plan.md`

If the phase fails, report the failure and preserve `artifactDir`.

## Phase 5: Review The Plan

Review the produced plan before publishing it. Prefer Codex CLI from the worktree:

```bash
codex exec --cd "<worktree>" --sandbox read-only --model gpt-5.4 \
  "Review <artifactDir>/plan.md against <artifactDir>/intent-summary.md, <artifactDir>/design.md, and <artifactDir>/explore-report.md. First line must be APPROVED, REVISE, or BLOCKED. Focus on missing steps, unsafe assumptions, test adequacy, and whether the plan is executable by a separate agent. Do not implement anything."
```

Save the review output to `<artifactDir>/codex-plan-review.md`.

Also run the existing design review for resume compatibility:

```bash
python3 <orchestrate.py> --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --codex-model gpt-5.4
```

If the plan review is `REVISE`, update `<artifactDir>/plan.md` using the review feedback, then run the plan review once more. If it is `BLOCKED`, stop with the failure report and the blocker.

## Phase 6: Save The Markdown Plan

Create `plans/` in the current project if missing.

Slug rules:

- lower-case the task
- replace non-alphanumeric runs with `-`
- trim leading/trailing `-`
- truncate to 50 characters

Save the final plan to:

```text
plans/YYYY-MM-DD-<task-slug>.md
```

The file must include:

```markdown
# <Task Title> Implementation Plan

> Source artifact: <artifactDir>
> Reviewed: <codex-plan-review.md verdict line>

## Goal
...

## Context
...

## Plan
...

## Verification
...

## Resume Handoff

Run: `/fiftybox-orchestration --resume <artifactDir>`
```

Keep `<artifactDir>/plan.md` as the orchestration-resume source of truth. The `plans/*.md` file is the human-facing copy.

## Completion Output

Report only:

- `artifactDir`
- saved plan path under `plans/`
- first line of `codex-plan-review.md`
- `/fiftybox-orchestration --resume <artifactDir>` handoff command

Do not start implementation unless the user explicitly asks for the resume handoff.

## Failure Report Format

```markdown
**Phase N (NAME) 실패**

**오류:** <specific error message>
**원인:** <brief analysis>
**보존된 artifactDir:** <artifactDir if available>

**추천 행동:**
1. <option 1>
2. <option 2>
3. <option 3>
```
