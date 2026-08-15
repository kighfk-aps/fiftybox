#!/usr/bin/env bash
# Tests for the grok agent entry in orchestrate.py
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
    print("yes" if "grok" in mod.BUILTIN_AGENTS else "no")
elif what == "argv":
    cfg = {"agents": dict(mod.BUILTIN_AGENTS)}
    argv = mod.build_agent_cmd(
        "grok", cfg,
        prompt="PROMPT", task="TASK", model="grok-4.6",
        provider="SHOULD_NOT_APPEAR", adapters_dir=Path("/tmp"),
    )
    print(json.dumps(argv))
elif what == "cli-route":
    import argparse
    ns = argparse.Namespace(implement_agent="grok")
    cfg = mod.resolve_agent_config(Path("/nonexistent-skill-dir"), ns)
    print(cfg["implement_agent"])
PY
}

[[ "$(run_py has-agent)" == "yes" ]] \
    && pass "grok agent registered in BUILTIN_AGENTS" \
    || fail "grok agent missing from BUILTIN_AGENTS"

ARGV="$(run_py argv 2>/dev/null || echo '[]')"
EXPECTED='["grok", "-p", "PROMPT\nTASK", "--model", "grok-4.6", "--permission-mode", "bypassPermissions", "--output-format", "json"]'
NORMALISED="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$ARGV")"
EXPECTED_NORM="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1])))' "$EXPECTED")"
[[ "$NORMALISED" == "$EXPECTED_NORM" ]] \
    && pass "grok argv matches the specified flag set" \
    || fail "grok argv mismatch: $ARGV"

[[ "$ARGV" != *SHOULD_NOT_APPEAR* ]] \
    && pass "provider value not passed to grok" \
    || fail "provider value leaked into grok argv: $ARGV"

[[ "$(run_py cli-route 2>/dev/null || echo FAILED)" == "grok" ]] \
    && pass "--implement-agent override resolves to grok" \
    || fail "resolve_agent_config did not honour --implement-agent grok"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
