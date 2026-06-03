# Pi CLI 모델 Fallback 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deepseek 등 지정 모델이 구독 만료/권한 오류로 사용 불가할 때 Pi CLI 페이즈가 `model_unavailable: true` JSON을 반환하고, 사용자가 가용 모델을 선택해 재시도할 수 있게 한다.

**Architecture:** `orchestrate.py`에 모델 unavailable 에러 패턴 감지 로직을 추가하고, setup 페이즈에서 `pi --list-models` 결과를 `summary.json["availableModels"]`에 캐싱한다. explore/implement/pi-deploy 페이즈 실패 시 패턴 매칭 후 `fail_json(extra={"model_unavailable": true, ...})`로 반환한다. orchestrate SKILL.md와 pi-execute SKILL.md는 이 응답을 받아 사용자에게 가용 모델 목록을 제시하고 선택받아 재시도한다.

**Tech Stack:** Python 3, orchestrate.py, Markdown (SKILL.md)

---

## 파일 구조

| 파일 | 변경 종류 | 책임 |
|------|-----------|------|
| `~/.claude/skills/orchestrate/scripts/orchestrate.py` | 수정 | 에러 감지 상수/함수 추가, setup 캐싱, 3개 페이즈 에러 감지 |
| `~/.claude/skills/orchestrate/SKILL.md` | 수정 | `model_unavailable` 응답 처리 지침 추가 |
| `~/.claude/skills/pi-execute/SKILL.md` | 수정 | 동일한 `model_unavailable` 응답 처리 지침 추가 |

---

## Task 1: 에러 감지 상수와 함수 추가 (`orchestrate.py`)

**Files:**
- Modify: `~/.claude/skills/orchestrate/scripts/orchestrate.py:138`

현재 파일 라인 138 직후 (`RMCP_NOISE_MARKERS` 블록 바로 위)에 새 상수와 함수를 삽입한다.

- [ ] **Step 1: `PI_MODEL_UNAVAILABLE_PATTERNS` 상수를 라인 138 직후에 삽입**

정확히 `RMCP_NOISE_MARKERS = [` 바로 앞에 추가:

```python
PI_MODEL_UNAVAILABLE_PATTERNS = [
    "subscription",
    "payment required",
    "402",
    "403 forbidden",
    "model not found",
    "model unavailable",
    "model access denied",
    "access denied",
    "not authorized",
    "quota exceeded",
    "no access to model",
    "you don't have access",
    "you do not have access",
    "permission denied",
    "no permission",
    "forbidden",
]

```

- [ ] **Step 2: `is_pi_model_unavailable()` 함수를 `is_codex_api_error()` 함수(라인 547) 직후에 삽입**

```python
def is_pi_model_unavailable(output: str) -> bool:
    """Detect Pi CLI model unavailable errors (subscription expired, no access, etc.)."""
    lower = output.lower()
    return any(pattern in lower for pattern in PI_MODEL_UNAVAILABLE_PATTERNS)

```

- [ ] **Step 3: 파일이 파싱 가능한지 확인**

```bash
python3 -c "import ast; ast.parse(open('/Users/tanpapa/.claude/skills/orchestrate/scripts/orchestrate.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 커밋**

```bash
cd ~/.claude/skills/orchestrate
git add scripts/orchestrate.py
git commit -m "feat: add PI_MODEL_UNAVAILABLE_PATTERNS and is_pi_model_unavailable()"
```

---

## Task 2: setup 페이즈에서 가용 모델 목록 캐싱 (`orchestrate.py`)

**Files:**
- Modify: `~/.claude/skills/orchestrate/scripts/orchestrate.py:968-1002`

setup 페이즈의 `pi --list-models` 호출 결과를 파싱해 `summary.json`에 저장한다.

- [ ] **Step 1: `pi --list-models` 결과 파싱 코드 삽입**

라인 974 (provider 체크 통과 직후) 다음에 추가:

```python
        available_models: list[str] = []
        for line in pi_models.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == args.provider:
                available_models.append(parts[1])
```

- [ ] **Step 2: summary dict에 `availableModels` 필드 추가**

라인 987–1002의 summary dict에 `"availableModels": available_models,` 를 추가한다.

현재 코드:
```python
    summary = {
        "taskDescription": args.task,
        "worktree": str(worktree_path),
        "branch": branch,
        "artifactDir": str(artifact_dir),
        "provider": args.provider,
        "model": args.model,
        "codexModel": args.codex_model,
        "claudeModel": args.claude_model,
        "interop": interop_paths,
        "files": {},
        "phases": {},
        "finalStatus": "in_progress",
        "error": None,
        "mergedCommit": None,
    }
```

변경 후:
```python
    summary = {
        "taskDescription": args.task,
        "worktree": str(worktree_path),
        "branch": branch,
        "artifactDir": str(artifact_dir),
        "provider": args.provider,
        "model": args.model,
        "codexModel": args.codex_model,
        "claudeModel": args.claude_model,
        "interop": interop_paths,
        "availableModels": available_models,
        "files": {},
        "phases": {},
        "finalStatus": "in_progress",
        "error": None,
        "mergedCommit": None,
    }
```

- [ ] **Step 3: dry_run 경로에도 `available_models = []` 초기화 추가**

`else:` (dry_run 분기, 라인 975)에 빈 목록 초기화 추가:

```python
    else:
        logger.log("[DRY RUN] Skipping prerequisite command checks")
        available_models: list[str] = []
```

- [ ] **Step 4: 파일 파싱 확인**

```bash
python3 -c "import ast; ast.parse(open('/Users/tanpapa/.claude/skills/orchestrate/scripts/orchestrate.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: dry_run으로 setup 실행해 `availableModels` 필드가 출력되는지 확인**

```bash
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase setup --task "test task" --cwd /tmp --dry-run 2>&1 | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        if 'availableModels' in d:
            print('availableModels present:', d['availableModels'])
        elif 'artifactDir' in d:
            import os, json as j
            s = j.load(open(d['artifactDir'] + '/summary.json'))
            print('availableModels in summary:', s.get('availableModels', 'MISSING'))
    except: pass
"
```

Expected: `availableModels present: []` (dry_run이므로 빈 목록)

- [ ] **Step 6: 커밋**

```bash
cd ~/.claude/skills/orchestrate
git add scripts/orchestrate.py
git commit -m "feat: cache available models in summary.json during setup"
```

---

## Task 3: explore 페이즈 모델 에러 감지 (`orchestrate.py`)

**Files:**
- Modify: `~/.claude/skills/orchestrate/scripts/orchestrate.py:1089-1098`

Pi CLI 호출 실패 시 `is_pi_model_unavailable()`로 모델 에러 여부 확인 후 `extra` 포함.

- [ ] **Step 1: explore 페이즈의 실패 처리 블록 교체**

현재 코드 (라인 1089–1098):
```python
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["explore"] = phase_record("failed", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="explore",
            error=(result_proc.stdout or "Unknown Pi CLI error")[-2000:],
            artifact_dir=artifact_dir,
            exit_code=result_proc.returncode,
        )
```

변경 후:
```python
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["explore"] = phase_record("failed", logger)
        write_json(artifact_dir / "summary.json", summary)
        error_output = (result_proc.stdout or "Unknown Pi CLI error")[-2000:]
        extra: dict[str, Any] | None = None
        if is_pi_model_unavailable(result_proc.stdout):
            available = [m for m in summary.get("availableModels", []) if m != args.explore_model]
            extra = {
                "retriable": True,
                "model_unavailable": True,
                "triedModel": args.explore_model,
                "availableModels": available,
            }
        return fail_json(
            phase="explore",
            error=error_output,
            artifact_dir=artifact_dir,
            exit_code=result_proc.returncode,
            extra=extra,
        )
```

- [ ] **Step 2: 파일 파싱 확인**

```bash
python3 -c "import ast; ast.parse(open('/Users/tanpapa/.claude/skills/orchestrate/scripts/orchestrate.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: `model_unavailable` 응답 JSON 수동 테스트**

아래 스크립트로 에러 감지 함수가 올바른 패턴을 인식하는지 확인:

```bash
python3 - <<'EOF'
import sys
sys.path.insert(0, str(__import__('pathlib').Path.home() / '.claude/skills/orchestrate/scripts'))
from orchestrate import is_pi_model_unavailable
cases = [
    ("subscription expired", True),
    ("403 forbidden", True),
    ("model not found", True),
    ("connection reset", False),
    ("rate_limit_exceeded", False),
    ("you do not have access to this model", True),
]
for text, expected in cases:
    result = is_pi_model_unavailable(text)
    status = "OK" if result == expected else "FAIL"
    print(f"{status}: is_pi_model_unavailable({text!r}) == {result} (expected {expected})")
EOF
```

Expected: 모든 라인이 `OK:`로 시작

- [ ] **Step 4: 커밋**

```bash
cd ~/.claude/skills/orchestrate
git add scripts/orchestrate.py
git commit -m "feat: detect model_unavailable in explore phase"
```

---

## Task 4: implement 페이즈 모델 에러 감지 (`orchestrate.py`)

**Files:**
- Modify: `~/.claude/skills/orchestrate/scripts/orchestrate.py:1545-1549`

- [ ] **Step 1: implement 페이즈의 실패 처리 블록 교체**

현재 코드 (라인 1545–1549):
```python
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["implement"] = phase_record("failed", logger, attempt=2 if is_retry else 1)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="implement", error=result_proc.stdout[-2000:], artifact_dir=artifact_dir, exit_code=result_proc.returncode)
```

변경 후:
```python
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["implement"] = phase_record("failed", logger, attempt=2 if is_retry else 1)
        write_json(artifact_dir / "summary.json", summary)
        error_output = result_proc.stdout[-2000:]
        extra: dict[str, Any] | None = None
        if is_pi_model_unavailable(result_proc.stdout):
            available = [m for m in summary.get("availableModels", []) if m != args.model]
            extra = {
                "retriable": True,
                "model_unavailable": True,
                "triedModel": args.model,
                "availableModels": available,
            }
        return fail_json(
            phase="implement",
            error=error_output,
            artifact_dir=artifact_dir,
            exit_code=result_proc.returncode,
            extra=extra,
        )
```

- [ ] **Step 2: 파일 파싱 확인**

```bash
python3 -c "import ast; ast.parse(open('/Users/tanpapa/.claude/skills/orchestrate/scripts/orchestrate.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
cd ~/.claude/skills/orchestrate
git add scripts/orchestrate.py
git commit -m "feat: detect model_unavailable in implement phase"
```

---

## Task 5: pi-deploy 페이즈 모델 에러 감지 (`orchestrate.py`)

**Files:**
- Modify: `~/.claude/skills/orchestrate/scripts/orchestrate.py:2109-2113`

- [ ] **Step 1: pi-deploy 페이즈의 실패 처리 블록 교체**

현재 코드 (라인 2109–2113):
```python
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["pi_deploy"] = phase_record("failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-deploy", error=result_proc.stdout[-2000:], artifact_dir=artifact_dir, exit_code=result_proc.returncode)
```

변경 후:
```python
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["pi_deploy"] = phase_record("failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        error_output = result_proc.stdout[-2000:]
        extra: dict[str, Any] | None = None
        if is_pi_model_unavailable(result_proc.stdout):
            available = [m for m in summary.get("availableModels", []) if m != args.model]
            extra = {
                "retriable": True,
                "model_unavailable": True,
                "triedModel": args.model,
                "availableModels": available,
            }
        return fail_json(
            phase="pi-deploy",
            error=error_output,
            artifact_dir=artifact_dir,
            exit_code=result_proc.returncode,
            extra=extra,
        )
```

- [ ] **Step 2: 파일 파싱 확인**

```bash
python3 -c "import ast; ast.parse(open('/Users/tanpapa/.claude/skills/orchestrate/scripts/orchestrate.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
cd ~/.claude/skills/orchestrate
git add scripts/orchestrate.py
git commit -m "feat: detect model_unavailable in pi-deploy phase"
```

---

## Task 6: orchestrate SKILL.md에 `model_unavailable` 처리 추가

**Files:**
- Modify: `~/.claude/skills/orchestrate/SKILL.md` (API Error vs. Rejection 섹션)

- [ ] **Step 1: "API Error vs. Rejection" 섹션 찾기**

```bash
grep -n "API Error vs. Rejection\|retriable" ~/.claude/skills/orchestrate/SKILL.md | head -10
```

- [ ] **Step 2: "API Error vs. Rejection" 섹션 바로 앞에 새 섹션 삽입**

`### API Error vs. Rejection` 헤더 바로 위에 다음 블록을 추가한다:

```markdown
### Model Unavailable Error

Pi CLI 페이즈(explore, implement, pi-deploy)가 실패하고 JSON에 `"model_unavailable": true`가 포함된 경우:

1. 사용자에게 다음 메시지를 표시한다:

```
[페이즈명] 모델 [triedModel]에 접근할 수 없습니다.
사유: <에러 요약 1줄>

현재 사용 가능한 모델:
1. <availableModels[0]>
2. <availableModels[1]>
...

어떤 모델로 재시도할까요? (번호 또는 "취소")
```

2. 사용자 응답 처리:
   - 번호 선택 → 해당 페이즈를 `--model <선택모델>`로 재실행 (`explore` 페이즈는 `--explore-model <선택모델>`)
   - "취소" → 기존 실패 보고 흐름으로 진행 (Failure Report Format 참조)

3. `availableModels`가 빈 목록인 경우: "사용 가능한 모델이 없습니다. `pi --list-models <provider>`로 확인하세요." 메시지 표시 후 취소와 동일하게 처리한다.

```

- [ ] **Step 3: 삽입 결과 확인**

```bash
grep -n "Model Unavailable Error\|model_unavailable\|API Error vs. Rejection" ~/.claude/skills/orchestrate/SKILL.md
```

Expected: `Model Unavailable Error` 섹션이 `API Error vs. Rejection` 섹션보다 먼저 나와야 함.

- [ ] **Step 4: 커밋**

```bash
cd ~/.claude/skills/orchestrate
git add SKILL.md
git commit -m "docs: add model_unavailable handling to orchestrate SKILL.md"
```

---

## Task 7: pi-execute SKILL.md에 동일한 처리 추가

**Files:**
- Modify: `~/.claude/skills/pi-execute/SKILL.md` (Failure Report Format 섹션 근처)

- [ ] **Step 1: Failure Report Format 섹션 위치 확인**

```bash
grep -n "Failure Report Format\|Safety Contract" ~/.claude/skills/pi-execute/SKILL.md | head -10
```

- [ ] **Step 2: "Failure Report Format" 섹션 바로 앞에 새 섹션 삽입**

```markdown
## Model Unavailable Error

Pi CLI 페이즈(implement, pi-deploy)가 실패하고 JSON에 `"model_unavailable": true`가 포함된 경우:

1. 사용자에게 다음 메시지를 표시한다:

```
[페이즈명] 모델 [triedModel]에 접근할 수 없습니다.
사유: <에러 요약 1줄>

현재 사용 가능한 모델:
1. <availableModels[0]>
2. <availableModels[1]>
...

어떤 모델로 재시도할까요? (번호 또는 "취소")
```

2. 사용자 응답 처리:
   - 번호 선택 → 해당 페이즈를 `--model <선택모델> --skip-verify`로 재실행
   - "취소" → 기존 실패 보고 흐름으로 진행 (Failure Report Format 참조)

3. `availableModels`가 빈 목록인 경우: "사용 가능한 모델이 없습니다. `pi --list-models <provider>`로 확인하세요." 메시지 표시 후 취소와 동일하게 처리한다.

```

- [ ] **Step 3: 삽입 결과 확인**

```bash
grep -n "Model Unavailable Error\|Failure Report Format" ~/.claude/skills/pi-execute/SKILL.md
```

Expected: `Model Unavailable Error` 섹션이 `Failure Report Format` 섹션보다 먼저 나와야 함.

- [ ] **Step 4: 커밋**

```bash
cd ~/.claude/skills/pi-execute
git add SKILL.md
git commit -m "docs: add model_unavailable handling to pi-execute SKILL.md"
```

---

## Task 8: 통합 검증

- [ ] **Step 1: `is_pi_model_unavailable` 패턴 커버리지 최종 확인**

```bash
python3 - <<'EOF'
import sys
sys.path.insert(0, str(__import__('pathlib').Path.home() / '.claude/skills/orchestrate/scripts'))
from orchestrate import is_pi_model_unavailable, PI_MODEL_UNAVAILABLE_PATTERNS, is_codex_api_error

# 모델 에러 → True여야 함
model_errors = [
    "Error: subscription expired for model deepseek-v4-pro",
    "HTTP 403 forbidden: model access denied",
    "402 payment required",
    "you do not have access to this model",
    "quota exceeded for deepseek",
    "permission denied: model unavailable",
]
# 다른 에러 → False여야 함 (기존 Codex 패턴과 겹치지 않아야 함)
other_errors = [
    "connection reset by peer",
    "internal server error",
    "rate_limit_exceeded",
    "timeout after 300s",
]

print("=== Model Errors (expect True) ===")
for e in model_errors:
    r = is_pi_model_unavailable(e)
    print(f"{'OK' if r else 'FAIL'}: {e[:60]!r} -> {r}")

print("\n=== Other Errors (expect False) ===")
for e in other_errors:
    r = is_pi_model_unavailable(e)
    print(f"{'OK' if not r else 'FAIL'}: {e[:60]!r} -> {r}")
EOF
```

Expected: 모든 라인 `OK`.

- [ ] **Step 2: `summary.json` 스키마 확인 (dry-run)**

```bash
TMP=$(mktemp -d)
python3 ~/.claude/skills/orchestrate/scripts/orchestrate.py \
  --phase setup --task "verify availableModels" --cwd "$TMP" --dry-run \
  | python3 -c "
import sys, json, pathlib
for line in sys.stdin:
    try:
        d = json.loads(line)
        ad = d.get('artifactDir')
        if ad:
            s = json.loads(pathlib.Path(ad, 'summary.json').read_text())
            key = 'availableModels'
            print(f'{key} in summary.json:', key in s)
            print('value:', s.get(key))
    except Exception as e:
        pass
"
```

Expected: `availableModels in summary.json: True`

- [ ] **Step 3: SKILL.md 두 파일 모두 `model_unavailable` 섹션 포함 확인**

```bash
grep -l "model_unavailable" \
  ~/.claude/skills/orchestrate/SKILL.md \
  ~/.claude/skills/pi-execute/SKILL.md \
  | wc -l
```

Expected: `2`

- [ ] **Step 4: 최종 커밋 (변경 없으면 skip)**

```bash
cd ~/.claude/skills/orchestrate
git status
```
