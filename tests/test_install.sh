#!/usr/bin/env bash
# Tests for install.sh and configure.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

# ---------------------------------------------------------------------------
# Setup: fake install destination
# ---------------------------------------------------------------------------
INSTALL_ROOT="$(mktemp -d)"
export HOME="$INSTALL_ROOT"
SKILLS_DIR="$INSTALL_ROOT/.claude/skills/orchestrate"
PLANS_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-plans"
LOCAL_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-local"
CODEX_SKILLS_DIR="$INSTALL_ROOT/.codex/skills"
COMMANDS_DIR="$INSTALL_ROOT/.claude/commands"

# Run install.sh
bash "$SCRIPT_DIR/install.sh" >/dev/null 2>&1

# ---------------------------------------------------------------------------
# install.sh: expected files
# ---------------------------------------------------------------------------

[[ -f "$SKILLS_DIR/SKILL.md" ]] \
    && pass "SKILL.md installed" \
    || fail "SKILL.md not installed"

[[ -f "$SKILLS_DIR/scripts/orchestrate.py" ]] \
    && pass "orchestrate.py installed" \
    || fail "orchestrate.py not installed"

[[ -f "$SKILLS_DIR/scripts/orchestrate_watcher.py" ]] \
    && pass "orchestrate_watcher.py installed" \
    || fail "orchestrate_watcher.py not installed"

[[ -f "$SKILLS_DIR/adapters/cursor.sh" ]] \
    && pass "cursor.sh installed" \
    || fail "cursor.sh not installed"

[[ -x "$SKILLS_DIR/adapters/cursor.sh" ]] \
    && pass "cursor.sh is executable" \
    || fail "cursor.sh not executable"

[[ -f "$SKILLS_DIR/config.example.json" ]] \
    && pass "config.example.json installed" \
    || fail "config.example.json not installed"

[[ -f "$SKILLS_DIR/configure.sh" ]] \
    && pass "configure.sh installed" \
    || fail "configure.sh not installed"

[[ -x "$SKILLS_DIR/configure.sh" ]] \
    && pass "configure.sh is executable" \
    || fail "configure.sh not executable"

[[ -f "$COMMANDS_DIR/fiftybox-orchestration.md" ]] \
    && pass "fiftybox-orchestration.md installed" \
    || fail "fiftybox-orchestration.md not installed"

[[ -f "$COMMANDS_DIR/fiftybox-plans.md" ]] \
    && pass "fiftybox-plans.md command installed" \
    || fail "fiftybox-plans.md command not installed"

[[ -f "$CODEX_SKILLS_DIR/fiftybox-plans/SKILL.md" ]] \
    && pass "Codex fiftybox-plans skill installed" \
    || fail "Codex fiftybox-plans skill not installed"

[[ -f "$PLANS_SKILL_DIR/SKILL.md" ]] \
    && pass "Claude fiftybox-plans skill installed" \
    || fail "Claude fiftybox-plans skill not installed"

[[ -f "$LOCAL_SKILL_DIR/SKILL.md" ]] \
    && pass "Claude fiftybox-local skill installed" \
    || fail "Claude fiftybox-local skill not installed"

[[ -x "$LOCAL_SKILL_DIR/scripts/select_remote_model.sh" ]] \
    && pass "fiftybox-local select_remote_model.sh installed executable" \
    || fail "fiftybox-local select_remote_model.sh missing or not executable"

[[ -x "$LOCAL_SKILL_DIR/scripts/stop_remote_model.sh" ]] \
    && pass "fiftybox-local stop_remote_model.sh installed executable" \
    || fail "fiftybox-local stop_remote_model.sh missing or not executable"

# ---------------------------------------------------------------------------
# configure.sh: sets agents
# ---------------------------------------------------------------------------

CONFIG="$SKILLS_DIR/config.json"
# Simulate user entering "gemini" for explore, "aider" for implement
echo -e "gemini\naider" | bash "$SKILLS_DIR/configure.sh" >/dev/null 2>&1

[[ -f "$CONFIG" ]] \
    && pass "configure.sh created config.json" \
    || fail "configure.sh did not create config.json"

explore=$(python3 -c "import json; print(json.load(open('$CONFIG'))['explore_agent'])" 2>/dev/null || echo "")
implement=$(python3 -c "import json; print(json.load(open('$CONFIG'))['implement_agent'])" 2>/dev/null || echo "")

[[ "$explore" == "gemini" ]] \
    && pass "explore_agent set to gemini" \
    || fail "explore_agent expected 'gemini', got '$explore'"

[[ "$implement" == "aider" ]] \
    && pass "implement_agent set to aider" \
    || fail "implement_agent expected 'aider', got '$implement'"

# ---------------------------------------------------------------------------
# configure.sh: injection safety — shell metacharacters in env vars
# ---------------------------------------------------------------------------

echo -e "pi\npi" | bash "$SKILLS_DIR/configure.sh" >/dev/null 2>&1
# Overwrite with a value that would be dangerous if interpolated in a heredoc
CONFIG_PATH="$CONFIG" python3 -c "
import json, os
path = os.environ['CONFIG_PATH']
cfg = json.loads(open(path).read())
cfg['explore_agent'] = 'pi'
cfg['implement_agent'] = 'pi'
open(path, 'w').write(json.dumps(cfg, indent=2) + '\n')
"
echo -e "pi\npi" | bash "$SKILLS_DIR/configure.sh" >/dev/null 2>&1
explore2=$(python3 -c "import json; print(json.load(open('$CONFIG'))['explore_agent'])" 2>/dev/null || echo "")
[[ "$explore2" == "pi" ]] \
    && pass "configure.sh injection-safe: explore_agent saved correctly" \
    || fail "configure.sh injection safety: explore_agent expected 'pi', got '$explore2'"

# ---------------------------------------------------------------------------
# configure.sh: pressing Enter keeps current value
# ---------------------------------------------------------------------------

echo -e "opencode\ngemini" | bash "$SKILLS_DIR/configure.sh" >/dev/null 2>&1
# Now press Enter (empty) for both — should keep current values
echo -e "\n" | bash "$SKILLS_DIR/configure.sh" >/dev/null 2>&1
explore3=$(python3 -c "import json; print(json.load(open('$CONFIG'))['explore_agent'])" 2>/dev/null || echo "")
implement3=$(python3 -c "import json; print(json.load(open('$CONFIG'))['implement_agent'])" 2>/dev/null || echo "")
[[ "$explore3" == "opencode" ]] \
    && pass "configure.sh: Enter keeps current explore_agent" \
    || fail "configure.sh: Enter should keep 'opencode', got '$explore3'"
[[ "$implement3" == "gemini" ]] \
    && pass "configure.sh: Enter keeps current implement_agent" \
    || fail "configure.sh: Enter should keep 'gemini', got '$implement3'"

# ---------------------------------------------------------------------------
# cursor.sh: --model passed as separate argument
# ---------------------------------------------------------------------------

CURSOR_SH="$SKILLS_DIR/adapters/cursor.sh"
# Parse the script to verify --model is not word-split (i.e., uses if/else or separate args)
if grep -q 'cursor chat --model "\$MODEL" --stdin' "$CURSOR_SH" \
   || grep -q "cursor chat --model \"\$MODEL\" --stdin" "$CURSOR_SH"; then
    pass "cursor.sh passes --model as separate argument"
else
    fail "cursor.sh may word-split --model"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
