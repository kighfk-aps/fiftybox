# Fiftybox Repository Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `/Users/tanpapa/Desktop/develop-a/fiftybox/` as a public Claude Code plugin repo that lets anyone install the Claude + Codex + Pi CLI orchestration harness via `claude plugins install github:kighfk-aps/fiftybox`.

**Architecture:** Copy/extract the orchestrate skill from the existing `workflow` repo into a new standalone plugin repo. Add `install.sh` as a conversational install fallback and `README.md` as the user-facing entry point. Create the GitHub repo and push.

**Tech Stack:** bash, Python (existing scripts), Claude Code plugin format (`package.json`), GitHub CLI (`gh`)

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `package.json` | Create | Claude Code plugin manifest |
| `AGENTS.md` | Create | Orchestrate workflow rules (extracted from workflow repo) |
| `skills/orchestrate/SKILL.md` | Copy from workflow | Main skill definition |
| `skills/orchestrate/scripts/orchestrate.py` | Copy from workflow | Phase runner |
| `skills/orchestrate/scripts/orchestrate_watcher.py` | Copy from workflow | Auto-resume daemon |
| `skills/orchestrate/tests/test_orchestrate.py` | Copy from workflow | Existing tests |
| `skills/orchestrate/tests/test_orchestrate_watcher.py` | Copy from workflow | Existing tests |
| `skills/orchestrate/tests/test_codex_detection.py` | Copy from workflow | Existing tests |
| `commands/orchestrate.md` | Create | `/orchestrate` slash command |
| `install.sh` | Create | Fallback install script |
| `README.md` | Create | User-facing docs (prerequisites, 3 install paths, usage) |

---

## Task 1: Initialize repo directory

**Files:**
- Create: `/Users/tanpapa/Desktop/develop-a/fiftybox/` (git repo)

- [ ] **Step 1: Create directory and init git**

```bash
mkdir -p /Users/tanpapa/Desktop/develop-a/fiftybox
git -C /Users/tanpapa/Desktop/develop-a/fiftybox init
```

Expected output: `Initialized empty Git repository in .../fiftybox/.git/`

- [ ] **Step 2: Verify**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox status
```

Expected: `On branch main` (or `master`) with no commits yet.

---

## Task 2: Create package.json

**Files:**
- Create: `/Users/tanpapa/Desktop/develop-a/fiftybox/package.json`

- [ ] **Step 1: Write package.json**

```json
{
  "name": "fiftybox",
  "version": "1.0.0",
  "description": "Claude + Codex + Pi CLI orchestration harness — TDD-driven development pipeline"
}
```

Save to `/Users/tanpapa/Desktop/develop-a/fiftybox/package.json`.

- [ ] **Step 2: Commit**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox add package.json
git -C /Users/tanpapa/Desktop/develop-a/fiftybox commit -m "chore: init repo with package.json"
```

---

## Task 3: Create AGENTS.md

**Files:**
- Create: `/Users/tanpapa/Desktop/develop-a/fiftybox/AGENTS.md`

- [ ] **Step 1: Write AGENTS.md**

Write the following content to `/Users/tanpapa/Desktop/develop-a/fiftybox/AGENTS.md`:

```markdown
# Orchestrate Harness

## Project Overview

Multi-agent orchestration harness. Claude Code drives the entire pipeline, coordinating Pi CLI (exploration/implementation) and Codex (design verification/review/testing).

## Tool Chain

| Role | Tool | Model Source |
|------|------|-------------|
| Orchestrator | Claude Code | Anthropic |
| Explore + Implement | Pi CLI | OpenCode Go plan |
| Design Verification | Codex | OpenAI |
| Code Review + Test | Codex | OpenAI |

## Workflow Rules

- Every task runs in an isolated git worktree
- No automatic recovery on failure — report to user, present choices, wait
- Single automatic retry: Phase 6 (review+test) failure triggers one Phase 5 re-implementation
- On success: commit → merge to main → push (all sequential, no user gate)
- Agents share no session memory — handoffs are artifact-file based
- Intent clarification (Phase 2) is mandatory before design

## Safety Policy

- No destructive git operations (force push, reset --hard, branch -D)
- Push only at pipeline completion (Phase 7)
- No file modifications outside the worktree
- No parallel agents editing the same files
- No commit/push by implementation agents (Pi CLI) — only the orchestrator commits

## Artifact Location

```
.omx/artifacts/orchestrate/<timestamp>/
```

## Failure Reporting Format

On failure, Claude Code reports:
1. Phase name and number
2. Error cause (message, exit code, log excerpt)
3. 2-4 recommended actions as user choices

## Slash Command

```
/orchestrate "<task description>"
```
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox add AGENTS.md
git -C /Users/tanpapa/Desktop/develop-a/fiftybox commit -m "docs: add AGENTS.md with orchestrate workflow rules"
```

---

## Task 4: Copy orchestrate skill files

**Files:**
- Copy: `skills/orchestrate/SKILL.md`
- Copy: `skills/orchestrate/scripts/orchestrate.py`
- Copy: `skills/orchestrate/scripts/orchestrate_watcher.py`
- Copy: `skills/orchestrate/tests/test_orchestrate.py`
- Copy: `skills/orchestrate/tests/test_orchestrate_watcher.py`
- Copy: `skills/orchestrate/tests/test_codex_detection.py`

Source: `/Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/`

- [ ] **Step 1: Create directory structure and copy files**

```bash
mkdir -p /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/scripts
mkdir -p /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/tests

cp /Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/SKILL.md \
   /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/SKILL.md

cp /Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/scripts/orchestrate.py \
   /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/scripts/orchestrate.py

cp /Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/scripts/orchestrate_watcher.py \
   /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/scripts/orchestrate_watcher.py

cp /Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/tests/test_orchestrate.py \
   /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/tests/test_orchestrate.py

cp /Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/tests/test_orchestrate_watcher.py \
   /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/tests/test_orchestrate_watcher.py

cp /Users/tanpapa/Desktop/develop-a/workflow/skills/orchestrate/tests/test_codex_detection.py \
   /Users/tanpapa/Desktop/develop-a/fiftybox/skills/orchestrate/tests/test_codex_detection.py
```

- [ ] **Step 2: Verify files exist**

```bash
find /Users/tanpapa/Desktop/develop-a/fiftybox/skills -type f | sort
```

Expected output:
```
.../fiftybox/skills/orchestrate/SKILL.md
.../fiftybox/skills/orchestrate/scripts/orchestrate.py
.../fiftybox/skills/orchestrate/scripts/orchestrate_watcher.py
.../fiftybox/skills/orchestrate/tests/test_codex_detection.py
.../fiftybox/skills/orchestrate/tests/test_orchestrate.py
.../fiftybox/skills/orchestrate/tests/test_orchestrate_watcher.py
```

- [ ] **Step 3: Verify tests pass (existing tests must not be broken by the copy)**

```bash
cd /Users/tanpapa/Desktop/develop-a/fiftybox && python3 -m pytest skills/orchestrate/tests/ -v 2>&1 | tail -20
```

Expected: all tests pass or skip (no new failures introduced).

- [ ] **Step 4: Commit**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox add skills/
git -C /Users/tanpapa/Desktop/develop-a/fiftybox commit -m "feat: add orchestrate skill, scripts, and tests"
```

---

## Task 5: Create commands/orchestrate.md

**Files:**
- Create: `/Users/tanpapa/Desktop/develop-a/fiftybox/commands/orchestrate.md`

- [ ] **Step 1: Create commands directory and write slash command**

```bash
mkdir -p /Users/tanpapa/Desktop/develop-a/fiftybox/commands
```

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/commands/orchestrate.md`:

```markdown
---
name: orchestrate
description: Multi-agent orchestration harness: explore, clarify, design, implement, review, merge
---

Load and follow the orchestrate skill instructions at `~/.claude/skills/orchestrate/SKILL.md`.

Task: $ARGUMENTS
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox add commands/orchestrate.md
git -C /Users/tanpapa/Desktop/develop-a/fiftybox commit -m "feat: add /orchestrate slash command"
```

---

## Task 6: Create install.sh

**Files:**
- Create: `/Users/tanpapa/Desktop/develop-a/fiftybox/install.sh`

- [ ] **Step 1: Write install.sh**

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILLS_DIR="$HOME/.claude/skills/orchestrate"
COMMANDS_DIR="$HOME/.claude/commands"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '[fiftybox] %s\n' "$*"; }
warn() { printf '[fiftybox] WARNING: %s\n' "$*" >&2; }

log "Installing Fiftybox orchestrate harness..."
echo ""

# Check prerequisites — warn but don't abort so partial installs still work
for bin in pi codex claude; do
  if command -v "$bin" &>/dev/null; then
    log "  ✓ $bin"
  else
    warn "  $bin not found — install it before running /orchestrate"
  fi
done
echo ""

# Install skill
mkdir -p "$SKILLS_DIR/scripts"
cp "$SCRIPT_DIR/skills/orchestrate/SKILL.md" "$SKILLS_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/orchestrate/scripts/"*.py "$SKILLS_DIR/scripts/"
log "Installed skills/orchestrate/ → $SKILLS_DIR"

# Install slash command
mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/commands/orchestrate.md" "$COMMANDS_DIR/orchestrate.md"
log "Installed commands/orchestrate.md → $COMMANDS_DIR/orchestrate.md"

echo ""
log "Done! Restart Claude Code, then try:"
log "  /orchestrate \"add login feature\""
```

- [ ] **Step 2: Make executable**

```bash
chmod +x /Users/tanpapa/Desktop/develop-a/fiftybox/install.sh
```

- [ ] **Step 3: Write failing test for install.sh**

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/tests/test_install.sh`:

```bash
#!/usr/bin/env bash
# Tests for install.sh — runs in a temp HOME to avoid touching real ~/.claude
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAKE_HOME="$(mktemp -d)"
trap 'rm -rf "$FAKE_HOME"' EXIT

pass() { printf '[PASS] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*"; exit 1; }

# Run install.sh with fake HOME
HOME="$FAKE_HOME" bash "$SCRIPT_DIR/install.sh" >/dev/null 2>&1

# Assert skill files installed
[[ -f "$FAKE_HOME/.claude/skills/orchestrate/SKILL.md" ]] \
  && pass "SKILL.md installed" \
  || fail "SKILL.md missing"

[[ -f "$FAKE_HOME/.claude/skills/orchestrate/scripts/orchestrate.py" ]] \
  && pass "orchestrate.py installed" \
  || fail "orchestrate.py missing"

[[ -f "$FAKE_HOME/.claude/commands/orchestrate.md" ]] \
  && pass "orchestrate.md command installed" \
  || fail "orchestrate.md command missing"

echo ""
echo "All install.sh tests passed."
```

- [ ] **Step 4: Run test — expect FAIL (tests/ dir doesn't exist yet)**

```bash
mkdir -p /Users/tanpapa/Desktop/develop-a/fiftybox/tests
chmod +x /Users/tanpapa/Desktop/develop-a/fiftybox/tests/test_install.sh
bash /Users/tanpapa/Desktop/develop-a/fiftybox/tests/test_install.sh
```

Expected: All 3 PASS (install.sh already written, so this should pass immediately).

- [ ] **Step 5: Commit**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox add install.sh tests/test_install.sh
git -C /Users/tanpapa/Desktop/develop-a/fiftybox commit -m "feat: add install.sh with prerequisite checks and install test"
```

---

## Task 7: Create README.md

**Files:**
- Create: `/Users/tanpapa/Desktop/develop-a/fiftybox/README.md`

- [ ] **Step 1: Write README.md**

Write the following to `/Users/tanpapa/Desktop/develop-a/fiftybox/README.md`:

```markdown
# Fiftybox

> Claude + Codex + Pi CLI orchestration harness — TDD-driven development pipeline in a single `claude plugins install`.

Fiftybox wires three AI agents into a focused development pipeline:

- **Claude Code** — orchestrates the full lifecycle
- **Pi CLI** — explores the codebase and implements changes
- **Codex CLI** — verifies design and reviews code

Invoke `/orchestrate "task"` and Fiftybox drives everything: explore → clarify → design → implement → review → commit → push.

**Why Fiftybox and not [metaswarm](https://github.com/dsifry/metaswarm)?**
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
Install the Fiftybox harness: https://github.com/kighfk-aps/fiftybox
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
| 1 Explore | Pi CLI | Maps codebase, identifies relevant files |
| 2 Clarify | Claude | Confirms intent with user if ambiguous |
| 3 Design | Codex | Verifies architecture, flags risks |
| 4 Test | Claude | Writes failing tests (Red) |
| 5 Implement | Pi CLI | Implements to pass tests (Green) |
| 6 Review | Codex | Reviews code, runs tests |
| 7 Commit | Claude | Commits → merges → pushes |

---

## License

MIT
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/tanpapa/Desktop/develop-a/fiftybox add README.md
git -C /Users/tanpapa/Desktop/develop-a/fiftybox commit -m "docs: add README with install paths, prerequisites, usage"
```

---

## Task 8: Create GitHub repo and push

**Prerequisite:** `gh` CLI must be authenticated (`gh auth status`).

- [ ] **Step 1: Verify gh auth**

```bash
gh auth status
```

Expected: `Logged in to github.com as kighfk-aps`

- [ ] **Step 2: Create public GitHub repo and push**

```bash
gh repo create fiftybox \
  --public \
  --description "Claude + Codex + Pi CLI orchestration harness — TDD-driven dev pipeline" \
  --source=/Users/tanpapa/Desktop/develop-a/fiftybox \
  --remote=origin \
  --push
```

Expected: repo created and all commits pushed.

- [ ] **Step 3: Verify**

```bash
gh repo view kighfk-aps/fiftybox --web
```

Confirm the repo is live at `https://github.com/kighfk-aps/fiftybox`.

- [ ] **Step 4: Smoke-test plugin install path**

```bash
# Test that the plugin install command resolves (dry run — don't actually reinstall)
gh api repos/kighfk-aps/fiftybox --jq '{name: .name, private: .private, url: .html_url}'
```

Expected:
```json
{
  "name": "fiftybox",
  "private": false,
  "url": "https://github.com/kighfk-aps/fiftybox"
}
```

---

## Self-Review

**Spec coverage:**
- ✅ Plugin format (`package.json`) — Task 2
- ✅ Conversational install (`install.sh` + README Option 2) — Tasks 6, 7
- ✅ Manual install path — Task 7
- ✅ `skills/orchestrate/` structure — Task 4
- ✅ `commands/orchestrate.md` — Task 5
- ✅ `AGENTS.md` with workflow rules — Task 3
- ✅ Prerequisites documented in README — Task 7
- ✅ GitHub repo created and public — Task 8
- ✅ Positioning vs metaswarm in README — Task 7

**No placeholders:** All steps contain actual code/commands/content.

**No workflow changes:** `workflow` repo untouched — `fiftybox` is a standalone copy.
