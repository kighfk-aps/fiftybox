#!/usr/bin/env python3
"""Check that CommandCode (`cmd`) is ready to act as an implementer.

Emits a JSON document on stdout describing installation, authentication, and
model availability. Knows nothing about orchestrate.py.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# `cmd --list-models` prints "<id><2+ spaces><description>" rows between plain
# section headers ("Open Source", "Anthropic"). Headers carry no double space,
# so requiring one is what excludes them. Ids are either "vendor/model" or a
# bare name such as "claude-sonnet-5".
MODEL_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._/-]*)\s{2,}\S")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def parse_models(text: str) -> list[str]:
    """Extract model ids from `cmd --list-models` output, preserving order."""
    models: list[str] = []
    for line in strip_ansi(text).splitlines():
        match = MODEL_LINE_RE.match(line)
        if match:
            models.append(match.group(1))
    return models


def run_cmd(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def emit(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def preflight(required: list[str], timeout: int) -> dict:
    if shutil.which("cmd") is None:
        return {
            "ok": False,
            "status": "not_installed",
            "message": "CommandCode CLI가 없습니다. `npm i -g command-code`로 설치하세요.",
            "models": [],
            "missingModels": list(required),
        }

    try:
        status = run_cmd(["status"], timeout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "not_authenticated",
            "message": f"`cmd status`가 {timeout}초 안에 응답하지 않았습니다.",
            "models": [],
            "missingModels": list(required),
        }
    if status.returncode != 0:
        return {
            "ok": False,
            "status": "not_authenticated",
            # Surface the CLI's own wording so the user runs whatever login
            # command this version actually documents.
            "message": strip_ansi(status.stdout).strip(),
            "models": [],
            "missingModels": list(required),
        }

    try:
        listing = run_cmd(["--list-models"], timeout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "list_failed",
            "message": f"`cmd --list-models`가 {timeout}초 안에 응답하지 않았습니다.",
            "models": [],
            "missingModels": list(required),
        }
    if listing.returncode != 0:
        return {
            "ok": False,
            "status": "list_failed",
            "message": strip_ansi(listing.stdout).strip(),
            "models": [],
            "missingModels": list(required),
        }

    models = parse_models(listing.stdout)
    missing = [m for m in required if m not in models]
    if missing:
        return {
            "ok": False,
            "status": "missing_models",
            "message": "요구한 모델이 목록에 없습니다: " + ", ".join(missing),
            "models": models,
            "missingModels": missing,
        }

    return {
        "ok": True,
        "status": "ready",
        "message": f"CommandCode 준비 완료 — 모델 {len(models)}개.",
        "models": models,
        "missingModels": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-model",
        action="append",
        default=[],
        dest="required",
        help="이 모델이 목록에 있어야 한다 (반복 가능)",
    )
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    return emit(preflight(args.required, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
