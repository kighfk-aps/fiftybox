# Local Model Config 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 맥미니 로컬 모델 설정(탐색 9B, 구현 27B/35B A3B)을 공개 GitHub에서 격리하고, explore phase를 Gemma4에서 Qwen3.5 9B(Ollama)로 교체한다.

**Architecture:** `.gitignore` 패턴 보완으로 평면 `.md` 파일 누락을 막고, `select_remote_model.sh`·`stop_remote_model.sh`에 `9b` 케이스를 추가해 Ollama(port 11434)를 컨테이너 시작 없이 사용한다. `SKILL.md`는 `gemma4` 별칭을 `9b`로 교체하는 것이 전부다.

**Tech Stack:** bash, git, Ollama API (`http://100.121.45.122:11434/v1`)

---

## 파일 맵

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `.gitignore` | 수정 | `skills/fiftybox-local*.md` 1줄 추가 |
| `skills/fiftybox-local/scripts/select_remote_model.sh` | 수정 | `9b` 케이스 추가 (base_url 오버라이드, SSH 없음) |
| `skills/fiftybox-local/scripts/stop_remote_model.sh` | 수정 | `9b` 케이스 추가 (no-op) |
| `skills/fiftybox-local/SKILL.md` | 수정 | Phase 1 전체에서 `gemma4` → `9b` 교체, 설명 텍스트 갱신 |

---

## Task 1: .gitignore 패턴 보완

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 현재 상태 확인 — `skills/fiftybox-local.md`가 gitignore에 안 잡히는지 검증**

```bash
git check-ignore -v skills/fiftybox-local.md skills/fiftybox-local-execute.md
```

Expected: 아무것도 출력되지 않음 (= gitignored 아님). exit code 1.

- [ ] **Step 2: `.gitignore`에 평면 파일 패턴 추가**

`.gitignore`의 `skills/fiftybox-local*/` 바로 아래에 한 줄 추가:

```
# Local-only Claude command/skill variants that may contain private endpoints
commands/fiftybox-local*.md
skills/fiftybox-local*/
skills/fiftybox-local*.md
```

- [ ] **Step 3: 적용 확인**

```bash
git check-ignore -v skills/fiftybox-local.md skills/fiftybox-local-execute.md
```

Expected 출력:
```
.gitignore:12:skills/fiftybox-local*.md	skills/fiftybox-local.md
.gitignore:12:skills/fiftybox-local*.md	skills/fiftybox-local-execute.md
```

exit code 0.

- [ ] **Step 4: 커밋**

```bash
git add .gitignore
git commit -m "fix: cover fiftybox-local flat .md files in gitignore"
```

---

## Task 2: select_remote_model.sh에 9b 케이스 추가

**Files:**
- Modify: `skills/fiftybox-local/scripts/select_remote_model.sh`

- [ ] **Step 1: syntax 사전 확인**

```bash
bash -n skills/fiftybox-local/scripts/select_remote_model.sh && echo "OK"
```

Expected: `OK`

- [ ] **Step 2: usage 문자열 업데이트 및 `9b` 케이스 추가**

`select_remote_model.sh`의 `usage()` 첫 줄을 수정하고 case문에 `9b` 케이스를 추가한다.

usage 변경 (`gemma4|27b|35b|current` → `9b|27b|35b|current`):

```bash
Usage: select_remote_model.sh [9b|27b|35b|current]

Starts or verifies the remote GPU model on tanpapa@100.121.45.122, waits for
the OpenAI-compatible /v1/models endpoint, then prints shell export statements.

Use with:
  eval "$(~/.claude/skills/fiftybox-local/scripts/select_remote_model.sh 9b)"
```

`case "$choice" in` 블록의 첫 번째 케이스로 `9b`를 추가한다 (`gemma4` 케이스 삭제):

```bash
case "$choice" in
  9|9b|ollama-9b)
    echo "Using Ollama 9B (always-on, no container start)..." >&2
    base_url="http://100.121.45.122:11434/v1"
    ;;
  27|27b|llama|llamacpp)
    echo "Starting 27B llama.cpp remote model as current..." >&2
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" '~/.local/bin/serve-qwen36-27b-128k.sh' >/dev/null
    ;;
  35|35b|vllm)
    echo "Starting 35B vLLM remote model as current..." >&2
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" '~/.local/bin/serve-vllm-current' >/dev/null
    ;;
  current|keep|existing)
    echo "Keeping current remote model; verifying readiness..." >&2
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unsupported remote model choice: $choice" >&2
    usage
    exit 2
    ;;
esac
```

- [ ] **Step 3: syntax 확인**

```bash
bash -n skills/fiftybox-local/scripts/select_remote_model.sh && echo "OK"
```

Expected: `OK`

- [ ] **Step 4: 9b 케이스 smoke test — stderr 메시지 확인**

```bash
bash skills/fiftybox-local/scripts/select_remote_model.sh 9b 2>&1 | head -3
```

Expected 첫 줄: `Using Ollama 9B (always-on, no container start)...`  
이후 Ollama 엔드포인트 readiness를 기다리는 메시지가 나오거나, 서버가 이미 응답하면 모델 준비 완료 메시지가 나온다. (실제 SSH 없이 시작하므로 네트워크만 필요)

- [ ] **Step 5: 잘못된 인자 확인**

```bash
bash skills/fiftybox-local/scripts/select_remote_model.sh bad-arg 2>&1; echo "exit: $?"
```

Expected: `Unsupported remote model choice: bad-arg` + `exit: 2`

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-local/scripts/select_remote_model.sh
git commit -m "feat: add 9b alias (Ollama, port 11434) to select_remote_model.sh"
```

---

## Task 3: stop_remote_model.sh에 9b 케이스 추가

**Files:**
- Modify: `skills/fiftybox-local/scripts/stop_remote_model.sh`

- [ ] **Step 1: `9b` no-op 케이스 추가**

`case "$choice" in` 블록의 첫 번째 케이스로 추가한다 (`gemma4` 케이스 삭제):

```bash
case "$choice" in
  9|9b|ollama-9b)
    echo "Ollama is a shared service — not stopping." >&2
    ;;
  27|27b|llama|llamacpp)
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" 'docker stop llama-qwen36-27b-iq4-128k >/dev/null 2>&1 || true'
    ;;
  35|35b|vllm)
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" 'docker stop vllm-qwen-35b-gptq >/dev/null 2>&1 || true'
    ;;
  current|all|both)
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$remote" 'docker stop llama-qwen36-27b-iq4-128k vllm-qwen-35b-gptq >/dev/null 2>&1 || true'
    ;;
  keep|none)
    echo "Keeping remote model running." >&2
    ;;
  *)
    echo "Unsupported remote model stop choice: $choice" >&2
    exit 2
    ;;
esac
```

`current|all|both` 케이스에서 `llama-gemma4-a4b-q4-256k llama-gemma4-a4b-q4-128k` 삭제도 함께 처리한다 (Gemma4 컨테이너는 더 이상 쓰지 않음).

- [ ] **Step 2: syntax 확인**

```bash
bash -n skills/fiftybox-local/scripts/stop_remote_model.sh && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: 9b 케이스 동작 확인 — SSH 없이 즉시 반환**

```bash
bash skills/fiftybox-local/scripts/stop_remote_model.sh 9b 2>&1; echo "exit: $?"
```

Expected:
```
Ollama is a shared service — not stopping.
exit: 0
```

- [ ] **Step 4: 커밋**

```bash
git add skills/fiftybox-local/scripts/stop_remote_model.sh
git commit -m "feat: add 9b no-op case to stop_remote_model.sh (Ollama is shared)"
```

---

## Task 4: fiftybox-local/SKILL.md Phase 1 업데이트

**Files:**
- Modify: `skills/fiftybox-local/SKILL.md`

- [ ] **Step 1: 헤더 description 업데이트**

Line 3을 변경한다:

```yaml
description: Use when user invokes /fiftybox-local or wants the full orchestration pipeline with Qwen3.5 9B (Ollama) fixed for codebase exploration and a local GPU model on 100.121.45.122 for implementation.
```

- [ ] **Step 2: Phase 1 도입부 텍스트 교체**

Line 84 (Phase 1 도입부)를 변경한다:

```
Pi CLI 대신 `qwen-summary-index`를 사용한다. **이 단계는 항상 Qwen3.5 9B 262K(Ollama)를 고정 사용한다.** 탐색 시작 직전에 환경변수를 Ollama endpoint로 설정한다:
```

- [ ] **Step 3: EXPLORE 환경변수 블록 교체 (lines 87-94)**

```bash
export FIFTYBOX_EXPLORE_MODEL_CHOICE="9b"
eval "$("$HOME/.claude/skills/fiftybox-local/scripts/select_remote_model.sh" 9b)"
export QWEN_SUMMARY_MAX_CHARS_PER_FILE="12000"
export QWEN_SUMMARY_FILE_BATCH_MAX_TOKENS="8192"
export QWEN_SUMMARY_SINGLE_FILE_MAX_TOKENS="1024"
export QWEN_SUMMARY_MODULE_MAX_TOKENS="2048"
export QWEN_SUMMARY_FINAL_MAX_TOKENS="4096"
export QWEN_SUMMARY_TIMEOUT="900"
```

- [ ] **Step 4: Gemma4 thinking 관련 주석 제거, context-tier 설명 수정**

Line 97 (Gemma 4 thinking 설명)을 삭제한다:
```
Gemma 4는 thinking 출력이 생길 수 있으므로 출력 예산을 작게 잡지 않는다. 코드베이스 탐색 프롬프트는 reasoning을 요구하지 말고, 근거 기반 구조 요약과 경로 목록을 요구한다.
```

Line 99 설명을 변경한다:
```
`qwen-summary-index`는 9B의 context tier인 `256k`로 실행한다:
```

- [ ] **Step 5: stop 호출 교체 (line 110, 113)**

Line 110 텍스트 변경:
```
**탐색 산출물 복사가 끝나는 즉시 Ollama 환경변수를 정리한다.** Ollama는 공유 서비스이므로 컨테이너를 내리지 않는다. 성공, 실패, 중단 모두 동일하게 적용한다:
```

Line 113 변경:
```bash
"$HOME/.claude/skills/fiftybox-local/scripts/stop_remote_model.sh" 9b
```

- [ ] **Step 6: 변경 결과 grep 확인**

```bash
grep -n "gemma\|Gemma\|gemma4\|a4b" skills/fiftybox-local/SKILL.md
```

Expected: 아무것도 출력되지 않음 (gemma 관련 문자열 전부 제거됨).

```bash
grep -n "9b\|Qwen3.5 9B\|Ollama" skills/fiftybox-local/SKILL.md | head -10
```

Expected: Phase 1 관련 라인들에서 `9b`와 `Ollama`가 나타남.

- [ ] **Step 7: 커밋**

```bash
git add skills/fiftybox-local/SKILL.md
git commit -m "feat: switch explore phase from Gemma4 to Qwen3.5 9B via Ollama"
```

---

## Task 5: 통합 검증

- [ ] **Step 1: gitignore 최종 확인**

```bash
git check-ignore -v skills/fiftybox-local.md skills/fiftybox-local-execute.md skills/fiftybox-local/SKILL.md
```

Expected: 세 파일 모두 gitignore 매칭 출력.

- [ ] **Step 2: 스크립트 전체 alias 목록 일관성 확인**

```bash
grep -E "^\s+[0-9]|9b|27b|35b" skills/fiftybox-local/scripts/select_remote_model.sh
grep -E "^\s+[0-9]|9b|27b|35b" skills/fiftybox-local/scripts/stop_remote_model.sh
```

`select`와 `stop` 양쪽에 `9b`, `27b`, `35b`가 모두 있어야 한다.

- [ ] **Step 3: git status — 로컬 파일이 untracked로만 남는지 확인**

```bash
git status
```

Expected: `nothing to commit, working tree clean` (모든 변경이 커밋됨).
`skills/fiftybox-local*` 파일들이 `git status`에 나타나지 않아야 한다 (gitignored).

- [ ] **Step 4: 실제 연결 테스트 (선택, 서버 접근 가능할 때)**

```bash
eval "$(bash skills/fiftybox-local/scripts/select_remote_model.sh 9b 2>/dev/null)"
echo "Model: $LOCAL_MODEL_NAME"
echo "URL:   $LOCAL_MODEL_BASE_URL"
```

Expected:
```
Model: qwen35-9b-262k-pi:latest
URL:   http://100.121.45.122:11434/v1
```
