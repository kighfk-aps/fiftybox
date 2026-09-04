#!/usr/bin/env bash
# Install the fiftybox-pi skill into the Pi CLI agent home.
#
#   ./install-pi.sh                 # install into ~/.pi/agent
#   PI_AGENT_HOME=/tmp/x ./install-pi.sh   # sandbox install (tests)
#
# Idempotent: re-running never clobbers an existing config or agents file.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$REPO_DIR/skills/fiftybox-pi"
PI_AGENT_HOME="${PI_AGENT_HOME:-$HOME/.pi/agent}"
AGENT_CONFIG_DIR="$PI_AGENT_HOME/fiftybox-pi-agents"

pass() { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n' "$1" >&2; }
warn() { printf '  ! %s\n' "$1" >&2; }

echo "fiftybox-pi install → $PI_AGENT_HOME"

# --- preflight -------------------------------------------------------------
command -v pi >/dev/null 2>&1 && pass "pi CLI found: $(command -v pi)" \
  || { fail "pi CLI not on PATH (https://pi.ai/cli)"; exit 1; }
command -v python3 >/dev/null 2>&1 && pass "python3 found" \
  || { fail "python3 not on PATH"; exit 1; }
ORCHESTRATE="${FIFTYBOX_ORCHESTRATE:-$HOME/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py}"
if [ -f "$ORCHESTRATE" ]; then
  pass "orchestrate.py engine: $ORCHESTRATE"
else
  warn "orchestrate.py not found at $ORCHESTRATE — set FIFTYBOX_ORCHESTRATE; phases setup/implement will fail until fixed"
fi

# --- skill symlink ----------------------------------------------------------
mkdir -p "$PI_AGENT_HOME/skills"
TARGET="$PI_AGENT_HOME/skills/fiftybox-pi"
if [ -L "$TARGET" ]; then
  pass "skill symlink already present"
elif [ -e "$TARGET" ]; then
  warn "$TARGET exists and is not a symlink — leaving it untouched"
else
  ln -s "$SKILL_SRC" "$TARGET"
  pass "skill symlinked: $TARGET → $SKILL_SRC"
fi

# --- default config (never overwrite) ---------------------------------------
CONFIG_TARGET="$PI_AGENT_HOME/fiftybox-config.json"
if [ -f "$CONFIG_TARGET" ]; then
  warn "config already exists — keeping it"
elif python3 "$SKILL_SRC/scripts/fiftybox_config.py" --path "$CONFIG_TARGET" --init >/dev/null; then
  pass "default config written: $CONFIG_TARGET"
else
  warn "could not write default config at $CONFIG_TARGET"
fi

# --- agent registry (piqwen for the Modal lane) ------------------------------
mkdir -p "$AGENT_CONFIG_DIR"
python3 - "$AGENT_CONFIG_DIR/config.json" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
piqwen = {"cmd": ["pi", "--print", "--provider", "modal-qwen38",
                  "--model", "qwen3.8-27b-q4_k_m", "--thinking", "off",
                  "--no-session", "--no-context-files",
                  "--append-system-prompt", "{prompt}", "{task}"]}
config = {}
if path.exists():
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
agents = config.get("agents", {})
if "piqwen" in agents:
    print(f"  ✓ piqwen already registered in {path}")
    sys.exit(0)
config.setdefault("explore_agent", "pi")
config.setdefault("implement_agent", "pi")
agents["piqwen"] = piqwen
config["agents"] = agents
path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
print(f"  ✓ agent registry written: {path} (piqwen)")
PY

# --- smoke the catalog -------------------------------------------------------
if pi --list-models zai-coding >/dev/null 2>&1; then
  pass "provider catalog reachable (zai-coding)"
else
  warn "pi --list-models zai-coding failed — check ~/.pi/agent/models.json before running the skill"
fi

echo
echo "Done. Run inside any pi session:"
echo "  /skill:fiftybox-pi \"<task description>\""
echo "Config: $PI_AGENT_HOME/fiftybox-config.json (edit lanes/models freely)"
