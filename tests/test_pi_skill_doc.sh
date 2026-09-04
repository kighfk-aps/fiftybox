#!/usr/bin/env bash
# Tests for the fiftybox-pi SKILL.md contract.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-pi/SKILL.md"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }
lacks() { if [[ -f "$1" ]] && ! grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

# --- invocation surface ----------------------------------------------------
has "$SKILL" "name: fiftybox-pi" "SKILL.md declares the fiftybox-pi skill name"
has "$SKILL" "disable-model-invocation: true" "SKILL.md requires explicit /skill invocation"
has "$SKILL" "/skill:fiftybox-pi" "SKILL.md documents the slash command"
has "$SKILL" "Session Preflight" "SKILL.md mandates the session model preflight"
has "$SKILL" "PI_PROVIDER" "SKILL.md checks the injected session provider"
has "$SKILL" "Lane Preflight" "SKILL.md mandates the lane preflight"
has "$SKILL" "tool-call smoke" "SKILL.md gates implement on the tool-call smoke"

# --- tiered routing contract -----------------------------------------------
has "$SKILL" "zai-coding/glm-5.3" "SKILL.md routes top tier to GLM-5.3"
has "$SKILL" "xai-auth/grok-4.6" "SKILL.md routes top tier to Grok-4.6"
has "$SKILL" "openrouter-free" "SKILL.md includes the OpenRouter free lane"
has "$SKILL" "nvidia-nim" "SKILL.md includes the NVIDIA NIM lane"
has "$SKILL" "modal-qwen38" "SKILL.md includes the Modal Qwen lane"
has "$SKILL" "Never fall back to a paid provider" "SKILL.md forbids paid fallback for implementation"
has "$SKILL" "Emergency Stop" "SKILL.md defines the all-lanes-down user choice"
has "$SKILL" "lane-health.json" "SKILL.md persists per-run lane health"

# --- dispatch contract -------------------------------------------------------
has "$SKILL" "--implement-agent pi --provider <provider> --model <model>" "SKILL.md dispatches with an explicit (agent, provider, model) triple"
has "$SKILL" "--implement-agent piqwen" "SKILL.md routes the Modal lane through piqwen"
has "$SKILL" "nohup" "SKILL.md dispatches implementation detached"
has "$SKILL" "EXIT_CODE=" "SKILL.md polls the EXIT_CODE sentinel"
has "$SKILL" "--agent-config" "SKILL.md points orchestrate.py at the pi-native agent registry"
lacks "$SKILL" "--auto-resume" "SKILL.md drops the Claude-only auto-resume watcher"
has "$SKILL" "--skip-codex-review" "SKILL.md keeps the objective Phase 6 gate"

# --- safety contract ---------------------------------------------------------
has "$SKILL" "Never force push" "SKILL.md forbids force push"
has "$SKILL" "Never push before Phase 7" "SKILL.md gates push on completion"
has "$SKILL" "Do not modify the test files" "SKILL.md keeps children off test files"
has "$SKILL" "verify Red" "SKILL.md verifies tests fail before implementation"

# --- references present ------------------------------------------------------
for ref in failure-classification phase-contract routing; do
  has "$SCRIPT_DIR/skills/fiftybox-pi/references/$ref.md" "fiftybox-pi" \
      "references/$ref.md exists and is scoped to fiftybox-pi"
done

echo "test_pi_skill_doc: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
