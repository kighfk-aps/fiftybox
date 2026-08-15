---
name: fiftybox-local
description: 로컬·무료 provider(opencode 무료 티어, Modal Qwen3.8-27B)로 구현하는 동적 병렬 TDD 실행 파이프라인 — 가용 모델 수만큼 병렬도를 조절한다. Claude가 테스트를 쓰고 provider가 구현하고 Claude가 리뷰한다. 비용 없이(또는 최소 비용으로) 구현을 돌리고 싶을 때 사용한다.
---

# Fiftybox Local

로컬·무료 provider로 구현 페이즈를 돌린다. 후보는 매 실행 실측 탐색한다 —
무료 티어는 제공 모델과 할당량이 수시로 바뀐다.

**핵심 루프:** Claude가 실패하는 테스트 작성(Red) → provider가 통과시킴(Green) → Claude 리뷰

**실행 방식:** 동적 병렬. 이번 실행에서 가용한(healthy) distinct 모델 수가
배치의 최대 동시 실행 수다. 모델 1개면 순차, N개면 최대 N개 병렬 — 배치 내
각 태스크는 서로 다른 모델에 배정한다(같은 모델에 태스크를 몰지 않는다 —
무료 티어 분당 요청 제한, Modal 컨테이너 자원 경합을 피한다).

---

## ⛔ 절대 금지

**Claude는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다. Claude가 이
스킬에서 쓸 수 있는 파일은 두 가지뿐이다:
1. 테스트 파일 (Red 페이즈)
2. 아티팩트 문서 (`<artifactDir>/design.md` 등)

orchestrate.py가 실패하면 사용자에게 보고한다. 대신 구현하지 않는다.

## 호출

```
/fiftybox-local "<작업 설명>" [--provider <id> --model <id> ...]
```

`--provider`/`--model`을 명시하면 탐색을 건너뛰고 그 목록만 후보로 쓴다(수동
모드). 생략하면 아래 후보 풀 구성대로 매번 탐색한다.

## 후보 풀 구성

1. `discover_free_models.py`로 opencode Zen 무료 티어를 실측 탐색한다
   (각 후보에 실제 호출 1회 — 수십 초 걸릴 수 있다). `smoke: ok`인 것만
   후보로 삼는다.
2. **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
   `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만 가용성
   자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).
3. `metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

   > opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로
   > 진행하며 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

4. `smoke: ok` 후보(opencode 무료 + modal-qwen38 항상 포함)가 하나도 없으면
   중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.**

수동 모드(`--provider`/`--model` 직접 지정)에서는 이 탐색 전체를 건너뛰고
지정된 provider/model 쌍들을 그대로 후보로 쓴다.

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
체크 후에도 `200`이 아니면 디스패치하지 않고 보고한다 — 토큰/Keychain
문제는 `account`로, 그 외는 엔드포인트 실패로 분류한다. 모델 교체를
제안하지 않는다.

`--phase implement`/`--phase deploy` 호출에 `--implement-agent piqwen
--implementation-timeout 1800`을 추가한다. `--phase setup`에도
`--implement-agent piqwen`을 넘겨 미지의 에이전트 이름을 setup 단계에서
먼저 걸러낸다.

## 워크플로

### Step 1-4: 설계 수집, Setup, 태스크 분해

`fiftybox-free-execute`와 동일 — 단, 태스크 분해는 배치 크기가 **후보 모델 수**에
좌우되므로 **배치 단위**로 만든다(순수 순차 목록이 아니다):

```markdown
## Task Batches (동적 병렬 — 후보 3개 기준 예시)

### Round 1 (최대 3개 병렬, 서로 다른 모델)
- Task A → opencode/nemotron-3-ultra-free
- Task B → opencode/mimo-v2.5-free
- Task C → modal-qwen38

### Round 2 (남은 태스크, 다시 최대 3개 병렬)
- Task D → opencode/nemotron-3-ultra-free
```

### Step 5: Claude가 테스트 작성 (Red)

`fiftybox-free-execute`의 Step 6과 동일(라운드의 각 태스크에 대해 병렬로
작성).

### Step 6: 구현 (Green) — 라운드 병렬

라운드 내 각 태스크를 배정된 모델로 동시에 디스패치한다(cc-execute의 Agent
+ detached orchestrate.py 패턴과 동일). `modal-qwen38`이 배정된 레인은
디스패치 전 웨이크업 절차를 거친다.

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<배정된 provider>" --model "<배정된 model>" --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

라운드 내 모든 태스크가 끝날 때까지 기다린다.

### Step 7: Claude 리뷰 게이트

`fiftybox-free-execute`의 Step 8과 동일(테스트 결과 → 테스트 무력화 검사 →
명세 준수 → 통합 확인). 문제 없으면 다음 라운드로(Step 5-7 반복), 라운드가
모두 끝났으면 Step 8로.

Advisory diff 리뷰는 `fiftybox-execute`와 동일한 자연어 opt-in 트리거를
따른다(`~/.claude/skills/fiftybox-execute/scripts/diff_review.py` 재사용).

### Step 8-11: Review+Test, Complete, Deploy, Cleanup

`fiftybox-free-execute`의 Step 9-12와 동일 — `--implement-agent`/`--model`을
실패한 태스크에 배정됐던 값으로 재시도한다.

## 모델 소진 처리

라운드 중 한 모델이 소진되면 그 모델이 담당하던 태스크만 재탐색된 다른
후보로 재배정한다. 형제 레인(다른 모델)은 계속 진행한다. `smoke: ok` 후보가
하나도 안 남으면 중단하고 보고한다.

## 안전 계약

`fiftybox-free-execute`/`fiftybox-execute`와 동일 — Claude는 구현 코드를
직접 쓰지 않는다, provider는 테스트 파일을 수정하지 않는다, force
push/reset hard/branch -D 금지, Phase 7 이전 push 금지, 자동 재시도는
태스크당 1회, 실패 시 선택지 제시.
