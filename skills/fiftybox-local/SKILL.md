---
name: fiftybox-local
description: Use when implementation should run on the fixed local executor — Mac Studio Qwen3.8-Flash-Next oQ4e-mtp (oMLX over Tailscale, co-resident lanes: Qwen3.8-27B 8-bit, Gemma4-26B-A4B) via Pi CLI — sequential TDD with no discovery and no model switching. Also when the user invokes /fiftybox-local or $fiftybox-local.
---

# Fiftybox Local

구현 페이즈를 맥스튜디오(M4 Max 128GB) oMLX 서버(8000번)의 Qwen3.8-Flash-Next(oQ4e-mtp)로만
돌린다. **executor는 고정이다** — 후보 탐색, 폴백 순서, 모델 교체가 없다.

**핵심 루프:** 오케스트레이터(Claude/Codex)가 실패하는 테스트 작성(Red) → 로컬 모델이 통과시킴(Green)
→ 오케스트레이터가 **묶음** 단위로 리뷰. **순차** 실행(모델이 하나뿐이라 병렬 디스패치가 없다).

## Claude 사용량 계약

Claude 비용은 `모델 호출 횟수 × 그때의 대화 크기`다. 로컬 모델이 공짜여도 오케스트레이터 턴이
많으면 Sonnet 직접 구현보다 비싸다(실측: 7태스크에 Opus 60회, 호출당 평균 17만 토큰 → 약 $3.6 vs
Sonnet $0.4~0.5). 그래서:

1. 기계적 일은 `fbl_task.py` 한 번에 맡긴다 — 헬스체크·dry-run·길이 게이트·디스패치·테스트·
   변조/범위/skip/외국문자 검사·메트릭 기록.
2. **폴링 금지.** 폴링 한 번 = 대화 전체 재읽기. 배경 실행 후 알림을 기다린다.
3. 리뷰는 **묶음당 1회**(최대 5태스크): `VERDICT` 줄 → 주석 뺀 `diff` 1회.
4. **세션 위생을 지킨다**([Step 0](#step-0-세션-위생)). 스크립트가 이미 출력한 값을 다시 확인하지 않는다.

## ⛔ 절대 금지

**오케스트레이터는 구현 파일을 직접 쓰거나 고치지 않는다.** 예외 없다. 쓸 수 있는 파일은 테스트
파일(Red)과 아티팩트 문서(`<artifactDir>/design.md`, `tasks/task-N.md` 등)뿐이다. 스크립트나
orchestrate.py가 실패하면 사용자에게 보고한다. 대신 구현하지 않는다.

## 호출

```
/fiftybox-local "<작업 설명>"        /fiftybox-local --resume <artifactDir>        $fiftybox-local "<작업 설명>"
```

provider/model 플래그가 없다. `fbl_task.py`의 `--executor`도 쓰지 않는다(예외 레인은 [reference.md](reference.md)).

## Executor (고정)

| 항목 | 값 |
|---|---|
| `IMPL_AGENT` | `pi` |
| `IMPL_PROVIDER` | `macstudio-qwen-flash-next` |
| `IMPL_MODEL` | `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp` |
| `IMPL_TIMEOUT` | `1800` |

`fbl_task.py`가 모든 디스패치에 이 네 값을 넘긴다. orchestrate.py를 직접 부를 때는 **전부** 명시한다
(`--provider`를 빠뜨리면 기본값 `opencode-go`로 조용히 나간다).

**백엔드:** Pi `~/.pi/agent/models.json`의 `macstudio-qwen-flash-next` → `http://100.115.199.115:8000/v1`
(oMLX, brew 서비스). **Bearer 인증 필수** — 키는 `~/.config/opencode/macstudio-omlx.key`. 컨텍스트 262,144,
max tokens 16,384. 11234번(Qwen3.8-27B 8bit)·11235번(Gemma4)은 별도 프로세스이고, Flash-Next는 상주
약 75GB라 동시 구동하면 메모리를 경합한다 — oMLX memory guard는 `aggressive` tier(다른 레인 메모리
절반을 압축기로 동원, `~/.omlx/settings.json`)라 Gemma4가 idle로 떠 있어도 램 여유가 있으면 작업이
시작된다. tier를 임의로 되돌리지 않는다. 어떤 포트도 임의로 끄지 않는다. 서버 절차는 [reference.md](reference.md).

**ioh 대체 레인:** 스튜디오 8000번이 장기 불가일 때만 `--executor iq3s`로 같은 계열 모델
(ioh PC `qwen3.8-flash-next-iq3_s`, 키 없음, 컨텍스트 65,536, Pi provider명 `ioh`)을 쓴다.
실사용은 사용자 지시가 있을 때만이다([reference.md](reference.md)).

### 실행 예산

| 상수 | 값 | 근거 |
|---|---|---|
| `DESIGN_MD_MAX_LINES` | `70` | 40태스크 연속 성공 후 60→70 (Calibration) |
| `TASK_SPEC_MAX_LINES` | `15` | 205줄·3~4파일 태스크는 `no_changes`로 끝났다 |
| `TASK_MAX_FILES` | `2` | 한 태스크가 소유(수정)할 파일 상한 |
| `INTENT_SUMMARY_MAX_LINES` | `14` | intent 51줄이 낀 1481줄 프롬프트 사고 |
| `PROMPT_MAX_LINES` | `140` | `implement-prompt.md` 실측 게이트 (`31+design+spec+intent`) |

병목은 컨텍스트가 아니라 **출력 `max_tokens` 16,384**다. 컨텍스트가 남는다고 태스크를 키우지 않는다.
상수는 `fbl_task.py` 맨 위 한 곳에 있고, 값 조정은 사용자 승인 후에만 한다(Calibration: [reference.md](reference.md)).

### 설정 게이트

시작 전에 `~/.claude/fiftybox-config.json`을 읽는다(`/fiftybox-config`가 관리).
`providers.pi.backends.macstudio-qwen-flash-next`의 `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp`가 꺼져 있거나
없으면 중단하고 `/fiftybox-config`로 켜라고 안내한다. 파일이 없으면 기본값(켜짐).

---

## 워크플로

`FBL=~/.claude/skills/fiftybox-local/scripts/fbl_task.py`, `A=<artifactDir>`.

### Step 0: 세션 위생

이 대화에 이미 다른 작업이 쌓여 있으면(수만 토큰 이상) **준비(Step 1~4)까지만 하고 멈춘다.**
`python3 $FBL status --artifact-dir A`로 확인한 뒤, 세션 종류에 따라 한 줄만 안내한다:

- **ccdx(GLM) 세션** — 그대로 `/compact` 후 이 세션에서 `/fiftybox-local --resume A` 실행.
  모든 실행 상태는 `A` 아래 파일에 있어 compact 요약이 잃을 게 없다.
- **원본 Claude(유료) 세션** — 새 세션으로 넘긴다: `fblr A`(인자 생략 시 최신 A 자동 선택)가
  새 tmux pane에 resume 세션까지 띄운다. 스크립트는 `scripts/fbl_resume`.

`--resume A`로 호출됐으면 Step 1~4를 건너뛰고 `status`부터 한다.

### Step 1: 설계 수집

설계 문서를 받는다(파일 경로 / 인라인 / "현재 디렉터리 컨텍스트 사용"). **executor용 실행계약으로 압축**해
`A/design.md`에 쓴다 — `DESIGN_MD_MAX_LINES`(70) 이하, 배경·동기·대안 토의를 빼고 **파일 목록 / 인터페이스 /
행동 정의**만. 원문은 `A/design-source.md`에 보존한다(executor는 읽지 않는다). 70줄로 압축되지 않으면
그건 태스크가 아니라 프로젝트다 — 더 작은 설계로 분해하도록 요청하고 멈춘다. `design.md`는
`--skip-verify`여도 필수다.

### Step 2: Setup + preflight

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py --phase setup \
  --task "<작업>" --cwd "$(pwd)" --implement-agent pi --provider macstudio-qwen-flash-next
python3 $FBL preflight --artifact-dir A
```

JSON에서 `artifactDir`·`worktree`를 챙긴다. `PREFLIGHT=ok`면 계속한다. `down`/`auth`면
[reference.md](reference.md)대로 처리하고, 8분 안에 못 살리면 `server`로 보고한다(모델 교체 제안 금지).

### Step 3: 태스크 분해 (순차)

설계를 원자적 단위로 쪼개 `A/tasks/task-N.md`로 쓴다:

```markdown
<한 줄 제목>
Modify ONLY: src/probe.py, tests/test_probe.py
- <행동 정의>
```

- 명세 `TASK_SPEC_MAX_LINES(15)`줄 이하, 소유 파일 `TASK_MAX_FILES(2)`개 이하. **`Modify ONLY:` 줄 필수**
  (범위 검사가 이 줄을 쓴다). "A하고 B하고 C"식 복합 태스크는 행동 경계에서 쪼갠다.
- **너무 잘게 쪼개지도 않는다.** 호출 수가 곧 비용이다. 행동 경계가 다르지 않은 인접 조각은 상한까지 합친다.
  명세 9줄 미만 태스크가 줄줄이 이어지면 합칠 곳을 먼저 찾는다.
- `A/task-batches.md`에 ```json 태스크 블록을 넣지 않는다(다중 모드로 바뀐다).

### Step 4: Red 테스트 (오케스트레이터)

묶음(최대 5개)의 Red를 **한 번에** 쓴다. 위치는 `A/tests/task-N/<저장소 기준 상대경로>`, 내용은 그 시점의
**파일 전체**다(같은 파일에 누적되면 누적본). 스크립트가 워크트리에 복사하고 Red를 확인한다 — 이미
통과하면 `RED_ALREADY_PASSES`로 멈추니 파일 존재·동작을 단언하는 Red를 쓴다. 테스트 명령은 첫 `run`에서
`--test-command`로 한 번만 준다(사용자 환경에서 실제로 되는 명령, pytest가 없으면 unittest).

### Step 5: 구현 (Green) — 묶음당 1회

**`run_in_background: true`**로 한 번만 실행한다:

```bash
python3 $FBL run --artifact-dir A --tasks 1-3 --test-command "<명령>"
```

**폴링 금지.** 끝나면 알림이 온다. 그 전에 `sleep`·`grep EXIT_CODE`·`tail` 호출을 하지 않는다. 알림이 없는
환경(Codex 등)은 `--detach`로 띄우고 `python3 $FBL wait --artifact-dir A`(최대 9분 블로킹)를 반복한다. `wait`는 Bash `timeout`을 `600000`으로 지정한다(기본 2분이면 중간에 끊겨 턴이 늘어난다).

태스크마다 스크립트가 한다: 헬스체크 → Red 복사·확인 → 예산 검사 → dry-run 길이 게이트(`PROMPT_MAX_LINES`) →
실디스패치(`A/implement-task-N.out`, 마지막 줄 `EXIT_CODE=`) → 검사 → `A/executor-metrics.md` 행 추가.
출력은 태스크당 한 줄이다:

```
TASK=2 VERDICT=CLEAN EXIT=0 CLASS=- SECONDS=143 PROMPT=81 TESTS=pass TAMPER=none SCOPE=none SKIPS=none SCRIPT=none DIFF=+34/-2 COMMENTS=18%
```

`CLEAN`이면 다음 태스크로 가고, `FLAG`(검사 걸림)·`FAIL`(테스트/디스패치 실패)·`STOP`(디스패치 전 중단)이면
거기서 멈춘다. `STOP` 사유: `PREFLIGHT` `BUDGET` `GATE` `RED_ALREADY_PASSES` `NO_RED_TESTS` `SPEC_MISSING`
`RETRY_BUDGET` `NO_TEST_COMMAND`.

### Step 6: 묶음 리뷰 (묶음당 1회)

1. `VERDICT` 줄만 읽는다. 걸린 항목만 처리한다: `TAMPER`→테스트 되돌리고 재실행, `SCOPE`→범위 밖 파일 되돌림,
   `SKIPS`·`SCRIPT`→해당 줄 수정 요청.
2. 전부 `CLEAN`이면 `python3 $FBL diff --artifact-dir A`를 **1회** 실행한다(주석·docstring 뺀 묶음 diff).
   명세와 한 줄씩 대조하고 선행 태스크와의 인터페이스를 확인한다. diff만으로 판단이 안 될 때만 파일을 읽는다.
3. 고칠 게 있으면 피드백을 `A/feedback-N.txt`에 쓰고
   `python3 $FBL run --artifact-dir A --tasks N --retry-feedback-file A/feedback-N.txt`.
   **자동 재시도는 태스크당 1회**다. 두 번째도 실패하면 사용자에게 선택지를 제시한다.
4. 통과하면 다음 묶음(Step 4~6), 끝났으면 Step 7. 원하면 `fiftybox-execute`와 같은 자연어 opt-in으로
   advisory diff 리뷰(`~/.claude/skills/fiftybox-execute/scripts/diff_review.py`).

### Step 7~10: 마무리

```bash
O=~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py; C='--task "<작업>" --cwd "$(pwd)" --artifact-dir A'
python3 $O --phase review-test $C --skip-codex-review      # 첫 실패 시 해당 태스크 run --retry 1회
python3 $O --phase complete $C
python3 $FBL preflight --artifact-dir A                    # deploy 직전
python3 $O --phase deploy $C --implement-agent pi --provider macstudio-qwen-flash-next \
  --model Jundot--Qwen3.8-Flash-Next-oQ4e-mtp --implementation-timeout 1800
python3 $O --phase cleanup $C
python3 $FBL calibrate --repo "$(pwd)"                     # 한 줄을 최종 보고에 붙인다
```

`ADVICE`가 `KEEP`이 아니면 누적 행을 사용자에게 보여주고 **승인 후에만** 상수를 바꾼다.
`summary.json`의 최종 상태를 보고한다.

---

## 실패 처리

스크립트가 `.out` 로그와 `EXIT_CODE`로 `CLASS`를 이미 분류한다. 다시 분류하지 말고 대응만 따른다.
**executor가 하나뿐이므로 모델·provider 교체는 어떤 분류에서도 선택지가 아니다.**
**유료 모델·원격 무료 모델로 전환하지 않는다.**

| CLASS | 대응 |
|---|---|
| `server` | preflight부터 다시(기동 포함) 후 같은 설정으로 1회 재시도 |
| `timeout` | timeout을 **올리지 않는다.** 행동 경계에서 하프 2개로 분할, 하프별 Red를 새로 쓰고 순차 재디스패치(재시도 1회 소비) |
| `too_long` | 입력이 예산을 넘은 것. 넘친 항목만 줄인다(design 압축 / 명세 하프 분할) |
| `no_changes` | 예산 초과 여부 먼저 점검 → 넘쳤으면 `too_long`처럼 쪼갠다. 아니면 1회 재시도, 반복되면 프롬프트 문제로 보고 |
| `model`·`orchestrate`·`unknown` | 스킬/설정 버그. 멈추고 로그 원문과 함께 보고 |

어떤 실패에서도 오케스트레이터가 대신 구현하지 않는다. 보고에는 레인
(`pi/macstudio-qwen-flash-next/Jundot--Qwen3.8-Flash-Next-oQ4e-mtp`), 분류, `.out` 인용 + `EXIT_CODE`,
예산 점검(spec/files/design/prompt 줄수), 추천 행동 2~4개를 담는다.

## 안전 계약

`/fiftybox-orchestration`에서 상속: `.omx/artifacts/` 밖 직접 편집 금지(Red 테스트 파일은 명시적 예외) /
force push·force merge·reset hard·`-D` 브랜치 삭제 금지 / Phase 7 이전 push 금지 / provider는 커밋·푸시하지
않는다 / 자동 재시도는 태스크당 1회만, 실패 시 조용히 복구하지 않고 선택지를 제시한다.

이 스킬 고유:

- executor는 `pi`/`macstudio-qwen-flash-next`/`Jundot--Qwen3.8-Flash-Next-oQ4e-mtp`로 고정이다. 어떤
  실패·속도 문제도 모델이나 provider를 바꾸지 않는다.
- provider는 테스트 파일을 수정하지 않는다(`TAMPER` 검사). 수정했으면 되돌리고 재실행한다.
- `--dangerously-skip-permissions`는 orchestrate가 만든 격리된 워크트리 안에서만 유효하다.
- 디스패치 앞에는 항상 Bearer 헬스체크를 한다(`fbl_task.py run`이 매 태스크 앞에서 한다). 8000번 oMLX와
  11234/11235번 레인을 이 스킬이 임의로 끄거나 재시작하지 않는다.
- `--phase implement`를 foreground로 직접 돌리지 않는다(10분 한도에 죽는다). 항상 `fbl_task.py`를 통한다.
- 길이 게이트(`PROMPT_MAX_LINES`)를 통과하지 않은 태스크는 실디스패치하지 않는다.
- timeout 값을 올리지 않는다. `--implementation-timeout`은 `1800` 고정, 대응은 태스크 쪼개기뿐이다.
- `design.md`는 실행계약이고 원문은 `design-source.md`에 둔다.
