#!/usr/bin/env bash
# Offline tests for pi_runner.py: stream parsing, failure classification,
# command shape. No network, no pi invocation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$SCRIPT_DIR/skills/fiftybox-pi/scripts/pi_runner.py"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

# 1. selftest battery
if python3 "$RUNNER" --selftest | tail -1 | grep -q "PASS"; then
  pass "runner selftest battery"
else
  fail "runner selftest battery"
fi

# 2. fixture classification through the module API
FIXTURES="$(RUNNER_PATH="$RUNNER" python3 - <<'PY'
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("pi_runner", os.environ["RUNNER_PATH"])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
out = {
    "model_400": mod.classify_error('400: {"code":"1214","message":"modelCode: does not exist"}'),
    "auth_410": mod.classify_error("410 status code (no body)"),
    "busy_429": mod.classify_error('429: Rate limit exceeded'),
    "window": mod.classify_error("prompt is too long: 200000 tokens > 131072 context"),
    "credit": mod.classify_error("402 insufficient credits"),
    "unknown": mod.classify_error("something entirely novel"),
    "scope_auth": mod.scope_of("auth"),
    "scope_busy": mod.scope_of("model_busy"),
    "scope_timeout": mod.scope_of("timeout"),
}
print(json.dumps(out))
PY
)"

expect() { echo "$FIXTURES" | grep -q "\"$1\": \"$2\"" && pass "$3" || fail "$3 (got: $(echo "$FIXTURES" | grep -o "\"$1\": \"[^\"]*\""))"; }
expect model_400 model "400 modelCode -> model scope"
expect auth_410 auth "410 no body -> auth (lane closure)"
expect busy_429 model_busy "429 -> model_busy (in-lane swap)"
expect window window "context overflow -> window"
expect credit credit "402 -> credit"
expect unknown unknown "novel error -> unknown (task scope)"
expect scope_auth account "auth scope is account"
expect scope_busy model "model_busy scope is model"
expect scope_timeout task "timeout scope is task"

# 3. timeout env contract: config exposes runner timeouts
CONFIG_DEFAULTS="$(CONFIG_PATH="$(dirname "$RUNNER")/fiftybox_config.py" python3 - <<'PY'
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("fiftybox_config", os.environ["CONFIG_PATH"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps({"smoke": mod.DEFAULTS["timeouts"]["smoke"],
                  "implement": mod.DEFAULTS["timeouts"]["implement"]}))
PY
)"
echo "$CONFIG_DEFAULTS" | grep -q '"smoke": 120' && pass "smoke timeout default 120s" \
  || fail "smoke timeout default: $CONFIG_DEFAULTS"
echo "$CONFIG_DEFAULTS" | grep -q '"implement": 1800' && pass "implement timeout default 1800s" \
  || fail "implement timeout default: $CONFIG_DEFAULTS"

# 4. CLI surface: unknown subcommand usage exits non-zero, selftest exits 0
python3 "$RUNNER" >/dev/null 2>&1 && fail "bare invocation must fail" \
  || pass "bare invocation rejected"
python3 "$RUNNER" --selftest >/dev/null 2>&1 && pass "--selftest exits 0" \
  || fail "--selftest exit code"

echo "test_pi_runner: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
