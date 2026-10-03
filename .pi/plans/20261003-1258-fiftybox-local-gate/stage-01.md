# Stage 01 - Gate probe (dry-run, offline)

## Goal
Prove, with real command output and **zero SKILL.md edits**, that
`implement-prompt.md` length is measurable before dispatch and that both a
passing (≤120) and an over (>120) case are reachable and distinguishable.

## Inputs To Read
- `.pi/plans/20261003-1258-fiftybox-local-gate/staged-plan.md`
- `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py:2433-2521` (prompt assembly + dry_run branch)
- `~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py:1465-1500` (setup dry_run still records `worktree`)
- `~/.claude/skills/fiftybox-local/SKILL.md:229-235, 272-281` (flag shapes)

## Files To Change
- none in the repo. Scratch only under
  `.pi/plans/20261003-1258-fiftybox-local-gate/scratch/gate-probe/`
- evidence under `.pi/plans/20261003-1258-fiftybox-local-gate/evidence/`

## Steps
1. `mkdir -p .pi/plans/<ts>/{scratch,evidence}`; `cd scratch/gate-probe`;
   `git init -q`; write `.gitignore` with `.omx/` and `.worktrees/`;
   `git add -A && git commit -qm probe`.
2. Healthcheck (record, do not block): `curl -s -o /dev/null -w '%{http_code}'
   --max-time 10 http://100.115.199.115:11235/v1/models`.
   - `200` → also run the non-dry `--phase setup` variant as a bonus check.
   - non-200 → continue with **`--dry-run` setup** (works offline, verified).
3. Write `design.md` with 40 content lines (PASS case) into the artifactDir.
4. `python3 ~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py
   --phase setup --task "gate probe" --cwd "$PWD" --implement-agent pi
   --provider macstudio-gemma4 --dry-run` → capture `artifactDir` from JSON.
5. Write the fixed 3-axis `model-choice.json` + a 3-line `intent-summary.md`.
6. `--phase implement --dry-run` with the same flags + `--artifact-dir` +
   `--model mlx-community--gemma-4-26B-A4B-it-qat-4bit`; `wc -l` the produced
   `implement-prompt.md`; save to `evidence/stage-01-dryrun-pass.txt`.
7. Replace `design.md` with a 100-line sample; re-run step 6; save to
   `evidence/stage-01-dryrun-over.txt`.
8. Record prompt skeleton (`grep -n '^## ' implement-prompt.md`) so later
   stages can cite the real section order.

## Acceptance
- `git -C scratch/gate-probe status --porcelain` → empty
- PASS case: `wc -l implement-prompt.md` ≤ 120, number recorded in evidence
- OVER case: `wc -l implement-prompt.md` > 120, number recorded in evidence
- log contains `DRY RUN` (proves Pi was never called)
- measured **template overhead** (prompt lines minus design lines) recorded —
  stage 02 uses it to sanity-check the 80/15/120 triangle

## Verification
- `cat .pi/plans/<ts>/evidence/stage-01-dryrun-pass.txt`
- `cat .pi/plans/<ts>/evidence/stage-01-dryrun-over.txt`

## Handoff Notes
- Report both measured numbers; if PASS > 120 or OVER ≤ 120 the constants in
  stage 02 must be recalibrated before any doc edit — do not proceed.
- Server state (200/000) must be carried into the final report.
