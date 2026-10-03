# Stage 04 - Step 3: quantitative decomposition gate

## Goal
Make task decomposition measurable: ownership line + hard ceilings + split rules.

## Inputs To Read
- `stage-02.md` (constant names), `context-summary.md` § Stage 02
- `skills/fiftybox-local/SKILL.md` § Step 3
- `orchestrate.py:677-683` — ownership sections exist only in multi-task mode

## Files To Change
- `skills/fiftybox-local/SKILL.md` (Step 3)

## Steps
1. Point at the budget table via anchor `#gemma4-실행-예산`.
2. Add mandatory `Modify ONLY:` ownership line + `lines: spec N` to the example list.
3. Add ceilings: spec ≤15, files ≤2, no "A하고 B하고 C" compound tasks,
   same-file >15 lines → sequential half-split (signature+stub → logic → errors),
   each half gets its own Step 4 Red test.
4. Keep the ```json task-batches ban verbatim.

## Acceptance
- `grep -c 'Modify ONLY'` ≥1 · `TASK_SPEC_MAX_LINES(15)`=1 · `TASK_MAX_FILES(2)`=1
- json ban still present

## Verification
- `awk '/### Step 3:/,/### Step 4:/' skills/fiftybox-local/SKILL.md`

## Handoff Notes
- Stage 05's shrink order (design → spec → intent) must stay consistent with the
  `31 + design + spec + intent` model.

## Result (applied 13:06, verified)
Modify ONLY=3 · spec15=1 · files2=1 · 복합=1 · 하프=1 · json ban=2
