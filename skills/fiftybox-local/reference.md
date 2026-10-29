# fiftybox-local reference

SKILL.md는 오케스트레이터가 매 턴 다시 읽는다. 아래는 **실패했을 때나 상수를 조정할 때만**
필요한 내용이라 따로 뺐다. 평소에는 읽지 않는다.

## 서버 점검·기동 (preflight가 `down`/`auth`일 때)

`fbl_task.py preflight`는 헬스체크가 200이 아니면 SSH로 LISTEN 포트를 `LANES=`로 알려 준다. 수동 확인은
`ssh tanpapa@100.115.199.115 'source ~/.zprofile 2>/dev/null; lsof -nP -iTCP:8000 -iTCP:11234 -iTCP:11235 -sTCP:LISTEN'`.

- `HEALTH=401` → 서버는 살아 있으나 키가 어긋났다. 키파일
  `~/.config/opencode/macstudio-omlx.key`와 스튜디오 `~/.omlx/settings.json`의
  `auth.api_key`를 비교한다. 중단하고 보고한다 — 임의로 키를 재발급하지 않는다.
- `LANES=ssh_failed` → 스튜디오가 꺼졌거나 오프라인. 서버 기동도 SSH가 필요하므로 중단하고 보고한다.
- `LANES=none`/8000 없음 → 8000번이 죽어 있다. 11234(8bit)·11235(Gemma4)가 같이 떠 있으면
  Flash-Next(상주 약 75GB)와 합쳐 128GB를 넘기므로 **사용자에게 알리고 어느 쪽을 내릴지 묻는다.**
  임의로 끄지 않는다.

기동(8000번이 죽어 있고 경합이 없을 때만):

```bash
ssh -o BatchMode=yes tanpapa@100.115.199.115 'source ~/.zprofile 2>/dev/null; omlx start'
```

`omlx start`는 `~/.omlx/settings.json`의 host/port를 따른다. PATH에 `omlx`가 없으면
`brew services start omlx`. 수동 `omlx serve` 포그라운드는 쓰지 않는다 — API 키가 비어 있으면
확인 프롬프트에 응답자가 없어 "Startup canceled"로 조용히 죽는다. 로그 확인:
`ssh tanpapa@100.115.199.115 'source ~/.zprofile 2>/dev/null; omlx status'`.

기동 후 30초 간격 최대 16회(8분)로 `python3 $FBL preflight`를 반복한다. PLE n-gram 표를 SSD mmap으로
읽어 콜드 부팅에 수 분 걸린다. 8분 안에 `PREFLIGHT=ok`가 아니면 디스패치하지 않고 `server`로
보고한다. 모델 교체를 제안하지 않는다. 이 스킬이 서버를 새로 띄웠다면 보고에 적는다.

웜업(첫 생성 경로 확인)은 `preflight`가 실행당 1회 자동으로 한다(`A/.fbl/warmed`).

### memory guard tier

`~/.omlx/settings.json`의 `memory.memory_guard_tier`는 **aggressive**로 고정한다(2026-10-16).
`safe`였을 때 Gemma4(11235번)가 idle로 떠 있기만 해도 동적 ceiling이 77.5GB까지 내려가 109K 토큰
prefill이 400으로 거부됐다(10/15 로그). aggressive는 다른 프로세스 메모리의 절반을 macOS 압축기로
돌릴 수 있다고 보고 예약을 16GB→4GB로 줄여 ceiling을 ~108GB로 유지한다 — 램에 실제 여유가 있으면
작업이 시작된다. hard watermark 도달 시 요청 중단·모델 퇴출은 tier와 무관하게 일어나므로
동시 구동은 여전히 경합이다. tier를 되돌리려면 사용자 승인이 필요하다.

## 실패 분류 근거

`fbl_task.py`의 `classify_failure`가 `A/implement-task-N.out`(마지막 줄 `EXIT_CODE=`)로 분류한다.

| 신호 | CLASS |
|---|---|
| `Connection refused`, `Failed to connect`, 요청 중 EOF·502 | `server` |
| `LANE_HEALTH_LOST`(헬스 와치독) | `server` |
| `Unknown model`, 404/410, 모델 ID 거부 | `model` |
| `EXIT_CODE=124` | `timeout` |
| 응답이 `finish_reason: length`로 잘림 | `too_long` |
| `EXIT_CODE=3`, 태스크가 예산 초과 | `too_long` |
| `EXIT_CODE=3`, 예산 이내 | `no_changes` |
| `EXIT_CODE=1` + `not in the agents list`/`unrecognized arguments` | `orchestrate` |
| 그 외 | `unknown` |

`run`은 디스패치 **전에** 예산을 검사하므로(`STOP=BUDGET`/`GATE`) 디스패치된 태스크의
`EXIT_CODE=3`은 대개 `no_changes`다.

## Calibration

`A/executor-metrics.md`에 태스크마다 `task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 | lane`
행이 쌓인다(결과: `success`/`retry`/`flagged`/`failed`/`moved`). `fbl_task.py calibrate --repo R`가 저장소의
**모든** 실행 기록을 모아 **레인별로** 계산한다(옛 6열 행은 `flash-next`로 본다). `moved` 행은 인프라 이동이지
모델 실패가 아니므로 제외한다. 상수 조정은 여전히 사용자 승인 후에만.

- 레인별 최근 5태스크 성공률 < 80% → `ADVICE=DOWN`: design 70→60(또는 60→45), prompt 140→120(또는 120→100).
- 레인별 10태스크 연속 성공 → `ADVICE=UP`: design +10, prompt +20.
- 조정은 누적 행을 사용자에게 보여주고 **승인 후** `fbl_task.py` 상단의 `EXECUTORS` 값과
  SKILL.md 예산 표를 함께 고친다. 임의로 바꾸지 않는다.

이력: 60/120은 Gemma4 실측에서 온 값이었다. 2026-10-08 trendwatch 실험에서 Flash-Next가 40태스크를
모두 첫 시도에 통과해(`docs/reviews/2026-10-08-fiftybox-local-vs-sonnet-trendwatch.md`) 위 규칙대로
70/140으로 올렸다. Flash-Next 계열이 아닌 후보는 원래 값(60/120)으로 시작한다.

## 후보 표

후보는 `fbl_task.py`의 `EXECUTORS`에 있는 아홉 개뿐이다(표 순서가 `params_b` 동점 규칙). 세 조건을 모두 만족해야
후보다: 표에 있고, Pi `~/.pi/agent/models.json`에 provider·model이 등록돼 있고, `~/.claude/fiftybox-config.json`에서
꺼져 있지 않다(항목이 없으면 켜짐). 같은 PC의 후보끼리는 한 번에 하나만 레인이 된다.

| 이름 | PC | provider / model | 포트 | 키 | 예산 | params_b |
|---|---|---|---|---|---|---|
| `flash-next` | Studio | `macstudio-qwen-flash-next` / `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp` | 8000 | 필요 | 70/140 | 125 |
| `qwen27b-mlx4` | Studio | `macstudio-qwen-flash-next` / `lmstudio-community--Qwen3.8-27B-MLX-4bit` | 8000 | 필요 | 60/120 | 27 |
| `qwen27b-8bit` | Studio | `macstudio-qwen38-27b` / `qwen38-27b-8bit` | 11234 | 없음 | 60/120 | 27 |
| `gemma4` | Studio | `macstudio-gemma4` / `mlx-community--gemma-4-26B-A4B-it-qat-4bit` | 11235 | 없음 | 60/120 | 26 |
| `gpt-oss-20b` | Studio | `macstudio-darkbloom` / `gpt-oss-20b` | 8001 | 없음 | 60/120 | 20 |
| `qwen35b-a3b` | Studio | `macstudio-darkbloom` / `qwen3.5-35b-a3b` | 8001 | 없음 | 60/120 | 35 |
| `iq3s` | ioh (R9700) | `ioh` / `qwen3.8-flash-next-iq3_s` | 8080 | 없음 | 70/140 | 125 |
| `gemma31b` | ioh (R9700) | `ioh-gemma31b` / `gemma-4-31b-it` | 8083 | 없음 | 60/120 | 31 |
| `qwen27b` | ioh (R9700) | `ioh-qwen27b` / `qwen3.8-27b` | 8084 | 없음 | 60/120 | 27 |

- **선택 규칙:** 맥스튜디오는 `GET /v1/models`가 200이고 `data[].id`에 후보의 model ID가 있어야 «서빙 중»이다(8000번 한
  포트에서 모델이 바뀐다). ioh는 HTTP 200만 본다(포트 하나에 모델 하나). 한 PC에서 둘 이상이 서빙 중이면 `params_b`가
  큰 쪽, 같으면 표 순서다. `flash-next`는 모델 카드 기준 125B(활성 6B)다. 11234·8001번은 키 없음으로 두었다 — 서버가
  떠 있을 때 401이면 `needs_key`를 True로 바꾼다.
- **ioh는 R9700 포트만 후보다.** 8080번(Strata 중계)·8083·8084번이 R9700에서 돈다. 8081번(RTX 5060 Ti)은 RAG용
  Gemma-4-12b라 표에도 Pi에도 없고 레인이 될 수 없다.
- **Pi에 등록되지 않은 모델은 서빙 중이어도 후보가 아니다.** 예: 스튜디오 디스크의
  `umixer--Qwen3.8-Flash-Next-oQ4e-mix6-mtp`(117GB). 쓰려면 Pi `models.json`에 한 줄, `EXECUTORS`에 한 줄을 더한다.
- **프리플라이트 출력:** `SKIP=<이름> REASON=not-in-pi|off-in-config`(후보에서 빠진 이유),
  `LANE=<이름> HEALTH=<코드> SERVED=yes|no`(`no`는 서버는 떴지만 후보 모델 ID가 목록에 없음),
  `PICK=studio:<이름>,ioh:<이름>`, `WARN=pi registry unreadable ...`(등록 확인을 건너뜀). 후보가 0개면
  `PREFLIGHT=none`이고 `run`은 `STOP=NO_CANDIDATES`다.
- **실행 중에 모델이 바뀌면** 그 레인은 죽은 것으로 본다. `Unknown model`로 거부됐고 헬스가 더는 200이 아니면
  `server`로 다시 분류해(모델 실패가 아님) 태스크를 한 번 다른 레인으로 옮긴다(`MOVED=`).
- **스튜디오 백엔드:** Pi `models.json`의 `macstudio-qwen-flash-next` → `http://100.115.199.115:8000/v1`
  (oMLX, brew 서비스). max tokens 16,384. 11234번(Qwen3.8-27B 8bit)·11235번(Gemma4)은 별도 프로세스이고,
  Flash-Next는 상주 약 75GB라 동시 구동하면 메모리를 경합한다 — oMLX memory guard는 `aggressive` tier(다른
  레인 메모리 절반을 압축기로 동원, `~/.omlx/settings.json`)라 Gemma4가 idle로 떠 있어도 램 여유가 있으면
  작업이 시작된다. tier를 임의로 되돌리지 않는다. 어떤 포트도 임의로 끄지 않는다.
- 토큰 절감 측정 도구는 `tests/bench/token_bench.py`(`--executor gemma4|flash-next`로 한 후보만 지정해 돌린다).

## 레인 풀: ioh (R9700)

ioh PC(Tailscale `100.76.6.16`, llama.cpp, 키 없음)에서 R9700이 서빙하는 모델이 ioh 레인이다: `iq3s`(8080번 Strata
중계, Flash-Next 계열이라 예산 70/140, 컨텍스트 262,144), `gemma31b`(8083번), `qwen27b`(8084번). R9700은 VRAM 32GB라
한 번에 모델 하나가 올라간다. 살아 있는 레인이 둘(PC 둘)이면 독립 태스크가 동시에 분배되고, 한쪽만 살아 있으면
그 레인으로 순차 실행이다. 한 후보만 쓰려면 `run --lanes flash-next`처럼 후보 이름으로 제한한다.

- **생존 판정은 HTTP 응답뿐이다(ioh).** 모델 ID는 보지 않는다. ioh가 RAG 때문에 R9700의 모델을 바꾸면 내려간
  포트는 응답하지 않아 조용히 풀에서 빠지고, 새로 올라온 모델의 포트가 응답하면 그쪽이 레인이 된다.
- **이 스킬은 ioh 서버를 기동·종료하지 않는다.** RAG가 쓰는 중이라 방해하지 않는다. 스튜디오 기동 절차만
  아래(«서버 점검·기동») 그대로 유지된다. 스튜디오가 죽어 있고 ioh만 살아 있으면 ioh로 진행한다.
- **와치독:** 디스패치 중 60초 간격 헬스체크로 3회 연속 실패하면 프로세스 그룹을 죽이고 로그에
  `LANE_HEALTH_LOST`를 남긴다(`classify_failure`가 `server`로 본다). 그 태스크는 다른 레인으로 이동한다.
- **레인 워크트리:** 실행 중 각 레인이 `<repo>/.worktrees/fbl-<A>-<lane>`에서 돌고, `run`이 끝나면 지워진다.
  남은 게 있으면 `git worktree remove --force <path>`로 정리한다.
- **이동(`MOVED=`)과 재시도는 다르다.** 서버 문제 이동은 재시도 예산(태스크당 1회)을 쓰지 않고 이동도
  태스크당 1회다. 재시도는 메인 워크트리 재동기화 + 마지막 시도의 소유 파일 오버레이에서 시작한다.

## 근거 실측

- trendwatch 40태스크: 로컬 $0·첫 시도 40/40, Sonnet 5.5 구현자 $4.86. 오케스트레이터 비용은 비교에서 빠졌다.
  세션 로그를 다시 재면 오케스트레이터가 API를 305번 불렀고 호출당 평균 27만 토큰을 다시 읽었다.
- blog-pipeline 7태스크: fiftybox-local Claude 약 $3.6(Opus 60회, 평균 17만) vs Sonnet 약 $0.4~0.5.
  비용 대부분이 구현이 아니라 **오케스트레이션**(큰 세션 반복 읽기).
- 개선 후 측정(2026-10-11, 장난감 4태스크, gemma4, 오케스트레이터 Sonnet 5.5): 개선 전 흐름 $0.26·20턴 →
  개선 후 $0.07·5턴, Sonnet 직접 구현 $0.08·17턴. 자세한 한계는 `docs/reviews/2026-10-11-fiftybox-local-token-bench.md`.
- 알림 경로 vs `wait` 경로(같은 장난감 4태스크, 완료된 2쌍): 비용 $0.066 vs $0.069, 턴 6.0 vs 5.5, 토큰 82K vs 76K로
  차이가 없다. 백그라운드 알림은 출력이 아니라 요약+파일 경로만 주므로 "대기 문장" 턴과 "출력 읽기" 턴이 더 들고,
  블로킹 `wait`는 기다리는 동안 API 호출이 없고 결과를 바로 돌려준다. 어느 쪽이 싸다고 단정하지 않는다.
- 두 실험에서 걸린 구현 결함: Sonnet이 pytest를 못 찾고 테스트를 안 돌림(T3~T6) → `Run:` 줄을 태스크에
  자동 추가, Red가 구현 전에 통과(T4) → `RED_ALREADY_PASSES`, 로컬 모델의 범위 밖 수정·페르시아어 혼입 →
  `SCOPE`/`SCRIPT` 검사.
