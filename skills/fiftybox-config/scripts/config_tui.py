"""Interactive TUI for fiftybox-config.

State/row/key-handling logic below is pure (no curses import needed to run
it), so it is unit-tested without a real terminal. `render` and `main`
(Task 4) are the only functions that touch curses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import config_lib as cl
import curses  # noqa: E402  (kept below dataclass imports intentionally)


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
