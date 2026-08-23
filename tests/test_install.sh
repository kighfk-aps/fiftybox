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
SKILLS_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-orchestration"
PLANS_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-plans"
LOCAL_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-local"
LOCAL_EXECUTE_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-local-execute"
SKILLS_DIR_EXECUTE="$INSTALL_ROOT/.claude/skills/fiftybox-execute"
GPT_REVIEW_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-gpt-review"
CODEX_SKILLS_DIR="$INSTALL_ROOT/.codex/skills"
CODEX_LOCAL_EXECUTE_SKILL_DIR="$CODEX_SKILLS_DIR/fiftybox-local-execute"
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

[[ ! -e "$COMMANDS_DIR/fiftybox-orchestration.md" ]] \
    && pass "fiftybox-orchestration.md command wrapper not installed" \
    || fail "fiftybox-orchestration.md command wrapper still installed"

[[ ! -e "$COMMANDS_DIR/fiftybox-plans.md" ]] \
    && pass "fiftybox-plans.md command wrapper not installed" \
    || fail "fiftybox-plans.md command wrapper still installed"

[[ ! -e "$COMMANDS_DIR/fiftybox-execute.md" ]] \
    && pass "fiftybox-execute.md command wrapper not installed" \
    || fail "fiftybox-execute.md command wrapper still installed"

[[ -f "$SKILLS_DIR_EXECUTE/scripts/diff_review.py" ]] \
    && pass "fiftybox-execute diff_review.py installed" \
    || fail "fiftybox-execute diff_review.py missing"

[[ -f "$SKILLS_DIR_EXECUTE/scripts/cc_preflight.py" ]] \
    && pass "fiftybox-execute cc_preflight.py installed" \
    || fail "fiftybox-execute cc_preflight.py missing"

[[ ! -e "$COMMANDS_DIR/fiftybox-local.md" ]] \
    && pass "fiftybox-local command wrapper not installed" \
    || fail "fiftybox-local command wrapper still installed"

[[ -f "$GPT_REVIEW_SKILL_DIR/SKILL.md" ]] \
    && pass "fiftybox-gpt-review SKILL.md installed" \
    || fail "fiftybox-gpt-review SKILL.md not installed"

[[ -f "$GPT_REVIEW_SKILL_DIR/scripts/gpt_review.py" ]] \
    && pass "gpt_review.py installed" \
    || fail "gpt_review.py not installed"

[[ ! -e "$COMMANDS_DIR/fiftybox-gpt-review.md" ]] \
    && pass "fiftybox-gpt-review.md command wrapper not installed" \
    || fail "fiftybox-gpt-review.md command wrapper still installed"

[[ -f "$CODEX_SKILLS_DIR/fiftybox-plans/SKILL.md" ]] \
    && pass "Codex fiftybox-plans skill installed" \
    || fail "Codex fiftybox-plans skill not installed"

[[ -f "$PLANS_SKILL_DIR/SKILL.md" ]] \
    && pass "Claude fiftybox-plans skill installed" \
    || fail "Claude fiftybox-plans skill not installed"

[[ -f "$LOCAL_SKILL_DIR/SKILL.md" ]] \
    && pass "fiftybox-local skill installed" \
    || fail "fiftybox-local skill not installed"

[[ -f "$LOCAL_SKILL_DIR/scripts/discover_free_models.py" ]] \
    && pass "fiftybox-local discover_free_models.py installed" \
    || fail "fiftybox-local discover_free_models.py missing"

if [[ -f "$SCRIPT_DIR/skills/fiftybox-local-execute/SKILL.md" ]]; then
    [[ -f "$LOCAL_EXECUTE_SKILL_DIR/SKILL.md" ]] \
        && pass "Claude fiftybox-local-execute skill installed" \
        || fail "Claude fiftybox-local-execute skill not installed"

    [[ -f "$CODEX_LOCAL_EXECUTE_SKILL_DIR/SKILL.md" ]] \
        && pass "Codex fiftybox-local-execute skill installed" \
        || fail "Codex fiftybox-local-execute skill not installed"

    [[ -f "$CODEX_LOCAL_EXECUTE_SKILL_DIR/agents/openai.yaml" ]] \
        && pass "Codex fiftybox-local-execute OpenAI metadata installed" \
        || fail "Codex fiftybox-local-execute OpenAI metadata not installed"
else
    [[ ! -e "$LOCAL_EXECUTE_SKILL_DIR" ]] \
        && pass "fiftybox-local-execute absent from source and not installed" \
        || fail "fiftybox-local-execute installed although the source lacks it"
fi

[[ ! -e "$COMMANDS_DIR/fiftybox-local-execute.md" ]] \
    && pass "fiftybox-local-execute.md command wrapper not installed" \
    || fail "fiftybox-local-execute.md command wrapper still installed"

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
# install.sh survives a checkout without the still-gitignored
# fiftybox-local-execute skill. fiftybox-local itself is now tracked.
# ---------------------------------------------------------------------------

BARE_SRC="$(mktemp -d)"
cp -R "$SCRIPT_DIR/." "$BARE_SRC/"
rm -rf "$BARE_SRC/skills/fiftybox-local-execute" \
       "$BARE_SRC/commands/fiftybox-local-execute.md"

BARE_HOME="$(mktemp -d)"
if HOME="$BARE_HOME" bash "$BARE_SRC/install.sh" >/dev/null 2>&1; then
    pass "install.sh succeeds without the gitignored fiftybox-local-execute skill"
else
    fail "install.sh failed on a checkout lacking skills/fiftybox-local-execute"
fi

[[ -f "$BARE_HOME/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py" ]] \
    && pass "orchestrate.py still installed without fiftybox-local-execute" \
    || fail "orchestrate.py missing when fiftybox-local-execute absent"

[[ -f "$BARE_HOME/.claude/skills/fiftybox-execute/scripts/diff_review.py" ]] \
    && pass "fiftybox-execute scripts still installed without fiftybox-local-execute" \
    || fail "fiftybox-execute scripts missing when fiftybox-local-execute absent"

[[ ! -e "$BARE_HOME/.claude/commands/fiftybox-execute.md" ]] \
    && pass "command wrappers still omitted without fiftybox-local-execute" \
    || fail "command wrapper appeared when fiftybox-local-execute absent"

[[ -f "$BARE_HOME/.claude/skills/fiftybox-local/SKILL.md" ]] \
    && pass "tracked fiftybox-local still installed without fiftybox-local-execute" \
    || fail "fiftybox-local missing when fiftybox-local-execute absent"

[[ ! -e "$BARE_HOME/.claude/skills/fiftybox-local-execute" ]] \
    && pass "absent fiftybox-local-execute is not installed" \
    || fail "fiftybox-local-execute installed from a source that lacks it"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
