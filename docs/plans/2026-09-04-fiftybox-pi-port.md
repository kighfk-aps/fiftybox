# fiftybox-pi — Pi CLI 네이티브 오케스트레이션 하네스 구현 계획

> 작성: 2026-09-04 · scout(GLM-5.3-flash) → planner(GLM-5.3) → critic(Kimi-k3) 체인 결과
> 상태: 검토 완료, 미구현. Critic 판정: **ACCEPT WITH CHANGES**

## 목표

Pi CLI 안에서 한 번의 명령(`/skill:fiftybox-pi`)으로 explore → clarify → design → implement → review/test → commit/push 파이프라인을 구동하되:

- **설계·테스트 작성·리뷰**: top-tier 모델 (GLM 5.3 / Grok 4.6)
- **구현**: 무료·저가 모델 (OpenRouter free / NIM / Groq / Modal·Cerebras Qwen 27B)
- **Claude Code 의존성 제거**

---

## 1. 실현가능성 판정: 달성 가능 (제약 조건하에)

**가능 — 실제 파일 검증 완료:**
- `orchestrate.py`는 하네스 무관 상태 기계. `BUILTIN_AGENTS["pi"]`가 이미 `pi --print --provider {provider} --model {model} --no-session --no-context-files --append-system-prompt {prompt} {task}` 를 생성 → 엔진 수정 없이 재사용 가능
- 이 머신 `~/.pi/agent/models.json`에 필요한 프로바이더 전부 존재: `zai-coding`(glm-5.2/5.3/5.3-flash), `nvidia-nim`(gpt-oss-120b/kimi-k3/laguna-xs/minimax-m3, 전부 cost 0), `openrouter-free`, `modal-qwen38`, `turbofieldfare`, `cerebras`
- 병렬 디스패치: 기존 `nohup` detached + `.out` 폴링 패턴 이식 가능 + `examples/extensions/subagent/` 참조 구현 존재
- 리뷰 샌드박스 대체: `codex -s read-only` → `pi -p --no-session --tools read,grep,find,ls`

**제약:**
1. 오케스트레이터 두뇌 품질 = 세션 모델 종속 → top-tier 세션에서 실행 필수
2. `PI_MODEL_UNAVAILABLE_PATTERNS`는 설계 문서에만 존재, 코드에는 없음 → 신규 구현 필요
3. Pi bash tool 포그라운드 타임아웃 → detached 디스패치 유지 필수
4. 레인 드리프트: `deepseek-v4-flash` 등 기본값이 현재 models.json에 없음 → 모든 디스패치에 (agent, provider, model) 3튜플 명시
5. cerebras는 baseUrl 없는 미완성 상태 → 비활성 유지
6. Claude 전용 기능(5h watcher/auto-resume) 폐기

## 2. 아키텍처 결정

**선택: Pi skill(SKILL.md)이 오케스트레이션 두뇌, 에이전트 실행은 subprocess `pi -p --provider X --model Y` (기존 `orchestrate.py` 경유)**

```
Pi 인터랙티브 세션 (top-tier: glm-5.3 | grok-4.6)  ← /skill:fiftybox-pi "<task>"
 ├─ SKILL.md 지시대로 페이즈 구동 (판단·아티팩트·사용자 Q&A)
 ├─ bash: orchestrate.py --phase setup|review-test|complete|cleanup
 ├─ bash: nohup orchestrate.py --phase implement --implement-agent <agent> \
 │        --provider <provider> --model <model> (detached + .out 폴링)
 └─ git worktree + .omx/artifacts/orchestrate/<ts>/ 아티팩트 핸드오프 (기존 계약 승계)
```

**탈락 후보:**
- pi extension 단독(TS 전체 루프): 판단 페이즈를 코드로 옮기면 SDK 재작성, clarify가 부자연스러움. → Stage 4에서 디스패치 계층만 extension tool로 래핑하는 하이브리드로 채택
- SDK 외부 드라이버(`createAgentSession` + `runRpcMode`): Phase 2 사용자 대화 불가, "한 명령 inside Pi CLI" 요구와 어긋남. CI 배치 확장(선택)으로만 유보

## 3. 페이즈별 모델 라우팅 테이블

| Phase | Tier | 1순위 | Fallback 체인 |
|---|---|---|---|
| 0 SETUP | — | orchestrate.py | hard gate |
| 1 EXPLORE | cheap/free | `openrouter-free` 탐색 모델 | `zai-coding/glm-5.3-flash` → `nvidia-nim/gpt-oss-120b` |
| 2 ROUTE+CLARIFY | **top(세션)** | 세션 = `zai-coding/glm-5.3` | `xai-auth/grok-4.6` |
| 3 DESIGN | **top(세션)** | 세션 모델 | `xai-auth/grok-4.6` |
| 4 VERIFY-DESIGN (opt-in) | top(교차) | `xai-auth/grok-4.6` | `zai-coding/glm-5.2` (advisory) |
| 4.5 WRITE TESTS (Red) | **top(세션)** | 세션 모델 | — |
| 5 IMPLEMENT (Green) | **free 전용** | `openrouter-free` (매 실행 탐색, 분산) | `nvidia-nim`(gpt-oss-120b→kimi-k3→laguna-xs→minimax-m3) → `groq`(신규) → `modal-qwen38/qwen3.8-27b`(piqwen, timeout 1800) → `turbofieldfare`(최후, 병렬도 1). **절대 유료 폴백 금지** |
| 5.5 REVIEW GATE | **top(세션)** | 세션 모델 | — |
| 6 REVIEW+TEST | objective | `--phase review-test --skip-codex-review` (LLM 없음) | 실패 시 Phase 5 1회 자동 재시도 |
| 6a diff 리뷰 (opt-in) | **top** | `pi -p --tools read,grep,find,ls` @ glm-5.3 | grok-4.6 → 세션 직접 (exit 2–6 계약, advisory) |
| 7/7b/8 | — | orchestrate.py (commit→merge→push / deploy / cleanup) | hard gate |

실패 분류: `auth`/`window`/`credit` = 레인 폐쇄·모델 교체 금지·배치 중단 / `model`/`model_busy` = 레인 내 교체(재시도 예산 불산입) / `timeout`/`no_changes`/`unknown` = 태스크 국소 / `orchestrate` = 정지

## 4. 파일 레이아웃

```
fiftybox/
├── skills/fiftybox-pi/
│   ├── SKILL.md                     # 전체 파이프라인 절차 (orchestration SKILL.md의 Pi 세션 개역판)
│   ├── scripts/
│   │   ├── pi_runner.py             # [S2] pi --mode json 실행기·실패 분류
│   │   ├── diff_review_pi.py        # [S3] read-only advisory 리뷰 (exit 2–6 계약 유지)
│   │   ├── fiftybox_config.py       # 설정 로더/검증/기본값
│   │   └── config_tui.py            # [S4 선택] 설정 TUI 포팅
│   ├── references/                  # phase-contract / failure-classification / routing 문서
│   └── agents/                      # fbx-explorer / fbx-implementer / fbx-reviewer (.md)
├── install-pi.sh                    # ~/.pi/agent/ 배포 + 사전 점검
└── tests/                           # test_pi_skill_doc / test_pi_agent / test_pi_runner / test_diff_review_pi (.sh)
~/.pi/agent/fiftybox-config.json     # 런타임 설정 (신규)
```

MVP는 설치본 `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py`를 그대로 호출(Claude Code 바이너리 개입 없음). Stage 2에서 `--agent-config` 플래그 추가로 `~/.pi/agent/`로 완전 분리(~20줄 수정).

## 5. 설정 스키마 (`~/.pi/agent/fiftybox-config.json`)

- `session.preferred: ["zai-coding/glm-5.3", "xai-auth/grok-4.6"]`, `warnBelowTier: true`
- `explore.fallback: ["openrouter-free:auto", "zai-coding/glm-5.3-flash", "nvidia-nim/openai/gpt-oss-120b"]`
- `implement.lane_priority: ["openrouter-free", "nvidia-nim", "groq", "modal-qwen38", "turbofieldfare"]`
  - openrouter-free: 매 실행 `discover_openrouter_free.py` 실측 (cost==0 ∧ toolcall ∧ active, MIN_CONTEXT=131072, smoke 30s, 동시 ≤4)
  - modal-qwen38: agent `piqwen`, Keychain wake-up(t+75/120/150s), timeout 1800
  - turbofieldfare: 최후 폴백, 병렬도 1, 디스패치 전 사용자 확인
- `review: { model: glm-5.3, fallback: [grok-4.6], tools: "read,grep,find,ls" }`
- `providers.*`: enabled/models 토글 + `fallbackRules: { accountScope, modelScope, taskScope, neverPaidFallbackFromFree: true }`
- 레인 활성 판정: 설정 `enabled` ∧ `pi --list-models <provider>` 존재 ∧ API key/env 존재

## 6. 구현 단계 (critic 수정 반영)

| Stage | 내용 | 완료 기준 |
|---|---|---|
| **S0 — 선행 게이트 (1–2일, critic 격상)** | 환경 실측: 7개 provider `pi --list-models` 확인, GROQ_API_KEY·groq 무료 모델 확정, Pi bash 타임아웃 실측, **`pi --mode json` 오류 페이로드 표본 수집(종료코드×stdout/stderr×타임아웃 결정표)**, **tool-call smoke**(파일 읽기 강제) 매트릭스 | 전 provider 응답 + 종료판정 계약(결정표 + 판정식 pseudocode) 확정. 판정식 도출 불가 provider는 레인 제외를 명시적 결과로 |
| **S1 — MVP** | SKILL.md 완성(3튜플 명시, detached 디스패치, 세션 모델 사전 점검, auto-resume 삭제) | (i) fake provider 자식(`FIFTYBOX_CHILD_CMD_OVERRIDE`)으로 엔진 로직 검증 + (ii) 실제 NIM 1모델 E2E — 분리. (ii)는 nightly/수동 트리거 |
| **S2 — 구조화 러너** | `pi_runner.py`(JSONL 파싱·실패 분류·model-choice.json 감사), `--agent-config` 분리, `PI_MODEL_UNAVAILABLE_PATTERNS` 신규 구현 | fixture JSONL 3종 분류 단언 + 실측 가짜 모델/잘못된 키로 scope 판정 |
| **S3 — advisory diff 리뷰** | `diff_review_pi.py` (exit 2–6, APPROVED/REVISE/BLOCKED/UNKNOWN 유지) | fixture diff 2종 verdict·exit 코드 계약 |
| **S4 — 확장(선택)** | extension `fbx_dispatch` 툴(pi.exec + abort 전파, MAX_CONCURRENCY=4), `/fiftybox` 커맨드, 설정 TUI | 병렬 배치(태스크 3·모델 3) abort 시 전체 자식 종료 |

## 7. 테스트 전략

기존 `tests/*.sh` 패턴 재사용 (`set -euo pipefail`, pass/fail 헬퍼, importlib 모듈 로드, `--help` exit 코드 확인):
- `test_pi_agent.sh` — BUILTIN_AGENTS argv 단언 (test_cc_agent.sh 6단계 구조 복제)
- `test_pi_skill_doc.sh` — SKILL.md 필수 절 단언
- `test_pi_runner.sh` — JSONL fixture 기반 분류 단위 테스트(네트워크 무의존)
- `test_diff_review_pi.sh` — exit 2–6 계약
- E2E: toy git repo, 무료 레인 1개만 켠 최소 구성, **429 주입 시나리오 1종 포함(stub provider)**

## 8. 리스크 (critic 보강 반영)

| 리스크 | 완화 |
|---|---|
| 세션 모델 품질 의존 (GLM/grok의 지시 이행도) | SKILL.md 체크리스트+템플릿 경직화, 게이트는 객관 테스트 블로킹 |
| 무료 모델 tool-calling 붕괴 (단문 OK ≠ 멀티턴 tool 루프) | **S0 tool-call smoke 통과 모델만 implement 레인 편입** |
| `pi -p` 종료코드 의미론 미문서화 | **S0 종료판정 계약 확정 전 free 레인 투입 금지** |
| 컨텍스트 오버플로 (Qwen 163k 등) | 분류표에 `context_length_exceeded` 추가 → in-lane 큰 모델 스왑, 없으면 레인 폐기. 자식 프롬프트에 "파일 전체 읽기 금지" 가드 |
| 429 폭주·lane 전환 루프 | per-lane 재시도 상한, `summary.json.childCalls[]`(provider/model/시각/종료판정) 기록 |
| 무료 레인 변동성 (OR :free 목록·NIM 모델명) | 매 실행 실측 탐색, MIN_CONTEXT/toolcall 필터 |
| groq 미검증 / cerebras 미완성 / xai OAuth 만료 | preflight 통과 시에만 레인 활성 |
| 스킬 자동 로딩 불확실성 | `/skill:fiftybox-pi` 명시 호출 강제 (`disable-model-invocation: true` 검토) |
| 엔진 fork 이중 유지 (~/.claude 공유) | S2 `--agent-config` 조기 분리, diff 감시 경계 지금 결정 |
| 비용/한도 모니터링 | 범위 외 명시 — 수동 확인, 최소한 childCalls 기록 |

---

## Critic 종합 판정: ACCEPT WITH CHANGES

**Blocking issues (계획에 반영 완료):**
1. "smoke = OK 응답"은 구현 에이전트 적합성을 검증 못 함 → tool-call smoke 2단계로 강화
2. `pi -p` 실패 판정 계약이 문서 근거 없이 가정 → S0 완료 기준을 "종료판정 계약"으로 격상
3. timeout 정책이 컨텍스트 오버플로 미처리 → `context_length_exceeded` 분류 추가
4. M1(S1)이 너무 크고 검증 약함 → fake provider 엔진 검증과 실측 E2E 분리

**MVP 조정:** S1은 "고정 3모델 + 파이프라인 골격 + 종료판정 계약"으로 한정. 전체 설정 스키마·동적 lane 탐색·병렬은 S2 이후. S0이 사실상 핵심 — 반나절 추정은 낙관적, 1–2일 배정.

**긴급정지 조항 (SKILL.md 추가):** 무료 레인 전멸 + neverEscalateToPaid 충돌 시 단순 중단이 아니라 사용자 선택지(유료 승격 1회 승인 / 중단 / top-tier로 implement) 출력.

**Verdict: Proceed with changes — tool-call smoke와 종료판정 계약이 확정되기 전 어떤 free 레인도 implement에 투입하지 말 것.**
