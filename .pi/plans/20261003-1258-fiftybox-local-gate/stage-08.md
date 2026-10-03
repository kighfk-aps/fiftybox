# Stage 08 - Sync, run Definition of Done, stop for commit approval

## Goal
Both SKILL.md copies identical, every acceptance check executed with real
output, nothing committed without the user saying so.

## Inputs To Read
- `staged-plan.md` § Global Acceptance
- both SKILL.md copies

## Files To Change
- `~/.claude/skills/fiftybox-local/SKILL.md` ← `cp` from the repo copy

## Steps
1. `cp skills/fiftybox-local/SKILL.md ~/.claude/skills/fiftybox-local/SKILL.md`; `diff` exit 0.
2. Run every DoD grep (3600 / too_long / Modify ONLY / gemma4-metrics /
   design-source / budget section / anchors / frontmatter).
3. **Execute the Step 5 gate command extracted verbatim from the document** to
   prove the doc is runnable, not just searchable.
4. Prove no out-of-scope file was touched (`orchestrate.py` dirt is pre-existing
   — check mtime and grep for gate vocabulary = 0).
5. Stop. Present commit commands to the user. Do not commit.

## Acceptance
- see `evidence/stage-08-dod.txt`

## Verification
- `cat .pi/plans/20261003-1258-fiftybox-local-gate/evidence/stage-08-dod.txt`

## Handoff Notes
- Commit message proposed: `docs(fiftybox-local): add gemma4 task-length gate
  (spec<=15, files<=2, design<=60, prompt<=120) and split-on-timeout`
- Scratch repo `.pi/plans/<ts>/scratch/gate-probe/` is nested — offer deletion.

## Result (applied 13:10)
All 12 DoD checks PASS. Commits withheld pending user approval.
