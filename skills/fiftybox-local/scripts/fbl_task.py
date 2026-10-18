#!/usr/bin/env python3
"""Mechanical half of the fiftybox-local loop.

The orchestrator (Claude/Codex) used to spend a model turn on every health
check, dry-run, wc, dispatch, poll, test run, tamper check and metrics row.
Each turn re-reads the whole conversation, so those turns were the real Claude
cost. This script does all of that in one call and prints a few KEY=value
lines. The orchestrator only writes Red tests and reviews one batch diff.

Subcommands: preflight, run, wait, diff, status, calibrate.
Standard library only (the NAS and Codex hosts run old Pythons).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

IMPL_AGENT = "pi"
IMPL_TIMEOUT = 1800
TASK_SPEC_MAX_LINES = 15
TASK_MAX_FILES = 2
INTENT_SUMMARY_MAX_LINES = 14
BATCH_MAX_TASKS = 5
STUDIO_SSH = "tanpapa@100.115.199.115"
KEY_FILE = Path("~/.config/opencode/macstudio-omlx.key").expanduser()
ORCHESTRATE = Path("~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py").expanduser()


@dataclasses.dataclass(frozen=True)
class Executor:
    name: str
    provider: str
    model: str
    base_url: str
    needs_key: bool
    design_max: int
    prompt_max: int


EXECUTORS = {
    "flash-next": Executor(
        "flash-next", "macstudio-qwen-flash-next", "Jundot--Qwen3.8-Flash-Next-oQ4e-mtp",
        "http://100.115.199.115:8000", True, design_max=70, prompt_max=140),
    # Benchmark-only lane: the skill's executor stays fixed on flash-next.
    "gemma4": Executor(
        "gemma4", "macstudio-gemma4", "mlx-community--gemma-4-26B-A4B-it-qat-4bit",
        "http://100.115.199.115:11235", False, design_max=60, prompt_max=120),
    # ioh PC lane (llama.cpp Strata, ctx 131072, no auth) — user-directed
    # fallback while the studio lane is down; same model family as flash-next.
    "iq3s": Executor(
        "iq3s", "ioh", "qwen3.8-flash-next-iq3_s",
        "http://100.126.254.22:8080", False, design_max=70, prompt_max=140),
}
DEFAULT_EXECUTOR = "flash-next"

HEAVY_DIRS = ("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".worktrees", ".git")
TEST_DIRS = ("tests", "test", "__tests__")
TEST_FILE_RE = re.compile(r"test_.*\.py$|.*_test\.(py|go)$|.*\.(test|spec)\.[cm]?[jt]sx?$")
STRIPPABLE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".java", ".rs",
                  ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".kt")
ALLOWED_SCRIPTS = {"LATIN", "HANGUL", "GREEK"}
SKIP_RES = [re.compile(p) for p in (
    r"pytest\.mark\.(skip|xfail)", r"pytest\.skip\(", r"\b(?:it|test|describe)\.(?:skip|only)\b",
    r"\.only\(", r"\bassert True\b", r"\bskipTest\(", r"unittest\.skip", r"\bt\.Skip\(",
    r"@Ignore\b", r"\bxit\(", r"\bxdescribe\(")]


# ---------- parsing ----------

def parse_task_range(spec: str) -> list[int]:
    ids: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"bad task range: {part!r}")
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        if hi < lo:
            raise ValueError(f"descending range: {part!r}")
        ids.extend(range(lo, hi + 1))
    if len(ids) > BATCH_MAX_TASKS:
        raise ValueError(f"batch has {len(ids)} tasks; max is {BATCH_MAX_TASKS}")
    return ids


def parse_exit_code(text: str) -> int | None:
    found = re.findall(r"EXIT_CODE=(\d+)", text)
    return int(found[-1]) if found else None


def parse_owned(spec: str) -> list[str]:
    m = re.search(r"Modify ONLY:?\**\s*(.*)", spec)
    if not m:
        return []
    rest = m.group(1).strip()
    if "," in rest:
        return [p.strip().strip("`").strip() for p in rest.split(",") if p.strip().strip("`")]
    ticked = re.findall(r"`([^`]+)`", rest)
    return ticked or ([rest] if rest else [])


def classify_failure(text: str, exit_code: int | None, over_budget: bool) -> str:
    if re.search(r"Connection refused|Failed to connect|ECONNREFUSED|502 Bad Gateway|"
                 r"unexpected EOF|connection (?:reset|closed)", text, re.I):
        return "server"
    if re.search(r"unknown model|model[_ ]not[_ ]found|(?:http|status|error)[^\n]{0,15}\b(?:404|410)\b",
                 text, re.I):
        return "model"
    if exit_code == 124:
        return "timeout"
    if re.search(r'finish_reason"?\s*:\s*"length"|stop_reason"?\s*:\s*"max_tokens"', text):
        return "too_long"
    if exit_code == 3:
        return "too_long" if over_budget else "no_changes"
    if exit_code == 1 and re.search(r"not in the agents list|unrecognized arguments", text):
        return "orchestrate"
    return "unknown"


# ---------- diff helpers ----------

def _line_kinds(diff_text: str):
    """Yield (line, kind) with kind in ctx/code/comment/blank for +/- lines."""
    in_doc = in_block = False
    for line in diff_text.splitlines():
        if line[:1] not in ("+", "-"):
            yield line, "ctx"
            continue
        body = line[1:].strip()
        if in_doc:
            if '"""' in body or "'''" in body:
                in_doc = False
            yield line, "comment"
        elif in_block:
            if "*/" in body:
                in_block = False
            yield line, "comment"
        elif body == "":
            yield line, "blank"
        elif body.startswith(('"""', "'''")):
            if body.count(body[:3]) < 2:
                in_doc = True
            yield line, "comment"
        elif body.startswith(("#", "//")):
            yield line, "comment"
        elif body.startswith("/*"):
            if "*/" not in body:
                in_block = True
            yield line, "comment"
        else:
            yield line, "code"


def strip_comment_lines(diff_text: str) -> str:
    return "\n".join(line for line, kind in _line_kinds(diff_text) if kind in ("ctx", "code"))


def comment_stats(diff_text: str) -> tuple[int, int]:
    total = comments = 0
    for line, kind in _line_kinds(diff_text):
        if line.startswith("+") and kind in ("code", "comment"):
            total += 1
            comments += kind == "comment"
    return total, comments


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    return any(p in TEST_DIRS for p in parts[:-1]) or bool(TEST_FILE_RE.match(parts[-1]))


def _is_noise_path(path: str) -> bool:
    parts = path.split("/")
    return any(p in HEAVY_DIRS for p in parts) or parts[-1].endswith(".pyc")


def _split_files(diff_text: str) -> list[tuple[str, list[str]]]:
    files: list[tuple[str, list[str]]] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)$", line)
            files.append((m.group(2) if m else line, []))
        elif files:
            files[-1][1].append(line)
    return files


def _file_body(block: list[str]) -> list[str]:
    body, in_hunk = [], False
    for line in block:
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk:
            body.append(line)
    return body


def _count_changes(body: list[str]) -> tuple[int, int]:
    return (sum(1 for l in body if l.startswith("+")), sum(1 for l in body if l.startswith("-")))


def render_diff(raw: str, max_lines: int = 300) -> str:
    out: list[str] = []
    for path, block in _split_files(raw):
        body = _file_body(block)
        added, removed = _count_changes(body)
        out.append(f"## {path} +{added} -{removed}")
        text = "\n".join(body)
        if path.endswith(STRIPPABLE_EXT):
            text = strip_comment_lines(text)
        out.extend(l for l in text.splitlines() if l.strip())
    if len(out) > max_lines:
        dropped = len(out) - max_lines
        out = out[:max_lines] + [f"... truncated {dropped} lines (read the file directly if needed)"]
    return "\n".join(out)


def added_text(raw: str) -> str:
    return "\n".join(l[1:] for l in raw.splitlines() if l.startswith("+") and not l.startswith("+++"))


def foreign_scripts(text: str) -> set[str]:
    found: set[str] = set()
    for ch in text:
        if ch.isascii() or not unicodedata.category(ch).startswith("L"):
            continue
        try:
            script = unicodedata.name(ch).split()[0]
        except ValueError:
            continue
        if script not in ALLOWED_SCRIPTS:
            found.add(script)
    return found


def find_skips(lines: list[str]) -> list[str]:
    return [l for l in lines if l.startswith("+") and any(r.search(l) for r in SKIP_RES)]


def scope_violations(changed: list[str], allowed: set[str]) -> list[str]:
    norm = {a[2:] if a.startswith("./") else a for a in allowed}
    return [c for c in changed
            if not is_test_path(c) and not _is_noise_path(c) and c not in norm]


def tampered_tests(staged: Path, worktree: Path) -> list[str]:
    bad = []
    for f in sorted(staged.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(staged)
        cur = worktree / rel
        if not cur.is_file() or cur.read_bytes() != f.read_bytes():
            bad.append(rel.as_posix())
    return bad


def budget_violations(design_lines: int, spec_lines: int, files: int, intent_lines: int,
                      ex: Executor) -> list[str]:
    out = []
    if design_lines > ex.design_max:
        out.append(f"design>{ex.design_max}")
    if spec_lines > TASK_SPEC_MAX_LINES:
        out.append(f"spec>{TASK_SPEC_MAX_LINES}")
    if files > TASK_MAX_FILES:
        out.append(f"files>{TASK_MAX_FILES}")
    if intent_lines > INTENT_SUMMARY_MAX_LINES:
        out.append(f"intent>{INTENT_SUMMARY_MAX_LINES}")
    return out


# ---------- metrics ----------

METRICS_HEADER = "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 |\n|---|---|---|---|---|---|\n"


def append_metrics(path: Path, task: str, spec: int, prompt: int, seconds: int, changed: int,
                   result: str) -> None:
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8") as f:
        if new:
            f.write(METRICS_HEADER)
        f.write(f"| {task} | {spec} | {prompt} | {seconds}s | {changed} | {result} |\n")


def parse_metrics(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] == "task" or all(re.fullmatch(r"-+", c) for c in cells):
            continue
        rows.append(dict(zip(("task", "spec", "prompt", "duration", "changed", "result"), cells)))
    return rows


def calibrate(rows: list[dict]) -> dict:
    ok = [r["result"].startswith("success") for r in rows]
    streak = 0
    for v in reversed(ok):
        if not v:
            break
        streak += 1
    last5 = ok[-5:]
    rate = sum(last5) / len(last5) if last5 else 1.0
    if len(rows) >= 5 and rate < 0.8:
        advice = "DOWN"
    elif streak >= 10:
        advice = "UP"
    else:
        advice = "KEEP"
    return {"n": len(rows), "streak": streak, "last5_rate": rate, "advice": advice}


# ---------- server ----------

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_key(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def check_health(base_url: str, key: str | None = None, timeout: float = 10) -> int:
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/models")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with _NO_PROXY.open(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0


def executor_health(ex: Executor) -> int:
    return check_health(ex.base_url, read_key(KEY_FILE) if ex.needs_key else None)


def warm_up(ex: Executor) -> int:
    body = json.dumps({"model": ex.model, "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 1}).encode()
    req = urllib.request.Request(ex.base_url + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    key = read_key(KEY_FILE) if ex.needs_key else None
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    for attempt in (1, 2):
        try:
            with _NO_PROXY.open(req, timeout=120) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code
        except (urllib.error.URLError, OSError):
            if attempt == 1:
                time.sleep(30)
    return 0


def probe_lanes() -> str:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", STUDIO_SSH,
           "source ~/.zprofile 2>/dev/null; lsof -nP -iTCP:8000 -iTCP:11234 -iTCP:11235 -sTCP:LISTEN"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return "ssh_failed"
    if out.returncode not in (0, 1):
        return "ssh_failed"
    ports = sorted(set(re.findall(r":(\d+) \(LISTEN\)", out.stdout)))
    return ",".join(ports) or "none"


# ---------- git snapshots ----------

def _git(worktree: Path, *args: str, env: dict | None = None) -> str:
    full_env = dict(os.environ, **(env or {}))
    res = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True,
                         env=full_env)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {res.stderr.strip()[:300]}")
    return res.stdout


def snapshot_tree(worktree: Path, index_path: Path) -> str:
    """Write the working tree to a git tree object via a private index (no commit)."""
    index_path = Path(index_path).resolve()
    index_path.unlink(missing_ok=True)
    env = {"GIT_INDEX_FILE": str(index_path)}
    excludes = [f":(exclude,glob)**/{d}/**" for d in HEAVY_DIRS if d != ".git"]
    excludes += [f":(exclude){d}" for d in HEAVY_DIRS if d != ".git"]
    _git(worktree, "add", "-A", "--", ".", *excludes, env=env)
    return _git(worktree, "write-tree", env=env).strip()


def diff_trees(worktree: Path, a: str, b: str, include_tests: bool = False) -> str:
    raw = _git(worktree, "diff", "--no-color", "-U0", a, b)
    kept = []
    for path, block in _split_files(raw):
        if _is_noise_path(path) or (not include_tests and is_test_path(path)):
            continue
        kept.append(f"diff --git a/{path} b/{path}")
        kept.extend(block)
    return "\n".join(kept) + ("\n" if kept else "")


# ---------- dispatch ----------

class OrchestrateDispatcher:
    """Calls orchestrate.py --phase implement with all four executor values."""

    def _cmd(self, task_text, artifact_dir, ex, extra):
        root = _git(Path(artifact_dir), "rev-parse", "--show-toplevel").strip()
        return ["python3", str(ORCHESTRATE), "--phase", "implement", "--task", task_text,
                "--cwd", root, "--artifact-dir", str(artifact_dir),
                "--implement-agent", IMPL_AGENT, "--provider", ex.provider, "--model", ex.model,
                "--implementation-timeout", str(IMPL_TIMEOUT), "--skip-verify", *extra]

    @staticmethod
    def _retry_args(retry_feedback):
        return ["--is-retry", "--feedback", retry_feedback] if retry_feedback else []

    def dry_run(self, task_text, artifact_dir, ex, *, retry_feedback=None) -> Path:
        cmd = self._cmd(task_text, artifact_dir, ex, ["--dry-run", *self._retry_args(retry_feedback)])
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError(f"dry-run failed: {(res.stdout + res.stderr)[-400:]}")
        name = "implement-prompt-retry.md" if retry_feedback else "implement-prompt.md"
        return Path(artifact_dir) / name

    def implement(self, task_text, artifact_dir, ex, out_path, *, retry_feedback=None) -> int:
        cmd = self._cmd(task_text, artifact_dir, ex, self._retry_args(retry_feedback))
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=IMPL_TIMEOUT + 120)
            code, text = res.returncode, res.stdout + res.stderr
        except subprocess.TimeoutExpired as exc:
            code = 124
            text = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        Path(out_path).write_text(f"{text}\nEXIT_CODE={code}\n", encoding="utf-8")
        return code


# ---------- runner ----------

@dataclasses.dataclass
class TaskResult:
    task: int
    verdict: str = "FAIL"  # CLEAN | FLAG | FAIL | STOP
    stop: str | None = None
    detail: str = ""
    klass: str = "-"
    exit_code: int | None = None
    seconds: int = 0
    prompt_lines: int = 0
    checks: dict = dataclasses.field(default_factory=dict)
    log_tail: str = ""


def format_result(r: TaskResult) -> str:
    if r.verdict == "STOP":
        return f"TASK={r.task} VERDICT=STOP STOP={r.stop} DETAIL={r.detail}".replace("\n", " ")
    parts = [f"TASK={r.task}", f"VERDICT={r.verdict}", f"EXIT={r.exit_code}", f"CLASS={r.klass}",
             f"SECONDS={r.seconds}", f"PROMPT={r.prompt_lines}"]
    parts += [f"{k}={v}" for k, v in r.checks.items()]
    return " ".join(parts)


def run_shell(cmd: str, cwd: Path, timeout: int = 600) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
                             timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "test command timed out"
    return res.returncode, (res.stdout + res.stderr)[-1500:]


def _tail(text: str, n: int = 15) -> str:
    return "\n".join(text.splitlines()[-n:])


class TaskRunner:
    FIXED_LINES = ("Run: {cmd}", "Keep code comments and docstrings minimal.",
                   "Write code and comments in English or Korean only.")

    def __init__(self, artifact_dir, executor: Executor, *, dispatcher=None, health=None,
                 test_command: str | None = None):
        self.a = Path(artifact_dir)
        self.ex = executor
        self.dispatcher = dispatcher or OrchestrateDispatcher()
        self.health = health or executor_health
        self.wt = Path(json.loads((self.a / "summary.json").read_text(encoding="utf-8"))["worktree"])
        self.dir = self.a / ".fbl"
        self.dir.mkdir(exist_ok=True)
        cfg_path = self.dir / "config.json"
        if test_command:
            cfg_path.write_text(json.dumps({"test_command": test_command}), encoding="utf-8")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        self.test_command = cfg.get("test_command")

    # state ---------------------------------------------------------
    def _state(self) -> dict:
        p = self.dir / "state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"tasks": {}, "pre": {}}

    def _save(self, state: dict) -> None:
        (self.dir / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def _checkpoint(self, retry: bool) -> None:
        cp, marker = self.dir / "checkpoint", self.dir / "reviewed"
        if cp.exists() and not (marker.exists() and not retry):
            return
        cp.write_text(snapshot_tree(self.wt, self.dir / "idx-checkpoint"), encoding="utf-8")
        marker.unlink(missing_ok=True)

    # public --------------------------------------------------------
    def run(self, task_ids: list[int], retry_feedback: str | None = None,
            emit: Callable[[TaskResult], None] | None = None) -> list[TaskResult]:
        results: list[TaskResult] = []
        if self.test_command is None:
            r = TaskResult(task_ids[0], "STOP", stop="NO_TEST_COMMAND", detail="pass --test-command once")
            return [r]
        self._checkpoint(retry=retry_feedback is not None)
        for tid in task_ids:
            r = self._run_one(tid, retry_feedback)
            results.append(r)
            if emit:
                emit(r)
            if r.verdict != "CLEAN":
                break
        return results

    # one task ------------------------------------------------------
    def _stop(self, tid: int, stop: str, detail: str = "") -> TaskResult:
        return TaskResult(tid, "STOP", stop=stop, detail=detail)

    def _run_one(self, tid: int, retry_feedback: str | None) -> TaskResult:
        state = self._state()
        attempts = state["tasks"].get(str(tid), {}).get("attempts", 0) if retry_feedback else 0
        if attempts >= 2:
            return self._stop(tid, "RETRY_BUDGET", "one automatic retry per task is used up")
        attempt = attempts + 1

        code = self.health(self.ex)
        if code != 200:
            return self._stop(tid, "PREFLIGHT", f"health HTTP {code}; see reference.md to start the server")

        spec_path = self.a / "tasks" / f"task-{tid}.md"
        if not spec_path.is_file():
            return self._stop(tid, "SPEC_MISSING", str(spec_path))
        spec = spec_path.read_text(encoding="utf-8")
        owned = parse_owned(spec)
        spec_lines = len(spec.splitlines())
        design = self.a / "design.md"
        intent = self.a / "intent-summary.md"
        over = budget_violations(
            len(design.read_text(encoding="utf-8").splitlines()) if design.exists() else 0,
            spec_lines, len(owned),
            len(intent.read_text(encoding="utf-8").splitlines()) if intent.exists() else 0, self.ex)
        if over:
            return self._stop(tid, "BUDGET", ",".join(over))

        staged = self.a / "tests" / f"task-{tid}"
        if not staged.is_dir() or not any(p.is_file() for p in staged.rglob("*")):
            return self._stop(tid, "NO_RED_TESTS", str(staged))
        shutil.copytree(staged, self.wt, dirs_exist_ok=True)
        if retry_feedback is None:
            rc, _ = run_shell(self.test_command, self.wt)
            if rc == 0:
                return self._stop(tid, "RED_ALREADY_PASSES", "rewrite the Red test")
            state["pre"][str(tid)] = snapshot_tree(self.wt, self.dir / "idx-pre")

        task_text = spec.rstrip("\n") + "\n" + "\n".join(self.FIXED_LINES).format(cmd=self.test_command)
        prompt = self.dispatcher.dry_run(task_text, self.a, self.ex, retry_feedback=retry_feedback)
        prompt_lines = len(Path(prompt).read_text(encoding="utf-8").splitlines())
        if prompt_lines > self.ex.prompt_max:
            return self._stop(tid, "GATE", f"prompt {prompt_lines}>{self.ex.prompt_max}")

        out = self.a / f"implement-task-{tid}{'r' if retry_feedback else ''}.out"
        t0 = time.time()
        exit_code = self.dispatcher.implement(task_text, self.a, self.ex, out,
                                              retry_feedback=retry_feedback)
        seconds = int(time.time() - t0)
        out_text = out.read_text(encoding="utf-8") if out.exists() else ""
        r = TaskResult(tid, exit_code=exit_code, seconds=seconds, prompt_lines=prompt_lines)
        row = f"Task {tid}"
        if exit_code != 0:
            r.klass = classify_failure(out_text, exit_code, over_budget=False)
            r.log_tail = _tail(out_text)
            result = "retry" if attempt == 1 else "failed"
            changed = 0
        else:
            result, changed = self._check(r, tid, staged, owned, state)
        append_metrics(self.a / "executor-metrics.md", row, spec_lines, prompt_lines, seconds, changed, result)
        state["tasks"][str(tid)] = {"verdict": r.verdict, "klass": r.klass, "attempts": attempt}
        state["last"] = tid
        self._save(state)
        return r

    def _check(self, r: TaskResult, tid: int, staged: Path, owned: list[str], state: dict):
        rc, test_out = run_shell(self.test_command, self.wt)
        post = snapshot_tree(self.wt, self.dir / "idx-post")
        pre = state["pre"].get(str(tid)) or post
        code_diff = diff_trees(self.wt, pre, post)
        all_diff = diff_trees(self.wt, pre, post, include_tests=True)
        changed = [p for p, _ in _split_files(code_diff)]
        tamper = tampered_tests(staged, self.wt)
        scope = scope_violations(changed, set(owned))
        skips = find_skips(all_diff.splitlines())
        scripts = foreign_scripts(added_text(code_diff))
        added, comments = comment_stats(code_diff)
        plus = sum(_count_changes(_file_body(b))[0] for _, b in _split_files(code_diff))
        minus = sum(_count_changes(_file_body(b))[1] for _, b in _split_files(code_diff))
        r.checks = {
            "TESTS": "pass" if rc == 0 else "fail",
            "TAMPER": ",".join(tamper) or "none",
            "SCOPE": ",".join(scope) or "none",
            "SKIPS": str(len(skips)) if skips else "none",
            "SCRIPT": ",".join(sorted(scripts)) or "none",
            "DIFF": f"+{plus}/-{minus}",
            "COMMENTS": f"{round(100 * comments / added) if added else 0}%",
        }
        if rc != 0:
            r.verdict, r.log_tail = "FAIL", _tail(test_out)
            return "failed", len(changed)
        flagged = any(r.checks[k] != "none" for k in ("TAMPER", "SCOPE", "SKIPS", "SCRIPT"))
        r.verdict = "FLAG" if flagged else "CLEAN"
        return ("flagged" if flagged else "success"), len(changed)


# ---------- reports ----------

def batch_diff(artifact_dir, max_lines: int = 300) -> str:
    a = Path(artifact_dir)
    wt = Path(json.loads((a / "summary.json").read_text(encoding="utf-8"))["worktree"])
    cp = (a / ".fbl" / "checkpoint").read_text(encoding="utf-8").strip()
    now = snapshot_tree(wt, a / ".fbl" / "idx-diff")
    (a / ".fbl" / "reviewed").write_text("1", encoding="utf-8")
    return render_diff(diff_trees(wt, cp, now), max_lines)


def status_report(artifact_dir) -> dict:
    a = Path(artifact_dir)
    ids = sorted(int(m.group(1)) for p in (a / "tasks").glob("task-*.md")
                 if (m := re.fullmatch(r"task-(\d+)\.md", p.name)))
    sp = a / ".fbl" / "state.json"
    state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"tasks": {}}
    done = [i for i in ids if state["tasks"].get(str(i), {}).get("verdict") == "CLEAN"]
    pending = [i for i in ids if i not in done]
    last = state.get("last")
    return {
        "DONE": ",".join(map(str, done)) or "-",
        "PENDING": ",".join(map(str, pending)) or "-",
        "LAST_VERDICT": state["tasks"].get(str(last), {}).get("verdict", "-") if last else "-",
    }


def wait_for_done(path: Path, max_seconds: float, poll: float = 5.0) -> dict:
    deadline = time.time() + max_seconds
    while True:
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        if "FBL_DONE" in text:
            return {"done": True, "tail": _tail(text)}
        if time.time() >= deadline:
            return {"done": False, "tail": _tail(text)}
        time.sleep(poll)


# ---------- CLI ----------

def _executor(name: str) -> Executor:
    ex = EXECUTORS[name]
    if name != DEFAULT_EXECUTOR:
        print(f"WARN=executor {name} is not the skill default ({DEFAULT_EXECUTOR}); "
              f"see reference.md before using it for real work", file=sys.stderr)
    return ex


def cmd_preflight(args) -> int:
    ex = _executor(args.executor)
    code = executor_health(ex)
    print(f"EXECUTOR={ex.name} HEALTH={code}")
    if code == 200:
        warmed = Path(args.artifact_dir, ".fbl", "warmed") if args.artifact_dir else None
        if warmed is None or not warmed.exists():
            wcode = warm_up(ex)
            print(f"WARM={'ok' if wcode == 200 else wcode}")
            if wcode == 200 and warmed is not None:
                warmed.parent.mkdir(exist_ok=True)
                warmed.write_text("1", encoding="utf-8")
            if wcode != 200:
                print("PREFLIGHT=down")
                return 1
        print("PREFLIGHT=ok")
        return 0
    lanes = probe_lanes()
    print(f"LANES={lanes}")
    if code == 401:
        print("PREFLIGHT=auth (key file and studio auth.api_key disagree; do not reissue the key)")
    else:
        print("PREFLIGHT=down (start procedure: reference.md)")
    return 1


def cmd_run(args) -> int:
    ex = _executor(args.executor)
    try:
        ids = parse_task_range(args.tasks)
    except ValueError as exc:
        print(f"STOP=BAD_TASKS DETAIL={exc}")
        return 2
    if args.detach:
        a = Path(args.artifact_dir)
        out = a / "fbl-run.out"
        cmd = [sys.executable, str(Path(__file__).resolve()), "run", "--artifact-dir", str(a),
               "--tasks", args.tasks, "--executor", args.executor, "--emit-done"]
        for flag, val in (("--test-command", args.test_command),
                          ("--retry-feedback-file", args.retry_feedback_file)):
            if val:
                cmd += [flag, val]
        with out.open("w", encoding="utf-8") as fh:
            subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        print(f"DETACHED OUT={out}")
        return 0
    feedback = Path(args.retry_feedback_file).read_text(encoding="utf-8") if args.retry_feedback_file else None
    runner = TaskRunner(args.artifact_dir, ex, test_command=args.test_command)
    shown: list[TaskResult] = []

    def emit(r: TaskResult) -> None:
        shown.append(r)
        print(format_result(r), flush=True)
        if r.log_tail:
            print("\n".join("  | " + l for l in r.log_tail.splitlines()), flush=True)

    results = runner.run(ids, retry_feedback=feedback, emit=emit)
    if not shown:
        for r in results:
            emit(r)
    clean = sum(r.verdict == "CLEAN" for r in results)
    print(f"BATCH tasks={args.tasks} clean={clean}/{len(ids)} "
          f"stopped_at={'none' if clean == len(ids) else results[-1].task}", flush=True)
    if args.emit_done:
        print("FBL_DONE", flush=True)
    return 0 if clean == len(ids) else 1


def cmd_wait(args) -> int:
    res = wait_for_done(Path(args.artifact_dir) / "fbl-run.out", args.max)
    print(res["tail"])
    print(f"WAIT={'done' if res['done'] else 'timeout'}")
    return 0 if res["done"] else 1


def cmd_diff(args) -> int:
    print(batch_diff(args.artifact_dir, args.max))
    return 0


def cmd_status(args) -> int:
    for k, v in status_report(args.artifact_dir).items():
        print(f"{k}={v}")
    return 0


def cmd_calibrate(args) -> int:
    rows: list[dict] = []
    root = Path(args.repo) / ".omx/artifacts/orchestrate"
    for f in sorted(root.glob("*/executor-metrics.md")):
        rows.extend(parse_metrics(f.read_text(encoding="utf-8")))
    info = calibrate(rows)
    print(f"N={info['n']} STREAK={info['streak']} LAST5={info['last5_rate']:.2f} ADVICE={info['advice']}")
    if info["advice"] != "KEEP":
        print("NOTE=show these rows to the user; change limits only after approval")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fbl_task.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, executor=True):
        if executor:
            sp.add_argument("--executor", choices=sorted(EXECUTORS), default=DEFAULT_EXECUTOR)

    sp = sub.add_parser("preflight")
    common(sp)
    sp.add_argument("--artifact-dir")
    sp.set_defaults(fn=cmd_preflight)

    sp = sub.add_parser("run")
    common(sp)
    sp.add_argument("--artifact-dir", required=True)
    sp.add_argument("--tasks", required=True)
    sp.add_argument("--test-command")
    sp.add_argument("--retry-feedback-file")
    sp.add_argument("--detach", action="store_true")
    sp.add_argument("--emit-done", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("wait")
    sp.add_argument("--artifact-dir", required=True)
    sp.add_argument("--max", type=float, default=540)
    sp.set_defaults(fn=cmd_wait)

    sp = sub.add_parser("diff")
    sp.add_argument("--artifact-dir", required=True)
    sp.add_argument("--max", type=int, default=300)
    sp.set_defaults(fn=cmd_diff)

    sp = sub.add_parser("status")
    sp.add_argument("--artifact-dir", required=True)
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("calibrate")
    sp.add_argument("--repo", default=os.getcwd())
    sp.set_defaults(fn=cmd_calibrate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
