"""Tests for config_lib: packaged default, load/save, corruption recovery."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import config_lib as cl  # noqa: E402


def test_default_config_has_all_five_providers():
    cfg = cl.default_config()
    assert set(cfg["providers"].keys()) == {
        "codex-write", "pi", "grok", "commandcode", "opencode",
    }


def test_default_config_returns_independent_copies():
    a = cl.default_config()
    b = cl.default_config()
    a["providers"]["grok"]["enabled"] = False
    assert b["providers"]["grok"]["enabled"] is True


def test_load_config_creates_default_when_missing(tmp_path):
    path = tmp_path / "fiftybox-config.json"
    assert not path.exists()
    cfg, warning = cl.load_config(path)
    assert path.exists()
    assert warning is None
    assert cfg["providers"]["codex-write"]["enabled"] is True


def test_load_config_recovers_from_corrupt_json(tmp_path):
    path = tmp_path / "fiftybox-config.json"
    path.write_text("{ not valid json", encoding="utf-8")
    cfg, warning = cl.load_config(path)
    assert warning is not None
    assert "invalid JSON" in warning
    backup = path.with_suffix(path.suffix + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "{ not valid json"
    assert cfg["providers"]["codex-write"]["enabled"] is True
    # the recovered file on disk is the fresh default, not the corrupt text
    assert json.loads(path.read_text(encoding="utf-8"))["providers"]["codex-write"]["enabled"] is True


def test_save_and_reload_round_trips(tmp_path):
    path = tmp_path / "fiftybox-config.json"
    cfg, _ = cl.load_config(path)
    cfg["providers"]["grok"]["enabled"] = False
    cl.save_config(cfg, path)
    reloaded, warning = cl.load_config(path)
    assert warning is None
    assert reloaded["providers"]["grok"]["enabled"] is False


def test_first_enabled_model_returns_first_true():
    assert cl.first_enabled_model({"a": False, "b": True, "c": True}) == "b"


def test_first_enabled_model_returns_none_when_all_false():
    assert cl.first_enabled_model({"a": False}) is None


def test_first_enabled_model_returns_none_for_empty_map():
    assert cl.first_enabled_model({}) is None


def test_resolve_lane_picks_first_provider_in_priority():
    cfg = cl.default_config()
    assert cl.resolve_lane(cfg, 0) == "codex-write"


def test_resolve_lane_falls_through_disabled_provider():
    cfg = cl.default_config()
    cfg["providers"]["codex-write"]["enabled"] = False
    assert cl.resolve_lane(cfg, 0) == "pi"


def test_resolve_lane_skips_pi_when_all_backend_models_disabled():
    cfg = cl.default_config()
    cfg["providers"]["codex-write"]["enabled"] = False
    for backend in cfg["providers"]["pi"]["backends"].values():
        for model in backend["models"]:
            backend["models"][model] = False
    assert cl.resolve_lane(cfg, 0) == "grok"


def test_resolve_lane_treats_missing_models_map_as_available():
    cfg = cl.default_config()
    for provider in ("codex-write", "pi", "grok", "commandcode"):
        cfg["providers"][provider]["enabled"] = False
    cfg["lane_priority"].append("opencode")
    assert cl.resolve_lane(cfg, 0) == "opencode"


def test_resolve_lane_returns_none_when_all_disabled():
    cfg = cl.default_config()
    for provider in cfg["providers"].values():
        provider["enabled"] = False
    assert cl.resolve_lane(cfg, 0) is None


def test_resolve_lane_respects_slot_index():
    cfg = cl.default_config()
    # slot 1 should never look at slot 0's provider first
    assert cl.resolve_lane(cfg, 1) == "pi"


def test_add_model_on_flat_provider():
    cfg = cl.default_config()
    cl.add_model(cfg, "grok", "grok-5.0")
    assert cfg["providers"]["grok"]["models"]["grok-5.0"] is True


def test_add_model_disabled():
    cfg = cl.default_config()
    cl.add_model(cfg, "grok", "grok-5.0-preview", enabled=False)
    assert cfg["providers"]["grok"]["models"]["grok-5.0-preview"] is False


def test_add_model_on_pi_backend():
    cfg = cl.default_config()
    cl.add_model(cfg, "pi", "glm-6.0-preview", backend="zai-coding")
    assert cfg["providers"]["pi"]["backends"]["zai-coding"]["models"]["glm-6.0-preview"] is True


def test_remove_model():
    cfg = cl.default_config()
    cl.add_model(cfg, "grok", "grok-5.0")
    cl.remove_model(cfg, "grok", "grok-5.0")
    assert "grok-5.0" not in cfg["providers"]["grok"]["models"]


def test_remove_model_on_pi_backend():
    cfg = cl.default_config()
    cl.remove_model(cfg, "pi", "glm-5.3-flash", backend="zai-coding")
    assert "glm-5.3-flash" not in cfg["providers"]["pi"]["backends"]["zai-coding"]["models"]
