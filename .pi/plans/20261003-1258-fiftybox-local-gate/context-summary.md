# Context Summary

Append-only. Each block is written from live command output, not from memory.

## Stage 01 Complete - 2026-10-03 13:02

### Completed
- Dry-run length gate probed on a scratch repo with **no SKILL.md edits** and
  **no server**: `setup --dry-run` then `implement --dry-run` produced real
  `implement-prompt.md` at three input sizes.

### Files Touched
- `.pi/plans/20261003-1258-fiftybox-local-gate/scratch/gate-probe/` (throwaway git repo, nested, gitignored `.omx/`+`.worktrees/`)
- `.pi/plans/20261003-1258-fiftybox-local-gate/evidence/stage-01-dryrun-probe.txt`
- `.pi/plans/20261003-1258-fiftybox-local-gate/evidence/stage-01-floor-skeleton.txt` (the 33-line prompt skeleton)
- repo: no tracked file modified

### Current Truth
- `prompt = 31 + design + spec + intent` — fixed boilerplate measured at
  **31 lines** (floor run: design 1 + spec 1 + no intent ⇒ 33).
- Measured points: design 40 → prompt **79**; design 100 → prompt **139**.
- Gate boundary 120 is cleanly between the two ⇒ `wc -l implement-prompt.md`
  is a valid pre-dispatch discriminator.
- dry_run returns before `repo_snapshot()`; log line
  `[DRY RUN] Skipping Pi CLI implementation` proves Pi was never called.
- Prompt section order (real): `## Task Description` → `## Design Specification`
  → `## Intent Summary` → `## Constraints` → `## Final Response`.
- Mac Studio host is UP (ping 0.95ms) but **both mlx-serve ports 11235 and
  11234 return 000** — servers are down right now.
- `--phase setup` without `--dry-run` requires the live server
  (`pi --list-models macstudio-gemma4`, orchestrate.py:1445). With
  `--dry-run` it does not, and still records the `worktree` key (:1465-1499),
  which is what `phase_implement` needs.
- Omitting `--model` silently defaults to `deepseek-v4-flash` in setup output
  ⇒ the fixed 3-axis must always be explicit.

### Verification
- `git -C scratch/gate-probe status --porcelain` → empty (PASS)
- `wc -l implement-prompt.md` → 33 / 79 / 139 (PASS / PASS / OVER) (PASS)
- `grep -c 'DRY RUN' logs/phase-6-implement.log` → 1 (PASS)

### Decisions
- **`DESIGN_MD_MAX_LINES` 80 → 60.** The source plan's 80/15/120 is
  arithmetically unsatisfiable: 31 + 80 + 15 = 126 > 120 even with an empty
  intent summary. 60 closes it (31 + 60 + 15 + 14 = 120) and is closer to the
  evidence band (clean successes at design 22~54 lines). `PROMPT_MAX_LINES=120`
  and `TASK_SPEC_MAX_LINES=15` / `TASK_MAX_FILES=2` (user-confirmed) are kept.
- **New `INTENT_SUMMARY_MAX_LINES=14`.** `intent-summary.md` is concatenated
  into the same prompt and was unbudgeted in the source plan; the 1481-line
  accident had a 51-line intent block.
- Scratch lives inside the project (`.pi/plans/<ts>/scratch/`) instead of
  `/tmp`, per workspace AGENTS.md.

### Next Stage Guardrails
- Stage 02 must insert `### Gemma4 실행 예산` **after** the mlx-serve paragraph
  and **before** `### 설정 게이트` (live: line 63 is `### 설정 게이트`), located
  by heading text — line numbers shift after every insert.
- Must carry: 60 / 15 / 2 / 120 / 14, the measured `31 + design + spec + intent`
  model, `max_tokens 16384` and `IMPL_TIMEOUT 1800` as the real bottlenecks.
- Do not touch the frontmatter (first 4 lines) or any other section.
- If the server is needed by any later stage, re-healthcheck 11235 first.

### Open Risks
- Mac Studio mlx-serve is down — stages 02–08 are doc-only and unaffected, but
  the *runtime* effect of the gate cannot be observed until 11235 returns.
- Threshold change (80→60) is a deviation from a number the user may have seen
  in the opencode plan — surface it before committing.

## Stage 02 Complete - 2026-10-03 13:05

### Completed
- Inserted `### Gemma4 실행 예산` between the mlx-serve paragraph and
  `### 설정 게이트` — 5-constant budget table + the measured `31 + design + spec
  + intent` arithmetic + bottleneck note + calibration rule.

### Files Touched
- `skills/fiftybox-local/SKILL.md` (repo copy, +27 lines: 395 → 422)
- `~/.claude/skills/fiftybox-local/SKILL.md` (identical; re-synced after the
  first insert)

### Current Truth
- `wc -l` = 422 on both copies, `diff` exit 0.
- New section at line 63, `### 설정 게이트` now at line 90.
- Constant counts: DESIGN_MD_MAX_LINES 3, TASK_SPEC_MAX_LINES 1,
  TASK_MAX_FILES 1, INTENT_SUMMARY_MAX_LINES 1, PROMPT_MAX_LINES 3.
- Frontmatter (`head -4`) byte-identical to the original.

### Verification
- `grep -c '### Gemma4 실행 예산'` → 1; all 5 constants ≥1; order 63 < 90 (PASS)
- `diff exec repo` → exit 0 (PASS)

### Decisions
- **Authoring moves inside the project.** From stage 03 on, edits target the
  repo copy `skills/fiftybox-local/SKILL.md`; stage 08 copies it back to
  `~/.claude/skills/fiftybox-local/SKILL.md`. Reason: workspace AGENTS.md
  forbids writing outside the running folder. Same end state as the source plan.
- `DESIGN_MD_MAX_LINES=60` (not the source plan's 80) — see Stage 01 decision.

### Next Stage Guardrails
- All thresholds are now **60 / 15 / 2 / 14 / 120** — any stage text that says
  80 is wrong and must be corrected, not copied.
- Step 1 must keep the existing `design.md not found in artifact directory`
  sentence and the `--skip-verify` note untouched.
- Stage 05's gate must reference the same `PROMPT_MAX_LINES=120`.

### Open Risks
- `~/.claude/skills` copy is now edited; if stage 08 is skipped the two copies
  stay identical only because of the mid-stage resync — do not leave the repo
  copy behind again.

## Stage 03 Complete - 2026-10-03 13:05

### Completed
- Step 1 now demands an executor execution contract ≤60 lines, preserves the
  original in `design-source.md`, and forbids overshooting the budget.

### Files Touched
- `skills/fiftybox-local/SKILL.md`: Step 1 +3 paragraphs (+13 lines)

### Current Truth
- orchestrate.py:2438/2451 read **only** `design.md` — `design-source.md` is
  never sent to the executor, so preserving it is free.
- 422 → 435 lines.

### Verification
- `awk '/### Step 1:/,/### Step 2/'` shows compression + preservation + stop
  clauses; `grep -c 'design.md not found in artifact directory'` → 1 (PASS)

### Decisions
- Wrote "실행계약" wording so a reader cannot confuse it with the design doc.

### Next Stage Guardrails
- Step 3 must not reintroduce a parallel/batch example (json ban).

### Open Risks
- None new.

## Stage 04 Complete - 2026-10-03 13:06

### Completed
- Step 3 rewritten as a quantitative gate: `Modify ONLY:` ownership line,
  `lines: spec N`, ≤15 spec / ≤2 files, compound-task ban, same-file
  sequential half-split, per-half Red tests.

### Files To Keep In Mind
- `skills/fiftybox-local/SKILL.md`: 435 → 455 lines

### Current Truth
- Ownership sections are generated **only** in multi-task mode, so the task text
  is the only carrier in single-task mode — the `Modify ONLY:` line is load-bearing.
- json task-batches ban still appears twice (Step 3 + 안전 계약).

### Verification
- `Modify ONLY`=3, `TASK_SPEC_MAX_LINES(15)`=1, `TASK_MAX_FILES(2)`=1,
  `복합 태스크`=1, `하프 연속 태스크`=1 (PASS)
- anchor `#gemma4-실행-예산` resolves (checked in stage 08)

### Decisions
- Kept the original sequential example and appended fields to it instead of
  replacing it, so the Step 3 shape stays recognizable.

### Next Stage Guardrails
- Stage 05 must not modify the nohup block or `EXIT_CODE=` polling.

### Open Risks
- None new.

## Stage 05 Complete - 2026-10-03 13:06

### Completed
- Dry-run length gate inserted between preflight and the real nohup dispatch.

### Files Touched
- `skills/fiftybox-local/SKILL.md`: 455 → 483 lines

### Current Truth
- dry_run returns before `repo_snapshot()` — measured prompt cost is zero server
  cost, so the gate can run even while 11235 is down.
- Gate flags must equal the real dispatch flags exactly; `--skip-verify` and
  `--implementation-timeout 1800` appear in both blocks (grep count 2).
- 455 → 483 lines.

### Verification
- offsets inside Step 5: dry-run 460 < wc 471 < PROMPT_MAX_LINES 695 < nohup 730
  (PASS). Polling block `grep -o 'EXIT_CODE=[0-9]*'` untouched.

### Decisions
- Documented shrink priority `design → spec → intent` directly from the
  `31 + design + spec + intent` model, so the gate is actionable rather than a
  dead end.

### Next Stage Guardrails
- The command block here is executed verbatim in stage 08 — do not reformat it.

### Open Risks
- If a user adds `--dry-run` to a real dispatch by copy-paste error the gate
  would look like a success; the block keeps `--dry-run` visually last to reduce
  that risk.

## Stage 06 Complete - 2026-10-03 13:06

### Completed
- Deleted the `--implementation-timeout 3600` retry; added `too_long`
  classification (3 signals), a split-on-timeout response, budget-first
  reclassification of `no_changes`, and `예산 점검:` in the failure report.

### Files Touched
- `skills/fiftybox-local/SKILL.md`: 분류표 +3 rows, 대응 bullets replaced,
  Failure Report Format +2 lines. 483 → 496 lines.

### Current Truth
- `grep -c '3600'` → **0** file-wide.
- `too_long` appears 6×; `태스크당 1회` still 3×; "오케스트레이터가 대신 구현"
  prohibition still present.
- `EXIT_CODE=3` now splits into two rows: over-budget ⇒ `too_long`, within-budget
  ⇒ `no_changes`.

### Verification
- `grep -n '3600' skills/fiftybox-local/SKILL.md; echo exit=$?` → no match, exit 1
- `sed -n '/### 분류표/,/### Failure/p'` shows the new rows and split response (PASS)

### Decisions
- Truncation ("응답이 문장 도중 잘림") classified `too_long` rather than `unknown`,
  because `max_tokens 16384` makes it a length symptom, not a random failure.

### Next Stage Guardrails
- Stage 07's safety clause must not soften "timeout 값은 올리지 않는다".

### Open Risks
- A genuine server-side timeout (slow but correctly-sized task) now also triggers
  splitting; the pre-split healthcheck is the discriminator.

## Stage 07 Complete - 2026-10-03 13:07

### Completed
- `#### 실행 메트릭 기록` block at the end of Step 6 with the metrics row format;
  3 new 안전 계약 clauses; intro sentence tying dispatch to the budget.

### Files Touched
- `skills/fiftybox-local/SKILL.md`: 496 → 523 lines

### Current Truth
- Safety-contract unique bullets 9 → 12; nothing deleted.
- All 12 internal anchors resolve after the new heading exists.
- Metrics `prompt 줄수` is defined as the Step 5 dry-run `wc` value — the same
  number the gate used, so calibration cannot drift from the gate.

### Verification
- `grep -c 'gemma4-metrics.md'` → 2; new clauses grep → 3; `awk '/이 스킬
  고유:/,0' | grep -c '^- '` → 12 (PASS)

### Decisions
- Metrics live in `<artifactDir>` (per-run, gitignored) rather than in the repo,
  so no new tracked state is introduced.

### Next Stage Guardrails
- Sync direction is repo → exec only; never hand-edit the exec copy again.

### Open Risks
- Nobody has run 5 tasks yet, so calibration thresholds are theory until
  `gemma4-metrics.md` accumulates.

## Stage 08 Complete - 2026-10-03 13:10

### Completed
- Executable copy synced from the repo copy; full DoD suite executed; the Step 5
  gate command extracted verbatim from the finished document and executed.

### Files Touched
- `~/.claude/skills/fiftybox-local/SKILL.md` ← cp of `skills/fiftybox-local/SKILL.md`
- `.pi/plans/20261003-1258-fiftybox-local-gate/evidence/stage-08-dod.txt`
- `.pi/plans/20261003-1258-fiftybox-local-gate/evidence/stage-08-doc-command-run.txt`

### Current Truth
- `diff exec repo` → identical, 523 lines each.
- Verbatim doc command run: exit 0, design 58 + spec 1 → **prompt 92 ≤ 120**,
  `[DRY RUN]` marker 1 (Pi never called).
- `orchestrate.py` is dirty in `~/.claude/skills` from **before** this session
  (mtime 2026-09-28 16:57:56) and contains **0** occurrences of the gate
  vocabulary — not touched here.
- fiftybox repo tracked diff: `skills/fiftybox-local/SKILL.md` only.

### Verification
- All 12 DoD checks PASS → `evidence/stage-08-dod.txt`

### Decisions
- **No commit.** The source plan asks for commits in two repos; harness rule says
  commits require an explicit user request. Stage 08 stopped at "ready to commit"
  and presented the commands.

### Next Stage Guardrails
- If the user approves commits: stage both repos with the same message, no push
  unless asked, never force.
- If the user objects to `DESIGN_MD_MAX_LINES=60`, the fix is a single table row
  plus the Step 1 mentions — but the 120 gate cannot coexist with design 80
  (31+80+15 = 126).

### Open Risks
- Mac Studio 11235/11234 down: the gate's runtime effect is unverified.
- Review wave F1–F4 not dispatched (offered as a user choice).
- Nested scratch repo `.pi/plans/<ts>/scratch/gate-probe/` still on disk.

## Commit & Push - 2026-10-03 13:14 (user requested)

### Completed
- fiftybox repo `c43842a` — SKILL.md gate + this plan dir (16 files, +1021/-9),
  pushed to origin/main `eefe7bc..c43842a` (fast-forward, now 0/0 in sync).
- `~/.claude/skills` split into two commits so the gate diff stays readable:
  `63b255b` carries the **pre-existing** 299→395-line Gemma4 executor revision
  that was never committed in that repo, `b17917e` is the gate (395→523,
  +137/-9).

### Current Truth
- `~/.claude/skills` has **no remote configured** — push is impossible there; the
  two commits are local-only.
- Both SKILL.md copies byte-identical at 523 lines; neither shows dirty.
- Excluded on purpose: `.pi/plans/<ts>/scratch/` (nested git repo),
  `.sisyphus/` (opencode state), and 68 pre-existing dirty files in
  `~/.claude/skills`.

### Open Risks
- Runtime copy is unpushed — a machine rebuild from the GitHub repo alone would
  still lose the gate for the Claude runtime path.

## Remote created for the runtime copy - 2026-10-03 13:20 (supersedes the no-remote risk above)

- Created private repo **`github.com/kighfk-aps/myfiftybox`** (gh CLI, account
  kighfk-aps, `repo` scope) and pushed `~/.claude/skills` main.
- `git ls-remote` → `b17917e…` == local HEAD; pushed tree = 201 files;
  remote blob `fiftybox-local/SKILL.md` = 25187 bytes with **15** gate markers.
- Pre-push secret scan of committed content: only hits were the alphabet-sequence
  fake keys inside `orchestrate/tests/test_orchestrate.py` redaction tests.
- **Still not backed up:** 21 modified + 18 deleted + 29 untracked working-tree
  entries in `~/.claude/skills`, including whole untracked skills
  (`fiftybox-config/`, `scholar-kit/`, `grok-review/`, `fiftybox-cc-execute/`, …).
  A restore from `myfiftybox` today yields the committed state, not the live one.
- Blocker for a snapshot commit: `sprite-gen/.venv` is **76M** and `.gitignore`
  does not cover root `.venv/` — must gitignore before any `git add -A`.
  (Secret scan of untracked content: 1 hit, `AKIAAQAAAAAABAAH` inside Pillow in
  that venv — placeholder-shaped, not a credential.)

## Skills backup (option 2) - 2026-10-03 13:35

### Completed
- `myfiftybox` pushed through 4 more commits: `873f2af` (10 never-tracked skills,
  50 files), `ce83fbd` (review-voc-crawler amazon adapter + CSV export, 17 files),
  `51be674` (fiftybox-cc-execute, grok-review), `37ab4e1` (correction).
  Remote tree 201 → 289 entries. local == origin.

### Current Truth
- Two "untracked skills" were **embedded git repos**: `sprite-gen/` (clone of
  aldegad/sprite-gen, **local commits on top**, 76M `.venv`) and
  `svg-eli5-archify/` (clone of kcc920926-droid/explain_me, **0 ahead**, clean).
  `git add` turned svg-eli5 into a mode-160000 gitlink — caught by the
  `git diff --cached --summary` guard, unstaged, both gitignored.
- `fiftybox-cc-execute/scripts/cc_preflight.py` is a mode-120000 symlink; its
  blob is a path string. Canonical content is committed at
  `fiftybox-execute/scripts/cc_preflight.py`, so nothing is lost, but the link is
  absolute. Recorded in `BACKUP-COVERAGE.md` with a relative-link fix.
- 7 more entries are symlinks leaving this repo (ego-browser, gpt-image,
  humanize×3, modal-h3-video, find-skills/orchestration → ~/.agents/skills) —
  left untracked on purpose and documented.
- `amazon_login.cjs` is credential-free: it waits for the `at-main` cookie name in
  the persistent browser profile and persists only `{loggedIn: bool}`.

### Verification
- every staging step guarded: `git diff --cached --summary | grep -E 'mode 160000|mode 120000'`
  and a junk/secret name grep, run before each commit
- gate file untouched throughout: 523 lines, identical to the fiftybox repo copy
- remote blob size `fiftybox-local/SKILL.md` = 25187 bytes

### Remaining uncommitted in ~/.claude/skills (restore gap, by choice)
- 11 modified: `orchestrate.py`, `fiftybox-orchestration/SKILL.md`,
  `fiftybox-execute/SKILL.md`, `ideate`, `open-design`, `opencode-implement/*`, …
- 18 deleted: retired `orchestrate/`, `pi-execute/`, `local-small/`,
  `fiftybox-local-execute/`
- 8 symlinks (documented)
- `sprite-gen/` needs its own private repo — its local commits exist nowhere else

## Mirror closed — deletions + modifications pushed - 2026-10-03 13:45

### Completed
- `6acd148` chore(skills): retirement of orchestrate / pi-execute / local-small /
  fiftybox-local-execute + obsolete fiftybox-local scripts — **18 files, 0 insertions**
- `b60a8ba` feat(skills): live engine + skill revisions — **11 files, +919/-504**
- pushed; `myfiftybox` HEAD `b60a8ba` == origin, tree 289 → 257 entries
  (18 files removed + 14 emptied directories)

### Current Truth
- 5 of the 11 modified files were **byte-identical to this fiftybox repo's
  copies** (`orchestrate.py` 158,878B, `fiftybox-execute/SKILL.md` 29,671B,
  `fiftybox-orchestration/SKILL.md`, `config.example.json`,
  `fiftybox-plans/SKILL.md`) — the mirror was stale, not divergent.
- 6 are runtime-only and existed nowhere else until now: `ideate/SKILL.md`,
  `open-design/SKILL.md`, `opencode-implement/spec.md`, `workflow.md`, and the
  two `claude_opencode_implement.py` (`--agent-name` default Codex → OpenCode).
- All 18 deleted files verified readable at `HEAD~2` before committing the
  deletion — recoverable, not destroyed.
- `python3 -m py_compile` passes on `orchestrate.py` and both
  `claude_opencode_implement.py`.
- `orchestrate/config.json` is the only survivor of the retired directory and is
  ignored by `*/config.json` — never staged.
- Working tree now clean except the 8 documented symlinks.

### Verification
- `git diff --cached --summary | grep -E 'mode 160000|mode 120000'` → 0 before each commit
- secret scan on added diff lines only (`git diff -U0 | grep '^+'`) → 0 hits
- remote spot check by size: orchestrate.py 158,878 == local; SKILL.md 29,671 == local

### Remaining uncovered
- 8 symlinks whose targets live outside the repo (`~/.agents/skills`, `~/.codex/skills`,
  `~/.claude/tools/im-not-ai`, `~/.local/share/...`) — listed in `BACKUP-COVERAGE.md`
- `sprite-gen/` — embedded repo with local commits that exist nowhere else; needs
  its own private repo
