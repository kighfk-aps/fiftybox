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

   ```bash
   python3 ~/.claude/skills/fiftybox-local/scripts/discover_free_models.py
   ```

   stdout의 JSON을 읽는다.

2. **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
   `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만 가용성
   자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).

   ⚠️ `IMPL_PROVIDER`(`modal-qwen38`)는 사람이 읽는 **후보 라벨**이고,
   orchestrate.py의 `--implement-agent`에 넘기는 것은 `IMPL_AGENT`(`piqwen`)다.
   두 값을 혼동해 라벨 쪽을 `--implement-agent`에 넘기면 `BUILTIN_AGENTS`에도
   `config.json`에도 없는 이름이라 실패한다. opencode 무료 후보는 반대로
   라벨이 곧 모델 ID이고 에이전트는 항상 `opencode`다.
3. `metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

   > opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로
   > 진행하며 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

4. `smoke: ok` 후보(opencode 무료 + modal-qwen38 항상 포함)가 하나도 없으면
   중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.**

수동 모드(`--provider`/`--model` 직접 지정)에서는 이 탐색 전체를 건너뛰고
지정된 provider/model 쌍들을 그대로 후보로 쓴다.

## 후보 제시와 기록

탐색이 끝나면 후보를 표로 제시한다. `smoke`가 `ok`인 것을 위에 둔다.
`fiftybox-execute`와 달리 사용자가 **하나**를 고르는 것이 아니라, 이 목록
전체가 이번 실행의 병렬도와 레인 배정을 결정한다 — 사용자는 제외하고 싶은
후보만 빼면 된다.

```
이번 실행에서 사용 가능한 로컬·무료 후보:

  번호  후보                             컨텍스트  응답      상태
  1     opencode/nemotron-3-ultra-free   1.0M      2.1s      ok
  2     opencode/mimo-v2.5-free          200K      1.8s      ok
  3     modal-qwen38 (qwen3.8-27b)       -         (콜드스타트) always
  4     opencode/laguna-s-2.1-free       256K      -         rate_limited

사용 가능 후보 3개 → 라운드당 최대 3개 병렬. 이대로 진행할까요?
(제외할 번호가 있으면 알려주세요)
```

확정된 후보 목록과 라운드별 배정을 `<artifactDir>/model-choice.json`에
기록한다(artifactDir은 Step 2 setup에서 생긴다):

```json
{
  "selected": ["opencode/nemotron-3-ultra-free", "opencode/mimo-v2.5-free", "modal-qwen38"],
  "selected_at_step": "initial",
  "discovery": { "metadata_degraded": false, "candidates": [] },
  "history": []
}
```

`selected`가 배열인 것이 유일한 차이다 — 이 스킬은 라운드마다 여러 모델을
동시에 쓴다. 레인 교체가 일어날 때마다 `history` 배열에 append 한다(뒤의
「모델 소진 처리」 참고).

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

### Step 1: 설계 수집

사용자에게 설계 문서를 요청한다. 파일 경로(`./design.md`, `./PRD.md`,
`./plan.md`), 대화 중 인라인 텍스트, "현재 디렉터리 컨텍스트 사용" 중
아무거나 받는다. 마지막의 경우 관련 파일을 읽어 설계로 요약한다.

설계를 `<artifactDir>/design.md`에 쓴다(artifactDir은 Step 2에서 생긴다.
그전까지는 메모리에 들고 있는다).

**`design.md`는 필수다.** `--skip-verify`를 줘도 implement 페이즈가 이 파일을
읽는다. 없으면 `design.md not found in artifact directory`로 즉시 실패한다.

설계 문서의 범위(Out of Scope) 절에 **Red 페이즈 테스트 파일이 예외임을
명시한다** — Claude가 테스트를 추가하는 것은 이 작업의 정상적인 일부인데,
범위 절이 이를 빼놓으면 Step 7 리뷰에서 스코프 위반으로 오판하게 된다.

### Step 2: Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)" \
  --implement-agent "<이번 라운드에서 쓸 에이전트 중 하나>"
```

`--implement-agent`를 setup에도 넘겨 미지·오타 에이전트 이름을 파이프라인
중간이 아니라 setup에서 먼저 걸러낸다. 값은 에이전트 이름이지 후보 라벨이
아니다 — opencode 무료 레인은 `opencode`, Modal 레인은 `piqwen`이다
(`modal-qwen38`은 후보 라벨일 뿐 에이전트 이름이 아니다).

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다. 설계 문서를 아티팩트
디렉터리에 복사하고, 「후보 제시와 기록」의 `model-choice.json`을 쓴다.

### Step 3-4: 태스크 분해

태스크 분해는 배치 크기가 **후보 모델 수**에 좌우되므로 **배치 단위**로
만든다(순수 순차 목록이 아니다). `<artifactDir>/task-batches.md`에 쓴다:

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

실패하는 테스트를 **이번 라운드의 각 태스크에 대해** Claude가 직접 쓴다(Red).
내부 구조가 아니라 동작을 검증하고, 해피 패스·엣지 케이스·에러 케이스를
명세에서 뽑고, 아직 존재하지 않는 함수·클래스를 참조하고(구현 모델이 만든다),
테스트 이름이 수용 기준처럼 읽히게 쓴다. `<artifactDir>/tests/`와 실제
프로젝트 테스트 디렉터리 양쪽에 쓴다.

**실패하는지 확인한다(Red).** 구현 전에 통과하면 아무것도 검증하지 않는
테스트다. 다시 쓴다.

이것은 「안전 계약」의 `.omx/artifacts/` 밖 편집 금지 규칙에 대한 명시적
예외다 — 테스트 파일만 해당하며 구현 파일에는 적용되지 않는다.

### Step 6: 구현 (Green) — 라운드 병렬

라운드 내 각 태스크를 배정된 모델로 동시에 디스패치한다 — 태스크마다 Agent
하나씩 띄우고, 각 Agent가 orchestrate.py를 `nohup`으로 **detached** 실행한다.
`modal-qwen38`이 배정된 레인은 디스패치 전 웨이크업 절차를 거친다.

**foreground 실행 금지.** `--phase implement`를 foreground로 돌리면 Bash 도구의
10분 한도를 넘겨 파일도 로그도 없이 통째로 죽는다. 반드시 detached로 돌리고
`.out` 로그를 폴링해 완료를 기다린다.

⚠️ **`--implement-agent`에는 후보 라벨이 아니라 에이전트 이름을 넣는다.**
후보 라벨(`modal-qwen38`)과 orchestrate.py 에이전트 이름(`piqwen`)은 다르다.
라벨을 그대로 넘기면 `BUILTIN_AGENTS`/`config.json`에 없는 이름이라 setup·
implement 페이즈에서 실패한다. 레인별로 아래 둘 중 하나를 쓴다.

**opencode 무료 레인** (`--model`은 그 레인에 배정된 무료 모델 ID):

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>" --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

**Modal 레인**(후보가 `modal-qwen38`일 때 — 웨이크업이 `200`을 낸 뒤에만):

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent piqwen --model qwen3.8-27b-q4_k_m \
  --implementation-timeout 1800 --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

이 두 형태는 **재시도(`--is-retry`)와 deploy 페이즈에도 그대로 적용된다** —
`--implement-agent`가 등장하는 모든 호출에서 레인에 맞는 쪽을 고른다.

`--skip-verify`는 필수다. 이 스킬은 설계 검증을 외부에서 하고 orchestrate의
verify-design 페이즈를 건너뛴다.

각 Agent 프롬프트에 반드시 포함할 것:
- 전체 태스크 설명(파일 경로가 아니라 텍스트를 붙여넣는다)
- 설계 문서의 관련 맥락
- 이 태스크가 건드릴 파일과, 형제 레인 소유라 건드리면 안 되는 파일
- 해당 태스크 테스트 파일의 전체 내용
- "이 테스트를 통과시켜라. 테스트 파일을 수정하지 마라. 구현 후 테스트를 돌려 확인하라."
- "orchestrate.py로 구현하라. 직접 코드를 쓰지 마라."

라운드 내 모든 태스크가 끝날 때까지 기다린다.

### Step 7: Claude 리뷰 게이트

라운드가 끝나면 Claude(서브에이전트 아님)가 레인마다 4단계 리뷰를 한다.

**1단계 — 테스트 결과:** Step 5의 테스트를 전부 돌린다. 실패한 레인은 실패
출력과 함께 Step 6을 재실행한다.

**2단계 — 테스트 무력화 검사:** 구현 모델이 테스트를 통과시키려고 테스트
자체를 약화시켰는지 본다. `git diff`로 테스트 파일 변경을 확인한다 — 테스트
파일이 수정됐으면 되돌리고 재실행, 단언 삭제·`assert True` 치환, 스킵 마킹
(`@pytest.mark.skip`, `xfail`, `it.skip`) 추가, 스텁만 채운 구현을 본다.
**무료·로컬 모델은 지시 준수율이 낮다. 이 단계를 건너뛰지 않는다.**

**3단계 — 명세 준수:** 레인이 소유한 파일만 pathspec으로 잘라
(`git -C "<worktree>" diff -- <소유 파일...>`) 태스크 명세와 한 줄씩 대조한다.
pathspec 없이 뜨면 형제 레인의 변경이 섞여 스코프 위반을 오탐한다.

**4단계 — 통합 확인:** 같은 라운드의 형제 레인과 선행 라운드 결과 사이의
인터페이스가 맞는지(함수 시그니처, 공유 타입), 병렬 충돌 편집(중복 정의)이
없는지 확인한다.

문제가 있으면 리뷰 결과를 피드백으로 그 레인의 Step 6을 재실행한다(태스크당
자동 재시도 1회). 두 번째도 실패하면 사용자에게 선택지를 제시한다.
문제 없으면 다음 라운드로(Step 5-7 반복), 라운드가 모두 끝났으면 Step 8로.

Advisory diff 리뷰는 `fiftybox-execute`와 동일한 자연어 opt-in 트리거를
따른다(`~/.claude/skills/fiftybox-execute/scripts/diff_review.py` 재사용).

### Step 8: Review + Test (Phase 6)

모든 라운드가 리뷰 게이트를 통과한 뒤:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

**`--skip-codex-review`는 필수다.** Codex는 은퇴했다(2026-07-15 라우팅 결정).
빠뜨리면 orchestrate가 advisory Codex 스펙 리뷰를 돌려 매 실행마다 리뷰 비용이
들고, 설계 문서의 범위 절과 어긋나는 파일을 스코프 위반으로 오탐해 불필요한
대응을 유발한다. 비용을 안 쓰는 것이 이 스킬의 존재 이유다. 명세 준수는
Step 7에서 이미 봤다.

첫 실패 시 **실패한 태스크에 배정됐던 레인의 provider/model 그대로** Step 6을
실패 출력을 피드백으로 **1회 자동 재시도**한다. `--implement-agent`/`--model`은
Step 6의 레인별 형태를 그대로 쓴다(opencode 레인이면 `opencode` + 그 무료
모델, Modal 레인이면 `piqwen` + `qwen3.8-27b-q4_k_m` + `--implementation-timeout
1800`, 그리고 디스패치 전 웨이크업):

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<실패 태스크>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent <opencode|piqwen> --model "<그 레인의 모델>" --skip-verify \
  --is-retry --feedback "<테스트 실패 출력>" \
  > "<artifactDir>/implement-task-N-retry.out" 2>&1 &
```

두 번째 실패는 보고하고 선택지를 제시한다:
1. 수동 수정 후 Phase 6 재실행
2. 머지 없이 현재 상태로 커밋
3. 중단

### Step 9: Complete (Phase 7)

Phase 6이 성공한 뒤에만 실행한다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

> 이 계통 orchestrate.py에는 커밋 메시지를 넘기는 인자가 없다. 커밋 메시지는
> `--task` 값과 아티팩트 문서에서 생성된다. 존재하지 않는 인자를 붙이면
> `unrecognized arguments` 오류로 exit 2가 나고 커밋이 아예 실행되지 않는다.

⚠️ **`incomplete_commit` 실패 경고:** `--phase complete`가 `incomplete_commit`으로
실패하면 커밋이 작업 전부를 담지 못한 것이고 merge/push가 정상적으로 차단된
상태다. 이 경우 **Step 11(cleanup)을 실행하지 않는다** — cleanup이 그 작업의
유일한 사본을 지우기 때문이다. 원인을 파악해 사용자에게 보고한다.

### Step 10: Deploy (Phase 7b)

배포도 provider가 한다. 마지막 라운드에서 살아 있던 레인 중 하나를 골라 그
레인의 에이전트/모델 형태를 그대로 쓴다:

```bash
# opencode 무료 레인으로 배포할 때
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>"

# Modal 레인으로 배포할 때 (웨이크업 절차를 먼저 거친다)
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent piqwen --model qwen3.8-27b-q4_k_m \
  --implementation-timeout 1800
```

사용자가 배포 명령을 지정했으면 `--deploy-command "<명령>"`을 넘긴다.
배포 설정이 감지되지 않으면 자동으로 건너뛴다.

### Step 11: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

## 모델 소진 처리

라운드 중 한 모델이 소진되면 그 모델이 담당하던 태스크만 재탐색된 다른
후보로 재배정한다. 형제 레인(다른 모델)은 계속 진행한다.

### rate limit 판별

opencode CLI는 rate limit을 종료 코드로 구분하지 않는다. 그 레인의
`<artifactDir>/implement-task-N.out`(stdout/stderr 합본)에서 `429`,
`rate limit`, `quota`, `insufficient`를 **대소문자 무시**로 찾아 판별한다.
매칭되면 아래 재배정 절차로 가고, **매칭되지 않는 실패는 일반 구현 실패로
다뤄 Step 8의 1회 자동 재시도 경로를 탄다.** 모델을 바꾸지 않는다.

`modal-qwen38` 레인에는 이 판별을 적용하지 않는다 — Modal은 pay-per-use라
할당량 소진 개념이 없다. Modal 레인의 실패는 「실패 처리」 표로 분류한다.

### 재배정 절차

1. 무료 모델을 다시 탐색한다:

```bash
python3 ~/.claude/skills/fiftybox-local/scripts/discover_free_models.py
```

2. 사용자에게 제시한다:

```
[Round 2 / Task B] 모델 opencode/mimo-v2.5-free 에 접근할 수 없습니다.
사유: rate limit (429)

현재 사용 가능한 무료 후보:
1. opencode/nemotron-3-ultra-free   (ctx 1.0M, 응답 2.1s)
2. modal-qwen38 (qwen3.8-27b, 항상 가용)

Task B를 어떤 후보로 재시도할까요? (번호 또는 "취소")
형제 레인(Task A, Task C)은 계속 진행 중입니다.
```

3. 응답 처리:
   - 번호 선택 → **실패한 그 태스크만** 새 후보로 Step 6 재실행. 이미 통과한
     태스크는 건드리지 않는다. 같은 라운드에서 이미 쓰이고 있는 모델은
     고르지 않는다(한 모델에 태스크를 몰지 않는다는 규칙). 이후 라운드의
     후보 풀에서도 소진된 모델을 뺀다
   - "취소" → 실패 보고 흐름으로 진행

4. `smoke: ok` 후보가 하나도 안 남으면(그리고 `modal-qwen38`도 못 쓰면)
   중단하고 보고한다. **유료 모델 폴백은 제안하지 않는다.**

5. 레인 교체는 `<artifactDir>/model-choice.json`의 `history` 배열에 append 한다:

```json
{"from": "opencode/mimo-v2.5-free", "to": "opencode/nemotron-3-ultra-free",
 "reason": "rate_limited", "task": "Task B", "round": 2}
```

## 실패 처리

이 계통 orchestrate.py는 실패 분류 필드를 제공하지 않으므로, 레인별
`<artifactDir>/implement-task-N.out` 로그를 직접 읽어 이 표로만 분류한다.
표에 없는 근거로 임의로 모델을 바꾸지 않는다.

| 로그 신호 | 분류 | 범위 |
|---|---|---|
| `429`, `rate limit`, `quota`, `insufficient` | `window` | 그 모델만 |
| `Not authenticated`, 401 | `auth` | 그 provider의 모든 레인 |
| `Unknown model`, 모델 ID 거부 | `model` | 그 모델만 |
| Modal 웨이크업이 `200`을 못 냄 (토큰/Keychain) | `account` | Modal 레인만 |
| Modal 웨이크업이 `200`을 못 냄 (그 외) | `endpoint` | Modal 레인만 |
| exit 8 | `max_turns` | 그 태스크만 |
| exit 124 | `timeout` | 그 태스크만 |
| 그 외 | `unknown` | 그 태스크만 |

**핵심 차이:** 이 스킬에서 실패는 대개 **레인 국소**다. 후보마다 별개의
계정·엔드포인트를 쓰므로 한 모델이 죽어도 형제 레인은 계속 간다. 배치 전체를
중단하는 경우는 두 가지뿐이다 — (a) 같은 provider의 모든 레인이 `auth`로
죽었을 때, (b) `smoke: ok` 후보가 하나도 안 남았을 때.

분류별 대응:
- `window` — 위의 「재배정 절차」로 그 레인만 다른 후보에 넘긴다. 유료 모델
  제안은 하지 않는다
- `auth` — 해당 CLI 로그인 안내(`opencode` 로그인). 모델 교체는 무의미하다
- `model` — 재탐색 결과를 제시하고 대체 후보를 받는다
- `account` / `endpoint` — Modal 레인만 중단하고 보고한다. **모델 교체를
  제안하지 않는다**(웨이크업 절차의 규칙과 동일)
- `max_turns` — 태스크가 너무 크다는 신호. 쪼개 재시도할지 묻는다
- `timeout` — `--implementation-timeout` 상향 후 재시도 / 중단

어떤 실패에서도 Claude가 대신 구현하는 것은 금지다.

### Failure Report Format

```markdown
**Round N, Task M (NAME) 실패**

**레인:** <배정됐던 후보> (agent: <opencode|piqwen>, model: <모델 ID>)
**분류:** <window | auth | model | account | endpoint | max_turns | timeout | unknown>
**오류:** <구체적 오류 메시지>
**원인:** <짧은 분석>
**영향:** <형제 레인이 계속 가는지, 남은 후보 수가 몇 개인지>

**추천 행동:**
1. <선택지 1 — 보통 "다른 후보로 이 태스크만 재배정">
2. <선택지 2>
3. <선택지 3>
```

레인 정보를 빼먹지 않는다 — 이 스킬은 한 라운드에서 여러 모델이 동시에
돌므로 "태스크가 실패했다"만으로는 어느 모델을 갈아야 하는지 알 수 없다.

## 안전 계약

`fiftybox-execute`와 동일한 계약 — Claude는 구현 코드를
직접 쓰지 않는다, provider는 테스트 파일을 수정하지 않는다, force
push/reset hard/branch -D 금지, Phase 7 이전 push 금지, 자동 재시도는
태스크당 1회, 실패 시 선택지 제시.
