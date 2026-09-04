#!/usr/bin/env bash
# Validates the machine-level Pi backend registration for OpenRouter.
# Checks ~/.pi/agent/models.json (outside the repo) — run on the user's machine.
set -euo pipefail
MODELS_JSON="$HOME/.pi/agent/models.json"
PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

[[ -f "$MODELS_JSON" ]] && pass "models.json exists" || fail "models.json missing"

jq -e '.providers["openrouter-free"].baseUrl == "https://openrouter.ai/api/v1"' "$MODELS_JSON" >/dev/null 2>&1 \
    && pass "openrouter-free baseUrl points at OpenRouter" \
    || fail "openrouter baseUrl wrong or missing"

jq -e '.providers["openrouter-free"].apiKey | contains("pi-openrouter-api-key")' "$MODELS_JSON" >/dev/null 2>&1 \
    && pass "openrouter-free apiKey reads the Keychain entry" \
    || fail "openrouter-free apiKey does not reference pi-openrouter-api-key"

COUNT="$(jq '.providers["openrouter-free"].models | length' "$MODELS_JSON" 2>/dev/null || echo 0)"
[[ "$COUNT" -ge 5 ]] && pass "openrouter-free registers at least 5 models ($COUNT)" \
    || fail "openrouter-free registers fewer than 5 models ($COUNT)"

PAID="$(jq '[.providers["openrouter-free"].models[].id | select(endswith(":free") | not)] | length' "$MODELS_JSON" 2>/dev/null || echo 999)"
[[ "$PAID" -eq 0 ]] && pass "openrouter-free registers zero non-free models" \
    || fail "openrouter-free registers $PAID non-free (paid) models"

GLM="$(jq '[.providers["openrouter-free"].models[].id | select(. == "z-ai/glm-5.2:free")] | length' "$MODELS_JSON" 2>/dev/null || echo 0)"
[[ "$GLM" -eq 1 ]] && pass "z-ai/glm-5.2:free is registered under openrouter-free" \
    || fail "z-ai/glm-5.2:free is not registered under openrouter-free"

ZEROCOST="$(jq '[.providers["openrouter-free"].models[].cost // {} | select(.input != 0 or .output != 0)] | length' "$MODELS_JSON" 2>/dev/null || echo 999)"
[[ "$ZEROCOST" -eq 0 ]] && pass "all registered models carry zero cost" \
    || fail "$ZEROCOST registered openrouter-free models have nonzero cost"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
