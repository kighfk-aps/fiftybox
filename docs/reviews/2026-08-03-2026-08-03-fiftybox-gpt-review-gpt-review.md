# GPT Review — 2026-08-03-fiftybox-gpt-review.md

- 대상: docs/superpowers/plans/2026-08-03-fiftybox-gpt-review.md
- 모델: gpt-5.6-terra (effort: high)
- 시각: 2026-08-03T10:37:38
- 판정: REVISE

## 리뷰 원문

REVISE

- [severity: major] Task 1 has no safe rollback path for a system-wide executable replacement.
  Evidence: it deletes `/opt/homebrew/bin/codex` before creating the replacement link, with no backup or recovery procedure if linking or the subsequent authentication check fails.
  Proposal: record the existing target/content first, use an atomic replacement where possible, and specify how to restore the shim or previous link on failure.

- [severity: major] The proposed stubbed-Codex tests will not reliably execute.
  Evidence: tests set `PATH` to only the temporary `bin` directory, while the stub shebang is `#!/usr/bin/env bash`; `env` then cannot locate `bash`.
  Proposal: preserve the original PATH after the temporary directory, or use an absolute shell path in the stub; add a test run proving the success stub actually executes.

- [severity: major] CLI input validation and its exit-2 contract are incomplete.
  Evidence: `--effort` accepts arbitrary strings, `--timeout` accepts zero/negative values, and unreadable document/context files can raise uncaught exceptions; the plan only tests missing paths.
  Proposal: define valid effort values and positive timeout requirements, catch read failures, return exit 2 consistently, and add tests for each invalid-input path.

- [severity: major] Pipeline integration lacks an end-to-end behavioral regression test.
  Evidence: Task 5 tests `resolve_reviewer()` and directly calls `run_design_review_agent()`, but does not run `phase_verify_design()` with parsed Codex flags to prove selection, command execution, result recording, and advisory/strict handling.
  Proposal: add phase-level tests for Codex opt-in, default skip, failed Codex review, and strict-review behavior.

- [severity: major] `--design-review-agent` has no defined validation or failure behavior.
  Evidence: `resolve_reviewer()` accepts any nonempty agent string and forwards it to `run_design_review_agent()`, while the plan defines only `codex` as the supported provider-less reviewer.
  Proposal: restrict the argument to supported configured agents or explicitly validate it before Phase 4; specify the error/result path and test an unknown agent.

- [severity: minor] Verdict parsing accepts strings outside the stated literal contract.
  Evidence: `parse_verdict()` uses `startswith`, so outputs such as `APPROVEDLY` are treated as `APPROVED`, despite the contract requiring exact verdict literals.
  Proposal: require a token boundary after the verdict (end of line, whitespace, `:`, or dash) and add malformed-prefix tests.

- [severity: major] Required repository commit protocol is not executable from this plan.
  Evidence: every proposed commit uses a short conventional message, but the workspace requires Lore commit messages with decision context and applicable trailers.
  Proposal: replace each commit step with a complete Lore-compliant message template, including verification and known test gaps.
