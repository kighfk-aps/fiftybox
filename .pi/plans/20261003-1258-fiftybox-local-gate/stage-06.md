# Stage 06 - 실패 처리: delete the 3600 retry, add `too_long`

## Goal
Remove the only documented path that makes a too-long task worse, and give
length failure a name.

## Inputs To Read
- `skills/fiftybox-local/SKILL.md` § 분류표 / 대응 / Failure Report Format
- `context-summary.md` § Stage 01 (max_tokens 16384 truncation signal)

## Files To Change
- `skills/fiftybox-local/SKILL.md`

## Steps
1. Classification table: split the old `EXIT_CODE=3 → no_changes` row into
   `too_long` (over budget) and `no_changes` (within budget); add truncation and
   `changedFiles` < spec rows.
2. Replace the timeout bullet: **no timeout increase** — split at the behaviour
   boundary into 2 halves, rewrite each half's Red test (Step 4 준용), dispatch the
   first half, consumes the 1-retry budget, report if a half still fails.
3. Add a `too_long` bullet pointing at the budget anchor and the Step 5 gate.
4. `no_changes` now checks budget first and reclassifies to `too_long`.
5. Failure Report Format: add `too_long` to the enum + a `예산 점검:` line +
   split as recommended action.

## Acceptance
- `grep -c '3600'` == 0 · `grep -c 'too_long'` ≥2 · `태스크당 1회` preserved

## Verification
- `grep -n '3600' skills/fiftybox-local/SKILL.md; echo exit=$?`

## Handoff Notes
- Stage 07's safety clause must repeat "no timeout increase" so the two agree.

## Result (applied 13:06, verified)
3600=0 · too_long=6 · 태스크당 1회=3 · 오케스트레이터 대신 구현 금지=1
