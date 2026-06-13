# 로컬 모델 설정 분리 설계

**날짜:** 2026-06-13  
**목표:** 맥미니 로컬 GPU 모델 설정을 공개 GitHub 리포에서 격리

---

## 문제

`.gitignore`의 `skills/fiftybox-local*/` 패턴은 디렉토리만 커버한다.
`skills/fiftybox-local.md`, `skills/fiftybox-local-execute.md` 같은 평면 `.md` 파일은 패턴 밖이라
`git add .` 한 번에 실수로 공개될 수 있다.

---

## 서버 현황 (100.121.45.122 확인)

| 모델 | 컨테이너 | 엔드포인트 | 모델 ID |
|------|----------|------------|---------|
| 9B | `ollama-qwen35` (항상 실행 중) | `http://100.121.45.122:11434/v1` | `qwen35-9b-262k-pi:latest` |
| 27B | `llama-qwen36-27b-iq4-128k` | `http://100.121.45.122:8000/v1` | `serve-qwen36-27b-128k.sh`로 시작 |
| 35B A3B | `vllm-qwen-35b-gptq` | `http://100.121.45.122:8000/v1` | `serve-vllm-current`로 시작 |

9B는 전용 serve 스크립트 없음. Ollama 컨테이너가 항상 실행 중이며 OpenAI 호환 API 제공.

---

## 설계

### 변경 1: `.gitignore` 패턴 보완

```diff
  commands/fiftybox-local*.md
  skills/fiftybox-local*/
+ skills/fiftybox-local*.md
```

`skills/fiftybox-local*.md` 추가로 평면 `.md` 파일까지 커버한다.

---

### 변경 2: 모델 매핑

| 단계 | 현재 | 변경 후 |
|------|------|---------|
| Phase 1 EXPLORE | Gemma 4 26B A4B (port 8000) | **9B — Ollama (port 11434)** |
| Phase 5 IMPLEMENT 기본 | Qwen3 27B (port 8000) | 27B (유지) |
| Phase 5 IMPLEMENT `--local-model 35b` | Qwen3 35B vLLM (port 8000) | **35B A3B (유지)** |
| Phase 6/7 | 스크립트 실행 (모델 불필요) | 변경 없음 |

---

### 변경 3: `select_remote_model.sh`에 `9b` 케이스 추가

9B는 Ollama가 항상 실행 중이므로 SSH로 컨테이너를 시작할 필요 없음.
엔드포인트만 포트 11434로 바꿔서 readiness 대기 후 env 출력.

```bash
9|9b|ollama-9b)
  echo "Using Ollama 9B (always-on, no container start)..." >&2
  base_url="http://100.121.45.122:11434/v1"
  ;;
```

---

### 변경 4: `stop_remote_model.sh`에 `9b` 케이스 추가

Ollama는 공유 서비스이므로 stop 하지 않음.

```bash
9|9b|ollama-9b)
  echo "Ollama is a shared service — not stopping." >&2
  ;;
```

---

### 변경 5: `fiftybox-local/SKILL.md` Phase 1 업데이트

```diff
- export FIFTYBOX_EXPLORE_MODEL_CHOICE="gemma4"
- eval "$("$HOME/.claude/skills/fiftybox-local/scripts/select_remote_model.sh" gemma4)"
+ export FIFTYBOX_EXPLORE_MODEL_CHOICE="9b"
+ eval "$("$HOME/.claude/skills/fiftybox-local/scripts/select_remote_model.sh" 9b)"
```

stop 시에도 `9b`로 호출하여 Ollama를 내리지 않도록:

```diff
- "$HOME/.claude/skills/fiftybox-local/scripts/stop_remote_model.sh" gemma4
+ "$HOME/.claude/skills/fiftybox-local/scripts/stop_remote_model.sh" 9b
```

---

## 보장

- `git push` 후 GitHub에 로컬 IP, 포트, 모델 ID가 노출되지 않는다.
- `git add .` 실수에도 `skills/fiftybox-local*.md`가 스테이지되지 않는다.
- `/fiftybox-local` 실행 시: 탐색은 Ollama 9B, 구현은 llama.cpp 27B, 대형 구현은 vLLM 35B A3B.
- Ollama는 탐색 후에도 내려가지 않는다 (공유 서비스).

---

## 범위 외

- Phase 3 DESIGN (Opus 클라우드), Phase 5.5 CLAUDE REVIEW GATE (Claude 직접 실행)는 변경하지 않는다.
