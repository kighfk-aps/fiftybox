# Fiftybox Multi-Agent Backend Selection Design

**Date:** 2026-06-01  
**Status:** Approved  
**Repo:** `/Users/tanpapa/Desktop/develop-a/fiftybox/`

## What Are We Building?

Make the explore and implement agents in fiftybox independently configurable. Instead of Pi CLI being hardcoded, users set a default agent once in `config.json` and can extend with any CLI tool via JSON templates or shell adapter scripts.

---

## Goals

- Users can independently choose explore/implement agents from: Pi, OpenCode, Qwen, Aider, Gemini, Cursor
- Users can add custom agents without touching Python
- Zero config needed for existing Pi CLI users (backward compatible)
- Simple UX: `./configure.sh` or direct JSON edit

---

## Architecture

### Approach: JSON command templates + shell adapter fallback

- Simple agents: defined as `cmd` arrays with `{prompt}`, `{task}`, `{model}`, `{provider}`, `{adapters_dir}` variables in `config.json`
- Complex agents (Cursor): `cmd[0]` points to a `.sh` adapter script; orchestrate.py detects and runs via bash
- `BUILTIN_AGENTS` constant in `orchestrate.py` is the fallback when no `config.json` exists

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `skills/orchestrate/scripts/orchestrate.py` | Modify | Add `load_agent_config()`, `build_agent_cmd()`, replace 4 hardcoded Pi calls |
| `skills/orchestrate/adapters/cursor.sh` | Create | Shell adapter for Cursor CLI |
| `skills/orchestrate/config.example.json` | Create | Copy-and-edit template for users |
| `configure.sh` | Create | Interactive agent picker |
| `install.sh` | Modify | Also copy `adapters/` to `~/.claude/skills/orchestrate/adapters/` |
| `README.md` | Modify | Add "Agent Configuration" section |

---

## Section 1: config.json Schema

**Location:** `~/.claude/skills/orchestrate/config.json`

```json
{
  "explore_agent": "gemini",
  "implement_agent": "aider",
  "agents": {
    "pi": {
      "cmd": ["pi", "--print", "--provider", "{provider}", "--model", "{model}",
              "--no-session", "--no-context-files", "--append-system-prompt", "{prompt}", "{task}"]
    },
    "opencode": {
      "cmd": ["opencode", "run", "--model", "{model}", "--print", "{prompt}\n{task}"]
    },
    "aider": {
      "cmd": ["aider", "--message", "{prompt}\n{task}", "--yes-always", "--no-git"]
    },
    "gemini": {
      "cmd": ["gemini", "-p", "{prompt}\n{task}"]
    },
    "qwen": {
      "cmd": ["qwen-code", "--model", "{model}", "--message", "{prompt}\n{task}"]
    },
    "cursor": {
      "cmd": ["{adapters_dir}/cursor.sh", "{prompt}", "{task}", "{model}"]
    }
  }
}
```

**Substitution variables:**

| Variable | Value |
|----------|-------|
| `{prompt}` | System/context prompt for the phase |
| `{task}` | User's task description |
| `{model}` | Model name (from `--model` arg) |
| `{provider}` | Provider name (from `--provider` arg, Pi-specific) |
| `{adapters_dir}` | Absolute path to `~/.claude/skills/orchestrate/adapters/` |

**Fallback:** If `config.json` absent → use `BUILTIN_AGENTS` with `explore_agent: "pi"`, `implement_agent: "pi"`.

---

## Section 2: orchestrate.py Changes

### New constants

```python
BUILTIN_AGENTS: dict[str, dict] = {
    "pi":       {"cmd": ["pi", "--print", "--provider", "{provider}", "--model", "{model}",
                         "--no-session", "--no-context-files",
                         "--append-system-prompt", "{prompt}", "{task}"]},
    "opencode": {"cmd": ["opencode", "run", "--model", "{model}", "--print", "{prompt}\n{task}"]},
    "aider":    {"cmd": ["aider", "--message", "{prompt}\n{task}", "--yes-always", "--no-git"]},
    "gemini":   {"cmd": ["gemini", "-p", "{prompt}\n{task}"]},
    "qwen":     {"cmd": ["qwen-code", "--model", "{model}", "--message", "{prompt}\n{task}"]},
    "cursor":   {"cmd": ["{adapters_dir}/cursor.sh", "{prompt}", "{task}", "{model}"]},
}
```

### New functions

```python
def load_agent_config(skill_dir: Path) -> dict:
    """Load config.json; fall back to Pi defaults if absent."""
    config_path = skill_dir / "config.json"
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        # Merge user agents over builtins so builtins are always available
        merged_agents = {**BUILTIN_AGENTS, **raw.get("agents", {})}
        return {**raw, "agents": merged_agents}
    return {"explore_agent": "pi", "implement_agent": "pi", "agents": BUILTIN_AGENTS}


def build_agent_cmd(
    agent_name: str,
    config: dict,
    *,
    prompt: str,
    task: str,
    model: str,
    provider: str,
    adapters_dir: Path,
) -> list[str]:
    """Resolve template variables in an agent cmd array."""
    if agent_name not in config["agents"]:
        raise ValueError(f"Unknown agent '{agent_name}'. Add it to config.json.")
    variables = {
        "prompt": prompt,
        "task": task,
        "model": model,
        "provider": provider,
        "adapters_dir": str(adapters_dir),
    }
    raw_cmd = config["agents"][agent_name]["cmd"]
    return [token.format(**variables) for token in raw_cmd]
```

### Phases modified

`phase_explore()`, `phase_implement()`, `phase_pi_complete()`, `phase_pi_deploy()` — each replaces (note: `phase_pi_complete` and `phase_pi_deploy` keep their names for now but now use `implement_agent` instead of Pi CLI):

```python
cmd = ["pi", "--print", "--provider", args.provider, "--model", args.model, ...]
```

with:

```python
skill_dir = Path.home() / ".claude" / "skills" / "orchestrate"
agent_config = load_agent_config(skill_dir)
adapters_dir = skill_dir / "adapters"
agent_name = agent_config["explore_agent"]   # or "implement_agent"
cmd = build_agent_cmd(agent_name, agent_config, prompt=system_prompt, task=args.task,
                      model=args.explore_model, provider=args.provider,
                      adapters_dir=adapters_dir)
```

If `cmd[0]` ends with `.sh`, prepend `["bash"]`.

### Startup validation (setup phase)

```python
for role in ("explore_agent", "implement_agent"):
    name = agent_config[role]
    bin_path = agent_config["agents"][name]["cmd"][0]
    if bin_path.endswith(".sh"):
        if not Path(bin_path.format(adapters_dir=str(adapters_dir))).exists():
            warn(f"{role} adapter script not found: {bin_path}")
    elif not shutil.which(bin_path):
        warn(f"{role} agent binary '{bin_path}' not found — install it before running /orchestrate")
```

---

## Section 3: Adapters

**`skills/orchestrate/adapters/cursor.sh`:**

```bash
#!/usr/bin/env bash
# Normalized interface: cursor.sh "<prompt>" "<task>" "<model>"
# Cursor CLI does not support --message; uses positional input via stdin pipe.
set -euo pipefail
PROMPT="$1"
TASK="$2"
MODEL="${3:-}"
printf '%s\n%s' "$PROMPT" "$TASK" | cursor chat ${MODEL:+--model "$MODEL"} --stdin
```

**`skills/orchestrate/config.example.json`** — copy of the full schema above, with comments explaining each field.

---

## Section 4: configure.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
CONFIG="$HOME/.claude/skills/orchestrate/config.json"
AVAILABLE="pi opencode aider gemini qwen cursor"

current_explore=$(python3 -c "import json,sys; d=json.load(open('$CONFIG')) if __import__('os').path.exists('$CONFIG') else {}; print(d.get('explore_agent','pi'))" 2>/dev/null)
current_implement=$(python3 -c "import json,sys; d=json.load(open('$CONFIG')) if __import__('os').path.exists('$CONFIG') else {}; print(d.get('implement_agent','pi'))" 2>/dev/null)

echo "Available agents: $AVAILABLE"
read -rp "Explore agent [current: $current_explore]: " explore
read -rp "Implement agent [current: $current_implement]: " implement

explore="${explore:-$current_explore}"
implement="${implement:-$current_implement}"

# Merge into existing config or create new
python3 - <<PYEOF
import json, os, pathlib
path = pathlib.Path("$CONFIG")
cfg = json.loads(path.read_text()) if path.exists() else {}
cfg["explore_agent"] = "$explore"
cfg["implement_agent"] = "$implement"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"[fiftybox] Saved → {path}")
PYEOF
```

---

## install.sh Changes

Add after existing skill copy:

```bash
# Install adapters
if [[ -d "$SCRIPT_DIR/skills/orchestrate/adapters" ]]; then
    mkdir -p "$SKILLS_DIR/adapters"
    cp "$SCRIPT_DIR/skills/orchestrate/adapters/"* "$SKILLS_DIR/adapters/"
    chmod +x "$SKILLS_DIR/adapters/"*.sh 2>/dev/null || true
    log "Installed adapters/ → $SKILLS_DIR/adapters"
fi

# Install config example
cp "$SCRIPT_DIR/skills/orchestrate/config.example.json" "$SKILLS_DIR/config.example.json"
log "Config example → $SKILLS_DIR/config.example.json"

log ""
log "To configure agents: ./configure.sh"
```

---

## README Addition

```markdown
## Agent Configuration

By default, fiftybox uses Pi CLI for both exploration and implementation.
To switch agents, run:

\`\`\`bash
./configure.sh
\`\`\`

Or edit `~/.claude/skills/orchestrate/config.json` directly.

Supported built-in agents: `pi`, `opencode`, `aider`, `gemini`, `qwen`, `cursor`

### Adding a custom agent

Add an entry to the `agents` object in `config.json`:

\`\`\`json
{
  "implement_agent": "my-agent",
  "agents": {
    "my-agent": { "cmd": ["/path/to/my-agent.sh", "{prompt}", "{task}"] }
  }
}
\`\`\`

Variables: `{prompt}`, `{task}`, `{model}`, `{provider}`, `{adapters_dir}`
```

---

## Out of Scope

- Per-run agent override (`/orchestrate --agent aider "task"`) — not in this spec
- Agent output format normalization — each agent's stdout is treated as-is
- Model selection per agent — users set `--model` at the `orchestrate.py` level; agents that don't use `{model}` simply ignore it
