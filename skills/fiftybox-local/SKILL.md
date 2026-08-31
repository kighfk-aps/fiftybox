---
name: fiftybox-local
description: Use when implementation should run on local or free providers (opencode free-tier, Modal Qwen3.8-27B, NVIDIA NIM via Pi CLI) with dynamic parallelism tied to healthy model count. Also when the user invokes /fiftybox-local or $fiftybox-local.
---

# Fiftybox Local

로컬·무료 provider로 구현 페이즈를 돌린다. 후보는 매 실행 실측 탐색한다 —
무료 티어는 제공 모델과 할당량이 수시로 바뀐다.

**핵심 루프:** 오케스트레이터(Claude/Codex)가 실패하는 테스트 작성(Red) → provider가 통과시킴(Green) → 오케스트레이터 리뷰

**실행 방식:** 동적 병렬. 이번 실행에서 가용한(healthy) distinct 모델 수가
배치의 최대 동시 실행 수다. 모델 1개면 순차, N개면 최대 N개 병렬 — 배치 내
각 태스크는 서로 다른 모델에 배정한다(같은 모델에 태스크를 몰지 않는다 —
무료 티어 분당 요청 제한, Modal 컨테이너 자원 경합을 피한다). 배치 크기는
후보 모델 수와 같다.

---

## ⛔ 절대 금지

**오케스트레이터는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다.
Claude/Codex가 이 스킬에서 쓸 수 있는 파일은 두 가지뿐이다:
1. 테스트 파일 (Red 페이즈)
2. 아티팩트 문서 (`<artifactDir>/design.md` 등)

orchestrate.py가 실패하면 사용자에게 보고한다. 대신 구현하지 않는다.

---

## 호출

```
/fiftybox-local "<작업 설명>" [--provider <id> --model <id> ...]
$fiftybox-local "<작업 설명>" [--provider <id> --model <id> ...]
```

`--provider`/`--model`을 명시하면 탐색을 건너뛰고 그 목록만 후보로 쓴다(수동
모드). 생략하면 아래 후보 풀 구성대로 매번 탐색한다.

---

## 후보 풀 구성

**시작 전에 `~/.claude/fiftybox-config.json`을 읽는다** (`/fiftybox-config`
스킬이 관리한다). 이 설정으로 아래 세 후보 원천을 켜고 끈다:

- `providers.opencode.enabled`가 `false`면 1번(무료 티어 탐색) 자체를 생략한다.
- `providers.pi.backends.modal-qwen38`의 `models`에 켜진 모델이 하나도 없으면
  2번(Modal 항상 포함)을 생략한다 — 예를 들어 지출을 잠깐 막고 싶을 때 끌 수
  있다. `providers.pi.enabled`(Pi CLI 전체 스위치)는 이 판단에 영향을 주지
  않는다 — Modal은 Pi CLI 구독과 무관한 별도의 pay-per-use 배포이기
  때문이다.
- `providers.pi.backends.nvidia-nim`의 `models`에 켜진 모델이 하나도 없으면
  3번(NIM 항상 포함)을 생략한다.

설정 파일이 없으면 아직 `/fiftybox-config`를 실행한 적이 없다는 뜻이니, 리포
기본값(셋 다 켜짐)을 그대로 쓴다.

**각 후보는 (agent, provider, model) 3튜플이다.** `orchestrate.py`의
`--implement-agent`는 에이전트 레지스트리 키(`opencode`/`pi`/`piqwen` 등)만
받는다 — provider 이름(`nvidia-nim`, `modal-qwen38`)을 그 자리에 넣으면 setup이
"is not in the agents list"로 하드 실패한다. `--provider`는 별개 플래그이고
기본값이 `opencode-go`라서, 빠뜨리면 의도한 백엔드가 아니라 조용히
`opencode-go`로 나간다. 세 후보 원천은 다음과 같이 고정된다:

| 후보 원천 | `IMPL_AGENT`(`--implement-agent`) | `IMPL_PROVIDER`(`--provider`) | `IMPL_MODEL`(`--model`) |
|---|---|---|---|
| opencode 무료 티어 | `opencode` | (전달해도 무시됨 — 템플릿이 `{provider}`를 안 씀) | 탐색된 `opencode/<모델>` |
| Modal Qwen | `piqwen` | `modal-qwen38` | `qwen3.8-27b-q4_k_m` |
| NVIDIA NIM | `pi` | `nvidia-nim` | config의 `nvidia-nim.models`에서 켜진 모델 |

Step 5/7/9의 모든 디스패치 명령은 이 표의 세 값을 **전부** 넘겨야 한다. 하나만
빠져도 오작동(잘못된 백엔드) 또는 하드 실패(잘못된 에이전트 이름) 중 하나로
이어진다.

1. (`providers.opencode.enabled`가 `true`일 때만) `discover_free_models.py`로
   opencode Zen 무료 티어를 실측 탐색한다
   (각 후보에 실제 호출 1회 — 수십 초 걸릴 수 있다). `smoke: ok`인 것만
   후보로 삼는다. 이 후보들 사이에서도 배치 도중 하나가 막히면
   [opencode 폴백 순서](#opencode-폴백-순서)를 따라 순차 전환한다 — 자세한
   내용은 해당 섹션 참고.

```bash
python3 ~/.claude/skills/fiftybox-local/scripts/discover_free_models.py
```

2. (`providers.pi.backends.modal-qwen38`가 config에서 켜져 있을 때만)
   **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_AGENT=piqwen`, `IMPL_PROVIDER=modal-qwen38`,
   `IMPL_MODEL=qwen3.8-27b-q4_k_m`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만
   가용성 자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).
3. (`providers.pi.backends.nvidia-nim`가 config에서 켜져 있을 때만)
   **NIM을 탐색 없이 항상 후보 1개로 추가한다** — `IMPL_AGENT=pi`,
   `IMPL_PROVIDER=nvidia-nim`, `IMPL_MODEL=<config의 `nvidia-nim.models`에서
   켜진 첫 모델, JSON 키 순서 기준>`, `IMPL_TIMEOUT=600`. 이 후보 1개는
   내부적으로 [NIM 폴백 순서](#nim-폴백-순서)를 따라 순차 재시도한다 — 자세한
   내용은 해당 섹션 참고.
4. `metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

   > opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로
   > 진행하며 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

5. `smoke: ok` 후보(설정에서 켜진 opencode 무료 + modal-qwen38 + nvidia-nim)가
   하나도 없으면 중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.**
   config에서 셋 다 껐다면 `/fiftybox-config`로 최소 하나는 켜야 한다고
   안내한다.

수동 모드(`--provider`/`--model` 직접 지정)에서는 이 탐색 전체를 건너뛰고
지정된 provider/model 쌍들을 그대로 후보로 쓴다.

---

## Modal Qwen 웨이크업 절차

`modal-qwen38`이 이번 배치에 포함될 때만 그 레인 앞에 적용한다. 다른 레인의
진행을 막지 않는다 — 독립 detached 프로세스이므로.

Modal serverless(ap-south)는 유휴 시 컨테이너가 0으로 스케일된다. 배치
implement 디스패치, fix 재시도, Phase 6 auto-retry, Phase 7b deploy — **매
디스패치 전에** 웨이크업한다:

```bash
nohup bash -c '
  token="$(security find-generic-password -a "$USER" -s pi-modal-qwen38-proxy-token -w)" || exit 1
  curl --silent --output /dev/null --write-out "%{http_code}" \
    --connect-timeout 15 --max-time 900 --retry 8 --retry-all-errors --retry-delay 2 --fail \
    -H "Authorization: Bearer $token" \
    https://kighfk--modal-qwen38-27b-serve.ap-south.modal.run/v1/models
' > "<artifactDir>/modal-wake-<N>.out" 2>&1 &
```

**정확히 세 번**, t+75초/t+120초/t+150초에 확인한다(루프로 폴링하지 않는다).
쉘 명령 타임아웃은 최소 180초로 잡는다:

```bash
wake="<artifactDir>/modal-wake-<N>.out"
elapsed=0
for extra in 75 45 30; do
  sleep "$extra"
  elapsed=$((elapsed + extra))
  code="$(tr -d '[:space:]' < "$wake" 2>/dev/null || true)"
  echo "wake-check t+${elapsed}s: ${code:-<empty>}"
  if [ "$code" = "200" ]; then echo READY; break; fi
done
```

`200`이 나오면 즉시 디스패치한다(남은 체크를 기다리지 않는다). 세 번째
체크 후에도 `200`이 아니면 디스패치하지 않고 보고한다 — [실패 처리](#실패-처리)
기준으로 토큰/Keychain 문제는 `auth`, 그 외는 `unknown`으로 분류한다. 모델
교체를 제안하지 않는다(Modal은 provider가 하나뿐이라 교체할 다음 모델이
없다).

`--phase implement`/`--phase deploy` 호출에 `--implement-agent piqwen
--provider modal-qwen38 --implementation-timeout 1800`을 **셋 다** 추가한다.
`--provider`를 빠뜨리면 웨이크업한 Modal 엔드포인트가 아니라 기본값
`opencode-go`로 조용히 나간다. `--phase setup`에도 [Step 2](#step-2-setup-phase-0)의
규칙대로 `--implement-agent piqwen --provider modal-qwen38`을 넘긴다.

---

## NIM 폴백 순서

`nvidia-nim` 후보 하나에는 실제로 모델 여러 개가 묶여 있다. 순서는
`providers.pi.backends.nvidia-nim.models`의 JSON 키 순서(=`/fiftybox-config`
TUI에서 조정 가능)를 그대로 따른다 — 리포 기본값은:

1. `openai/gpt-oss-120b` — executor 실측 테스트에서 속도·정답률 1순위
2. `moonshotai/kimi-k3`
3. `poolside/laguna-xs-2.1`
4. `minimaxai/minimax-m3`

**⚠️ NIM의 40 RPM과 무료 크레딧은 계정 단위 풀이다.** [실패 처리](#실패-처리)
분류표에서 `window`/`credit`/`auth`로 분류되는 신호(429·rate limit·크레딧
소진·인증 실패)는 계정 전체가 막힌 것이라 **목록의 다음 모델로 넘어가도
풀리지 않는다.** 이 경우 목록을 순회하지 말고 곧장 NIM lane 전체를 "소진"으로
처리하고 [모델 소진 처리](#모델-소진-처리)로 넘어간다.

**목록을 순서대로 재시도하는 경우는 `model` 분류(그 모델만 배포 중단·교체·거부)
일 때뿐이다:**
1. 실패한 태스크를 목록의 **다음 모델**로 재디스패치한다
   (`IMPL_PROVIDER=nvidia-nim`, `IMPL_MODEL=<다음 모델>`는 그대로, 나머지
   인자는 동일). 이 전환은 [안전 계약](#안전-계약)의 "자동 재시도는 태스크당
   1회만"과 별개다 — NIM 리스트 소진 전까지는 provider 내부 전환이지
   재시도가 아니다.
2. 목록의 모든 모델을 `model` 분류로 다 소진하면, 그때 NIM lane 전체를
   "소진"으로 처리하고 [모델 소진 처리](#모델-소진-처리) 절차로 넘어간다.
3. 어느 단계에서 전환했든 `<artifactDir>/model-choice.json`의 `history`에
   `{"from": "nvidia-nim/<이전 모델>", "to": "nvidia-nim/<다음 모델>" 또는
   "<다른 provider>", "reason": "model" | "window" | "credit" | "auth" |
   "timeout"}`을 append한다.

형제 레인(opencode 후보, modal-qwen38)은 이 전환 동안 영향받지 않고 계속
진행한다.

---

## opencode 폴백 순서

opencode 후보는 매 실행 `discover_free_models.py`가 실측한 healthy 모델
목록이다. 스모크 테스트를 통과했더라도 무료 티어 한도는 실행 도중에도
소진되거나 배포가 바뀔 수 있다.

**한계를 먼저 밝힌다.** 이 스킬의 핵심 원칙은 "배치 크기 = 후보 수, 라운드
안 각 태스크는 서로 다른 모델"이다(`:13-17`). 그래서 **꽉 찬 라운드에서는
opencode 후보가 이미 전부 사용 중이라 넘어갈 데가 없다.** 이 폴백은 라운드가
후보 수보다 작을 때(마지막 라운드, 태스크가 적을 때)만 실질적으로 의미가
있다. 갈 곳이 없을 때는 3번의 보류(defer) 규칙을 따른다 — 조용히 레인
소진으로 떨어뜨리지 않는다.

**발동 조건**은 [실패 처리](#실패-처리)의 `model`/`model_busy` 분류일 때만이다.
opencode 무료 티어의 한도는 모델별이 아니라 계정 단위인 경우가 많으므로,
문구 없는 순수 429는 `window`로 분류하고 다음 모델로 옮기지 않는다 — 곧장
opencode 레인 전체를 소진 처리한다.

**절차 (`model`/`model_busy`일 때만):**
1. 막힌 모델을 이번 실행의 차단 목록에 넣는다([모델 소진 처리](#모델-소진-처리)
   참고). 재탐색에서 다시 `smoke: ok`로 나와도 이번 실행 동안은 재배정하지
   않는다.
2. 정렬 순서(`sort_candidates` 결과: smoke: ok 우선, 그다음 context
   내림차순)상 다음 opencode 후보 중 **차단 목록에 없고 이번 라운드의 다른
   태스크가 쓰고 있지 않은** 모델로 재디스패치한다.
3. 그런 모델이 없으면: 이번 라운드에 아직 배정되지 않은 다른 lane(Modal,
   NIM)이 비어 있으면 그쪽으로 재배정한다. 그것도 없으면 이 태스크를 **다음
   라운드로 미룬다(defer)** — 형제 태스크가 끝나면 모델이 비므로, 다음
   라운드 시작 시 차단 목록에 없는 healthy opencode 모델에 재배정할 수 있다.
   "같은 모델에 태스크를 몰지 않는다"는 원칙은 *동시* 실행에 대한 것이라
   라운드를 넘긴 재사용은 위반이 아니다. 남은 라운드가 없거나 보류가 반복되면
   그때 opencode 레인 전체를 "소진"으로 처리하고 [모델 소진
   처리](#모델-소진-처리)로 넘어간다.
4. 전환할 때마다 `<artifactDir>/model-choice.json`의 `history`에
   `{"from": "opencode/<이전 모델>", "to": "opencode/<다음 모델>" 또는
   "<다른 provider>" 또는 "deferred", "reason": "model" | "model_busy" |
   "window"}`을 append한다.

형제 레인(modal-qwen38, nvidia-nim)은 이 전환 동안 영향받지 않고 계속
진행한다.

---

## 실패 처리

`orchestrate.py`는 구현 경로에 실패 분류 필드를 만들지 않는다.
`classify_codex_error`/`CODEX_API_ERROR_PATTERNS`는 존재하지만 Codex 리뷰
경로 전용이고 `phase_implement`에서 호출되지 않는다. HTTP 429와 진짜 구현
실패를 프로그램적으로 구분할 방법이 없다 — 로그를 직접 읽어야 한다. 아래
표로만 분류하고, **표에 없는 근거로 임의로 모델을 바꾸지 않는다.**

### 근거 파일

| 근거 | 신뢰도 | 비고 |
|---|---|---|
| `<artifactDir>/implement-task-N.out`의 `EXIT_CODE=` 줄 | **높음 — 유일한 레인별 근거** | Step 5의 디스패치 래퍼가 남긴다 |
| `.out` 본문의 provider CLI 원문 | 높음 | 429·모델 거부 문구는 여기서만 보인다 |
| `<artifactDir>/summary.json` | **쓰지 않는다** | 이 스킬은 `task-batches.md`에 JSON 블록을 안 쓰므로 모든 레인이 orchestrate.py의 단일 호출 경로를 타고, **같은 `summary.json`을 동시에 read-modify-write한다.** 마지막에 끝난 레인이 덮어써서 레인별 판단 근거가 못 된다 |
| `<artifactDir>/implement-log.md` | **쓰지 않는다** | 같은 이유로 레인끼리 충돌한다 |

> 워크트리도 형제 레인과 공유하므로 `changedFiles`/`no_changes` 판정은 형제의
> 변경에 오염될 수 있다. 실제 성공 여부는 Step 6의 테스트 실행으로 다시
> 확인한다.

### 분류표

| 로그 신호 | 분류 | 범위 |
|---|---|---|
| `Not authenticated`, 401, Keychain 조회 실패 | `auth` | 계정 |
| `insufficient credit`, `balance`, 402, `quota exceeded` | `credit` | 계정 |
| 문구 없는 순수 429, `rate limit`, `usage limit`, `daily`, `weekly` | `window` | 계정 |
| `Unknown model`, 404, 모델 ID 거부, `deprecated` | `model` | 모델 |
| 503, `overloaded`, `capacity`, `queue full` | `model_busy` | 모델 |
| `EXIT_CODE=124` | `timeout` | 태스크 |
| `EXIT_CODE=3` (변경 파일 없음) | `no_changes` | 태스크 |
| `EXIT_CODE=1` + `not in the agents list`, `unrecognized arguments`, 소유권 위반 | `orchestrate` | 스킬/설정 버그 |
| 그 외 | `unknown` | 태스크 |

### 범위별 대응

**계정 단위(`auth`·`window`·`credit`) — 그 provider 레인 전체를 즉시 소진
처리한다.** 같은 레인의 남은 태스크를 새로 디스패치하지 않는다(이미 돌고
있는 프로세스는 죽이지 않고 결과만 받는다). **모델 교체를 해결책으로
제시하지 않는다** — 한도는 계정 단위 풀이므로 다음 모델도 같은 이유로
막힌다.
- `auth` — 해당 provider의 로그인/토큰을 안내한다(Modal은 Keychain의
  `pi-modal-qwen38-proxy-token`)
- `window` — 리셋 대기 또는 중단을 사용자에게 묻는다
- `credit` — 충전이 필요함을 명시한다

**형제 레인은 영향받지 않고 계속 진행한다** — NIM이 계정 단위로 막혀도
Modal·opencode는 그대로 돈다. 모든 레인이 막혔을 때만 전체를 중단하고
보고한다.

**모델 단위(`model`·`model_busy`) — 그 모델만 차단 목록에 넣고 같은 레인의
다음 모델로 스왑한다.** 절차는 [NIM 폴백 순서](#nim-폴백-순서) /
[opencode 폴백 순서](#opencode-폴백-순서)를 따른다.

**태스크 국소(`timeout`·`no_changes`·`unknown`) — 모델을 바꾸지 않는다.**
- `timeout` — Modal이면 웨이크업을 다시 확인, 아니면
  `--implementation-timeout` 상향 후 1회 재시도
- `no_changes` — 모델이 지시를 무시했거나 프롬프트가 부실하다는 신호. 같은
  3축으로 재시도하고, 반복되면 모델 단위로 취급해 다음 모델로 넘긴다
- `unknown` — 로그 원문과 함께 사용자에게 보고한다. 임의로 모델을 바꾸지 않는다

**`orchestrate` — 스킬/설정 버그다.** 파이프라인을 멈추고 그대로 보고한다.
흔한 원인: `--implement-agent`에 provider 이름(`nvidia-nim` 등)을 잘못 넣음,
`~/.claude/skills/orchestrate/config.json` 유실로 `piqwen` 미정의.

### Failure Report Format

```markdown
**Round N, Task M 실패**

**레인:** <agent>/<provider>/<model>
**분류:** <auth | window | credit | model | model_busy | timeout | no_changes | orchestrate | unknown>
**범위:** <계정 | 모델 | 태스크 | 스킬 버그>
**근거:** <.out 로그에서 인용한 줄 + EXIT_CODE>
**영향:** <이 레인 / 형제 레인에 미치는 영향>

**추천 행동:**
1. <선택지 1>
2. <선택지 2>
```

어떤 실패에서도 오케스트레이터가 대신 구현하는 것은 금지다.

---

## 워크플로

### Step 1: 설계 수집

사용자에게 설계 문서를 요청한다. 다음 중 아무거나 받는다:
- 파일 경로 (`./design.md`, `./PRD.md`, `./plan.md`)
- 대화 중 인라인 텍스트
- "현재 디렉터리 컨텍스트 사용" — 관련 파일을 읽어 설계로 요약

설계를 `<artifactDir>/design.md`에 쓴다(artifactDir은 Step 2에서 생긴다).

**`design.md`는 필수다.** `--skip-verify`를 줘도 구현 페이즈가 이 파일을 읽는다.
없으면 `design.md not found in artifact directory`로 즉시 실패한다.

### Step 2: Setup (Phase 0)

setup은 **이번 실행 후보 풀에 실제로 포함된 distinct `IMPL_AGENT` 값마다** 한
번씩 검증한다. 예: 후보가 opencode 2개 + modal-qwen38 + nvidia-nim이면 distinct
에이전트는 `opencode`, `piqwen`, `pi` 세 개다. Modal이 config에서 꺼져 있어
이번 후보 풀에 없다면 `piqwen`을 검증하지 않는다.

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)" \
  --implement-agent "<후보 풀의 distinct 에이전트 중 하나>" \
  --provider "<그 에이전트가 쓸 IMPL_PROVIDER>"
```

여러 개면 순서대로 반복 호출한다(각 호출은 독립적으로 성공/실패한다).

**setup이 확인하는 것 두 가지:**
1. `--implement-agent` 값이 에이전트 레지스트리(`~/.claude/skills/orchestrate/config.json`
   + 빌트인)의 키인지 — 아니면 exit 1. 자격증명이나 모델 가용성은 보지
   않는다. 바이너리 존재 여부는 경고만 하고 실패시키지 않는다.
2. **`pi --list-models <provider>`가 항상 돈다.** `explore_agent`가
   `--explore-agent` 같은 override 플래그 없이 기본값 `pi`로 고정돼 있어서,
   `--implement-agent`로 뭘 넘기든 `"pi"`가 검증 대상 집합에 항상 포함되기
   때문이다. 이 검사는 `--provider`(생략 시 기본값 `opencode-go`)가 실제
   Pi 백엔드 목록에 있는지 본다 — 없으면 exit 1. **그래서 `--provider`를
   반드시 넘겨야 진짜 preflight가 된다.** 생략하면 이번 실행에 안 쓸
   `opencode-go`만 검증하고 정작 쓸 `nvidia-nim`/`modal-qwen38`은 확인 없이
   지나간다.

Pi 백엔드 후보가 둘(Modal + NIM) 이상이면 한 번의 setup 호출로는 하나만
검증된다. 나머지는 검증되지 않은 채 남고, 문제가 있으면 Step 5에서
[실패 처리](#실패-처리)의 `orchestrate`/`model`로 드러난다.

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다. 설계 문서를 복사하고
후보 풀을 `<artifactDir>/model-choice.json`에 3축(agent/provider/model)으로
기록한다(이 파일은 orchestrate.py가 읽거나 쓰지 않는 순수 수기 감사 로그다 —
[모델 소진 처리](#모델-소진-처리) 참고).

### Step 3: 태스크 분해 (동적 병렬)

설계를 원자적 구현 단위로 쪼갠다. 배치 크기가 후보 모델 수에 좌우되므로
**배치 단위**로 만든다. 라운드 안 각 태스크는 서로 다른 모델에 배정한다:

```markdown
## Task Batches (동적 병렬 — 후보 3개 기준 예시)

### Round 1 (최대 3개 병렬, 서로 다른 모델)
- Task A → agent=opencode, provider=(무시됨), model=opencode/nemotron-3-ultra-free
- Task B → agent=opencode, provider=(무시됨), model=opencode/mimo-v2.5-free
- Task C → agent=piqwen, provider=modal-qwen38, model=qwen3.8-27b-q4_k_m

### Round 2 (남은 태스크, 다시 최대 3개 병렬)
- Task D → agent=opencode, provider=(무시됨), model=opencode/nemotron-3-ultra-free
```

**`<artifactDir>/task-batches.md`에 ```json 태스크 블록을 넣지 않는다.** 넣으면
orchestrate.py가 각 호출을 순차 다중 태스크 모드로 처리해서, 병렬로 뜬 레인
각각이 전체 태스크 목록을 통째로 실행하게 된다 — 같은 워크트리를 N중으로
겹쳐 쓴다. 자세한 이유는 [실패 처리](#실패-처리)의 근거 파일 절 참고.

### Step 4: 오케스트레이터가 테스트 작성 (Red)

라운드의 각 태스크에 대해 Claude/Codex 오케스트레이터가 실패하는 테스트를 쓴다.

`<artifactDir>/tests/`와 실제 프로젝트 테스트 디렉터리 양쪽에 쓴다.

**실패하는지 확인한다(Red):**

```bash
<프로젝트 테스트 명령> <테스트 파일>
```

구현 전에 통과하면 다시 쓴다.

### Step 5: 구현 (Green) — 라운드 병렬

라운드 내 각 태스크를 배정된 (agent, provider, model) 3튜플로 동시에
디스패치한다. `modal-qwen38`이 배정된 레인은 디스패치 전 웨이크업 절차를
거친다.

**foreground 실행 금지.** `--phase implement`를 foreground로 돌리면 Bash 도구의
10분 한도를 넘겨 파일도 로그도 없이 통째로 죽는다. 반드시 detached로 돌린다.

**`<artifactDir>`은 모든 레인이 공유한다.** `task-batches.md`에 ```json
블록을 넣지 않는 한(**넣지 않는다** — 넣으면 각 레인이 전체 태스크 목록을
통째로 순차 실행해 같은 워크트리를 N중으로 겹쳐 쓴다), 각 레인은
`orchestrate.py`의 단일 호출 경로를 타고 **같은 `summary.json`/
`implement-log.md`를 동시에 read-modify-write한다.** 마지막에 끝난 레인이
덮어쓰므로 이 두 파일은 레인별 판단 근거로 쓸 수 없다. 레인마다 유일하게
안전한 파일은 각자의 `.out`뿐이다. 그래서 종료 코드를 그 파일 안에 직접
남긴다:

```bash
nohup bash -c '
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<IMPL_AGENT>" --provider "<IMPL_PROVIDER>" \
  --model "<IMPL_MODEL>" --skip-verify
echo "EXIT_CODE=$?"
' > "<artifactDir>/implement-task-N.out" 2>&1 &
```

`modal-qwen38` 레인에는 `--implement-agent piqwen --provider modal-qwen38
--implementation-timeout 1800`을 붙인다.

라운드 내 모든 `.out` 파일에 `EXIT_CODE=`가 찍힐 때까지 30~60초 간격으로
폴링한다:

```bash
for f in "<artifactDir>"/implement-task-*.out; do
  printf '%s: %s\n' "$(basename "$f")" \
    "$(grep -o 'EXIT_CODE=[0-9]*' "$f" | tail -1 || echo RUNNING)"
done
```

한 레인의 `EXIT_CODE=`를 확인하면 그 레인만 즉시 [실패 처리](#실패-처리)로
분류하고, 형제 레인의 종료를 기다리지 않고 재디스패치한다. "즉시"는 "그
레인이 끝난 것을 폴링으로 확인한 즉시"를 뜻한다 — 실시간으로 실패를 감시할
방법은 없다.

### Step 6: 오케스트레이터 리뷰 게이트

태스크마다 Claude/Codex 오케스트레이터가 4단계 리뷰를 한다.

**1단계 — 테스트 결과:** Step 4의 테스트를 전부 돌린다. 하나라도 실패하면 실패
출력과 함께 Step 5를 재실행한다.

**2단계 — 테스트 무력화 검사:** provider가 테스트를 통과시키려고 테스트 자체를
약화시켰는지 본다. `git diff`로 테스트 파일 변경을 확인한다:
- 테스트 파일이 수정됐으면 되돌리고 재실행한다
- 단언이 삭제됐거나 `assert True`로 바뀌었는지
- 스킵 마킹(`@pytest.mark.skip`, `xfail`, `it.skip`)이 추가됐는지
- 구현이 스텁만 채우고 실제 동작이 없는지

무료 모델은 지시 준수율이 낮다. 이 단계를 건너뛰지 않는다.

**3단계 — 명세 준수:** 실제 코드 변경(`git diff`)을 태스크 명세와 한 줄씩
대조한다.

**4단계 — 통합 확인:** 선행 태스크와의 인터페이스가 맞는지, 의도치 않은 결합이
생기지 않았는지 확인한다.

문제가 있으면 리뷰 결과를 피드백으로 Step 5를 재실행한다. 두 번째도 실패하면
사용자에게 선택지를 제시한다.

문제가 없으면 다음 라운드로(Step 4-6 반복), 라운드가 모두 끝났으면 Step 7로.

Advisory diff 리뷰는 `fiftybox-execute`와 동일한 자연어 opt-in 트리거를
따른다(`~/.claude/skills/fiftybox-execute/scripts/diff_review.py` 재사용).

### Step 7: Review + Test (Phase 6)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

첫 실패 시 실패한 태스크의 Step 5를 실패 출력과 함께 **1회 자동 재시도**한다.
`--implement-agent`/`--provider`/`--model` **3축 모두** 그 태스크에 배정됐던
값 그대로 재시도한다 — 재시도에서 모델을 바꾸지 않는다(모델 교체는
[실패 처리](#실패-처리)가 모델 단위로 분류했을 때만 한다).

### Step 8: Complete (Phase 7)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

### Step 9: Deploy (Phase 7b)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<IMPL_AGENT>" --provider "<IMPL_PROVIDER>" \
  --model "<IMPL_MODEL>"
```

`modal-qwen38`이면 웨이크업 후 `--implement-agent piqwen --provider
modal-qwen38 --implementation-timeout 1800`.

### Step 10: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

---

## 모델 소진 처리

라운드 중 한 모델이 소진되면 그 태스크만 재배정한다. 형제 레인은 계속
진행한다.

**재배정 규칙:**
1. 방금 실패한 `provider/model`을 **이번 실행 동안 유효한 차단 목록**에
   넣는다(메모리에 두고, `model-choice.json`의 `blocklist` 배열에도 append).
   **재탐색으로 그 모델이 다시 `smoke: ok`로 나와도 이번 실행 동안은 다시
   배정하지 않는다.** opencode 무료 티어는 짧은 창으로 리셋되므로, 이 규칙이
   없으면 방금 막힌 모델을 재탐색이 또 뽑아 같은 실패를 반복하는 루프에
   빠진다.
2. 후보는 **차단 목록에 없고, 계정 단위로 소진되지 않은 레인에 속하며, 이번
   라운드에서 다른 태스크가 쓰고 있지 않은** 모델 중에서만 고른다.
3. 레인이 계정 단위 실패(`auth`/`window`/`credit`)로 닫혔으면 그 레인의
   **모든** 모델이 이번 실행에서 제외된다 — 레인 안에서 다른 모델을 찾지
   않는다.
4. 조건을 만족하는 후보가 없으면 그 태스크를 다음 라운드로 미룬다
   ([opencode 폴백 순서](#opencode-폴백-순서) 3번과 같은 보류 규칙).
5. 남은 라운드도 후보도 없으면 중단하고 보고한다. **유료 모델로 임의
   전환하지 않는다.**

모든 교체는 `<artifactDir>/model-choice.json`의 `history`에, 차단은
`blocklist`에 append한다. **이 파일은 orchestrate.py가 읽지도 쓰지도 않는
순수 수기 감사 로그다** — 여기 뭘 적어도 실행 동작 자체는 바뀌지 않는다.
차단 목록을 실제로 지키는 것은 오케스트레이터(Claude/Codex)의 책임이고, 이
파일은 최종 보고에서 "어떤 태스크가 어떤 모델로 돌았고 왜 바뀌었는지"를
재구성하는 용도다.

---

## 안전 계약

`/fiftybox-orchestration`에서 상속:

- `.omx/artifacts/` 밖 직접 편집 금지. **단 Red 페이즈 테스트 파일은 명시적 예외다**
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- provider는 커밋·푸시하지 않는다
- 자동 재시도는 태스크당 1회만(모델 단위 실패로 인한 provider 내부 모델
  스왑은 이 카운트에 들어가지 않는다 — [NIM](#nim-폴백-순서)/[opencode](#opencode-폴백-순서)
  폴백 참고)
- 실패 시 조용히 복구하지 않고 선택지를 제시한다

이 스킬 고유:

- **Claude/Codex 오케스트레이터는 구현 코드를 직접 쓰지 않는다.** 계획서
  내용, 속도, 모델 가용성과 무관하다
- provider는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행한다
- `--dangerously-skip-permissions`는 orchestrate가 만든 격리된 워크트리 안에서만
  유효하다
- 무료 후보가 모두 막히면 중단한다. 유료 모델로 넘어가지 않는다
- 배치 크기는 후보 모델 수이고, 라운드 안 각 태스크는 서로 다른 모델에 배정한다
- `--implement-agent`에는 에이전트 이름만, `--provider`에는 백엔드 이름만
  넣는다. 섞지 않는다 — [후보 풀 구성](#후보-풀-구성)의 3튜플 표 참고
- Pi 계열 레인(`pi`/`piqwen`)에는 `--provider`를 반드시 명시한다. 생략하면
  기본값 `opencode-go`로 조용히 오배송된다
- 실패 분류는 [실패 처리](#실패-처리) 표로만 한다. 표 밖의 근거로 모델을
  바꾸지 않는다
- 계정 단위 실패(`auth`/`window`/`credit`)에 **모델 교체를 해결책으로
  제시하지 않는다**
- 한 번 실패로 차단된 모델은 이번 실행 동안 재배정하지 않는다
- `--phase implement`는 항상 detached로 돌리고 `EXIT_CODE=` sentinel을 남긴다
- `task-batches.md`에 ```json 태스크 블록을 넣지 않는다
