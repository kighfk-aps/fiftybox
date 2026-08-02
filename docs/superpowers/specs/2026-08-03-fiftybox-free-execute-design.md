# fiftybox-free-execute 설계

**날짜:** 2026-08-03
**상태:** 승인됨

## 목적

opencode Zen이 제공하는 **무료 모델**로 구현 페이즈를 돌리는 실행 스킬을 만든다.
무료 티어는 제공 모델과 할당량이 수시로 바뀌므로, 실행할 때마다 지금 쓸 수 있는
무료 모델을 탐색하고 사용자가 그중 하나를 고르는 단계를 파이프라인 앞에 둔다.

기존 `fiftybox-execute`는 Pi CLI의 `opencode-go` 프로바이더(유료)를 쓴다. 이 스킬은
그 경로를 전혀 건드리지 않는다.

## 배경 사실

설계 시점(opencode 1.14.41, Pi CLI 기준)에 확인한 것:

- `opencode-go`는 opencode CLI가 아니라 **Pi CLI의 프로바이더**다. `pi --list-models`에
  나타난다. 무료 모델(`opencode/*`)은 Pi 쪽에 없고 **opencode CLI로만** 닿는다.
- `orchestrate.py:82`의 기존 `opencode` 어댑터는 현재 그대로면 실패한다. `opencode run`에
  `--print` 플래그가 존재하지 않는다(`--format default|json`으로 대체됨).
- 비대화식 실행에서 파일을 편집하려면 `--dangerously-skip-permissions`가 필요하다.
- `opencode models <provider> --verbose`는 모델 ID 한 줄 + JSON 블록이 반복되는 형태로
  `cost`, `limit.context`, `capabilities.toolcall`, `status`를 준다. 전용 `--json` 플래그는 없다.
- **비용 0만으로 무료를 판별하면 안 된다.** `openai/gpt-5.6-pro`, `zai/glm-4.5-flash` 등도
  `cost.input == 0`으로 나오는데 이는 무료가 아니라 구독 인증이라 단가가 안 붙은 것이다.
  이를 잡으면 사용자의 유료 할당량을 소모한다.
- 이름의 `-free` 접미사로 판별해도 안 된다. `opencode/big-pickle`은 접미사 없이 무료다.

## 결정 사항

| 항목 | 결정 |
|---|---|
| 스킬 형태 | fiftybox 레포에 새 스킬 `fiftybox-free-execute` (기존 스킬 미변경) |
| 모델 선택 | 탐색 결과를 표로 제시하고 사용자가 선택. 그 실행 내내 고정 |
| 탐색 깊이 | 메타데이터 + 실제 스모크 테스트 |
| 탐색 캐싱 | 없음. 매 실행마다 새로 탐색 |
| 실행 중 모델 사망 | 중단하고 재탐색 결과로 재선택 요청 (자동 승계 없음) |
| 병렬 실행 | 없음. 완전 순차 |
| 에이전트 전환 방법 | `orchestrate.py`에 `--implement-agent` 오버라이드 플래그 추가 |

## 아키텍처

**신규 파일**
- `skills/fiftybox-free-execute/SKILL.md`
- `skills/fiftybox-free-execute/scripts/discover_free_models.py`
- `commands/fiftybox-free-execute.md`
- 테스트 (아래 「테스트 전략」 참조)

**수정 파일**
- `skills/fiftybox-orchestration/scripts/orchestrate.py`
- `skills/fiftybox-orchestration/config.example.json`

**구성 요소별 책임**

| 구성요소 | 책임 |
|---|---|
| `discover_free_models.py` | opencode 무료 모델 탐색 + 스모크 테스트 → JSON 출력. 그 외 아무 일도 안 함 |
| `SKILL.md` | 탐색 결과 제시 → 선택 수령 → 선택된 모델로 orchestrate.py를 순차 호출하는 워크플로 |
| `orchestrate.py` 수정 | ① `--implement-agent` 오버라이드 ② `opencode` 어댑터 커맨드 수정 |

`discover_free_models.py`는 orchestrate.py를 모르고, orchestrate.py는 무료 모델 개념을
모른다. 둘의 유일한 접점은 SKILL.md가 넘기는 모델 ID 문자열이다.

**데이터 흐름**

```
사용자 → SKILL.md
  └→ discover_free_models.py → {metadata_degraded, candidates:[...]}
  └→ 사용자에게 표 제시 → 모델 ID 확정 (예: opencode/mimo-v2.5-free)
  └→ orchestrate.py --phase setup
  └→ Claude가 테스트 작성 (Red)
  └→ orchestrate.py --phase implement --implement-agent opencode
         --model <선택> --skip-verify          ← 태스크당 1회, 순차
  └→ Claude 리뷰 게이트 → 다음 태스크
  └→ review-test → complete → deploy → cleanup
```

## 모델 탐색·선택

### `discover_free_models.py`

1. **메타데이터 수집** — `opencode models opencode --verbose --refresh`.
   모델 ID 라인(`^opencode/<id>$`) 기준으로 분할하고 각 JSON 블록을 `json.loads`.

2. **필터** — 모두 만족해야 후보:
   - `providerID == "opencode"` (스코프 고정. 다른 프로바이더는 비용 0이어도 제외)
   - `cost.input == 0` AND `cost.output == 0`
   - `capabilities.toolcall == true` (파일 편집 불가 모델은 구현 에이전트로 못 씀)
   - `status == "active"`

   모델 이름의 `-free` 접미사는 보지 않는다.

3. **파싱 실패 폴백** — 한 블록도 파싱되지 않으면 평문 `opencode models opencode` 목록으로
   후퇴하고 `metadata_degraded: true`를 실어 보낸다. 이 경우 `context`와 `toolcall`은
   `null`로 두고 SKILL.md가 `unknown`으로 표시한다. 조용히 빈 목록을 반환하지 않는다.

4. **스모크 테스트** — 후보마다
   `opencode run --model <id> --format json "reply with exactly: OK"`를 **임시 디렉터리에서**
   실행한다. 편집이 없으므로 권한 플래그는 붙이지 않는다.
   - 타임아웃 30초, 동시 실행 최대 4개
   - 분류: `ok` / `rate_limited` (출력에 `429`·`rate limit`·`quota`·`insufficient`) /
     `error` / `timeout`
   - 응답 지연(`latency_ms`) 기록

5. **출력** — stdout에 JSON 한 덩어리:

   ```json
   {
     "metadata_degraded": false,
     "candidates": [
       {"id": "opencode/mimo-v2.5-free", "context": 200000,
        "toolcall": true, "smoke": "ok", "latency_ms": 1840}
     ]
   }
   ```

   정렬: `smoke == "ok"` 우선, 그다음 `context` 큰 순.

### SKILL.md의 선택 단계

- JSON을 표로 렌더링해 제시하고 사용자 선택을 받는다.
- `smoke == "ok"`인 후보가 하나도 없으면 목록과 각 실패 사유를 보여준 뒤 **중단**한다.
  유료 모델로 임의 전환하지 않는다.
- 선택된 ID는 그 실행 내내 고정된다.
- 탐색은 `--phase setup` 이전에 일어나므로 `artifactDir`이 아직 없다. 탐색 결과와 선택은
  메모리에 들고 있다가 setup 완료 직후 `<artifactDir>/model-choice.json`에 기록한다.

## orchestrate.py 수정

### 1. `--implement-agent` 플래그 추가

`load_agent_config()` 결과의 `implement_agent` 키를 호출 단위로 덮어쓴다.

- 값은 `agents` 딕셔너리에 존재하는 이름이어야 하며, 없으면 기존과 동일한 에러로 실패한다
  (`orchestrate.py:1159`의 검증 루프를 그대로 통과시킨다).
- 플래그 미지정 시 `config.json` 값을 그대로 쓴다. 따라서 `fiftybox-execute`와
  `fiftybox-orchestration`의 동작은 완전히 불변이다.
- `explore_agent`는 건드리지 않는다. 이 스킬은 탐색 페이즈를 쓰지 않는다.

### 2. `opencode` 어댑터 커맨드 수정

`orchestrate.py:82`의 `BUILTIN_AGENTS`와 `config.example.json` 양쪽:

```
현재: ["opencode","run","--model","{model}","--print","{prompt}\n{task}"]
수정: ["opencode","run","--model","{model}","--dangerously-skip-permissions","{prompt}\n{task}"]
```

`--print`는 현재 opencode에 존재하지 않아 즉시 실패한다.
`--dangerously-skip-permissions`는 비대화식 실행에서 편집 승인을 받을 방법이 없어 필수다.
이 플래그의 위험 범위는 실행 위치가 orchestrate가 만든 **격리된 git 워크트리**라는 점과,
안전 계약이 커밋·푸시·배포를 금지한다는 점으로 제한된다.

`--format`은 기본값(`default`)을 유지한다. 기존 페이즈들이 에이전트 stdout을 사람이 읽는
텍스트로 다루기 때문이다.

## 실행 파이프라인

`fiftybox-execute`와 동일하되 병렬 실행을 제거한다.

| 단계 | 내용 |
|---|---|
| 0 | 무료 모델 탐색 → 사용자 선택 |
| 1 | 설계 문서 수집 → `<artifactDir>/design.md` |
| 2 | `--phase setup` |
| 3 | 태스크 분해. 의존성 그래프는 만들되 **위상 정렬된 순차 목록**으로 평탄화 → `<artifactDir>/task-list.md` |
| 4 | Claude가 해당 태스크의 실패하는 테스트 작성 (Red) + 실제 실패 확인 |
| 5 | `--phase implement --implement-agent opencode --model <선택> --skip-verify` — 태스크 1개 |
| 6 | Claude 리뷰 게이트 |
| 7 | 남은 태스크가 있으면 4로 복귀 |
| 8 | `--phase review-test --skip-codex-review` → `complete` → `deploy` → `cleanup` |

`fiftybox-execute`의 Agent 툴 병렬 디스패치, 파일 소유권 규칙, 배치 충돌 해소 절은
**전부 삭제한다.** 순차 실행에서는 죽은 규칙이고 남겨두면 잘못 참조된다.

### 리뷰 게이트 (단계 6)

`fiftybox-execute`의 3단계(테스트 결과 / 스펙 준수 / 통합 확인)에 한 가지를 추가한다:

- **테스트 무력화 검사** — 테스트를 통과시키려고 테스트 자체를 약화시켰거나
  (`assert True`, 스킵 마킹, 단언 삭제) 스텁만 채워 넣었는지 확인한다.
  발견 시 되돌리고 피드백과 함께 재시도한다.

무료 모델의 낮은 지시 준수율을 감안한 것이다.

## 실패 처리

### 모델 소진/장애

`fiftybox-execute`의 Model Unavailable 프로토콜을 재사용하되, 재선택 목록을
`pi --list-models`가 아니라 `discover_free_models.py` 재실행 결과로 채운다.

```
[implement] 모델 opencode/mimo-v2.5-free 에 접근할 수 없습니다.
사유: rate limit exceeded (429)

현재 사용 가능한 무료 모델:
1. opencode/nemotron-3-ultra-free   (ctx 1.0M, 응답 2.1s)
2. opencode/laguna-s-2.1-free       (ctx 256K, 응답 3.4s)

어떤 모델로 재시도할까요? (번호 또는 "취소")
```

- 재선택하면 **실패한 그 태스크만** 새 모델로 재실행한다. 통과한 태스크는 건드리지 않는다.
- 이후 태스크는 새 모델로 계속 진행하고, 교체 이력을 `model-choice.json`에 append 한다.
- 스모크가 `ok`인 후보가 하나도 없으면 보고하고 **중단**한다. 유료 폴백은 제안하지 않는다.
  비용 절감이 이 스킬의 존재 이유다.

### 실패 감지

opencode CLI는 rate limit을 종료 코드로 구분해주지 않는다. stdout/stderr에서
`429` / `rate limit` / `quota` / `insufficient` 패턴을 매칭해 `model_unavailable`로 분류한다.
매칭되지 않는 실패는 일반 구현 실패로 다뤄 기존 1회 자동 재시도 경로를 탄다.

## 안전 계약

`fiftybox-orchestration`에서 상속하고 다음을 추가한다.

- `.omx/artifacts/` 밖 직접 편집 금지
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- opencode 에이전트는 커밋·푸시 금지. `--dangerously-skip-permissions`는 격리된 워크트리
  안에서만 유효하다
- Claude는 구현 코드를 직접 쓰지 않는다. 테스트 파일과 아티팩트 문서만 쓴다
- opencode는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행한다
- 탐색 스모크 테스트는 항상 임시 디렉터리에서 실행한다. 사용자 리포지토리를 건드리지 않는다
- 실패 시 조용히 복구하지 않고 선택지를 제시한다

## 테스트 전략

`fiftybox/tests/`와 `skills/fiftybox-orchestration/tests/` 관례를 따른다.

### `discover_free_models.py`

파싱·필터·분류를 순수 함수로 분리해 서브프로세스 없이 테스트한다.

- 실제 `opencode models --verbose` 출력을 픽스처로 저장해 후보 추출 검증
- 필터 회귀 (가장 중요):
  - `openai/gpt-5.6-pro` — cost 0이지만 프로바이더가 달라 **제외**
  - `zai/glm-4.5-flash` — cost 0이지만 프로바이더가 달라 **제외**
  - `opencode/big-pickle` — `-free` 접미사가 없지만 **포함**
- `capabilities.toolcall == false` 모델 제외
- `status != "active"` 모델 제외
- 파싱 전면 실패 시 `metadata_degraded: true` + 평문 폴백 목록
- 스모크 분류: 429 출력 → `rate_limited`, 타임아웃 → `timeout`
- 정렬: `ok` 우선, 그다음 컨텍스트 큰 순
- 스모크 서브프로세스는 목으로 대체한다. 네트워크에 의존하는 테스트는 만들지 않는다

### `orchestrate.py` 변경

- `--implement-agent opencode` 지정 시 실제로 opencode 커맨드가 빌드되는지
- 플래그 미지정 시 `config.json` 값이 그대로 쓰이는지 (**기존 스킬 회귀 방지 — 필수**)
- `agents`에 없는 이름을 넘기면 기존과 동일한 에러로 실패하는지
- `build_agent_cmd`가 opencode 템플릿에서 `--print` 없이
  `--dangerously-skip-permissions`를 포함하는지
- 기존 `test_orchestrate.py` / `test_agent_config.py` 전체가 계속 통과하는지

### 수동 검증

작은 실제 태스크로 무료 모델 하나를 골라 단계 4→5→6 사이클을 끝까지 1회 돌린다.
CLI 플래그 조합은 목으로 검증되지 않기 때문이다.

## 범위 밖

- 무료 모델 자동 선택·자동 폴백 (사용자 선택으로 고정)
- 탐색 결과 캐싱
- 병렬 배치 실행
- 유료 모델 폴백
- `fiftybox-execute` / `fiftybox-orchestration`의 동작 변경
- opencode 외 프로바이더의 무료 모델 지원
