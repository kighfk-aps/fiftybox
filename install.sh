#!/usr/bin/env bash
set -euo pipefail

SKILLS_DIR="$HOME/.claude/skills/fiftybox-orchestration"
PLANS_SKILL_DIR="$HOME/.claude/skills/fiftybox-plans"
LOCAL_SKILL_DIR="$HOME/.claude/skills/fiftybox-local"
EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-execute"
LOCAL_EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-local-execute"
CODEX_SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
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
    warn "  $bin not found — install it before running /fiftybox-orchestration"
  fi
done
echo ""

# Install skill
mkdir -p "$SKILLS_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-orchestration/SKILL.md" "$SKILLS_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-orchestration/scripts/"*.py "$SKILLS_DIR/scripts/"
log "Installed skills/fiftybox-orchestration/ → $SKILLS_DIR"

# Install adapters
if [[ -d "$SCRIPT_DIR/skills/fiftybox-orchestration/adapters" ]]; then
  mkdir -p "$SKILLS_DIR/adapters"
  cp "$SCRIPT_DIR/skills/fiftybox-orchestration/adapters/"* "$SKILLS_DIR/adapters/"
  chmod +x "$SKILLS_DIR/adapters/"*.sh 2>/dev/null || true
  log "Installed adapters/ → $SKILLS_DIR/adapters"
fi

# Install config example
cp "$SCRIPT_DIR/skills/fiftybox-orchestration/config.example.json" "$SKILLS_DIR/config.example.json"
log "Config example → $SKILLS_DIR/config.example.json"

# Install configure.sh so plugin users can run it without the repo
cp "$SCRIPT_DIR/configure.sh" "$SKILLS_DIR/configure.sh"
chmod +x "$SKILLS_DIR/configure.sh"
log "Installed configure.sh → $SKILLS_DIR/configure.sh"

# Install fiftybox-execute skill
mkdir -p "$EXECUTE_SKILL_DIR"
cp "$SCRIPT_DIR/skills/fiftybox-execute/SKILL.md" "$EXECUTE_SKILL_DIR/SKILL.md"
log "Installed Claude skill fiftybox-execute → $EXECUTE_SKILL_DIR"

# Install fiftybox-local-execute skill
mkdir -p "$LOCAL_EXECUTE_SKILL_DIR"
cp "$SCRIPT_DIR/skills/fiftybox-local-execute/SKILL.md" "$LOCAL_EXECUTE_SKILL_DIR/SKILL.md"
log "Installed Claude skill fiftybox-local-execute → $LOCAL_EXECUTE_SKILL_DIR"

# Install planning skill for Claude slash commands and Codex-global use
mkdir -p "$PLANS_SKILL_DIR"
cp "$SCRIPT_DIR/skills/fiftybox-plans/SKILL.md" "$PLANS_SKILL_DIR/SKILL.md"
log "Installed Claude skill fiftybox-plans → $PLANS_SKILL_DIR"
mkdir -p "$CODEX_SKILLS_DIR/fiftybox-plans"
cp "$SCRIPT_DIR/skills/fiftybox-plans/SKILL.md" "$CODEX_SKILLS_DIR/fiftybox-plans/SKILL.md"
log "Installed Codex skill fiftybox-plans → $CODEX_SKILLS_DIR/fiftybox-plans"

# Install local-model orchestration variant
mkdir -p "$LOCAL_SKILL_DIR"
cp "$SCRIPT_DIR/skills/fiftybox-local/SKILL.md" "$LOCAL_SKILL_DIR/SKILL.md"
if [[ -d "$SCRIPT_DIR/skills/fiftybox-local/scripts" ]]; then
  mkdir -p "$LOCAL_SKILL_DIR/scripts"
  cp "$SCRIPT_DIR/skills/fiftybox-local/scripts/"*.sh "$LOCAL_SKILL_DIR/scripts/"
  chmod +x "$LOCAL_SKILL_DIR/scripts/"*.sh
fi
log "Installed Claude skill fiftybox-local → $LOCAL_SKILL_DIR"

# Install slash command
mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/commands/fiftybox-orchestration.md" "$COMMANDS_DIR/fiftybox-orchestration.md"
log "Installed commands/fiftybox-orchestration.md → $COMMANDS_DIR/fiftybox-orchestration.md"
cp "$SCRIPT_DIR/commands/fiftybox-plans.md" "$COMMANDS_DIR/fiftybox-plans.md"
log "Installed commands/fiftybox-plans.md → $COMMANDS_DIR/fiftybox-plans.md"
cp "$SCRIPT_DIR/commands/fiftybox-local.md" "$COMMANDS_DIR/fiftybox-local.md"
log "Installed commands/fiftybox-local.md → $COMMANDS_DIR/fiftybox-local.md"

echo ""
log "To configure agents: $SKILLS_DIR/configure.sh"
echo ""
log "Done! Restart Claude Code, then try:"
log "  /fiftybox-orchestration \"add login feature\""
log "  /fiftybox-plans \"add login feature\""
