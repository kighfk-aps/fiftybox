"""Tests for discover_openrouter_free."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))

import discover_openrouter_free as dof  # noqa: E402


@pytest.fixture
def catalog() -> list[dict]:
    payload = json.loads(
        (FIXTURES_DIR / "openrouter_catalog.json").read_text(encoding="utf-8")
    )
    return payload["data"]


class TestConstants:
    def test_catalog_url_points_at_openrouter(self):
        assert dof.CATALOG_URL == "https://openrouter.ai/api/v1/models"

    def test_min_context_threshold(self):
        assert dof.MIN_CONTEXT == 131072


class TestIsFreeToolModel:
    def test_accepts_free_model_with_tools_and_large_context(self, catalog):
        entry = next(e for e in catalog if e["id"] == "z-ai/glm-5.2:free")
        assert dof.is_free_tool_model(entry) is True

    def test_rejects_paid_variant(self, catalog):
        entry = next(e for e in catalog if e["id"] == "z-ai/glm-5.2")
        assert dof.is_free_tool_model(entry) is False

    def test_rejects_model_without_tools(self, catalog):
        entry = next(e for e in catalog if e["id"] == "nvidia/nemotron-3.5-content-safety:free")
        assert dof.is_free_tool_model(entry) is False

    def test_rejects_model_below_context_threshold(self, catalog):
        entry = next(e for e in catalog if e["id"] == "liquid/lfm-2.5-2.6b:free")
        assert dof.is_free_tool_model(entry) is False


class TestModelKeyMatching:
    def test_strip_free_suffix_removes_suffix(self):
        assert dof.strip_free_suffix("z-ai/glm-5.2:free") == "z-ai/glm-5.2"

    def test_strip_free_suffix_keeps_paid_id(self):
        assert dof.strip_free_suffix("z-ai/glm-5.2") == "z-ai/glm-5.2"

    def test_base_key_drops_vendor_and_free_markers(self):
        assert dof.base_key("minimax/minimax-m3:free") == "minimax-m3"
        assert dof.base_key("opencode/nemotron-3-ultra-free") == "nemotron-3-ultra"

    def test_overlaps_matches_same_model_with_different_vendor(self):
        assert dof.overlaps("minimax/minimax-m3:free", "minimaxai/minimax-m3") is True

    def test_overlaps_matches_size_suffixed_variant(self):
        assert (
            dof.overlaps(
                "nvidia/nemotron-3-ultra-550b-a55b:free",
                "opencode/nemotron-3-ultra-free",
            )
            is True
        )

    def test_overlaps_does_not_match_sibling_model(self):
        # laguna-s and laguna-xs are different models; must NOT be treated as overlap
        assert dof.overlaps("poolside/laguna-s-2.1:free", "poolside/laguna-xs-2.1") is False


class TestExcludeOverlapping:
    def test_drops_models_owned_by_other_lanes(self, catalog):
        candidates = [
            {"id": e["id"], "context": e["context_length"]}
            for e in catalog
            if dof.is_free_tool_model(e)
        ]
        other_lanes = ["minimaxai/minimax-m3", "opencode/nemotron-3-ultra-free"]
        kept = dof.exclude_overlapping(candidates, other_lanes)
        kept_ids = [c["id"] for c in kept]
        assert "minimax/minimax-m3:free" not in kept_ids
        assert "nvidia/nemotron-3-ultra-550b-a55b:free" not in kept_ids
        assert "z-ai/glm-5.2:free" in kept_ids


class TestOrderCandidates:
    def _candidates(self, catalog):
        return [
            {"id": e["id"], "context": e["context_length"]}
            for e in catalog
            if dof.is_free_tool_model(e)
        ]

    def test_config_order_comes_first_then_context_desc(self, catalog):
        candidates = dof.exclude_overlapping(
            self._candidates(catalog),
            ["minimaxai/minimax-m3", "opencode/nemotron-3-ultra-free"],
        )
        config_order = ["z-ai/glm-5.2:free", "cohere/north-mini-code:free"]
        ordered = dof.order_candidates(candidates, config_order)
        ids = [c["id"] for c in ordered]
        # config-ordered entries keep their relative order
        assert ids.index("z-ai/glm-5.2:free") < ids.index("cohere/north-mini-code:free")
        # leftovers follow in descending context: inkling (1M) then laguna-s (262144)
        assert ids[-2] == "thinkingmachines/inkling:free"
        assert ids[-1] == "poolside/laguna-s-2.1:free"

    def test_config_entries_missing_from_catalog_are_ignored(self, catalog):
        ordered = dof.order_candidates(self._candidates(catalog), ["does/not-exist:free"])
        assert len(ordered) == len(self._candidates(catalog))


class TestClassifyError:
    def test_shared_pool_429_is_model_busy(self):
        error = {"code": 429, "metadata": {"limit_source": "upstream_provider_shared_pool"}}
        assert dof.classify_error(error) == "model_busy"

    def test_overloaded_503_is_model_busy(self):
        assert dof.classify_error({"code": 503, "message": "Provider is overloaded"}) == "model_busy"

    def test_bare_429_is_account_window(self):
        assert dof.classify_error({"code": 429}) == "window"
        assert dof.classify_error({"code": 429, "message": "rate limit exceeded"}) == "window"

    def test_403_and_404_are_model_level(self):
        assert dof.classify_error({"code": 403, "message": "only available on agentic harnesses"}) == "model"
        assert dof.classify_error({"code": 404, "message": "Unknown model"}) == "model"

    def test_everything_else_is_unknown(self):
        assert dof.classify_error({"code": 500}) == "unknown"
        assert dof.classify_error({}) == "unknown"


class TestSmokeTestModel:
    def test_success_returns_ok(self, monkeypatch):
        monkeypatch.setattr(dof, "_chat_completion", lambda model_id, api_key, timeout: {"ok": True})
        result = dof.smoke_test_model("z-ai/glm-5.2:free", "sk-test")
        assert result["smoke"] == "ok"
        assert isinstance(result["latency_ms"], int)

    def test_shared_pool_429_retries_then_reports_model_busy(self, monkeypatch):
        calls = iter([
            {"error": {"code": 429, "metadata": {"limit_source": "upstream_provider_shared_pool"}}},
            {"error": {"code": 429, "metadata": {"limit_source": "upstream_provider_shared_pool"}}},
        ])
        monkeypatch.setattr(dof, "_chat_completion", lambda m, k, t: next(calls))
        monkeypatch.setattr(dof.time, "sleep", lambda s: None)
        result = dof.smoke_test_model("z-ai/glm-5.2:free", "sk-test")
        assert result["smoke"] == "model_busy"

    def test_account_429_reports_window_without_retry(self, monkeypatch):
        calls = []

        def fake_call(m, k, t):
            calls.append(m)
            return {"error": {"code": 429}}

        monkeypatch.setattr(dof, "_chat_completion", fake_call)
        result = dof.smoke_test_model("z-ai/glm-5.2:free", "sk-test")
        assert result["smoke"] == "window"
        assert len(calls) == 1

    def test_403_reports_model_without_retry(self, monkeypatch):
        monkeypatch.setattr(
            dof, "_chat_completion",
            lambda m, k, t: {"error": {"code": 403, "message": "agentic harnesses only"}},
        )
        result = dof.smoke_test_model("thinkingmachines/inkling:free", "sk-test")
        assert result["smoke"] == "model"


class TestDiscover:
    OTHER_LANES = ["minimaxai/minimax-m3", "opencode/nemotron-3-ultra-free"]

    def test_skip_smoke_returns_ordered_candidates_all_unknown(self, catalog):
        result = dof.discover(
            catalog,
            config_order=["z-ai/glm-5.2:free", "poolside/laguna-s-2.1:free"],
            other_lane_models=self.OTHER_LANES,
            skip_smoke=True,
        )
        assert result["window_exhausted"] is False
        ids = [c["id"] for c in result["candidates"]]
        assert ids == [
            "z-ai/glm-5.2:free",
            "poolside/laguna-s-2.1:free",
            "thinkingmachines/inkling:free",
            "cohere/north-mini-code:free",
        ]
        assert all(c["smoke"] == "unknown" for c in result["candidates"])
        assert all(c["context"] >= dof.MIN_CONTEXT for c in result["candidates"])

    def test_smoke_results_sort_ok_first(self, catalog, monkeypatch):
        outcomes = {
            "z-ai/glm-5.2:free": {"smoke": "ok", "latency_ms": 100},
            "poolside/laguna-s-2.1:free": {"smoke": "model_busy", "latency_ms": 50},
            "thinkingmachines/inkling:free": {"smoke": "model", "latency_ms": 40},
            "cohere/north-mini-code:free": {"smoke": "ok", "latency_ms": 70},
        }
        monkeypatch.setattr(
            dof, "smoke_test_model",
            lambda model_id, api_key: dict(outcomes[model_id]),
        )
        monkeypatch.setattr(dof, "get_api_key", lambda: "sk-test")
        result = dof.discover(
            catalog,
            config_order=[],
            other_lane_models=self.OTHER_LANES,
            skip_smoke=False,
        )
        ids = [c["id"] for c in result["candidates"]]
        # ok candidates first; among them the larger context (inkling excluded → north-mini 256000... glm 256000 tie) stays deterministic by context
        assert ids[0] in ("z-ai/glm-5.2:free", "cohere/north-mini-code:free")
        assert set(ids[:2]) == {"z-ai/glm-5.2:free", "cohere/north-mini-code:free"}

    def test_window_stops_discovery_and_flags_exhaustion(self, catalog, monkeypatch):
        def fake_smoke(model_id, api_key):
            if model_id == "z-ai/glm-5.2:free":
                return {"smoke": "window", "latency_ms": 10}
            raise AssertionError("window must stop further smoke tests")

        monkeypatch.setattr(dof, "smoke_test_model", fake_smoke)
        monkeypatch.setattr(dof, "get_api_key", lambda: "sk-test")
        result = dof.discover(
            catalog,
            config_order=["z-ai/glm-5.2:free", "poolside/laguna-s-2.1:free"],
            other_lane_models=self.OTHER_LANES,
            skip_smoke=False,
        )
        assert result["window_exhausted"] is True
