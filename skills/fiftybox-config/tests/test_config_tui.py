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


class _FakeStdscr:
    def __init__(self, maxyx=(1000, 1000)):
        self.lines: list[tuple] = []
        self._maxyx = maxyx

    def erase(self):
        self.lines.clear()

    def addstr(self, *args):
        self.lines.append(args)

    def getmaxyx(self):
        return self._maxyx

    def refresh(self):
        pass


def test_render_draws_header_and_provider_rows_without_raising():
    state = make_state()
    stdscr = _FakeStdscr()
    tui.render(stdscr, state)
    assert stdscr.lines  # something was drawn
    joined = " ".join(str(elem) for line in stdscr.lines for elem in line if isinstance(elem, str))
    assert "grok" in joined


def test_add_model_row_on_models_less_provider_sets_message_and_leaves_config_unchanged():
    state = make_state()
    idx = [r.provider for r in tui.visible_rows(state)].index("opencode")
    state.cursor = idx
    before = dict(state.config["providers"]["opencode"])
    tui.add_model_row(state, "some-model")
    assert state.message
    assert state.config["providers"]["opencode"] == before
    assert "models" not in state.config["providers"]["opencode"]


def test_render_does_not_raise_on_short_terminal():
    state = make_state()
    state.message = "a fairly long warning message that might overflow a narrow terminal"
    stdscr = _FakeStdscr(maxyx=(3, 20))
    tui.render(stdscr, state)  # must not raise
    for args in stdscr.lines:
        y = args[0]
        assert y < 3


def test_main_is_defined_and_callable():
    assert callable(tui.main)
