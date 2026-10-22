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
70/140으로 올렸다. Gemma4 레인은 원래 값(60/120)을 유지한다.

## benchmark-only: gemma4 레인

`fbl_task.py --executor gemma4`는 `macstudio-gemma4`(11235번, 키 없음)로 같은 루프를 돌린다. 스킬의
executor는 Flash-Next로 고정이라 **측정·비교 전용**이다(`WARN=`가 뜬다). Flash-Next가
꺼져 있어도 11235번이 떠 있으면 토큰 절감 효과를 재 볼 수 있어서 둔 옵션이다. 실사용 작업에 쓰지 않는다.
측정 도구는 `tests/bench/token_bench.py`.

## 레인 풀: ioh iq3_s

`fbl_task.py`의 레인 풀(`LANE_POOL`)은 맥스튜디오 Flash-Next와 ioh PC(Tailscale `100.126.254.22:8080`,
llama.cpp Strata, 키 없음)의 `qwen3.8-flash-next-iq3_s` 두 레인이다. Pi provider명은 `ioh`다. Flash-Next와
같은 모델 계열이라 예산(70/140)을 공유한다. 컨텍스트가 131,072로 스튜디오(262,144)보다 좁으니 긴
design/intent는 더 압축한다. 살아 있는 레인이 둘 이상이면 독립 태스크가 동시에 분배되고, 한쪽만 살아 있으면
그 레인으로 순차 실행이다. 한 저장소만 쓰려면 `run --lanes flash-next`로 제한한다.

- **생존 판정은 HTTP 응답뿐이다.** 모델 이름 확인을 하지 않는다. ioh가 RAG 때문에 q3s를 내리고 gemma4
  12b를 올리면 Tailscale이 응답하지 않게 돼 있으므로 그 레인은 조용히 풀에서 빠진다.
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
