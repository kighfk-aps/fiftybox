---
name: fiftybox-local
description: Use when implementation should run on local or free providers (opencode free-tier, Modal Qwen3.8-27B) with dynamic parallelism tied to healthy model count. Also when the user invokes /fiftybox-local or $fiftybox-local.
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
스킬이 관리한다). 이 설정으로 아래 두 후보 원천을 켜고 끈다:

- `providers.opencode.enabled`가 `false`면 1번(무료 티어 탐색) 자체를 생략한다.
- `providers.pi.backends.modal-qwen38`의 `models`에 켜진 모델이 하나도 없으면
  2번(Modal 항상 포함)을 생략한다 — 예를 들어 지출을 잠깐 막고 싶을 때 끌 수
  있다.

설정 파일이 없으면 아직 `/fiftybox-config`를 실행한 적이 없다는 뜻이니, 리포
기본값(둘 다 켜짐)을 그대로 쓴다.

1. (`providers.opencode.enabled`가 `true`일 때만) `discover_free_models.py`로
   opencode Zen 무료 티어를 실측 탐색한다
   (각 후보에 실제 호출 1회 — 수십 초 걸릴 수 있다). `smoke: ok`인 것만
   후보로 삼는다.

```bash
python3 ~/.claude/skills/fiftybox-local/scripts/discover_free_models.py
```

2. (`providers.pi.backends.modal-qwen38`가 config에서 켜져 있을 때만)
   **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
   `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만 가용성
   자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).
3. `metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

   > opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로
   > 진행하며 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

4. `smoke: ok` 후보(설정에서 켜진 opencode 무료 + modal-qwen38)가 하나도
   없으면 중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.** config에서
   둘 다 껐다면 `/fiftybox-config`로 최소 하나는 켜야 한다고 안내한다.

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
체크 후에도 `200`이 아니면 디스패치하지 않고 보고한다 — 토큰/Keychain
문제는 `account`로, 그 외는 엔드포인트 실패로 분류한다. 모델 교체를
제안하지 않는다.

`--phase implement`/`--phase deploy` 호출에 `--implement-agent piqwen
--implementation-timeout 1800`을 추가한다. `--phase setup`에도
`--implement-agent piqwen`을 넘겨 미지의 에이전트 이름을 setup 단계에서
먼저 걸러낸다.

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

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)" \
  --implement-agent piqwen
```

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다. 설계 문서를 복사하고
후보 풀을 `<artifactDir>/model-choice.json`에 기록한다.

### Step 3: 태스크 분해 (동적 병렬)

설계를 원자적 구현 단위로 쪼갠다. 배치 크기가 후보 모델 수에 좌우되므로
**배치 단위**로 만든다. 라운드 안 각 태스크는 서로 다른 모델에 배정한다:

```markdown
## Task Batches (동적 병렬 — 후보 3개 기준 예시)

### Round 1 (최대 3개 병렬, 서로 다른 모델)
- Task A → opencode/nemotron-3-ultra-free
- Task B → opencode/mimo-v2.5-free
- Task C → modal-qwen38

### Round 2 (남은 태스크, 다시 최대 3개 병렬)
- Task D → opencode/nemotron-3-ultra-free
```

### Step 4: 오케스트레이터가 테스트 작성 (Red)

라운드의 각 태스크에 대해 Claude/Codex 오케스트레이터가 실패하는 테스트를 쓴다.

`<artifactDir>/tests/`와 실제 프로젝트 테스트 디렉터리 양쪽에 쓴다.

**실패하는지 확인한다(Red):**

```bash
<프로젝트 테스트 명령> <테스트 파일>
```

구현 전에 통과하면 다시 쓴다.

### Step 5: 구현 (Green) — 라운드 병렬

라운드 내 각 태스크를 배정된 모델로 동시에 디스패치한다. `modal-qwen38`이
배정된 레인은 디스패치 전 웨이크업 절차를 거친다.

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<배정된 provider>" --model "<배정된 model>" --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

`modal-qwen38` 레인에는 `--implement-agent piqwen --implementation-timeout 1800`을
붙인다.

라운드 내 모든 태스크가 끝날 때까지 기다린다.

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
`--implement-agent`/`--model`은 그 태스크에 배정됐던 값으로 재시도한다.

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
  --implement-agent "<배정된 provider>" --model "<배정된 model>"
```

`modal-qwen38`이면 웨이크업 후 `--implement-agent piqwen --implementation-timeout 1800`.

### Step 10: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

---

## 모델 소진 처리

라운드 중 한 모델이 소진되면 그 모델이 담당하던 태스크만 재탐색된 다른
후보로 재배정한다. 형제 레인(다른 모델)은 계속 진행한다. `smoke: ok` 후보가
하나도 안 남으면 중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.**

모델 교체는 `<artifactDir>/model-choice.json`의 `history` 배열에 append 한다.

---

## 안전 계약

`/fiftybox-orchestration`에서 상속:

- `.omx/artifacts/` 밖 직접 편집 금지. **단 Red 페이즈 테스트 파일은 명시적 예외다**
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- provider는 커밋·푸시하지 않는다
- 자동 재시도는 태스크당 1회만
- 실패 시 조용히 복구하지 않고 선택지를 제시한다

이 스킬 고유:

- **Claude/Codex 오케스트레이터는 구현 코드를 직접 쓰지 않는다.** 계획서
  내용, 속도, 모델 가용성과 무관하다
- provider는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행한다
- `--dangerously-skip-permissions`는 orchestrate가 만든 격리된 워크트리 안에서만
  유효하다
- 무료 후보가 모두 막히면 중단한다. 유료 모델로 넘어가지 않는다
- 배치 크기는 후보 모델 수이고, 라운드 안 각 태스크는 서로 다른 모델에 배정한다
