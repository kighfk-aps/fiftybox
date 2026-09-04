# Failure Classification & Exit-Judgment Contract (fiftybox-pi)

> S0 실측 기반 (2026-09-04, pi 0.84.4). 모든 표본은 이 머신에서 `pi --mode json` 실행으로 수집한 실제 페이로드.

## 1. 종료판정 계약 (Exit-Judgment Contract)

**핵심 규칙: exit code는 신뢰할 수 없다. 판정은 반드시 JSONL 스트림 파싱으로 한다.**

실측: 모델 오류(400/410/429) 발생 시에도 `pi --mode json -p` 프로세스는 **exit 0**으로 종료된다.
오류는 stdout JSONL 스트림 내부의 assistant 메시지에만 기록된다.

### 판정식 (구현: `pi_runner.py`)

```
run = spawn(pi --mode json -p --no-session --no-context-files --provider P --model M "<task>")
      + wall-clock timeout (기본 900s; smoke는 120s) → 초과 시 SIGKILL → classify TIMEOUT

parse each JSONL line into event e:
  e.type == "message_end" and e.message.role == "assistant":
      if e.message.stopReason == "error":  errors.append(e.message.errorMessage)
      if e.message.stopReason == "stop":   final_text = concat(e.message.content[].type=="text")
      toolCall 블록 존재 여부 기록 (e.message.content[].type == "toolCall")
  e.type == "auto_retry_start":          retry_loops += 1
  e.type == "tool_execution_end":        tool_execs += 1
  e.type == "agent_settled":             settled = true

success    := settled AND len(errors)==0 AND final_text.strip() != ""
failed     := settled AND len(errors)>0          → classify(errors[-1])
timeout    := NOT settled AND process killed by runner timeout
broken     := NOT settled AND process exited      (비정상 종료; stderr 포함 보고)
```

### JSONL 이벤트 스키마 (실측)

| 이벤트 | 의미 | 러너 처리 |
|---|---|---|
| `message_end` (assistant, `stopReason:"error"`) | 모델/프로바이더 오류. `errorMessage`에 원문 | 분류기 입력 |
| `message_end` (assistant, `stopReason:"stop"`) | 정상 종료 텍스트 | 최종 답변 추출 |
| content 블록 `{"type":"toolCall","name":...,"arguments":...}` | 도구 호출 | tool-call smoke 판정에 사용 |
| `tool_execution_start` / `tool_execution_end` | 실제 도구 실행/결과 | 실행 횟수 집계 |
| `auto_retry_start` | pi 내부 재시도 루프 시작 | 관측 — 루프 탐지 지표 |
| `agent_settled` | 에이전트 완료 | 성공 필요조건 |
| `message_update` | 스트리밍 usage delta | 무시 (마지막 usage만 선택 캡처) |

### 표본: 오류 페이로드 (그대로 기록)

| 사례 | 호출 | errorMessage (실측) | exit | 분류 |
|---|---|---|---|---|
| 존재하지 않는 모델 | `zai-coding` + `nonexistent-model-xyz` | `400: {"code":"1214","message":"modelCode: does not exist"}` | 0 | `model` (레인 내 교체) |
| NIM 계정 단위 장애 | `nvidia-nim/openai/gpt-oss-120b` | `410 status code (no body)` | 0 | `auth` (레인 폐쇄 — bogus 키가 아니어도 동일 코드 재현) |
| 무료 모델 rate limit | `openrouter-free/gemma-4-31b-it:free` | `429: {"...}` ×10, `auto_retry_start` ×2 (100초 내 미완료) | (kill) | `model_busy` (레인 내 교체) |

stderr는 오류 판정에 사용하지 않는다. 단, pi 자체 경고(예: `Warning: Model "..." not found for provider "...". Using custom model id.`)는 보고서에 첨부한다.

## 2. 실패 분류표 (fiftybox-execute 표 승계 + S0 확장)

| 분류 | 패턴 (errorMessage, 대소문자 무시) | scope | 라우팅 동작 |
|---|---|---|---|
| auth | `401`, `403`, `invalid api key`, `unauthorized`, `authentication`, `410 status code` | 계정 | 레인 폐쇄, 모델 교체 금지, 배치 전체 중단 |
| window | `context length`, `maximum context`, `too many tokens`, `prompt is too long`, `window_exhausted` | 계정/모델 | 동일 레인 내 더 큰 컨텍스트 모델로 in-lane 스왑, 없으면 레인 폐기 |
| credit | `402`, `insufficient`, `quota`, `credit`, `billing` | 계정 | 레인 폐쇄 |
| model | `does not exist`, `not found`, `no endpoints`, `model_code`, `400` (그 외) | 모델 | 레인 내 폴백 순서대로 교체 (재시도 예산 불산입) |
| model_busy | `429`, `rate limit`, `busy`, `overloaded` | 모델 | 레인 내 교체 + 해당 모델 이번 실행 쿨다운 |
| timeout | (러너 타임아웃 kill) | 태스크 | 태스크 국소 재시도 1회 |
| no_changes | (성공 판정이나 worktree diff 없음) | 태스크 | 태스크 국소 — orchestrate.py 기존 처리 승계 |
| unknown | 그 외 | 태스크 | 태스크 국소 재시도 1회 |
| orchestrate | 러너/엔진 자체 버그 | 하네스 | 즉시 정지, 보고 |

**불변 규칙**: `auth`/`window`/`credit`에서는 절대 모델을 스왑하지 않는다. 무료 레인에서 유료로 절대 폴백하지 않는다 (`neverPaidFallbackFromFree`).

## 3. Tool-Call Smoke 매트릭스 (S0 실측)

방법: `pi --mode json -p --no-session --no-context-files --tools read --provider P --model M "<파일 첫 줄을 read tool로 읽어 출력>"` — `--no-context-files` 필수(컨텍스트 주입으로 툴 우회 방지). 판정: `settled` ∧ `toolCall` ≥1 ∧ 최종 텍스트 == 예상 첫 줄.

| 모델 | 결과 | 근거 |
|---|---|---|
| `zai-coding/glm-5.3-flash` | **PASS** (6s) | settled, toolCall 1회, 정답 `# fiftybox` |
| `openrouter-free/cohere/north-mini-code:free` | **PASS** (<90s) | settled, toolCall 4회, 정답 |
| `openrouter-free/google/gemma-4-31b-it:free` | FAIL | 429 ×10, auto_retry 루프, 미완료 (model_busy — 레인 내 교체 대상) |
| `nvidia-nim/openai/gpt-oss-120b` | FAIL | `410 status code (no body)` — 계정 단위 장애 (auth — 레인 폐쇄) |

> 매 실행마다 이 smoke를 레인 후보에 대해 재실행해 healthy 목록을 만든다 (S0 계약: smoke 미통과 모델은 implement 레인에 투입 금지).

## 4. Provider 실측 (2026-09-04, `pi --list-models`)

| Provider | 모델 (context) | 상태 |
|---|---|---|
| zai-coding | glm-5.2/5.3/5.3-flash (1M) | ✅ 사용 가능 |
| xai-auth | grok-4.3/4.5/4.5-latest/4.6/build-latest (500K), composer-2.5-fast | ⚠️ 카탈로그 정상, OAuth 만료 이력 있음 — 세션 전 preflight 요구 |
| nvidia-nim | minimax-m3 (131K), kimi-k3 (262K), gpt-oss-120b (131K), laguna-xs-2.1 (32.8K) | ⚠️ 410 장애 중 — preflight 통과 시에만 활성 |
| openrouter-free | `:free` 다수 (north-mini-code 256K, gemma-4 262K 등) | ✅ 매 실행 재탐색 필요 (429 변동성 실측됨) |
| modal-qwen38 | qwen3.8-27b-q4_k_m (163.8K) + modal-endpoint-qwen38/Qwen3.8-27B (128K) | ✅ 콜드스타트 wake-up 절차 유지 |
| turbofieldfare | gemma-4-26b-a4b-it (65.5K, max-out 4.1K) | ✅ 최후 폴백 전용 |
| cerebras | gemma-4-31b, gpt-oss-120b, qwen3.8-27b | ⚠️ 카탈로그 존재 — API 키 preflight 전까지 비활성 |
| groq | 카탈로그 없음 + `GROQ_API_KEY` 미설정 | ❌ 레인 비활성 (키 발급 시 재평가) |

pi 내부 재시도 정책(`settings.json`: maxRetries 8, provider timeoutMs 900000) 때문에 단발 호출이 수 분 걸릴 수 있음 → **러너는 반드시 자체 wall-clock 타임아웃 + SIGKILL을 적용**한다 (smoke 120s, implement 1800s 기본).
