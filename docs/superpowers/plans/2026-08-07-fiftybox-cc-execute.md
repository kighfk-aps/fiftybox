# fiftybox-cc-execute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CommandCode(`cmd`) CLI를 구현자로 쓰는 병렬 배치 TDD 실행 스킬 `fiftybox-cc-execute`를 추가한다.

**Architecture:** 기존 `fiftybox-execute`(Pi 계열) 파이프라인을 그대로 재사용하고, `orchestrate.py`의 `BUILTIN_AGENTS`에 `commandcode` 항목 하나를 추가한 뒤 스킬이 `--implement-agent commandcode`로 호출한다. 파이썬 로직 수정은 없다. 스킬 전용 자산은 SKILL.md와 preflight 스크립트 둘뿐이며, 나머지는 설치 배선과 테스트다.

**Tech Stack:** Python 3(표준 라이브러리만), Bash 테스트(`tests/*.sh`의 pass/fail 헬퍼 패턴), Markdown 스킬 문서.

**Spec:** `docs/superpowers/specs/2026-08-07-fiftybox-cc-execute-design.md`

## Global Constraints

- 새 파이썬 의존성 금지. `cc_preflight.py`는 표준 라이브러리만 쓴다 (`argparse`, `json`, `re`, `shutil`, `subprocess`, `sys`).
- `orchestrate.py`는 `BUILTIN_AGENTS` 딕셔너리 항목 추가 외의 수정을 하지 않는다.
- 테스트는 실제 `cmd` 바이너리를 호출하지 않는다. PATH에 스텁을 넣어 검증한다.
- 문서(SKILL.md, 슬래시 명령)는 한국어로 쓴다. 기존 `skills/fiftybox-free-execute/SKILL.md`와 같은 톤이다.
- 모델 ID는 실측값을 그대로 쓴다: `deepseek/deepseek-v4-flash`, `zai-org/glm-5.2`.
- 검증된 CLI 버전은 CommandCode v1.14.1이다.
- 커밋은 태스크마다 한 번. 커밋 메시지는 영어 Conventional Commits.

---

### Task 1: orchestrate.py CommandCode 어댑터

**Files:**
- Modify: `skills/fiftybox-orchestration/scripts/orchestrate.py:79-91` (`BUILTIN_AGENTS`)
- Test: `tests/test_cc_agent.sh` (create)

**Interfaces:**
- Consumes: 기존 `build_agent_cmd(agent_name, config, *, prompt, task, model, provider, adapters_dir) -> list[str]`
- Produces: `BUILTIN_AGENTS["commandcode"]` — 이후 모든 태스크가 `--implement-agent commandcode`로 참조하는 에이전트 이름

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cc_agent.sh` 를 새로 만든다. `orchestrate.py`는 `if __name__ == "__main__"` 가드가 있어 import해도 argparse가 돌지 않는다(확인됨). 그래서 모듈을 직접 로드해 검증한다.

```bash
#!/usr/bin/env bash
# Tests for the commandcode agent entry in orchestrate.py
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCH="$SCRIPT_DIR/skills/fiftybox-orchestration/scripts/orchestrate.py"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

run_py() {
    ORCH_PATH="$ORCH" python3 - "$@" <<'PY'
import importlib.util, json, os, sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("orch", os.environ["ORCH_PATH"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

what = sys.argv[1]
if what == "has-agent":
    print("yes" if "commandcode" in mod.BUILTIN_AGENTS else "no")
elif what == "argv":
    cfg = {"agents": dict(mod.BUILTIN_AGENTS)}
    argv = mod.build_agent_cmd(
        "commandcode", cfg,
        prompt="PROMPT", task="TASK", model="MODEL",
        provider="SHOULD_NOT_APPEAR", adapters_dir=Path("/tmp"),
    )
    print(json.dumps(argv))
elif what == "unknown-agent":
    cfg = {"agents": dict(mod.BUILTIN_AGENTS)}
    try:
        mod.build_agent_cmd(
            "no-such-agent", cfg,
            prompt="P", task="T", model="M",
            provider="PR", adapters_dir=Path("/tmp"),
        )
    except ValueError as exc:
        print(str(exc))
    else:
        print("NO_ERROR_RAISED")
PY
}

# 1. 에이전트가 등록돼 있다
[[ "$(run_py has-agent)" == "yes" ]] \
    && pass "commandcode agent registered in BUILTIN_AGENTS" \
    || fail "commandcode agent missing from BUILTIN_AGENTS"

ARGV="$(run_py argv)"

# 2. 정확한 argv를 만든다
EXPECTED='["cmd", "-p", "PROMPT\nTASK", "-m", "MODEL", "--yolo", "--trust", "--no-session", "--skip-onboarding", "--no-auto-update"]'
NORMALISED="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$ARGV")"
EXPECTED_NORM="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$EXPECTED")"
[[ "$NORMALISED" == "$EXPECTED_NORM" ]] \
    && pass "commandcode argv matches the specified flag set" \
    || fail "commandcode argv mismatch: $ARGV"

# 3. provider 토큰이 새어나오지 않는다 (CommandCode에는 provider 개념이 없다)
[[ "$ARGV" != *SHOULD_NOT_APPEAR* ]] \
    && pass "provider value not passed to cmd" \
    || fail "provider value leaked into cmd argv: $ARGV"

# 4. 알 수 없는 에이전트는 기존 에러 메시지로 실패한다
UNKNOWN="$(run_py unknown-agent)"
[[ "$UNKNOWN" == *"Unknown agent 'no-such-agent'"* ]] \
    && pass "unknown agent still raises the existing error" \
    || fail "unknown agent error changed: $UNKNOWN"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `chmod +x tests/test_cc_agent.sh && bash tests/test_cc_agent.sh`
Expected: FAIL — "commandcode agent missing from BUILTIN_AGENTS" 및 argv 불일치

- [ ] **Step 3: 어댑터 추가**

`skills/fiftybox-orchestration/scripts/orchestrate.py`의 `BUILTIN_AGENTS`에서 `"codex"` 항목 바로 뒤, 닫는 중괄호 앞에 추가한다:

```python
    "commandcode": {"cmd": ["cmd", "-p", "{prompt}\n{task}", "-m", "{model}",
                            "--yolo", "--trust", "--no-session",
                            "--skip-onboarding", "--no-auto-update"]},
```

`{provider}`는 쓰지 않는다. CommandCode에는 provider 개념이 없다(`codex` 항목과 같다).

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `bash tests/test_cc_agent.sh`
Expected: PASS 4건, `Results: 4 passed, 0 failed`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_cc_agent.sh skills/fiftybox-orchestration/scripts/orchestrate.py
git commit -m "feat(orchestrate): add commandcode agent adapter"
```

---

### Task 2: cc_preflight.py

**Files:**
- Create: `skills/fiftybox-cc-execute/scripts/cc_preflight.py`
- Test: `tests/test_cc_preflight.sh` (create)

**Interfaces:**
- Consumes: 없음 (`cmd` 바이너리만 호출한다. orchestrate.py를 알지 못한다)
- Produces: stdout JSON —
  `{"ok": bool, "status": str, "message": str, "models": list[str], "missingModels": list[str]}`
  `status`는 `ready` / `not_installed` / `not_authenticated` / `list_failed` / `missing_models` 중 하나.
  exit 0은 `ok: true`일 때만. SKILL.md Step 0이 이 JSON을 읽는다.

**실측 근거:**
- `cmd status`는 미인증 시 exit 1, 인증 시 exit 0. 출력에 ANSI 색 코드가 섞인다
- `cmd --list-models`는 인증 없이도 exit 0으로 동작한다. 파이프로 받으면 ANSI가 없다
- 목록 형식: 섹션 헤더(`Open Source`, `Anthropic` …) 사이에 `<id><공백 2칸 이상><설명>` 줄
- ID는 `deepseek/deepseek-v4-flash`처럼 슬래시가 있는 것과 `claude-sonnet-5`처럼 없는 것이 섞여 있다

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cc_preflight.sh`:

```bash
#!/usr/bin/env bash
# Tests for cc_preflight.py — never invokes the real cmd binary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFLIGHT="$SCRIPT_DIR/skills/fiftybox-cc-execute/scripts/cc_preflight.py"
PASS=0
FAIL=0

# PATH를 비운 채 실행하는 케이스가 있으므로 인터프리터 경로를 미리 잡아둔다.
PY="$(command -v python3)"

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

STUB_DIR="$(mktemp -d)"
FIXTURE="$STUB_DIR/models.txt"

cat > "$FIXTURE" <<'EOF'
Available models  ·  3 models

Open Source

deepseek/deepseek-v4-flash           fast hybrid-attention reasoning (default)
zai-org/glm-5.2                      powerful coding with 1M context

Anthropic

claude-sonnet-5                      best combo of speed & intelligence
EOF

cat > "$STUB_DIR/cmd" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  status)
    printf 'stub status\n'
    exit "${CC_STUB_STATUS:-0}"
    ;;
  --list-models)
    cat "$CC_STUB_MODELS"
    exit "${CC_STUB_LIST_EXIT:-0}"
    ;;
esac
exit 0
EOF
chmod +x "$STUB_DIR/cmd"

# JSON 한 필드를 뽑는 헬퍼
field() { python3 -c 'import json,sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$1"; }

# --- 1. cmd 미설치 -------------------------------------------------------
EMPTY_PATH_DIR="$(mktemp -d)"
set +e
OUT="$(PATH="$EMPTY_PATH_DIR" "$PY" "$PREFLIGHT" 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -ne 0 ]] \
    && pass "missing cmd exits non-zero" \
    || fail "missing cmd exited 0"
[[ "$(printf '%s' "$OUT" | field status)" == "not_installed" ]] \
    && pass "missing cmd reports not_installed" \
    || fail "missing cmd status wrong: $OUT"

# --- 2. 미인증 -----------------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=1 CC_STUB_MODELS="$FIXTURE" \
       python3 "$PREFLIGHT" 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -ne 0 ]] \
    && pass "unauthenticated exits non-zero" \
    || fail "unauthenticated exited 0"
[[ "$(printf '%s' "$OUT" | field status)" == "not_authenticated" ]] \
    && pass "unauthenticated reports not_authenticated" \
    || fail "unauthenticated status wrong: $OUT"

# --- 3. 정상 ------------------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=0 CC_STUB_MODELS="$FIXTURE" \
       python3 "$PREFLIGHT" \
         --require-model deepseek/deepseek-v4-flash \
         --require-model zai-org/glm-5.2 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -eq 0 ]] \
    && pass "ready path exits 0" \
    || fail "ready path exited $RC: $OUT"
[[ "$(printf '%s' "$OUT" | field status)" == "ready" ]] \
    && pass "ready path reports ready" \
    || fail "ready status wrong: $OUT"

MODELS="$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(",".join(json.loads(sys.stdin.read())["models"]))')"
[[ "$MODELS" == "deepseek/deepseek-v4-flash,zai-org/glm-5.2,claude-sonnet-5" ]] \
    && pass "model list parsed in order, headers excluded" \
    || fail "model parse wrong: $MODELS"

# --- 4. 요구 모델 누락 ---------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=0 CC_STUB_MODELS="$FIXTURE" \
       python3 "$PREFLIGHT" --require-model no/such-model 2>/dev/null)"
RC=$?
set -e
[[ "$RC" -ne 0 ]] \
    && pass "missing required model exits non-zero" \
    || fail "missing required model exited 0"
[[ "$(printf '%s' "$OUT" | field status)" == "missing_models" ]] \
    && pass "missing required model reports missing_models" \
    || fail "missing model status wrong: $OUT"
MISSING="$(printf '%s' "$OUT" | python3 -c 'import json,sys; print(",".join(json.loads(sys.stdin.read())["missingModels"]))')"
[[ "$MISSING" == "no/such-model" ]] \
    && pass "missingModels names the absent model" \
    || fail "missingModels wrong: $MISSING"

# --- 5. 목록 조회 실패 ---------------------------------------------------
set +e
OUT="$(PATH="$STUB_DIR:$PATH" CC_STUB_STATUS=0 CC_STUB_MODELS="$FIXTURE" \
       CC_STUB_LIST_EXIT=3 python3 "$PREFLIGHT" 2>/dev/null)"
RC=$?
set -e
[[ "$(printf '%s' "$OUT" | field status)" == "list_failed" ]] \
    && pass "list-models failure reports list_failed" \
    || fail "list failure status wrong: $OUT"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `chmod +x tests/test_cc_preflight.sh && bash tests/test_cc_preflight.sh`
Expected: FAIL — `cc_preflight.py` 가 없어 python3가 "can't open file" 로 죽는다

- [ ] **Step 3: cc_preflight.py 작성**

```python
#!/usr/bin/env python3
"""Check that CommandCode (`cmd`) is ready to act as an implementer.

Emits a JSON document on stdout describing installation, authentication, and
model availability. Knows nothing about orchestrate.py.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# `cmd --list-models` prints "<id><2+ spaces><description>" rows between plain
# section headers ("Open Source", "Anthropic"). Headers carry no double space,
# so requiring one is what excludes them. Ids are either "vendor/model" or a
# bare name such as "claude-sonnet-5".
MODEL_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._/-]*)\s{2,}\S")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def parse_models(text: str) -> list[str]:
    """Extract model ids from `cmd --list-models` output, preserving order."""
    models: list[str] = []
    for line in strip_ansi(text).splitlines():
        match = MODEL_LINE_RE.match(line)
        if match:
            models.append(match.group(1))
    return models


def run_cmd(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def preflight(required: list[str], timeout: int) -> dict:
    if shutil.which("cmd") is None:
        return {
            "ok": False,
            "status": "not_installed",
            "message": "CommandCode CLI가 없습니다. `npm i -g command-code`로 설치하세요.",
            "models": [],
            "missingModels": list(required),
        }

    try:
        status = run_cmd(["status"], timeout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "not_authenticated",
            "message": f"`cmd status`가 {timeout}초 안에 응답하지 않았습니다.",
            "models": [],
            "missingModels": list(required),
        }
    if status.returncode != 0:
        return {
            "ok": False,
            "status": "not_authenticated",
            # Surface the CLI's own wording so the user runs whatever login
            # command this version actually documents.
            "message": strip_ansi(status.stdout).strip(),
            "models": [],
            "missingModels": list(required),
        }

    try:
        listing = run_cmd(["--list-models"], timeout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "list_failed",
            "message": f"`cmd --list-models`가 {timeout}초 안에 응답하지 않았습니다.",
            "models": [],
            "missingModels": list(required),
        }
    if listing.returncode != 0:
        return {
            "ok": False,
            "status": "list_failed",
            "message": strip_ansi(listing.stdout).strip(),
            "models": [],
            "missingModels": list(required),
        }

    models = parse_models(listing.stdout)
    missing = [m for m in required if m not in models]
    if missing:
        return {
            "ok": False,
            "status": "missing_models",
            "message": "요구한 모델이 목록에 없습니다: " + ", ".join(missing),
            "models": models,
            "missingModels": missing,
        }

    return {
        "ok": True,
        "status": "ready",
        "message": f"CommandCode 준비 완료 — 모델 {len(models)}개.",
        "models": models,
        "missingModels": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-model",
        action="append",
        default=[],
        dest="required",
        help="이 모델이 목록에 있어야 한다 (반복 가능)",
    )
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    return emit(preflight(args.required, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `bash tests/test_cc_preflight.sh`
Expected: PASS 11건, `Results: 11 passed, 0 failed`

- [ ] **Step 5: 실제 CLI로 한 번 확인 (스텁 없이)**

Run: `python3 skills/fiftybox-cc-execute/scripts/cc_preflight.py --require-model deepseek/deepseek-v4-flash`
Expected: 로그인 전이라면 `{"ok": false, "status": "not_authenticated", ...}` 가 나오고 exit 1. `cmd`가 설치돼 있지 않은 머신이라면 `not_installed`. 어느 쪽이든 JSON 한 줄이 나와야 한다.

- [ ] **Step 6: 커밋**

```bash
git add skills/fiftybox-cc-execute/scripts/cc_preflight.py tests/test_cc_preflight.sh
git commit -m "feat(cc-execute): add CommandCode preflight check"
```

---

### Task 3: SKILL.md와 슬래시 명령

**Files:**
- Create: `skills/fiftybox-cc-execute/SKILL.md`
- Create: `commands/fiftybox-cc-execute.md`

**Interfaces:**
- Consumes: Task 1의 `--implement-agent commandcode`, Task 2의 `cc_preflight.py` JSON 계약
- Produces: `/fiftybox-cc-execute` 슬래시 명령과 스킬 본문. Task 4의 설치 배선이 이 두 파일 경로를 참조한다

이 태스크는 문서만 만든다. 실행 가능한 코드가 없으므로 자동 테스트 대신 구조 검증으로 대체한다(Step 2).

- [ ] **Step 1: `commands/fiftybox-cc-execute.md` 작성**

`commands/fiftybox-free-execute.md`와 동일한 4줄 구조를 따른다.

```markdown
---
name: fiftybox-cc-execute
description: CommandCode(cmd) 요금제로 구현하는 병렬 배치 TDD 실행 파이프라인 — Claude가 테스트를 쓰고 CommandCode가 구현하고 Claude가 리뷰한다
---

Load and follow the fiftybox-cc-execute skill instructions at `skills/fiftybox-cc-execute/SKILL.md`.

Task: $ARGUMENTS
```

- [ ] **Step 2: `skills/fiftybox-cc-execute/SKILL.md` 작성**

frontmatter는 정확히 아래와 같이 시작한다:

```markdown
---
name: fiftybox-cc-execute
description: CommandCode(cmd) 요금제로 구현하는 병렬 배치 TDD 실행 파이프라인 — Claude가 실패하는 테스트를 쓰고 CommandCode가 통과시키고 Claude가 리뷰한다. 설계가 끝난 작업의 구현·배포를 CommandCode에 넘길 때 사용한다.
---
```

본문은 `skills/fiftybox-execute/SKILL.md`를 기반으로 하되 아래를 반영한다. 스펙 문서 `docs/superpowers/specs/2026-08-07-fiftybox-cc-execute-design.md`의 "워크플로" · "실패 처리" · "안전 계약" 절을 그대로 옮겨 쓰는 것이 가장 빠르다.

반드시 포함할 것:

1. **⛔ 절대 금지 절** — Claude는 구현 파일을 직접 쓰지 않는다. 쓸 수 있는 것은 테스트 파일과 아티팩트 문서뿐이다. 예외 없다.
2. **스크립트 경로** — `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py` (`~/.claude/skills/orchestrate/...`는 존재하지 않는 경로다).
3. **호출** — `/fiftybox-cc-execute "<작업 설명>" [--model <id>]`
4. **모델 티어 표**

   | 대상 | 모델 |
   |---|---|
   | `implement` · simple | `deepseek/deepseek-v4-flash` |
   | `implement` · complex | `zai-org/glm-5.2` |
   | `deploy` | `deepseek/deepseek-v4-flash` |

   complex 판정 기준 4가지(파일 3개 이상 / 새 추상화 설계 / 동시성·에러·보안 얽힘 / 테스트 5개 초과 또는 통합 시나리오) 중 하나라도 걸리면 complex. `--model`을 주면 표를 무시하고 전 페이즈 고정.
5. **Step 0 Preflight**

   ```bash
   python3 ~/.claude/skills/fiftybox-cc-execute/scripts/cc_preflight.py \
     --require-model deepseek/deepseek-v4-flash \
     --require-model zai-org/glm-5.2
   ```

   JSON의 `status`로 분기한다. `not_installed` → `npm i -g command-code` 안내 후 중단. `not_authenticated` → `message`를 그대로 보여주고 `! cmd login` 실행을 안내한 뒤 중단(로그인은 브라우저 대화형이라 대신 못 한다). `missing_models` → `models` 목록을 보여주고 대체 모델을 받는다. `ready` → 진행.
6. **Step 1~10** — 스펙의 워크플로 절 그대로. Setup / 태스크 분해와 tier 배정 / Claude 테스트 작성(Red) / 병렬 구현(Green) / Claude 리뷰 게이트 / review-test / complete / deploy / cleanup.
7. **detached 실행 경고** — `--phase implement`를 foreground로 돌리면 Bash 10분 한도에서 파일도 로그도 없이 죽는다. 반드시 아래 형태로 돌린다:

   ```bash
   nohup python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py \
     --phase implement --task "<task>" --cwd "$(pwd)" \
     --artifact-dir "<artifactDir>" \
     --implement-agent commandcode --model "<tier 모델>" \
     --skip-verify \
     > "<artifactDir>/implement-task-N.out" 2>&1 &
   ```
8. **실패 분류 표** — 스펙의 7행 표를 그대로. 표 위에 "`orchestrate.py`는 `errorClass`를 제공하지 않는다. 로그를 읽어 이 표로만 분류하고, 표에 없는 근거로 모델을 바꾸지 않는다"를 명시한다.
9. **배치 중단 규칙** — `auth` · `window` · `credit`은 계정 단위 실패라 형제 태스크도 곧 죽는다. 하나라도 나오면 배치 전체 즉시 중단, 성공한 태스크 결과는 워크트리에 그대로 두고 보고. `model` · `max_turns` · `timeout`은 해당 태스크만 처리.
10. **Failure Report Format** — 스펙의 코드블록 그대로(분류 필드 포함).
11. **안전 계약** — 스펙의 안전 계약 절 그대로.
12. **`incomplete_commit` 경고** — Step 8이 이 이유로 실패하면 cleanup을 실행하지 않는다. cleanup이 그 작업의 유일한 사본을 지운다.

포함하지 말 것: `errorClass` / `model_unavailable` 표(이 계통 `orchestrate.py`에 구현이 없다), `cmd taste` 연동, `cmd -w/--worktree` 사용, `--output-format json`.

- [ ] **Step 3: 구조 검증**

```bash
head -4 skills/fiftybox-cc-execute/SKILL.md
grep -c "implement-agent commandcode" skills/fiftybox-cc-execute/SKILL.md
grep -n "skills/orchestrate/scripts" skills/fiftybox-cc-execute/SKILL.md || echo "OK: no bad script path"
grep -n "errorClass" skills/fiftybox-cc-execute/SKILL.md || echo "OK: no errorClass table"
```

Expected: frontmatter `name: fiftybox-cc-execute` 확인, `--implement-agent commandcode` 가 1회 이상, 잘못된 스크립트 경로 없음, `errorClass` 없음.

- [ ] **Step 4: 커밋**

```bash
git add skills/fiftybox-cc-execute/SKILL.md commands/fiftybox-cc-execute.md
git commit -m "feat(cc-execute): add skill body and slash command"
```

---

### Task 4: 설치 배선

**Files:**
- Modify: `install.sh:9` (경로 변수), `install.sh:66` 부근 (스킬 복사), `install.sh:148` 부근 (슬래시 명령 복사), `install.sh:24` 부근 (사전 확인 루프)
- Modify: `tests/test_install.sh`

**Interfaces:**
- Consumes: Task 2·3이 만든 `skills/fiftybox-cc-execute/{SKILL.md,scripts/cc_preflight.py}` 와 `commands/fiftybox-cc-execute.md`
- Produces: `$HOME/.claude/skills/fiftybox-cc-execute/` 설치본과 `$HOME/.claude/commands/fiftybox-cc-execute.md`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_install.sh`의 경로 변수 블록(현재 17-27행 부근, `FREE_EXECUTE_SKILL_DIR` 정의 옆)에 추가:

```bash
CC_EXECUTE_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-cc-execute"
```

"install.sh: expected files" 절의 기존 단언들 뒤에 추가:

```bash
[[ -f "$CC_EXECUTE_SKILL_DIR/SKILL.md" ]] \
    && pass "fiftybox-cc-execute SKILL.md installed" \
    || fail "fiftybox-cc-execute SKILL.md not installed"

[[ -f "$CC_EXECUTE_SKILL_DIR/scripts/cc_preflight.py" ]] \
    && pass "cc_preflight.py installed" \
    || fail "cc_preflight.py not installed"

[[ -f "$COMMANDS_DIR/fiftybox-cc-execute.md" ]] \
    && pass "fiftybox-cc-execute slash command installed" \
    || fail "fiftybox-cc-execute slash command not installed"
```

그리고 gitignore된 로컬 스킬이 없는 체크아웃을 검증하는 절(파일 끝의 `BARE_HOME` 블록)에 추가:

```bash
[[ -f "$BARE_HOME/.claude/skills/fiftybox-cc-execute/SKILL.md" ]] \
    && pass "fiftybox-cc-execute still installed without local-model skills" \
    || fail "fiftybox-cc-execute missing when local-model skills absent"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `bash tests/test_install.sh`
Expected: FAIL 4건 — SKILL.md / cc_preflight.py / 슬래시 명령 / bare 체크아웃

- [ ] **Step 3: install.sh 배선 추가**

(a) 경로 변수 — `FREE_EXECUTE_SKILL_DIR` 정의(9행) 바로 아래:

```bash
CC_EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-cc-execute"
```

(b) 사전 확인 루프(24행 부근) — `cmd`를 추가한다. 없어도 중단하지 않고 경고만 하는 기존 동작을 유지한다:

```bash
for bin in pi claude cmd; do
```

(c) 스킬 복사 — `fiftybox-free-execute` 블록(61-65행) 바로 뒤:

```bash
# Install fiftybox-cc-execute skill (CommandCode paid plans)
mkdir -p "$CC_EXECUTE_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-cc-execute/SKILL.md" "$CC_EXECUTE_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-cc-execute/scripts/"*.py "$CC_EXECUTE_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-cc-execute → $CC_EXECUTE_SKILL_DIR"
```

(d) 슬래시 명령 — `fiftybox-gpt-review.md` 복사 줄(147-148행) 뒤. 이 블록은 파일마다 명시적 `cp` 한 줄씩이고 디렉터리 통째 복사가 아니므로 새 줄이 반드시 필요하다:

```bash
cp "$SCRIPT_DIR/commands/fiftybox-cc-execute.md" "$COMMANDS_DIR/fiftybox-cc-execute.md"
log "Installed commands/fiftybox-cc-execute.md → $COMMANDS_DIR/fiftybox-cc-execute.md"
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run: `bash tests/test_install.sh`
Expected: `Results: N passed, 0 failed` (기존 통과 건수 + 4)

- [ ] **Step 5: 전체 테스트 재실행**

```bash
bash tests/test_install.sh
bash tests/test_cc_agent.sh
bash tests/test_cc_preflight.sh
```

Expected: 세 스크립트 모두 `0 failed` 로 exit 0

- [ ] **Step 6: 커밋**

```bash
git add install.sh tests/test_install.sh
git commit -m "chore(install): wire up fiftybox-cc-execute skill and command"
```

---

## 수동 E2E (계획 실행 후, 사용자와 함께)

자동 테스트는 `cmd`를 호출하지 않는다. 아래는 사람이 한 번 돌려야 한다.

1. `! cmd login` — 브라우저 로그인. 에이전트가 대신 할 수 없다
2. `bash install.sh` — 실제 홈 디렉터리에 설치
3. Claude Code 재시작 후 `/fiftybox-cc-execute "<작은 실제 작업>" --model deepseek/deepseek-v4-flash`
4. 확인할 것: preflight가 `ready`를 반환하는가, 워크트리가 생기는가, `cmd`가 실제로 파일을 만드는가, 테스트가 통과하는가, 커밋이 남는가, cleanup이 도는가
5. 실측할 것: 실행 1회당 크레딧 소모, `--implementation-timeout` 기본값으로 충분한지, 5시간 롤링 한도까지 몇 회 돌 수 있는지

여기서 얻은 수치로 SKILL.md의 tier 표와 타임아웃 권고를 조정한다.
