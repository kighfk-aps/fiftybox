#!/usr/bin/env python3
"""Discover usable OpenRouter free-tier models.

Emits a JSON document on stdout describing ``:free`` candidates and whether
each one currently answers a trivial prompt. Preference order comes from the
fiftybox config (``providers.pi.backends.openrouter-free.models``) and models owned
by other lanes are dropped, either read from the same config (nvidia-nim) or
passed via ``--exclude`` (e.g. the opencode free-tier discovery output).
Knows nothing about orchestrate.py.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CATALOG_URL = "https://openrouter.ai/api/v1/models"
CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

#: Below this context window a model cannot hold a real coding task.
MIN_CONTEXT = 131072

CATALOG_TIMEOUT_SECONDS = 30
SMOKE_TIMEOUT_SECONDS = 30
SMOKE_MAX_TOKENS = 10
SMOKE_PROMPT = "Reply with exactly: OK"

#: Only these smoke outcomes justify one retry behind a backoff. A shared-pool
#: 429 usually clears within seconds; a bare account 429 ("window") will not
#: clear by waiting, and a wrong-model 403/404 never will.
RETRYABLE_SMOKE_RESULTS = ("model_busy", "unknown")
RETRY_BACKOFF_SECONDS = 5

KEYCHAIN_SERVICE = "pi-openrouter-api-key"
KEYCHAIN_TIMEOUT_SECONDS = 10

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "fiftybox-config.json"


def fetch_catalog() -> list[dict]:
    """GET the public OpenRouter model catalog and return its ``data`` list."""
    request = urllib.request.Request(
        CATALOG_URL, headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(
        request, timeout=CATALOG_TIMEOUT_SECONDS
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else None
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(
        data, list
    ) else []


def is_free_tool_model(entry: dict) -> bool:
    """True only for ``:free`` models that accept tools and fit a real task.

    Cost is not inspected because the ``:free`` suffix is the tier marker on
    OpenRouter; the tool parameter is what makes a model usable as an
    implementer, and the context floor filters out toys.
    """
    if not isinstance(entry, dict):
        return False
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id.endswith(":free"):
        return False
    parameters = entry.get("supported_parameters")
    if not isinstance(parameters, list) or "tools" not in parameters:
        return False
    context = entry.get("context_length")
    return isinstance(context, int) and context >= MIN_CONTEXT


def strip_free_suffix(model_id: str) -> str:
    """Remove a trailing ``:free`` marker, leaving any paid id untouched."""
    return model_id[: -len(":free")] if model_id.endswith(":free") else model_id


def base_key(model_id: str) -> str:
    """Reduce a model id to a comparable base name.

    Drops the vendor prefix, case, and free-tier markers so the same model
    published under different vendors (``minimax/minimax-m3:free`` vs
    ``minimaxai/minimax-m3``) collapses to one key.
    """
    name = model_id.rsplit("/", 1)[-1].lower()
    for suffix in (":free", "-free"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def overlaps(or_id: str, other_id: str) -> bool:
    """True when ``or_id`` is the same model (or a size variant) as ``other_id``.

    Equal base keys mean the same model; a base key extending the other with a
    ``-`` separator means a size-suffixed variant of it
    (``nemotron-3-ultra-550b-a55b`` vs ``nemotron-3-ultra``). Siblings such as
    ``laguna-s`` and ``laguna-xs`` share only a prefix without the separator
    and are correctly kept distinct.
    """
    or_key = base_key(or_id)
    other_key = base_key(other_id)
    return or_key == other_key or or_key.startswith(other_key + "-")


def exclude_overlapping(
    candidates: list[dict], other_lane_models: list[str]
) -> list[dict]:
    """Drop candidates already owned by another discovery lane.

    Checked in both directions so a lane id more specific than the candidate
    (or vice versa) still matches.
    """
    kept = []
    for candidate in candidates:
        if any(
            overlaps(candidate["id"], other) or overlaps(other, candidate["id"])
            for other in other_lane_models
        ):
            continue
        kept.append(candidate)
    return kept


def order_candidates(
    candidates: list[dict], config_order: list[str]
) -> list[dict]:
    """Order by config preference first, leftovers by descending context.

    Config entries missing from the catalog are ignored rather than errors —
    the config lists preferred models, it does not mandate them.
    """
    by_id = {candidate["id"]: candidate for candidate in candidates}
    preferred = [
        by_id[model_id]
        for model_id in dict.fromkeys(config_order)
        if model_id in by_id
    ]
    preferred_ids = {candidate["id"] for candidate in preferred}
    rest = [c for c in candidates if c["id"] not in preferred_ids]
    rest.sort(
        key=lambda c: -(c["context"] if isinstance(c.get("context"), int) else -1)
    )
    return preferred + rest


def classify_error(error: dict) -> str:
    """Map an OpenRouter error object to a smoke classification.

    A 429 carrying ``limit_source == "upstream_provider_shared_pool"`` is that
    one model's upstream pool being busy — switching models helps. A bare 429
    is the account's daily/rate window — switching models does not. 403/404
    (or "Unknown model"/"deprecated" phrasing) means the model itself is
    unusable from this harness.
    """
    if not isinstance(error, dict):
        return "unknown"
    code = error.get("code")
    message = str(error.get("message") or "").lower()
    metadata = error.get("metadata")
    limit_source = (
        metadata.get("limit_source")
        if isinstance(metadata, dict)
        else None
    )
    if code == 429 and limit_source == "upstream_provider_shared_pool":
        return "model_busy"
    if code == 503 or "overloaded" in message or "capacity" in message:
        return "model_busy"
    if code == 429:
        return "window"
    if code in (403, 404) or "unknown model" in message or "deprecated" in message:
        return "model"
    return "unknown"


def _chat_completion(
    model_id: str, api_key: str, timeout: int = SMOKE_TIMEOUT_SECONDS
) -> dict:
    """POST one trivial chat completion; return the parsed JSON body.

    HTTP error responses (429/403/...) carry the classification-relevant JSON
    in the error body, so an HTTPError is unwrapped and returned as a dict
    instead of raised. Network-level failures (DNS, refused, timeout) still
    raise and are handled by the caller.
    """
    payload = json.dumps(
        {
            "model": model_id,
            "messages": [{"role": "user", "content": SMOKE_PROMPT}],
            "max_tokens": SMOKE_MAX_TOKENS,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        CHAT_COMPLETIONS_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {"error": {"message": (body or "unparseable response")[:200]}}
    return parsed if isinstance(parsed, dict) else {}


def smoke_test_model(model_id: str, api_key: str) -> dict:
    """Ask one model a trivial question and classify the outcome.

    One retry behind a 5-second backoff is applied for transient outcomes only
    (model_busy, unknown, network errors); a window 429 or a model-level
    rejection is final on the first attempt.
    """
    started = time.monotonic()

    def attempt() -> str:
        try:
            response = _chat_completion(model_id, api_key, SMOKE_TIMEOUT_SECONDS)
        except (urllib.error.URLError, TimeoutError, OSError):
            return "unknown"
        if "error" not in response:
            return "ok"
        return classify_error(response["error"])

    outcome = attempt()
    if outcome in RETRYABLE_SMOKE_RESULTS:
        time.sleep(RETRY_BACKOFF_SECONDS)
        outcome = attempt()
    return {
        "smoke": outcome,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def sort_candidates(candidates: list[dict]) -> list[dict]:
    """Put smoke-ok candidates first; otherwise keep the preference order.

    The sort is stable on purpose: the input already encodes the preference
    ranking (config order, then context descending), and re-sorting the
    not-yet-ok tail by context would discard the config's explicit ranking.
    """
    return sorted(
        candidates, key=lambda c: 0 if c.get("smoke") == "ok" else 1
    )


def load_config_models(config_path: Path, backend: str = "openrouter-free") -> list[str]:
    """Read enabled model ids from the fiftybox config for one backend.

    JSON object key order is preserved (Python dicts are insertion-ordered),
    because that order is the documented preference ranking.
    """
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(config, dict):
        return []
    providers = config.get("providers")
    backends = (
        providers.get("pi", {}).get("backends", {})
        if isinstance(providers, dict)
        else {}
    )
    models = (
        backends.get(backend, {}).get("models", {})
        if isinstance(backends, dict)
        else {}
    )
    if not isinstance(models, dict):
        return []
    return [
        model_id for model_id, enabled in models.items() if enabled is True
    ]


def get_api_key() -> str:
    """Resolve the OpenRouter API key: env var first, Keychain second."""
    env_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        proc = subprocess.run(
            [
                "security", "find-generic-password",
                "-a", os.environ.get("USER", ""),
                "-s", KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True, text=True, timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return (proc.stdout or "").strip()


def discover(
    catalog: list[dict],
    config_order: list[str],
    other_lane_models: list[str],
    skip_smoke: bool = False,
) -> dict:
    """Filter, deduplicate against other lanes, order, and smoke-test.

    With ``skip_smoke`` no API call is made and every candidate reports
    ``smoke: "unknown"``. A ``window`` classification stops all further smoke
    tests and flags ``window_exhausted`` — the account's request window is
    gone, so the remaining models cannot answer either.
    """
    candidates = [
        {
            "id": entry["id"],
            "context": entry.get("context_length"),
            "smoke": "unknown",
            "latency_ms": None,
        }
        for entry in catalog
        if is_free_tool_model(entry)
    ]
    candidates = exclude_overlapping(candidates, other_lane_models)
    candidates = order_candidates(candidates, config_order)

    window_exhausted = False
    if candidates and not skip_smoke:
        api_key = get_api_key()
        if api_key:
            for candidate in candidates:
                outcome = smoke_test_model(candidate["id"], api_key)
                candidate["smoke"] = outcome["smoke"]
                candidate["latency_ms"] = outcome["latency_ms"]
                if outcome["smoke"] == "window":
                    window_exhausted = True
                    break
            candidates = sort_candidates(candidates)

    return {"candidates": candidates, "window_exhausted": window_exhausted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-smoke", action="store_true",
        help="Catalog, dedup and ordering only, without calling any model.",
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH,
        help="Path to fiftybox-config.json (preference order and NIM overlap).",
    )
    parser.add_argument(
        "--exclude", default="",
        help="Comma-separated model ids from other lanes (e.g. opencode free).",
    )
    args = parser.parse_args(argv)

    catalog = fetch_catalog()
    config_order = load_config_models(args.config, backend="openrouter-free")
    other_lane_models = [
        model_id.strip() for model_id in args.exclude.split(",") if model_id.strip()
    ]
    # NIM overlaps are structural (same config file), not per-invocation.
    other_lane_models += load_config_models(args.config, backend="nvidia-nim")

    result = discover(
        catalog,
        config_order,
        other_lane_models,
        skip_smoke=args.skip_smoke,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
