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
