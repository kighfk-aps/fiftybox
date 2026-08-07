# fiftybox

> Claude + Pi CLI orchestration harness — TDD-driven development pipeline in a single `claude plugins install`.

Fiftybox wires AI agents into a focused development pipeline:

- **Claude Code** — orchestrates the full lifecycle and reviews every change
- **Pi CLI** — explores the codebase and implements changes (default: opencode-go / `deepseek-v4-flash`)

Invoke `/fiftybox-orchestration "task"` and fiftybox drives everything: explore → clarify → design → implement → review → commit → push.

> **Codex retired (2026-07).** Design/implementation reviews no longer shell out to Codex. The Claude Review Gate is the primary quality check; a design review is skipped by default and only runs on GLM (Z.AI Coding Plan — `zai-coding` / `glm-5.2`) when an architecture is genuinely complex.

**Why fiftybox instead of [metaswarm](https://github.com/dsifry/metaswarm)?**
Metaswarm is powerful but complex (18 agents, 9 phases). Fiftybox is opinionated and lightweight — Pi CLI is the implementation engine, Claude is the conductor and reviewer. Two tools, one command.

---

## Prerequisites

| Tool | Install | Check |
|------|---------|-------|
| Claude Code | [claude.ai/code](https://claude.ai/code) | `claude --version` |
| Pi CLI | [pi.ai/cli](https://pi.ai/cli) | `pi --version` |

Claude Code plugins required:

```bash
claude plugins install superpowers@claude-plugins-official
```

---

## Install

### Option 1 — Plugin (recommended)

```bash
claude plugins install github:kighfk-aps/fiftybox
```

Claude Code handles the rest — no cloning needed.

### Option 2 — Paste into Claude chat

Copy and paste this into any Claude Code session:

```
Install the fiftybox harness: https://github.com/kighfk-aps/fiftybox
```

Claude will clone the repo and run `install.sh` automatically.

### Option 3 — Manual

```bash
git clone https://github.com/kighfk-aps/fiftybox
cd fiftybox && ./install.sh
```

---

## Usage

```bash
/fiftybox-orchestration "add JWT authentication to the API"
```

### Commands

fiftybox ships six slash commands:

| Command | What it does |
|---------|--------------|
| `/fiftybox-orchestration` | Full pipeline: explore → clarify → design → implement → review → commit → push |
| `/fiftybox-plans` | Planning front half only — produces a saved Markdown plan for later handoff |
| `/fiftybox-execute` | Parallel-batch TDD execution with Pi CLI as the implementer |
| `/fiftybox-free-execute` | Sequential TDD execution on opencode free-tier models |
| `/fiftybox-cc-execute` | Parallel-batch TDD execution with the CommandCode (`cmd`) CLI as the implementer |
| `/fiftybox-gpt-review` | Reviews a design or plan document with Codex GPT models |

### Flags

| Flag | Description |
|------|-------------|
| `--skip-verify` | Skip the design-verify dependency for implement. Use when design is already done and you only need implementation (`/fiftybox-execute`). |
| `--design-review-provider` / `--design-review-model` | Opt-in GLM design review for a very complex architecture (e.g. `zai-coding` / `glm-5.2`). Omit to skip the design review entirely. |
| `--strict-review` | Restore hard-gating on review verdicts (Phase 4 design verify). Default: advisory — REJECTED/UNCLEAR is recorded and surfaced but does not stop the pipeline. Test failures always block. |

---

## How It Works

| Phase | Agent | What happens |
|-------|-------|-------------|
| 0 Setup | Claude | Creates isolated git worktree + artifact dir |
| 1 Explore | explore_agent (default: Pi) | Maps codebase, identifies relevant files |
| 2 Clarify | Claude (Opus) | Confirms intent with user if ambiguous |
| 3 Design | Claude (Opus) | Writes architecture + plan; review skipped by default (GLM opt-in for complex work) |
| 4 Test | Claude | Writes failing tests (Red) |
| 5 Implement | implement_agent (default: Pi / opencode-go / deepseek-v4-flash) | Implements to pass tests (Green) |
| 5.5 Review Gate | Claude | Primary quality check: tests, spec compliance, integration |
| 6 Review | tests (blocking) | Runs tests; no LLM review (Codex retired) |
| 7 Commit | Claude | Commits → merges → pushes |

---

## Agent Configuration

By default, fiftybox uses Pi CLI for both exploration and implementation.
To switch agents, run:

```bash
./configure.sh
```

Or edit `~/.claude/skills/fiftybox-orchestration/config.json` directly.

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
