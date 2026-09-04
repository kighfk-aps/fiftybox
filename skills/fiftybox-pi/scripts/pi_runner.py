#!/usr/bin/env python3
"""Structured runner for headless `pi --mode json` child processes.

Implements the exit-judgment contract discovered in S0
(references/failure-classification.md):

- pi exits 0 even when the model errors — classification MUST parse the
  JSONL stream, never trust the process exit code alone.
- success := agent_settled present AND zero stopReason:"error" messages AND
  non-empty final text.
- The runner always enforces its own wall-clock timeout (pi's internal retry
  policy can stall one call for minutes) and SIGKILLs on overrun.

Self-test: ``python3 pi_runner.py --selftest`` (offline, fixture streams).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# --- scope classification (references/failure-classification.md §2) -----------

SCOPE_ACCOUNT = "account"    # close lane, never swap models, stop batch
SCOPE_MODEL = "model"        # swap within lane per fallback order
SCOPE_TASK = "task"          # task-local retry budget

CLASSIFICATION_PATTERNS: list[tuple[str, str]] = [
    # (errorClass, lowercase substring patterns)
    ("auth", ["401", "403", "invalid api key", "unauthorized",
              "authentication", "410 status code"]),
    ("window", ["context length", "maximum context", "too many tokens",
                "prompt is too long", "window_exhausted"]),
    ("credit", ["402", "insufficient", "quota", "credit", "billing"]),
    ("model_busy", ["429", "rate limit", "busy", "overloaded"]),
    ("model", ["does not exist", "not found", "no endpoints", "model_code",
               "modelcode"]),
]

CLASS_TO_SCOPE: dict[str, str] = {
    "auth": SCOPE_ACCOUNT,
    "window": SCOPE_ACCOUNT,
    "credit": SCOPE_ACCOUNT,
    "model": SCOPE_MODEL,
    "model_busy": SCOPE_MODEL,
    "timeout": SCOPE_TASK,
    "no_changes": SCOPE_TASK,
    "unknown": SCOPE_TASK,
}

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2
EXIT_ARGS = 3

PI = "pi"


def classify_error(message: str) -> str:
    """Map an errorMessage payload to an errorClass via pattern table."""
    text = (message or "").lower()
    for error_class, patterns in CLASSIFICATION_PATTERNS:
        if any(p in text for p in patterns):
            return error_class
    return "unknown"


def scope_of(error_class: str) -> str:
    return CLASS_TO_SCOPE.get(error_class, SCOPE_TASK)


# --- JSONL stream parsing ------------------------------------------------------

@dataclass
class RunResult:
    ok: bool = False
    settled: bool = False
    timed_out: bool = False
    exit_code: int | None = None
    final_text: str = ""
    errors: list[str] = field(default_factory=list)
    error_classes: list[str] = field(default_factory=list)
    tool_calls: int = 0
    tool_execs: int = 0
    retry_loops: int = 0
    usage: dict = field(default_factory=dict)
    stderr_tail: str = ""
    duration_s: float = 0.0
    provider: str = ""
    model: str = ""

    @property
    def last_error_class(self) -> str:
        return self.error_classes[-1] if self.error_classes else (
            "timeout" if self.timed_out else "unknown")

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "settled": self.settled,
            "timedOut": self.timed_out, "exitCode": self.exit_code,
            "finalText": self.final_text[:400], "errors": self.errors[-3:],
            "errorClasses": self.error_classes[-3:],
            "lastErrorClass": self.last_error_class,
            "scope": scope_of(self.last_error_class),
            "toolCalls": self.tool_calls, "toolExecs": self.tool_execs,
            "retryLoops": self.retry_loops, "usage": self.usage,
            "stderrTail": self.stderr_tail[-400:],
            "durationS": round(self.duration_s, 1),
            "provider": self.provider, "model": self.model,
        }


def parse_stream(lines: list[str]) -> dict:
    """Reduce a captured --mode json stdout into runner counters.

    Pure function over text so tests can feed fixture streams.
    """
    out = {"errors": [], "final_text": "", "tool_calls": 0,
           "tool_execs": 0, "retry_loops": 0, "settled": False,
           "usage": {}}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # pi may interleave progress noise; contract lives in JSON
        etype = event.get("type")
        if etype == "message_end":
            message = event.get("message", {})
            if message.get("role") != "assistant":
                continue
            stop = message.get("stopReason")
            if stop == "error":
                out["errors"].append(message.get("errorMessage") or "unknown error")
            elif stop == "stop":
                texts = [c.get("text", "") for c in message.get("content", [])
                         if isinstance(c, dict) and c.get("type") == "text"]
                joined = "".join(texts).strip()
                if joined:
                    out["final_text"] = joined
            for block in message.get("content", []):
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    out["tool_calls"] += 1
            usage = message.get("usage")
            if isinstance(usage, dict) and usage.get("totalTokens"):
                out["usage"] = usage
        elif etype == "tool_execution_end":
            out["tool_execs"] += 1
        elif etype == "auto_retry_start":
            out["retry_loops"] += 1
        elif etype == "agent_settled":
            out["settled"] = True
    return out


def build_cmd(provider: str, model: str, *, tools: str | None = None,
              system_prompt: str | None = None,
              task_arg: str | None = None,
              extra_args: list[str] | None = None) -> list[str]:
    """The headless invocation. Mirrors orchestrate.py BUILTIN_AGENTS["pi"]
    plus --mode json (structured events instead of log scraping).

    Long payloads must NOT go through argv (ARG_MAX, provider quirks) —
    pass them via run_pi(stdin_prompt=...); keep --append-system-prompt short.
    """
    cmd = [PI, "--mode", "json", "-p", "--no-session", "--no-context-files"]
    if provider:
        cmd += ["--provider", provider]
    if model:
        cmd += ["--model", model]
    if tools:
        cmd += ["--tools", tools]
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]
    if extra_args:
        cmd += extra_args
    if task_arg:
        cmd.append(task_arg)
    return cmd


def run_pi(task: str, provider: str, model: str, *, tools: str | None = None,
           system_prompt: str | None = None, stdin_prompt: str | None = None,
           timeout: float = 900.0, cwd: str | None = None,
           extra_args: list[str] | None = None) -> RunResult:
    """Run one headless pi call and judge it by the stream contract.

    stdin_prompt: large payloads (diff review) go through stdin instead of
    argv to stay under ARG_MAX and provider system-prompt quirks.
    """
    cmd = build_cmd(provider, model, tools=tools, system_prompt=system_prompt,
                    task_arg=None if stdin_prompt is not None else task,
                    extra_args=extra_args)
    result = RunResult(provider=provider, model=model)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, input=stdin_prompt if stdin_prompt is not None else None,
            capture_output=True, text=True, timeout=timeout, cwd=cwd)
        result.exit_code = proc.returncode
        parsed = parse_stream(proc.stdout.splitlines())
        result.stderr_tail = (proc.stderr or "")[-400:]
    except subprocess.TimeoutExpired as exc:
        result.timed_out = True
        result.exit_code = None
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        parsed = parse_stream(stdout.splitlines() if stdout else [])
        result.stderr_tail = ((exc.stderr or ""))
        if isinstance(result.stderr_tail, bytes):
            result.stderr_tail = result.stderr_tail.decode("utf-8", errors="replace")
        result.stderr_tail = result.stderr_tail[-400:]
    result.duration_s = time.monotonic() - started
    result.errors = parsed["errors"]
    result.error_classes = [classify_error(e) for e in result.errors]
    result.final_text = parsed["final_text"]
    result.tool_calls = parsed["tool_calls"]
    result.tool_execs = parsed["tool_execs"]
    result.retry_loops = parsed["retry_loops"]
    result.settled = parsed["settled"]
    result.usage = parsed["usage"]
    result.ok = (result.settled and not result.errors and not result.timed_out
                 and bool(result.final_text.strip()))
    return result


# --- audit trail (model-choice.json style) -------------------------------------

def append_audit(audit_path: str | Path, record: dict) -> None:
    """Append one run record to a JSON-lines audit file."""
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
             **record}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --- fixtures for the offline self-test -----------------------------------------

FIXTURE_SUCCESS = "\n".join([
    '{"type":"session","version":3,"id":"t"}',
    '{"type":"agent_start"}',
    '{"type":"turn_start"}',
    '{"type":"message_end","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
    '{"type":"message_end","message":{"role":"assistant","content":[{"type":"toolCall","id":"c1","name":"read","arguments":{"path":"a.md"}}],"stopReason":"toolUse"}}',
    '{"type":"tool_execution_start","toolCallId":"c1","toolName":"read"}',
    '{"type":"tool_execution_end","toolCallId":"c1","toolName":"read"}',
    '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"stopReason":"stop","usage":{"totalTokens":42}}}',
    '{"type":"agent_end"}',
    '{"type":"agent_settled"}',
])

FIXTURE_MODEL_ERROR = "\n".join([
    '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"400: {\\"code\\":\\"1214\\",\\"message\\":\\"modelCode: does not exist\\"}"}}',
    '{"type":"agent_settled"}',
])

FIXTURE_RATE_LIMIT = "\n".join([
    '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"429: {\\"error\\":{\\"message\\":\\"Rate limit exceeded\\"}"}}',
    '{"type":"auto_retry_start"}',
    '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"429: {\\"error\\":{\\"message\\":\\"Rate limit exceeded\\"}"}}',
])

FIXTURE_AUTH = "\n".join([
    '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"410 status code (no body)"}}',
    '{"type":"agent_settled"}',
])


def selftest() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)
        print(f"  {'ok' if cond else 'FAIL'} — {name}")

    good = parse_stream(FIXTURE_SUCCESS.splitlines())
    check("success: settled", good["settled"] is True)
    check("success: final text", good["final_text"] == "done")
    check("success: toolCall counted", good["tool_calls"] == 1)
    check("success: toolExecution counted", good["tool_execs"] == 1)
    check("success: usage captured", good["usage"].get("totalTokens") == 42)

    model_err = parse_stream(FIXTURE_MODEL_ERROR.splitlines())
    check("model error captured", len(model_err["errors"]) == 1)
    check("model error class", classify_error(model_err["errors"][0]) == "model")
    check("model error scope", scope_of("model") == SCOPE_MODEL)

    rl = parse_stream(FIXTURE_RATE_LIMIT.splitlines())
    check("rate limit: retry loop counted", rl["retry_loops"] == 1)
    check("rate limit: class model_busy",
          classify_error(rl["errors"][0]) == "model_busy")
    check("rate limit: scope model", scope_of("model_busy") == SCOPE_MODEL)

    auth = parse_stream(FIXTURE_AUTH.splitlines())
    check("410 no body -> auth", classify_error(auth["errors"][0]) == "auth")
    check("auth scope = account", scope_of("auth") == SCOPE_ACCOUNT)

    window = classify_error("prompt is too long: 200000 tokens > 131072")
    check("context overflow -> window", window == "window"
          and scope_of(window) == SCOPE_ACCOUNT)

    # success judgment requires settled + no errors + non-empty final text
    result = RunResult(settled=True, errors=[], final_text="x")
    result.error_classes = []
    result.ok = (result.settled and not result.errors and not result.timed_out
                 and bool(result.final_text.strip()))
    check("ok requires all three conditions", result.ok is True)
    result.errors = ["boom"]
    result.ok = (result.settled and not result.errors and not result.timed_out
                 and bool(result.final_text.strip()))
    check("errors block ok", result.ok is False)

    cmd = build_cmd("nvidia-nim", "openai/gpt-oss-120b", tools="read",
                    system_prompt="be brief", task_arg="do it")
    check("cmd mirrors BUILTIN_AGENTS pi + --mode json",
          cmd[:9] == [PI, "--mode", "json", "-p", "--no-session",
                      "--no-context-files", "--provider", "nvidia-nim",
                      "--model"] and "--tools" in cmd
          and "openai/gpt-oss-120b" in cmd)

    print(f"pi_runner selftest: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a headless pi child and judge it by the JSONL contract")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--task", help="task text (or --task-file)")
    parser.add_argument("--task-file", help="read task text from file")
    parser.add_argument("--stdin-prompt-file",
                        help="large prompt delivered via stdin instead of argv")
    parser.add_argument("--tools", help="comma-separated tool whitelist")
    parser.add_argument("--system-prompt", help="short system prompt text")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--cwd", help="working directory for the child")
    parser.add_argument("--audit", help="append the run record to this JSONL file")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.provider or not args.model:
        parser.error("--provider and --model are required")

    task = args.task or ""
    if args.task_file:
        task = Path(args.task_file).read_text(encoding="utf-8")
    stdin_prompt = None
    if args.stdin_prompt_file:
        stdin_prompt = Path(args.stdin_prompt_file).read_text(encoding="utf-8")
    if not task and not stdin_prompt:
        parser.error("one of --task / --task-file / --stdin-prompt-file is required")

    result = run_pi(task, args.provider, args.model,
                    tools=args.tools, system_prompt=args.system_prompt,
                    stdin_prompt=stdin_prompt, timeout=args.timeout,
                    cwd=args.cwd)
    if args.audit:
        append_audit(args.audit, result.to_dict())
    print(json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")))
    if result.ok:
        return EXIT_OK
    return EXIT_TIMEOUT if result.timed_out else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
