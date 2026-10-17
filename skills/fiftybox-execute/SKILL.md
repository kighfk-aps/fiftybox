---
name: fiftybox-execute
description: Use when a finished plan already exists and should be implemented and deployed by one subscription model. Also when the user invokes /fiftybox-execute.
---

# Fiftybox Execute

끝난 계획서 하나를 받아, 사용자가 지정한 구독 모델 하나로 구현하고, main에 합치고,
push하고, 배포까지 간다. 계획은 이 스킬 밖에서 opus-plan으로 이미 끝나 있다. 이 스킬을
실행 중인 주체를 아래에서는 «세션»이라고 부른다. 세션은 계획을 구현 모델에게 넘기고,
구현이 끝나면 합치고 push하고 배포하는 운반기다. 세션은 구현 파일을 쓰지 않는다.
세션은 테스트 파일을 만들지 않는다. diff를 읽고 판정하지 않는다. 요약하지 않는다.

맞는지는 배포된 것을 사용자가 직접 써 보고 판단한다. 이상하면 되돌리거나 다시 시킬지는
사용자가 나중에 고른다. 이 스킬은 되돌리지 않고, 배포 후에 선택 메뉴를 띄우지 않는다.

## 누가 무엇을 하나

| 역할 | 누가 | 이 스킬 안에서의 일 |
|---|---|---|
| 계약 | opus-plan (스킬 밖, 이미 끝남) | 없음. 결과 계획서만 받는다 |
| 구현 | 사용자가 지정한 구독 모델 하나 (예: glm-5.3) | orchestrate `--phase implement`만 |
| 운반 | 이 스킬을 실행 중인 세션 | 작업 공간, 계획서 전달, 구현 호출, 합치기, push, 배포, 죽은 호출 보고 |
| 인수 | 사용자 | 배포 후에 직접 한다. 스킬은 기다리지 않는다 |

## 절대 금지

- 세션은 구현 파일을 쓰지 않는다. 구현이 뻔해 보여도, orchestrate.py가 느리거나 응답이
  없어도, 태스크가 사소해 보여도 세션이 대신 쓰지 않는다. 세션이 쓸 수 있는 파일은
  아티팩트 문서뿐이다. 프로젝트 소스와 테스트 파일은 쓰지 않는다.
- 세션은 테스트 파일을 만들지 않는다. 테스트 파일 예외는 없다. 계획서가 구현자에게
  테스트를 만들라고 적었으면 구현자가 만든다. 세션이 미리 만들지 않는다.
- 세션은 구현 결과의 diff를 읽고 판정하지 않는다. 테스트 명령을 돌려 통과 여부를
  게이트로 삼지 않는다.
- 세션은 계획을 고치거나 다시 쪼개지 않는다.
- 어떤 실패에서도 세션이 대신 구현하지 않고, 조용히 재시도하지 않는다.

---

## 호출

```
/fiftybox-execute "<작업 설명>" [--provider <id>] [--model <id>]
```

계획서도 있어야 한다. 파일 경로, 인라인 텍스트, 또는 현재 디렉터리에서 계획 파일을
집어 달라는 말을 받는다. 없으면 물어보고 멈춘다. 세션은 계획서를 새로 쓰지 않는다.

## Model Resolution

레인 배정기는 쓰지 않는다. 태스크마다 모델을 바꾸지 않는다. 한 번 정한 쌍을 그 실행의
모든 구현과 배포에 쓴다.

| 플래그 | 쌍 |
|---|---|
| 없음 | `pi` / `zai-coding` / `glm-5.3` |
| `--provider`만 | 지금 Model Resolution에서 그 provider의 기본 모델. `commandcode`는 `meta/muse-spark-1.2-contributor`, `codex-write`는 `gpt-5.6-luna`, `grok`는 `grok-4.6`다. |
| `--model`만 | `pi` / `zai-coding` / 그 모델. 다른 provider를 쓰고 싶으면 `--provider`가 필요하다 |
| 둘 다 | 지금 Model Resolution. provider가 에이전트 이름이면 그 에이전트와 그 모델, Pi 백엔드 이름이면 `IMPL_AGENT=pi`와 그 백엔드와 그 모델이다 |

--model만 주면 pi / zai-coding / 그 모델이다. 다른 provider를 쓰고 싶으면
--provider가 필요하다.

- provider가 에이전트 이름(`commandcode`, `grok`, `pi`, `codex-write`, `opencode`,
  `aider`, `gemini`, `qwen`, `cursor`, `codex`)이면 `IMPL_AGENT=<provider>`다.
- provider가 Pi 백엔드 이름(`zai-coding`, `opencode-go`, `modal-qwen38` 등)이면
  `IMPL_AGENT=pi`다. Pi 백엔드 이름만 준 경우도 이 규칙대로다.
- `pi`와 `zai-coding`의 기본 모델은 `glm-5.3`이다. 이름 없는 provider의 기본 모델로
  glm 쌍을 끼워 넣지 않는다. `--provider commandcode`가 glm으로 바뀌지 않는다.

고른 provider가 `~/.claude/fiftybox-config.json`에서 꺼져 있으면 그 provider만
확인하고 멈춘다. 다른 레인으로 넘어가지 않는다. 설정 파일이 없으면 위 표대로 간다.
JSON이 깨졌으면 안내하고 멈춘다. 깨진 설정을 기본 쌍으로 무시하고 계속 가지 않는다.

## 스크립트 경로

이 스킬이 부르는 orchestrate.py의 정확한 경로는
`~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`다. 이 경로를
생략하거나 다른 이름으로 바꾼 경로는 존재하지 않는다. 모든 명령에서 이 경로를 그대로 쓴다.

---

## 워크플로

### 1. 계획서 수집

사용자가 준 계획서를 고치지 않고 `<artifactDir>/design.md`에 복사한다. 요약하지 않는다.
줄을 줄이지 않는다. orchestrate는 `--skip-verify`여도 이 파일을 읽는다. 없으면
implement가 실패한다.

### 2. Setup

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업 설명>" --cwd "$(pwd)"
```

JSON 출력에서 `artifactDir`과 `worktree`를 챙긴다. 선택한 쌍을
`<artifactDir>/model-choice.json`에 남긴다. 태스크마다 다른 쌍을 적지 않는다.

Preflight는 선택한 provider만 한다. CommandCode면 기존
`~/.claude/skills/fiftybox-execute/scripts/cc_preflight.py`, Grok이면 `grok inspect`,
Pi Coding Plan이면 `pi --list-models zai-coding`에 고른 모델이 있는지만 본다.
`codex-write`면 `codex exec --help`와 `workspace-write` sandbox 지원만 본다. 실패하면
로그인이나 설치를 안내하고 멈춘다. 다른 provider로 대체하지 않는다.

### 3. 일 단위 — task-batches.md

세션이 계획 산문으로 태스크를 만들어 내지 않는다. 구현 프로세스는 하나다. 세션이
일마다 implement를 나누어 띄우지 않고, 동시에 여러 개를 띄우지 않는다.

`orchestrate.py`는 `<artifactDir>/task-batches.md`의 마지막 ```json 블록이
`parse_task_batches`를 통과하면 `--task`를 무시하고 그 목록을 한 프로세스에서 순서대로
실행한다. 항목마다 프롬프트를 그 항목의 `description`과 `files`로 좁히고, 첫 실패에서
멈춘다. `parallelGroup`은 읽지 않는다. 이 스킬은 그 동작을 그대로 쓴다. 병렬을 위해
orchestrate를 고치지 않는다.

- 계획서에 그런 JSON 블록이 하나 있고, 그대로 복사했을 때 `parse_task_batches`가
  빈 목록이 아니면, 그 블록만 `<artifactDir>/task-batches.md`에 복사한다. 세션은
  항목을 고치거나 보태거나 빼지 않는다.
- 블록이 없거나, 복사해도 `parse_task_batches`가 빈 목록이면 `task-batches.md`를
  만들지 않는다. 계획서 전체가 구현 한 번이다.
- 산문에 «parallel»이라고 적혀 있어도 무시한다.

계획이 길어서 구현 모델이 못 끝내는 위험이 있어도 세션은 그걸 이유로 쪼개지 않는다.
그 제한은 사용자가 이미 받은 것이다.

### 4. 구현 — detached 한 번

세션은 구현 파일을 쓰지 않는다. 호출은 detached 한 번이다. foreground
`--phase implement`는 금지다 — Bash 도구 한도를 넘겨 파일도 로그도 없이 통째로 죽는다.

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<작업 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<AGENT>" --provider "<PROVIDER>" --model "<MODEL>" \
  --skip-verify \
  > "<artifactDir>/implement.out" 2>&1 &
```

`--skip-verify`는 유지한다. 이 스킬은 설계 검증을 하지 않는다.
`<artifactDir>/implement.out` 로그를 폴링해 완료를 기다린다.

`task-batches.md`가 있으면 orchestrate가 항목별 프롬프트를 만든다. 세션은 그 프롬프트를
다시 쓰지 않는다. `task-batches.md`가 없으면 `--task`와 design.md 전문이 그 한 번의
구현 범위다.

목록 안의 한 항목이 실패하면 orchestrate가 그 프로세스 전체를 멈춘다. 세션은 남은
항목을 이어서 호출하지 않는다. 이미 적용된 변경과 작업 공간은 지우지 않고, 실패한
항목 번호를 보고한 뒤 멈춘다. complete와 deploy로 가지 않는다. 계획의 나머지 단위가
실행되지 않은 상태이기 때문이다.

구현 프로세스가 끝나고 변경 파일이 있으면 세션은 diff를 읽고 판정하지 않는다. 테스트
명령을 돌려 통과 여부를 게이트로 삼지 않는다. 변경 파일이 없으면 아래
«구현 호출이 죽었을 때»의 `no_changes`다. 배포까지 가지 않는다.

### 5. review-test — 검증 건너뛰기

review-test는 원래 테스트 명령을 실행하고, 실패하면 complete가 진행하지 못하게 막는다.
`--skip-codex-review`는 리뷰어만 건너뛰고 테스트 실패는 그대로 막는다. 이 스킬은 그
실패로 push를 막지 않는다. 테스트 명령을 속여 통과시키는 방식은 금지다 — 커밋 메시지가
테스트를 통과했다고 거짓말하게 된다.

complete 전에 검증 건너뛰기 플래그 `--skip-verification`을 붙여 review-test를 한 번
호출한다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review --skip-verification
```

`--skip-verification`을 붙이면 orchestrate는 테스트 명령을 실행하지 않고, 리뷰 모델을
호출하지 않고, `review_test` status를 `success`로 기록해 complete가 진행되게 한다.
complete가 만드는 커밋 메시지는 테스트가 통과했다고 쓰지 않는다. 검증을 건너뛰었고
인수는 배포 후 사용자가 한다고 쓴다. 테스트 실패를 보고 구현을 자동으로 한 번 더
돌리지 않는다. 자동 재시도는 없다.

### 6. complete, deploy, cleanup

`review_test`가 위 플래그로 `success`가 된 뒤에만 아래를 순서대로 실행한다. 단계 사이에
사용자 확인을 넣지 않는다.

1. `--phase complete` — main에 합치고 `git push origin HEAD:main`까지 실행한다.
   사용자에게 미리 물어보고 멈추지 않는다.

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

2. `--phase deploy` — 고른 구현 쌍을 그대로 넘긴다. 배포 설정이 없으면 orchestrate가
   지금처럼 건너뛴다.

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<AGENT>" --provider "<PROVIDER>" --model "<MODEL>"
```

3. `--phase cleanup`

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`--phase complete`가 `incomplete_commit`으로 실패하면 cleanup하지 않는다. cleanup이
작업 공간의 유일한 사본을 지우기 때문이다. 원인을 보고하고 멈춘다.

끝난 보고는 배포가 됐는지, 작업 공간과 브랜치, `summary.json`의 상태다. 코드가 계획과 맞다는 문장은 넣지 않는다. 무엇을 실행해 보면 되는지만 적는다. 계획서에 확인 방법이
없으면 «배포된 결과를 직접 확인해 달라»고만 한다.

---

## 구현 호출이 죽었을 때

품질이 나빠서가 아니라 결과가 없을 때만 멈춘다. `<artifactDir>/implement.out` 로그를
이 표로만 분류한다. 표에 없는 근거로 임의로 모델을 바꾸지 않는다.

| 로그 신호 | 분류 |
|---|---|
| `Not authenticated`, 401 | `auth` |
| 429, `rate limit`, `usage limit`, `5-hour`, `weekly` | `window` |
| `insufficient credit`, `balance` | `credit` |
| `Unknown model`, 모델 ID 거부 | `model` |
| exit 8 | `max_turns` |
| exit 124 | `timeout` |
| exit 3, phase status `no_changes` | `no_changes` |
| 그 외 | `unknown` |

- `auth`: 그 provider의 로그인을 안내한다. 모델을 바꾸라고 하지 않는다.
- `window`, `credit`: 한도나 충전 문제다. 다른 모델을 해결책으로 제시하지 않는다.
- `model`: 그 provider의 모델 목록을 보여주고, 사용자가 고른 모델로 그 일만 다시
  호출한다. 세션이 더 센 모델을 골라 주지 않는다.
- `max_turns`, `timeout`: 계획을 더 작은 단위로 고쳐 달라고 사용자에게 말한다. 세션이
  계획을 쪼개지 않는다. timeout 값을 올려 조용히 재시도하지 않는다.
- `no_changes`: 구현 모델이 끝났다고 했는데 저장소 파일이 바뀌지 않았다. no_changes이면 complete와 deploy로 가지 않는다. 세션이 대신 구현하지 않는다. 로그를 보고하고 멈춘다.

어떤 분류에서도 세션이 구현하지 않는다. 자동 재시도는 없다.

계정 단위 실패(`auth`, `window`, `credit`)면 그 구현 프로세스를 끝난 것으로 보지
않는다. 목록 실행 중 한 항목이 이 이유로 죽으면 나머지 항목은 orchestrate가 이미
멈추므로, 세션이 나머지를 다시 띄우지 않는다.

---

## Deploy-Only

사용자가 `/fiftybox-execute deploy`라고 하거나 «그냥 배포만»을 요청하면 Setup부터
complete까지를 건너뛴다. 지금처럼 최소 아티팩트(dir과 `complete.status: "success"`인
summary.json)를 만들어 deploy 게이트만 통과시킨다. 구현 쌍은 같은 기본값 또는 플래그를
쓰고, deploy 명령은 위 6번의 deploy와 같다.

## 사용자가 나중에 다시 시킬 때

이 스킬의 성공 경로에 없는 일이다. 배포 뒤에 사용자가 이상하다고 하면, 사용자는 직접
되돌리거나, 새 계획으로 opus-plan을 다시 돌리거나, 이 스킬을 새로 호출한다. 새로
호출할 때 고칠 말을 작업 설명에 포함하면 그 말이 구현 프롬프트에 계획서와 함께 붙는다.
세션이 «구현 모델에게 보낼지, 계획을 다시 쓸지»를 고르지 않는다. 사용자가 호출
방식으로 이미 고른 것이다.

데이터 삭제, 마이그레이션, 외부 발송처럼 되돌리기 어려운 변경도 따로 멈추지 않는다.
이것은 사용자와 맞춘 내용이다. 사용자는 배포까지 자동으로 가고, 이상하면 자신이
되돌리기로 했다. 멈춤 예외를 만들지 않는다.

---

## 안전 계약

- 세션은 `.omx/artifacts/` 밖의 프로젝트 파일을 쓰지 않는다. 테스트 파일 예외는 없다.
- force push, force merge, reset hard, `-D` 브랜치 삭제는 하지 않는다. 사용자가 나중에
  직접 되돌리는 것이지, 이 스킬은 되돌리지 않는다.
- provider는 커밋하거나 push하지 않는다. 커밋과 push는 `--phase complete`만 한다.
- push는 complete 전에 하지 않는다. complete는 review-test가 `--skip-verification`으로
  `success`를 기록한 뒤에만 한다.
- 구현 호출이 죽으면 선택지를 제시하고 멈춘다. 조용히 구현하거나 다른 모델로 넘기지 않는다.
- 구현 프로세스는 하나다. 세션이 일마다 나누어 띄우거나 동시에 여러 개를 띄우지 않는다.
- 세션은 계획서, 속도, 모델 가용성과 무관하게 구현 코드를 직접 쓰지 않는다.
- no_changes이거나 목록의 한 항목이 실패하면 complete와 deploy로 가지 않는다.
