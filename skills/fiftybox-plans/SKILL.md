---
name: fiftybox-plans
description: Token-efficient planning skill — Ollama/Gemma4 for codebase exploration, Claude Opus for architecture design, Codex GPT-5.5-high for review. Produces artifacts compatible with /orchestrate --resume. Use when you want to plan a task before implementing it, saving tokens on exploration.
---

# fiftybox-plans

## Overview

Token-efficient planning pipeline. Runs codebase exploration on a free model and reserves Claude Opus + Codex for the high-value design and planning phases. The output is a verified implementation plan and a set of orchestrate-compatible artifacts.

**Invocation:**
```
/fiftybox-plans "<task description>"
```

The task description is passed unchanged to every helper phase.

## Phase 1: SETUP

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase setup --task "<task>" --cwd "$(pwd)"
```

Read the JSON output. Keep `artifactDir` and `worktree` for all later phases. If setup fails, report the error and stop.

## Phase 2: EXPLORE

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase explore --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --provider ollama --explore-model gemma4
```

This calls Pi CLI with `--provider ollama --model gemma4` for free, read-only exploration.

On success, read `<artifactDir>/explore-report.md`.

**On timeout or failure**, report the error and offer:
1. Retry with a longer timeout: add `--explore-timeout 300`
2. Skip exploration and proceed with limited context (Claude reads repo directly)
3. Abort

## Phase 3: CLARIFY

Read `<artifactDir>/explore-report.md`. Apply the complexity rubric — if **2 or more** criteria are met, the task is **complex**:

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
**Criteria matched:** [list matched criteria, or "none — Route B"]
**Reasoning:** [1–2 sentences]
```

Then clarify intent with the user:

- Ask one question at a time
- Prefer multiple choice when possible
- Focus on scope, constraints, success criteria, and edge cases
- Stop when ambiguity is low enough or the user says enough

Write `<artifactDir>/intent-summary.md`:

```markdown
## Intent Summary

**Agreed objective:** [what we're building]
**In scope:** [explicit inclusions]
**Out of scope:** [explicit exclusions]
**Constraints:** [technical or business constraints]
**Success criteria:** [how we know it's done]
**Non-goals:** [things we're deliberately not doing]
```

## Phase 4: DESIGN

Delegate to an Opus sub-agent:

```
Agent({
  model: "opus",
  description: "Write architecture design",
  prompt: "Task: <task>\n\nRead:\n- <artifactDir>/explore-report.md\n- <artifactDir>/intent-summary.md\n\nWrite <artifactDir>/design.md containing:\n\n## Architecture Overview\n[2–4 paragraph description of the overall approach]\n\n## Components and Responsibilities\n[List each component with its single responsibility]\n\n## Data Flow\n[How data moves through the system]\n\n## File Changes\n[Exact file paths to create or modify, with one-line description of each]\n\n## Interface Contracts\n[Function signatures, types, or API shapes that cross component boundaries]\n\n## Error Handling Approach\n[How errors propagate and are surfaced]\n\n## Verification Plan\n[How to verify the implementation is correct — test cases, commands, expected output]\n"
})
```

**If the agent fails:** Report the error and offer:
1. Retry with the same context
2. Abort

## Phase 5: VERIFY DESIGN

Run:

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --codex-model gpt-5.5-high
```

The Codex design review is **advisory**. After running, read `<artifactDir>/codex-design-review.md`. If the verdict is REJECTED or UNCLEAR:
- Summarize the specific concerns for the user (1-3 bullet points)
- Proceed to Phase 6 by default
- Only stop and ask the user if the concerns indicate a fundamental flaw (security vulnerability, data loss risk, approach is technically infeasible)

**If Codex returns an API error (`"retriable": true`):** Offer:
1. Retry Phase 5 (the API issue may have resolved)
2. Skip Codex review and proceed to Phase 6 with design as-is
3. Abort

## Phase 6: WRITE PLAN

Delegate to an Opus sub-agent:

```
Agent({
  model: "opus",
  description: "Write implementation plan",
  prompt: "Task: <task>\n\nRead:\n- <artifactDir>/explore-report.md\n- <artifactDir>/intent-summary.md\n- <artifactDir>/design.md\n- <artifactDir>/codex-design-review.md\n\nWrite a comprehensive TDD implementation plan. Follow these rules exactly:\n\n1. Start with this required header:\n\n# [Feature] Implementation Plan\n\n> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.\n\n**Goal:** [one sentence]\n**Architecture:** [2-3 sentences]\n**Tech Stack:** [key technologies]\n\n---\n\n2. Map all files to create or modify with their responsibilities.\n\n3. Write bite-sized tasks. Each task must include:\n   - Exact file paths\n   - The failing test to write first (with full test code)\n   - Command to run the test and confirm it fails\n   - Minimal implementation code to make it pass\n   - Command to run and confirm pass\n   - git commit command\n\n4. No placeholders. No TBDs. Every step must show actual code.\n\nSave the plan to TWO locations:\n- <artifactDir>/plan.md\n- docs/superpowers/plans/YYYY-MM-DD-<task-slug>.md\n  (where task-slug is the task description lowercased, spaces replaced with hyphens, truncated to 40 chars)\n"
})
```

**If the user requests changes at Phase 7:** Re-run this phase with the user's feedback appended to the prompt as a `## Revision Request` section, then re-present the updated plan.

## Phase 7: USER GATE

After the plan is written, present it to the user:

```
계획 파일이 작성됐습니다: docs/superpowers/plans/<filename>.md

검토 후 응답해 주세요:
1. 승인 — /orchestrate --resume <artifactDir> 로 구현 단계 시작
2. 수정 요청 — 변경 내용을 설명해 주세요 (Phase 6 재실행)
3. 취소 — 여기서 중단 (artifactDir 보존)
```

Wait for the user's response before proceeding.

## Phase 8: HANDOFF

On user approval (option 1), execute:

```
Skill("orchestrate", args="--resume <artifactDir>")
```

This hands off to the orchestrate pipeline starting at Phase 4.5 (write failing tests). The `artifactDir` already contains all four artifacts required for resume:

- `intent-summary.md`
- `design.md`
- `route-decision.md`
- `codex-design-review.md`

If the Skill invocation is not available, instruct the user to run:

```bash
/orchestrate --resume <artifactDir>
```

## Failure Report Format

Use this shape for any phase failure:

```markdown
**Phase N (NAME) 실패**

**오류:** <specific error message>
**원인:** <brief analysis>

**추천 행동:**
1. <option 1>
2. <option 2>
3. <option 3>
```
