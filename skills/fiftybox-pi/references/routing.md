# Routing: Tiers, Lanes, Fallback (fiftybox-pi)

> 라우팅의 단일 출처는 설정 (`fiftybox_config.py` — `$FIFTYBOX_PI_CONFIG` >
> `~/.pi/agent/fiftybox-config.json` > 내장 기본값). 이 문서는 규칙의 배경과
> 절차를 설명한다. 모델 가용성은 날마다 바뀐다 — 항상 설정+preflight가 이긴다.

## 페이즈 → 티어 매핑

| 페이즈 | 티어 | 기본 체인 (설정 기본값) |
|---|---|---|
| 세션 (설계/테스트/게이트) | top | `zai-coding/glm-5.3` → `xai-auth/grok-4.6` |
| 1 EXPLORE | cheap | `openrouter-free:auto` → `zai-coding/glm-5.3-flash` → `nvidia-nim/openai/gpt-oss-120b` |
| 5 IMPLEMENT | **free 전용** | 아래 레인 우선순위 |
| 4/6a 리뷰 (opt-in) | top (세션과 다른 계열 권장) | `zai-coding/glm-5.3` ↔ `xai-auth/grok-4.6` |

## Implement 레인 우선순위 (기본값)

| # | 레인 | 모델 순서 | 비고 |
|---|---|---|---|
| 1 | `openrouter-free` | 매 실행 탐색 (`discover_openrouter_free.py`: cost==0 ∧ toolcall ∧ context≥131072) | 429 변동성 큼 — healthy 목록만 사용, 태스크마다 다른 모델 분산 |
| 2 | `nvidia-nim` | gpt-oss-120b → kimi-k3 → laguna-xs-2.1 → minimax-m3 (설정 JSON 키 순서) | timeout 600s 기본; 2026-09-04 기준 410 장애 관측 — preflight 필수 |
| 3 | `groq` | (tool 지원 무료 모델 — Stage 0에서 미확정) | `GROQ_API_KEY` 없으면 레인 비활성 |
| 4 | `modal-qwen38` | qwen3.8-27b-q4_k_m (agent `piqwen`, `--thinking off`) | 콜드스타트 wake-up ping (t+75/120/150s), timeout 1800s |
| 5 | `turbofieldfare` | gemma-4-26b-a4b-it | 최후 폴백: 병렬도 1, 디스패치 전 사용자 확인, max-out 4.1K 주의 |

레인 활성 조건: 설정 `enabled` ∧ (API key/env 존재, 정의된 경우) ∧
(`pi --list-models <provider>` 카탈로그 존재) ∧ (tool-call smoke 통과).
cerebras는 카탈로그만 있고 키 미확인 — 기본 비활성.

## 불변 규칙

1. **neverPaidFallbackFromFree** — 무료 레인에서 유료로 자동 폴백 금지.
   유료는 Emergency Stop 승인 1회만 허용 (태스크 스코프, 설정 변경 아님).
2. **smoke 미통과 모델 투입 금지** — "단문 OK"는 불충분 (references/failure-classification.md §3).
3. **3튜플 명시** — 모든 디스패치에 (agent, provider, model)을 직접 전달.
   엔진 기본값(deepseek-v4-flash)은 소멸한 모델이다.
4. **분류 우선, 스왑은 분류 이후** — auth/window/credit은 스왑 없이 레인 폐쇄.
   model/model_busy만 레인 내 스왑. (§2 분류표)
5. **러너 타임아웃 상한** — pi 내부 재시도(maxRetries 8, provider timeout 900s)
   떄문에 단발 호출이 수 분 걸린다. smoke 120s / explore 900s / implement 1800s /
   review 900s (설정 `timeouts`).

## piqwen (Modal 레인) 에이전트

`orchestrate.py --agent-config` 디렉터리의 `config.json`에 등록:

```json
{
  "explore_agent": "pi",
  "implement_agent": "pi",
  "agents": {
    "piqwen": {"cmd": ["pi", "--print", "--provider", "modal-qwen38",
                       "--model", "qwen3.8-27b-q4_k_m", "--thinking", "off",
                       "--no-session", "--no-context-files",
                       "--append-system-prompt", "{prompt}", "{task}"]}
  }
}
```

install-pi.sh가 이 디렉터리(`~/.pi/agent/fiftybox-pi-agents/`)를 생성한다.
공유 `~/.claude/skills/orchestrate/config.json`은 읽기 전용으로만 사용한다.
