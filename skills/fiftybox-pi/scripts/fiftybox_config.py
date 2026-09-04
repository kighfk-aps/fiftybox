#!/usr/bin/env python3
"""Config loader for the fiftybox-pi Pi CLI skill.

Resolution order: $FIFTYBOX_PI_CONFIG > ~/.pi/agent/fiftybox-config.json >
embedded defaults. A malformed user config never blocks a run: it degrades to
defaults with a ``_config_error`` warning, mirroring orchestrate.py's
config.json behavior.

Self-test: ``python3 fiftybox_config.py --selftest``
Write defaults: ``python3 fiftybox_config.py --init [--force]``
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".pi" / "agent" / "fiftybox-config.json"

# Tiered routing defaults (see docs/plans/2026-09-04-fiftybox-pi-port.md §3/§5).
# All providers below already exist in ~/.pi/agent/models.json on this machine.
DEFAULTS: dict = {
    # Orchestrator session (top tier): design, Red tests, review gates.
    "session": {
        "preferred": ["zai-coding/glm-5.3", "xai-auth/grok-4.6"],
        "warnBelowTier": True,
    },
    # Cheap tier: Phase 1 read-only exploration.
    "explore": {
        "fallback": [
            "openrouter-free:auto",
            "zai-coding/glm-5.3-flash",
            "nvidia-nim/openai/gpt-oss-120b",
        ],
    },
    # Free tier only: Phase 5 implementation. Never falls back to paid.
    "implement": {
        "lane_priority": [
            "openrouter-free",
            "nvidia-nim",
            "groq",
            "modal-qwen38",
            "turbofieldfare",
        ],
    },
    # Top tier: opt-in advisory diff review (read-only sandbox).
    "review": {
        "model": "zai-coding/glm-5.3",
        "fallback": ["xai-auth/grok-4.6"],
        "tools": "read,grep,find,ls",
    },
    "providers": {
        "zai-coding": {
            "enabled": True,
            "models": {"glm-5.3": True, "glm-5.3-flash": True, "glm-5.2": False},
        },
        "xai-auth": {"enabled": True, "models": {"grok-4.6": True}},
        "openrouter-free": {
            "enabled": True,
            "discovery": True,
            "models": {},  # discovered fresh each run via discover_openrouter_free.py
        },
        "nvidia-nim": {
            "enabled": True,
            "models": {
                "openai/gpt-oss-120b": True,
                "moonshotai/kimi-k3": True,
                "poolside/laguna-xs-2.1": True,
                "minimaxai/minimax-m3": True,
            },
        },
        "groq": {
            "enabled": False,  # flips on when GROQ_API_KEY exists and preflight passes
            "apiKeyEnv": "GROQ_API_KEY",
            "models": {},
        },
        "modal-qwen38": {
            "enabled": True,
            "models": {"qwen3.8-27b-q4_k_m": True},
            "agent": "piqwen",
        },
        "cerebras": {
            "enabled": False,  # catalog exists; inactive until API key preflight passes
            "apiKeyEnv": "CEREBRAS_API_KEY",
            "models": {"qwen3.8-27b": True},
        },
        "turbofieldfare": {
            "enabled": True,
            "models": {"gemma-4-26b-a4b-it": True},
            "lastResort": True,
        },
    },
    # Machine-readable failure routing (see references/failure-classification.md).
    "fallbackRules": {
        "accountScope": ["auth", "window", "credit"],
        "modelScope": ["model", "model_busy"],
        "taskScope": ["timeout", "no_changes", "unknown"],
        "neverPaidFallbackFromFree": True,
    },
    # Runner wall-clock timeouts in seconds (pi's internal retries can stall a
    # single call for minutes; the runner always enforces its own limit).
    "timeouts": {
        "smoke": 120,
        "explore": 900,
        "implement": 1800,
        "review": 900,
    },
}

# Session models considered "top tier" for warnBelowTier.
TOP_TIER_PREFIXES = ("zai-coding/glm-5.3", "xai-auth/grok-4.6")

# Models that may serve implement dispatch under any circumstance.
PAID_PROVIDERS = ("zai-coding", "xai-auth", "cerebras")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base; override wins on conflicts."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def config_path(explicit: str | None = None) -> Path:
    """Resolve the config file path: arg > env > default location."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("FIFTYBOX_PI_CONFIG", "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: str | None = None) -> dict:
    """Load user config over defaults; malformed config degrades to defaults.

    Returns a dict that always contains every default key. A ``_config_error``
    key signals that the user file existed but was invalid (never fatal).
    """
    path_obj = config_path(path)
    if not path_obj.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        raw = json.loads(path_obj.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"config must be a JSON object, got {type(raw).__name__}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        merged = copy.deepcopy(DEFAULTS)
        merged["_config_error"] = str(exc)
        return merged
    merged = _deep_merge(DEFAULTS, raw)
    error = merged.pop("_config_error", None)
    merged = _validate(merged)
    if error:
        merged["_config_error"] = error
    return merged


def _validate(config: dict) -> dict:
    """Coerce known-shape mistakes into safe values; record problems."""
    problems: list[str] = []
    lanes = config.get("implement", {}).get("lane_priority")
    if not isinstance(lanes, list) or not all(isinstance(l, str) for l in lanes):
        problems.append("implement.lane_priority must be a list of strings")
        config.setdefault("implement", {})["lane_priority"] = (
            DEFAULTS["implement"]["lane_priority"])
    providers = config.get("providers")
    if not isinstance(providers, dict):
        problems.append("providers must be an object")
        providers = config["providers"] = copy.deepcopy(DEFAULTS["providers"])
    for name, spec in providers.items():
        if not isinstance(spec, dict):
            problems.append(f"providers.{name} must be an object")
            providers[name] = {"enabled": False}
    timeouts = config.get("timeouts")
    if isinstance(timeouts, dict):
        for key, value in timeouts.items():
            if not isinstance(value, (int, float)) or value <= 0:
                problems.append(f"timeouts.{key} must be a positive number")
                timeouts[key] = DEFAULTS["timeouts"].get(key, 900)
    if problems:
        config["_validation_warnings"] = problems
    return config


def active_lanes(config: dict) -> list[str]:
    """Implement lanes that are enabled, in configured priority order."""
    providers = config.get("providers", {})
    lanes = []
    for lane in config.get("implement", {}).get("lane_priority", []):
        spec = providers.get(lane, {})
        if not isinstance(spec, dict) or not spec.get("enabled"):
            continue
        api_env = spec.get("apiKeyEnv")
        if api_env and not os.environ.get(api_env, "").strip():
            continue
        lanes.append(lane)
    return lanes


def lane_models(config: dict, lane: str) -> list[str]:
    """Enabled model ids for a lane, in JSON key (= fallback) order.

    An empty result means the lane discovers models at runtime (openrouter-free).
    """
    spec = config.get("providers", {}).get(lane, {})
    models = spec.get("models", {}) if isinstance(spec, dict) else {}
    return [name for name, on in models.items() if on]


def parse_model_ref(ref: str) -> tuple[str, str]:
    """Split "provider/model" (first slash wins — NIM ids contain slashes)."""
    if "/" not in ref:
        raise ValueError(f"model ref must be 'provider/model', got {ref!r}")
    provider, model = ref.split("/", 1)
    return provider, model


def session_models(config: dict) -> list[str]:
    """Preferred orchestrator session models in order."""
    refs = config.get("session", {}).get("preferred", [])
    return [r for r in refs if isinstance(r, str) and r.strip()]


def review_models(config: dict) -> list[str]:
    """Advisory diff-review models in order (primary + fallbacks)."""
    review = config.get("review", {})
    refs = [review.get("model", "")] + list(review.get("fallback", []))
    return [r for r in refs if isinstance(r, str) and r.strip()]


def explore_models(config: dict) -> list[str]:
    """Explore-tier model refs in fallback order."""
    refs = config.get("explore", {}).get("fallback", [])
    return [r for r in refs if isinstance(r, str) and r.strip()]


def is_top_tier(model_ref: str) -> bool:
    """True when the ref belongs to a designated top-tier model."""
    return any(model_ref.startswith(p) for p in TOP_TIER_PREFIXES)


def assert_no_paid_implement(config: dict, provider: str) -> None:
    """Guard: refuse a paid provider as an implement dispatch target.

    Implements fallbackRules.neverPaidFallbackFromFree as a hard stop so a
    mis-edited config cannot silently burn paid quota from the implement lane.
    """
    if not config.get("fallbackRules", {}).get("neverPaidFallbackFromFree", True):
        return
    if provider in PAID_PROVIDERS:
        raise ValueError(
            f"implement dispatch refused: provider '{provider}' is paid "
            f"(fallbackRules.neverPaidFallbackFromFree)")


def write_default_config(path: str | None, force: bool = False) -> Path:
    """Write embedded defaults to the target path; refuse to clobber."""
    target = config_path(path)
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists (use --force to overwrite)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return target


def selftest() -> int:
    """Assertion battery run without network or a user config file."""
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)
        print(f"  {'ok' if cond else 'FAIL'} — {name}")

    defaults = copy.deepcopy(DEFAULTS)
    required = {"session", "explore", "implement", "review", "providers",
                "fallbackRules", "timeouts"}
    check("defaults contain every required section",
          required.issubset(DEFAULTS) and required.issubset(defaults))
    check("active lanes exclude disabled groq/cerebras",
          "groq" not in active_lanes(defaults)
          and "cerebras" not in active_lanes(defaults))
    check("lane order preserved",
          active_lanes(defaults)[0] == "openrouter-free")
    check("nim lane models ordered",
          lane_models(defaults, "nvidia-nim")[0] == "openai/gpt-oss-120b")
    check("openrouter-free discovers at runtime",
          lane_models(defaults, "openrouter-free") == [])
    check("parse_model_ref splits on first slash",
          parse_model_ref("nvidia-nim/openai/gpt-oss-120b")
          == ("nvidia-nim", "openai/gpt-oss-120b"))
    check("session preferred is top tier",
          all(is_top_tier(r) for r in session_models(defaults)))
    check("review models primary first",
          review_models(defaults)[0] == "zai-coding/glm-5.3")
    try:
        assert_no_paid_implement(defaults, "zai-coding")
        check("paid implement refused", False)
    except ValueError:
        check("paid implement refused", True)
    assert_no_paid_implement({**defaults,
                              "fallbackRules": {"neverPaidFallbackFromFree": False}},
                             "zai-coding")
    check("guard respects opt-out", True)

    # Malformed user config degrades to defaults with an error marker.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        fh.write("{ not json")
        bad_path = fh.name
    try:
        bad = load_config(bad_path)
        check("malformed config -> defaults + _config_error",
              "_config_error" in bad and bad["implement"]["lane_priority"]
              == DEFAULTS["implement"]["lane_priority"])
    finally:
        os.unlink(bad_path)

    # Validation coercion: bad lane_priority falls back to defaults.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"implement": {"lane_priority": "not-a-list"}}, fh)
        ugly_path = fh.name
    try:
        ugly = load_config(ugly_path)
        check("bad lane_priority coerced + warned",
              ugly["implement"]["lane_priority"] == DEFAULTS["implement"]["lane_priority"]
              and ugly.get("_validation_warnings"))
    finally:
        os.unlink(ugly_path)

    print(f"fiftybox_config selftest: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fiftybox-pi config utility")
    parser.add_argument("--selftest", action="store_true",
                        help="run the assertion battery and exit")
    parser.add_argument("--init", action="store_true",
                        help="write the default config to the resolved path")
    parser.add_argument("--force", action="store_true",
                        help="allow --init to overwrite an existing config")
    parser.add_argument("--path", help="override the config file path")
    parser.add_argument("--print", dest="print_config", action="store_true",
                        help="print the merged effective config as JSON")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.init:
        print(write_default_config(args.path, force=args.force))
        return 0
    print(json.dumps(load_config(args.path), indent=2, ensure_ascii=False)
          if args.print_config else config_path(args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
