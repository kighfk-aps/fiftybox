# Stage 02 - Insert `### Gemma4 실행 예산` constants block

## Goal
Add one new section that states the quantitative dispatch budget, so every
later rule in the document has a single source of truth for its numbers.

## Inputs To Read
- `staged-plan.md` § Deviations #4 (threshold correction), `context-summary.md` § Stage 01
- `~/.claude/skills/fiftybox-local/SKILL.md:42-64` (Executor section → `### 설정 게이트`)

## Files To Change
- `~/.claude/skills/fiftybox-local/SKILL.md` (insert only)

## Steps
1. Locate the anchor `서버 운용 기록은 \`~/Desktop/develop-a/local-model/\`(모델 전환·평가 리포트).`
   and the following `### 설정 게이트` heading. Insert the block between them.
2. Do not renumber, move, or reword anything else.

## Exact text to insert
```markdown
### Gemma4 실행 예산

executor가 한 번의 디스패치로 처리할 수 있는 입력 크기의 정량 상한이다. 태스크는
디스패치 전에 이 예산을 통과해야 한다.

| 상수 | 값 | 근거 |
|---|---|---|
| `DESIGN_MD_MAX_LINES` | `60` | 클린 성공 태스크의 design은 22~54줄 band였다 |
| `TASK_SPEC_MAX_LINES` | `15` | 205줄·3~4파일 태스크는 반복 재시도 후 `no_changes`로 끝났다 |
| `TASK_MAX_FILES` | `2` | 단일 태스크가 소유(수정)할 수 있는 파일 상한 |
| `INTENT_SUMMARY_MAX_LINES` | `14` | intent 51줄이 낀 1481줄 프롬프트 사고가 실존한다 |
| `PROMPT_MAX_LINES` | `120` | 실측 게이트 — `implement-prompt.md`의 `wc -l` |

**산수:** `orchestrate.py`가 `implement`마다 고정 템플릿 **31줄** + 태스크 명세 +
`design.md` 전문 + `intent-summary.md`를 `implement-prompt.md`로 합친다. 즉
`프롬프트 = 31 + design + spec + intent`이고, 위 상한을 전부 채우면
`31+60+15+14 = 120`으로 게이트에 딱 맞는다. 하나라도 넘으면 게이트에서 떨어진다.
(실측: design 40 → 프롬프트 79 / design 100 → 프롬프트 139)

**병목:** 컨텍스트는 262,144지만 `max_tokens`가 **16,384**라 **출력이 먼저** 막힌다.
`IMPL_TIMEOUT`은 `1800`초. 컨텍스트가 남는다고 태스크를 키우지 않는다.

**Calibration:** Step 6의 `gemma4-metrics.md`에 태스크별 실측을 누적한다. 최근
5태스크 성공률 < 80% → `DESIGN_MD_MAX_LINES` 60→45, `PROMPT_MAX_LINES` 120→100.
10태스크 연속 100% → `DESIGN_MD_MAX_LINES` 60→70, `PROMPT_MAX_LINES` 120→140.
조정은 누적 실측을 보여주고 **사용자 승인 후** 반영한다. 임의로 바꾸지 않는다.
```

## Acceptance
- `grep -c '### Gemma4 실행 예산' SKILL.md` ≥ 1
- all five constant names grep-detectable
- section sits **before** `### 설정 게이트`
- `head -4` unchanged (frontmatter intact)

## Verification
- `grep -n -E 'DESIGN_MD_MAX_LINES|TASK_SPEC_MAX_LINES|TASK_MAX_FILES|INTENT_SUMMARY_MAX_LINES|PROMPT_MAX_LINES' ~/.claude/skills/fiftybox-local/SKILL.md`
- `awk '/### Gemma4 실행 예산/,/### 설정 게이트/' ~/.claude/skills/fiftybox-local/SKILL.md | head -30`

## Handoff Notes
- Stage 03 must reference `DESIGN_MD_MAX_LINES=60` (not 80).
- Stage 05's gate threshold stays `PROMPT_MAX_LINES=120`.
