---
name: fiftybox-local
description: Use when implementation should run on the fixed local executor — Mac Studio Gemma4-26B-A4B QAT 4-bit (mlx-serve over Tailscale, co-resident with Qwen3.8-27B 8-bit) via Pi CLI — sequential TDD with no discovery and no model switching. Also when the user invokes /fiftybox-local or $fiftybox-local.
---

# Fiftybox Local

구현 페이즈를 맥스튜디오(Mac Studio M4 Max 128GB) mlx-serve 서버의
Gemma4-26B-A4B(QAT 4-bit)로만 돌린다. **executor는 고정이다** — 후보 탐색,
폴백 순서, 모델 교체가 모두 없다.

**핵심 루프:** 오케스트레이터(Claude/Codex)가 실패하는 테스트 작성(Red) → 로컬
모델이 통과시킴(Green) → 오케스트레이터 리뷰

**실행 방식:** 순차. 모델이 하나뿐이므로 병렬 디스패치가 없다 — 태스크를 한
줄씩, 앞 태스크의 리뷰가 끝나면 다음 태스크를 디스패치한다. 각 태스크는
[`Gemma4 실행 예산`](#gemma4-실행-예산) 상한 안에서만 디스패치된다.

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
/fiftybox-local "<작업 설명>"
$fiftybox-local "<작업 설명>"
```

provider/model 플래그가 없다 — executor가 고정이기 때문이다.

---

## Executor (고정)

| 항목 | 값 |
|---|---|
| `IMPL_AGENT`(`--implement-agent`) | `pi` |
| `IMPL_PROVIDER`(`--provider`) | `macstudio-gemma4` |
| `IMPL_MODEL`(`--model`) | `mlx-community--gemma-4-26B-A4B-it-qat-4bit` |
| `IMPL_TIMEOUT`(`--implementation-timeout`) | `1800` |

모든 디스패치(implement·재시도·deploy)에 이 네 값을 **전부** 넘긴다.
`--implement-agent`는 에이전트 레지스트리 키(`pi`)만 받는다. `--provider`를
빠뜨리면 기본값 `opencode-go`로 조용히 나가므로 반드시 명시한다.

**백엔드 실체:** Pi `~/.pi/agent/models.json`의 `macstudio-gemma4` →
`http://100.115.199.115:11235/v1`(맥스튜디오 Tailscale IP, mlx-serve 26.9.6).
**인증이 없다** — `apiKey`는 더미 `EMPTY`고 Bearer 헤더 불필요. 컨텍스트
262,144, max tokens 16,384. 같은 호스트의 11234번(Qwen3.8-27B 8-bit)은 **별도
mlx-serve 프로세스**다 — 서로 독립이라 한쪽 재시작이 다른 쪽에 영향을 주지
않는다. 컨텍스트가 넓어도 태스크 프롬프트와 design.md 발췌는 간결하게 유지한다.
서버 운용 기록은 `~/Desktop/develop-a/local-model/`(모델 전환·평가 리포트).

### Gemma4 실행 예산

executor가 한 번의 디스패치로 처리할 수 있는 입력 크기의 정량 상한이다. 태스크는
디스패치 전에 이 예산을 통과해야 한다.

| 상수 | 값 | 근거 |
|---|---|---|
| `DESIGN_MD_MAX_LINES` | `60` | 클린 성공 태스크의 design은 22~54줄 band였다 |
| `TASK_SPEC_MAX_LINES` | `15` | 205줄·3~4파일 태스크는 반복 재시도 후 `no_changes`로 끝났다 |
| `TASK_MAX_FILES` | `2` | 단일 태스크가 소유(수정)할 수 있는 파일 상한 |
| `INTENT_SUMMARY_MAX_LINES` | `14` | intent 51줄이 낀 1481줄 프롬프트 사고가 실존한다 |
| `PROMPT_MAX_LINES` | `120` | 실측 게이트 — `implement-prompt.md`의 `wc -l` |

**산수:** `orchestrate.py`가 `implement`마다 고정 템플릿 **31줄** + 태스크 명세 +
`design.md` 전문 + `intent-summary.md`를 `implement-prompt.md`로 합친다. 즉
`프롬프트 = 31 + design + spec + intent`이고, 위 상한을 전부 채우면
`31+60+15+14 = 120`으로 게이트에 딱 맞는다. 하나라도 넘으면 게이트에서 떨어진다.
(실측: design 40 → 프롬프트 79 / design 100 → 프롬프트 139)

**병목:** 컨텍스트는 262,144지만 `max_tokens`가 **16,384**라 **출력이 먼저** 막힌다.
`IMPL_TIMEOUT`은 `1800`초. 컨텍스트가 남는다고 태스크를 키우지 않는다.

**Calibration:** Step 6의 `gemma4-metrics.md`에 태스크별 실측을 누적한다. 최근
5태스크 성공률 < 80% → `DESIGN_MD_MAX_LINES` 60→45, `PROMPT_MAX_LINES` 120→100.
10태스크 연속 100% → `DESIGN_MD_MAX_LINES` 60→70, `PROMPT_MAX_LINES` 120→140.
조정은 누적 실측을 보여주고 **사용자 승인 후** 반영한다. 임의로 바꾸지 않는다.

### 설정 게이트

시작 전에 `~/.claude/fiftybox-config.json`을 읽는다(`/fiftybox-config` 스킬이
관리한다). `providers.pi.backends.macstudio-gemma4.models`의
`mlx-community--gemma-4-26B-A4B-it-qat-4bit`이 꺼져 있으면 중단하고
`/fiftybox-config`로 켜라고 안내한다. config 파일이 없으면 기본값(켜짐)으로
진행한다.

---

## 맥스튜디오 서버 preflight

11235번 mlx-serve는 Gemma4-26B-A4B를 단독 서빙하는 **launchd 관리 상시
서버**다. 배치 디스패치, 실패 재시도, Phase 7b deploy — **디스패치 앞에
매번** 아래 1번 헬스체크를 한다. `200`이면 나머지 단계는 건너뛴다(웜업은
실행당 1회).

1. **헬스체크(인증 없음):**

```bash
curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
  http://100.115.199.115:11235/v1/models
```

- `200` → 서버·모델 정상. 이번 실행에서 웜업(5번)을 아직 안 했으면 5번만
  한다.
- 연결 실패 → 2번으로 간다.

2. **`200`이 아니면 스튜디오 상태 확인(SSH):**

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 tanpapa@100.115.199.115 \
  'source ~/.zprofile 2>/dev/null; echo ---11235---;
   lsof -nP -iTCP:11235 -sTCP:LISTEN; echo ---11234---;
   lsof -nP -iTCP:11234 -sTCP:LISTEN; echo ---8000---;
   lsof -nP -iTCP:8000 -sTCP:LISTEN'
```

- SSH 실패 → 스튜디오가 꺼져 있거나 오프라인. 중단하고 보고한다.
- **8000번(oMLX)이 LISTEN이면 경고만 한다** — oMLX는 휴면 중이어야 정상이며,
  떠 있으면 Flash/Q4까지 메모리를 잡아 11235와 경합한다. 사용자에게 알리고
  임의로 끄지 않는다.
- 11234번은 8bit 상주 레인(정상 상태). 끄지 않는다.
- 11235번이 LISTEN인데 1번 체크가 실패하면 로그 확인:
  `ssh tanpapa@100.115.199.115 'tail -20 ~/mlx-serve-gemma4.log'`

3. **서버 기동(11235번이 죽어 있을 때만):** launchd로 관리된다.

```bash
ssh -o BatchMode=yes tanpapa@100.115.199.115 \
  'launchctl kickstart -k gui/$(id -u)/com.tanpapa.mlx-gemma4'
```

플레인이 없으면 수동 기동(**`source ~/.zprofile`을 빼면 non-interactive
SSH에서 mlx-serve를 못 찾는다**):

```bash
ssh -o BatchMode=yes tanpapa@100.115.199.115 \
  'source ~/.zprofile; nohup mlx-serve --model ~/.omlx/models/mlx-community--gemma-4-26B-A4B-it-qat-4bit --serve --host 100.115.199.115 --port 11235 --ctx-size 262144 >> ~/mlx-serve-gemma4.log 2>&1 &'
```

이 스킬이 서버를 새로 띄웠는지 기록해 둔다.

4. **폴링:** 30초 간격으로 최대 16회(8분). 로그는
`ssh tanpapa@100.115.199.115 'tail -20 ~/mlx-serve-gemma4.log'`로 본다.

```bash
for i in $(seq 1 16); do
  sleep 30
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    http://100.115.199.115:11235/v1/models || true)"
  echo "boot-check $((i*30))s: ${code:-<empty>}"
  if [ "$code" = "200" ]; then echo READY; break; fi
done
```

8분 안에 `200`이 아니면 디스패치하지 않고 `server`로 분류해 보고한다.
모델 교체를 제안하지 않는다 — executor가 하나뿐이다.

5. **Gemma4 웜업(실행당 1회):** 모델은 서버 기동 시 로드되므로 lazy-load
   대기는 필요 없다. 첫 디스패치 직전 생성 경로 확인을 1회만:

```bash
curl -s -o /dev/null -w '%{http_code}\n' --max-time 120 \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community--gemma-4-26B-A4B-it-qat-4bit","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
  http://100.115.199.115:11235/v1/chat/completions
```

`200`이면 READY. 타임아웃 시 30초 뒤 한 번 더 한다. 두 번째까지 실패하면
`server`로 분류한다.

---

## 실패 처리

`orchestrate.py`는 구현 경로에 실패 분류 필드를 만들지 않는다. 로그를 직접
읽어 아래 표로만 분류한다.

### 근거 파일

| 근거 | 신호 |
|---|---|
| `<artifactDir>/implement-task-N.out`의 `EXIT_CODE=` 줄 | Step 5 디스패치 래퍼가 남긴다 |
| `.out` 본문의 provider CLI 원문 | 연결 오류·모델 거부 문구는 여기서만 보인다 |

### 분류표

| 로그 신호 | 분류 |
|---|---|
| `Connection refused`, `Failed to connect`, 요청 중 EOF·502 | `server` |
| `Unknown model`, 404, 410, 모델 ID 거부 | `model` |
| `EXIT_CODE=124` | `timeout` |
| `EXIT_CODE=3`인데 태스크가 예산 초과였다(명세 >15줄 또는 파일 >2개 또는 design >60줄) | `too_long` |
| 응답이 문장 도중에 잘림 — `max_tokens 16384` 출력 한도 신호 | `too_long` |
| `changedFiles`가 명세 파일 수보다 적음 | `too_long` |
| `EXIT_CODE=3` (변경 파일 없음), 태스크는 예산 이내 | `no_changes` |
| `EXIT_CODE=1` + `not in the agents list`, `unrecognized arguments` | `orchestrate` |
| 그 외 | `unknown` |

### 대응

**executor가 하나뿐이므로 모델·provider 교체는 어떤 분류에서도 선택지가
아니다. 유료 모델·원격 무료 모델로 전환하지 않는다.**

- `server` → [preflight](#맥스튜디오-서버-preflight)부터 다시 실행(재기동
  포함) 후 같은 3축으로 1회 재시도한다.
- `timeout` → **timeout 값은 올리지 않는다.** timeout은 "입력이 길다"의 다른
  얼굴이다. 헬스체크로 서버가 살아있는지 확인한 뒤 태스크를 **행동 경계에서 하프
  2개로** 분할하고, 하프별 Red 테스트를 Step 4를 준용해 다시 쓴 뒤 **첫 하프부터
  순차로** 재디스패치한다. 이는 원 태스크의 1회 재시도 예산을 소비한다. 하프까지
  실패하면 사용자에게 선택지를 제시한다.
- `too_long` → 입력이 [`Gemma4 실행 예산`](#gemma4-실행-예산)을 넘긴 상태다.
  넘친 항목을 줄인다 — design이면 Step 1 실행계약 압축, 명세면 Step 3 하프
  분할 — Step 5의 dry-run 게이트를 다시 통과시킨 뒤 재디스패치한다. 재시도는
  태스크당 1회 예산 안에서 한다. timeout 값을 올리는 것으로 해결하지 않는다.
- `no_changes` → 재디스패치하기 전에 **먼저** 이 태스크가 예산 상한을 넘지는
  않았는지 점검한다(명세 줄수·소유 파일수·design 줄수). 넘쳤다면 `no_changes`가
  아니라 `too_long`으로 재분류해 쪼개기로 대응한다. 예산 이내였으면 같은 3축으로
  1회 재시도하고, 반복되면 프롬프트 문제로 보고한다.
- `model` → `~/.pi/agent/models.json`의 백엔드 정의와 서버의 실제 모델 id가
  갈라진 것이다. 확인은 preflight 1번과 같은 curl로 `/v1/models`를 본다.
  스킬/설정 버그로 보고한다.
- `orchestrate` — 스킬/설정 버그다. 파이프라인을 멈추고 보고한다.
- `unknown` — 로그 원문과 함께 사용자에게 보고한다.

**자동 재시도는 태스크당 1회만.** 재시도까지 실패하면 사용자에게 선택지를
제시한다. 어떤 실패에서도 오케스트레이터가 대신 구현하는 것은 금지다.

### Failure Report Format

```markdown
**Task N 실패**

**레인:** pi/macstudio-gemma4/mlx-community--gemma-4-26B-A4B-it-qat-4bit
**분류:** <server | model | timeout | too_long | no_changes | orchestrate | unknown>
**근거:** <.out 로그에서 인용한 줄 + EXIT_CODE>
**예산 점검:** <spec N줄 / files N개 / design N줄 / prompt N줄 — 상한 초과 여부>
**추천 행동:**
1. <선택지 1 — 초과가 원인이라면 "하프 2개로 쪼개서 재디스패치">
2. <선택지 2>
```

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

**executor용 실행계약으로 압축한다.** `<artifactDir>/design.md`는
`DESIGN_MD_MAX_LINES(60)`를 넘기면 안 된다. **executor용** 파일이므로 배경·동기·
대안 토의·태스크 분할 계획을 빼고 **파일 목록 / 인터페이스 / 행동 정의**만 남긴다.
`orchestrate.py`가 매 디스패치마다 이 파일 **전문**을 `implement-prompt.md`에
통째로 집어넣는다 — Step 5의 길이 게이트가 이 줄수를 실측한다.

원문 전문은 `<artifactDir>/design-source.md`에 보존한다. 오케스트레이터와 리뷰
단계만 읽고 **executor는 읽지 않는다**(orchestrate는 `design.md`만 읽는다).

**60줄로 압축할 수 없으면 중단한다.** 설계가 실행계약으로 압축되지 않을 만큼
크면 그건 태스크가 아니라 프로젝트다. 더 작은 설계로 분해할 것을 사용자에게
요청하고 멈춘다. `design.md`를 60줄 넘게 쓰는 것으로 해결하지 않는다.

### Step 2: Setup (Phase 0)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase setup --task "<작업>" --cwd "$(pwd)" \
  --implement-agent pi --provider macstudio-gemma4
```

setup은 에이전트 레지스트리 키(`pi`)와 `pi --list-models
macstudio-gemma4` preflight를 검증한다. JSON 출력에서 `artifactDir`과
`worktree`를 챙긴다. 설계 문서를 복사하고 고정 3축을
`<artifactDir>/model-choice.json`에 기록한다(감사 로그 — 이번 실행 내내 이
한 줄뿐이며 교체는 일어나지 않는다).

### Step 3: 태스크 분해 (순차)

분해하기 전에 먼저 [`Gemma4 실행 예산`](#gemma4-실행-예산) 표를 연다. 아래 상한은
그 예산에서 온 것이다. 설계를 원자적 구현 단위로 쪼개 순차 목록으로 만든다:

```markdown
## Tasks (순차 — executor 1개 고정)

1. Task A → pi / macstudio-gemma4 / mlx-community--gemma-4-26B-A4B-it-qat-4bit
   Modify ONLY: src/probe.py
   lines: spec 9
2. Task B → pi / macstudio-gemma4 / mlx-community--gemma-4-26B-A4B-it-qat-4bit
   Modify ONLY: src/probe.py, tests/test_probe.py
   lines: spec 12
```

**태스크마다 `Modify ONLY:` 소유 라인이 필수다.** 단일 태스크 모드에서는
orchestrate.py가 소유권 섹션을 만들지 않는다(다중 모드만 만든다). 따라서 수정
범위는 태스크 텍스트로만 전달된다. 이 라인이 없으면 executor가 어디까지 만져도
되는지 모른다.

**상한(하나라도 넘으면 그 태스크는 두 개로 쪼갠다):**

- 명세 `TASK_SPEC_MAX_LINES(15)`줄 이하
- 소유 파일 `TASK_MAX_FILES(2)`개 이하
- "A하고 B하고 C"식 **복합 태스크 금지** — 연결사가 보이면 행동 경계에서 쪼갠다
- 같은 파일을 15줄 넘게 수정해야 하면 그 파일의 작업을 **하프 연속 태스크**로
  순차 분할한다(예: 시그니처+스텁 → 로직 → 예외 경로). 파일이 하나라는 사실은
  태스크가 작다는 증거가 아니다.
- 쪼갠 각 하프는 Step 4 Red 테스트도 **각 하프 명세만큼만** 새로 쓴다.

**`<artifactDir>/task-batches.md`에 ```json 태스크 블록을 넣지 않는다.** 넣으면
orchestrate.py가 다중 태스크 모드로 처리한다. 호출 1회 = 태스크 1개다.

### Step 4: 오케스트레이터가 테스트 작성 (Red)

이번 태스크 하나에 대해 실패하는 테스트를 쓴다. `<artifactDir>/tests/`와
실제 프로젝트 테스트 디렉터리 양쪽에 쓴다.

**실패하는지 확인한다(Red):** `<프로젝트 테스트 명령> <테스트 파일>`.
구현 전에 통과하면 다시 쓴다.

### Step 5: 구현 (Green)

[preflight](#맥스튜디오-서버-preflight)가 `200`인지 확인한 뒤 디스패치한다.

**디스패치 전에 길이 게이트를 통과시킨다.** 실디스패치는 아래 게이트를 통과한
것만 내보낸다:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent pi --provider macstudio-gemma4 \
  --model mlx-community--gemma-4-26B-A4B-it-qat-4bit --implementation-timeout 1800 --skip-verify \
  --dry-run

wc -l "<artifactDir>/implement-prompt.md"
```

`--dry-run`은 Pi를 호출하지 않고 `implement-prompt.md`만 만든다(로그에
`[DRY RUN] Skipping Pi CLI implementation`). 플래그 세트는 실디스패치와 **완전히
동일**하게 유지한다 — dry-run이라고 플래그를 빼면 실측이 무의미해진다.

- `wc`가 `PROMPT_MAX_LINES(120)` **이하** → 아래 nohup 실디스패치로 진행한다.
- **초과** → 디스패치하지 않는다. Step 3으로 돌아가 태스크를 하프 2개로 쪼개거나
  Step 1의 실행계약 압축(`design.md` ≤60줄)을 다시 한 뒤 게이트를 재실행한다.
  줄이기 순서는 `design → task 명세 → intent`다
  (`프롬프트 = 31 + design + spec + intent`).
- 게이트를 거치지 않은 실디스패치는 [안전 계약](#안전-계약) 위반이다.

> dry-run이 `summary.json`에 남기는 `dry_run` 상태는 실디스패치가 그대로
> 덮어쓰므로 남겨두어도 무해하다.

**foreground 실행 금지.** `--phase implement`를 foreground로 돌리면 Bash 도구의
10분 한도를 넘겨 파일도 로그도 없이 통째로 죽는다. 반드시 detached로 돌린다:

```bash
nohup bash -c '
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase implement --task "<task>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent pi --provider macstudio-gemma4 \
  --model mlx-community--gemma-4-26B-A4B-it-qat-4bit --implementation-timeout 1800 --skip-verify
echo "EXIT_CODE=$?"
' > "<artifactDir>/implement-task-N.out" 2>&1 &
```

`.out` 파일에 `EXIT_CODE=`가 찍힐 때까지 30~60초 간격으로 폴링한다:

```bash
grep -o 'EXIT_CODE=[0-9]*' "<artifactDir>/implement-task-N.out" | tail -1 || echo RUNNING
```

`EXIT_CODE=`가 확인되면 [실패 처리](#실패-처리)로 분류한다. 0이 아니면
재시도 규칙을, 0이면 Step 6으로 간다.

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

로컬 모델은 지시 준수율 편차가 있다. 이 단계를 건너뛰지 않는다.

**3단계 — 명세 준수:** 실제 코드 변경(`git diff`)을 태스크 명세와 한 줄씩
대조한다.

**4단계 — 통합 확인:** 선행 태스크와의 인터페이스가 맞는지 확인한다.

문제가 있으면 리뷰 결과를 피드백으로 Step 5를 재실행한다(재시도 규칙은
[실패 처리](#실패-처리) 참고). 두 번째도 실패하면 사용자에게 선택지를 제시한다.

문제가 없으면 다음 태스크로(Step 4-6 반복), 태스크가 모두 끝났으면 Step 7로.

Advisory diff 리뷰는 `fiftybox-execute`와 동일한 자연어 opt-in 트리거를
따른다(`~/.claude/skills/fiftybox-execute/scripts/diff_review.py` 재사용).

#### 실행 메트릭 기록

태스크가 이 리뷰 게이트를 통과하면 `<artifactDir>/gemma4-metrics.md`에 행을
append한다. 다음 태스크의 상한 판단과 calibration 근거는 이 표다.

| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 |
|---|---|---|---|---|---|
| Task A | 12 | 97 | 412s | 2 | success |

- **spec 줄수** — Step 3 태스크 명세의 실측 줄수
- **prompt 줄수** — `wc -l "<artifactDir>/implement-prompt.md"`(Step 5 dry-run에서
  이미 실측한 그 값)
- **duration** — `logs/phase-6-implement.log`의 `[DURATION]`
- **changedFiles** — `summary.json`의 `changedFiles` 개수
- **결과** — `success` / `retry` / `split` / `failed`

이 표를 누적해서 [`Gemma4 실행 예산`](#gemma4-실행-예산)의 Calibration 규칙
(최근 5태스크 성공률 < 80% → 하향, 10태스크 연속 100% → 상향)을 평가한다.
상한 조정은 표를 보여주고 사용자 승인한 뒤에 반영한다.

### Step 7: Review + Test (Phase 6)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase review-test --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" --skip-codex-review
```

첫 실패 시 실패한 태스크의 Step 5를 실패 출력과 함께 **1회 자동 재시도**한다.
3축은 고정값 그대로다 — 재시도에서 모델을 바꾸지 않는다.

### Step 8: Complete (Phase 7)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase complete --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

### Step 9: Deploy (Phase 7b)

[preflight](#맥스튜디오-서버-preflight) 후:

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase deploy --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>" \
  --implement-agent pi --provider macstudio-gemma4 \
  --model mlx-community--gemma-4-26B-A4B-it-qat-4bit --implementation-timeout 1800
```

### Step 10: Cleanup (Phase 8)

```bash
python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
  --phase cleanup --task "<작업>" --cwd "$(pwd)" \
  --artifact-dir "<artifactDir>"
```

`summary.json`의 최종 상태를 보고한다. **11234/11235번 mlx-serve는 임의로
끄지 않는다** — 각각 8bit·Gemma4의 상시 서버이며 다른 세션·레인이 사용 중일
수 있다. 두 포트는 독립 프로세스라 예전 oMLX처럼 함께 내려가지 않는다.
8000번 oMLX는 휴면이 정상 — 떠 있으면 사용자에게 알리기만 한다.

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
  내용, 속도, 모델 상태와 무관하다
- **executor는 `pi`/`macstudio-gemma4`/`mlx-community--gemma-4-26B-A4B-it-qat-4bit`로 고정이다.**
  어떤 실패·속도 문제도 모델이나 provider를 바꾸지 않는다. 유료 모델·원격
  무료 모델로 전환하지 않는다
- provider는 테스트 파일을 수정하지 않는다. 수정했으면 되돌리고 재실행한다
- `--dangerously-skip-permissions`는 orchestrate가 만든 격리된 워크트리 안에서만
  유효하다
- `--implement-agent`에는 에이전트 이름만, `--provider`에는 백엔드 이름만
  넣는다 — [Executor (고정)](#executor-고정) 표 참고
- **디스패치 앞에 매번 서버 preflight 헬스체크를 한다.** 11235번은 launchd
  관리 상시 서버다 — 이 스킬이 임의로 끄거나 재시작하지 않는다. 8000번
  oMLX(휴면 예정)가 떠 있으면 알리고 임의로 끄지 않는다
- `--phase implement`는 항상 detached로 돌리고 `EXIT_CODE=` sentinel을 남긴다
- `task-batches.md`에 ```json 태스크 블록을 넣지 않는다
- 실패 분류는 [실패 처리](#실패-처리) 표로만 한다
- **dry-run 길이 게이트(`PROMPT_MAX_LINES` 120줄)를 통과하지 않은 태스크는
  실디스패치하지 않는다.** 게이트를 건너뛴 디스패치는 위반이다
- **timeout 대응으로 timeout 값을 올리지 않는다.** `--implementation-timeout`은
  `1800` 고정이고, 허용되는 대응은 태스크 쪼개기뿐이다
- **executor용 `design.md`는 `DESIGN_MD_MAX_LINES(60)`줄 실행계약이고, 원문은
  `design-source.md`에 보존한다.** executor는 `design-source.md`를 읽지 않는다
