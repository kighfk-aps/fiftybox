#!/usr/bin/env python3
"""Discover usable opencode Zen free models.

Emits a JSON document on stdout describing free-tier candidates and whether
each one currently answers a trivial prompt. Knows nothing about orchestrate.py.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

MODEL_ID_RE = re.compile(r"(?m)^([a-z0-9][a-z0-9-]*/[A-Za-z0-9._-]+)[ \t]*$")


def parse_verbose_models(text: str) -> list[tuple[str, dict]]:
    """Parse `opencode models <provider> --verbose` output.

    The output repeats a bare `provider/model` line followed by a JSON block.
    Blocks that fail to parse are skipped so one format change cannot blank
    the whole listing.
    """
    parts = MODEL_ID_RE.split(text)
    # parts[0] is whatever preceded the first id line; pairs follow.
    pairs: list[tuple[str, dict]] = []
    for i in range(1, len(parts) - 1, 2):
        model_id = parts[i].strip()
        blob = parts[i + 1]
        try:
            entry = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict):
            pairs.append((model_id, entry))
    return pairs


def parse_plain_models(text: str) -> list[str]:
    """Parse plain `opencode models <provider>` output into model ids."""
    return [m.strip() for m in MODEL_ID_RE.findall(text)]


FREE_PROVIDER = "opencode"


def is_free_candidate(entry: dict) -> bool:
    """True only for opencode Zen free-tier models usable as an implementer.

    Cost alone is not sufficient: subscription-authenticated providers such as
    openai and zai also report zero cost but consume the user's paid quota.
    The provider scope is therefore part of the rule, not an optimisation.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("providerID") != FREE_PROVIDER:
        return False
    if entry.get("status") != "active":
        return False
    cost = entry.get("cost")
    if not isinstance(cost, dict):
        return False
    if cost.get("input") != 0 or cost.get("output") != 0:
        return False
    capabilities = entry.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    return capabilities.get("toolcall") is True


def to_candidate(model_id: str, entry: dict) -> dict:
    """Build the candidate record emitted to stdout (pre-smoke-test)."""
    limit = entry.get("limit") if isinstance(entry.get("limit"), dict) else {}
    capabilities = entry.get("capabilities") if isinstance(entry.get("capabilities"), dict) else {}
    return {
        "id": model_id,
        "context": limit.get("context"),
        "toolcall": capabilities.get("toolcall"),
        "smoke": "unknown",
        "latency_ms": None,
    }


def sort_candidates(candidates: list[dict]) -> list[dict]:
    """Sort by smoke result (ok first), then by descending context."""
    def key(candidate: dict):
        context = candidate.get("context")
        return (
            0 if candidate.get("smoke") == "ok" else 1,
            -(context if isinstance(context, int) else -1),
        )

    return sorted(candidates, key=key)


SMOKE_TIMEOUT_SECONDS = 30
SMOKE_MAX_WORKERS = 4
SMOKE_PROMPT = "reply with exactly: OK"
RATE_LIMIT_PATTERNS = ("429", "rate limit", "quota", "insufficient")


def classify_smoke(returncode: int, output: str, timed_out: bool) -> str:
    """Classify one smoke-test run.

    opencode does not distinguish rate limiting by exit code, so the output is
    pattern-matched. A rate-limit phrase wins even on a zero exit code.
    """
    if timed_out:
        return "timeout"
    lowered = (output or "").lower()
    if any(pattern in lowered for pattern in RATE_LIMIT_PATTERNS):
        return "rate_limited"
    return "ok" if returncode == 0 else "error"


def run_smoke_test(model_id: str, timeout: int = SMOKE_TIMEOUT_SECONDS) -> tuple[str, int]:
    """Ask one model a trivial question in a throwaway directory.

    The prompt makes no edits, so no permission flag is passed and the user's
    repository is never the working directory.
    """
    cmd = ["opencode", "run", "--model", model_id, "--format", "json", SMOKE_PROMPT]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fiftybox-smoke-") as workdir:
        try:
            proc = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "timeout", int((time.monotonic() - started) * 1000)
        except (FileNotFoundError, OSError):
            return "error", int((time.monotonic() - started) * 1000)
    latency_ms = int((time.monotonic() - started) * 1000)
    combined = f"{proc.stdout}\n{proc.stderr}"
    return classify_smoke(proc.returncode, combined, timed_out=False), latency_ms


def smoke_test_all(
    candidates: list[dict], max_workers: int = SMOKE_MAX_WORKERS
) -> list[dict]:
    """Smoke-test every candidate concurrently, returning updated copies."""
    if not candidates:
        return []
    results = [dict(candidate) for candidate in candidates]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        outcomes = list(pool.map(lambda c: run_smoke_test(c["id"]), results))
    for candidate, (smoke, latency_ms) in zip(results, outcomes):
        candidate["smoke"] = smoke
        candidate["latency_ms"] = latency_ms
    return results


LIST_TIMEOUT_SECONDS = 60


def _run_capture(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=LIST_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return proc.stdout or ""


def list_models_verbose() -> str:
    return _run_capture(
        ["opencode", "models", FREE_PROVIDER, "--verbose", "--refresh"]
    )


def list_models_plain() -> str:
    return _run_capture(["opencode", "models", FREE_PROVIDER])


def discover(skip_smoke: bool = False) -> dict:
    """Find opencode free-tier models that can act as an implementer.

    Falls back to the plain listing when no verbose block parses, rather than
    reporting an empty list — a format change must be visible, not silent.
    """
    parsed = parse_verbose_models(list_models_verbose())
    metadata_degraded = not parsed

    if parsed:
        candidates = [
            to_candidate(model_id, entry)
            for model_id, entry in parsed
            if is_free_candidate(entry)
        ]
    else:
        prefix = f"{FREE_PROVIDER}/"
        candidates = [
            {"id": model_id, "context": None, "toolcall": None,
             "smoke": "unknown", "latency_ms": None}
            for model_id in parse_plain_models(list_models_plain())
            if model_id.startswith(prefix)
        ]

    if candidates and not skip_smoke:
        candidates = smoke_test_all(candidates)

    return {
        "metadata_degraded": metadata_degraded,
        "candidates": sort_candidates(candidates),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-smoke", action="store_true",
        help="List candidates from metadata only, without calling each model.",
    )
    args = parser.parse_args(argv)
    print(json.dumps(discover(skip_smoke=args.skip_smoke), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
