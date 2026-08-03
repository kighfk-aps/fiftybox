---
name: fiftybox-gpt-review
description: 설계·계획 마크다운 문서를 Codex의 GPT 모델에 리뷰받고, 타당한 지적만 검증해 원본에 반영한 뒤 리뷰 로그와 함께 커밋한다. /fiftybox-gpt-review 호출 시 또는 spec·plan 문서를 GPT에게 리뷰받고 싶을 때 사용한다.
---

# fiftybox-gpt-review

설계·계획 문서를 GPT에 리뷰받고 반영한다. 1회전으로 끝난다 — 재리뷰는 사용자가 다시 부른다.

## Invocation

```text
/fiftybox-gpt-review <문서경로> [--model <slug>] [--effort <level>] [--context <path>]
```

문서 경로가 없으면 대화 맥락에서 추측하지 말고 사용자에게 묻는다.

## Resolve The Helper Script

다음 순서로 존재하는 첫 경로를 쓴다:

1. `~/.claude/skills/fiftybox-gpt-review/scripts/gpt_review.py`
2. `./skills/fiftybox-gpt-review/scripts/gpt_review.py`

둘 다 없으면 스킬이 설치되지 않았다고 보고하고 멈춘다.

## Phase 1: Run The Review

```bash
python3 <gpt_review.py> --doc "<문서경로>" [--model <slug>] [--effort <level>] [--context <path>]
```

기본값은 `gpt-5.6-terra` / `high`다. 사용자가 모델을 지정하지 않으면 그대로 쓴다.

문서가 다른 산출물(intent, explore report 등)에 의존하면 `--context`로 넘긴다. 리뷰어는
read-only 샌드박스에서 돌고 저장소를 탐색하지 않으므로, 넘기지 않은 파일은 리뷰에 반영되지 않는다.

**exit code가 0이 아니면 문서를 절대 수정하지 않는다.** 메시지를 그대로 사용자에게 전달하고 멈춘다:

| exit | 대응 |
|---|---|
| 2 | 경로 오류 — 올바른 경로를 사용자에게 확인 |
| 3 | codex 사용 불가 — 출력된 재활성화 명령을 사용자에게 그대로 전달 |
| 4 | 모델 슬러그 오류 — 출력된 사용 가능 목록에서 고르게 함 |
| 5 | 타임아웃 — `--timeout`을 늘리거나 더 가벼운 모델을 제안 |
| 6 | codex 실행 실패 — 출력된 stderr를 그대로 전달 |

성공하면 stdout JSON에서 `reviewPath`와 `verdict`를 읽는다.

## Phase 2: Apply The Feedback

`verdict`가 `BLOCKED`이면 **문서를 고치지 않는다.** 무엇이 막혔는지 요약해 보고하고
사용자 판단을 기다린다. 설계 자체를 다시 해야 하는 신호이므로 자동 수정이 오히려 해롭다.

`APPROVED`이면 반영할 것이 없다. Phase 3으로 간다.

`REVISE`(또는 `UNKNOWN`이지만 내용이 유효한 지적일 때)이면 리뷰 로그를 읽고 항목별로 처리한다:

- 각 지적을 **검증한 뒤** 반영한다. 문서에 이미 있는 내용을 못 본 지적, 이 저장소의 실제
  코드·규약과 어긋나는 지적은 기각한다. 근거를 확인하려면 해당 파일을 직접 읽는다.
- `blocking` 항목을 기각할 때는 반드시 이유를 남긴다. `minor`는 문서 의도를 흐리면 기각해도 된다.
- 기존 구조·문체를 유지한 채 **최소 편집**한다. 문서를 통째로 다시 쓰지 않는다.

반영을 마치면 리뷰 로그 파일 끝에 다음을 덧붙인다:

```markdown
## 반영 결과

**반영**
- <항목 요약> — <문서의 어디를 어떻게 고쳤는지>

**기각**
- <항목 요약> — <기각 이유>
```

## Phase 3: Commit

문서와 리뷰 로그를 함께 한 커밋으로 남긴다:

```bash
git add "<문서경로>" "<reviewPath>"
git commit -m "docs: apply GPT review feedback to <doc-name>

Reviewed by <model> (<effort>) — verdict <VERDICT>
Applied: N items / Rejected: M items"
```

`APPROVED`라 수정이 없었으면 리뷰 로그만 스테이징하고 커밋 메시지 제목을
`docs: record GPT review of <doc-name>`으로 한다.

## Report

사용자에게 한 화면으로 보고한다: 판정, 반영한 항목 수와 요약, 기각한 항목과 이유,
리뷰 로그 경로, 커밋 해시.

## 파이프라인에서 쓰기

`/fiftybox-orchestration`이나 `/fiftybox-plans` 안에서 설계를 리뷰하려면 이 스킬 대신
그쪽 phase의 opt-in 플래그를 쓴다:

```bash
--design-review-agent codex --design-review-model gpt-5.6-terra
```
