#!/usr/bin/env bash
set -euo pipefail

SKILLS_DIR="$HOME/.claude/skills/fiftybox-orchestration"
PLANS_SKILL_DIR="$HOME/.claude/skills/fiftybox-plans"
LOCAL_SKILL_DIR="$HOME/.claude/skills/fiftybox-local"
EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-execute"
GPT_REVIEW_SKILL_DIR="$HOME/.claude/skills/fiftybox-gpt-review"
LOCAL_EXECUTE_SKILL_DIR="$HOME/.claude/skills/fiftybox-local-execute"
CODEX_SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
CODEX_LOCAL_SKILL_DIR="$CODEX_SKILLS_DIR/fiftybox-local"
CODEX_LOCAL_EXECUTE_SKILL_DIR="$CODEX_SKILLS_DIR/fiftybox-local-execute"
COMMANDS_DIR="$HOME/.claude/commands"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '[fiftybox] %s\n' "$*"; }
warn() { printf '[fiftybox] WARNING: %s\n' "$*" >&2; }

log "Installing fiftybox orchestrate harness..."
echo ""

# Check prerequisites — warn but don't abort so partial installs still work
for bin in pi claude cmd; do
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
mkdir -p "$EXECUTE_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-execute/SKILL.md" "$EXECUTE_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-execute/scripts/"*.py "$EXECUTE_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-execute → $EXECUTE_SKILL_DIR"

# Install fiftybox-gpt-review skill (Codex/GPT design & plan review)
mkdir -p "$GPT_REVIEW_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-gpt-review/SKILL.md" "$GPT_REVIEW_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-gpt-review/scripts/"*.py "$GPT_REVIEW_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-gpt-review → $GPT_REVIEW_SKILL_DIR"

# Install fiftybox-local-execute skill
# skills/fiftybox-local*/ is gitignored, so a clean clone or an orchestrate
# worktree will not have it. Skip rather than abort the whole install.
if [[ -f "$SCRIPT_DIR/skills/fiftybox-local-execute/SKILL.md" ]]; then
  mkdir -p "$LOCAL_EXECUTE_SKILL_DIR"
  cp "$SCRIPT_DIR/skills/fiftybox-local-execute/SKILL.md" "$LOCAL_EXECUTE_SKILL_DIR/SKILL.md"
  if [[ -d "$SCRIPT_DIR/skills/fiftybox-local-execute/agents" ]]; then
    mkdir -p "$LOCAL_EXECUTE_SKILL_DIR/agents"
    cp "$SCRIPT_DIR/skills/fiftybox-local-execute/agents/"* "$LOCAL_EXECUTE_SKILL_DIR/agents/"
  fi
  log "Installed Claude skill fiftybox-local-execute → $LOCAL_EXECUTE_SKILL_DIR"

  # Install fiftybox-local-execute skill for Codex
  mkdir -p "$CODEX_LOCAL_EXECUTE_SKILL_DIR"
  cp "$SCRIPT_DIR/skills/fiftybox-local-execute/SKILL.md" "$CODEX_LOCAL_EXECUTE_SKILL_DIR/SKILL.md"
  if [[ -d "$SCRIPT_DIR/skills/fiftybox-local-execute/agents" ]]; then
    mkdir -p "$CODEX_LOCAL_EXECUTE_SKILL_DIR/agents"
    cp "$SCRIPT_DIR/skills/fiftybox-local-execute/agents/"* "$CODEX_LOCAL_EXECUTE_SKILL_DIR/agents/"
  fi
  log "Installed Codex skill fiftybox-local-execute → $CODEX_LOCAL_EXECUTE_SKILL_DIR"
else
  log "Skipped fiftybox-local-execute (not present in this checkout)"
fi

# Install planning skill for Claude slash commands and Codex-global use
mkdir -p "$PLANS_SKILL_DIR"
cp "$SCRIPT_DIR/skills/fiftybox-plans/SKILL.md" "$PLANS_SKILL_DIR/SKILL.md"
log "Installed Claude skill fiftybox-plans → $PLANS_SKILL_DIR"
mkdir -p "$CODEX_SKILLS_DIR/fiftybox-plans"
cp "$SCRIPT_DIR/skills/fiftybox-plans/SKILL.md" "$CODEX_SKILLS_DIR/fiftybox-plans/SKILL.md"
log "Installed Codex skill fiftybox-plans → $CODEX_SKILLS_DIR/fiftybox-plans"

# Install fiftybox-local (tracked; local/free execute)
mkdir -p "$LOCAL_SKILL_DIR/scripts"
cp "$SCRIPT_DIR/skills/fiftybox-local/SKILL.md" "$LOCAL_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-local/scripts/discover_free_models.py" "$LOCAL_SKILL_DIR/scripts/"
log "Installed Claude skill fiftybox-local → $LOCAL_SKILL_DIR"

# Claude Code already exposes each installed skill as /skill-name. Matching
# ~/.claude/commands/*.md wrappers made every fiftybox skill appear twice in
# the skill / slash-command list. Do not install wrappers; remove leftovers.
mkdir -p "$COMMANDS_DIR"
for cmd in fiftybox-orchestration fiftybox-plans fiftybox-execute \
           fiftybox-local fiftybox-gpt-review fiftybox-local-execute \
           fiftybox-cc-execute fiftybox-free-execute; do
  wrapper="$COMMANDS_DIR/$cmd.md"
  if [[ -f "$wrapper" ]]; then
    rm -f "$wrapper"
    log "Removed duplicate slash-command wrapper → $wrapper"
  fi
done
log "Slash commands come from skills; no ~/.claude/commands wrappers installed"

echo ""
log "To configure agents: $SKILLS_DIR/configure.sh"
echo ""
log "Done! Restart Claude Code, then try:"
log "  /fiftybox-orchestration \"add login feature\""
log "  /fiftybox-plans \"add login feature\""
