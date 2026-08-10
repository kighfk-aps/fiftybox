#!/usr/bin/env python3
"""Run a GPT advisory review of one task's code diff through the Codex CLI.

Sibling of fiftybox-gpt-review/scripts/gpt_review.py, which reviews design and
plan documents. The two are deliberately separate files: the review contract
and the inputs differ, and folding both into one script would mean a mode flag
threaded through every function.

The reviewer runs read-only and cannot execute anything, so it judges spec
conformance and test adequacy from inlined text only. Whether the suite is
green is verified by Claude before this script is ever called. This script
makes no judgement about the review's content — it invokes, parses, persists.
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

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")

REENABLE_HINT = (
    "Codex is disabled on this machine (shutout shim). Re-enable it with:\n"
    "  rm /opt/homebrew/bin/codex\n"
    "  ln -s /opt/homebrew/Caskroom/codex/<version>/bin/codex /opt/homebrew/bin/codex"
)

VERDICTS = ("APPROVED", "REVISE", "BLOCKED")

FINDING_RE = re.compile(r"^\s*-\s*\[severity:\s*(?:blocking|major|minor)\]",
                        re.IGNORECASE)

DIFF_REVIEW_CONTRACT = """You are reviewing a code diff against its task specification and acceptance tests.

Respond in exactly this shape:

FIRST LINE: one of APPROVED | REVISE | BLOCKED
THEN: a list of findings. Each finding is

- [severity: blocking|major|minor] one-line summary
  Evidence: which part of the diff or spec is wrong, and why
  Proposal: concretely what to change

Judge only these:
- does the diff satisfy every requirement in the task spec
- do the acceptance tests actually cover the spec, or do they pass
  vacuously (tautological assertions, mocked-away behavior, missing
  edge cases the spec names)
- scope creep: changes outside the task's files, unrelated edits
- missing requirements or half-implemented behavior

You cannot run anything. Judge from the text you were given. Never claim a test passed or failed — whether the suite is green has already been verified by another reviewer.

Out of scope — do not comment on: code style, naming, prose,
cross-task integration conflicts (a separate reviewer owns that),
or anything the spec deliberately defers. Do not modify any file."""


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


def build_prompt(spec_name: str, spec_text: str,
                 diff_name: str, diff_text: str,
                 tests: list[tuple[str, str]],
                 contexts: list[tuple[str, str]]) -> str:
    """Inline everything the reviewer may read, spec first.

    The spec leads because it is the yardstick: the reviewer should know what
    was asked before it reads what was done. The reviewer is read-only and is
    given no repository search task, so what it sees here is exactly what it
    reviews, which keeps a review reproducible.
    """
    parts = [
        DIFF_REVIEW_CONTRACT,
        f"\n\n## Task specification: {spec_name}\n\n{spec_text}",
        f"\n\n## Diff under review: {diff_name}\n\n```diff\n{diff_text}\n```",
    ]
    for name, text in tests:
        parts.append(f"\n\n## Acceptance test: {name}\n\n{text}")
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


def count_findings(text: str) -> int:
    """Number of contract-shaped finding headers in the review.

    Off-contract prose counts zero. A zero count next to a REVISE verdict is
    the signal for Claude to read the raw log rather than trust the summary.
    """
    return sum(1 for line in text.splitlines() if FINDING_RE.match(line))


def diff_review_log_path(out_dir: Path, task_name: str, today: str) -> Path:
    """<out>/<date>-<task>-gpt-review[-N].md, never overwriting a log.

    The counter is what makes a re-review of the same task on the same day
    keep its predecessor, so callers must use the returned path rather than
    rebuilding it.
    """
    candidate = out_dir / f"{today}-{task_name}-gpt-review.md"
    counter = 2
    while candidate.exists():
        candidate = out_dir / f"{today}-{task_name}-gpt-review-{counter}.md"
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


def read_pairs(raw_paths: list[str]) -> list[tuple[str, str]] | None:
    """(filename, text) for each path, or None after reporting the first failure.

    An empty input list yields an empty list — used for the optional
    ``--context`` argument when none is supplied.
    """
    pairs: list[tuple[str, str]] = []
    for raw in raw_paths:
        path = Path(raw)
        if not path.is_file():
            print(f"file not found: {path}", file=sys.stderr)
            return None
        try:
            pairs.append((path.name, path.read_text(encoding="utf-8", errors="replace")))
        except OSError as exc:
            print(f"could not read {path}: {exc}", file=sys.stderr)
            return None
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a GPT advisory review of a task diff through the Codex CLI")
    parser.add_argument("--diff", required=True, help="git diff for this task")
    parser.add_argument("--spec", required=True, help="task specification file")
    parser.add_argument("--test", action="append", required=True,
                        help="acceptance test file (repeatable)")
    parser.add_argument("--context", action="append", default=[],
                        help="extra context file to inline (repeatable)")
    parser.add_argument("--task-name", required=True, dest="task_name",
                        help="task identifier used in the log filename")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"codex model slug (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort", default=DEFAULT_EFFORT,
                        help=f"reasoning effort (default: {DEFAULT_EFFORT})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"codex timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--out", required=True, help="review log output directory")
    args = parser.parse_args(argv)

    codex = find_codex()
    if codex is None:
        print("codex not found on PATH. Install the Codex CLI first.",
              file=sys.stderr)
        return EXIT_NO_CODEX
    if is_shim(codex):
        print(REENABLE_HINT, file=sys.stderr)
        return EXIT_NO_CODEX

    if args.effort not in VALID_EFFORTS:
        print(f"invalid effort '{args.effort}'. "
              f"Valid efforts: {', '.join(VALID_EFFORTS)}", file=sys.stderr)
        return EXIT_ARGS
    if args.timeout <= 0:
        print(f"--timeout must be positive, got {args.timeout}", file=sys.stderr)
        return EXIT_ARGS

    diff_pair = read_pairs([args.diff])
    spec_pair = read_pairs([args.spec])
    tests = read_pairs(args.test)
    contexts = read_pairs(args.context)
    if diff_pair is None or spec_pair is None or tests is None or contexts is None:
        return EXIT_ARGS

    slugs = load_model_slugs(codex_cache_path())
    if slugs is None:
        print(f"warning: model cache unavailable — cannot validate "
              f"'{args.model}', continuing", file=sys.stderr)
    elif args.model not in slugs:
        print(f"unknown model '{args.model}'. "
              f"Available: {', '.join(slugs)}", file=sys.stderr)
        return EXIT_BAD_MODEL

    prompt = build_prompt(spec_pair[0][0], spec_pair[0][1],
                          diff_pair[0][0], diff_pair[0][1], tests, contexts)

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
    findings = count_findings(review)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = diff_review_log_path(out_dir, args.task_name, today)
    log_path.write_text(
        f"# GPT Diff Review — {args.task_name}\n\n"
        f"- diff: {args.diff}\n"
        f"- 명세: {args.spec}\n"
        f"- 테스트: {', '.join(args.test)}\n"
        f"- 모델: {args.model} (effort: {args.effort})\n"
        f"- 시각: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"- 판정: {verdict} (findings: {findings})\n\n"
        f"## 리뷰 원문\n\n{review.rstrip()}\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "ok": True,
        "taskName": args.task_name,
        "diffPath": args.diff,
        "reviewPath": str(log_path),
        "model": args.model,
        "effort": args.effort,
        "verdict": verdict,
        "findingsCount": findings,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
