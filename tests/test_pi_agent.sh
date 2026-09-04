#!/usr/bin/env bash
# Tests for the pi/piqwen agent entries and the fiftybox-pi engine hooks
# (--agent-config, FIFTYBOX_CHILD_CMD_OVERRIDE) in orchestrate.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCH="$SCRIPT_DIR/skills/fiftybox-orchestration/scripts/orchestrate.py"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

run_py() {
    ORCH_PATH="$ORCH" python3 - "$@" <<'PY'
import importlib.util, json, os, sys, tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("orch", os.environ["ORCH_PATH"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

what = sys.argv[1]
if what == "pi-argv":
    cfg = {"agents": dict(mod.BUILTIN_AGENTS)}
    argv = mod.build_agent_cmd(
        "pi", cfg, prompt="PROMPT", task="TASK",
        model="glm-5.3-flash", provider="zai-coding",
        adapters_dir=Path("/tmp"),
    )
    print(json.dumps(argv))
elif what == "fake-child":
    os.environ["FIFTYBOX_CHILD_CMD_OVERRIDE"] = "/tmp/fake-child"
    try:
        cfg = {"agents": dict(mod.BUILTIN_AGENTS)}
        argv = mod.build_agent_cmd(
            "pi", cfg, prompt="SYS", task="do it",
            model="m", provider="p", adapters_dir=Path("/tmp"))
        print(json.dumps({"argv": argv, "prompt": os.environ.get("FIFTYBOX_CHILD_PROMPT"),
                          "model": os.environ.get("FIFTYBOX_CHILD_MODEL")}))
    finally:
        del os.environ["FIFTYBOX_CHILD_CMD_OVERRIDE"]
        os.environ.pop("FIFTYBOX_CHILD_MODEL", None)
elif what == "agent-config-load":
    with tempfile.TemporaryDirectory() as td:
        custom = Path(td)
        (custom / "config.json").write_text(
            '{"implement_agent": "piqwen", "agents":'
            ' {"piqwen": {"cmd": ["fake", "{task}"]}}}')
        cfg = mod.load_agent_config(custom)
        print(json.dumps({"implement": cfg["implement_agent"],
                          "has_builtin_pi": "pi" in cfg["agents"]}))
elif what == "help-lists-agent-config":
    import subprocess
    out = subprocess.run(
        [sys.executable, os.environ["ORCH_PATH"], "--help"],
        capture_output=True, text=True, timeout=60)
    print("yes" if "--agent-config" in out.stdout else "no")
PY
}

PI_ARGV="$(run_py pi-argv)"
echo "$PI_ARGV" | grep -q '"pi", "--print", "--provider", "zai-coding"' \
  && pass "pi agent builds provider/model argv" \
  || fail "pi agent argv: $PI_ARGV"
echo "$PI_ARGV" | grep -q -- "--no-session" \
  && pass "pi agent runs no-session" || fail "pi agent missing --no-session"
echo "$PI_ARGV" | grep -q -- "--no-context-files" \
  && pass "pi agent runs without context files" || fail "pi agent missing --no-context-files"
echo "$PI_ARGV" | grep -q -- "--append-system-prompt" \
  && pass "pi agent receives the system prompt" || fail "pi agent missing system prompt"
echo "$PI_ARGV" | grep -q '"--mode"' \
  && fail "pi agent must stay on --print (runner adds --mode json)" \
  || pass "pi agent stays on --print"

FAKE="$(run_py fake-child)"
echo "$FAKE" | grep -q '"/tmp/fake-child", "do it"' \
  && pass "FIFTYBOX_CHILD_CMD_OVERRIDE replaces the child" || fail "fake child argv: $FAKE"
echo "$FAKE" | grep -q '"prompt": "SYS"' \
  && pass "fake child receives the system prompt via env" || fail "fake child env prompt"
echo "$FAKE" | grep -q '"model": "m"' \
  && pass "fake child receives the model via env" || fail "fake child env model"

AGENT_LOAD="$(run_py agent-config-load)"
echo "$AGENT_LOAD" | grep -q '"implement": "piqwen"' \
  && pass "load_agent_config reads a --agent-config directory" || fail "agent config load: $AGENT_LOAD"
echo "$AGENT_LOAD" | grep -q '"has_builtin_pi": true' \
  && pass "custom registry merges builtin agents" || fail "builtin merge"

HELP="$(run_py help-lists-agent-config)"
[ "$HELP" = "yes" ] && pass "--help documents --agent-config" \
  || fail "--agent-config missing from --help"

# piqwen must come from the pi-native registry, not the engine defaults
grep -q 'piqwen' "$SCRIPT_DIR/skills/fiftybox-pi/references/routing.md" \
  && pass "routing.md defines the piqwen agent" || fail "piqwen not defined"

echo "test_pi_agent: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
