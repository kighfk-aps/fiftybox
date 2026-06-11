# fiftybox-plans Skill Design

**Date:** 2026-06-11
**Skill name:** `fiftybox-plans`
**Slash command:** `/fiftybox-plans`

## Goal

A standalone planning skill that covers the front half of the orchestrate pipeline (exploration → design → plan) using cheap/free models for codebase exploration and Claude Opus + Codex for design and planning. Produces artifacts compatible with `/orchestrate --resume` so the user can hand off to implementation without re-doing any planning work.

## Problem Being Solved

Running `/orchestrate` uses expensive Claude tokens for every phase including codebase exploration, which is read-only and doesn't require a high-quality model. This skill moves exploration to Ollama Cloud (free Gemma4) and keeps Opus/Codex focused on the high-value design and planning phases. Token savings are primarily in Phase 1 EXPLORE, which on large repos can be the most token-heavy read phase.

## Architecture

### Workflow Phases

```
Phase 1  SETUP       orchestrate.py --phase setup
Phase 2  EXPLORE     orchestrate.py --phase explore --provider ollama --explore-model gemma4
Phase 3  CLARIFY     Claude (brainstorming style) → intent-summary.md, route-decision.md
Phase 4  DESIGN      Claude Opus sub-agent → design.md
Phase 5  VERIFY      orchestrate.py --phase verify-design (Codex GPT-5.5-high, advisory)
Phase 6  WRITE-PLAN  Claude Opus sub-agent → plan.md (writing-plans style)
Phase 7  USER GATE   Show plan, wait for user approval
Phase 8  HANDOFF     /orchestrate --resume <artifactDir>
```

### Model Responsibility Split

| Phase | Model | Cost |
|---|---|---|
| Codebase exploration (read-only) | Pi CLI + ollama gemma4 | Free |
| Complexity routing + clarifying Q&A | Claude Sonnet (current session) | Minimal |
| Architecture design | Claude Opus sub-agent | Medium |
| Design review | Codex GPT-5.5-high (via orchestrate.py) | Medium |
| Plan writing | Claude Opus sub-agent | Medium |

### Artifact Structure

All artifacts are written to the standard orchestrate artifact directory so that `/orchestrate --resume` can pick them up without modification:

```
.omx/artifacts/orchestrate/<timestamp>/
  ├── explore-report.md       ← Gemma4 codebase exploration
  ├── route-decision.md       ← Complexity routing decision
  ├── intent-summary.md       ← Agreed objective + constraints
  ├── design.md               ← Architecture design (Opus)
  ├── codex-design-review.md  ← Codex advisory review
  └── plan.md                 ← Implementation plan (Opus, writing-plans style)

docs/superpowers/plans/YYYY-MM-DD-<task>.md  ← Final plan file (user-facing)
```

### Handoff Contract

For `/orchestrate --resume <artifactDir>` to resume from Phase 4.5 (write tests), the following artifacts must exist:
- `intent-summary.md`
- `design.md`
- `route-decision.md`
- `codex-design-review.md`

This skill produces all four, so resume picks up at test-writing without user needing to redo any planning.

## Components

### SKILL.md

Location: `skills/fiftybox-plans/SKILL.md`

Defines the 8-phase workflow as Claude-executable instructions. References `orchestrate.py` for Phase 1, 2, and 5. Claude handles Phases 3, 4, 6, 7, 8 directly.

### orchestrate.py (no changes)

Reuses existing phases:
- `--phase setup` — creates artifactDir and worktree
- `--phase explore` — accepts `--provider ollama --explore-model gemma4`
- `--phase verify-design` — Codex advisory design review

### New plan file location

The final plan is saved to both:
1. `<artifactDir>/plan.md` — for orchestrate resume context
2. `docs/superpowers/plans/YYYY-MM-DD-<task>.md` — user-facing, follows writing-plans convention

## Data Flow

```
User: /fiftybox-plans "add OAuth login"
  │
  ▼
Phase 1: orchestrate.py setup → artifactDir = .omx/artifacts/orchestrate/20260611-143022/
  │
  ▼
Phase 2: Pi CLI (ollama/gemma4) reads repo → explore-report.md
  │
  ▼
Phase 3: Claude reads explore-report, asks 2-4 clarifying questions one at a time
         → intent-summary.md, route-decision.md
  │
  ▼
Phase 4: Opus sub-agent reads explore-report + intent-summary → design.md
  │
  ▼
Phase 5: orchestrate.py --phase verify-design → Codex reviews design.md → codex-design-review.md
         (advisory: REJECTED concerns are surfaced but don't block)
  │
  ▼
Phase 6: Opus sub-agent reads design.md + codex-design-review.md → plan.md
         (writing-plans style: bite-sized tasks, TDD steps, file paths)
  │
  ▼
Phase 7: Claude presents plan to user, waits for approval or change requests
  │
  ▼
Phase 8: User approves → /orchestrate --resume <artifactDir> auto-executed
         orchestrate picks up at Phase 4.5 (write failing tests)
```

## Error Handling

- **Phase 2 (explore) timeout/failure:** Report error, offer retry or manual continue
- **Phase 4 (design) agent failure:** Report, offer retry with different prompt
- **Phase 5 (Codex) API error:** Show retriable flag — offer retry, skip (proceed with design as-is), or abort
- **Phase 5 REJECTED verdict:** Surface concerns (1-3 bullets), proceed by default unless fundamental flaw
- **Phase 7 user requests changes:** Re-run Phase 6 with change feedback, re-present plan
- **Phase 8 orchestrate --resume failure:** Report the exact error, preserve artifactDir, suggest manual resume command

## Invocation

```bash
/fiftybox-plans "<task description>"
```

The task description is passed unchanged to every helper phase (same contract as `/orchestrate`).

## Scope

**In scope:**
- SKILL.md for the 8-phase planning workflow
- Pi CLI + ollama provider integration for exploration
- Opus sub-agent design and plan writing
- Codex advisory review reuse
- Artifact compatibility with orchestrate --resume

**Out of scope:**
- Changes to orchestrate.py
- Implementation phases (tests, code, review, commit) — handled by `/orchestrate --resume`
- New orchestrate.py phases
- Changes to the Codex integration beyond passing `gpt-5.5-high`

## Testing / Verification

After implementation, verify by:
1. Running `/fiftybox-plans "add a simple feature"` on this repo
2. Confirming `explore-report.md` is written and non-empty
3. Confirming all 4 required resume artifacts are present in artifactDir
4. Confirming `/orchestrate --resume <artifactDir>` reaches Phase 4.5 without re-running setup/explore/design
