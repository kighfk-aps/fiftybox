# fiftybox-local 서빙 중인 모델 레인 설계

날짜: 2026-10-29
상태: 승인됨 (2026-10-29)

## 목적

`fiftybox-local`이 두 PC(맥스튜디오, ioh)에서 **지금 실제로 서빙 중인 모델**로 구현하게 한다.

지금은 레인 표(`LANE_POOL = ("flash-next", "iq3s")`)에 적힌 모델 둘만 쓴다. 그런데 두 PC가 서빙하는 모델은 그때그때 달라진다. 2026-10-29에 실제로 이랬다.

- 맥스튜디오 8000번: `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp` 서빙 중 (레인 표에 있음).
- ioh 8080번(`iq3s`): 응답 없음. R9700이 다른 모델로 차 있다.
- ioh 8083번: `gemma-4-31b-it` 서빙 중 (R9700, 레인 표에 없음).

결과: 스킬이 ioh의 Gemma-4-31B를 못 쓰고 맥스튜디오 한 대로만 돈다. 레인 표에 한 줄을 더해도 모델이 또 바뀌면 같은 일이 반복된다.

## 현재 구조 (바뀌는 이유)

- `fbl_task.py`의 `EXECUTORS` 표에 모델이 하드코딩돼 있다(`flash-next`, `gemma4`, `iq3s`). `LANE_POOL`이 그중 풀에 들어갈 둘을 고정한다.
- 레인 생존 판정은 `GET /v1/models`의 HTTP 상태 코드뿐이다. 서버가 어떤 모델을 서빙하는지는 보지 않는다.
- 레인 이름(`flash-next`, `iq3s`)이 레인 worktree 경로(`fbl-<A>-<lane>`), `A/lanes/<lane>/`, `state.json`, `executor-metrics.md`, `calibrate`의 키로 쓰인다.
- 풀 모드는 레인당 동시 태스크 하나, 독립 태스크 병렬, 서버 사망 시 다른 레인으로 이동(`MOVED=`)이다. 이 동작은 바뀌지 않는다.
- `SKILL.md`의 설정 게이트는 Flash-Next가 꺼져 있으면 시작 자체를 중단한다.

## 목표

1. 시작할 때(`preflight`와 `run`) 각 PC에서 지금 서빙 중인 후보 모델을 찾고, PC마다 하나를 레인으로 쓴다.
2. 후보는 아래 «후보 표»에 있는 모델이다. 표 밖 모델은 쓰지 않는다.
3. ioh는 **R9700에서 서빙하는 모델만** 쓴다.
4. 맥스튜디오에서 후보가 둘 이상 응답하면 **파라미터가 큰 모델**을 쓴다.
5. 결과 줄·메트릭·`calibrate`는 지금처럼 모델(레인)별이다.
6. 한 PC만 살아 있으면 순차 실행, 둘 다 살아 있으면 독립 태스크 병렬 실행이다. 지금과 같다.

## 비목표

- 서버를 올리거나 내리지 않는다. 모델을 바꾸지 않는다. ioh는 건드리지 않고, 맥스튜디오의 기존 기동 절차(`reference.md`)는 그대로다.
- ioh의 RTX 5060 Ti는 쓰지 않는다. 거기서 도는 Gemma-4-12b(8081번)는 RAG용이다.
- 클라우드 모델(openrouter, opencode-go, openai-codex 등 Pi가 고를 수 있는 나머지)은 쓰지 않는다. 쓰는 것은 두 PC가 서빙하는 모델뿐이다.
- 실행 중에 레인 모델이 바뀌는 것을 다시 찾지 않는다. 도중에 바뀌면 그 레인은 죽은 것으로 보고, 기존 이동 규칙(`MOVED=`)을 따른다.
- Pi `~/.pi/agent/models.json`을 자동으로 고치지 않는다. 등록되지 않은 모델은 후보가 아니다.
- Flash-Next 계열의 실행 예산(70/15/2/14/140)은 바꾸지 않는다.
- 오케스트레이터가 구현 파일을 직접 쓰지 않는다는 금지는 그대로다.

## 반대 목표

다음은 동작하면 실패다.

- RTX 5060 Ti(8081번)나 RAG가 쓰는 자원에 구현 요청을 보낸다.
- 서버가 서빙하지 않는 모델 ID로 요청을 보낸다(`model` 실패).
- 한 PC에서 태스크 둘을 동시에 돌린다.
- `--provider`를 빠뜨려 기본값 `opencode-go`로 조용히 나간다(클라우드로 새는 것).
- Flash-Next가 아닌 모델에 Flash-Next 예산(70/140)을 그대로 준다.
- 서버를 임의로 켜거나 끈다.

## 사용자가 정한 것

- 두 PC에서 그때그때 서빙 중인 모델로 구현한다.
- ioh는 R9700에서 서빙하는 모델만 구현에 쓴다. (ioh에는 GPU가 둘이다.)
- 맥스튜디오에서 모델 둘 이상이 동시에 떠 있는 일은 없다고 본다. 있으면 파라미터가 큰 모델을 고른다.

## 제 판단으로 정한 것 (읽으면서 확인해 주세요)

- **레인은 PC 한 대에 하나다. 이름은 후보 이름 그대로 쓴다.** 이름은 지금처럼 `flash-next`, `iq3s`, `gemma4`에 새 후보 이름을 더한다. 그래서 worktree 경로, `state.json`, 메트릭, `calibrate`가 그대로 동작한다. 같은 PC에서 모델이 바뀌면 이름이 바뀌고 `calibrate`는 모델별로 따로 센다.
- **후보 표(제가 읽은 현재 값).** 표는 `fbl_task.py` 맨 위 한 곳에 둔다.

  | PC | Pi provider / model | 포트 | 비고 |
  |---|---|---|---|
  | Studio | `macstudio-qwen-flash-next` / `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp` | 8000 | 디스크 99GB로 가장 크다 |
  | Studio | `macstudio-qwen-flash-next` / `lmstudio-community--Qwen3.8-27B-MLX-4bit` | 8000 | |
  | Studio | `macstudio-qwen38-27b` / `qwen38-27b-8bit` | 11234 | |
  | Studio | `macstudio-gemma4` / `mlx-community--gemma-4-26B-A4B-it-qat-4bit` | 11235 | |
  | Studio | `macstudio-darkbloom` / `gpt-oss-20b`, `qwen3.5-35b-a3b` | 8001 | |
  | ioh (R9700) | `ioh` / `qwen3.8-flash-next-iq3_s` | 8080 | Strata 중계. R9700(HIP판)에서 돈다(`~/Desktop/ioh-control/AGENTS.md`, 2026-10-28 재설치 기준) |
  | ioh (R9700) | `ioh-gemma31b` / `gemma-4-31b-it` | 8083 | Pi 모델 이름에 «R9700 llama.cpp» |
  | ioh (R9700) | `ioh-qwen27b` / `qwen3.8-27b` | 8084 | Pi 모델 이름에 «R9700 llama.cpp» |

  ioh 8081번(5060 Ti)은 표에 없고 Pi에도 등록돼 있지 않다.
- **후보인 조건 세 가지.** (1) 표에 있다. (2) Pi `models.json`에 provider와 model이 등록돼 있다. (3) `~/.claude/fiftybox-config.json`에서 꺼져 있지 않다(항목이 없으면 켜짐으로 본다). 하나라도 어긋나면 그 후보는 조용히 빠지고, 이유를 `preflight` 출력에 한 줄 남긴다.
- **생존 판정: 맥스튜디오는 모델 ID까지 본다. ioh는 HTTP 200만 본다.** 맥스튜디오는 `GET /v1/models`가 200이고 응답의 `data[].id`에 후보의 model ID가 있어야 «서빙 중»이다. 8000번 한 포트에서 모델이 바뀔 수 있어서 상태 코드만으로는 부족하기 때문이다. ioh는 포트 하나에 모델 하나라서 200이면 «서빙 중»이다(이전 설계와 같다). Strata(8080번)가 `/v1/models`에 어떤 ID를 내는지 기록이 없어, ID 확인을 강제하면 멀쩡한 `iq3s`가 빠질 수 있다. 빌더가 ioh 서버가 떠 있을 때 응답을 한 번 확인해서, ID가 후보와 같으면 ioh에도 ID 확인을 넣어도 된다.
- **PC마다 후보를 고르는 규칙.** 그 PC에서 «서빙 중»인 후보가 둘 이상이면 `params_b`(총 파라미터, 십억 단위)가 큰 쪽이다. 같으면 표 순서다. `params_b`는 표에 직접 적는다(oMLX는 파라미터 수를 알려 주지 않는다). Flash-Next는 다른 Studio 후보보다 크다. 나머지는 모델 이름의 숫자(27, 26, 20, 35 등)를 쓰고, 이름에 없는 값은 빌더가 모델 카드에서 확인한다. 값을 모르는 후보는 가장 작은 것으로 본다.
- **두 PC가 다 한가하고 준비된 태스크가 하나뿐이면 맥스튜디오가 가져간다.** 지금과 같은 규칙이다.
- **예산은 모델별이다.** Flash-Next 계열(맥스튜디오 Flash-Next, ioh `iq3s`)은 지금처럼 70/140이다. 그 밖의 후보는 Gemma4 실측 값 60/120으로 시작한다. 값은 표에 후보마다 적고, 조정은 기존처럼 `calibrate`를 보고 사용자 승인 뒤에만 한다.
- **`--lanes`는 후보 이름을 받는다.** 지금처럼 쓰는 레인을 제한한다. `--executor`는 한 후보만 쓰는 순차 경로로 남는다. «벤치마크 전용» 표시(gemma4 경고)는 문서와 경고 문구에서 뺀다.
- **설정 게이트가 «중단»에서 «제외»로 바뀐다.** 꺼진 후보는 풀에서 빠지고, 후보가 하나도 남지 않을 때만 중단하고 `/fiftybox-config`를 안내한다.
- **문서와 테스트.** `SKILL.md`(description, 레인 풀 표, 설정 게이트, 실패 처리, 안전 계약), `reference.md`(레인 풀 절, gemma4 «benchmark-only» 절), `tests/test_fbl_task.py`, `tests/test_local_skill_doc.sh`를 새 동작에 맞춘다. 낡은 문구 «표 밖 모델 금지»는 «후보 표 밖 모델 금지»로 좁힌다. 클라우드 전환 금지는 그대로다. 실행용 사본 `~/.claude/skills/fiftybox-local`을 repo 사본과 맞춘다.
- **작업 트리가 지금 깨끗하지 않다.** `skills/fiftybox-local/` 아래 4개 파일과 테스트 2개에 커밋 안 된 수정이 있다(ioh 컨텍스트 값 정정으로 보인다). 빌더는 그 수정 위에서 작업하고 되돌리지 않는다.

## 빌더에게 맡기는 것

- 후보 표의 자료 구조(`Executor`에 필드를 더할지, 별도 표를 둘지).
- Pi `models.json`과 설정 파일을 읽는 방법, 읽기 실패 때의 처리.
- 모델 ID 확인과 PC별 선택을 넣는 위치(`live_lanes`, `select_mode`, `_preflight_pool`).
- `probe_lanes()`의 SSH 점검 포트 목록 갱신.
- 가짜 서버로 맥스튜디오·ioh 응답을 재현하는 테스트 방법.
- 새 후보의 레인 이름 짓기, `params_b` 중 모를 값 채우기.

## 성공 기준

- 2026-10-29 상태(맥스튜디오 Flash-Next 서빙, ioh 8080 응답 없음, ioh 8083 Gemma-4-31B 서빙)에서 `preflight`가 두 레인(`flash-next`, Gemma-31B 레인)을 올리고 `PREFLIGHT=ok`를 낸다. 독립 태스크가 두 곳에서 동시에 돈다.
- R9700이 `qwen3.8-27b`(8084번)로 바뀌면 ioh 레인이 그 모델로 바뀐다. 코드 수정은 필요 없다.
- 맥스튜디오에서 후보 둘이 응답하면 `params_b`가 큰 쪽만 레인이 된다.
- 8081번(5060 Ti)이 응답해도 레인이 되지 않는다. 표에 없는 모델은 후보가 되지 않는다.
- 맥스튜디오에서 서버는 200인데 후보의 model ID가 `data[].id`에 없으면 그 후보는 «서빙 중»이 아니다.
- Pi에 등록되지 않은 모델은 서빙 중이어도 후보가 아니다. 예: 맥스튜디오 디스크에 `umixer--Qwen3.8-Flash-Next-oQ4e-mix6-mtp`(117GB)가 있지만 Pi에는 없다. 쓰려면 Pi에 한 줄, 후보 표에 한 줄을 더한다.
- 설정에서 꺼진 후보는 풀에서 빠진다. 후보가 하나도 없으면 `STOP`과 안내가 나온다.
- Flash-Next가 아닌 레인은 60/120 예산을 쓰고, 예산 위반이 디스패치 전에 `STOP=BUDGET`으로 걸린다.
- 모든 디스패치에 `--provider`와 `--model`이 후보의 값으로 명시된다.
- 기존 단일 레인·풀·이동 동작과 테스트가 새 표 기준으로 모두 통과한다.
