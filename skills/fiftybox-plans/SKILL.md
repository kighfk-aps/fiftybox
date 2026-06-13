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

Qwen3.5 9B 262K(Ollama) 고정 사용. 탐색 시작 직전에 환경변수를 Ollama endpoint로 설정한다:

```bash
eval "$("$HOME/.claude/skills/fiftybox-local/scripts/select_remote_model.sh" 9b)"
export QWEN_SUMMARY_MAX_CHARS_PER_FILE="12000"
export QWEN_SUMMARY_FILE_BATCH_MAX_TOKENS="8192"
export QWEN_SUMMARY_SINGLE_FILE_MAX_TOKENS="1024"
export QWEN_SUMMARY_MODULE_MAX_TOKENS="2048"
export QWEN_SUMMARY_FINAL_MAX_TOKENS="4096"
export QWEN_SUMMARY_TIMEOUT="900"
```

`qwen-summary-index`를 9B의 context tier인 `256k`로 실행한다:

```bash
python3 /Users/tanpapa/Desktop/develop-a/local-model/bin/qwen-summary-index "$(pwd)" \
  --context-tier 256k \
  --model "$LOCAL_MODEL_NAME" \
  --runs-dir "<artifactDir>/qwen-explore"
```

완료 후 가장 최신 출력 디렉토리의 `final-summary.md`를 `<artifactDir>/explore-report.md`에 복사한다:

```bash
latest="$(ls -td "<artifactDir>/qwen-explore"/run-* 2>/dev/null | head -1)"
cp "$latest/final-summary.md" "<artifactDir>/explore-report.md"
```

복사 완료 즉시 환경변수를 정리한다. Ollama는 공유 서비스이므로 컨테이너를 내리지 않는다:

```bash
"$HOME/.claude/skills/fiftybox-local/scripts/stop_remote_model.sh" 9b
unset QWEN_SUMMARY_BASE_URL QWEN_SUMMARY_MODEL QWEN_SUMMARY_API_KEY
unset QWEN_SUMMARY_MAX_CHARS_PER_FILE QWEN_SUMMARY_FILE_BATCH_MAX_TOKENS
unset QWEN_SUMMARY_SINGLE_FILE_MAX_TOKENS QWEN_SUMMARY_MODULE_MAX_TOKENS
unset QWEN_SUMMARY_FINAL_MAX_TOKENS
```

**탐색 실패·타임아웃 시 절대 금지 사항:**
- Claude가 직접 코드베이스를 읽거나 탐색하는 fallback을 수행해서는 안 된다.
- 느리다고 판단해 중도 포기하거나 대안 탐색으로 전환해서도 안 된다.
- 오직 두 가지 행동만 허용된다: **재시도(1회)** 또는 **실패 보고 후 중단**.

실패 시 처리 순서:
1. `qwen-summary-index`가 비정상 종료하거나 `final-summary.md`가 생성되지 않으면 한 번 재시도한다.
2. 재시도도 실패하면 `stop_remote_model.sh 9b`를 실행하고, 환경변수를 정리한 뒤, 아래 형식으로 실패 보고를 작성하고 즉시 중단한다.

```
**Phase 2 (EXPLORE) 실패**

**오류:** <qwen-summary-index 종료 코드 및 마지막 출력>
**원인:** <타임아웃 / 연결 실패 / 기타>
**보존된 artifactDir:** <artifactDir>

**추천 행동:**
1. 9B 모델 상태 확인 후 재실행
2. 원격 GPU 재부팅 후 재실행
3. 작업 중단
```

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
