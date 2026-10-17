# fiftybox-execute 스펙 주도 실행 설계

날짜: 2026-10-17
상태: 승인됨 (2026-10-17)

## 목적

`fiftybox-execute`를 스펙 주도 운반기로 바꾼다. 계획은 이 스킬 밖에서 `opus-plan`으로 이미 끝나 있다. 이 스킬을 실행하는 세션은 로컬 모델이다. 그 모델은 계획을 구현 모델에게 넘기고, 구현이 끝나면 합치고 push하고 배포한다. 코드가 계획대로인지는 판단하지 않는다.

지금 스킬의 핵심 루프는 «세션이 실패 테스트를 작성(Red) → provider가 통과(Green) → 세션이 리뷰 게이트»다. 세션이 로컬 모델이면 그 두 자리는 더 약한 모델이 더 센 모델의 기준을 쓰거나 결과를 감수하는 일이 된다. 그 루프를 뺀다.

맞는지는 배포된 것을 사용자가 직접 써 보고 판단한다. 이상하면 되돌리거나 다시 시킬지는 사용자가 나중에 고른다. 이 스킬은 되돌리지 않고, 배포 후에 선택 메뉴를 띄우지 않는다.

## 목표

- 끝난 계획서 하나를 받아, 사용자가 지정한 구독 모델 하나로 구현하고, main에 합치고, push하고, 배포까지 간다.
- 세션 모델은 구현 코드를 쓰지 않는다. 테스트를 쓰지 않는다. diff를 판정하지 않는다. 계획을 고치거나 다시 쪼개지 않는다.
- 구현 호출 자체가 죽었을 때만 멈추고 사용자에게 묻는다. 코드가 나왔으면 품질과 상관없이 배포까지 간다.
- 스킬 본문에서 «Claude»는 앤트로픽 모델이 아니라 «이 스킬을 실행 중인 세션»임이 드러나야 한다. 그 세션이 로컬 모델이어도 같은 금지와 허용이 적용된다.

## 비목표

- `opus-plan`을 바꾸지 않는다. 계획 형식에 새 필수 필드를 요구하지 않는다.
- `fiftybox-local`을 바꾸지 않는다.
- 코드 감수 스킬을 새로 만들지 않는다. LAYA 같은 결정 모델을 넣지 않는다.
- 배포 후 되돌리기, 재계획, 재구현 선택을 이 스킬의 단계로 넣지 않는다.
- `fiftybox-config`의 `lane_priority` 스키마를 바꾸지 않는다. 이 스킬이 그 배열로 태스크를 배정하지만 않으면 된다.
- `diff_review.py`와 그 테스트는 지우지 않는다. `fiftybox-local`이 선택적으로 부른다. 이 스킬은 더 이상 부르지 않는다.

## 반대 목표

다음은 동작하면 실패다.

- 로컬 세션이 실패 테스트를 써서 수용 기준을 만든다.
- 로컬 세션이 구현 diff를 읽고 맞다 틀리다를 말한다.
- 로컬 세션이 구현 파일을 직접 고친다. orchestrate가 느리거나, 계획이 짧거나, 태스크가 작아 보여도 같다.
- 태스크 난이도를 보고 더 센 모델로 바꾼다.
- 테스트 실패나 모델 판정 때문에 push 또는 배포를 막는다.
- 사용량 한도나 크레딧 부족의 해결책으로 다른 모델을 제안한다.

## 누가 무엇을 하나

| 역할 | 누가 | 이 스킬 안에서의 일 |
|---|---|---|
| 계약 | opus-plan (스킬 밖, 이미 끝남) | 없음. 결과 계획서만 받는다 |
| 구현 | 사용자가 지정한 구독 모델 하나 (예: glm-5.3) | orchestrate `--phase implement`만 |
| 운반 | 이 스킬을 실행 중인 세션 (로컬 모델) | 작업 공간, 계획서 전달, 구현 호출, 합치기, push, 배포, 죽은 호출 보고 |
| 인수 | 사용자 | 배포 후에 직접 한다. 스킬은 기다리지 않는다 |

## 호출

```
/fiftybox-execute "<작업 설명>" [--provider <id>] [--model <id>]
```

계획서도 있어야 한다. 파일 경로, 인라인 텍스트, 또는 현재 디렉터리에서 계획 파일을 집어 달라는 말을 받는다. 없으면 물어보고 멈춘다. 세션이 계획서를 새로 쓰지 않는다.

레인 배정기는 쓰지 않는다. 태스크마다 모델을 바꾸지 않는다. 한 번 정한 쌍을 그 실행의 모든 구현과 배포에 쓴다.

| 플래그 | 쌍 |
|---|---|
| 없음 | `pi` / `zai-coding` / `glm-5.3` |
| `--provider`만 | 지금 Model Resolution에서 그 provider의 기본 모델. `commandcode`는 `meta/muse-spark-1.2-contributor`, `codex-write`는 `gpt-5.6-luna`, `grok`는 `grok-4.6`, `pi`와 `zai-coding`은 `glm-5.3`. Pi 백엔드 이름만 준 경우도 지금 규칙대로 `IMPL_AGENT=pi`다. 이름 없는 provider의 기본 모델로 glm 쌍을 끼워 넣지 않는다 |
| `--model`만 | `pi` / `zai-coding` / 그 모델. 다른 provider를 쓰고 싶으면 `--provider`가 필요하다 |
| 둘 다 | 지금 Model Resolution. provider가 에이전트 이름이면 그 에이전트와 그 모델, Pi 백엔드 이름이면 `IMPL_AGENT=pi`와 그 백엔드와 그 모델 |

이것이 빌더 결정이다. 플래그를 안 주면 glm-5.3이고, provider만 주면 그 provider의 기존 기본 모델이다. `--provider commandcode`가 glm으로 바뀌지 않는다.

고른 provider가 `~/.claude/fiftybox-config.json`에서 꺼져 있으면 그 provider만 확인하고 멈춘다. 다른 레인으로 넘어가지 않는다. 설정 파일이 없으면 위 표대로 간다. JSON이 깨졌으면 지금 Step 0처럼 안내하고 멈춘다. 깨진 설정을 기본 쌍으로 무시하고 계속 가지 않는다.

## 워크플로

세션이 쓸 수 있는 파일은 아티팩트 문서뿐이다. 프로젝트 소스와 테스트 파일은 쓰지 않는다. 지금 Step 4의 테스트 예외는 삭제한다.

### 1. 계획서 수집

사용자가 준 계획서를 고친 없이 `<artifactDir>/design.md`에 복사한다. 요약하지 않는다. 줄을 줄이지 않는다. orchestrate는 `--skip-verify`여도 이 파일을 읽는다. 없으면 implement가 실패한다.

계획에 구현자가 테스트를 만들라고 적혀 있으면 구현자가 만든다. 세션이 미리 만들지 않는다.

### 2. Setup

지금과 같이 `orchestrate.py --phase setup`을 돌리고 `artifactDir`과 `worktree`를 챙긴다. 선택한 쌍을 `<artifactDir>/model-choice.json`에 남긴다. 태스크마다 다른 쌍을 적지 않는다.

Preflight는 선택한 provider만 한다. CommandCode면 기존 `cc_preflight.py`, Grok이면 `grok inspect`, Pi Coding Plan이면 `pi --list-models zai-coding`에 고른 모델이 있는지만 본다. `codex-write`면 `codex exec --help`와 `workspace-write` 지원만 본다. 실패하면 로그인이나 설치를 안내하고 멈춘다. 다른 provider로 대체하지 않는다.

### 3. 일 단위

세션이 계획 산문으로 태스크를 만들어 내지 않는다. 구현 프로세스는 항상 하나다. 세션이 일마다 `implement`를 나누어 띄우지 않고, 동시에 여러 개를 띄우지 않는다.

`orchestrate.py`는 `<artifactDir>/task-batches.md`의 마지막 ` ```json ` 블록이 `parse_task_batches`를 통과하면 `--task`를 무시하고 그 목록을 한 프로세스에서 순서대로 실행한다. 항목마다 프롬프트를 그 항목의 `description`과 `files`로 좁히고, 첫 실패에서 멈춘다. `parallelGroup`은 읽지 않는다. 이 스킬은 그 동작을 그대로 쓴다. 병렬을 위해 orchestrate를 고치지 않는다.

- 계획서에 그런 JSON 블록이 하나 있고, 그대로 복사했을 때 `parse_task_batches`가 빈 목록이 아니면, 그 블록만 `<artifactDir>/task-batches.md`에 복사한다. 세션은 항목을 고치거나 보태거나 빼지 않는다.
- 블록이 없거나, 복사해도 `parse_task_batches`가 빈 목록이면 `task-batches.md`를 만들지 않는다. 계획서 전체가 구현 한 번이다.
- 산문에 «parallel»이라고 적혀 있어도 무시한다.

이것이 빌더 결정이다. 검토에서 일마다 detached 호출과 «orchestrate 변경은 검증 플래그뿐»이 서로 깨뜨린다는 지적이 있었다. 사용자는 세션이 일을 다시 쪼개지 않기로 했고, 병렬을 요구하지 않았다. 그래서 병렬과 일마다 호출은 뺀다. 목록이 없는 계획이 한 번의 구현이 되는 것은 그대로다. 계획이 길어서 구현 모델이 못 끝내는 위험은 사용자가 이미 받은 제한이다. 세션이 그걸 이유로 쪼개지 않는다.

### 4. 구현

세션은 구현 파일을 쓰지 않는다. 호출은 detached 한 번이다. foreground `--phase implement`는 금지다.

```bash
nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<작업 설명>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent "<AGENT>" --provider "<PROVIDER>" --model "<MODEL>" \
  --skip-verify \
  > "<artifactDir>/implement.out" 2>&1 &
```

`--skip-verify`는 유지한다. 이 스킬은 설계 검증을 하지 않는다.

`task-batches.md`가 있으면 orchestrate가 항목별 프롬프트를 만든다. 세션은 그 프롬프트를 다시 쓰지 않는다. `task-batches.md`가 없으면 `--task`와 `design.md` 전문이 그 한 번의 구현 범위다. 세션이 쓴 테스트 파일을 붙이지 않는다.

목록 안의 한 항목이 실패하면 orchestrate가 그 프로세스 전체를 멈춘다. 세션은 남은 항목을 이어서 호출하지 않는다. 이미 적용된 변경과 작업 공간은 지우지 않고, 실패한 항목 번호를 보고한 뒤 멈춘다. complete와 deploy로 가지 않는다. 계획의 나머지 단위가 실행되지 않은 상태이기 때문이다.

구현 프로세스가 끝나고 변경 파일이 있으면 세션은 diff를 읽고 판정하지 않는다. 테스트 명령을 돌려 통과 여부를 게이트로 삼지 않는다. 변경 파일이 없으면 아래 `no_changes`다. 배포까지 가지 않는다.

### 5. 검증 단계를 품질 게이트로 쓰지 않는다

`orchestrate.py`의 `complete`는 `summary.phases.review_test.status`가 `success`일 때만 진행한다. `review-test`는 테스트 명령을 찾으면 실행하고, 실패하면 status를 `success`로 남기지 않는다. `--skip-codex-review`는 리뷰어만 건너뛰고 테스트 실패는 그대로 막는다.

이 스킬은 그 실패로 push를 막으면 안 된다. 테스트 명령을 `true`로 속여 통과시키는 방식은 금지다. 커밋 메시지가 테스트를 통과했다고 거짓말하게 된다.

빌더 결정: `orchestrate.py`에 검증을 건너뛰는 플래그를 하나 추가한다. 이름과 인자는 빌더가 정한다. 동작은 다음으로 고정한다.

- 테스트 명령을 실행하지 않는다.
- 리뷰 모델을 호출하지 않는다.
- `review_test` status를 `success`로 기록해 `complete`가 진행되게 한다.
- `complete`가 만드는 커밋 메시지는 테스트가 통과했다고 쓰지 않는다. 검증을 건너뛰었고, 인수는 배포 후 사용자가 한다고 쓴다.
- 플래그가 없으면 지금처럼 테스트 실패가 `complete`를 막는다. `fiftybox-local`과 다른 호출자는 플래그를 주지 않으므로 지금 동작이 유지된다.

이 스킬은 `complete` 전에 그 플래그로 `review-test`를 한 번 호출한다. 테스트 실패를 보고 구현을 자동으로 한 번 더 돌리지 않는다. 그 자동 재시도는 삭제한다.

### 6. Complete, deploy, cleanup

`review_test`가 위 플래그로 `success`가 된 뒤에만:

1. `--phase complete` — main에 합치고 `git push origin HEAD:main`. 사용자에게 미리 물어보고 멈추지 않는다.
2. `--phase deploy` — 고른 구현 쌍을 그대로 넘긴다. 배포 설정이 없으면 orchestrate가 지금처럼 건너뛴다.
3. `--phase cleanup`

`incomplete_commit`이면 cleanup하지 않는다. 작업 공간의 유일한 사본을 지우기 때문이다. 원인을 보고하고 멈춘다.

Deploy-only (`/fiftybox-execute deploy`, «그냥 배포만»)는 유지한다. Setup부터 complete까지를 건너뛰고, 지금처럼 최소 아티팩트로 deploy 게이트만 통과시킨다. 구현 쌍은 같은 기본값 또는 플래그를 쓴다.

끝난 보고는 배포가 됐는지, 작업 공간과 브랜치, `summary.json`의 상태다. 코드가 계획과 맞다는 문장은 넣지 않는다. 무엇을 실행해 보면 되는지만 적는다. 계획서에 확인 방법이 없으면 «배포된 결과를 직접 확인해 달라»고만 한다.

## 구현 호출이 죽었을 때

품질이 나빠서가 아니라 결과가 없을 때만 멈춘다. 로그 분류는 지금 표를 유지한다.

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
- `model`: 그 provider의 모델 목록을 보여주고 사용자가 고른 모델로 그 일만 다시 호출한다. 세션이 더 센 모델을 골라 주지 않는다.
- `max_turns`, `timeout`: 계획을 더 작은 단위로 고쳐 달라고 사용자에게 말한다. 세션이 계획을 쪼개지 않는다. timeout 값을 올려 조용히 재시도하지 않는다.
- `no_changes`: 구현 모델이 끝났다고 했는데 저장소 파일이 바뀌지 않았다. complete와 deploy로 가지 않는다. 세션이 대신 구현하지 않는다. 로그를 보고하고 멈춘다.
- 어떤 분류에서도 세션이 구현하지 않는다. 자동 재시도는 없다.

계정 단위 실패(`auth`, `window`, `credit`)면 그 구현 프로세스를 끝난 것으로 보지 않는다. 목록 실행 중 한 항목이 이 이유로 죽으면 나머지 항목은 orchestrate가 이미 멈추므로, 세션이 나머지를 다시 띄우지 않는다.

## 사용자가 나중에 다시 시킬 때

이 스킬의 성공 경로에 없는 일이다. 배포 뒤에 사용자가 이상하다고 하면, 사용자는 직접 되돌리거나, 새 계획으로 `opus-plan`을 다시 돌리거나, 이 스킬을 새로 호출한다. 새로 호출할 때 고칠 말을 작업 설명에 포함하면 구현 프롬프트에 그 말을 계획서와 함께 붙인다. 세션이 «구현 모델에게 보낼지, 계획을 다시 쓸지»를 고르지 않는다. 사용자가 호출 방식으로 이미 고른 것이다.

데이터 삭제, 마이그레이션, 외부 발송처럼 되돌리기 어려운 변경도 따로 멈추지 않는다. 이것이 빌더 결정이 아니라 사용자와 맞춘 내용이다. 사용자는 배포까지 자동으로 가고, 이상하면 자신이 되돌리기로 했다. 멈춤 예외를 만들지 않는다.

## 손댈 파일

저장소가 원본이다. 세션이 실행하는 설치본은 별도 복사본이고 내용이 같을 때만 이 변경이 적용된다. 작업이 끝나려면 아래 두 위치가 같은 내용이어야 한다.

| 원본 | 설치본 |
|---|---|
| `skills/fiftybox-execute/SKILL.md` | `~/.claude/skills/fiftybox-execute/SKILL.md` (`~/.claude-vibeproxy/skills/fiftybox-execute`와 같은 디렉터리) |
| `skills/fiftybox-orchestration/scripts/orchestrate.py` | `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py` |

설치 시스템을 새로 만들지 않는다. 원본을 고친 뒤 설치본을 같은 내용으로 맞춘다.

`SKILL.md` description은 언제 쓰는지와 호출만 적는다. Red/Green/리뷰 순서를 description에 적지 않는다. 적으면 세션이 본문 대신 description을 따른다.

오케스트레이션 쪽 변경은 검증 건너뛰기 플래그와, 그 플래그를 썼을 때의 커밋 문구뿐이다. 플래그가 없을 때의 `review-test`와 `complete` 게이트는 유지한다. 그 플래그의 테스트를 orchestrate 테스트가 있는 곳에 추가한다. 없는 위치는 빌더가 찾아서, 없으면 그 스크립트 곁에 그 동작만 검증하는 테스트를 추가한다.

## 안전 계약

- 세션은 `.omx/artifacts/` 밖의 프로젝트 파일을 쓰지 않는다. 테스트 파일 예외는 없다.
- force push, force merge, reset hard, `-D` 브랜치 삭제는 하지 않는다. 사용자가 나중에 직접 되돌리는 것이지, 이 스킬이 되돌리지 않는다.
- provider는 커밋하거나 push하지 않는다. 커밋과 push는 `--phase complete`만 한다.
- push는 complete 전에 하지 않는다. complete는 검증 건너뛰기 플래그로 `review_test`가 `success`가 된 뒤에만 한다.
- 구현 호출이 죽으면 선택지를 제시하고 조용히 구현하거나 다른 모델로 넘기지 않는다.
- 구현 프로세스는 하나다. 세션이 일마다 나누어 띄우거나 동시에 여러 개를 띄우지 않는다.
- 세션은 계획서, 속도, 모델 가용성과 무관하게 구현 코드를 직접 쓰지 않는다.
- `no_changes`이거나 목록의 한 항목이 실패하면 complete와 deploy로 가지 않는다.

## 빌더가 정하면 되는 것

- 검증 건너뛰기 플래그의 이름과 CLI 표기.
- 설치본을 원본과 맞추는 복사 방법.
- orchestrate 테스트를 어느 파일에 넣을지.
- `SKILL.md`의 문장 순서와 표의 재배치. 위 금지와 허용은 유지한다.

## 빌더가 정하면 안 되는 것

- 세션이 테스트를 쓰거나 diff를 판정하게 되돌리는 것.
- 레인 배정기를 기본 경로에 남기는 것.
- 테스트 실패나 리뷰 판정이 push를 막게 두는 것.
- `true` 같은 가짜 테스트 명령으로 게이트를 통과시키는 것.
- `opus-plan`, `fiftybox-local`, `diff_review.py`를 이 변경에 끌어들이는 것.
- 일마다 `implement`를 띄우거나, `parallelGroup`을 읽도록 orchestrate를 고치는 것.
- `--provider`만 줬을 때 그 provider를 glm 쌍으로 바꾸는 것.
