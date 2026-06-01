"""Regression tests for Codex output classification in the orchestrate harness."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import orchestrate


# A realistic security-review body Codex returns on the hardening branch.
# It MENTIONS "API key", "authentication", "rate limit" as subject matter,
# but it is a successful APPROVED review, NOT an API error.
SECURITY_REVIEW = """OpenAI Codex v0.135.0
--------
workdir: /tmp/wt
model: gpt-5.5
provider: openai
--------
user
review this
codex
APPROVED: The API key sanitization is correct. Authentication failures are
handled, and the rate limit backoff looks right. No connection reset issues.
tokens used
1234
APPROVED: The API key sanitization is correct. Authentication failures are
handled, and the rate limit backoff looks right. No connection reset issues."""

# A genuine transient API error: codex exits non-zero and the body says so.
USAGE_LIMIT_OUTPUT = "stream error: you've hit your usage limit. upgrade to Pro."


def test_security_review_first_line_verdict_is_approved():
    """A review whose verdict is APPROVED parses as approved even though the
    body contains 'api key', 'authentication', 'rate limit'."""
    verdict, _ = orchestrate.parse_codex_verdict(SECURITY_REVIEW)
    assert verdict == "approved"


def test_parse_verdict_never_returns_api_error_from_body():
    """parse_codex_verdict must not infer 'api_error' from body substrings.
    A body with no verdict line is 'unclear', never 'api_error'."""
    no_verdict = "Some notes about the api key and rate limit handling here."
    verdict, _ = orchestrate.parse_codex_verdict(no_verdict)
    assert verdict == "unclear"


def test_is_codex_api_error_true_on_real_usage_limit():
    """Genuine transient errors are still detected."""
    assert orchestrate.is_codex_api_error(USAGE_LIMIT_OUTPUT) is True


def test_is_codex_api_error_false_on_review_body_mentioning_keywords():
    """Subject-matter mentions in a review body are NOT API errors."""
    body = "The authentication module needs an api key; the rate limit is 5/s."
    assert orchestrate.is_codex_api_error(body) is False


def test_rmcp_token_refresh_line_is_not_api_error():
    """The RMCP transport noise line codex prints every run must be ignored."""
    noise = (
        "2026-05-31T04:00:57Z ERROR rmcp::transport::worker: worker quit with "
        'fatal: Transport channel closed, when Auth(TokenRefreshFailed("Failed '
        'to parse server response"))\ncodex\nAPPROVED: looks good'
    )
    assert orchestrate.is_codex_api_error(noise) is False
    verdict, _ = orchestrate.parse_codex_verdict(noise)
    assert verdict == "approved"


def test_review_test_api_error_check_is_returncode_gated():
    """phase_review_test must only treat output as an API error when Codex
    exited non-zero. Guards against the ungated call site regressing."""
    import inspect
    src = inspect.getsource(orchestrate.phase_review_test)
    # The is_codex_api_error call in review-test must be on the same condition
    # as a returncode check.
    assert "is_codex_api_error(codex_output)" in src
    # Find that line and assert it is guarded by a returncode comparison.
    guarded = any(
        "is_codex_api_error(codex_output)" in line and "returncode" in line
        for line in src.splitlines()
    )
    assert guarded, "review-test API-error check is not gated on returncode"


def test_codex_exec_requests_last_message_file(monkeypatch, tmp_path):
    """codex_exec should pass -o <file> so we can read the clean final message."""
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "full noisy transcript"
        stderr = ""
        args = ["codex", "exec"]

    def fake_run(cmd, cwd, timeout=600, text=None):
        captured["cmd"] = cmd
        # Simulate codex writing its last message to the -o path.
        if "-o" in cmd:
            out_path = cmd[cmd.index("-o") + 1]
            pathlib_path = __import__("pathlib").Path(out_path)
            pathlib_path.write_text("APPROVED: clean", encoding="utf-8")
        return FakeProc()

    monkeypatch.setattr(orchestrate, "run", fake_run)
    result = orchestrate.codex_exec(tmp_path, "gpt-5.5", "review", 60)
    assert "-o" in captured["cmd"]
    # The cleaned last message should be surfaced on result.stdout.
    assert "APPROVED: clean" in result.stdout
