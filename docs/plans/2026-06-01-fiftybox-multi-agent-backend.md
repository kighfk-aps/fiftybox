# Fiftybox Multi-Agent Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Context:** The base repo setup (first spec) is fully implemented — `package.json`, `README.md`, `AGENTS.md`, `install.sh`, `skills/orchestrate/`, `commands/orchestrate.md`, and GitHub remote all exist. This plan implements the second spec only.

**Goal:** Replace the four hardcoded Pi CLI calls in `orchestrate.py` with a template-based agent dispatch system so users can independently choose explore/implement agents (Pi, OpenCode, Aider, Gemini, Qwen, Cursor, or custom) via a `config.json`.

**Architecture:** Add `BUILTIN_AGENTS` constant + `load_agent_config()` + `build_agent_cmd()` helpers to `orchestrate.py`. The four phases (`explore`, `implement`, `pi_complete`, `pi_deploy`) call `build_agent_cmd()` instead of hardcoding Pi CLI. A `config.json` at `~/.claude/skills/orchestrate/config.json` overrides agent selection; absent config falls back to Pi. Shell adapters (`adapters/cursor.sh`) handle CLIs with non-standard interfaces. `configure.sh` provides an interactive picker.

**Tech Stack:** Python 3 (orchestrate.py), bash (configure.sh, adapters/cursor.sh, install.sh), JSON (config.example.json), pytest (tests)

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `skills/orchestrate/scripts/orchestrate.py` | Modify | Add `BUILTIN_AGENTS`, `load_agent_config()`, `build_agent_cmd()`, startup validation, replace 4 Pi CLI cmd blocks |
| `skills/orchestrate/tests/test_agent_config.py` | Create | Tests for the new config loader and command builder |
| `skills/orchestrate/adapters/cursor.sh` | Create | Shell adapter normalizing Cursor CLI to the common interface |
| `skills/orchestrate/config.example.json` | Create | Copy-and-edit config template |
| `configure.sh` | Create | Interactive agent picker |
| `install.sh` | Modify | Copy `adapters/` and `config.example.json` on install |
| `README.md` | Modify | Add "Agent Configuration" section |

---

## Task 1: Add `BUILTIN_AGENTS`, `load_agent_config()`, `build_agent_cmd()` with tests

**Files:**
- Modify: `skills/orchestrate/scripts/orchestrate.py:66` (after `OMX_TEAM_CLI`)
- Create: `skills/orchestrate/tests/test_agent_config.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/tests/test_agent_config.py`:

```python
import pytest
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import orchestrate


def test_load_agent_config_defaults_to_pi_when_no_config(tmp_path):
    config = orchestrate.load_agent_config(tmp_path)
    assert config["explore_agent"] == "pi"
    assert config["implement_agent"] == "pi"
    assert "pi" in config["agents"]


def test_load_agent_config_reads_json(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"explore_agent": "aider", "implement_agent": "gemini", "agents": {}})
    )
    config = orchestrate.load_agent_config(tmp_path)
    assert config["explore_agent"] == "aider"
    assert config["implement_agent"] == "gemini"


def test_load_agent_config_merges_user_agents_over_builtins(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({
            "explore_agent": "custom",
            "agents": {"custom": {"cmd": ["mytool", "{task}"]}}
        })
    )
    config = orchestrate.load_agent_config(tmp_path)
    assert "custom" in config["agents"]
    assert "pi" in config["agents"]  # builtin still accessible


def test_load_agent_config_invalid_json_raises(tmp_path):
    (tmp_path / "config.json").write_text("not json {{{")
    with pytest.raises(Exception):
        orchestrate.load_agent_config(tmp_path)


def test_build_agent_cmd_resolves_pi_variables(tmp_path):
    config = orchestrate.load_agent_config(tmp_path)
    cmd = orchestrate.build_agent_cmd(
        "pi", config,
        prompt="explore the repo", task="add feature",
        model="deepseek-v4-flash", provider="openrouter",
        adapters_dir=tmp_path / "adapters",
    )
    assert "pi" in cmd
    assert "deepseek-v4-flash" in cmd
    assert "openrouter" in cmd
    assert "explore the repo" in cmd
    assert "add feature" in cmd


def test_build_agent_cmd_resolves_adapters_dir(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "explore_agent": "cursor",
        "agents": {
            "cursor": {"cmd": ["{adapters_dir}/cursor.sh", "{prompt}", "{task}", "{model}"]}
        }
    }))
    config = orchestrate.load_agent_config(tmp_path)
    adapters_dir = tmp_path / "adapters"
    cmd = orchestrate.build_agent_cmd(
        "cursor", config,
        prompt="p", task="t", model="m", provider="prov",
        adapters_dir=adapters_dir,
    )
    assert str(adapters_dir) + "/cursor.sh" == cmd[0]
    assert "p" in cmd
    assert "t" in cmd
    assert "m" in cmd


def test_build_agent_cmd_raises_for_unknown_agent(tmp_path):
    config = orchestrate.load_agent_config(tmp_path)
    with pytest.raises(ValueError, match="Unknown agent"):
        orchestrate.build_agent_cmd(
            "nonexistent", config,
            prompt="p", task="t", model="m", provider="prov",
            adapters_dir=tmp_path / "adapters",
        )


def test_builtin_agents_contains_expected_agents():
    for name in ("pi", "opencode", "aider", "gemini", "qwen", "cursor"):
        assert name in orchestrate.BUILTIN_AGENTS
        assert "cmd" in orchestrate.BUILTIN_AGENTS[name]
        assert isinstance(orchestrate.BUILTIN_AGENTS[name]["cmd"], list)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/test_agent_config.py -v 2>&1 | tail -20
```

Expected: `AttributeError: module 'orchestrate' has no attribute 'BUILTIN_AGENTS'` (or similar)

- [ ] **Step 3: Add `BUILTIN_AGENTS` constant to `orchestrate.py` after line 66**

Insert after `OMX_TEAM_CLI = "omx"` (line 66):

```python
SKILL_DIR = Path.home() / ".claude" / "skills" / "orchestrate"

BUILTIN_AGENTS: dict[str, dict] = {
    "pi": {
        "cmd": [
            "pi", "--print", "--provider", "{provider}", "--model", "{model}",
            "--no-session", "--no-context-files", "--append-system-prompt", "{prompt}", "{task}",
        ]
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
    },
}
```

- [ ] **Step 4: Add `load_agent_config()` and `build_agent_cmd()` after `detect_interop_paths()` (around line 121)**

Insert the two functions after the closing brace of `detect_interop_paths()`:

```python
def load_agent_config(skill_dir: Path) -> dict[str, Any]:
    """Load config.json; fall back to Pi defaults if absent."""
    config_path = skill_dir / "config.json"
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        merged_agents = {**BUILTIN_AGENTS, **raw.get("agents", {})}
        return {**raw, "agents": merged_agents}
    return {"explore_agent": "pi", "implement_agent": "pi", "agents": dict(BUILTIN_AGENTS)}


def build_agent_cmd(
    agent_name: str,
    config: dict[str, Any],
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

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/test_agent_config.py -v 2>&1 | tail -20
```

Expected: all 8 tests PASS

- [ ] **Step 6: Run all existing tests to confirm no regressions**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/ -v 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add skills/orchestrate/scripts/orchestrate.py skills/orchestrate/tests/test_agent_config.py && git commit -m "feat: add BUILTIN_AGENTS, load_agent_config, build_agent_cmd"
```

---

## Task 2: Add startup validation in `phase_setup()`

**Files:**
- Modify: `skills/orchestrate/scripts/orchestrate.py` — `phase_setup()` function

- [ ] **Step 1: Write the failing test**

Append to `skills/orchestrate/tests/test_agent_config.py`:

```python
def test_build_agent_cmd_sh_adapter_flagged_by_caller(tmp_path):
    """Callers must prepend 'bash' when cmd[0] ends with .sh."""
    (tmp_path / "config.json").write_text(json.dumps({
        "agents": {"cursor": {"cmd": ["{adapters_dir}/cursor.sh", "{prompt}", "{task}"]}}
    }))
    config = orchestrate.load_agent_config(tmp_path)
    adapters_dir = tmp_path / "adapters"
    cmd = orchestrate.build_agent_cmd(
        "cursor", config,
        prompt="p", task="t", model="m", provider="prov",
        adapters_dir=adapters_dir,
    )
    assert cmd[0].endswith(".sh"), "caller must detect .sh and prepend bash"
```

- [ ] **Step 2: Run test to confirm it passes (it's a design-verification test)**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/test_agent_config.py::test_build_agent_cmd_sh_adapter_flagged_by_caller -v
```

Expected: PASS (confirms the contract — callers detect `.sh` and prepend `bash`)

- [ ] **Step 3: Add startup validation to `phase_setup()` in `orchestrate.py`**

In `phase_setup()`, after the existing binary check block (after the `if missing and not args.dry_run:` block, around line 975), add:

```python
    # Validate configured agent binaries (warn only, consistent with tool check above)
    if not args.dry_run:
        agent_config = load_agent_config(SKILL_DIR)
        adapters_dir = SKILL_DIR / "adapters"
        for role in ("explore_agent", "implement_agent"):
            agent_name = agent_config[role]
            agent_agents = agent_config["agents"]
            if agent_name not in agent_agents:
                logger.log(f"[AGENT WARNING] {role} '{agent_name}' not in config — falling back to pi")
                continue
            bin_path = agent_agents[agent_name]["cmd"][0].format(adapters_dir=str(adapters_dir))
            if bin_path.endswith(".sh"):
                if not Path(bin_path).exists():
                    logger.log(f"[AGENT WARNING] {role} adapter script not found: {bin_path}")
            elif not shutil.which(bin_path):
                logger.log(f"[AGENT WARNING] {role} agent binary '{bin_path}' not found — install it before running /orchestrate")
```

- [ ] **Step 4: Run existing tests to confirm no regressions**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/ -v 2>&1 | tail -20
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add skills/orchestrate/scripts/orchestrate.py skills/orchestrate/tests/test_agent_config.py && git commit -m "feat: add agent binary startup validation in phase_setup"
```

---

## Task 3: Replace hardcoded Pi CLI calls in the four phases

**Files:**
- Modify: `skills/orchestrate/scripts/orchestrate.py` — `phase_explore()`, `phase_implement()`, `phase_pi_complete()`, `phase_pi_deploy()`

- [ ] **Step 1: Write the failing test for `phase_explore` dispatch**

Append to `skills/orchestrate/tests/test_agent_config.py`:

```python
import subprocess
from unittest.mock import patch


def test_phase_explore_uses_configured_agent(tmp_path, monkeypatch):
    """phase_explore must call the agent from load_agent_config, not always pi."""
    worktree = tmp_path / "wt"; worktree.mkdir()
    artifact_dir = tmp_path / "art"; (artifact_dir / "logs").mkdir(parents=True)
    orchestrate.write_json(
        artifact_dir / "summary.json",
        {"worktree": str(worktree), "phases": {}, "files": {}},
    )
    args = orchestrate.parse_args(
        ["--phase", "explore", "--task", "add feature", "--artifact-dir", str(artifact_dir)]
    )
    # Patch SKILL_DIR so load_agent_config reads from tmp_path
    # Use a config that selects 'opencode' agent
    (tmp_path / "config.json").write_text(
        json.dumps({"explore_agent": "opencode", "agents": {}})
    )
    ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="# report\nok")
    with patch("orchestrate.SKILL_DIR", tmp_path), \
         patch("orchestrate.run", return_value=ok) as mock_run:
        orchestrate.phase_explore(tmp_path, artifact_dir, args)

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "opencode", f"Expected opencode, got {cmd[0]}"
    assert "pi" not in cmd[0]


def test_phase_implement_uses_configured_agent(tmp_path, monkeypatch):
    """phase_implement must call the implement_agent, not always pi."""
    worktree = tmp_path / "wt"; worktree.mkdir()
    artifact_dir = tmp_path / "art"; (artifact_dir / "logs").mkdir(parents=True)
    orchestrate.write_json(
        artifact_dir / "summary.json",
        {"worktree": str(worktree), "phases": {"verify_design": {"status": "success"}}, "files": {}},
    )
    (artifact_dir / "design.md").write_text("# Design\nDo stuff.")
    (tmp_path / "config.json").write_text(
        json.dumps({"implement_agent": "aider", "agents": {}})
    )
    args = orchestrate.parse_args(
        ["--phase", "implement", "--task", "add feature", "--artifact-dir", str(artifact_dir)]
    )
    ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="done")
    # patch run + git status helpers so the "no_changes" branch isn't hit
    with patch("orchestrate.SKILL_DIR", tmp_path), \
         patch("orchestrate.run", return_value=ok) as mock_run, \
         patch("orchestrate.repo_snapshot", return_value=set()), \
         patch("orchestrate.changed_files", return_value=["src/foo.py"]):
        orchestrate.phase_implement(tmp_path, artifact_dir, args)

    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[0] == "aider", f"Expected aider, got {cmd[0]}"
```

- [ ] **Step 2: Run failing tests**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/test_agent_config.py::test_phase_explore_uses_configured_agent skills/orchestrate/tests/test_agent_config.py::test_phase_implement_uses_configured_agent -v 2>&1 | tail -15
```

Expected: FAIL — `phase_explore` and `phase_implement` still call `pi` regardless of config

- [ ] **Step 3: Replace Pi CLI cmd in `phase_explore()`**

In `phase_explore()`, replace the hardcoded `cmd` block (lines 1051–1063):

```python
# Old code to remove:
    cmd = [
        "pi",
        "--print",
        "--provider",
        args.provider,
        "--model",
        args.explore_model,
        "--no-session",
        "--no-context-files",
        "--append-system-prompt",
        system_prompt,
        "Explore the repository now. Do not edit files.",
    ]
```

With:

```python
# New code:
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    explore_agent = agent_config["explore_agent"]
    cmd = build_agent_cmd(
        explore_agent, agent_config,
        prompt=system_prompt, task=args.task,
        model=args.explore_model, provider=args.provider,
        adapters_dir=adapters_dir,
    )
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
```

- [ ] **Step 4: Replace Pi CLI cmd in `phase_implement()`**

In `phase_implement()`, replace the hardcoded `cmd` block (lines 1522–1534):

```python
# Old code to remove:
    cmd = [
        "pi",
        "--print",
        "--provider",
        args.provider,
        "--model",
        args.model,
        "--no-session",
        "--no-context-files",
        "--append-system-prompt",
        prompt,
        "Implement the requested changes now.",
    ]
```

With:

```python
# New code:
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    implement_agent = agent_config["implement_agent"]
    cmd = build_agent_cmd(
        implement_agent, agent_config,
        prompt=prompt, task=args.task,
        model=args.model, provider=args.provider,
        adapters_dir=adapters_dir,
    )
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
```

- [ ] **Step 5: Replace Pi CLI cmd in `phase_pi_complete()`**

In `phase_pi_complete()`, replace the hardcoded `cmd` block (lines 1940–1952):

```python
# Old code to remove:
    cmd = [
        "pi",
        "--print",
        "--provider",
        args.provider,
        "--model",
        args.model,
        "--no-session",
        "--no-context-files",
        "--append-system-prompt",
        prompt,
        "Commit and push the completed implementation now.",
    ]
```

With:

```python
# New code:
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    implement_agent = agent_config["implement_agent"]
    cmd = build_agent_cmd(
        implement_agent, agent_config,
        prompt=prompt, task=args.task,
        model=args.model, provider=args.provider,
        adapters_dir=adapters_dir,
    )
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
```

- [ ] **Step 6: Replace Pi CLI cmd in `phase_pi_deploy()`**

In `phase_pi_deploy()`, replace the hardcoded `cmd` block (lines 2083–2095):

```python
# Old code to remove:
    cmd = [
        "pi",
        "--print",
        "--provider",
        args.provider,
        "--model",
        args.model,
        "--no-session",
        "--no-context-files",
        "--append-system-prompt",
        prompt,
        "Run the deploy phase now.",
    ]
```

With:

```python
# New code:
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    implement_agent = agent_config["implement_agent"]
    cmd = build_agent_cmd(
        implement_agent, agent_config,
        prompt=prompt, task=args.task,
        model=args.model, provider=args.provider,
        adapters_dir=adapters_dir,
    )
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
```

- [ ] **Step 7: Run the new dispatch tests**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/test_agent_config.py::test_phase_explore_uses_configured_agent skills/orchestrate/tests/test_agent_config.py::test_phase_implement_uses_configured_agent -v 2>&1 | tail -15
```

Expected: both PASS

- [ ] **Step 8: Run all tests**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/ -v 2>&1 | tail -25
```

Expected: all tests pass

- [ ] **Step 9: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add skills/orchestrate/scripts/orchestrate.py skills/orchestrate/tests/test_agent_config.py && git commit -m "feat: replace hardcoded Pi CLI calls with configurable agent dispatch"
```

---

## Task 4: Create `adapters/cursor.sh`

**Files:**
- Create: `skills/orchestrate/adapters/cursor.sh`

- [ ] **Step 1: Create the adapters directory and write cursor.sh**

```bash
mkdir -p /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/adapters
```

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/adapters/cursor.sh`:

```bash
#!/usr/bin/env bash
# Normalized adapter: cursor.sh "<prompt>" "<task>" "<model>"
# Cursor CLI does not support --message; pass input via stdin pipe.
set -euo pipefail
PROMPT="$1"
TASK="$2"
MODEL="${3:-}"
printf '%s\n%s' "$PROMPT" "$TASK" | cursor chat ${MODEL:+--model "$MODEL"} --stdin
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/adapters/cursor.sh
```

- [ ] **Step 3: Verify the shebang and permissions**

```bash
head -1 /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/adapters/cursor.sh
ls -la /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/adapters/cursor.sh
```

Expected: `#!/usr/bin/env bash` on line 1; `-rwxr-xr-x` permissions

- [ ] **Step 4: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add skills/orchestrate/adapters/cursor.sh && git commit -m "feat: add cursor.sh adapter for Cursor CLI"
```

---

## Task 5: Create `config.example.json`

**Files:**
- Create: `skills/orchestrate/config.example.json`

- [ ] **Step 1: Write config.example.json**

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/config.example.json`:

```json
{
  "explore_agent": "pi",
  "implement_agent": "pi",
  "agents": {
    "pi": {
      "cmd": [
        "pi", "--print", "--provider", "{provider}", "--model", "{model}",
        "--no-session", "--no-context-files", "--append-system-prompt", "{prompt}", "{task}"
      ]
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

- [ ] **Step 2: Verify it parses as valid JSON**

```bash
python3 -c "import json; json.load(open('/Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/config.example.json')); print('valid JSON')"
```

Expected: `valid JSON`

- [ ] **Step 3: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add skills/orchestrate/config.example.json && git commit -m "feat: add config.example.json with all built-in agents"
```

---

## Task 6: Create `configure.sh`

**Files:**
- Create: `configure.sh`

- [ ] **Step 1: Write configure.sh**

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/configure.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

CONFIG="$HOME/.claude/skills/orchestrate/config.json"
AVAILABLE="pi opencode aider gemini qwen cursor"

log() { printf '[fiftybox] %s\n' "$*"; }

current_explore=$(python3 -c "
import json, os
p = '$CONFIG'
d = json.load(open(p)) if os.path.exists(p) else {}
print(d.get('explore_agent', 'pi'))
" 2>/dev/null || echo "pi")

current_implement=$(python3 -c "
import json, os
p = '$CONFIG'
d = json.load(open(p)) if os.path.exists(p) else {}
print(d.get('implement_agent', 'pi'))
" 2>/dev/null || echo "pi")

echo "Available agents: $AVAILABLE"
echo ""
read -rp "Explore agent [current: $current_explore]: " explore
read -rp "Implement agent [current: $current_implement]: " implement

explore="${explore:-$current_explore}"
implement="${implement:-$current_implement}"

python3 - <<PYEOF
import json, pathlib
path = pathlib.Path("$CONFIG")
cfg = json.loads(path.read_text()) if path.exists() else {}
cfg["explore_agent"] = "$explore"
cfg["implement_agent"] = "$implement"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(cfg, indent=2) + "\n")
PYEOF

log "Saved config → $CONFIG"
log "  explore_agent:   $explore"
log "  implement_agent: $implement"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /Users/tanpapa/Desktop/develop-a/fiftybox/configure.sh
```

- [ ] **Step 3: Smoke test (non-interactive — pipe answers in)**

```bash
FAKE_HOME="$(mktemp -d)"
trap 'rm -rf "$FAKE_HOME"' EXIT
printf 'gemini\naider\n' | HOME="$FAKE_HOME" bash /Users/tanpapa/Desktop/develop-a/fiftybox/configure.sh
python3 -c "
import json
d = json.load(open('$FAKE_HOME/.claude/skills/orchestrate/config.json'))
assert d['explore_agent'] == 'gemini', d
assert d['implement_agent'] == 'aider', d
print('configure.sh smoke test PASSED')
"
```

Expected: `configure.sh smoke test PASSED`

- [ ] **Step 4: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add configure.sh && git commit -m "feat: add configure.sh interactive agent picker"
```

---

## Task 7: Update `install.sh` to copy adapters and config example

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Write the failing install test**

Append to `/Users/tanpapa/Desktop/develop-a/fiftybox/tests/test_install.sh` (if it exists) or create it:

```bash
# Additional check: adapters and config.example.json must be installed
[[ -f "$FAKE_HOME/.claude/skills/orchestrate/adapters/cursor.sh" ]] \
  && pass "cursor.sh adapter installed" \
  || fail "cursor.sh adapter missing"

[[ -f "$FAKE_HOME/.claude/skills/orchestrate/config.example.json" ]] \
  && pass "config.example.json installed" \
  || fail "config.example.json missing"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
FAKE_HOME="$(mktemp -d)"
HOME="$FAKE_HOME" bash /Users/tanpapa/Desktop/develop-a/fiftybox/install.sh >/dev/null 2>&1
[[ -f "$FAKE_HOME/.claude/skills/orchestrate/adapters/cursor.sh" ]] && echo "PASS: adapter present" || echo "FAIL: adapter missing"
[[ -f "$FAKE_HOME/.claude/skills/orchestrate/config.example.json" ]] && echo "PASS: config.example.json present" || echo "FAIL: config.example.json missing"
rm -rf "$FAKE_HOME"
```

Expected: both lines say `FAIL`

- [ ] **Step 3: Add adapter and config-example copy to `install.sh`**

In `install.sh`, after the line `log "Installed skills/orchestrate/ → $SKILLS_DIR"`, add:

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
```

Also add a hint about `configure.sh` before the final success message. After the `log "Installed commands/orchestrate.md → ..."` line, add:

```bash
echo ""
log "To configure agents: ./configure.sh"
```

- [ ] **Step 4: Run the install test again to confirm it passes**

```bash
FAKE_HOME="$(mktemp -d)"
HOME="$FAKE_HOME" bash /Users/tanpapa/Desktop/develop-a/fiftybox/install.sh >/dev/null 2>&1
[[ -f "$FAKE_HOME/.claude/skills/orchestrate/adapters/cursor.sh" ]] && echo "PASS: adapter present" || echo "FAIL: adapter missing"
[[ -f "$FAKE_HOME/.claude/skills/orchestrate/config.example.json" ]] && echo "PASS: config.example.json present" || echo "FAIL: config.example.json missing"
rm -rf "$FAKE_HOME"
```

Expected: both lines say `PASS`

- [ ] **Step 5: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add install.sh && git commit -m "feat: install adapters/ and config.example.json in install.sh"
```

---

## Task 8: Update `README.md` with "Agent Configuration" section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Agent Configuration section to README.md**

After the `## How It Works` section (before `## License`), insert:

````markdown
## Agent Configuration

By default, fiftybox uses Pi CLI for both exploration and implementation.
To switch agents, run:

```bash
./configure.sh
```

Or edit `~/.claude/skills/orchestrate/config.json` directly.

Supported built-in agents: `pi`, `opencode`, `aider`, `gemini`, `qwen`, `cursor`

### Adding a custom agent

Add an entry to the `agents` object in `config.json`:

```json
{
  "implement_agent": "my-agent",
  "agents": {
    "my-agent": { "cmd": ["/path/to/my-agent.sh", "{prompt}", "{task}"] }
  }
}
```

Template variables: `{prompt}`, `{task}`, `{model}`, `{provider}`, `{adapters_dir}`
````

- [ ] **Step 2: Verify the README renders (check markdown structure)**

```bash
grep -n "## " /Users/tanpapa/Desktop/develop-a/fiftybox/README.md
```

Expected output (sections in order):
```
## Prerequisites
## Install
## Usage
## How It Works
## Agent Configuration
## License
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git add README.md && git commit -m "docs: add Agent Configuration section to README"
```

---

## Task 9: Push to GitHub

- [ ] **Step 1: Run full test suite one final time**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/ -v 2>&1 | tail -30
```

Expected: all tests pass

- [ ] **Step 2: Verify repo state**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git log --oneline -8
```

Expected: 8 new commits since the last push (Tasks 1–8 commits)

- [ ] **Step 3: Push**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && git push origin main
```

Expected: `Branch 'main' set up to track remote branch 'main' from 'origin'.`

---

## Self-Review

**Spec coverage check against `2026-06-01-fiftybox-multi-agent-backend-design.md`:**

| Spec requirement | Task |
|---|---|
| `BUILTIN_AGENTS` constant | Task 1 |
| `load_agent_config()` function | Task 1 |
| `build_agent_cmd()` function | Task 1 |
| `phase_explore()` uses configurable agent | Task 3 |
| `phase_implement()` uses configurable agent | Task 3 |
| `phase_pi_complete()` uses configurable agent | Task 3 |
| `phase_pi_deploy()` uses configurable agent | Task 3 |
| Startup validation in `phase_setup()` | Task 2 |
| `adapters/cursor.sh` | Task 4 |
| `config.example.json` | Task 5 |
| `configure.sh` interactive picker | Task 6 |
| `install.sh` copies `adapters/` | Task 7 |
| `install.sh` copies `config.example.json` | Task 7 |
| README "Agent Configuration" section | Task 8 |
| Backward compatible (no config → Pi defaults) | Covered by `load_agent_config()` fallback |

**Placeholder scan:** No TBD, TODO, "implement later", or "add appropriate" phrases.

**Type consistency:**
- `BUILTIN_AGENTS` type is `dict[str, dict]` — consistent across all references
- `load_agent_config()` returns `dict[str, Any]` — consistent with `build_agent_cmd()` `config` param
- `build_agent_cmd()` returns `list[str]` — assigned to `cmd` in all 4 phase replacements
- `SKILL_DIR` is `Path` — used consistently as `Path` in all load/build calls
