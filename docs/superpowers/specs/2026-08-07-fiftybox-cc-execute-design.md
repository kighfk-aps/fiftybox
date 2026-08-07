# fiftybox-cc-execute 설계

날짜: 2026-08-07
상태: 승인됨

## 목적

CommandCode(`cmd`) 요금제를 구현자로 쓰는 실행 스킬을 만든다. `fiftybox-execute`(Pi
계열)의 병렬 배치 TDD 파이프라인을 그대로 계승하고, 구현 에이전트만 Pi CLI에서
CommandCode로 바꾼다. 설계·기획 단계는 포함하지 않는다 — 이미 끝난 설계를 받아
구현과 배포까지 수행한다.

사용자 플랜은 Go($1/월, $10 크레딧)로 시작해 부족하면 GOAT($10/월)로 올린다.
5시간 롤링 30% · 주간 60% 한도가 있으므로 크레딧 소모가 설계 제약이다.

## 조사 결과 (실측)

- 바이너리는 `cmd`, 설치는 `npm i -g command-code`. 검증 버전 v1.14.1
- `cmd --list-models`는 인증 없이도 동작하며 52개 모델을 반환한다
- `cmd status` / `cmd whoami`로 인증 상태를 확인한다. 로그인(`cmd login`)은
  브라우저 대화형이라 에이전트가 대신 수행할 수 없다
- 헤드리스 실행은 `-p`(print) 모드. `--output-format`은 `text`(기본)와 `json`
- 이 리포지토리 계통의 `orchestrate.py`에는 `errorClass` / `model_unavailable`
  분류가 **없다**. `fiftybox-execute` SKILL.md의 "Pi CLI 실패 분류" 표는 대응
  구현이 없는 상태이므로 새 스킬에 복사하지 않는다
- `~/.claude/skills/orchestrate/config.json`은 존재하지 않는다. 따라서
  `load_agent_config`는 항상 기본값(`explore_agent`/`implement_agent` = `pi`)을
  쓰며, `--implement-agent` 오버라이드 없이는 CommandCode로 실행되지 않는다

## 범위

새로 만들거나 바꾸는 파일:

| 파일 | 변경 |
|---|---|
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | `BUILTIN_AGENTS`에 `commandcode` 항목 추가 |
| `skills/fiftybox-cc-execute/SKILL.md` | 새 스킬 본문 |
| `skills/fiftybox-cc-execute/scripts/cc_preflight.py` | 인증·모델 확인 스크립트 |
| `commands/fiftybox-cc-execute.md` | 슬래시 명령 |
| `install.sh` | 설치 배선 |
| `tests/test_install.sh`, `tests/test_cc_agent.sh` | 검증 |

## 승계하는 계약

`fiftybox-execute`에서 그대로 가져온다:

- **Claude는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다. Claude가 쓸 수
  있는 파일은 테스트 파일과 아티팩트 문서뿐이다
- Red(Claude가 실패하는 테스트 작성) → Green(`cmd`가 통과시킴) → Claude 리뷰
  게이트 → 다음 배치
- `cmd`는 커밋·푸시하지 않는다. 커밋은 `--phase complete`가 수행한다
- 배치 병렬 실행. 독립 태스크는 각자 Agent + 각자 orchestrate.py 프로세스
- 자동 재시도는 태스크당 1회

## orchestrate.py 어댑터

`BUILTIN_AGENTS`에 항목 하나를 추가한다. 파이썬 로직은 수정하지 않는다 —
`build_agent_cmd`가 `{prompt}` / `{task}` / `{model}` 치환을 이미 처리한다.

```python
"commandcode": {"cmd": ["cmd", "-p", "{prompt}\n{task}", "-m", "{model}",
                        "--yolo", "--trust", "--no-session",
                        "--skip-onboarding", "--no-auto-update"]},
```

플래그 근거:

- `-p` — 비대화 모드, 응답 출력 후 종료. 출력은 text 기본으로 둔다. orchestrate가
  stdout을 로그 파일로 받으므로 NDJSON이 필요 없다
- `--yolo` — 권한 프롬프트 우회
- `--trust` — 워크트리는 매번 새 경로라 신뢰 프롬프트가 뜬다. 이를 차단
- `--no-session` — 세션 파일 오염 방지
- `--skip-onboarding` — taste 온보딩이 자동 실행을 막는 것을 방지
- `--no-auto-update` — 배치 도중 자동 업데이트로 인한 비결정성 차단
- `--no-skills`는 **넣지 않는다**. 프로젝트 `AGENTS.md`와 스킬을 읽는 편이
  구현 품질에 이득이다
- `{provider}`는 쓰지 않는다. CommandCode에는 provider 개념이 없다(`codex` 항목과 동일)

호출부는 `--implement-agent commandcode`를 넘긴다. 이 오버라이드는 인보케이션
단위라 동시에 도는 다른 세션의 Pi 실행에 영향을 주지 않는다.

`--implement-agent`는 implement뿐 아니라 **deploy 페이즈에도 같은 에이전트를
적용한다**(`phase_deploy`가 `implement_agent`를 읽는다). 의도한 동작이다.

## 모델 티어

| 대상 | 모델 |
|---|---|
| `implement` · simple | `deepseek/deepseek-v4-flash` |
| `implement` · complex | `zai-org/glm-5.2` |
| `deploy` | `deepseek/deepseek-v4-flash` |

태스크 분해 단계에서 각 태스크에 `simple` / `complex`를 붙이고 판정 근거 한 줄을
`task-batches.md`에 남긴다.

**complex 판정 기준** — 하나라도 해당하면 complex:

- 편집 대상 파일이 3개 이상
- 새 추상화나 인터페이스를 설계해야 한다 (기존 패턴 복제가 아니다)
- 동시성, 에러 처리, 보안 경계가 얽혀 있다
- 테스트가 5개를 넘거나 통합 시나리오를 포함한다

`--model <id>`를 주면 이 표를 무시하고 전 페이즈를 해당 모델로 고정한다.

## 워크플로

호출: `/fiftybox-cc-execute "<작업 설명>" [--model <id>]`

### Step 0 — Preflight (신규)

```bash
python3 ~/.claude/skills/fiftybox-cc-execute/scripts/cc_preflight.py
```

`cmd status`로 인증을, `cmd --list-models`로 모델 ID 집합을 확인해 JSON을 출력한다.

- `cmd`가 설치돼 있지 않으면 중단하고 `npm i -g command-code`를 안내한다
- 미인증이면 중단하고 사용자에게 `! cmd login` 실행을 안내한다. 로그인은 브라우저
  대화형이라 에이전트가 대신 수행할 수 없다
- 티어 모델이 목록에 없으면(모델 리네임 또는 플랜 제한) 그 사실과 실제 목록을
  보여주고 대체 모델 선택을 받는다

### Step 1 — 설계 수집

파일 경로, 인라인 텍스트, 또는 "현재 디렉터리 컨텍스트 사용" 중 하나를 받는다.
설계를 `<artifactDir>/design.md`에 쓴다.

### Step 2 — Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)"
```

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다. 설계 문서를 아티팩트 디렉터리에
복사하고, Step 0의 preflight 결과를 `<artifactDir>/cc-preflight.json`에 기록한다.

### Step 3 — 태스크 분해와 tier 배정

설계를 원자적 구현 단위로 쪼개고 의존성을 파악해 병렬 배치를 만든다. 두 태스크가
독립이려면 서로 다른 파일을 건드리고, 데이터·함수 의존이 없고, 격리 테스트가
가능해야 한다.

`<artifactDir>/task-batches.md`에 쓴다:

```markdown
## Task Batches

### Batch 1 (parallel)
- Task A: <설명> — 파일: [목록] — tier: simple (기존 패턴 복제, 파일 1개)
- Task B: <설명> — 파일: [목록] — tier: complex (새 인터페이스 설계, 파일 4개)

### Batch 2 (parallel, after Batch 1)
- Task D: <설명> — 파일: [목록], 선행: Task A — tier: simple
```

태스크가 하나거나 전부 강결합이면 순차 모드로 떨어진다.

### Step 4 — Claude가 테스트 작성 (Red)

Claude가 직접 각 태스크의 실패하는 테스트를 쓴다. 구현이 아니라 동작을 검증하고,
아직 존재하지 않는 함수·클래스를 참조한다. 테스트를 `<artifactDir>/tests/`와 실제
프로젝트 테스트 디렉터리 양쪽에 쓰고, `<artifactDir>/test-manifest.md`를 남긴다.

테스트를 돌려 **실패하는 것을 확인한다.** 구현 전에 통과하는 테스트는 아무것도
검증하지 않으므로 다시 쓴다.

### Step 5 — 병렬 구현 (Green)

배치 내 태스크마다 Agent 하나씩 띄우고, 각 Agent는 자기 tier 모델로 orchestrate를
detached 실행한다:

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent commandcode --model "<tier 모델>" \
  --skip-verify \
  > "<artifactDir>/implement-task-N.out" 2>&1 &
```

`--skip-verify`가 필요하다. 이 스킬은 설계·검증을 외부에서 하고 verify-design
페이즈를 건너뛴다.

**foreground 실행 금지.** 한 번 실행이 Bash 도구의 10분 foreground 한도를 넘기면
파일도 로그도 없이 통째로 죽는다. 반드시 detached로 돌리고 로그를 폴링한다.

Agent 프롬프트에 반드시 포함할 것:

- 전체 태스크 설명 (파일 경로가 아니라 텍스트를 붙여넣는다)
- 설계 문서의 관련 맥락
- 이 태스크가 건드릴 파일과, 형제 태스크 소유라 건드리면 안 되는 파일
- 해당 태스크 테스트 파일의 전체 내용
- "이 테스트를 통과시켜라. 테스트 파일을 수정하지 마라. 구현 후 테스트를 돌려 확인하라."
- "orchestrate.py로 구현하라. 직접 코드를 쓰지 마라."

배치 내 모든 Agent가 끝날 때까지 기다린다.

### Step 6 — Claude 리뷰 게이트

배치마다 Claude가 직접(서브에이전트 아님) 3단계 리뷰를 한다:

1. **테스트 결과** — Step 4의 테스트 전부 통과. `cmd`가 테스트 파일을 고쳤다면
   되돌리고 재실행
2. **스펙 준수** — git diff를 읽고 태스크 명세와 한 줄씩 대조
3. **통합 검사** — 병렬 태스크 간 충돌 편집, 인터페이스 불일치, 의도치 않은 결합

문제가 있으면 해당 태스크에 수정 Agent를 붙이고 재검사한다. 두 번째 실패면
사용자에게 선택지를 제시한다.

### Step 7 — review-test (Phase 6)

스펙 준수와 통합은 Step 6에서 끝났으므로 이 페이즈는 객관적 테스트 명령만 돌린다.

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

첫 실패 시 실패한 태스크의 Phase 5를 `--is-retry --feedback "<테스트 실패 출력>"`로
한 번 자동 재시도한다. 두 번째 실패는 보고하고 선택을 받는다.

### Step 8 — complete (Phase 7)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --commit-message "<배치들이 실제로 바꾼 내용 요약>"
```

`incomplete_commit`으로 실패하면 커밋이 작업 전부를 담지 못한 것이고 merge/push가
정상적으로 차단된 상태다. **Step 10(cleanup)을 실행하지 않는다** — cleanup이 그
작업의 유일한 사본을 지운다. 원인을 파악해 사용자에게 보고한다.

### Step 9 — deploy (Phase 7b)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent commandcode --model deepseek/deepseek-v4-flash
```

배포 설정이 감지되지 않으면 자동으로 건너뛴다. 호출 시 `--model`이 주어졌다면
여기서도 표 대신 그 모델을 쓴다.

### Step 10 — cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다.

## 실패 처리

`orchestrate.py`가 `errorClass`를 제공하지 않으므로, 스킬이
`<artifactDir>/implement-task-N.out` 로그를 직접 읽어 아래 표로만 분류한다.
표에 없는 근거로 즉흥적으로 모델을 바꾸지 않는다.

| 로그 신호 | 분류 | 대응 |
|---|---|---|
| `Not authenticated`, 401 | `auth` | 배치 전체 중단. `! cmd login` 안내. 모델 교체는 무의미 |
| 429, `rate limit`, `usage limit`, `5-hour`, `weekly` | `window` | 배치 중단. **모델 교체를 해결책으로 제시하지 않는다.** 리셋 대기 / 온디맨드 크레딧 충전 / 중단을 묻는다 |
| `insufficient credit`, `balance` | `credit` | 배치 중단. 충전이 필요함을 명시 |
| `Unknown model`, 모델 ID 거부 | `model` | `cmd --list-models` 결과를 제시하고 대체 모델을 받는다. 해당 태스크만 재실행 |
| exit 8 | `max_turns` | 태스크가 너무 크다는 신호. 쪼개 재시도할지 묻는다 |
| exit 124 | `timeout` | `--implementation-timeout` 상향 후 재시도 / 중단 |
| 그 외 | `unknown` | Failure Report Format |

**병렬 배치 특유의 규칙:** `auth` · `window` · `credit`은 계정 단위 실패라 같은
배치의 형제 태스크도 곧 같은 이유로 죽는다. 하나라도 이 셋 중 하나로 실패하면
배치 전체를 즉시 중단하고, 이미 성공한 태스크의 결과는 워크트리에 그대로 둔 채
보고한다. `model` · `max_turns` · `timeout`은 태스크 국소 실패이므로 해당
태스크만 처리한다.

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

## 안전 계약

`/fiftybox-orchestration`에서 승계:

- 활성 상태에서 `.omx/artifacts/` 밖 직접 파일 편집 금지
- force push, force merge, reset hard, `-D` 브랜치 삭제 금지
- Phase 7 이전 push 금지
- `cmd`는 커밋·푸시하지 않는다
- 자동 재시도는 태스크당 Phase 5→6 1회
- 실패 시 선택지를 제시한다. 조용히 복구하지 않는다
- 병렬: Agent는 소유 경계 밖 파일을 편집하지 않는다
- 병렬: Claude가 매 배치를 리뷰한 뒤에만 다음 배치를 시작한다
- TDD: `cmd`는 Claude가 쓴 테스트 파일을 수정하지 않는다. 수정했다면 되돌린 뒤 리뷰한다
- **Claude는 계획서 내용, 속도, 모델 가용성과 무관하게 구현 코드를 직접 쓰지 않는다.
  이 규칙 위반은 치명적 실패다**

## 설치

`install.sh`:

- `CC_EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-cc-execute"` 추가
- `SKILL.md`와 `scripts/*.py` 복사
- `commands/fiftybox-cc-execute.md` 복사 줄 추가. 기존 복사 로직은 파일마다 명시적
  `cp` 한 줄씩이므로(디렉터리 통째 복사가 아니다) 새 줄이 반드시 필요하다
- 사전 확인 루프에 `cmd` 추가. 없으면 경고만 하고 중단하지 않는다(부분 설치 허용)

## 검증

1. `tests/test_install.sh` 확장 — 새 스킬 디렉터리, `SKILL.md`, `cc_preflight.py`,
   슬래시 명령 파일이 설치되는지. 기존 pass/fail 헬퍼 패턴을 따른다
2. `tests/test_cc_agent.sh` 신설 — `orchestrate.py --dry-run`으로
   `--implement-agent commandcode` 경로가 인자 조립까지 도달하는지, 알 수 없는
   에이전트명이 기존 에러 메시지로 실패하는지. `cmd`를 실제로 호출하지 않는다
3. `cc_preflight.py` — `cmd` 미설치와 미인증 두 경우에 각각 명확한 JSON을 뱉는지

**수동 E2E** (로그인 후 사용자와 함께): 작은 실제 태스크 하나를
`--model deepseek/deepseek-v4-flash` 고정으로 끝까지 돌려 워크트리·커밋·cleanup을
확인하고, 실제 플래그 조합과 크레딧 소모를 실측한다.

## 넣지 않는 것 (YAGNI)

- **taste 학습 연동 (`cmd taste`)** — 구현 품질과 직결되지 않고 배치 실행에
  비결정성만 추가한다
- **`cmd -w/--worktree`** — orchestrate.py가 이미 워크트리를 관리한다. 이중 격리는
  커밋 경로를 깨뜨린다
- **크레딧 잔액 실시간 표시** — `cmd status`가 잔액을 제공하는지 확인되지 않았다.
  preflight는 인증 여부만 본다
- **`--output-format json`** — text 출력으로 충분하다. 로그는 orchestrate가 받는다
