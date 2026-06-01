#!/usr/bin/env bash
set -euo pipefail
CONFIG="$HOME/.claude/skills/orchestrate/config.json"
BUILTIN_AGENTS="pi opencode aider gemini qwen cursor"

current_explore=$(CONFIG="$CONFIG" python3 -c "
import json, os, sys
p = os.environ.get('CONFIG', '')
try:
    d = json.loads(open(p).read()) if p and os.path.exists(p) else {}
    print(d.get('explore_agent', 'pi'))
except Exception:
    print('pi')
" 2>/dev/null || echo "pi")

current_implement=$(CONFIG="$CONFIG" python3 -c "
import json, os, sys
p = os.environ.get('CONFIG', '')
try:
    d = json.loads(open(p).read()) if p and os.path.exists(p) else {}
    print(d.get('implement_agent', 'pi'))
except Exception:
    print('pi')
" 2>/dev/null || echo "pi")

echo "Available agents: $BUILTIN_AGENTS"
read -rp "Explore agent [current: $current_explore]: " explore
read -rp "Implement agent [current: $current_implement]: " implement

explore="${explore:-$current_explore}"
implement="${implement:-$current_implement}"

# Validate: accept builtin names or the current custom value (allows preserving non-builtin agents)
for role_val in "$explore" "$implement"; do
    is_valid=0
    for builtin in $BUILTIN_AGENTS; do
        [[ "$role_val" == "$builtin" ]] && is_valid=1 && break
    done
    [[ "$role_val" == "$current_explore" || "$role_val" == "$current_implement" ]] && is_valid=1
    if [[ "$is_valid" -eq 0 ]]; then
        echo "Unknown agent '$role_val'. Available: $BUILTIN_AGENTS" >&2
        echo "To use a custom agent, add it to $CONFIG manually." >&2
        exit 1
    fi
done

CONFIG="$CONFIG" EXPLORE="$explore" IMPLEMENT="$implement" python3 - <<'PYEOF'
import json, pathlib, os
path = pathlib.Path(os.environ["CONFIG"])
try:
    cfg = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(cfg, dict):
        cfg = {}
except (json.JSONDecodeError, OSError):
    cfg = {}
cfg["explore_agent"] = os.environ["EXPLORE"]
cfg["implement_agent"] = os.environ["IMPLEMENT"]
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"[fiftybox] Saved → {path}")
PYEOF
