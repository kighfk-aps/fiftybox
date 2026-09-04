# Pi Diff Review — fixture-good

- diff: skills/fiftybox-pi/tests/fixtures/diff-good.diff
- 명세: skills/fiftybox-pi/tests/fixtures/spec-add-greet.md
- 테스트: skills/fiftybox-pi/tests/fixtures/test-greet.py
- 모델: zai-coding/glm-5.3 (thinking: high)
- 시각: 2026-09-04T13:20:46
- 판정: APPROVED (findings: 0)

## 리뷰 원문

APPROVED

- [minor] Return value strips the name, diverging from the spec's "exactly `Hello, <name>!`"
  Evidence: Spec requirement 1 says greet "Returns exactly `Hello, <name>!` for a non-empty name." The diff returns `f"Hello, {name.strip()}!"`, so `greet(" Ada ")` yields `"Hello, Ada!"` rather than `"Hello,  Ada !"`. Stripping is only mandated for *validation* (requirement 2); the spec never asks to normalize the name in the output. Both named requirements (empty / whitespace-only rejection, canonical greeting) are correctly implemented, so this is an edge deviation, not a broken requirement.
  Proposal: Either change the return to `return f"Hello, {name}!"`, or (if trimming is intended) get the spec amended to say so — right now the code silently extends the contract.

- [minor] Acceptance tests don't cover the padded-name case implied by "exactly"
  Evidence: `test-greet.py` covers `"world"`, `""`, and `"   "` — the two cases requirement 2 names and one canonical case for requirement 1. No test exercises a non-whitespace-only name with surrounding whitespace (e.g. `" world "`), which is precisely the input where the implementation's `.strip()` departs from the literal spec, so that behavior is untested in either direction. The tests are otherwise real (no mocks, concrete string equality against the spec's exact format) and not vacuous.
  Proposal: Add `assert greet(" world ") == "Hello,  world !"` (or the trimmed expectation, once the spec question above is resolved) so the "exactly" requirement is pinned down for padded names.

Notes on the other judged dimensions: the diff touches only `src/greet.py` as specified (no scope creep), the signature matches `def greet(name: str) -> str`, and requirement 2 is fully implemented — `not name` catches `""` and `not name.strip()` catches whitespace-only, both raising `ValueError`.
