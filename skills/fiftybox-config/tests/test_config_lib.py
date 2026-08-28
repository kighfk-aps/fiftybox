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
