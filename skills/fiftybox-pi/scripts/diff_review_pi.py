#!/usr/bin/env python3
"""Run a top-tier advisory review of one task's code diff through headless pi.

Port of fiftybox-execute/scripts/diff_review.py: the review contract, inputs,
verdict parsing, exit-code contract (2-6) and stdout JSON shape are preserved;
only the executor changes — `codex exec -s read-only` becomes a read-only
`pi --mode json` child driven by pi_runner (S0 exit-judgment contract).

The reviewer may read files (read/grep/find/ls) but can never write or
execute, so whether the suite is green is still verified by the orchestrator
before this script is called. This script makes no judgement about the
review's content — it invokes, parses, persists.

Self-test: ``python3 diff_review_pi.py --selftest`` (offline).
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pi_runner  # noqa: E402

EXIT_ARGS = 2
EXIT_NO_PI = 3
EXIT_BAD_MODEL = 4
EXIT_TIMEOUT = 5
EXIT_PI_FAILED = 6

DEFAULT_PROVIDER = "zai-coding"
DEFAULT_MODEL = "glm-5.3"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 900
REVIEW_TOOLS = "read,grep,find,ls"

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
EFFORT_TO_THINKING = {"low": "low", "medium": "medium", "high": "high",
                      "xhigh": "high", "max": "max", "ultra": "max"}

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

You may read repository files with the read/grep/find tools, but you cannot
execute commands or modify anything. Judge primarily from the text you were
given; read files only to confirm a suspicion. Never claim a test passed or
failed — whether the suite is green has already been verified by another
reviewer.

Out of scope — do not comment on: code style, naming, prose,
cross-task integration conflicts (a separate reviewer owns that),
or anything the spec deliberately defers. Do not modify any file."""


def build_prompt(spec_name: str, spec_text: str,
                 diff_name: str, diff_text: str,
                 tests: list[tuple[str, str]],
                 contexts: list[tuple[str, str]]) -> str:
    """Inline everything the reviewer should judge, spec first. Identical to
    the codex version — the yardstick (spec) leads."""
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
    """First non-blank line must start with a verdict literal + boundary;
    anything else is UNKNOWN. Identical to the codex version."""
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
    """Contract-shaped finding headers; zero + REVISE means read the raw log."""
    return sum(1 for line in text.splitlines() if FINDING_RE.match(line))


def list_provider_models(provider: str) -> list[str] | None:
    """Model ids from `pi --list-models <provider>`, or None when it fails.

    None means "cannot validate", not "no models": callers skip validation
    rather than block (same semantics as the codex model cache).
    """
    try:
        proc = subprocess.run([pi_runner.PI, "--list-models", provider],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    models: list[str] = []
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == provider and parts[1] != "model":
            models.append(parts[1])
    return models


def read_pairs(raw_paths: list[str]) -> list[tuple[str, str]] | None:
    """(filename, text) for each path, or None after reporting the failure."""
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


def review_log_path(out_dir: Path, task_name: str, today: str) -> Path:
    """<out>/<date>-<task>-pi-review[-N].md — never overwrite a log."""
    candidate = out_dir / f"{today}-{task_name}-pi-review.md"
    counter = 2
    while candidate.exists():
        candidate = out_dir / f"{today}-{task_name}-pi-review-{counter}.md"
        counter += 1
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a pi-driven advisory review of a task diff")
    parser.add_argument("--diff", help="git diff for this task")
    parser.add_argument("--spec", help="task specification file")
    parser.add_argument("--test", action="append",
                        help="acceptance test file (repeatable)")
    parser.add_argument("--context", action="append", default=[],
                        help="extra context file to inline (repeatable)")
    parser.add_argument("--task-name", dest="task_name",
                        help="task identifier used in the log filename")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER,
                        help=f"pi provider (default: {DEFAULT_PROVIDER})")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"pi model id (default: {DEFAULT_MODEL})")
    parser.add_argument("--effort", default=DEFAULT_EFFORT,
                        help=f"reasoning effort, mapped to pi --thinking "
                             f"(default: {DEFAULT_EFFORT})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"review timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--out", help="review log output directory")
    parser.add_argument("--audit", help="optional pi_runner audit JSONL path")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    missing = [name for name, val in (("--diff", args.diff), ("--spec", args.spec),
                                      ("--test", args.test),
                                      ("--task-name", args.task_name),
                                      ("--out", args.out)) if not val]
    if missing:
        parser.error("the following arguments are required: " + ", ".join(missing))

    if shutil.which(pi_runner.PI) is None:
        print("pi not found on PATH. Install the Pi CLI first.", file=sys.stderr)
        return EXIT_NO_PI
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

    models = list_provider_models(args.provider)
    if models is None:
        print(f"warning: cannot list models for '{args.provider}' — "
              f"skipping model validation", file=sys.stderr)
    elif args.model not in models:
        print(f"unknown model '{args.model}' for provider '{args.provider}'. "
              f"Available: {', '.join(models[:20])}", file=sys.stderr)
        return EXIT_BAD_MODEL

    prompt = build_prompt(spec_pair[0][0], spec_pair[0][1],
                          diff_pair[0][0], diff_pair[0][1], tests, contexts)
    run = pi_runner.run_pi(
        task="", provider=args.provider, model=args.model,
        tools=REVIEW_TOOLS, stdin_prompt=prompt, timeout=args.timeout,
        system_prompt="You are an advisory code reviewer. Follow the output "
                      "contract exactly.",
        extra_args=["--thinking", EFFORT_TO_THINKING[args.effort]])

    if run.timed_out:
        print(f"pi review exceeded {args.timeout}s", file=sys.stderr)
        return EXIT_TIMEOUT
    review = run.final_text
    if not run.ok or not review.strip():
        detail = "; ".join(run.errors[-2:]) or run.stderr_tail or "empty review"
        print(f"pi review failed ({run.last_error_class}): {detail}",
              file=sys.stderr)
        return EXIT_PI_FAILED

    verdict = parse_verdict(review)
    findings = count_findings(review)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = review_log_path(out_dir, args.task_name, today)
    log_path.write_text(
        f"# Pi Diff Review — {args.task_name}\n\n"
        f"- diff: {args.diff}\n"
        f"- 명세: {args.spec}\n"
        f"- 테스트: {', '.join(args.test)}\n"
        f"- 모델: {args.provider}/{args.model} (thinking: "
        f"{EFFORT_TO_THINKING[args.effort]})\n"
        f"- 시각: {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        f"- 판정: {verdict} (findings: {findings})\n\n"
        f"## 리뷰 원문\n\n{review.rstrip()}\n",
        encoding="utf-8",
    )
    if args.audit:
        pi_runner.append_audit(args.audit, {
            "kind": "diff_review", "taskName": args.task_name,
            "provider": args.provider, "model": args.model,
            "verdict": verdict, **run.to_dict()})

    print(json.dumps({
        "ok": True,
        "taskName": args.task_name,
        "diffPath": args.diff,
        "reviewPath": str(log_path),
        "provider": args.provider,
        "model": args.model,
        "effort": args.effort,
        "verdict": verdict,
        "findingsCount": findings,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


def selftest() -> int:
    """Offline contract checks — no network, no pi invocation."""
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)
        print(f"  {'ok' if cond else 'FAIL'} — {name}")

    check("verdict first line",
          parse_verdict("APPROVED\n- [severity: minor] x") == "APPROVED")
    check("verdict with colon suffix",
          parse_verdict("REVISE: two issues") == "REVISE")
    check("prefix word not a verdict", parse_verdict("APPROVEDLY fine") == "UNKNOWN")
    check("off-contract text -> UNKNOWN", parse_verdict("The diff looks fine") == "UNKNOWN")
    check("empty -> UNKNOWN", parse_verdict("  \n\n") == "UNKNOWN")
    check("findings counted",
          count_findings("- [severity: blocking] a\n- [severity: minor] b\n- not one") == 2)
    check("effort mapping covers valid efforts",
          set(EFFORT_TO_THINKING) == set(VALID_EFFORTS))
    check("review tools read-only", set(REVIEW_TOOLS.split(",")) <= {"read", "grep", "find", "ls"})

    prompt = build_prompt("spec.md", "SPEC", "d.diff", "+changed", [("t.py", "TEST")], [])
    check("prompt leads with contract",
          prompt.startswith(DIFF_REVIEW_CONTRACT) and "+changed" in prompt
          and "TEST" in prompt)

    print(f"diff_review_pi selftest: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
