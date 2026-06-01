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
