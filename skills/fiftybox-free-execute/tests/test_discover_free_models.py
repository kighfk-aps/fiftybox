"""Tests for discover_free_models."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))

import discover_free_models as dfm  # noqa: E402


@pytest.fixture
def verbose_text() -> str:
    return (FIXTURES_DIR / "opencode_models_verbose.txt").read_text(encoding="utf-8")


@pytest.fixture
def plain_text() -> str:
    return (FIXTURES_DIR / "opencode_models_plain.txt").read_text(encoding="utf-8")


class TestParseVerboseModels:
    def test_parses_every_block(self, verbose_text):
        parsed = dfm.parse_verbose_models(verbose_text)
        assert len(parsed) == 8

    def test_returns_id_and_metadata_pairs(self, verbose_text):
        parsed = dfm.parse_verbose_models(verbose_text)
        ids = [model_id for model_id, _ in parsed]
        assert ids[0] == "opencode/big-pickle"
        assert ids[-1] == "zai/glm-4.5-flash"

    def test_metadata_is_parsed_json(self, verbose_text):
        parsed = dfm.parse_verbose_models(verbose_text)
        by_id = dict(parsed)
        entry = by_id["opencode/nemotron-3-ultra-free"]
        assert entry["providerID"] == "opencode"
        assert entry["limit"]["context"] == 1000000
        assert entry["capabilities"]["toolcall"] is True

    def test_skips_unparseable_block_keeps_rest(self):
        text = (
            "opencode/good\n"
            '{ "providerID": "opencode" }\n'
            "opencode/broken\n"
            "{ not json at all\n"
            "opencode/also-good\n"
            '{ "providerID": "opencode" }\n'
        )
        parsed = dfm.parse_verbose_models(text)
        assert [model_id for model_id, _ in parsed] == ["opencode/good", "opencode/also-good"]

    def test_empty_text_returns_empty_list(self):
        assert dfm.parse_verbose_models("") == []

    def test_plain_listing_without_json_returns_empty(self, plain_text):
        assert dfm.parse_verbose_models(plain_text) == []


class TestParsePlainModels:
    def test_returns_model_ids(self, plain_text):
        assert dfm.parse_plain_models(plain_text) == [
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        ]

    def test_ignores_blank_and_non_model_lines(self):
        text = "\nopencode/a\nsome noise here\n\nopencode/b\n"
        assert dfm.parse_plain_models(text) == ["opencode/a", "opencode/b"]


class TestIsFreeCandidate:
    def _entry(self, **overrides) -> dict:
        base = {
            "providerID": "opencode",
            "status": "active",
            "cost": {"input": 0, "output": 0},
            "limit": {"context": 200000},
            "capabilities": {"toolcall": True},
        }
        base.update(overrides)
        return base

    def test_accepts_opencode_zero_cost_toolcall_active(self):
        assert dfm.is_free_candidate(self._entry()) is True

    def test_rejects_other_provider_even_at_zero_cost(self):
        assert dfm.is_free_candidate(self._entry(providerID="openai")) is False
        assert dfm.is_free_candidate(self._entry(providerID="zai")) is False
        assert dfm.is_free_candidate(self._entry(providerID="opencode-go")) is False

    def test_rejects_nonzero_input_cost(self):
        assert dfm.is_free_candidate(self._entry(cost={"input": 0.14, "output": 0})) is False

    def test_rejects_nonzero_output_cost(self):
        assert dfm.is_free_candidate(self._entry(cost={"input": 0, "output": 0.28})) is False

    def test_rejects_missing_toolcall(self):
        assert dfm.is_free_candidate(self._entry(capabilities={"toolcall": False})) is False

    def test_rejects_inactive_status(self):
        assert dfm.is_free_candidate(self._entry(status="deprecated")) is False

    def test_rejects_entry_missing_keys(self):
        assert dfm.is_free_candidate({}) is False
        assert dfm.is_free_candidate({"providerID": "opencode"}) is False


class TestFilterAgainstRealFixture:
    """The regression tests that matter: which models survive the filter."""

    def _surviving_ids(self, verbose_text) -> list[str]:
        parsed = dfm.parse_verbose_models(verbose_text)
        return [mid for mid, entry in parsed if dfm.is_free_candidate(entry)]

    def test_big_pickle_included_despite_no_free_suffix(self, verbose_text):
        assert "opencode/big-pickle" in self._surviving_ids(verbose_text)

    def test_openai_pro_excluded_despite_zero_cost(self, verbose_text):
        assert "openai/gpt-5.6-pro" not in self._surviving_ids(verbose_text)

    def test_zai_flash_excluded_despite_zero_cost(self, verbose_text):
        assert "zai/glm-4.5-flash" not in self._surviving_ids(verbose_text)

    def test_paid_opencode_go_excluded(self, verbose_text):
        assert "opencode-go/deepseek-v4-flash" not in self._surviving_ids(verbose_text)

    def test_non_toolcall_free_model_excluded(self, verbose_text):
        assert "opencode/legacy-chat-free" not in self._surviving_ids(verbose_text)

    def test_deprecated_free_model_excluded(self, verbose_text):
        assert "opencode/retired-free" not in self._surviving_ids(verbose_text)

    def test_exact_surviving_set(self, verbose_text):
        assert set(self._surviving_ids(verbose_text)) == {
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        }


class TestToCandidate:
    def test_builds_record_with_unknown_smoke(self):
        entry = {
            "providerID": "opencode",
            "status": "active",
            "cost": {"input": 0, "output": 0},
            "limit": {"context": 256000},
            "capabilities": {"toolcall": True},
        }
        assert dfm.to_candidate("opencode/x-free", entry) == {
            "id": "opencode/x-free",
            "context": 256000,
            "toolcall": True,
            "smoke": "unknown",
            "latency_ms": None,
        }

    def test_missing_context_becomes_none(self):
        entry = {"capabilities": {"toolcall": True}}
        assert dfm.to_candidate("opencode/y-free", entry)["context"] is None


class TestSortCandidates:
    def test_ok_before_non_ok(self):
        cands = [
            {"id": "a", "context": 1000000, "smoke": "rate_limited"},
            {"id": "b", "context": 100000, "smoke": "ok"},
        ]
        assert [c["id"] for c in dfm.sort_candidates(cands)] == ["b", "a"]

    def test_larger_context_first_within_same_smoke(self):
        cands = [
            {"id": "a", "context": 200000, "smoke": "ok"},
            {"id": "b", "context": 1000000, "smoke": "ok"},
        ]
        assert [c["id"] for c in dfm.sort_candidates(cands)] == ["b", "a"]

    def test_none_context_sorts_last(self):
        cands = [
            {"id": "a", "context": None, "smoke": "ok"},
            {"id": "b", "context": 100000, "smoke": "ok"},
        ]
        assert [c["id"] for c in dfm.sort_candidates(cands)] == ["b", "a"]


import subprocess  # noqa: E402  (used by the smoke tests below)


class TestClassifySmoke:
    def test_zero_exit_is_ok(self):
        assert dfm.classify_smoke(0, "OK", timed_out=False) == "ok"

    def test_timed_out_wins_over_exit_code(self):
        assert dfm.classify_smoke(0, "OK", timed_out=True) == "timeout"

    def test_429_is_rate_limited(self):
        assert dfm.classify_smoke(1, "HTTP 429 Too Many Requests", timed_out=False) == "rate_limited"

    def test_rate_limit_phrase_is_rate_limited(self):
        assert dfm.classify_smoke(1, "Error: rate limit exceeded", timed_out=False) == "rate_limited"

    def test_quota_phrase_is_rate_limited(self):
        assert dfm.classify_smoke(1, "monthly QUOTA exhausted", timed_out=False) == "rate_limited"

    def test_insufficient_phrase_is_rate_limited(self):
        assert dfm.classify_smoke(1, "insufficient credits", timed_out=False) == "rate_limited"

    def test_other_failure_is_error(self):
        assert dfm.classify_smoke(1, "connection refused", timed_out=False) == "error"

    def test_rate_limit_pattern_wins_even_on_zero_exit(self):
        assert dfm.classify_smoke(0, "warning: rate limit near", timed_out=False) == "rate_limited"


class TestRunSmokeTest:
    def test_invokes_opencode_run_with_model(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        result, latency = dfm.run_smoke_test("opencode/mimo-v2.5-free")

        assert result == "ok"
        assert isinstance(latency, int)
        assert captured["cmd"][:2] == ["opencode", "run"]
        assert "--model" in captured["cmd"]
        assert captured["cmd"][captured["cmd"].index("--model") + 1] == "opencode/mimo-v2.5-free"

    def test_runs_in_a_temporary_directory_not_the_repo(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        dfm.run_smoke_test("opencode/x-free")

        assert captured["cwd"] is not None
        assert Path(captured["cwd"]) != Path.cwd()

    def test_never_passes_skip_permissions(self, monkeypatch):
        """The smoke prompt makes no edits, so it must not request write access."""
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        dfm.run_smoke_test("opencode/x-free")

        assert "--dangerously-skip-permissions" not in captured["cmd"]

    def test_timeout_expired_is_classified_timeout(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30)

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        assert dfm.run_smoke_test("opencode/x-free")[0] == "timeout"

    def test_missing_binary_is_error(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("opencode")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        assert dfm.run_smoke_test("opencode/x-free")[0] == "error"

    def test_stderr_is_considered_for_classification(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="429 rate limit")

        monkeypatch.setattr(dfm.subprocess, "run", fake_run)
        assert dfm.run_smoke_test("opencode/x-free")[0] == "rate_limited"


class TestSmokeTestAll:
    def test_fills_smoke_and_latency_for_each_candidate(self, monkeypatch):
        monkeypatch.setattr(dfm, "run_smoke_test", lambda model_id, timeout=30: ("ok", 1234))
        candidates = [
            {"id": "opencode/a", "context": 100, "toolcall": True, "smoke": "unknown", "latency_ms": None},
            {"id": "opencode/b", "context": 200, "toolcall": True, "smoke": "unknown", "latency_ms": None},
        ]
        result = dfm.smoke_test_all(candidates)
        assert all(c["smoke"] == "ok" for c in result)
        assert all(c["latency_ms"] == 1234 for c in result)

    def test_does_not_mutate_input(self, monkeypatch):
        monkeypatch.setattr(dfm, "run_smoke_test", lambda model_id, timeout=30: ("ok", 5))
        candidates = [{"id": "opencode/a", "context": 1, "toolcall": True, "smoke": "unknown", "latency_ms": None}]
        dfm.smoke_test_all(candidates)
        assert candidates[0]["smoke"] == "unknown"

    def test_per_model_results_are_not_swapped(self, monkeypatch):
        monkeypatch.setattr(
            dfm, "run_smoke_test",
            lambda model_id, timeout=30: ("ok", 1) if model_id == "opencode/a" else ("rate_limited", 2),
        )
        candidates = [
            {"id": "opencode/a", "context": 1, "toolcall": True, "smoke": "unknown", "latency_ms": None},
            {"id": "opencode/b", "context": 2, "toolcall": True, "smoke": "unknown", "latency_ms": None},
        ]
        by_id = {c["id"]: c for c in dfm.smoke_test_all(candidates)}
        assert by_id["opencode/a"]["smoke"] == "ok"
        assert by_id["opencode/b"]["smoke"] == "rate_limited"

    def test_empty_list_returns_empty(self):
        assert dfm.smoke_test_all([]) == []


import json as _json  # noqa: E402


class TestDiscover:
    def test_returns_sorted_free_candidates(self, monkeypatch, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: [
            {**c, "smoke": "ok", "latency_ms": 100} for c in cands
        ])
        result = dfm.discover()
        assert result["metadata_degraded"] is False
        ids = [c["id"] for c in result["candidates"]]
        assert set(ids) == {
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        }
        assert ids[0] == "opencode/nemotron-3-ultra-free"  # largest context first

    def test_skip_smoke_leaves_smoke_unknown(self, monkeypatch, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        result = dfm.discover(skip_smoke=True)
        assert all(c["smoke"] == "unknown" for c in result["candidates"])

    def test_falls_back_to_plain_when_verbose_unparseable(self, monkeypatch, plain_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "garbage with no json")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: plain_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: [
            {**c, "smoke": "ok", "latency_ms": 10} for c in cands
        ])
        result = dfm.discover()
        assert result["metadata_degraded"] is True
        assert {c["id"] for c in result["candidates"]} == {
            "opencode/big-pickle",
            "opencode/mimo-v2.5-free",
            "opencode/nemotron-3-ultra-free",
        }

    def test_degraded_candidates_have_unknown_metadata(self, monkeypatch, plain_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "garbage")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: plain_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: cands)
        result = dfm.discover()
        assert all(c["context"] is None and c["toolcall"] is None for c in result["candidates"])

    def test_degraded_fallback_still_scopes_to_opencode_provider(self, monkeypatch):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "garbage")
        monkeypatch.setattr(
            dfm, "list_models_plain",
            lambda: "opencode/a-free\nopencode-go/paid\nopenai/gpt-5.6-pro\n",
        )
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: cands)
        result = dfm.discover()
        assert [c["id"] for c in result["candidates"]] == ["opencode/a-free"]

    def test_no_candidates_returns_empty_list_not_error(self, monkeypatch):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: "")
        result = dfm.discover()
        assert result["candidates"] == []


class TestMain:
    def test_prints_json_document(self, monkeypatch, capsys, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        monkeypatch.setattr(dfm, "smoke_test_all", lambda cands, **kw: [
            {**c, "smoke": "ok", "latency_ms": 1} for c in cands
        ])
        exit_code = dfm.main([])
        payload = _json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["metadata_degraded"] is False
        assert len(payload["candidates"]) == 3

    def test_skip_smoke_flag_is_honoured(self, monkeypatch, capsys, verbose_text):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: verbose_text)
        dfm.main(["--skip-smoke"])
        payload = _json.loads(capsys.readouterr().out)
        assert all(c["smoke"] == "unknown" for c in payload["candidates"])

    def test_exit_code_zero_even_with_no_candidates(self, monkeypatch, capsys):
        monkeypatch.setattr(dfm, "list_models_verbose", lambda: "")
        monkeypatch.setattr(dfm, "list_models_plain", lambda: "")
        assert dfm.main([]) == 0
        assert _json.loads(capsys.readouterr().out)["candidates"] == []
