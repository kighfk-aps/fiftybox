# Stage 03 - Step 1: design.md becomes an <=60-line execution contract

## Goal
Stop `design.md` from being the thing that blows up the prompt: it becomes a
compressed executor contract, with the original preserved elsewhere.

## Inputs To Read
- `context-summary.md` § Stage 02 Next Stage Guardrails (thresholds are 60, not 80)
- `skills/fiftybox-local/SKILL.md` § Step 1
- `orchestrate.py:2438,2451` — implement reads `design.md` only

## Files To Change
- `skills/fiftybox-local/SKILL.md` (Step 1, append 3 paragraphs)

## Steps
1. Keep `design.md 필수` + `design.md not found in artifact directory` verbatim.
2. Append: contract compression rule (drop 배경/동기/대안/분할계획; keep
   파일 목록/인터페이스/행동 정의), `design-source.md` preservation, and a
   stop-if-not-compressible clause.

## Acceptance
- `grep -c 'design-source.md'` ≥1; `DESIGN_MD_MAX_LINES(60)` present in Step 1
- the original failure sentence still present

## Verification
- `awk '/### Step 1: 설계 수집/,/### Step 2/' skills/fiftybox-local/SKILL.md`

## Handoff Notes
- Stage 05 must cite the same 60-line design budget when telling the reader what
  to shrink first.

## Result (applied 13:05, verified)
design-source=1 · DESIGN_MD_MAX_LINES(60)=present · notfound-sentence=1
