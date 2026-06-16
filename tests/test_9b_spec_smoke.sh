#!/usr/bin/env bash
# Smoke test: verifies 9b explore phase token budget fix is applied.
# Checks that SKILL.md uses increased token budgets (빈응답 방지).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SELECT_SCRIPT="$REPO_DIR/skills/fiftybox-local/scripts/select_remote_model.sh"
STOP_SCRIPT="$REPO_DIR/skills/fiftybox-local/scripts/stop_remote_model.sh"
SKILL_MD="$REPO_DIR/skills/fiftybox-local/SKILL.md"
PASS=0
FAIL=0

ok()   { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

echo "=== select_remote_model.sh: 9b routes to Ollama (11434) ==="

if grep -q '9start' "$SELECT_SCRIPT" && ! grep -q '9spec-start' "$SELECT_SCRIPT"; then
  ok "select_remote_model.sh 9b case calls 9start (Ollama)"
else
  fail "select_remote_model.sh 9b case does not call 9start"
fi

if grep -q '11434' "$SELECT_SCRIPT"; then
  ok "select_remote_model.sh references port 11434"
else
  fail "select_remote_model.sh does not reference port 11434"
fi

echo ""
echo "=== stop_remote_model.sh: 9b calls 9stop ==="

if grep -q '9stop' "$STOP_SCRIPT" && ! grep -q '9spec-stop' "$STOP_SCRIPT"; then
  ok "stop_remote_model.sh 9b case calls 9stop (Ollama)"
else
  fail "stop_remote_model.sh does not call 9stop"
fi

echo ""
echo "=== SKILL.md: increased token budgets ==="

check_budget() {
  local key="$1" expected="$2"
  if grep -q "${key}=\"${expected}\"" "$SKILL_MD"; then
    ok "SKILL.md ${key}=${expected}"
  else
    actual=$(grep "$key" "$SKILL_MD" | grep -o '"[0-9]*"' | tr -d '"' || echo "not found")
    fail "SKILL.md ${key} expected=${expected} got=${actual}"
  fi
}

check_budget "QWEN_SUMMARY_FILE_BATCH_MAX_TOKENS" "3600"
check_budget "QWEN_SUMMARY_SINGLE_FILE_MAX_TOKENS" "1024"
check_budget "QWEN_SUMMARY_MODULE_MAX_TOKENS" "1500"
check_budget "QWEN_SUMMARY_FINAL_MAX_TOKENS" "2400"
check_budget "QWEN_SUMMARY_MAX_CHARS_PER_FILE" "1000"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
