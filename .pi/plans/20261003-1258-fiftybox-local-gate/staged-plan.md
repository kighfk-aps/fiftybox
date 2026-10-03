# Staged Plan

Source plan: `.sisyphus/plans/fiftybox-local-task-length-gate.md` (opencode/Atlas).
This document re-sizes it for the current Pi model and adds the live-code
corrections found while verifying anchors.

## Model Sizing

- Provider/model: `macstudio-qwen-flash-next` / `Jundot--Qwen3.8-Flash-Next-oQ4e-mtp`
  (local Mac Studio, ctx 262144, **maxTokens 16384**), thinking `high`
- Sizing signal: local model + 16K output cap ⇒ conservative stages. A long
  context window is **not** treated as capacity — the output cap and the local
  quality variance are the binding limits (this is the same failure mode the
  source plan is fixing).
- Stage sizing decision: **one document section per stage, 1 file, grep-based
  verification.** Every stage is a bounded insert/patch with a deterministic
  acceptance command. 8 stages instead of the source plan's 7+4.

## Deviations from the source plan (recorded, intentional)

1. **T0 probe runs fully offline.** Source plan runs `--phase setup` for real,
   which calls `pi --list-models macstudio-gemma4` and needs port 11235. That
   port is **down right now** (`curl` → `000`, host pings OK ⇒ services down,
   not the host). Live code shows `--phase setup --dry-run` still writes
   `summary.json` with the `worktree` key (orchestrate.py:1465–1499) and skips
   the Pi preflight (:1445), and `--phase implement --dry-run` returns before
   any Pi call (:2512). So `setup --dry-run` + `implement --dry-run` produces
   the real `implement-prompt.md` with no server. Gate stays measured, not
   assumed. If the server comes back, stage 01 re-runs the non-dry setup path
   as a bonus check.
2. **Scratch moves inside the project.** Source plan uses `/tmp/gemma4-gate-test`.
   Workspace AGENTS.md requires agent output to stay inside the running folder,
   so scratch is `.pi/plans/<ts>/scratch/gate-probe/`. `.omx/` is gitignored in
   the scratch repo so the `git status --porcelain` acceptance check is
   achievable (artifacts live inside the worktree root — orchestrate.py:1084).
3. **Commits are user-gated.** Stage 08 performs `cp` + `diff` + all grep
   verification but does **not** commit. The source plan asks for commits in two
   repos; harness safety rules require an explicit user request for commits.
   Stage 08 stops and presents the exact commit commands.
4. **`DESIGN_MD_MAX_LINES` 80 → 60 (arithmetic conflict, corrected by
   measurement).** The source plan's 80 / 15 / 120 cannot all hold: the
   orchestrate template adds a fixed **31 lines**, so `31 + 80 + 15 = 126 > 120`
   even with an empty intent summary — every compliant task would fail its own
   gate. 60 closes it (`31 + 60 + 15 + 14 = 120`) and sits closer to the
   evidence band (clean successes at design 22~54 lines). `PROMPT_MAX_LINES=120`,
   `TASK_SPEC_MAX_LINES=15`, `TASK_MAX_FILES=2` are unchanged (user-confirmed).
5. **New `INTENT_SUMMARY_MAX_LINES=14`.** `intent-summary.md` is concatenated
   into the same prompt (:2456) but had no budget in the source plan; the
   1481-line accident carried a 51-line intent block.

## Stages

1. Gate probe (dry-run, offline) — prove `implement-prompt.md` length tracks design length and that ≤120 / >120 are both reachable and distinguishable.
2. Insert `### Gemma4 실행 예산` constants block — design 80 / spec 15 / files 2 / prompt 120 + calibration rule.
3. Rewrite Step 1 — `design.md` becomes an ≤80-line execution contract; original preserved in `design-source.md`.
4. Rewrite Step 3 — quantitative decomposition gate: `Modify ONLY:` ownership line, ≤15 lines, ≤2 files, compound-task split.
5. Insert Step 5 dry-run length gate — `--dry-run` → `wc -l implement-prompt.md` → dispatch only if ≤120.
6. Patch 실패 처리 — delete the `3600` timeout retry, add `too_long` classification + half-split response.
7. Add Step 6 metrics block + 3 safety-contract clauses + intro sentence.
8. Sync executable → repo copy, run the full Definition-of-Done grep suite, then stop for commit approval.

Review wave F1–F4 from the source plan is **not** run automatically — offered
after stage 08 as a user choice.

## Global Acceptance

- `grep -c '3600' ~/.claude/skills/fiftybox-local/SKILL.md` → `0`
- `too_long`, `Gemma4 실행 예산`, `Modify ONLY`, `design-source.md`,
  `gemma4-metrics.md`, `--dry-run` all present in the executable copy
- `diff ~/.claude/skills/fiftybox-local/SKILL.md skills/fiftybox-local/SKILL.md` → exit 0
- frontmatter (first 4 lines) byte-identical to pre-change
- every existing `](#...)` anchor still resolves to a real heading
- measured evidence file for the pass (>boundary not required) and over
  (>120) dry-run cases exist
- `git status` shows **no** change to `orchestrate.py` or any other shared file

## Risks

- **Server offline (active).** 11235/11234 both `000`. Mitigation: whole gate
  is dry-run, so stages 01–08 all pass without the server; only the optional
  real-setup confirmation waits.
- **`intent-summary.md` is unbudgeted.** It is concatenated into the same
  prompt (orchestrate.py:2456) and the source plan gives it no cap. Mitigation:
  the 120-line prompt gate is measured on the *final* file, so an oversized
  intent summary is caught empirically; stage 05 text says which of design/task/
  intent to shrink.
- **Two-copy drift.** `~/.claude/skills` and the fiftybox repo both track
  SKILL.md. Mitigation: stage 08 enforces `diff` exit 0 before anything else.
- **Untracked scratch repo inside the repo.** Mitigation: scratch is confined
  to `.pi/plans/<ts>/scratch/`, self-reporting path in evidence, deletion
  offered to the user.
- **Anchors shift as sections are inserted.** Mitigation: every stage locates
  its target by heading text, not by line number.
