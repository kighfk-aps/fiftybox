---
name: fiftybox-cc-execute
description: CommandCode(cmd) 요금제로 구현하는 병렬 배치 TDD 실행 파이프라인 — Claude가 실패하는 테스트를 쓰고 CommandCode가 통과시키고 Claude가 리뷰한다. 설계가 끝난 작업의 구현·배포를 CommandCode에 넘길 때 사용한다.
---

# Fiftybox CC Execute

설계·기획 단계는 포함하지 않는다. 이미 끝난 설계를 받아 CommandCode(`cmd`) 요금제로
구현과 배포까지 수행하는 병렬 배치 TDD 실행 파이프라인이다. `fiftybox-execute`(Pi
CLI 계열) 파이프라인을 그대로 계승하되, 구현 에이전트만 CommandCode로 바꾼 것이다.

**핵심 루프:** Claude가 실패하는 테스트 작성(Red) → `cmd`가 통과시킴(Green) → Claude 리뷰 게이트

**실행 방식:** 배치 병렬. 독립 태스크는 각자 Agent + 각자 orchestrate.py 프로세스로
동시에 돌리고, Claude가 매 배치를 리뷰한 뒤에만 다음 배치를 시작한다.

---

## ⛔ 절대 금지 — NEVER BYPASS

**Claude는 구현 파일을 절대 직접 쓰거나 고치지 않는다.** 이 규칙에는 예외가 없다.
구현이 "뻔해 보여도", 계획서에 붙여넣기만 하면 되는 코드가 있어도,
orchestrate.py가 느리거나 응답이 없어도, 서브에이전트가 더 빨라 보여도, 태스크가
사소해 보여도 마찬가지다.

**구현 코드는 전부 CommandCode(`cmd`)가 orchestrate.py를 통해 만들어야 한다.**
이 스킬에서 Claude가 쓸 수 있는 파일은 딱 두 가지뿐이다:
1. 테스트 파일 (Step 4 — Red 페이즈)
2. 아티팩트 문서 (`<artifactDir>/design.md`, `<artifactDir>/task-batches.md`,
   `<artifactDir>/test-manifest.md` 등)

구현 코드를 직접 쓰고 싶어지면 멈추고 orchestrate.py를 실행한다. orchestrate.py가
실패하면 사용자에게 보고한다 — 조용히 대신 구현하지 않는다.

---

## 사전 조건

사용자가 제공해야 하는 것:
1. **작업 설명** — 무엇을 만들지
2. **설계 문서** — 파일 경로 또는 인라인 내용

또한 CommandCode 요금제 가입, `cmd` 설치와 로그인이 필요하다. Step 0에서
확인한다.

## 호출

```
/fiftybox-cc-execute "<작업 설명>" [--model <id>]
```

작업 설명이 없으면 물어본다.

## 모델 티어

| 대상 | 모델 |
|---|---|
| `implement` · simple | `qwen/qwen3.7-flash` |
| `implement` · complex | `zai-org/glm-5.2` |
| `deploy` | `qwen/qwen3.7-flash` |
| `review` (Step 6a advisory) | `gpt-5.6-terra` / effort high |

태스크 분해 단계(Step 3)에서 각 태스크에 `simple` / `complex` tier와 판정 근거
한 줄을 붙여 `<artifactDir>/task-batches.md`에 남긴다.

**complex 판정 기준** — 아래 중 하나라도 해당하면 complex:
- 편집 대상 파일이 3개 이상
- 새 추상화나 인터페이스를 설계해야 한다 (기존 패턴 복제가 아니다)
- 동시성, 에러 처리, 보안 경계가 얽혀 있다
- 테스트가 5개를 넘거나 통합 시나리오를 포함한다

**`--model <id>` 오버라이드:** 호출 시 `--model <id>`를 주면 이 표를 무시하고
implement와 deploy 전 페이즈를 그 모델로 고정한다.

`review` 티어는 CommandCode가 아니라 Codex CLI로 도는 별도 축이라 `--model`
오버라이드의 영향을 받지 않는다. 바꾸려면 Step 6a 명령의 `--model`을 직접 준다
(`gpt-5.6-sol`도 가능).

## 스크립트 경로 경고

이 스킬이 호출하는 orchestrate.py의 정확한 경로는
`~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`다.
`~/.claude/skills/` 밑에 `orchestrate/scripts/orchestrate.py`를 두는 잘못된 경로는
**존재하지 않는다.** `fiftybox-orchestration`을 생략하거나 다른 이름으로 바꾼
경로로 실행하면 스크립트를 찾을 수 없다. 모든 명령에서 위 정확한 경로를 그대로
쓴다.

## 워크플로

### Step 0 — Preflight

`cmd` 설치·인증·모델 가용성을 한 번에 확인한다.

```bash
python3 ~/.claude/skills/fiftybox-cc-execute/scripts/cc_preflight.py \
  --require-model qwen/qwen3.7-flash \
  --require-model zai-org/glm-5.2
```

stdout JSON의 `status` 필드로 분기한다:
- `not_installed` — `cmd`가 설치돼 있지 않다. `npm i -g command-code`로
  설치하라고 안내하고 중단한다.
- `not_authenticated` — JSON의 `message`를 그대로 사용자에게 보여주고,
  `! cmd login`을 실행하라고 안내한 뒤 중단한다. 로그인은 브라우저 대화형이라
  에이전트가 대신 할 수 없다.
- `list_failed` — 모델 목록 조회가 실패했다. 중단하고 보고한다.
- `missing_models` — 티어 모델이 목록에 없다(모델 리네임 또는 플랜 제한). JSON의
  `models`(실제 사용 가능한 모델 목록)를 보여주고 대체 모델을 사용자에게
  선택받는다.
- `ready` — 다음 단계로 진행한다.

### Step 1 — 설계 수집

사용자에게 설계 문서를 요청한다. 다음 중 아무거나 받는다:
- 파일 경로 (`./design.md`, `./PRD.md`, `./plan.md`)
- 대화 중 인라인 텍스트
- "현재 디렉터리 컨텍스트 사용" — 관련 파일을 읽어 설계로 요약

설계를 `<artifactDir>/design.md`에 쓴다(artifactDir은 Step 2에서 생긴다. 그
전까지는 메모리에 들고 있는다).

**design.md는 필수다.** `--skip-verify`를 줘도 implement 페이즈가 이 파일을 읽는다.
없으면 `design.md not found in artifact directory`로 즉시 실패한다.

**설계 문서의 범위(Out of Scope) 절에 Red 페이즈 테스트 파일이 예외임을 명시한다.**
Claude가 테스트를 추가하는 것은 이 작업의 정상적인 일부인데, 범위 절이 이를 빼놓으면
Step 6 리뷰에서 스코프 위반으로 오판하게 된다. 예: "단 Red 페이즈 테스트 파일은
예외다 — Claude가 테스트를 추가하는 것은 이 작업의 정상적인 일부다."

### Step 2 — Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)"
```

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다. 설계 문서를 아티팩트
디렉터리에 복사하고, Step 0의 preflight 결과 JSON을 그대로
`<artifactDir>/cc-preflight.json`에 기록한다.

### Step 3 — 태스크 분해와 tier 배정

설계를 원자적 구현 단위로 쪼개고 의존성을 파악해 병렬 배치를 만든다. 두 태스크가
독립이려면 서로 다른 파일을 건드리고, 데이터·함수 의존이 없고, 격리 테스트가
가능해야 한다.

각 태스크에 `simple` / `complex` tier와 판정 근거 한 줄을 붙여
`<artifactDir>/task-batches.md`에 쓴다:

```markdown
## Task Batches

### Batch 1 (parallel)
- Task A: <설명> — 파일: [목록] — tier: simple (기존 패턴 복제, 파일 1개)
- Task B: <설명> — 파일: [목록] — tier: complex (새 인터페이스 설계, 파일 4개)

### Batch 2 (parallel, after Batch 1)
- Task D: <설명> — 파일: [목록], 선행: Task A — tier: simple
```

tier 판정은 위「모델 티어」의 complex 판정 기준을 쓴다. 태스크가 하나거나 전부
강결합이면 순차 모드로 떨어진다.

### Step 4 — Claude가 테스트 작성 (Red)

**현재 배치의 각 태스크에 대해** Claude가 직접 실패하는 테스트를 쓴다. 이
페이즈가 Red 페이즈다 — 구현이 생기기 전에 수용 기준을 테스트로 고정한다.

1. 태스크 명세에서 기대 동작·입출력·엣지 케이스를 뽑는다
2. 프로젝트 관례에 맞는 테스트 위치를 정한다 (`tests/`, `__tests__/`, `*_test.py`)
3. 프로젝트의 테스트 프레임워크로 테스트 파일을 쓴다

규칙:
- 내부 구조가 아니라 동작을 검증한다
- 해피 패스·엣지 케이스·에러 케이스를 명세에서 뽑아 덮는다
- **아직 존재하지 않는 함수·클래스를 참조한다** — `cmd`가 만들 것이다
- 테스트 이름이 수용 기준처럼 읽히게 쓴다
- 각 태스크의 테스트는 독립적으로 실행 가능해야 한다

테스트를 `<artifactDir>/tests/`와 실제 프로젝트 테스트 디렉터리 양쪽에 쓰고,
`<artifactDir>/test-manifest.md`를 남긴다.

이것은 「안전 계약」의 `.omx/artifacts/` 밖 편집 금지 규칙에 대한 명시적 예외다.
테스트 파일만 해당하며 구현 파일에는 적용되지 않는다.

**실패하는지 확인한다(Red):**

```bash
<프로젝트 테스트 명령> <테스트 파일>
```

구현 전에 통과하면 아무것도 검증하지 않는 테스트다. 다시 쓴다.

### Step 5 — 병렬 구현 (Green)

> ⛔ 이 단계에서 Claude는 구현 코드를 쓰지 않는다. 구현은 orchestrate.py가
> detached로 실행하는 `cmd`만이 만든다.

배치 내 태스크마다 Agent 하나씩 띄우고, 각 Agent는 자기 tier 모델로 orchestrate를
**detached 실행**한다:

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent commandcode --model "<tier 모델>" \
  --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

**foreground 실행 금지.** `--phase implement`를 foreground로 돌리면 Bash 도구의
10분 한도를 넘겨 **파일도 로그도 없이 통째로 죽는다.** 반드시 detached로 돌리고
`<artifactDir>/implement-task-N.out` 로그를 폴링해 완료를 기다린다.

`--skip-verify`는 필수다. 이 스킬은 설계·검증을 외부에서 하고 orchestrate의
verify-design 페이즈를 건너뛴다.

Agent 프롬프트에 반드시 포함할 것:
- 전체 태스크 설명 (파일 경로가 아니라 텍스트를 붙여넣는다)
- 설계 문서의 관련 맥락
- 이 태스크가 건드릴 파일과, 형제 태스크 소유라 건드리면 안 되는 파일
- 해당 태스크 테스트 파일의 전체 내용
- "이 테스트를 통과시켜라. 테스트 파일을 수정하지 마라. 구현 후 테스트를 돌려 확인하라."
- "orchestrate.py로 구현하라. 직접 코드를 쓰지 마라."

배치 내 모든 Agent가 끝날 때까지 기다린다. 실패가 있으면 아래「실패 처리」에 따라
분류하고 대응한다.

### Step 6 — 리뷰 게이트 (6a GPT advisory → 6b Claude 최종)

배치마다 리뷰 게이트를 통과해야 다음 배치로 간다. 검사는 세 항목이고, 담당이
나뉜다:

| 항목 | 담당 |
|---|---|
| ① 테스트 실행·통과 확인 | Claude |
| ② 스펙 준수 + 테스트 커버리지 적정성 | GPT (advisory) |
| ③ 통합 검사 (병렬 충돌·크로스 인터페이스) | Claude |
| findings 검증 + 최종 go/no-go | Claude |

**① 테스트 실행은 Claude가 한다.** GPT 리뷰어는 `-s read-only --ephemeral`
샌드박스에서 프롬프트에 인라인된 텍스트만 보므로 테스트를 실행할 수 없다.
Step 4에서 쓴 테스트를 전부 돌려 통과를 확인한다. `cmd`가 테스트 파일을
수정했다면 되돌리고 재실행한다.

**테스트가 실패한 태스크는 6a를 건너뛴다.** 깨진 diff에 리뷰 비용을 쓰지 않고
곧장 재구현으로 간다.

#### 6a — GPT advisory 리뷰 (자동)

배치가 green이면, 태스크마다 입력 파일 세 개를 만든다:

```bash
# 태스크가 소유한 파일만 pathspec으로 자른다
git -C "<worktree>" diff -- <태스크 소유 파일...> > "<artifactDir>/diff-task-N.patch"
```

그리고 `task-batches.md`의 해당 태스크 절을 발췌해
`<artifactDir>/spec-task-N.md`로 쓴다.

> **pathspec은 필수다.** 워크트리는 배치 내 형제 태스크와 공유된다. pathspec 없이
> `git diff`를 뜨면 형제의 변경이 섞여 GPT가 스코프 위반을 오탐한다.

태스크별 독립 프로세스로 detached 병렬 실행한다:

```bash
nohup python3 ~/.claude/skills/fiftybox-cc-execute/scripts/cc_diff_review.py \
  --diff "<artifactDir>/diff-task-N.patch" \
  --spec "<artifactDir>/spec-task-N.md" \
  --test "<테스트 파일>" \
  --context "<artifactDir>/design.md" \
  --task-name "task-N" --out "<artifactDir>/reviews" \
  --model gpt-5.6-terra --effort high \
  > "<artifactDir>/gpt-review-task-N.out" 2>&1 &
```

`.out` 로그를 폴링해 완료를 기다린다(Step 5 detached 패턴과 동일). 마지막 줄이
stdout JSON이다: `{ok, taskName, diffPath, reviewPath, model, effort, verdict, findingsCount}`.

exit code로 분기한다:

| exit | 의미 | 대응 |
|---|---|---|
| 0 | 성공 | `verdict`를 읽고 6b로 |
| 2 | 인자·경로 오류 | 스킬 버그. 보고하고 해당 태스크 Claude 폴백 |
| 3 | codex 미설치 또는 shim | stderr 안내를 전달하고 Claude 폴백 |
| 4 | 모델 슬러그 오류 | stderr의 사용 가능 목록을 제시하고 대체 모델로 재실행 |
| 5 | 타임아웃 | effort 하향 또는 더 가벼운 모델로 1회 재시도, 실패 시 Claude 폴백 |
| 6 | codex 실행 실패 | stderr를 전달하고 Claude 폴백 |

#### 6b — Claude 최종 게이트

각 태스크의 JSON `verdict`로 분기한다:

- **`APPROVED`** → ③ 통합 검사만 수행
- **`REVISE` / `BLOCKED`** → findings를 **검증**한다. GPT 판정을 맹신하지 않는다
  - 타당하면 → 수정 Agent(`cmd` 재구현)를 붙이고 테스트 재실행 → 6a+6b 재리뷰 1회
  - 타당하지 않으면(이미 만족한 요구, 오해, 범위 밖 지적) → 기각 사유를 JSON의
    `reviewPath`가 가리키는 로그 말미에 남기고 ③으로 간다
- **`UNKNOWN`** → contract를 벗어난 응답이다. 판정으로 취급하지 않고 Claude 폴백
- `findingsCount`가 0인데 판정이 `REVISE`/`BLOCKED`면 요약을 믿지 말고
  `reviewPath` 원문을 직접 읽는다

> 로그 경로를 직접 조립하지 않는다. 같은 날 재리뷰가 돌면 `-2`가 붙으므로 반드시
> JSON의 `reviewPath`를 쓴다.

**③ 통합 검사는 항상 Claude가 한다.** 병렬 태스크 간 충돌 편집(merge conflict,
중복 정의), 크로스 태스크 인터페이스 불일치(함수 시그니처, 공유 타입), 의도치 않은
결합을 본다. 이 항목은 GPT contract에서 명시적으로 out-of-scope다 — 단일 태스크
리뷰어는 형제 태스크를 보지 못한다.

#### Claude 폴백

**GPT 리뷰는 절약 기회이지 필수가 아니다.** 실패하거나 사용 불가면 해당 태스크는
Claude가 기존 방식(`git diff`를 명세와 직접 대조)으로 검사한다. 파이프라인은 GPT
때문에 멈추지 않는다.

폴백은 **태스크 국소**다. 한 태스크의 GPT 리뷰가 죽어도 형제 태스크는 GPT로 계속
간다.

GPT-driven 재구현이 재리뷰에서도 같은 blocking 지적을 받으면 사용자에게 선택지를
제시한다 — 기존 "두 번째 실패 시 사용자 보고" 규칙과 같다.

문제가 없으면 다음 배치로 넘어가 Step 4~6을 반복하거나, 배치가 전부 끝났으면
Step 7로 간다.

### Step 7 — review-test (Phase 6)

스펙 준수와 통합 검사는 Step 6에서 이미 했으므로 이 페이즈는 객관적 테스트 명령만
돌린다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

**`--skip-codex-review`는 필수다.** Codex는 은퇴했다(2026-07-15 라우팅 결정).
이 플래그를 빠뜨리면 orchestrate가 advisory Codex 스펙 리뷰를 돌려 REJECTED
판정과 지적 목록을 낸다. 파이프라인을 멈추지는 않지만 매 실행마다 리뷰 비용이
들고, 설계 문서의 범위 절과 어긋나는 파일을 스코프 위반으로 지적해 불필요한
대응을 유발한다.

Step 6a의 GPT diff 리뷰와는 별개다. 은퇴시킨 것은 orchestrate의 **설계·스펙**
advisory 리뷰이고, 6a는 cc-execute가 자체 스크립트로 도는 **구현 diff** 리뷰다.

첫 실패 시 실패한 태스크의 Phase 5를 실패 출력을 피드백으로 **1회 자동
재시도**한다:

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<실패 태스크>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent commandcode --model "<tier 모델>" --skip-verify \
  --is-retry --feedback "<테스트 실패 출력>" \
  > "<artifactDir>/implement-task-N-retry.out" 2>&1 &
```

두 번째 실패는 보고하고 선택지를 제시한다:
1. 수동 수정 후 Phase 6 재실행
2. 머지 없이 현재 상태로 커밋
3. 중단

### Step 8 — complete (Phase 7)

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
상태다. 이 경우 **Step 10(cleanup)을 실행하지 않는다** — cleanup이 그 작업의
유일한 사본을 지우기 때문이다. 원인을 파악해 사용자에게 보고한다.

### Step 9 — deploy (Phase 7b)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent commandcode --model qwen/qwen3.7-flash
```

`--implement-agent`는 implement뿐 아니라 deploy 페이즈에도 같은 에이전트를
적용한다. 호출 시 `--model <id>` 오버라이드가 있었다면 여기서도 표 대신 그
모델을 쓴다. 배포 설정이 감지되지 않으면 자동으로 건너뛴다.

### Step 10 — cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

---

## 실패 처리

이 계통 orchestrate.py는 실패 분류 필드를 제공하지 않으므로,
`<artifactDir>/implement-task-N.out` 로그를 직접 읽어 이 표로만 분류한다.
표에 없는 근거로 임의로 모델을 바꾸지 않는다.

| 로그 신호 | 분류 |
|---|---|
| `Not authenticated`, 401 | `auth` |
| 429, `rate limit`, `usage limit`, `5-hour`, `weekly` | `window` |
| `insufficient credit`, `balance` | `credit` |
| `Unknown model`, 모델 ID 거부 | `model` |
| exit 8 | `max_turns` |
| exit 124 | `timeout` |
| 그 외 | `unknown` |

### 배치 중단 규칙

`auth` · `window` · `credit`은 **계정 단위 실패**다. 같은 배치의 형제 태스크도 곧
같은 이유로 죽는다. 이 셋 중 하나라도 나오면 **배치 전체를 즉시 중단**하고, 이미
성공한 태스크의 결과는 워크트리에 그대로 둔 채 사용자에게 보고한다:

- `auth` — `! cmd login`을 안내한다. 모델 교체는 무의미하다
- `window` — 5시간 롤링 30% / 주간 60% 한도에 걸렸다. **모델 교체를 해결책으로
  제시하지 않는다.** 리셋 대기 / 온디맨드 크레딧 충전 / 중단을 묻는다
- `credit` — 충전이 필요함을 명시한다

`model` · `max_turns` · `timeout`은 **태스크 국소 실패**다. 해당 태스크만
처리한다:
- `model` — `cmd --list-models` 결과를 제시하고 대체 모델을 받은 뒤 해당
  태스크만 재실행
- `max_turns` — 태스크가 너무 크다는 신호. 쪼개 재시도할지 묻는다
- `timeout` — `--implementation-timeout` 상향 후 재시도 / 중단

어떤 실패에서도 Claude가 대신 구현하는 것은 금지다.

### Failure Report Format

```markdown
**Batch N, Task M (NAME) 실패**

**분류:** <auth | window | credit | model | max_turns | timeout | unknown>
**오류:** <구체적 오류 메시지>
**원인:** <짧은 분석>
**영향:** <배치 내 형제 태스크에 미치는 영향>

**추천 행동:**
1. <선택지 1>
2. <선택지 2>
3. <선택지 3>
```

---

## 안전 계약

`/fiftybox-orchestration`에서 승계한다:

- 활성 상태에서 `.omx/artifacts/` 밖 직접 파일 편집 금지. **단 Step 4의 Red 페이즈 테스트 파일은 명시적 예외다** — Claude는 프로젝트 테스트 디렉터리에 테스트를 쓴다. 이 금지의 대상은 구현 파일이다
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- `cmd`는 커밋·푸시하지 않는다. 커밋은 `--phase complete`가 수행한다
- 자동 재시도는 태스크당 Phase 5→6 1회
- 실패 시 선택지를 제시한다. 조용히 복구하지 않는다
- **병렬:** Agent는 소유 경계 밖 파일을 편집하지 않는다
- **병렬:** Claude가 매 배치를 리뷰한 뒤에만 다음 배치를 시작한다
- **TDD:** `cmd`는 Claude가 쓴 테스트 파일을 수정하지 않는다. 수정했다면 되돌린
  뒤 리뷰한다
- **GPT 리뷰(Step 6a)는 advisory(non-blocking)다.** 판정이 파이프라인을 멈추지 않는다
- **GPT 판정을 맹신하지 않는다.** Claude가 findings를 검증하고 최종 go/no-go를 낸다.
  테스트 실행과 통합 검사는 Claude가 유지한다
- GPT 리뷰어는 read-only 샌드박스라 파일을 수정할 수도, 테스트를 실행할 수도 없다
- **GPT 실패 시 자동 Claude 폴백.** GPT-driven 재구현도 `cmd`가 수행한다 — Claude가
  직접 고치지 않는다. 자동 재구현은 태스크당 1회
- **⛔ Claude는 계획서 내용, 속도, 모델 가용성과 무관하게 구현 코드를 직접 쓰지
  않는다. 이 규칙 위반은 치명적 실패다**
