#!/usr/bin/env bash
# Skills are slash commands. Matching ~/.claude/commands wrappers duplicate
# every fiftybox entry in Claude Code's skill / slash-command list.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }

TRACKED_WRAPPERS=(
    fiftybox-orchestration
    fiftybox-plans
    fiftybox-execute
    fiftybox-local
    fiftybox-gpt-review
)

for cmd in "${TRACKED_WRAPPERS[@]}"; do
    if [[ -f "$SCRIPT_DIR/commands/$cmd.md" ]]; then
        fail "commands/$cmd.md still exists (duplicates the skill slash command)"
    else
        pass "commands/$cmd.md is not shipped"
    fi
done

if grep -E 'cp "\$SCRIPT_DIR/commands/fiftybox-' "$SCRIPT_DIR/install.sh" >/dev/null; then
    fail "install.sh still copies fiftybox command wrappers"
else
    pass "install.sh does not copy fiftybox command wrappers"
fi

# Re-running install must remove leftover wrappers from older installs.
INSTALL_ROOT="$(mktemp -d)"
trap 'rm -rf "$INSTALL_ROOT"' EXIT
export HOME="$INSTALL_ROOT"
COMMANDS_DIR="$INSTALL_ROOT/.claude/commands"
mkdir -p "$COMMANDS_DIR"
for cmd in "${TRACKED_WRAPPERS[@]}" fiftybox-local-execute fiftybox-cc-execute fiftybox-free-execute; do
    printf 'legacy wrapper\n' > "$COMMANDS_DIR/$cmd.md"
done
# Compatibility alias with a different name must survive.
printf 'alias\n' > "$COMMANDS_DIR/orchestrate.md"

bash "$SCRIPT_DIR/install.sh" >/dev/null 2>&1

for cmd in "${TRACKED_WRAPPERS[@]}" fiftybox-local-execute fiftybox-cc-execute fiftybox-free-execute; do
    if [[ -e "$COMMANDS_DIR/$cmd.md" ]]; then
        fail "install.sh left leftover wrapper $cmd.md"
    else
        pass "install.sh removed leftover wrapper $cmd.md"
    fi
done

if [[ -f "$COMMANDS_DIR/orchestrate.md" ]]; then
    pass "install.sh keeps /orchestrate alias (different name)"
else
    fail "install.sh deleted the /orchestrate alias"
fi

if [[ -f "$INSTALL_ROOT/.claude/skills/fiftybox-orchestration/SKILL.md" ]]; then
    pass "skills still install after wrapper cleanup"
else
    fail "wrapper cleanup broke skill install"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
