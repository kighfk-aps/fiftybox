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
