#!/usr/bin/env bash
# Structure tests for the fiftybox-config skill
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-config/SKILL.md"
LIB="$SCRIPT_DIR/skills/fiftybox-config/scripts/config_lib.py"
TUI="$SCRIPT_DIR/skills/fiftybox-config/scripts/config_tui.py"
DEFAULT_CFG="$SCRIPT_DIR/skills/fiftybox-config/config/default-config.json"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

[[ -f "$LIB" ]] && pass "config_lib.py exists" || fail "config_lib.py missing"
[[ -f "$TUI" ]] && pass "config_tui.py exists" || fail "config_tui.py missing"
[[ -f "$DEFAULT_CFG" ]] && pass "default-config.json exists" || fail "default-config.json missing"

has "$SKILL" "name: fiftybox-config" "SKILL.md frontmatter declares its name"
has "$SKILL" "~/.claude/fiftybox-config.json" "SKILL.md documents the config file path"
has "$SKILL" "config_tui.py" "SKILL.md references the TUI script"
has "$SKILL" "! python3" "SKILL.md tells the user to run the TUI themselves via !"
has "$SKILL" "lane_priority" "SKILL.md documents the lane_priority field"

python3 -c "import json; json.load(open('$DEFAULT_CFG'))" \
    && pass "default-config.json is valid JSON" \
    || fail "default-config.json is not valid JSON"

for key in codex-write pi grok commandcode opencode; do
  python3 -c "
import json, sys
d = json.load(open('$DEFAULT_CFG'))
sys.exit(0 if '$key' in d['providers'] else 1)
" \
      && pass "default-config.json includes provider $key" \
      || fail "default-config.json missing provider $key"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
