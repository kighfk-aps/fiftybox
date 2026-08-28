# Fiftybox Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `fiftybox-config` skill — a stdlib-only settings file plus a curses TUI — that lets a human check on/off which CLI providers (Pi, Codex, CommandCode, Grok, opencode) and which models under each are currently usable, and wire `fiftybox-execute`/`fiftybox-local` to read that file instead of hardcoding availability.

**Architecture:** A pure logic module (`config_lib.py`) owns the JSON schema, load/save, corruption recovery, and lane-resolution math; a curses UI module (`config_tui.py`) is split into pure state/row/key-handling functions (unit-testable without a TTY) and a thin `render`/`main` layer that touches `curses`. `fiftybox-execute`'s Step 0 preflight and lane-allocator table, and `fiftybox-local`'s candidate-pool step, are edited to read `~/.claude/fiftybox-config.json` before deciding what to check/use.

**Tech Stack:** Python 3 stdlib only (`json`, `pathlib`, `dataclasses`, `curses`, `shutil`). pytest for unit tests (already used by `skills/fiftybox-orchestration/tests/test_agent_config.py`). Bash for the doc/install structure tests (existing `tests/test_*.sh` convention).

**Spec:** `docs/superpowers/specs/2026-08-28-fiftybox-config-design.md`

## Global Constraints

- Stdlib only. No new pip dependency (no `questionary`/`prompt_toolkit`/`rich` interactive widgets) — `rich` is installed but has no interactive checkbox widget; `curses` (stdlib) is what renders the TUI.
- Config file lives at `~/.claude/fiftybox-config.json` — global, machine-level, shared across every project. Never project-scoped.
- `install.sh` must never overwrite an existing `~/.claude/fiftybox-config.json` on a re-run — only seed it when absent.
- No `lane_priority` reordering UI in this iteration — the TUI only toggles `enabled` on providers and models; reordering `lane_priority` is a manual file edit.
- `fiftybox-config` never auto-detects subscription/login status itself (no calling `cmd`, `grok inspect`, etc.) — that stays `fiftybox-execute`'s Step 0 preflight job, and only for providers this config marks enabled.
- If every provider in `lane_priority` is disabled (or has no enabled models) for a priority slot that a task actually needs, stop and tell the user to enable at least one via `/fiftybox-config` — never fall back to a hardcoded or paid provider silently.

---

### Task 1: `config_lib.py` — packaged default, load/save, corruption recovery

**Files:**
- Create: `skills/fiftybox-config/config/default-config.json`
- Create: `skills/fiftybox-config/scripts/config_lib.py`
- Test: `skills/fiftybox-config/tests/test_config_lib.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `config_lib.DEFAULT_CONFIG_PATH: Path` — `~/.claude/fiftybox-config.json`
  - `config_lib.PACKAGED_DEFAULT_PATH: Path` — `skills/fiftybox-config/config/default-config.json`, resolved relative to `config_lib.py`'s own location
  - `config_lib.default_config() -> dict` — fresh deep copy of the packaged default
  - `config_lib.load_config(path: Path | None = None) -> tuple[dict, str | None]`
  - `config_lib.save_config(config: dict, path: Path | None = None) -> None`

- [ ] **Step 1: Create the packaged default config file**

Create `skills/fiftybox-config/config/default-config.json`:

```json
{
  "lane_priority": ["codex-write", "pi", "grok", "commandcode"],
  "providers": {
    "codex-write": {
      "enabled": true,
      "models": {
        "gpt-5.6-luna": true,
        "gpt-5.6-terra": false
      }
    },
    "pi": {
      "enabled": true,
      "backends": {
        "zai-coding": {
          "models": { "glm-5.3-flash": true }
        },
        "opencode-go": {
          "models": { "deepseek-v4-flash": true }
        },
        "modal-qwen38": {
          "models": { "qwen3.8-27b-q4_k_m": true }
        }
      }
    },
    "grok": {
      "enabled": true,
      "models": { "grok-4.6": true }
    },
    "commandcode": {
      "enabled": true,
      "models": {
        "qwen/qwen3.7-flash": true,
        "zai-org/glm-5.2": true
      }
    },
    "opencode": {
      "enabled": true
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `skills/fiftybox-config/tests/test_config_lib.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_lib.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config_lib'`

- [ ] **Step 4: Implement `config_lib.py`**

Create `skills/fiftybox-config/scripts/config_lib.py`:

```python
"""Pure config load/save logic for fiftybox-config.

No curses import here — this module must be importable and testable
without a TTY. config_tui.py is the only place curses is imported.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "fiftybox-config.json"
PACKAGED_DEFAULT_PATH = Path(__file__).parent.parent / "config" / "default-config.json"


def default_config() -> dict[str, Any]:
    """Return a fresh, independent copy of the packaged default config."""
    with open(PACKAGED_DEFAULT_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    return json.loads(text)


def load_config(path: Path | None = None) -> tuple[dict[str, Any], str | None]:
    """Load the settings file at `path` (default: DEFAULT_CONFIG_PATH).

    Returns (config, warning). warning is None unless the file was missing
    (silently created from defaults, no warning needed) or corrupt (backed
    up and reset, warning describes what happened).
    """
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        cfg = default_config()
        save_config(cfg, path)
        return cfg, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except (json.JSONDecodeError, OSError) as exc:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)
        cfg = default_config()
        save_config(cfg, path)
        return (
            cfg,
            f"{path} was invalid JSON ({exc}); backed up to {backup_path} "
            "and reset to defaults",
        )


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_lib.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add skills/fiftybox-config/config/default-config.json \
        skills/fiftybox-config/scripts/config_lib.py \
        skills/fiftybox-config/tests/test_config_lib.py
git commit -m "feat(fiftybox-config): add settings load/save with corruption recovery"
```

---

### Task 2: `config_lib.py` — lane resolution and model list editing

**Files:**
- Modify: `skills/fiftybox-config/scripts/config_lib.py`
- Test: `skills/fiftybox-config/tests/test_config_lib.py`

**Interfaces:**
- Consumes: `config_lib.default_config()` from Task 1
- Produces:
  - `config_lib.first_enabled_model(models: dict[str, bool]) -> str | None`
  - `config_lib.resolve_lane(config: dict, slot_index: int) -> str | None`
  - `config_lib.add_model(config: dict, provider: str, model: str, backend: str | None = None, enabled: bool = True) -> None`
  - `config_lib.remove_model(config: dict, provider: str, model: str, backend: str | None = None) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `skills/fiftybox-config/tests/test_config_lib.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_lib.py -v`
Expected: FAIL — `AttributeError: module 'config_lib' has no attribute 'first_enabled_model'` (and similarly for the other new names)

- [ ] **Step 3: Implement the new functions**

Append to `skills/fiftybox-config/scripts/config_lib.py`:

```python
def first_enabled_model(models: dict[str, bool]) -> str | None:
    for name, enabled in models.items():
        if enabled:
            return name
    return None


def _pi_has_enabled_model(pi_provider_cfg: dict[str, Any]) -> bool:
    for backend in pi_provider_cfg.get("backends", {}).values():
        if first_enabled_model(backend.get("models", {})) is not None:
            return True
    return False


def resolve_lane(config: dict[str, Any], slot_index: int) -> str | None:
    """Return the provider that fills priority slot `slot_index`.

    Walks forward through config["lane_priority"] starting at slot_index,
    returning the first provider that is enabled and has at least one
    enabled model (providers with no "models" map at all, like opencode,
    count as available whenever enabled=true). Returns None if nothing in
    the remainder of lane_priority is available.
    """
    lane_priority = config["lane_priority"]
    for provider in lane_priority[slot_index:]:
        provider_cfg = config["providers"].get(provider)
        if provider_cfg is None or not provider_cfg.get("enabled"):
            continue
        if provider == "pi":
            if _pi_has_enabled_model(provider_cfg):
                return provider
            continue
        models = provider_cfg.get("models")
        if models is None:
            return provider
        if first_enabled_model(models) is not None:
            return provider
    return None


def _models_map(config: dict[str, Any], provider: str, backend: str | None) -> dict[str, bool]:
    provider_cfg = config["providers"][provider]
    if backend is not None:
        return provider_cfg["backends"][backend]["models"]
    return provider_cfg["models"]


def add_model(
    config: dict[str, Any],
    provider: str,
    model: str,
    backend: str | None = None,
    enabled: bool = True,
) -> None:
    _models_map(config, provider, backend)[model] = enabled


def remove_model(
    config: dict[str, Any],
    provider: str,
    model: str,
    backend: str | None = None,
) -> None:
    _models_map(config, provider, backend).pop(model, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_lib.py -v`
Expected: PASS (18 tests total)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-config/scripts/config_lib.py skills/fiftybox-config/tests/test_config_lib.py
git commit -m "feat(fiftybox-config): add lane resolution and model list editing"
```

---

### Task 3: `config_tui.py` — pure state, row listing, and key handling

**Files:**
- Create: `skills/fiftybox-config/scripts/config_tui.py`
- Test: `skills/fiftybox-config/tests/test_config_tui.py`

**Interfaces:**
- Consumes: `config_lib.default_config()`, `config_lib.add_model()`, `config_lib.remove_model()` from Tasks 1-2
- Produces:
  - `config_tui.Row` — dataclass: `kind: str` (`"provider"` or `"model"`), `provider: str`, `backend: str | None`, `model: str | None`, `label: str`, `checked: bool`, `depth: int`
  - `config_tui.State` — dataclass: `config: dict`, `expanded: set[str]`, `cursor: int`, `should_save: bool`, `should_quit: bool`, `message: str`
  - `config_tui.visible_rows(state: State) -> list[Row]`
  - `config_tui.handle_key(state: State, key: str) -> State`
  - `config_tui.add_model_row(state: State, model_name: str) -> State`
  - `config_tui.delete_selected_row(state: State) -> State`

- [ ] **Step 1: Write the failing tests**

Create `skills/fiftybox-config/tests/test_config_tui.py`:

```python
"""Tests for config_tui's pure state/row/key-handling logic (no curses)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import config_lib as cl  # noqa: E402
import config_tui as tui  # noqa: E402


def make_state() -> tui.State:
    return tui.State(config=cl.default_config())


def test_visible_rows_lists_all_providers_collapsed():
    state = make_state()
    rows = tui.visible_rows(state)
    assert [r.provider for r in rows] == list(state.config["providers"].keys())
    assert all(r.kind == "provider" for r in rows)


def test_expanding_provider_shows_its_models():
    state = make_state()
    state.expanded.add("grok")
    rows = tui.visible_rows(state)
    model_rows = [r for r in rows if r.kind == "model" and r.provider == "grok"]
    assert [r.model for r in model_rows] == list(state.config["providers"]["grok"]["models"].keys())


def test_expanding_pi_shows_backend_prefixed_models():
    state = make_state()
    state.expanded.add("pi")
    rows = tui.visible_rows(state)
    labels = [r.label for r in rows if r.provider == "pi"]
    assert "zai-coding/glm-5.3-flash" in labels


def test_collapsed_provider_hides_models():
    state = make_state()
    rows = tui.visible_rows(state)
    assert not any(r.kind == "model" for r in rows)


def test_space_toggles_provider_enabled():
    state = make_state()
    idx = [r.provider for r in tui.visible_rows(state)].index("grok")
    state.cursor = idx
    tui.handle_key(state, " ")
    assert state.config["providers"]["grok"]["enabled"] is False
    tui.handle_key(state, " ")
    assert state.config["providers"]["grok"]["enabled"] is True


def test_enter_expands_and_collapses_provider():
    state = make_state()
    idx = [r.provider for r in tui.visible_rows(state)].index("grok")
    state.cursor = idx
    tui.handle_key(state, "\n")
    assert "grok" in state.expanded
    tui.handle_key(state, "\n")
    assert "grok" not in state.expanded


def test_space_toggles_model_enabled():
    state = make_state()
    state.expanded.add("grok")
    rows = tui.visible_rows(state)
    idx = next(i for i, r in enumerate(rows) if r.kind == "model" and r.model == "grok-4.6")
    state.cursor = idx
    tui.handle_key(state, " ")
    assert state.config["providers"]["grok"]["models"]["grok-4.6"] is False


def test_cursor_does_not_move_past_bounds():
    state = make_state()
    n = len(tui.visible_rows(state))
    state.cursor = n - 1
    tui.handle_key(state, "down")
    assert state.cursor == n - 1
    state.cursor = 0
    tui.handle_key(state, "up")
    assert state.cursor == 0


def test_s_sets_should_save():
    state = make_state()
    tui.handle_key(state, "s")
    assert state.should_save is True


def test_q_sets_should_quit():
    state = make_state()
    tui.handle_key(state, "q")
    assert state.should_quit is True


def test_add_model_row_adds_to_selected_pi_backend():
    state = make_state()
    state.expanded.add("pi")
    rows = tui.visible_rows(state)
    idx = next(i for i, r in enumerate(rows) if r.kind == "model" and r.backend == "zai-coding")
    state.cursor = idx
    tui.add_model_row(state, "glm-6.0-preview")
    assert state.config["providers"]["pi"]["backends"]["zai-coding"]["models"]["glm-6.0-preview"] is True


def test_add_model_row_on_collapsed_pi_provider_sets_message():
    state = make_state()
    idx = [r.provider for r in tui.visible_rows(state)].index("pi")
    state.cursor = idx
    tui.add_model_row(state, "glm-6.0-preview")
    assert state.message


def test_delete_selected_row_removes_model():
    state = make_state()
    state.expanded.add("grok")
    rows = tui.visible_rows(state)
    idx = next(i for i, r in enumerate(rows) if r.kind == "model" and r.model == "grok-4.6")
    state.cursor = idx
    tui.delete_selected_row(state)
    assert "grok-4.6" not in state.config["providers"]["grok"]["models"]


def test_delete_selected_row_on_provider_sets_message():
    state = make_state()
    idx = [r.provider for r in tui.visible_rows(state)].index("grok")
    state.cursor = idx
    tui.delete_selected_row(state)
    assert state.message
    assert "grok" in state.config["providers"]  # nothing was deleted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_tui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config_tui'`

- [ ] **Step 3: Implement the pure logic in `config_tui.py`**

Create `skills/fiftybox-config/scripts/config_tui.py`:

```python
"""Interactive TUI for fiftybox-config.

State/row/key-handling logic below is pure (no curses import needed to run
it), so it is unit-tested without a real terminal. `render` and `main`
(Task 4) are the only functions that touch curses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config_lib as cl


@dataclass
class Row:
    kind: str  # "provider" or "model"
    provider: str
    backend: str | None = None
    model: str | None = None
    label: str = ""
    checked: bool = False
    depth: int = 0


@dataclass
class State:
    config: dict[str, Any]
    expanded: set[str] = field(default_factory=set)
    cursor: int = 0
    should_save: bool = False
    should_quit: bool = False
    message: str = ""


def _provider_model_sources(provider_cfg: dict[str, Any]) -> list[tuple[str | None, dict[str, bool]]]:
    if "backends" in provider_cfg:
        return [(name, backend["models"]) for name, backend in provider_cfg["backends"].items()]
    if "models" in provider_cfg:
        return [(None, provider_cfg["models"])]
    return []


def visible_rows(state: State) -> list[Row]:
    rows: list[Row] = []
    for provider_key, provider_cfg in state.config["providers"].items():
        rows.append(Row(
            kind="provider",
            provider=provider_key,
            label=provider_key,
            checked=bool(provider_cfg.get("enabled")),
            depth=0,
        ))
        if provider_key not in state.expanded:
            continue
        for backend_name, models in _provider_model_sources(provider_cfg):
            for model_name, enabled in models.items():
                label = f"{backend_name}/{model_name}" if backend_name else model_name
                rows.append(Row(
                    kind="model",
                    provider=provider_key,
                    backend=backend_name,
                    model=model_name,
                    label=label,
                    checked=bool(enabled),
                    depth=1,
                ))
    return rows


def handle_key(state: State, key: str) -> State:
    rows = visible_rows(state)
    if not rows:
        return state
    state.cursor = min(state.cursor, len(rows) - 1)
    if key == "down":
        state.cursor = min(state.cursor + 1, len(rows) - 1)
    elif key == "up":
        state.cursor = max(state.cursor - 1, 0)
    elif key == " ":
        row = rows[state.cursor]
        if row.kind == "provider":
            state.config["providers"][row.provider]["enabled"] = not row.checked
        else:
            cl._models_map(state.config, row.provider, row.backend)[row.model] = not row.checked
    elif key == "\n":
        row = rows[state.cursor]
        if row.kind == "provider":
            if row.provider in state.expanded:
                state.expanded.discard(row.provider)
            else:
                state.expanded.add(row.provider)
    elif key == "s":
        state.should_save = True
    elif key == "q":
        state.should_quit = True
    return state


def add_model_row(state: State, model_name: str) -> State:
    rows = visible_rows(state)
    if not rows:
        return state
    row = rows[state.cursor]
    if row.kind == "provider":
        if "backends" in state.config["providers"][row.provider]:
            state.message = "Expand a Pi backend before adding a model (press Enter first)"
            return state
        cl.add_model(state.config, row.provider, model_name)
    else:
        cl.add_model(state.config, row.provider, model_name, backend=row.backend)
    state.message = f"Added {model_name}"
    return state


def delete_selected_row(state: State) -> State:
    rows = visible_rows(state)
    if not rows:
        return state
    row = rows[state.cursor]
    if row.kind != "model":
        state.message = "Select a model row (press Enter to expand a provider first)"
        return state
    cl.remove_model(state.config, row.provider, row.model, backend=row.backend)
    state.cursor = max(0, state.cursor - 1)
    state.message = f"Removed {row.model}"
    return state
```

Note: `handle_key`'s space-toggle branch calls `cl._models_map`, a
name-mangled-looking but plain module-private helper already defined in
Task 2's `config_lib.py`. Add it there if not already present (it was
introduced internally by `add_model`/`remove_model` in Task 2 — confirm it
exists before writing this step; it does not need a leading-underscore
export contract beyond intra-package use).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_tui.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-config/scripts/config_tui.py skills/fiftybox-config/tests/test_config_tui.py
git commit -m "feat(fiftybox-config): add pure TUI state/row/key-handling logic"
```

---

### Task 4: `config_tui.py` — curses rendering and main loop

**Files:**
- Modify: `skills/fiftybox-config/scripts/config_tui.py`
- Test: `skills/fiftybox-config/tests/test_config_tui.py`

**Interfaces:**
- Consumes: `Row`, `State`, `visible_rows`, `handle_key`, `add_model_row`, `delete_selected_row` from Task 3; `config_lib.load_config`, `config_lib.save_config`, `config_lib.DEFAULT_CONFIG_PATH` from Task 1
- Produces:
  - `config_tui.render(stdscr, state: State) -> None`
  - `config_tui.main() -> None`

- [ ] **Step 1: Write the failing test**

Append to `skills/fiftybox-config/tests/test_config_tui.py`:

```python
class _FakeStdscr:
    def __init__(self):
        self.lines: list[tuple] = []

    def erase(self):
        self.lines.clear()

    def addstr(self, *args, **kwargs):
        self.lines.append(args)

    def refresh(self):
        pass


def test_render_draws_header_and_provider_rows_without_raising():
    state = make_state()
    stdscr = _FakeStdscr()
    tui.render(stdscr, state)
    assert stdscr.lines  # something was drawn
    joined = " ".join(str(line[-1]) for line in stdscr.lines if isinstance(line[-1], str))
    assert "grok" in joined


def test_main_is_defined_and_callable():
    assert callable(tui.main)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_tui.py -v`
Expected: FAIL with `AttributeError: module 'config_tui' has no attribute 'render'`

- [ ] **Step 3: Implement rendering and the main loop**

Append to `skills/fiftybox-config/scripts/config_tui.py` (add `import curses`
at the top of the file alongside the existing imports):

```python
import curses  # noqa: E402  (kept below dataclass imports intentionally)


def render(stdscr, state: State) -> None:
    stdscr.erase()
    rows = visible_rows(state)
    stdscr.addstr(
        0, 0,
        "fiftybox-config  (space=toggle  enter=expand  a=add  d=delete  s=save  q=quit)",
    )
    for i, row in enumerate(rows):
        mark = "[x]" if row.checked else "[ ]"
        indent = "  " * row.depth
        attr = curses.A_REVERSE if i == state.cursor else curses.A_NORMAL
        stdscr.addstr(i + 2, 0, f"{indent}{mark} {row.label}", attr)
    if state.message:
        stdscr.addstr(len(rows) + 3, 0, state.message)
    stdscr.refresh()


def _prompt(stdscr, label: str) -> str:
    curses.echo()
    y = curses.LINES - 1
    stdscr.addstr(y, 0, label)
    stdscr.clrtoeol()
    text = stdscr.getstr(y, len(label)).decode("utf-8")
    curses.noecho()
    return text


def _run(stdscr, config_path) -> None:
    curses.curs_set(0)
    config, warning = cl.load_config(config_path)
    state = State(config=config)
    if warning:
        state.message = warning
    key_for_ch = {
        curses.KEY_DOWN: "down", ord("j"): "down",
        curses.KEY_UP: "up", ord("k"): "up",
        ord(" "): " ",
        curses.KEY_ENTER: "\n", 10: "\n", 13: "\n",
        ord("s"): "s",
        ord("q"): "q",
    }
    while True:
        render(stdscr, state)
        ch = stdscr.getch()
        if ch == ord("a"):
            name = _prompt(stdscr, "New model name: ")
            if name:
                state = add_model_row(state, name)
        elif ch == ord("d"):
            state = delete_selected_row(state)
        elif ch in key_for_ch:
            state = handle_key(state, key_for_ch[ch])
        if state.should_save:
            cl.save_config(state.config, config_path)
            return
        if state.should_quit:
            return


def main() -> None:
    curses.wrapper(_run, cl.DEFAULT_CONFIG_PATH)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest skills/fiftybox-config/tests/test_config_tui.py -v`
Expected: PASS (16 tests total)

- [ ] **Step 5: Manual smoke test (curses needs a real TTY, not covered by pytest)**

Run: `python3 skills/fiftybox-config/scripts/config_tui.py`
Expected: a checkbox screen appears listing `codex-write`, `pi`, `grok`,
`commandcode`, `opencode`; arrow keys move the highlighted row, space
toggles `[ ]`/`[x]`, Enter on `pi` reveals its three backends' models,
`s` saves to `~/.claude/fiftybox-config.json` (back up that file first if
it already exists) and exits, `q` exits without saving. Confirm this by
hand, then restore any backed-up file.

- [ ] **Step 6: Commit**

```bash
git add skills/fiftybox-config/scripts/config_tui.py skills/fiftybox-config/tests/test_config_tui.py
git commit -m "feat(fiftybox-config): add curses rendering and main loop"
```

---

### Task 5: `fiftybox-config` SKILL.md

**Files:**
- Create: `skills/fiftybox-config/SKILL.md`
- Test: `tests/test_config_skill_doc.sh`

**Interfaces:**
- Consumes: file paths from Tasks 1-4 (`scripts/config_lib.py`, `scripts/config_tui.py`, `config/default-config.json`)
- Produces: nothing consumed by later tasks (doc-only), but Task 6's
  `install.sh` copies the files this task's SKILL.md documents.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_skill_doc.sh`:

```bash
#!/usr/bin/env bash
# Structure tests for the fiftybox-config skill
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$SCRIPT_DIR/skills/fiftybox-config/SKILL.md"
LIB="$SCRIPT_DIR/skills/fiftybox-config/scripts/config_lib.py"
TUI="$SCRIPT_DIR/skills/fiftybox-config/scripts/config_tui.py"
DEFAULT_CFG="$SCRIPT_DIR/skills/fiftybox-config/config/default-config.json"
PASS=0
FAIL=0

pass() { echo "PASS: $1"; PASS=$(( PASS + 1 )); }
fail() { echo "FAIL: $1"; FAIL=$(( FAIL + 1 )); }
has() { if [[ -f "$1" ]] && grep -qF -- "$2" "$1"; then pass "$3"; else fail "$3"; fi; }

[[ -f "$LIB" ]] && pass "config_lib.py exists" || fail "config_lib.py missing"
[[ -f "$TUI" ]] && pass "config_tui.py exists" || fail "config_tui.py missing"
[[ -f "$DEFAULT_CFG" ]] && pass "default-config.json exists" || fail "default-config.json missing"

has "$SKILL" "name: fiftybox-config" "SKILL.md frontmatter declares its name"
has "$SKILL" "~/.claude/fiftybox-config.json" "SKILL.md documents the config file path"
has "$SKILL" "config_tui.py" "SKILL.md references the TUI script"
has "$SKILL" "! python3" "SKILL.md tells the user to run the TUI themselves via !"
has "$SKILL" "lane_priority" "SKILL.md documents the lane_priority field"

python3 -c "import json; json.load(open('$DEFAULT_CFG'))" \
    && pass "default-config.json is valid JSON" \
    || fail "default-config.json is not valid JSON"

for key in codex-write pi grok commandcode opencode; do
  python3 -c "
import json, sys
d = json.load(open('$DEFAULT_CFG'))
sys.exit(0 if '$key' in d['providers'] else 1)
" \
      && pass "default-config.json includes provider $key" \
      || fail "default-config.json missing provider $key"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_config_skill_doc.sh`
Expected: FAIL (`SKILL.md` grep checks fail — the file does not exist yet)

- [ ] **Step 3: Write `skills/fiftybox-config/SKILL.md`**

```markdown
---
name: fiftybox-config
description: fiftybox-execute/fiftybox-local이 쓰는 CLI provider(Pi, Codex, CommandCode, Grok, opencode)와 그 하위 모델의 사용 가능 여부를 체크박스 TUI로 켜고 끈다. 구독 상황이 바뀌었을 때, 또는 /fiftybox-config를 호출했을 때 사용한다.
---

# Fiftybox Config

`fiftybox-execute`/`fiftybox-local`이 어떤 CLI 도구·모델을 쓸 수 있는지는
`~/.claude/fiftybox-config.json`(머신 전역, 프로젝트 무관) 하나로 정해진다.
이 스킬은 그 파일을 사람이 직접 체크박스로 켜고 끄는 TUI만 제공한다 —
구독·로그인 상태를 대신 확인해주지는 않는다.

## 호출

`/fiftybox-config`를 부르면 Claude는 TUI를 대신 실행하지 않는다. curses TUI는
실제 키보드가 있는 사람 손에서만 동작하므로, 다음을 안내하고 멈춘다:

```
! python3 ~/.claude/skills/fiftybox-config/scripts/config_tui.py
```

사용자가 `!` 접두사로 직접 터미널에서 실행하게 한다.

## TUI 조작

- ↑/↓ (또는 k/j): 이동
- Space: 선택한 provider 또는 모델 체크박스 토글
- Enter: provider 행 펼치기/접기 (하위 모델 표시)
- `a`: 선택한 provider(또는 펼쳐진 Pi 백엔드의 모델 행)에 모델 추가
- `d`: 선택한 모델 행 삭제 (provider 행 자체는 삭제 불가)
- `s`: 저장하고 종료
- `q`: 저장하지 않고 종료

## 설정 파일

경로: `~/.claude/fiftybox-config.json`

```json
{
  "lane_priority": ["codex-write", "pi", "grok", "commandcode"],
  "providers": {
    "codex-write": {"enabled": true, "models": {"gpt-5.6-luna": true, "gpt-5.6-terra": false}},
    "pi": {"enabled": true, "backends": {
      "zai-coding": {"models": {"glm-5.3-flash": true}},
      "opencode-go": {"models": {"deepseek-v4-flash": true}},
      "modal-qwen38": {"models": {"qwen3.8-27b-q4_k_m": true}}
    }},
    "grok": {"enabled": true, "models": {"grok-4.6": true}},
    "commandcode": {"enabled": true, "models": {"qwen/qwen3.7-flash": true, "zai-org/glm-5.2": true}},
    "opencode": {"enabled": true}
  }
}
```

`lane_priority`는 fiftybox-execute의 4단계 우선순위 자리를 어떤 provider가
기본으로 채우는지의 순서다. 이 스킬의 TUI로는 순서를 바꾸지 않는다 — 필요하면
파일을 직접 편집한다. provider가 `enabled: false`거나 켜진 모델이 하나도
없으면, fiftybox-execute의 lane allocator가 `lane_priority`의 다음 값으로
자동 대체한다.

파일이 없으면 TUI 최초 실행 시 리포 기본값으로 만든다. JSON이 깨져 있으면
`.bak`으로 백업하고 기본값으로 재생성한 뒤 화면에 경고를 보여준다.

## fiftybox-execute / fiftybox-local과의 관계

이 스킬은 설정을 저장하기만 한다. 실제로 이 설정을 읽어 preflight를
건너뛰거나 lane/후보 풀을 재배정하는 것은 `/fiftybox-execute`와
`/fiftybox-local` 쪽 책임이다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_config_skill_doc.sh`
Expected: PASS (13 checks)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-config/SKILL.md tests/test_config_skill_doc.sh
git commit -m "docs(fiftybox-config): add SKILL.md for the provider/model toggle TUI"
```

---

### Task 6: `install.sh` wiring

**Files:**
- Modify: `install.sh`
- Modify: `tests/test_install.sh`

**Interfaces:**
- Consumes: `skills/fiftybox-config/SKILL.md`, `skills/fiftybox-config/scripts/*.py`, `skills/fiftybox-config/config/default-config.json` from Tasks 1-5
- Produces: `~/.claude/skills/fiftybox-config/` and a seeded
  `~/.claude/fiftybox-config.json`, consumed at runtime by `fiftybox-execute`/`fiftybox-local` (Tasks 7-8)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_install.sh`, in the variable block near the top (after
the existing `CODEX_LOCAL_EXECUTE_SKILL_DIR=...` line):

```bash
CONFIG_SKILL_DIR="$INSTALL_ROOT/.claude/skills/fiftybox-config"
USER_CONFIG_FILE="$INSTALL_ROOT/.claude/fiftybox-config.json"
```

Then add, right after the existing `fiftybox-local-execute.md command
wrapper not installed` check (before the `configure.sh: sets agents`
section header):

```bash
[[ -f "$CONFIG_SKILL_DIR/SKILL.md" ]] \
    && pass "fiftybox-config skill installed" \
    || fail "fiftybox-config skill not installed"

[[ -f "$CONFIG_SKILL_DIR/scripts/config_lib.py" ]] \
    && pass "fiftybox-config config_lib.py installed" \
    || fail "fiftybox-config config_lib.py missing"

[[ -f "$CONFIG_SKILL_DIR/scripts/config_tui.py" ]] \
    && pass "fiftybox-config config_tui.py installed" \
    || fail "fiftybox-config config_tui.py missing"

[[ -f "$CONFIG_SKILL_DIR/config/default-config.json" ]] \
    && pass "fiftybox-config default-config.json installed" \
    || fail "fiftybox-config default-config.json missing"

[[ -f "$USER_CONFIG_FILE" ]] \
    && pass "global fiftybox-config.json seeded" \
    || fail "global fiftybox-config.json not seeded"

# Reinstall must not clobber a user's existing provider/model choices
python3 -c "
import json
path = '$USER_CONFIG_FILE'
cfg = json.load(open(path))
cfg['providers']['grok']['enabled'] = False
json.dump(cfg, open(path, 'w'))
"
bash "$SCRIPT_DIR/install.sh" >/dev/null 2>&1
grok_enabled=$(python3 -c "import json; print(json.load(open('$USER_CONFIG_FILE'))['providers']['grok']['enabled'])")
[[ "$grok_enabled" == "False" ]] \
    && pass "reinstall does not clobber existing fiftybox-config.json" \
    || fail "reinstall overwrote existing fiftybox-config.json (grok enabled=$grok_enabled)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_install.sh`
Expected: FAIL on the new `fiftybox-config skill installed` checks (directory doesn't exist yet)

- [ ] **Step 3: Wire up `install.sh`**

Add `CONFIG_SKILL_DIR="$HOME/.claude/skills/fiftybox-config"` to the
variable block at the top of `install.sh` (after the existing
`CODEX_LOCAL_EXECUTE_SKILL_DIR=...` line).

Then add this block right after the existing fiftybox-local install block
(after the `log "Installed Codex skill fiftybox-local → $CODEX_LOCAL_SKILL_DIR"`
line, before the "Claude Code already exposes each installed skill" comment):

```bash
# Install fiftybox-config (provider/model availability toggle TUI)
mkdir -p "$CONFIG_SKILL_DIR/scripts" "$CONFIG_SKILL_DIR/config"
cp "$SCRIPT_DIR/skills/fiftybox-config/SKILL.md" "$CONFIG_SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/skills/fiftybox-config/scripts/"*.py "$CONFIG_SKILL_DIR/scripts/"
cp "$SCRIPT_DIR/skills/fiftybox-config/config/default-config.json" "$CONFIG_SKILL_DIR/config/default-config.json"
log "Installed Claude skill fiftybox-config → $CONFIG_SKILL_DIR"

# Seed the global provider/model settings file only if the user doesn't
# already have one — reinstalling must never clobber their choices.
USER_CONFIG_FILE="$HOME/.claude/fiftybox-config.json"
if [[ ! -f "$USER_CONFIG_FILE" ]]; then
  cp "$SCRIPT_DIR/skills/fiftybox-config/config/default-config.json" "$USER_CONFIG_FILE"
  log "Seeded default provider/model settings → $USER_CONFIG_FILE"
else
  log "Existing provider/model settings kept → $USER_CONFIG_FILE"
fi
```

Also add `fiftybox-config` to the wrapper-cleanup loop's list of command
names (the `for cmd in fiftybox-orchestration fiftybox-plans ...` line), so
a stray `~/.claude/commands/fiftybox-config.md` gets removed the same way
the others do.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_install.sh`
Expected: PASS (all checks, including the new ones)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_install.sh
git commit -m "feat(install): install fiftybox-config and seed its settings file"
```

---

### Task 7: `fiftybox-execute` reads the config for preflight and lane resolution

**Files:**
- Modify: `skills/fiftybox-execute/SKILL.md`
- Modify: `tests/test_execute_skill_doc.sh`

**Interfaces:**
- Consumes: `~/.claude/fiftybox-config.json` schema and `resolve_lane`
  semantics from Tasks 1-2 (referenced by name/behavior in prose, not
  imported as code — `SKILL.md` is instructions for Claude, not a script)
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the failing test**

Append to `tests/test_execute_skill_doc.sh` (before the `echo ""` /
`Results:` footer):

```bash
# --- fiftybox-config integration -------------------------------------------
has "$SKILL" "fiftybox-config.json" "SKILL.md reads the fiftybox-config.json settings file"
has "$SKILL" "resolve_lane" "SKILL.md computes lane assignment via resolve_lane"
has "$SKILL" "lane_priority" "SKILL.md documents lane_priority fallthrough"
has "$SKILL" "/fiftybox-config" "SKILL.md points users to /fiftybox-config when no provider is enabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_execute_skill_doc.sh`
Expected: FAIL on the four new checks

- [ ] **Step 3: Edit `skills/fiftybox-execute/SKILL.md`**

In the `### Step 0 — Preflight` section, replace:

```markdown
### Step 0 — Preflight

provider에 따라 조건부다.

기본 lane mode에서는 네 lane을 모두 확인한다. 명시 override에서는 선택한 lane만
확인한다. CommandCode lane 확인은 `cmd` 설치·인증·모델 가용성 검사다:
```

with:

```markdown
### Step 0 — Preflight

provider에 따라 조건부다.

**먼저 `~/.claude/fiftybox-config.json`을 읽는다** (`/fiftybox-config` 스킬이
관리하는 설정 파일). `providers.<name>.enabled`가 `false`인 provider는 이번
실행에서 존재하지 않는 것으로 취급한다 — 로그인·구독 확인조차 하지 않는다.
파일이 없으면 아직 `/fiftybox-config`를 한 번도 실행하지 않았다는 뜻이니, 리포
기본값(`lane_priority: ["codex-write", "pi", "grok", "commandcode"]`, 모두
`enabled: true`)을 그대로 쓴다.

기본 lane mode에서는 설정에서 `enabled`인 lane만 확인한다. 명시 override에서는
선택한 lane만 확인한다. CommandCode lane 확인은 `cmd` 설치·인증·모델 가용성
검사다:
```

In the `## Model Resolution` section, replace:

```markdown
**기본 lane allocator** (`--provider`/`--model` 모두 생략):

| 우선순위 | 태스크 성격 | executor |
|---|---|---|
| 1 | 보안·데이터 무결성·동시성·새 핵심 인터페이스처럼 강한 추론과 제한적 소유 파일이 필요한 작업 | `codex-write` / `gpt-5.6-luna` |
| 2 | 화면·이미지·브라우저 검증 또는 넓은 문맥을 가진 독립 구현 작업 | `pi` / `zai-coding` / `glm-5.3-flash` |
| 3 | 외부 API·배포 설정·기존 Grok 도구/계정 맥락이 직접 필요한 통합 작업 | `grok` / `grok-4.6` |
| 4 | 위에 속하지 않는 파일 국소적·결정적인 구현 및 테스트 통과 작업 | `commandcode` / `qwen/qwen3.7-flash` |

같은 파일을 소유하거나 선행 의존성이 있는 태스크는 같은 배치로 병렬화하지 않는다.
어느 lane에도 명확히 속하지 않는 작업은 4번 CommandCode로 시작하며, 실패 재시도도
lane을 바꾸지 않는다. lane 간 fallback은 실패 분류와 사용량 근거를 artifact에 남긴 뒤에만
사용한다.
```

with:

```markdown
**기본 lane allocator** (`--provider`/`--model` 모두 생략):

각 우선순위 자리가 기본으로 어떤 provider/model을 쓰는지는
`~/.claude/fiftybox-config.json`의 `lane_priority` 배열과 각 provider의
`enabled`/`models`로 정해진다. 아래 표의 executor 열은 설정 파일의 기본값
기준이다 — provider를 껐다 켰다 해도 태스크 성격→우선순위 자리 매핑 자체는
바뀌지 않는다.

| 우선순위 | 태스크 성격 | executor (기본 설정 기준) |
|---|---|---|
| 1 | 보안·데이터 무결성·동시성·새 핵심 인터페이스처럼 강한 추론과 제한적 소유 파일이 필요한 작업 | `codex-write` / `gpt-5.6-luna` |
| 2 | 화면·이미지·브라우저 검증 또는 넓은 문맥을 가진 독립 구현 작업 | `pi` / `zai-coding` / `glm-5.3-flash` |
| 3 | 외부 API·배포 설정·기존 Grok 도구/계정 맥락이 직접 필요한 통합 작업 | `grok` / `grok-4.6` |
| 4 | 위에 속하지 않는 파일 국소적·결정적인 구현 및 테스트 통과 작업 | `commandcode` / `qwen/qwen3.7-flash` |

실제 배정은 각 우선순위 자리 인덱스로 `resolve_lane`을 계산한 결과를 쓴다:
`lane_priority[i]`가 `enabled: false`(또는 `enabled: true`지만 켜진 모델이
하나도 없음)면 `lane_priority`의 다음 값으로 넘어간다. 그 provider의 모델은
`models`(Pi는 선택된 backend의 `models`) 중 켜진 것 중 첫 번째를 쓴다.
`lane_priority`의 끝까지 가도 켜진 provider가 없으면 그 우선순위 자리는
배정하지 않는다 — 그 자리에 해당하는 태스크가 실제로 있을 때만 중단하고
사용자에게 `/fiftybox-config`로 최소 1개는 켜달라고 안내한다.

같은 파일을 소유하거나 선행 의존성이 있는 태스크는 같은 배치로 병렬화하지 않는다.
자동 fallback으로 배정이 바뀌면 그 사실과 사유를 `model-choice.json`에 남긴다.
실패 재시도는 fallback으로 정해진 lane을 그대로 재사용하며 lane을 다시
바꾸지 않는다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_execute_skill_doc.sh`
Expected: PASS (all checks, including the four new ones)

- [ ] **Step 5: Commit**

```bash
git add skills/fiftybox-execute/SKILL.md tests/test_execute_skill_doc.sh
git commit -m "feat(fiftybox-execute): resolve lane assignment from fiftybox-config.json"
```

---

### Task 8: `fiftybox-local` gates its candidate pool on the config

**Files:**
- Modify: `skills/fiftybox-local/SKILL.md`
- Modify: `tests/test_local_skill_doc.sh`

**Interfaces:**
- Consumes: `~/.claude/fiftybox-config.json` schema from Tasks 1-2 (prose
  reference, same as Task 7)
- Produces: nothing consumed by later tasks (last task in this plan)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_local_skill_doc.sh` (before the `echo ""` /
`Results:` footer):

```bash
has "$SKILL" "fiftybox-config.json" "SKILL.md reads the fiftybox-config.json settings file"
has "$SKILL" "providers.opencode.enabled" "SKILL.md gates opencode discovery on config"
has "$SKILL" "providers.pi.backends.modal-qwen38" "SKILL.md gates modal-qwen38 inclusion on config"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/test_local_skill_doc.sh`
Expected: FAIL on the three new checks

- [ ] **Step 3: Edit `skills/fiftybox-local/SKILL.md`**

Replace the `## 후보 풀 구성` section's opening (through the end of item 2,
leaving item 3 and item 4 as-is) — i.e. replace:

```markdown
## 후보 풀 구성

1. `discover_free_models.py`로 opencode Zen 무료 티어를 실측 탐색한다
   (각 후보에 실제 호출 1회 — 수십 초 걸릴 수 있다). `smoke: ok`인 것만
   후보로 삼는다.

```bash
python3 ~/.claude/skills/fiftybox-local/scripts/discover_free_models.py
```

2. **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
   `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만 가용성
   자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).
```

with:

```markdown
## 후보 풀 구성

**시작 전에 `~/.claude/fiftybox-config.json`을 읽는다** (`/fiftybox-config`
스킬이 관리한다). 이 설정으로 아래 두 후보 원천을 켜고 끈다:

- `providers.opencode.enabled`가 `false`면 1번(무료 티어 탐색) 자체를 생략한다.
- `providers.pi.backends.modal-qwen38`의 `models`에 켜진 모델이 하나도 없으면
  2번(Modal 항상 포함)을 생략한다 — 예를 들어 지출을 잠깐 막고 싶을 때 끌 수
  있다.

설정 파일이 없으면 아직 `/fiftybox-config`를 실행한 적이 없다는 뜻이니, 리포
기본값(둘 다 켜짐)을 그대로 쓴다.

1. (`providers.opencode.enabled`가 `true`일 때만) `discover_free_models.py`로
   opencode Zen 무료 티어를 실측 탐색한다
   (각 후보에 실제 호출 1회 — 수십 초 걸릴 수 있다). `smoke: ok`인 것만
   후보로 삼는다.

```bash
python3 ~/.claude/skills/fiftybox-local/scripts/discover_free_models.py
```

2. (`providers.pi.backends.modal-qwen38`가 config에서 켜져 있을 때만)
   **`modal-qwen38`(Qwen3.8-27B)을 탐색 없이 항상 후보 1개로 추가한다** —
   `IMPL_PROVIDER=modal-qwen38`, `IMPL_MODEL=qwen3.8-27b-q4_k_m`,
   `IMPL_AGENT=piqwen`, `IMPL_TIMEOUT=1800`. 콜드스타트는 있지만 가용성
   자체는 항상 참으로 간주한다(Modal은 pay-per-use라 "무료 티어 소진"
   개념이 없다).
```

Then update item 4 (still in the same section) from:

```markdown
4. `smoke: ok` 후보(opencode 무료 + modal-qwen38 항상 포함)가 하나도 없으면
   중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.**
```

to:

```markdown
4. `smoke: ok` 후보(설정에서 켜진 opencode 무료 + modal-qwen38)가 하나도
   없으면 중단하고 보고한다. **유료 모델로 임의 전환하지 않는다.** config에서
   둘 다 껐다면 `/fiftybox-config`로 최소 하나는 켜야 한다고 안내한다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/test_local_skill_doc.sh`
Expected: PASS (all checks, including the three new ones)

- [ ] **Step 5: Run the full test suite once more**

Run: `for t in tests/test_*.sh; do echo "=== $t ==="; bash "$t" || echo "FAILED: $t"; done && find skills/fiftybox-config/tests -name "test_*.py" -exec python3 -m pytest {} + && find skills/fiftybox-orchestration/tests -name "test_*.py" -exec python3 -m pytest {} +`
Expected: every `.sh` test PASS, both pytest suites PASS

- [ ] **Step 6: Commit**

```bash
git add skills/fiftybox-local/SKILL.md tests/test_local_skill_doc.sh
git commit -m "feat(fiftybox-local): gate candidate pool sources on fiftybox-config.json"
```
