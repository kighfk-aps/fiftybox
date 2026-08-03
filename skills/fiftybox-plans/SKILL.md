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

## Resolve The Local-Model Helper Scripts

Phase 2 needs `select_remote_model.sh` / `stop_remote_model.sh` from the `fiftybox-local` skill. Resolve the directory in this order, same as `/fiftybox-local` does:

```bash
for dir in \
  "${CODEX_HOME:-$HOME/.codex}/skills/fiftybox-local/scripts" \
  "$HOME/.claude/skills/fiftybox-local/scripts" \
  "$(pwd)/skills/fiftybox-local/scripts"; do
  if [ -x "$dir/select_remote_model.sh" ]; then
    FIFTYBOX_LOCAL_HELPER_DIR="$dir"
    break
  fi
done
test -n "${FIFTYBOX_LOCAL_HELPER_DIR:-}" || {
  echo "fiftybox-local helper scripts not found" >&2
  exit 1
}
```

## Phase 1: Setup

Run:

```bash
python3 <orchestrate.py> --phase setup --task "<task>" --cwd "$(pwd)"
```

Read the JSON output and keep `artifactDir` and `worktree`.

## Phase 2: Explore

GLM-5.4 (Z.AI API) 고정 사용. 탐색 시작 직전에 환경변수를 Z.AI API endpoint로 설정한다:

```bash
eval "$("$FIFTYBOX_LOCAL_HELPER_DIR/select_remote_model.sh" glm-5.4)"
export QWEN_SUMMARY_MAX_CHARS_PER_FILE="500"
export QWEN_SUMMARY_FILE_BATCH_MAX_FILES="2"
export QWEN_SUMMARY_FILE_BATCH_MAX_TOKENS="1800"
export QWEN_SUMMARY_SINGLE_FILE_MAX_TOKENS="512"
export QWEN_SUMMARY_MODULE_MAX_TOKENS="768"
export QWEN_SUMMARY_FINAL_MAX_TOKENS="1200"
export QWEN_SUMMARY_TIMEOUT="900"
```

`qwen-summary-index`를 GLM-5.4의 context tier인 `256k`로 실행한다:

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

복사 완료 즉시 환경변수를 정리한다. GLM-5.4는 외부 API이므로 서버를 내리지 않는다:

```bash
"$FIFTYBOX_LOCAL_HELPER_DIR/stop_remote_model.sh" glm-5.4
unset QWEN_SUMMARY_BASE_URL QWEN_SUMMARY_MODEL QWEN_SUMMARY_API_KEY
unset QWEN_SUMMARY_MAX_CHARS_PER_FILE QWEN_SUMMARY_FILE_BATCH_MAX_TOKENS
unset QWEN_SUMMARY_FILE_BATCH_MAX_FILES QWEN_SUMMARY_SINGLE_FILE_MAX_TOKENS
unset QWEN_SUMMARY_MODULE_MAX_TOKENS
unset QWEN_SUMMARY_FINAL_MAX_TOKENS
```

**탐색 실패·타임아웃 시 절대 금지 사항:**
- Claude가 직접 코드베이스를 읽거나 탐색하는 fallback을 수행해서는 안 된다.
- 느리다고 판단해 중도 포기하거나 대안 탐색으로 전환해서도 안 된다.
- 오직 두 가지 행동만 허용된다: **재시도(1회)** 또는 **실패 보고 후 중단**.

실패 시 처리 순서:
1. `qwen-summary-index`가 비정상 종료하거나 `final-summary.md`가 생성되지 않으면 한 번 재시도한다.
2. 재시도도 실패하면 `stop_remote_model.sh glm-5.4`를 실행하고, 환경변수를 정리한 뒤, 아래 형식으로 실패 보고를 작성하고 즉시 중단한다.

```
**Phase 2 (EXPLORE) 실패**

**오류:** <qwen-summary-index 종료 코드 및 마지막 출력>
**원인:** <타임아웃 / 연결 실패 / 기타>
**보존된 artifactDir:** <artifactDir>

**추천 행동:**
1. GLM-5.4 API 상태 확인 후 재실행
2. GLM_API_KEY 유효 여부 확인 후 재실행
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

Review the produced plan before publishing it. Codex is retired, so **Claude reviews the plan directly**: read `<artifactDir>/plan.md` against `<artifactDir>/intent-summary.md`, `<artifactDir>/design.md`, and `<artifactDir>/explore-report.md`, and judge it on missing steps, unsafe assumptions, test adequacy, and whether a separate agent could execute it unaided. Record a first-line verdict (`APPROVED`, `REVISE`, or `BLOCKED`) plus notes to `<artifactDir>/plan-review.md`.

Then run verify-design for `--resume` compatibility. For a normal plan, run it without reviewer flags — it records an advisory pass:

```bash
python3 <orchestrate.py> --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

**Only for a genuinely complex architecture**, add the opt-in GLM design review (Z.AI Coding Plan — `zai-coding` / `glm-5.2`) instead:

```bash
python3 <orchestrate.py> --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --design-review-provider zai-coding --design-review-model glm-5.2
```

Codex/GPT is the other opt-in reviewer. It needs no provider — pass the agent instead:

```bash
python3 <orchestrate.py> --phase verify-design --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --design-review-agent codex --design-review-model gpt-5.6-terra
```

Codex must be enabled on this machine (`codex --version` must succeed). Either reviewer is **advisory**: the verdict is recorded in `design-review.md` and surfaced, but does not stop the pipeline unless you pass `--strict-review`.

If the plan review is `REVISE`, update `<artifactDir>/plan.md` using the review feedback, then review once more. If it is `BLOCKED`, stop with the failure report and the blocker.

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
> Reviewed: <plan-review.md verdict line>

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
- first line of `plan-review.md`
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
