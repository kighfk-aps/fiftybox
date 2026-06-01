#!/usr/bin/env bash
set -euo pipefail

SKILLS_DIR="$HOME/.claude/skills/orchestrate"
COMMANDS_DIR="$HOME/.claude/commands"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '[fiftybox] %s\n' "$*"; }
warn() { printf '[fiftybox] WARNING: %s\n' "$*" >&2; }

log "Installing fiftybox orchestrate harness..."
echo ""

# Check prerequisites — warn but don't abort so partial installs still work
for bin in pi codex claude; do
  if command -v "$bin" &>/dev/null; then
    log "  ✓ $bin"
  else
    warn "  $bin not found — install it before running /orchestrate"
  fi
done
echo ""

# Install skill
mkdir -p "$SKILLS_DIR/scripts"
cp "$SCRIPT_DIR/skills/orchestrate/SKILL.md" "$SKILLS_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/orchestrate/scripts/"*.py "$SKILLS_DIR/scripts/"
log "Installed skills/orchestrate/ → $SKILLS_DIR"

# Install slash command
mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/commands/orchestrate.md" "$COMMANDS_DIR/orchestrate.md"
log "Installed commands/orchestrate.md → $COMMANDS_DIR/orchestrate.md"

echo ""
log "Done! Restart Claude Code, then try:"
log "  /orchestrate \"add login feature\""
