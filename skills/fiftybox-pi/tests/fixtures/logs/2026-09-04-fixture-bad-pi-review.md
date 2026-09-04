# Pi Diff Review — fixture-bad

- diff: skills/fiftybox-pi/tests/fixtures/diff-bad.diff
- 명세: skills/fiftybox-pi/tests/fixtures/spec-add-greet.md
- 테스트: skills/fiftybox-pi/tests/fixtures/test-greet.py
- 모델: zai-coding/glm-5.3 (thinking: high)
- 시각: 2026-09-04T13:21:39
- 판정: BLOCKED (findings: 1)

## 리뷰 원문

BLOCKED

- [severity: blocking] Requirement 2 is entirely unimplemented: `greet` never raises `ValueError` for empty or whitespace-only names
  Evidence: The diff adds `src/greet.py` (fresh file, per `--- /dev/null`) containing only the signature, docstring, and `return f"Hello, {name}!"` — there is no validation branch. I verified no validation can come from elsewhere: a repo-wide grep shows no other `greet` definition, wrapper, or patch, and the acceptance test imports `src.greet.greet` directly (hypotheses that a decorator/conftest/monkeypatch or implicit string coercion supplied the rejection were all refuted by the diff text and grep). The acceptance tests themselves are sound and non-vacuous — `test_greet_rejects_empty` and `test_greet_rejects_whitespace` directly exercise the exact edge cases the spec names — so this is a missing implementation, not a mocked-away test. This is half-implemented behavior: spec requirement 1 is met, requirement 2 is absent. (No scope creep: the diff touches only the specified file.)
  Proposal: Add a guard at the top of the function body, e.g. `if not name or not name.strip(): raise ValueError("name must be a non-empty string")` before the return (this matches the repository's own reference fixture `skills/fiftybox-pi/tests/fixtures/diff-good.diff`). Do not weaken the tests to make the suite pass — the defect is in `src/greet.py`.
