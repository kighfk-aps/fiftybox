# fiftybox-cc-execute GPT advisory 리뷰 설계

날짜: 2026-08-10
상태: 승인됨

## 목적

`fiftybox-cc-execute` Step 6 리뷰 게이트에서 Claude 토큰을 가장 많이 소모하는
**단일 태스크 스펙 준수 검사**를 GPT(`gpt-5.6-terra`) advisory 리뷰로 위임한다.
Claude는 **통합 검사 + 최종 go/no-go**만 유지해 CLAUDE.md "최종 검증은 Claude가 직접
처리한다" 원칙을 지킨다.

배경: codex/GPT는 구독 중단으로 2026-07-15 라우팅 결정에서 은퇴시켰고(현재 브랜치
`retire-codex-consolidate-skills`가 그 정리 작업), cc-execute는 `--skip-codex-review`로
advisory 스펙 리뷰를 끄고 있다. 구독 복구로 GPT 재활용이 다시 가능해졌으므로, 그
인프라를 **구현 diff 리뷰** 용도로 되살린다.

## 조사 결과 (실측)

- `codex`는 shim이 아니라 실제 바이너리(`/opt/homebrew/Caskroom/codex/0.147.0/bin/codex`)
  심볼릭 링크. `gpt_review.py`의 `SHIM_MARKER` 미검출 → GPT 즉시 사용 가능
- `~/.codex/models_cache.json` 존재 (2026-08-10 갱신)
- `skills/fiftybox-gpt-review/scripts/gpt_review.py`가 이미 GPT 리뷰 인프라를 갖췄다:
  shim 감지 → `codex exec -s read-only` 호출 → 판정 파싱(`APPROVED/REVISE/BLOCKED`)
  → 로그 저장 → stdout JSON. 단 `REVIEW_CONTRACT`는 **문서 리뷰용**이라 diff 리뷰엔
  별도 contract가 필요하다
- `orchestrate.py`의 codex 인프라(`run_codex_phase`, `_emit_advisory`, design-review
  phase)는 **설계/스펙 advisory 리뷰**에 묶여 있다. 현재 cc-execute가 끄는
  `--skip-codex-review`도 이 설계 리뷰를 가리킨다. 구현 diff 리뷰와는 입력·contract가
  달라 이 인프라를 그대로 재용하기 부자연스럽다
- cc-execute `SKILL.md`는 orchestrate를 페이즈별로 호출만 하는 얇은 스킬이다

## 범위

| 파일 | 변경 |
|---|---|
| `skills/fiftybox-cc-execute/scripts/cc_diff_review.py` | 신규 — diff 리뷰 스크립트. `gpt_review.py` 패턴 복제, diff 리뷰용 contract |
| `skills/fiftybox-cc-execute/scripts/test_cc_diff_review.py` | 신규 — 판정 파싱·contract 빌드·exit code 매핑 단위 테스트 |
| `skills/fiftybox-cc-execute/SKILL.md` | Step 6 재구조화(6a GPT / 6b Claude 최종 게이트), 모델 티어 표 `review` 행 추가, 안전 계약 갱신 |
| `install.sh` | 새 스크립트·테스트 복사 줄 추가 (파일별 명시적 `cp` 패턴) |

`orchestrate.py`는 건드리지 않는다. 이 스킬의 GPT 리뷰는 cc-execute 안에 자체
완결된다.

## 아키텍처 / 역할 분담

Step 6의 기존 3단계를 두 역할로 나눈다:

| Step 6 항목 | 기존 | 새 |
|---|---|---|
| ① 테스트 통과 확인 | Claude | **GPT** (advisory) |
| ② 스펙 준수 (diff vs 명세) | Claude | **GPT** (advisory) |
| ③ 통합 검사 (병렬 충돌·크로스 인터페이스) | Claude | Claude (유지) |
| GPT findings 재확인 + 최종 go/no-go | — | Claude (유지) |

GPT는 **제1필터**이고 **non-blocking(advisory)**이다. Claude는 GPT 결과를 읽고
최종 판정한다. 이 분담은 CLAUDE.md의 최종 검증 원칙을 위반하지 않는다 — GPT가
"통과 후보"를 걸러내면 Claude가 그 위에서 통합 검사와 최종 승인을 한다.

## cc_diff_review.py 상세

`gpt_review.py`의 구조를 따르되 diff 리뷰에 맞게 contract와 입력을 바꾼다.

### 인자

```
--diff <path>        # 필수 — 해당 태스크의 git diff 파일
--spec <text>        # 필수 — 태스크 명세 텍스트 (스킬이 task-batches.md에서 발췌해 넘긴다)
--test <path>        # 필수 — 수용 기준 = 테스트 파일
--context <path>     # 옵션·반복 가능 — design.md 등 추가 맥락 파일
--model <slug>       # 기본 gpt-5.6-terra
--effort <level>     # 기본 high
--out <dir>          # 기본 <artifactDir>/reviews
--task-name <name>   # 로그 파일명에 쓸 태스크 식별자
```

### DIFF_REVIEW_CONTRACT

`gpt_review.py`의 `REVIEW_CONTRACT`와 같은 형태지만 판단 대상이 diff다:

```
You are reviewing a code diff against its task specification and acceptance tests.

Respond in exactly this shape:

FIRST LINE: one of APPROVED | REVISE | BLOCKED
THEN: a list of findings. Each finding is

- [severity: blocking|major|minor] one-line summary
  Evidence: which part of the diff or spec is wrong, and why
  Proposal: concretely what to change

Judge only these:
- does the diff satisfy every requirement in the task spec
- do the acceptance tests pass and actually cover the spec
- scope creep: changes outside the task's files, unrelated edits
- missing requirements or half-implemented behavior

Out of scope — do not comment on: code style, naming, prose,
cross-task integration conflicts (a separate reviewer owns that),
or anything the spec deliberately defers. Do not modify any file.
```

"cross-task integration conflicts"를 명시적으로 out-of-scope에 둬 **GPT(단일
태스크)와 Claude(통합)의 분담 경계를 contract 수준에서 고정**한다.

### 호출 (gpt_review.py와 동일)

```python
["codex", "exec", "--model", model,
 "-c", f"model_reasoning_effort={effort}",
 "-s", "read-only", "--ephemeral", "--skip-git-repo-check",
 "--ignore-user-config", "-o", str(output_file), "-"]
```

read-only 샌드박스라 리뷰어가 파일을 수정할 수 없다.

### 출력

- 로그: `<out>/<task-name>-gpt-review[-N].md` (덮어쓰기 방지 카운터, `review_log_path`
  패턴 재용)
- stdout JSON: `{ok, verdict, reviewPath, findingsCount, model, effort}`

### exit code (gpt_review.py 준수)

| exit | 의미 | cc-execute 대응 |
|---|---|---|
| 0 | 성공 | JSON에서 `verdict` 읽어 6b로 |
| 2 | 인자/경로 오류 | 스킬 버그. 보고 후 해당 태스크 Claude 폴백 |
| 3 | codex 사용 불가(shim) | 안내 메시지 전달, 해당 태스크 Claude 폴백 |
| 4 | 모델 슬러그 오류 | `codex` 사용 가능 목록 제시, 대체 모델 선택 후 재실행 |
| 5 | 타임아웃 | effort 하향 / 더 가벼운 모델 제안. 실패 시 Claude 폴백 |
| 6 | codex 실행 실패 | stderr 전달, Claude 폴백 |

## Step 6 재구조화

### 6a — GPT advisory 리뷰 (자동)

배치 내 각 태스크에 대해 `cc_diff_review.py`를 실행한다. detached 병렬이 가능하다
(태스크별로 독립 프로세스):

```bash
nohup python3 ~/.claude/skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
  --diff "<artifactDir>/diff-task-N.patch" \
  --spec "<task 명세 텍스트 또는 파일>" \
  --test "<테스트 파일>" \
  --context "<artifactDir>/design.md" \
  --task-name "task-N" --out "<artifactDir>/reviews" \
  --model gpt-5.6-terra --effort high \
  > "<artifactDir>/gpt-review-task-N.out" 2>&1 &
```

diff는 워크트리에서 `git diff`로 해당 태스크 파일만 잘라 `<artifactDir>/diff-task-N.patch`로
미리 만들어둔다. 로그를 폴링해 완료를 기다린다(Step 5 detached 패턴과 동일).

### 6b — Claude 최종 게이트

각 태스크의 GPT 결과 JSON을 읽어 분기한다:

- **`APPROVED`** → 통합 검사(③)만 수행. 통과하면 다음 배치
- **`REVISE` / `BLOCKED`** → findings를 읽고 **검증**한다:
  - 타당하면 → 수정 Agent(`cmd` 재구현)를 붙이고 테스트 재실행 → **6a+6b 재리뷰 1회**
  - 타당하지 않으면(이미 만족한 요구, 오해, 범위 밖 지적) → 기각 사유를
    `<artifactDir>/reviews/<task-name>-gpt-review.md` 말미에 남기고 통합 검사(③)로
- **통합 검사(③)** → 항상 Claude. 병렬 태스크 간 충돌 편집·크로스 인터페이스 불일치·
  의도치 않은 결합

GPT-driven 재구현이 1회 안에서 해결되지 않으면(재리뷰에서 여전히 동일 blocking
지적) 사용자에게 선택지를 제시한다 — 기존 "두 번째 실패 시 사용자 보고" 규칙을
GPT 경로에도 그대로 적용한다.

### 모델 티어 표 (SKILL.md에 추가)

| 대상 | 모델 |
|---|---|
| `implement` · simple | `qwen/qwen3.7-flash` |
| `implement` · complex | `zai-org/glm-5.2` |
| `deploy` | `qwen/qwen3.7-flash` |
| **`review`** (신규) | **`gpt-5.6-terra` / effort high** |

`gpt-5.6-sol`은 호출 시 `--model`로 선택 가능(terra/sol 비교는 구현 후 실제 diff로
검증해 기본값을 확정한다).

## 폴백 정책

**GPT 리뷰는 절약 기회이지 필수가 아니다.** GPT가 실패하거나 사용 불가(shim/timeout/
auth)면, 해당 태스크는 Claude가 기존 방식(직접 스펙 준수 검사)으로 폴백한다.
파이프라인은 절대 GPT 때문에 멈추지 않는다 — GPT가 죽으면 자동으로 오늘의 Claude
경로로 돌아간다. 이것이 이 설계의 안전망이다.

폴백은 태스크 국소다. 한 태스크의 GPT 리뷰가 실패해도 같은 배치의 형제 태스크는
GPT로 계속 진행할 수 있다(Step 5의 "태스크 국소 실패" 규칙과 일관).

## 안전 계약 (추가·갱신)

`/fiftybox-orchestration` 승계 계약 위에 다음을 추가한다:

- **GPT 리뷰는 advisory(non-blocking)다.** 판정이 파이프라인을 멈추지 않는다
- **GPT 판정을 맹신하지 않는다.** Claude가 findings를 검증하고 최종 go/no-go를 낸다
- GPT 리뷰어는 read-only 샌드박스라 파일을 수정할 수 없다
- **GPT 실패 시 자동 Claude 폴백.** 단절을 이유로 파이프라인을 멈추지 않는다
- 기존 "Claude는 구현 코드를 직접 쓰지 않는다" 규칙은 그대로. GPT-driven 재구현도
  `cmd`가 수행한다 — Claude가 직접 고치지 않는다
- GPT-driven 자동 재구현은 태스크당 1회. 그래도 안 되면 사용자에게 보고

## 검증

1. `test_cc_diff_review.py`:
   - `parse_verdict` — APPROVED/REVISE/BLOCKED/UNKNOWN 파싱 (gpt_review.py 테스트
     패턴 준수, 토큰 경계 케이스 포함)
   - `build_prompt` — DIFF_REVIEW_CONTRACT + diff + spec + test 조립 순서
   - `is_shim` / 모델 slug 검증 / exit code 매핑
   - `codex`를 실제로 호출하지 않는다(인자 빌드·파싱만)
2. `SKILL.md` 변경: Step 6a/6b 흐름, 폴백, 모델 티어 `review` 행이 문서에 정확히
   반영됐는지
3. **수동 E2E**(사용자와 함께): 작은 실제 태스크 2개짜리 배치로 6a 병렬 → 6b 분기
   (APPROVED 경로 + 의도적 스펙 위반으로 REVISE 경로)를 돌려, GPT가 단일 태스크
   위반을 잡아내고 Claude가 통합 검사를 유지하는지 확인. terra/sol 판정 품질도 이때
   비교

## 넣지 않는 것 (YAGNI)

- **`orchestrate.py` 신규 페이즈** — 공용 스크립트에 cc-execute 전용 로직이 섞여
  결합도가 올라간다. cc-execute 안에 자체 스크립트로 둔다
- **GPT 리뷰를 blocking 게이트로 승격** — 최종 검증은 Claude가 해야 한다(원칙). GPT는
  필터다
- **gpt_review.py에 diff 모드 추가** — 문서 리뷰와 diff 리뷰 contract/입력이 한 파일에
  섞여 복잡도가 증가한다. 별도 스크립트가 명확하다
- **자동 승인(AGENTS.md taste 학습 등) 연동** — 리뷰 품질과 직결되지 않고 비결정성만
  추가한다
- **GPT가 테스트를 직접 수정** — read-only 샌드박스가 원천 차단. TDD 안전 계약 유지
