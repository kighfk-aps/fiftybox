# fiftybox

> Claude + Codex + Pi CLI orchestration harness — TDD-driven development pipeline in a single `claude plugins install`.

Fiftybox wires three AI agents into a focused development pipeline:

- **Claude Code** — orchestrates the full lifecycle
- **Pi CLI** — explores the codebase and implements changes
- **Codex CLI** — verifies design and reviews code

Invoke `/orchestrate "task"` and fiftybox drives everything: explore → clarify → design → implement → review → commit → push.

**Why fiftybox instead of [metaswarm](https://github.com/dsifry/metaswarm)?**
Metaswarm is powerful but complex (18 agents, 9 phases). Fiftybox is opinionated and lightweight — Pi CLI is the implementation engine, Codex is the reviewer, Claude is the conductor. Three tools, one command.

---

## Prerequisites

| Tool | Install | Check |
|------|---------|-------|
| Claude Code | [claude.ai/code](https://claude.ai/code) | `claude --version` |
| Pi CLI | [pi.ai/cli](https://pi.ai/cli) | `pi --version` |
| Codex CLI | `npm i -g @openai/codex` | `codex --version` |

Claude Code plugins required:

```bash
claude plugins install superpowers@claude-plugins-official
claude plugins install codex@openai-codex
```

---

## Install

### Option 1 — Plugin (recommended)

```bash
claude plugins install github:kighfk-aps/fiftybox
```

Claude Code handles the rest — no cloning needed.

### Option 2 — Paste into Claude or Codex chat

Copy and paste this into any Claude Code or Codex session:

```
Install the fiftybox harness: https://github.com/kighfk-aps/fiftybox
```

Claude/Codex will clone the repo and run `install.sh` automatically.

### Option 3 — Manual

```bash
git clone https://github.com/kighfk-aps/fiftybox
cd fiftybox && ./install.sh
```

---

## Usage

```bash
/orchestrate "add JWT authentication to the API"
```

---

## How It Works

| Phase | Agent | What happens |
|-------|-------|-------------|
| 0 Setup | Claude | Creates isolated git worktree + artifact dir |
| 1 Explore | explore_agent (default: Pi) | Maps codebase, identifies relevant files |
| 2 Clarify | Claude | Confirms intent with user if ambiguous |
| 3 Design | Codex | Verifies architecture, flags risks |
| 4 Test | Claude | Writes failing tests (Red) |
| 5 Implement | implement_agent (default: Pi) | Implements to pass tests (Green) |
| 6 Review | Codex | Reviews code, runs tests |
| 7 Commit | Claude | Commits → merges → pushes |

---

## Agent Configuration

By default, fiftybox uses Pi CLI for both exploration and implementation.
To switch agents, run:

```bash
./configure.sh
```

Or edit `~/.claude/skills/orchestrate/config.json` directly.

Supported built-in agents: `pi`, `opencode`, `aider`, `gemini`, `qwen`, `cursor`

### Adding a custom agent

```json
{
  "implement_agent": "my-agent",
  "agents": {
    "my-agent": { "cmd": ["/path/to/my-agent.sh", "{prompt}", "{task}"] }
  }
}
```

Template variables: `{prompt}`, `{task}`, `{model}`, `{provider}`, `{adapters_dir}`

## License

MIT
