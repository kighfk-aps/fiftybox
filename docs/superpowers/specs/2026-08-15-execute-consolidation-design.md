# fiftybox-execute / fiftybox-local 통합 설계

날짜: 2026-08-15
상태: 검토 중

## 목적

현재 구현 실행 계열 스킬이 5개로 흩어져 있다:

| 스킬 | 저장소 | 구현자 | 실행 방식 | 고유 기능 |
|---|---|---|---|---|
| `fiftybox-execute` | fiftybox | opencode-go/deepseek-v4-flash (고정) | 배치 병렬 | 없음 |
| `fiftybox-cc-execute` | fiftybox | CommandCode (`cmd`), tier 표 | 배치 병렬 | Step 6a GPT(gpt-5.6-terra) advisory diff 리뷰 |
| `fiftybox-free-execute` | fiftybox | opencode 무료 티어 (매번 탐색) | 순수 순차 | 무료 모델 탐색 + 소진 시 재탐색 |
| `pi-execute` | claude-code-config | Pi CLI, `--provider`/`--model`/`--local` | 배치 병렬 | Modal Qwen 콜드스타트 웨이크업 (`--local`) |
| (신규 검토했던 grok 전용 스킬) | — | Grok Build | 배치 병렬 | 채택 안 함 — 아래로 흡수 |

다섯 스킬의 Step 1~10 워크플로·안전 계약·실패 보고 포맷은 문자 그대로에 가깝게
중복된다. 다른 건 ① 구현 에이전트/모델 지정 방식 ② 병렬 여부 ③ 애드혹으로 붙은
리뷰·탐색 기능뿐이다. 이 설계는 이를 **두 스킬로 수렴**한다:

- **`fiftybox-execute`** — 고정 비용/유료 provider 전반. 병렬 배치.
- **`fiftybox-local`** — 로컬·무료 provider 전반. 동적 병렬(가용 모델 수만큼).

동시에 별도로 진행 중이던 다음 두 가지도 이 작업에 포함한다:
1. Grok Build(`grok` CLI, xAI grok-4.6)를 신규 provider로 추가 — 전용 스킬을 새로
   만들지 않고 `fiftybox-execute`의 provider 중 하나로 흡수한다.
2. 설계/계획 리뷰 기본 모델을 `gpt-5.6-terra` → `gpt-5.6-sol`(effort high)로 교체.

## 조사 결과 (실측)

- `orchestrate.py`의 `BUILTIN_AGENTS`에는 이미 `pi`/`opencode`/`aider`/`gemini`/
  `qwen`/`cursor`/`codex`/`commandcode`가 등록돼 있다. `grok`은 없다.
- `grok` CLI는 `--permission-mode`로 `default/acceptEdits/auto/dontAsk/
  bypassPermissions/plan`을 지원한다. `grok-review` 스킬은 리뷰 전용이라 `auto`를
  쓰지만(파일 미수정 계약), 무인 배경 구현에는 승인 대기 없이 전부 통과시켜야
  하므로 `bypassPermissions`가 필요하다.
- `orchestrate.py`의 `resolve_agent_config`가 읽는 `config.json` 경로는
  `SKILL_DIR = ~/.claude/skills/orchestrate`로 **하드코딩**돼 있다 — 스크립트
  자신이 어느 디렉터리(`fiftybox-orchestration`)에서 실행되든 상관없다. 이
  레거시 이름은 그대로 둔다(범위 밖). 여기에 `agents.piqwen`이 이미 정의돼 있다:
  `pi --print --provider {provider} --model {model} --thinking off ...`.
- `~/.claude/skills/fiftybox-orchestration`(설치본)의 `orchestrate.py`는
  **fiftybox 저장소** 버전과 바이트 단위로 동일하다. `claude-code-config`
  저장소에도 동명의 `skills/fiftybox-orchestration/scripts/orchestrate.py`
  사본이 있으나 최근 fiftybox 커밋들(`commandcode` 에이전트, dirty-path 수정
  등)이 빠진 **오래된 사본**이다 — 실제 설치본은 fiftybox 쪽에서 온 것이므로
  이 사본은 죽은 코드다. 이번 작업 범위에서 손대지 않는다(별도 정리 필요하면
  후속 작업).
- `pi-execute`(claude-code-config)는 이미 `--provider`/`--model`/`--local` 파라미터화가
  돼 있다. `--local`은 `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
  `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`으로 전환하고, 매 디스패치(배치 implement,
  fix 재시도, Phase 6 auto-retry, Phase 7b deploy) 전에 Modal 콜드스타트 웨이크업
  절차(75/120/150초 3회 체크, 백그라운드 curl)를 강제한다.
- `fiftybox-free-execute`(fiftybox)는 `discover_free_models.py`로 opencode Zen
  무료 티어를 매번 실측 탐색하고(각 후보에 실제 호출 1회), 사용자가 고르며,
  순수 순차 실행한다. 소진 시 재탐색 후 실패한 태스크만 새 모델로 재실행한다.
- `fiftybox-cc-execute`의 Step 6a는 CommandCode 구현 diff를 `cc_diff_review.py`로
  `gpt-5.6-terra`/`high`에 advisory 리뷰시킨다(codex read-only 샌드박스, exit
  code 0/2~6 분기, verdict `APPROVED/REVISE/BLOCKED/UNKNOWN`).
- 설계/계획 리뷰 기본 모델은 두 곳에 있다: `orchestrate.py` Phase 4 opt-in
  design-review(`--design-review-agent codex --design-review-model
  gpt-5.6-terra`)와 독립 스킬 `/fiftybox-gpt-review`(`gpt_review.py`
  `DEFAULT_MODEL = "gpt-5.6-terra"`). 둘 다 `high`.

## 범위

### 새로 만들거나 바꾸는 파일 (fiftybox 저장소)

| 파일 | 변경 |
|---|---|
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | `BUILTIN_AGENTS`에 `grok` 추가 |
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | Phase4 design-review 기본 모델 도움말/기본값 `gpt-5.6-terra`→`gpt-5.6-sol` |
| `skills/fiftybox-gpt-review/scripts/gpt_review.py` | `DEFAULT_MODEL` `gpt-5.6-terra`→`gpt-5.6-sol` |
| `skills/fiftybox-gpt-review/SKILL.md` | 기본값 문구 갱신 |
| `skills/fiftybox-execute/SKILL.md` | 재작성 — provider 파라미터화 + 흡수 |
| `skills/fiftybox-execute/scripts/` | cc-execute의 `cc_diff_review.py`를 provider-무관 `diff_review.py`로 일반화해 이동 |
| `skills/fiftybox-local/` (신규) | `SKILL.md` + `discover_free_models.py`(free-execute에서 이동) + Modal 웨이크업 로직 |
| `commands/fiftybox-execute.md` | 인자 안내 갱신 |
| `commands/fiftybox-local.md` (신규) | 슬래시 명령 |
| `skills/fiftybox-cc-execute/` | 삭제 |
| `skills/fiftybox-free-execute/` | 삭제 |
| `commands/fiftybox-cc-execute.md`, `commands/fiftybox-free-execute.md` | 삭제 |
| `install.sh` | 배선 갱신(신규 fiftybox-local 추가, cc-execute/free-execute 제거) |
| `tests/` | 구조 테스트 갱신·신설, cc-execute/free-execute 전용 테스트 삭제 |
| `README.md` | 스킬 목록 갱신 |

### 삭제하는 파일 (claude-code-config 저장소)

| 파일 | 변경 |
|---|---|
| `skills/pi-execute/` | 삭제 (전체 흡수됨: 클라우드 경로 → fiftybox-execute, `--local` 경로 → fiftybox-local) |
| `commands/pi-execute.md` (있다면) | 삭제 |
| 해당 저장소의 install/test 스크립트 중 `pi-execute` 참조 | 제거 |

claude-code-config 저장소에 이미 커밋 안 된 `fiftybox-local`/`fiftybox-local-execute`
삭제 변경사항이 있다 — 이번 작업과 이름은 겹치지만 그 구현체는 이미 죽은
것이라 무관하다. 손대지 않고(사용자의 기존 미완 작업이므로 임의로 커밋·되돌리지
않는다) 그대로 둔 채 진행한다.

## `fiftybox-execute` (통합 후)

### 호출

```
/fiftybox-execute "<작업 설명>" [--provider <id>] [--model <id>]
```

`--provider`/`--model` 생략 시 기존 하위 호환 기본값 `opencode-go`/
`deepseek-v4-flash` 유지. 값은 그대로 `orchestrate.py`의
`--implement-agent`/`--model`로 전달한다(1:1 매핑, 스킬 레이어의 재해석 없음).

### provider 표 (참고용, 강제 아님)

| provider | 비고 |
|---|---|
| `opencode-go` (기본) | 기존 fiftybox-execute 기본값 |
| `commandcode` | 구 fiftybox-cc-execute. tier(simple/complex) 판단은 스킬 문서에 참고표로 유지하되 강제하지 않음 — 사용자가 `--model`로 직접 고를 수도 있음 |
| `pi` | 구 pi-execute 클라우드 경로 (`opencode-go`/`glm-5.2` 기본) |
| `grok` | 신규. `BUILTIN_AGENTS["grok"]` |

`BUILTIN_AGENTS["grok"]` 정의:

```python
"grok": {"cmd": ["grok", "-p", "{prompt}\n{task}", "--model", "{model}",
                 "--permission-mode", "bypassPermissions",
                 "--output-format", "json"]},
```

### Advisory diff 리뷰 (opt-in, 기본값 없음)

Step 6과 Step 7 사이에 **선택적** 단계로 둔다. 트리거는 플래그가 아니라
**자연어**다 — 사용자가 호출 문장에 "~로 리뷰해줘", "~가 검토하게" 등 리뷰
provider/model을 언급했을 때만 수행한다. 언급이 없으면 완전히 스킵한다(로그도
안 남김, 비용 발생 없음). 언급했는데 모델이 불분명하면 한 번 물어본다.

리뷰 실행은 `cc_diff_review.py`를 provider 인자를 받도록 일반화한
`diff_review.py`로 수행한다(현재는 codex 전용 하드코딩 — `--model`만 받고
내부적으로 `codex exec`를 호출하는 구조이므로, provider가 grok 등으로 바뀔
경우엔 이 스크립트가 아니라 해당 CLI를 직접 detached 호출해야 한다. 최소
변경으로는 "codex 계열 모델(gpt-5.6-*)"만 이 스크립트로 지원하고, 다른
provider의 advisory 리뷰는 1차 범위에서 제외 — 아래 Out of Scope 참고).

배치 병렬·안전 계약·실패 분류·complete/deploy/cleanup은 cc-execute 버전을
그대로 계승한다(가장 정교함).

## `fiftybox-local` (신규)

### 호출

```
/fiftybox-local "<작업 설명>" [--provider <id> --model <id> ...]
```

인자 없이 호출하면 free-execute처럼 매번 무료 티어를 탐색해 사용자가 고른다.

### 후보 풀 구성

1. `discover_free_models.py`(free-execute에서 이동)로 opencode Zen 무료 티어를
   실측 탐색 — `smoke: ok`인 것만 후보.
2. `modal-qwen38`(Qwen3.8-27B, pi-execute `--local`에서 이동)을 **탐색 없이 항상
   후보 1개로 추가** — 콜드스타트는 있지만 가용성 자체는 항상 참으로 간주.
3. 사용자가 `--provider`/`--model`을 명시하면 탐색을 건너뛰고 그 목록만 후보로
   쓴다(수동 모드).

### 동적 병렬도

이번 실행의 **후보 모델 수 = 최대 동시 배치 크기**.
- 후보 1개 → 순차(기존 free-execute/구 pi-execute --local과 동일 체감)
- 후보 N개(N≥2) → 배치당 최대 N개 병렬, **배치 내 각 태스크는 서로 다른
  모델에 배정**(같은 모델에 태스크 2개를 동시에 주지 않는다 — 무료 티어
  분당 요청 제한 회피, Modal 컨테이너 자원 경합 회피가 목적)
- 태스크 수 > 후보 수면 라운드를 반복한다(1라운드 = 최대 N개 병렬)

`modal-qwen38`이 배치에 포함될 때만 그 레인 앞에 웨이크업 절차(75/120/150초
3회 체크)를 삽입한다. 다른 레인의 진행을 막지 않는다 — 각 레인은 독립
detached 프로세스.

### 소진 처리

free-execute의 재탐색 로직을 계승하되 배치 단위로 확장: 배치 중 한 모델이
소진되면 그 모델이 담당하던 태스크만 재탐색된 다른 후보로 재배정한다. 형제
레인(다른 모델)은 계속 진행한다. `smoke: ok` 후보가 하나도 안 남으면 중단하고
보고한다 — 유료 provider로 자동 전환하지 않는다(free-execute의 존재 이유
보존).

### Advisory 리뷰

`fiftybox-execute`와 동일한 자연어 opt-in 트리거. 로컬/무료 스킬이라 기본적으로
쓸 일이 적겠지만 배제하지는 않는다.

## Out of Scope

- CommandCode·Grok 등 codex 계열이 아닌 provider의 advisory diff 리뷰 자동화
  스크립트화. 1차 범위는 "codex 계열 리뷰어(gpt-5.6-*)"만 스크립트로 지원한다.
  다른 조합(예: grok 구현물을 grok 자신이 리뷰)은 이번에 만들지 않는다 — 필요시
  후속 작업.
- claude-code-config 저장소의 orchestrate.py 오래된 사본 정리.
- claude-code-config에 이미 있는 미완 삭제 변경사항(`fiftybox-local(-execute)`)
  정리 — 사용자가 별도로 처리.
- `~/.claude/skills/orchestrate` 레거시 디렉터리 이름 정리.

## 승계하는 안전 계약

기존 다섯 스킬 공통으로 이미 있던 것 — 통합 후에도 그대로:

- Claude는 구현 파일을 직접 쓰지 않는다. 예외 없음. Claude가 쓰는 파일은
  테스트 파일과 아티팩트 문서뿐
- Red(Claude가 테스트 작성) → Green(provider가 통과시킴) → Claude 리뷰 게이트
- provider는 커밋·푸시하지 않는다. 커밋은 `--phase complete`가 수행
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지, Phase 7 이전
  push 금지
- 자동 재시도는 태스크당 1회
- 실패 시 선택지 제시, 조용히 복구하지 않음
- 병렬 시: 에이전트는 소유 경계 밖 파일을 편집하지 않는다, Claude가 매
  배치를 리뷰한 뒤에만 다음 배치 시작
- TDD: provider는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행

## 테스트 계획

- `skills/fiftybox-orchestration/tests`: `grok` BUILTIN_AGENTS 등록 테스트,
  Phase4 design-review 기본 모델 `gpt-5.6-sol` 테스트
- `skills/fiftybox-gpt-review/tests`: `DEFAULT_MODEL` 변경 반영
- `fiftybox-execute`/`fiftybox-local`: 구조 테스트(SKILL.md에 provider 표·자연어
  리뷰 트리거 문구·동적 병렬도 규칙 존재 확인) — 기존 스킬들의 structural test
  패턴 재사용
- `install.sh` 배선 테스트: cc-execute/free-execute 제거, fiftybox-local 추가
  반영
- 저장소 전체 grep으로 삭제된 스킬(`fiftybox-cc-execute`, `fiftybox-free-execute`,
  `pi-execute`) 참조 잔존 확인(README, 다른 SKILL.md의 상호 참조 등)
