#!/usr/bin/env bash
# Smoke test: verifies qwen35-9b vLLM speculative decoding wiring.
# Local checks: file content. Remote checks: live endpoint.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SELECT_SCRIPT="$REPO_DIR/skills/fiftybox-local/scripts/select_remote_model.sh"
STOP_SCRIPT="$REPO_DIR/skills/fiftybox-local/scripts/stop_remote_model.sh"
SKILL_MD="$REPO_DIR/skills/fiftybox-local/SKILL.md"
REMOTE="<퇴역-GPU서버>"
PASS=0
FAIL=0

ok()   { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

echo "=== select_remote_model.sh: 9b routes to port 8001 ==="

if grep -q '9spec-start' "$SELECT_SCRIPT"; then
  ok "select_remote_model.sh 9b case calls 9spec-start"
else
  fail "select_remote_model.sh does not call 9spec-start"
fi

if grep -q '8001' "$SELECT_SCRIPT"; then
  ok "select_remote_model.sh references port 8001"
else
  fail "select_remote_model.sh does not reference port 8001 (still using 11434?)"
fi

if ! grep -q '11434' "$SELECT_SCRIPT"; then
  ok "select_remote_model.sh no longer references port 11434"
else
  fail "select_remote_model.sh still references port 11434 in 9b case"
fi

echo ""
echo "=== stop_remote_model.sh: 9b calls 9spec-stop ==="

if grep -q '9spec-stop' "$STOP_SCRIPT"; then
  ok "stop_remote_model.sh 9b case calls 9spec-stop"
else
  fail "stop_remote_model.sh does not call 9spec-stop"
fi

echo ""
echo "=== SKILL.md: port 8001 reference ==="

if grep -q '8001' "$SKILL_MD"; then
  ok "SKILL.md references port 8001"
else
  fail "SKILL.md does not reference port 8001"
fi

if grep -q 'vllm-qwen35-9b-spec' "$SKILL_MD"; then
  ok "SKILL.md references container name vllm-qwen35-9b-spec"
else
  fail "SKILL.md does not reference vllm-qwen35-9b-spec"
fi

echo ""
echo "=== Remote: GGUF file present ==="
if ssh "$REMOTE" "test -f /home/tanpapa/models/qwen35-9b-q4km.gguf && echo ok" 2>/dev/null \
   | grep -q ok; then
  ok "GGUF exists at /home/tanpapa/models/qwen35-9b-q4km.gguf"
else
  fail "GGUF not found — run Task 2 (docker cp from Ollama volume)"
fi

echo ""
echo "=== Remote: vllm-qwen35-9b-spec endpoint (requires container running) ==="
if ssh "$REMOTE" "curl -fsS --max-time 8 http://127.0.0.1:8001/v1/models" 2>/dev/null \
   | grep -q '"id":"current"'; then
  ok "vllm-qwen35-9b-spec responds at :8001 with id=current"
else
  fail "vllm-qwen35-9b-spec not reachable at :8001 — run Tasks 3-5 then start the container"
fi

echo ""
echo "=== Remote: 9spec-start alias defined ==="
if ssh "$REMOTE" "zsh -i -c 'type 9spec-start'" 2>/dev/null | grep -q 'alias\|9spec-start'; then
  ok "9spec-start alias defined on remote server"
else
  fail "9spec-start alias not found — run Task 5 (add aliases to ~/.zshrc)"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
