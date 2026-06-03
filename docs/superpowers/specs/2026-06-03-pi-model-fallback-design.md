# Pi CLI 모델 Fallback 설계

**날짜:** 2026-06-03  
**상태:** 승인됨  
**대상 파일:** `orchestrate.py`, `skills/orchestrate/SKILL.md`, `skills/pi-execute/SKILL.md`

---

## 목적

`/orchestrate` 및 `/pi-execute` 파이프라인에서 지정된 모델(기본값: `deepseek-v4-pro`, `deepseek-v4-flash`)이 구독 만료 또는 권한 오류로 사용 불가할 때, 사용자가 확인 후 다른 가용 모델로 자동 전환할 수 있게 한다.

---

## 아키텍처 개요

변경은 세 레이어에 걸쳐 이루어진다:

1. **`orchestrate.py` (감지 레이어):** Pi CLI 에러 메시지에서 모델 unavailable 패턴을 감지하고, `fail_json` 응답에 `model_unavailable: true`와 `availableModels` 목록을 포함시킨다. setup 페이즈에서 이미 `pi --list-models` 를 호출하므로 그 결과를 파싱해 `summary.json`에 캐싱한다.

2. **`SKILL.md` (Claude 레이어):** `model_unavailable: true` 응답을 받으면 사용자에게 가용 모델 목록을 제시하고 선택받아 동일 페이즈를 `--model <선택>`으로 재실행한다.

3. **두 스킬 파일 모두 동일한 처리 로직** 적용 (orchestrate SKILL.md + pi-execute SKILL.md).

---

## 컴포넌트 및 책임

### `PI_MODEL_UNAVAILABLE_PATTERNS` 상수

Pi CLI가 반환하는 모델 unavailable 에러 문자열 패턴 목록:

```python
PI_MODEL_UNAVAILABLE_PATTERNS = [
    "subscription",
    "subscription expired",
    "no subscription",
    "payment required",
    "402 payment required",
    "403 forbidden",
    "model not found",
    "model unavailable",
    "model access denied",
    "access denied",
    "not authorized",
    "quota exceeded",
    "no access to model",
]
```

### `is_pi_model_unavailable(output: str) -> bool` 함수

Pi CLI stdout/stderr를 받아 모델 unavailable 여부 반환. `CODEX_API_ERROR_PATTERNS`와 동일한 패턴으로 구현.

### setup 페이즈 — `availableModels` 캐싱

`pi --list-models <provider>` 결과를 파싱해 모델명 목록을 `summary.json["availableModels"]`에 저장. 이후 모든 페이즈에서 재사용.

```json
{
  "availableModels": ["deepseek-v4-pro", "deepseek-v4-flash", "kimi-k2.5", "qwen3.6-plus", ...]
}
```

### implement / explore / deploy 페이즈 — 에러 감지 및 반환

Pi CLI 호출 실패 시:
1. `is_pi_model_unavailable(result_proc.stdout)` 호출
2. True이면 `summary.json["availableModels"]` 읽어서 현재 모델 제외
3. `fail_json`에 추가 필드 포함:

```json
{
  "status": "failed",
  "phase": "implement",
  "error": "<원본 에러>",
  "model_unavailable": true,
  "triedModel": "deepseek-v4-pro",
  "availableModels": ["kimi-k2.5", "kimi-k2.6", "qwen3.6-plus", ...],
  "retriable": true
}
```

---

## 데이터 흐름

```
Pi CLI 호출 실패
    │
    ├─ is_pi_model_unavailable? ──No──► 기존 fail_json (변경 없음)
    │
    └─ Yes
         │
         ▼
   summary.json["availableModels"] 읽기 (현재 모델 제외)
         │
         ▼
   fail_json + model_unavailable:true + availableModels 반환
         │
         ▼
   SKILL.md: 사용자에게 목록 제시
         │
         ▼
   사용자 선택
         │
         ▼
   --model <선택모델> 로 동일 페이즈 재실행
```

---

## 파일 변경 목록

| 파일 | 변경 내용 |
|------|-----------|
| `~/.claude/skills/orchestrate/scripts/orchestrate.py` | `PI_MODEL_UNAVAILABLE_PATTERNS`, `is_pi_model_unavailable()`, setup 캐싱, implement/explore/deploy 페이즈 에러 감지 |
| `~/.claude/skills/orchestrate/SKILL.md` | API Error vs Rejection 섹션에 `model_unavailable` 처리 추가 |
| `~/.claude/skills/pi-execute/SKILL.md` | 동일한 `model_unavailable` 처리 섹션 추가 |

---

## 에러 처리 접근법

### 모델 unavailable 에러 (신규)

SKILL.md에서 `model_unavailable: true`를 받으면:

```
모델 [deepseek-v4-pro]에 접근할 수 없습니다.
사유: <에러 요약>

현재 사용 가능한 모델:
1. kimi-k2.5
2. kimi-k2.6
3. qwen3.6-plus
4. mimo-v2.5-pro
...

어떤 모델로 재시도할까요? (번호 또는 취소)
```

사용자 선택 후 동일 페이즈를 `--model <선택>`으로 재실행.  
취소 시 기존 실패 보고 흐름으로 넘어간다.

### 기존 API 에러 (변경 없음)

`"retriable": true` but `model_unavailable` 없음 → 기존 처리 유지.

---

## 검증 계획

1. `deepseek-v4-pro` 대신 존재하지 않는 모델명으로 implement 실행 → `model_unavailable: true` JSON 반환 확인
2. `availableModels` 목록에서 현재 모델이 제외되는지 확인
3. 사용자가 대안 모델 선택 후 해당 모델로 Pi CLI가 재호출되는지 확인
4. explore, implement, deploy 세 페이즈 모두 동일하게 동작하는지 확인
5. 일반 실패(비 모델 에러)는 기존 흐름 유지 확인

---

## 인터페이스 계약

### `is_pi_model_unavailable(output: str) -> bool`

```python
def is_pi_model_unavailable(output: str) -> bool:
    lower = output.lower()
    return any(pattern in lower for pattern in PI_MODEL_UNAVAILABLE_PATTERNS)
```

### `fail_json` 호출 패턴 (시그니처 변경 없음)

`fail_json`은 이미 `extra: dict` 파라미터를 지원한다. 모델 unavailable 시 다음과 같이 호출:

```python
fail_json(
    phase="implement",
    error=result_proc.stdout[-2000:],
    artifact_dir=artifact_dir,
    exit_code=result_proc.returncode,
    extra={
        "retriable": True,
        "model_unavailable": True,
        "triedModel": args.model,
        "availableModels": available_models,  # summary.json에서 읽은 목록, 현재 모델 제외
    }
)
```

### `summary.json` 확장

```json
{
  "availableModels": ["deepseek-v4-pro", "deepseek-v4-flash", "kimi-k2.5", ...]
}
```
setup 페이즈에서 저장, 이후 페이즈에서 읽기 전용.
