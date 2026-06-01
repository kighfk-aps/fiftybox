# Fiftybox — Public Orchestration Harness

**Date:** 2026-06-01  
**Status:** Approved

## What Is Fiftybox?

Fiftybox is a standalone, installable Claude Code skill that wires Claude Code, Codex CLI, and Pi CLI into a single TDD-driven development pipeline. Users invoke `/orchestrate` and Fiftybox drives the full lifecycle: explore → clarify → design → implement → review → commit → push.

The name reflects the three-prong tool chain: **Claude** (orchestrator) + **Codex** (design verification / review) + **Pi CLI** (exploration / implementation).

---

## Positioning

The closest existing project is [metaswarm](https://github.com/dsifry/metaswarm) — 18 agents, 9-phase pipeline, multi-model support. Fiftybox is intentionally narrower:

| | Fiftybox | metaswarm |
|---|---|---|
| Agents | 3 (fixed: Claude / Pi / Codex) | 18 (configurable) |
| Install | one command | complex setup |
| Pi CLI | first-class implementation agent | not included |
| superpowers | native dependency | builds on top of it |
| Target | "same three tools, just works" | "full enterprise SDLC" |

Fiftybox's pitch: **Pi CLI is the implementation engine, Codex is the reviewer, Claude is the conductor — and it fits in a single `claude plugins install`.**

---

## Goals

- Let anyone with Claude Code + Codex CLI + Pi CLI run the same harness used in this project
- Installation requires no manual file surgery — one command or one chat message does it
- Scope is narrow: just the orchestrate harness, nothing else from the personal workflow config
- Differentiated from metaswarm by being lightweight and Pi CLI-native

---

## Out of Scope

- hooks, settings.json, personal Claude Code config
- Pi CLI or Codex CLI installation guides (link to their official repos)
- Other skills (ideate, pi-brainstorming, etc.)

---

## Repo Structure

```
fiftybox/                          ← github.com/username/fiftybox
├── package.json                  ← Claude Code plugin manifest
├── README.md
├── AGENTS.md                     ← orchestrate workflow rules (extracted from workflow repo)
├── skills/
│   └── orchestrate/
│       ├── SKILL.md
│       └── scripts/
│           ├── orchestrate.py
│           └── orchestrate_watcher.py
├── commands/
│   └── orchestrate.md            ← /orchestrate slash command
└── install.sh                    ← fallback for conversational install
```

### package.json

```json
{
  "name": "fiftybox",
  "version": "1.0.0",
  "description": "Claude + Codex + Pi CLI orchestration harness"
}
```

---

## Installation Paths

### Path 1 — Claude Code plugin (recommended)

```bash
claude plugins install github:username/fiftybox
```

Claude Code clones the repo and registers `skills/orchestrate/` and `commands/orchestrate.md` automatically.

### Path 2 — Conversational install (paste into Claude or Codex chat)

README includes a ready-to-copy block:

```
Install the Fiftybox harness: https://github.com/username/fiftybox
```

Claude/Codex runs `git clone` + `./install.sh` automatically.

### Path 3 — Manual fallback

```bash
git clone https://github.com/username/fiftybox
cd fiftybox && ./install.sh
```

### install.sh behavior

1. Check for `pi`, `codex`, `claude` binaries — warn if missing, do not abort
2. Copy `skills/orchestrate/` → `~/.claude/skills/orchestrate/`
3. Copy `commands/orchestrate.md` → `~/.claude/commands/orchestrate.md`
4. Print success message + next steps

---

## Prerequisites (documented in README)

| Tool | Check |
|------|-------|
| Claude Code | `claude --version` |
| Pi CLI | `pi --version` |
| Codex CLI | `codex --version` |
| superpowers plugin | `claude plugins list` |
| codex plugin | `claude plugins list` |

Plugin install commands included in README.

---

## README Structure

1. **What is Fiftybox?** — one paragraph
2. **Prerequisites** — table + install commands for plugins
3. **Install** — three paths, Path 1 first
4. **Usage** — `/orchestrate "task description"`
5. **How it works** — pipeline phase summary (Explore → Clarify → Design → Implement → Review → Commit → Push)

---

## Local Sync

Working directory: `/Users/tanpapa/Desktop/develop-a/fiftybox/`  
GitHub remote: `https://github.com/username/fiftybox` (to be created)

The folder is initialized as a git repo and pushed as the new `fiftybox` repository.

---

## What Does NOT Change in the Existing Workflow Repo

- `skills/orchestrate/` remains in `workflow` for local use
- No files are deleted or moved from `workflow`
- `fiftybox` is a copy/export, not a symlink or submodule
