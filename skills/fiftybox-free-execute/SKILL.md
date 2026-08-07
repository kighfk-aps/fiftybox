---
name: fiftybox-free-execute
description: opencode 무료 모델로 구현하는 순차 TDD 실행 파이프라인 — 사용 가능한 무료 모델을 탐색해 사용자가 고르고, Claude가 테스트를 쓰고 opencode가 구현하고 Claude가 리뷰한다. 비용 없이 구현을 돌리고 싶을 때 사용한다.
---

# Fiftybox Free Execute

opencode Zen 무료 티어 모델로 구현 페이즈를 돌린다. 무료 티어는 제공 모델과
할당량이 수시로 바뀌므로 **실행할 때마다 탐색하고 사용자가 고른다.**

**핵심 루프:** Claude가 실패하는 테스트 작성(Red) → opencode가 통과시킴(Green) → Claude 리뷰

**실행 방식:** 완전 순차. 태스크를 한 번에 하나씩 처리한다. 무료 티어의 동시 요청·
분당 토큰 제한을 태우지 않기 위해서다.

---

## ⛔ 절대 금지

**Claude는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다. 구현이 "뻔해
보여도", 계획서에 붙여넣기만 하면 되는 코드가 있어도, orchestrate.py가 느려도,
태스크가 사소해 보여도 마찬가지다.

Claude가 이 스킬에서 쓸 수 있는 파일은 두 가지뿐이다:
1. 테스트 파일 (Step 5 — Red 페이즈)
2. 아티팩트 문서 (`<artifactDir>/design.md` 등)

orchestrate.py가 실패하면 사용자에게 보고한다. 대신 구현하지 않는다.

---

## 호출

```
/fiftybox-free-execute "<작업 설명>"
```

작업 설명이 없으면 물어본다.

## 워크플로

### Step 1: 무료 모델 탐색

```bash
python3 ~/.claude/skills/fiftybox-free-execute/scripts/discover_free_models.py
```

stdout의 JSON을 읽는다. 수십 초 걸릴 수 있다(후보마다 실제 호출을 한 번씩 한다).

`metadata_degraded`가 `true`면 사용자에게 먼저 알린다:

> opencode 모델 메타데이터를 파싱하지 못했습니다. 모델 목록만으로 진행하며
> 컨텍스트 크기와 툴콜 지원 여부는 확인되지 않았습니다.

### Step 2: 사용자에게 모델 선택 요청

후보를 표로 제시한다. `smoke`가 `ok`인 것을 위에 둔다.

```
사용 가능한 opencode 무료 모델:

  번호  모델                             컨텍스트  응답      상태
  1     opencode/nemotron-3-ultra-free   1.0M      2.1s      ok
  2     opencode/mimo-v2.5-free          200K      1.8s      ok
  3     opencode/laguna-s-2.1-free       256K      -         rate_limited

어떤 모델로 구현할까요? (번호)
```

`smoke`가 `ok`인 후보가 **하나도 없으면** 목록과 각각의 실패 사유를 보여준 뒤
**중단한다.** 유료 모델로 임의 전환하지 않는다. 비용 절감이 이 스킬의 존재 이유다.

선택된 모델 ID는 이 실행 내내 고정된다. 아래에서 `<선택모델>`로 표기한다.

### Step 3: 설계 수집

사용자에게 설계 문서를 요청한다. 다음 중 아무거나 받는다:
- 파일 경로 (`./design.md`, `./PRD.md`, `./plan.md`)
- 대화 중 인라인 텍스트
- "현재 디렉터리 컨텍스트 사용" — 관련 파일을 읽어 설계로 요약

설계를 `<artifactDir>/design.md`에 쓴다(artifactDir은 Step 4에서 생긴다. 그전까지는
메모리에 들고 있는다).

**`design.md`는 필수다.** `--skip-verify`를 줘도 구현 페이즈가 이 파일을 읽는다.
없으면 `design.md not found in artifact directory`로 즉시 실패한다.

### Step 4: Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)"
```

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다.

설계 문서를 아티팩트 디렉터리에 복사하고, Step 1~2의 탐색 결과와 선택을
`<artifactDir>/model-choice.json`에 기록한다:

```json
{
  "selected": "opencode/nemotron-3-ultra-free",
  "selected_at_step": "initial",
  "discovery": { "metadata_degraded": false, "candidates": [] },
  "history": []
}
```

### Step 5: 태스크 분해

설계를 원자적 구현 단위로 쪼개고 의존성을 파악한다. **배치 병렬화는 하지 않는다.**
의존성 그래프를 위상 정렬해 하나의 순차 목록으로 평탄화한다.

`<artifactDir>/task-list.md`에 쓴다:

```markdown
## Task List (순차)

1. Task A: <설명> — 파일: [목록]
2. Task B: <설명> — 파일: [목록], 선행: Task A
3. Task C: <설명> — 파일: [목록], 선행: Task A
```

### Step 6: Claude가 테스트 작성 (Red)

**현재 태스크 하나에 대해서만** Claude가 직접 실패하는 테스트를 쓴다.

1. 태스크 명세에서 기대 동작·입출력·엣지 케이스를 뽑는다
2. 프로젝트 관례에 맞는 테스트 위치를 정한다 (`tests/`, `__tests__/`, `*_test.py`)
3. 프로젝트의 테스트 프레임워크로 테스트 파일을 쓴다

규칙:
- 내부 구조가 아니라 동작을 테스트한다
- 해피 패스·엣지 케이스·에러 케이스를 명세에서 뽑아 덮는다
- 아직 존재하지 않는 함수·클래스를 참조한다 — opencode가 만들 것이다
- 테스트 이름이 수용 기준처럼 읽히게 쓴다

`<artifactDir>/tests/`와 실제 프로젝트 테스트 디렉터리 양쪽에 쓴다.

이것은 「안전 계약」의 `.omx/artifacts/` 밖 편집 금지 규칙에 대한 명시적 예외다.
금지의 대상은 구현 파일이며 Red 페이즈 테스트 파일은 해당하지 않는다.

**실패하는지 확인한다(Red):**

```bash
<프로젝트 테스트 명령> <테스트 파일>
```

구현 전에 통과하면 아무것도 검증하지 않는 테스트다. 다시 쓴다.

### Step 7: 구현 (Green)

> ⛔ 이 단계에서 Claude는 구현 코드를 쓰지 않는다.

**현재 태스크 하나만** 실행한다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<현재 태스크 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>" --skip-verify
```

`--skip-verify`는 필수다. 이 스킬은 설계 검증을 외부에서 하고 orchestrate의
verify-design 페이즈를 건너뛴다.

전달하는 태스크 설명에 포함할 것:
- 전체 태스크 설명 (파일 경로가 아니라 텍스트를 붙여넣는다)
- 설계 문서의 관련 컨텍스트
- 건드려야 할 파일
- 이 태스크의 **테스트 파일 전체 내용**
- "이 테스트를 통과시켜라. 테스트 파일은 수정하지 마라. 구현 후 테스트를 실행해 확인하라."

실패 시:
- JSON에 `model_unavailable`이 있거나 출력에 rate limit 패턴이 있으면 → 아래
  「모델 소진 처리」로 간다
- 그 외에는 실패를 보고하고 선택지를 제시한다

### Step 8: Claude 리뷰 게이트

태스크마다 Claude(서브에이전트 아님)가 4단계 리뷰를 한다.

**1단계 — 테스트 결과:** Step 6의 테스트를 전부 돌린다. 하나라도 실패하면 실패
출력과 함께 Step 7을 재실행한다.

**2단계 — 테스트 무력화 검사:** opencode가 테스트를 통과시키려고 테스트 자체를
약화시켰는지 본다. `git diff`로 테스트 파일 변경을 확인한다:
- 테스트 파일이 수정됐으면 되돌리고 재실행한다
- 단언이 삭제됐거나 `assert True`로 바뀌었는지
- 스킵 마킹(`@pytest.mark.skip`, `xfail`, `it.skip`)이 추가됐는지
- 구현이 스텁만 채우고 실제 동작이 없는지

무료 모델은 지시 준수율이 낮다. 이 단계를 건너뛰지 않는다.

**3단계 — 명세 준수:** 실제 코드 변경(`git diff`)을 태스크 명세와 한 줄씩
대조한다. 누락된 요구사항, 범위 밖 작업, 오해가 있는지 본다.

**4단계 — 통합 확인:** 선행 태스크와의 인터페이스가 맞는지(함수 시그니처, 공유
타입), 의도치 않은 결합이 생기지 않았는지 확인한다.

문제가 있으면 리뷰 결과를 피드백으로 Step 7을 재실행한다. 두 번째도 실패하면
사용자에게 선택지를 제시한다.

문제가 없으면 다음 태스크로 가서 Step 6부터 반복한다.

### Step 9: Review + Test (Phase 6)

모든 태스크가 리뷰 게이트를 통과한 뒤:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

`--skip-codex-review`는 필수다. Codex는 은퇴했다. 명세 준수는 Step 8에서 이미 봤다.

첫 실패 시 실패한 태스크의 Step 7을 실패 출력과 함께 **1회 자동 재시도**한다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<실패 태스크>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>" --skip-verify \
  --is-retry --feedback "<테스트 실패 출력>"
```

두 번째 실패 시 보고하고 선택지를 제시한다:
1. 수동 수정 후 Phase 6 재실행
2. 머지 없이 현재 상태로 커밋
3. 중단

### Step 10: Complete (Phase 7)

Phase 6 성공 후에만 실행한다.

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

### Step 11: Deploy (Phase 7b)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent opencode --model "<선택모델>"
```

사용자가 배포 명령을 지정했으면 `--deploy-command "<명령>"`을 넘긴다.
배포 설정이 감지되지 않으면 자동으로 건너뛴다.

### Step 12: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

## 모델 소진 처리

구현 중 선택한 모델이 할당량 소진이나 장애로 죽으면:

1. 무료 모델을 다시 탐색한다:

```bash
python3 ~/.claude/skills/fiftybox-free-execute/scripts/discover_free_models.py
```

2. 사용자에게 제시한다:

```
[implement] 모델 <선택모델> 에 접근할 수 없습니다.
사유: <에러 요약 1줄>

현재 사용 가능한 무료 모델:
1. opencode/nemotron-3-ultra-free   (ctx 1.0M, 응답 2.1s)
2. opencode/laguna-s-2.1-free       (ctx 256K, 응답 3.4s)

어떤 모델로 재시도할까요? (번호 또는 "취소")
```

3. 응답 처리:
   - 번호 선택 → **실패한 그 태스크만** 새 모델로 Step 7 재실행. 이미 통과한
     태스크는 건드리지 않는다. 이후 태스크는 새 모델로 계속한다
   - "취소" → 실패 보고 흐름으로 진행

4. `smoke`가 `ok`인 후보가 하나도 없으면 그 사실을 보고하고 **중단한다.** 유료
   모델 폴백은 제안하지 않는다.

5. 모델 교체는 `<artifactDir>/model-choice.json`의 `history` 배열에 append 한다:

```json
{"from": "opencode/mimo-v2.5-free", "to": "opencode/nemotron-3-ultra-free",
 "reason": "rate_limited", "task": "Task B"}
```

### rate limit 판별

opencode CLI는 rate limit을 종료 코드로 구분하지 않는다. stdout/stderr에서
`429`, `rate limit`, `quota`, `insufficient`(대소문자 무시)를 찾아 판별한다.
매칭되지 않는 실패는 일반 구현 실패로 다뤄 Step 9의 1회 자동 재시도 경로를 탄다.

## 안전 계약

/fiftybox-orchestration에서 상속:

- `.omx/artifacts/` 밖 직접 편집 금지. **단 Step 6의 Red 페이즈 테스트 파일은
  명시적 예외다** — Claude는 프로젝트 테스트 디렉터리에 테스트를 쓴다. 금지의
  대상은 구현 파일이다
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- opencode는 커밋·푸시하지 않는다
- 자동 재시도는 태스크당 1회만
- 실패 시 조용히 복구하지 않고 선택지를 제시한다

이 스킬 고유:

- **Claude는 구현 코드를 직접 쓰지 않는다.** 계획서 내용, 속도, 모델 가용성과
  무관하다. 위반은 치명적 실패다
- opencode는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행한다
- `--dangerously-skip-permissions`는 orchestrate가 만든 격리된 워크트리 안에서만
  유효하다. 프로젝트 루트에서 직접 opencode를 돌리지 않는다
- 무료 후보가 모두 막히면 중단한다. 유료 모델로 넘어가지 않는다
- 병렬 실행하지 않는다. 태스크는 한 번에 하나씩이다
