# Stage 07 - Step 6 metrics block + safety contract clauses + intro

## Goal
Make the budget self-correcting: every task records its real measurements, and
the gate becomes a contractual prohibition rather than advice.

## Inputs To Read
- `stage-02.md` (calibration wording to mirror)
- `.omx/artifacts/orchestrate/20260904T020937Z/logs/phase-6-implement.log` (`[DURATION]` format)
- `skills/fiftybox-local/SKILL.md` § intro / Step 6 / 안전 계약

## Files To Change
- `skills/fiftybox-local/SKILL.md`

## Steps
1. Add `#### 실행 메트릭 기록` at the end of Step 6: append a row per task to
   `<artifactDir>/gemma4-metrics.md` — task / spec lines / prompt lines (the
   Step 5 dry-run `wc`) / duration (`[DURATION]`) / changedFiles /
   result(success|retry|split|failed).
2. Append 3 clauses to `이 스킬 고유:` — un-gated dispatch forbidden; timeout
   value never raised (1800 fixed, splitting is the only response); executor
   `design.md` ≤60 with original in `design-source.md`.
3. Add one sentence to the intro: every task dispatches only inside the budget.

## Acceptance
- `grep -c 'gemma4-metrics.md'` ≥1; 3 new clauses greppable; bullet count ≥ original 9

## Verification
- `awk '/이 스킬 고유:/,0' <file> | grep -c '^- '` → 12

## Handoff Notes
- The `#### 실행 메트릭 기록` heading must exist or stage 08's anchor check fails.

## Result (applied 13:07, verified)
metrics=2 · h4=1 · 3 clauses=3 · bullets 9→12 · anchors 12/12 resolve
