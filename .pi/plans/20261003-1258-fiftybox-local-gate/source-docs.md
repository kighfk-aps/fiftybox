# Source Docs

- Plan (primary): `/Users/tanpapa/Desktop/develop-a/fiftybox/.sisyphus/plans/fiftybox-local-task-length-gate.md`
  (opencode Atlas session `ses_f003a9d85ffe7hyBEjoMOx4yHv`, 2026-10-03 12:32)
- Active-plan registry: `/Users/tanpapa/Desktop/develop-a/fiftybox/.sisyphus/boulder.json`
- Target file (executable copy): `/Users/tanpapa/.claude/skills/fiftybox-local/SKILL.md` (395 lines)
- Target file (repo copy): `/Users/tanpapa/Desktop/develop-a/fiftybox/skills/fiftybox-local/SKILL.md` (395 lines, `diff` exit 0 — currently identical)
- Engine reference (read-only, out of scope for edits): `/Users/tanpapa/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py` (3591 lines)
- Additional context: none

## Scope

Add a quantitative task-length gate to the `fiftybox-local` skill so the fixed
executor (Mac Studio Gemma4-26B-A4B QAT 4-bit via Pi CLI) only ever receives
dispatches it can actually finish.

Verified live anchors (re-checked against the live files, all match the plan):

| anchor | plan says | live |
|---|---|---|
| `## Executor (고정)` | 42 | 42 |
| `### 설정 게이트` | — | 63 |
| `## 실패 처리` / `### 분류표` / `### 대응` / `### Failure Report Format` | 169–211 | 157 / 169 / 180 / 200 |
| `### Step 1` | 217–227 | 217 |
| `### Step 3` | 243–255 | 243 |
| `### Step 5` | 265–290 | 265 |
| `### Step 6` | 292–316 | 292 |
| `## 안전 계약` | 367–395 | 367 |
| `phase_implement()` | 2433–2519 | 2433 |
| dry_run branch | 2512 | 2512 |
| `prompt_path` (implement-prompt.md) | 2509 | 2509 |

Engine facts confirmed by reading `orchestrate.py`:

- `phase_implement` single-task prompt = fixed template (~31 lines) + fenced
  task + **full `design.md`** + `intent-summary.md` (optional) → written to
  `implement-prompt.md`. Design length dominates prompt length, so
  design ≤80 + task ≤15 + overhead ≈31 lands just under the 120 gate.
- `parse_task_batches` empty + no json block ⇒ single-task mode (confirms the
  "`Files:` ownership must be carried in the task text" rationale).
- dry_run branch (2512) returns **before** `repo_snapshot()` and before any Pi
  call — only writes `implement-prompt.md` + `[DRY RUN]` log.

## Non-goals

- No changes to `orchestrate.py` or any shared script (shared with
  fiftybox-orchestration / fiftybox-execute lanes).
- No change to the fixed executor triple
  (`pi` / `macstudio-gemma4` / `mlx-community--gemma-4-26B-A4B-it-qat-4bit`),
  no model-switch proposals.
- No re-introduction of any timeout increase (the `3600` retry must disappear).
- No full rewrite of the existing Step 1–10 / preflight / failure-table
  structure — insert and patch only.
- No change to the frontmatter `description` trigger wording.
- No new test infrastructure.
