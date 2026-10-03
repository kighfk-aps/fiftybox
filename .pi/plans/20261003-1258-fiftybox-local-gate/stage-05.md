# Stage 05 - Step 5: dry-run length gate before real dispatch

## Goal
No dispatch leaves this skill without a measured prompt length.

## Inputs To Read
- `evidence/stage-01-dryrun-probe.txt` (measured 33 / 79 / 139)
- `skills/fiftybox-local/SKILL.md` § Step 5
- `orchestrate.py:2509-2521` — dry_run returns before any Pi call

## Files To Change
- `skills/fiftybox-local/SKILL.md` (insert between preflight and the nohup block)

## Steps
1. Insert a `--dry-run` foreground command with the **identical** real-dispatch
   flag set, then `wc -l "<artifactDir>/implement-prompt.md"`.
2. ≤120 → proceed to nohup; >120 → do not dispatch, back to Step 3 split or
   Step 1 compression, re-run gate. Shrink order: design → task spec → intent.
3. Note the `dry_run` state left in `summary.json` is harmless (overwritten).
4. Declare an un-gated dispatch a safety-contract violation (closed in stage 07).
5. Do not touch the nohup block or the `EXIT_CODE=` polling.

## Acceptance
- order dry-run → wc → 120 → nohup
- nohup block byte-identical

## Verification
- `awk '/### Step 5:/,/### Step 6:/' <file> | grep -n -- '--dry-run\|wc -l\|PROMPT_MAX_LINES\|nohup'`

## Handoff Notes
- The inserted command block is the exact text stage 08 executes verbatim.

## Result (applied 13:06, verified)
offsets dry-run 460 < wc 471 < gate120 695 < nohup 730 · polling intact
