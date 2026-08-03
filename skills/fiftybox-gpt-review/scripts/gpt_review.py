#!/usr/bin/env python3
"""Run a GPT design/plan review through the Codex CLI.

Preflights codex availability (shim detection), validates the model slug against
the Codex model cache, pipes a self-contained prompt into `codex exec`, saves
the raw review to a dated Markdown log, and emits a one-line JSON summary.

This script makes no judgement about the review's content — it only invokes,
validates, and persists. Applying the feedback is Claude's job (SKILL.md).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SHIM_MARKER = "Codex shutout shim"

EXIT_ARGS = 2
EXIT_NO_CODEX = 3
EXIT_BAD_MODEL = 4
EXIT_TIMEOUT = 5
EXIT_CODEX_FAILED = 6

DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 900
DEFAULT_OUT_DIR = "docs/reviews"

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")

REENABLE_HINT = (
    "Codex is disabled on this machine (shutout shim). Re-enable it with:\n"
    "  rm /opt/homebrew/bin/codex\n"
    "  ln -s /opt/homebrew/Caskroom/codex/<version>/bin/codex /opt/homebrew/bin/codex"
)

VERDICTS = ("APPROVED", "REVISE", "BLOCKED")

DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")

REVIEW_CONTRACT = """You are reviewing a design or implementation-plan document.

Respond in exactly this shape:

FIRST LINE: one of APPROVED | REVISE | BLOCKED
THEN: a list of findings. Each finding is

- [severity: blocking|major|minor] one-line summary
  Evidence: which part of the document is wrong, and why
  Proposal: concretely what to change

Judge only these:
- missing steps, unverified assumptions
- missing failure or rollback paths
- test adequacy
- vague interface or module boundaries
- whether a different agent could execute this document unaided from the
  document alone

Out of scope — do not comment on: code style, prose style, or features the
document deliberately does not cover. Do not modify any file."""


def is_shim(path: Path) -> bool:
    """True when `path` is the Mac-wide Codex shutout shim.

    Detection reads the file rather than executing it: both the shim and a
    genuinely broken codex exit 1, so execution cannot tell them apart.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return SHIM_MARKER in text


def find_codex() -> Path | None:
    """The codex executable on PATH, or None when it is not installed."""
    found = shutil.which("codex")
    return Path(found) if found else None


def codex_cache_path() -> Path:
    """<CODEX_HOME>/models_cache.json, or ~/.codex/models_cache.json by default."""
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path(os.path.expanduser("~")) / ".codex"
    return base / "models_cache.json"


def load_model_slugs(cache_path: Path) -> list[str] | None:
    """Slugs from the Codex model cache, or None when it cannot be read.

    None means "cannot validate", not "no models": callers skip validation
    rather than block, so an offline or fresh install still works. Entries
    whose slug is not a string are skipped.
    """
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    models = raw.get("models")
    if not isinstance(models, list):
        return None
    return [m["slug"] for m in models
            if isinstance(m, dict) and isinstance(m.get("slug"), str)]


def build_prompt(doc_name: str, doc_text: str, contexts: list[tuple[str, str]]) -> str:
    """Inline everything the reviewer may read.

    The reviewer runs read-only and is given no repository search task: what it
    sees here is exactly what it reviews, which keeps a review reproducible.
    """
    parts = [REVIEW_CONTRACT, f"\n\n## Document under review: {doc_name}\n\n{doc_text}"]
    for name, text in contexts:
        parts.append(f"\n\n## Context: {name}\n\n{text}")
    return "".join(parts)


def parse_verdict(text: str) -> str:
    """Read the verdict off the first non-blank line; UNKNOWN when off-contract.

    A verdict literal only counts when it is followed by a token boundary:
    end of line, or a character that is neither alphanumeric nor an
    underscore (space, ":", "-", "—", ".", ...). This keeps words like
    "APPROVEDLY" or "BLOCKEDNESS" from being misread as verdicts.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for verdict in VERDICTS:
            if stripped.startswith(verdict):
                rest = stripped[len(verdict):]
                if not rest or not (rest[0].isalnum() or rest[0] == "_"):
                    return verdict
        return "UNKNOWN"
    return "UNKNOWN"


def review_log_path(out_dir: Path, doc_path: Path, today: str) -> Path:
    """<out>/<date>-<doc-slug>-gpt-review[-N].md, never overwriting a log.

    A `YYYY-MM-DD-` prefix already present in the document filename is
    dropped so the review date is not duplicated; the log date is always
    the day the review runs.
    """
    slug = DATE_PREFIX_RE.sub("", doc_path.stem)
    candidate = out_dir / f"{today}-{slug}-gpt-review.md"
    counter = 2
    while candidate.exists():
        candidate = out_dir / f"{today}-{slug}-gpt-review-{counter}.md"
        counter += 1
    return candidate


def build_codex_cmd(model: str, effort: str, output_file: Path) -> list[str]:
    """The `codex exec` command; the trailing "-" reads the prompt from stdin."""
    return [
        "codex", "exec",
        "--model", model,
        "-c", f"model_reasoning_effort={effort}",
        "-s", "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "-o", str(output_file),
        "-",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a GPT design/plan review through the Codex CLI")
    parser.add_argument("--doc", required=True,
                        help="design/plan document to review")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"codex model slug (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort", default=DEFAULT_EFFORT,
                        help=f"reasoning effort (default: {DEFAULT_EFFORT})")
    parser.add_argument("--context", action="append", default=[],
                        help="context file to inline into the prompt (repeatable)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"codex timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR,
                        help=f"review log output directory (default: {DEFAULT_OUT_DIR})")
    args = parser.parse_args(argv)

    codex = find_codex()
    if codex is None:
        print("codex not found on PATH. Install the Codex CLI first.",
              file=sys.stderr)
        return EXIT_NO_CODEX
    if is_shim(codex):
        print(REENABLE_HINT, file=sys.stderr)
        return EXIT_NO_CODEX

    doc_path = Path(args.doc)
    if not doc_path.is_file():
        print(f"document not found: {doc_path}", file=sys.stderr)
        return EXIT_ARGS

    if args.effort not in VALID_EFFORTS:
        print(f"invalid effort '{args.effort}'. "
              f"Valid efforts: {', '.join(VALID_EFFORTS)}", file=sys.stderr)
        return EXIT_ARGS

    if args.timeout <= 0:
        print(f"--timeout must be positive, got {args.timeout}", file=sys.stderr)
        return EXIT_ARGS

    contexts: list[tuple[str, str]] = []
    for raw in args.context:
        ctx = Path(raw)
        if not ctx.is_file():
            print(f"context file not found: {ctx}", file=sys.stderr)
            return EXIT_ARGS
        try:
            text = ctx.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"could not read context file {ctx}: {exc}", file=sys.stderr)
            return EXIT_ARGS
        contexts.append((ctx.name, text))

    slugs = load_model_slugs(codex_cache_path())
    if slugs is None:
        print(f"warning: model cache unavailable — cannot validate "
              f"'{args.model}', continuing", file=sys.stderr)
    elif args.model not in slugs:
        print(f"unknown model '{args.model}'. "
              f"Available: {', '.join(slugs)}", file=sys.stderr)
        return EXIT_BAD_MODEL

    try:
        doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"could not read document {doc_path}: {exc}", file=sys.stderr)
        return EXIT_ARGS
    prompt = build_prompt(doc_path.name, doc_text, contexts)

    # `codex` is resolved through the (possibly restricted) PATH, but it may be
    # a script whose shebang needs env/bash from the standard system dirs, so
    # keep those reachable for the child process too.
    run_env = dict(os.environ)
    run_env["PATH"] = run_env.get("PATH", "") + os.pathsep + os.defpath

    with tempfile.TemporaryDirectory() as tmp:
        last_message = Path(tmp) / "review.txt"
        cmd = build_codex_cmd(args.model, args.effort, last_message)
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True,
                                    text=True, timeout=args.timeout, env=run_env)
        except subprocess.TimeoutExpired:
            print(f"codex review exceeded {args.timeout}s", file=sys.stderr)
            return EXIT_TIMEOUT
        review = (last_message.read_text(encoding="utf-8", errors="replace")
                  if last_message.exists() else "")

    if result.returncode != 0 or not review.strip():
        tail = (result.stderr or result.stdout or "")[-2000:]
        print(f"codex exited {result.returncode}: {tail}", file=sys.stderr)
        return EXIT_CODEX_FAILED

    verdict = parse_verdict(review)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = review_log_path(out_dir, doc_path, today)
    log_path.write_text(
        f"# GPT Review — {doc_path.name}\n\n"
        f"- 대상: {doc_path}\n"
        f"- 모델: {args.model} (effort: {args.effort})\n"
        f"- 시각: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"- 판정: {verdict}\n\n"
        f"## 리뷰 원문\n\n{review.rstrip()}\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "ok": True,
        "docPath": str(doc_path),
        "reviewPath": str(log_path),
        "model": args.model,
        "effort": args.effort,
        "verdict": verdict,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
