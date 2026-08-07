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
elif what == "cli-route":
    # The checks above do not exercise resolve_agent_config, which is how a
    # real run reaches this adapter. Drive it with the same Namespace shape
    # argparse produces for `--implement-agent commandcode`.
    import argparse
    ns = argparse.Namespace(implement_agent="commandcode")
    cfg = mod.resolve_agent_config(Path("/nonexistent-skill-dir"), ns)
    print(cfg["implement_agent"])
elif what == "cli-accepts-flag":
    import subprocess
    # argparse must accept the flag on the real CLI surface. --help exits 0
    # and lists the option; an unknown option would exit 2.
    out = subprocess.run(
        [sys.executable, os.environ["ORCH_PATH"], "--help"],
        capture_output=True, text=True, timeout=60,
    )
    print("yes" if "--implement-agent" in out.stdout else "no")
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

# 어댑터가 없으면 build_agent_cmd가 예외를 던진다. 그래도 나머지 단언과 요약이
# 나오도록 빈 배열로 대체한다.
ARGV="$(run_py argv 2>/dev/null || echo '[]')"

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

# 4. --implement-agent 오버라이드가 실제로 commandcode로 해석된다
[[ "$(run_py cli-route 2>/dev/null || echo FAILED)" == "commandcode" ]] \
    && pass "--implement-agent override resolves to commandcode" \
    || fail "resolve_agent_config did not honour --implement-agent commandcode"

# 5. CLI가 --implement-agent 플래그를 실제로 받아들인다
[[ "$(run_py cli-accepts-flag 2>/dev/null || echo no)" == "yes" ]] \
    && pass "orchestrate.py CLI exposes --implement-agent" \
    || fail "orchestrate.py CLI does not expose --implement-agent"

# 6. 알 수 없는 에이전트는 기존 에러 메시지로 실패한다
UNKNOWN="$(run_py unknown-agent 2>/dev/null || echo 'RUN_FAILED')"
[[ "$UNKNOWN" == *"Unknown agent 'no-such-agent'"* ]] \
    && pass "unknown agent still raises the existing error" \
    || fail "unknown agent error changed: $UNKNOWN"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
