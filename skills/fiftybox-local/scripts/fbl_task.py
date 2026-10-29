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
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
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
    host: str = ""
    params_b: float = 0.0


STUDIO_URL = "http://100.115.199.115"
IOH_URL = "http://100.76.6.16"

# Candidate table: the only models the skill may use. Each PC contributes at most
# one served candidate per run (live_lanes): the bigger params_b wins and table
# order breaks ties. Flash-Next family keeps the budget earned over 40 clean
# tasks (70/140); every other model starts at the Gemma4 values (60/120).
# ioh lists the R9700 ports only (8080 Strata, 8083, 8084); 8081 is the RTX 5060
# Ti that serves the RAG, so it is never a candidate.
EXECUTORS = {
    "flash-next": Executor(
        "flash-next", "macstudio-qwen-flash-next", "Jundot--Qwen3.8-Flash-Next-oQ4e-mtp",
        f"{STUDIO_URL}:8000", True, design_max=70, prompt_max=140,
        host="studio", params_b=125.0),  # model card: 125B parameters, 6B active
    "qwen27b-mlx4": Executor(
        "qwen27b-mlx4", "macstudio-qwen-flash-next", "lmstudio-community--Qwen3.8-27B-MLX-4bit",
        f"{STUDIO_URL}:8000", True, design_max=60, prompt_max=120, host="studio", params_b=27.0),
    "qwen27b-8bit": Executor(
        "qwen27b-8bit", "macstudio-qwen38-27b", "qwen38-27b-8bit",
        f"{STUDIO_URL}:11234", False, design_max=60, prompt_max=120, host="studio", params_b=27.0),
    "gemma4": Executor(
        "gemma4", "macstudio-gemma4", "mlx-community--gemma-4-26B-A4B-it-qat-4bit",
        f"{STUDIO_URL}:11235", False, design_max=60, prompt_max=120, host="studio", params_b=26.0),
    "gpt-oss-20b": Executor(
        "gpt-oss-20b", "macstudio-darkbloom", "gpt-oss-20b",
        f"{STUDIO_URL}:8001", False, design_max=60, prompt_max=120, host="studio", params_b=20.0),
    "qwen35b-a3b": Executor(
        "qwen35b-a3b", "macstudio-darkbloom", "qwen3.5-35b-a3b",
        f"{STUDIO_URL}:8001", False, design_max=60, prompt_max=120, host="studio", params_b=35.0),
    # ioh PC (llama.cpp Strata, ctx 262144, no auth): same model as flash-next, lower quant.
    "iq3s": Executor(
        "iq3s", "ioh", "qwen3.8-flash-next-iq3_s",
        f"{IOH_URL}:8080", False, design_max=70, prompt_max=140, host="ioh", params_b=125.0),
    "gemma31b": Executor(
        "gemma31b", "ioh-gemma31b", "gemma-4-31b-it",
        f"{IOH_URL}:8083", False, design_max=60, prompt_max=120, host="ioh", params_b=31.0),
    "qwen27b": Executor(
        "qwen27b", "ioh-qwen27b", "qwen3.8-27b",
        f"{IOH_URL}:8084", False, design_max=60, prompt_max=120, host="ioh", params_b=27.0),
}
DEFAULT_EXECUTOR = "flash-next"
HOST_ORDER = ("studio", "ioh")  # the studio is preferred when both PCs are idle
LANE_SYNC_DIRS = ("node_modules", ".venv", "venv")
PI_MODELS_PATH = Path("~/.pi/agent/models.json").expanduser()
CONFIG_PATH = Path("~/.claude/fiftybox-config.json").expanduser()

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


# ---------- candidates ----------

def load_json(path: Path) -> dict | None:
    """Parsed JSON object, or None when the file is missing, unreadable or broken."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def eligible_candidates(registry: dict | None, config: dict | None) -> tuple[list[str], dict[str, str]]:
    """Candidates registered in Pi and not switched off in fiftybox-config.

    Returns (names in table order, {skipped name: "not-in-pi" | "off-in-config"}).
    ``None`` for either source means unreadable: that check is skipped. A missing
    config entry counts as on; ``providers.pi.enabled == false`` turns all off."""
    pi_cfg = ((config or {}).get("providers") or {}).get("pi") or {}
    names: list[str] = []
    skipped: dict[str, str] = {}
    for name, ex in EXECUTORS.items():
        if registry is not None:
            models = ((registry.get("providers") or {}).get(ex.provider) or {}).get("models") or []
            if ex.model not in {m.get("id") for m in models if isinstance(m, dict)}:
                skipped[name] = "not-in-pi"
                continue
        backend = (pi_cfg.get("backends") or {}).get(ex.provider) or {}
        if pi_cfg.get("enabled") is False or (backend.get("models") or {}).get(ex.model) is False:
            skipped[name] = "off-in-config"
            continue
        names.append(name)
    return names, skipped


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


def parse_depends(spec: str, tid: int, batch: list[int]) -> set[int]:
    """Depends: none → independent; no Depends: line → all earlier batch tasks."""
    m = re.search(r"^\**Depends:?\**\s*(.*)$", spec, re.M)
    if not m:
        return {i for i in batch if i < tid}
    value = m.group(1).strip()
    if value.lower() == "none":
        return set()
    return {int(x) for x in re.findall(r"\d+", value)}


def classify_failure(text: str, exit_code: int | None, over_budget: bool) -> str:
    if re.search(r"LANE_HEALTH_LOST|Connection refused|Failed to connect|ECONNREFUSED|502 Bad Gateway|"
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
METRICS_HEADER_LANE = "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 | lane |\n|---|---|---|---|---|---|---|\n"


def append_metrics(path: Path, task: str, spec: int, prompt: int, seconds: int, changed: int,
                   result: str, lane: str | None = None) -> None:
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8") as f:
        if new:
            f.write(METRICS_HEADER if lane is None else METRICS_HEADER_LANE)
        row = f"| {task} | {spec} | {prompt} | {seconds}s | {changed} | {result} |"
        if lane is not None:
            row += f" {lane} |"
        f.write(row + "\n")


def parse_metrics(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] == "task" or all(re.fullmatch(r"-+", c) for c in cells):
            continue
        row = dict(zip(("task", "spec", "prompt", "duration", "changed", "result", "lane"), cells))
        row.setdefault("lane", "flash-next")  # rows predating the lane column
        rows.append(row)
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


def calibrate_by_lane(rows: list[dict]) -> dict[str, dict]:
    """calibrate() per lane; moved rows are infrastructure, not model failures."""
    by_lane: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("result", "").startswith("moved"):
            continue
        by_lane.setdefault(r.get("lane", "flash-next"), []).append(r)
    return {lane: calibrate(rs) for lane, rs in sorted(by_lane.items())}


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


def fetch_models(base_url: str, key: str | None = None, timeout: float = 10) -> list[str]:
    """Model ids a server lists at /v1/models; [] on any HTTP, network or JSON failure."""
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/models")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with _NO_PROXY.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data")
    except urllib.error.HTTPError as exc:
        exc.close()
        return []
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return []
    return [m["id"] for m in data or [] if isinstance(m, dict) and isinstance(m.get("id"), str)]


def executor_health(ex: Executor) -> int:
    return check_health(ex.base_url, read_key(KEY_FILE) if ex.needs_key else None)


def executor_models(ex: Executor) -> list[str]:
    return fetch_models(ex.base_url, read_key(KEY_FILE) if ex.needs_key else None)


def executor_serving(ex: Executor) -> int:
    """executor_health, but a Studio candidate whose model id is not listed counts as down.

    The Studio's oMLX swaps models on one port, so HTTP 200 alone proves nothing there.
    An ioh port serves exactly one model, so 200 is enough."""
    code = executor_health(ex)
    if code == 200 and ex.host == "studio" and ex.model not in executor_models(ex):
        return 0
    return code


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
           "source ~/.zprofile 2>/dev/null; lsof -nP -iTCP:8000 -iTCP:8001 -iTCP:11234 -iTCP:11235 -sTCP:LISTEN"]
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


# ---------- pool helpers ----------

def task_paths(spec: str, staged: Path) -> set[str]:
    """Files a task owns: Modify ONLY paths plus its staged Red test files."""
    paths = {p[2:] if p.startswith("./") else p for p in parse_owned(spec)}
    if staged.is_dir():
        for f in staged.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                paths.add(f.relative_to(staged).as_posix())
    return paths


def pick_task(queue_: list[int], deps: dict[int, set[int]], done: set[int], busy: set[str],
              paths: dict[int, set[str]]) -> int | None:
    """First queued task whose deps are CLEAN and whose paths don't overlap busy."""
    for tid in queue_:
        if not deps.get(tid, set()) <= done:
            continue
        if paths.get(tid, set()) & busy:
            continue
        return tid
    return None


def live_lanes(names: list[str], health: Callable[[Executor], int]) -> list[str]:
    """One lane per PC: among the names whose health is 200, the bigger params_b wins.

    Ties fall back to table order; the result lists the studio first (HOST_ORDER)."""
    unknown = [n for n in names if n not in EXECUTORS]
    if unknown:
        raise ValueError(f"unknown lane: {unknown[0]}")
    best: dict[str, str] = {}
    for n, ex in EXECUTORS.items():  # table order breaks params_b ties
        if n in names and health(ex) == 200:
            cur = best.get(ex.host)
            if cur is None or ex.params_b > EXECUTORS[cur].params_b:
                best[ex.host] = n
    return sorted(best.values(), key=lambda n: HOST_ORDER.index(EXECUTORS[n].host))


def create_lane_worktree(main_wt: Path, path: Path) -> Path:
    """Make (or reuse) a detached worktree and share heavy dependency dirs."""
    main_wt, path = Path(main_wt).resolve(), Path(path)
    listing = _git(main_wt, "worktree", "list", "--porcelain")
    known = {ln.split(" ", 1)[1] for ln in listing.splitlines() if ln.startswith("worktree ")}
    if str(path.resolve()) not in known:
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(main_wt, "worktree", "add", "--detach", str(path), "HEAD")
    for d in LANE_SYNC_DIRS:
        src, dst = main_wt / d, path / d
        if (src.is_dir() or src.is_symlink()) and not dst.exists():
            dst.symlink_to(src)
    return path


def remove_lane_worktree(main_wt: Path, path: Path) -> bool:
    try:
        _git(Path(main_wt), "worktree", "remove", "--force", str(path))
        _git(Path(main_wt), "worktree", "prune")
        return True
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return False


def sync_lane(lane_wt: Path, main_wt: Path, index_path: Path) -> str:
    """Reset the lane worktree to the main worktree's current (uncommitted) state."""
    tree = snapshot_tree(Path(main_wt), index_path)
    _git(lane_wt, "read-tree", "-u", "--reset", tree)
    _git(lane_wt, "clean", "-fdq", *[f"-e{d}" for d in LANE_SYNC_DIRS])
    return tree


def overlay_paths(wt: Path, tree: str, paths: set[str]) -> list[str]:
    """Restore the owned files recorded in a tree; silently skip missing ones."""
    done: list[str] = []
    for p in sorted(paths):
        probe = subprocess.run(["git", "-C", str(wt), "cat-file", "-e", f"{tree}:{p}"],
                               capture_output=True)
        if probe.returncode == 0:
            _git(wt, "checkout", tree, "--", p)
            done.append(p)
    return done


def merge_paths(src_wt: Path, dst_wt: Path, paths: set[str]) -> list[str]:
    """Copy src files into dst; a path gone from src is deleted from dst."""
    touched: list[str] = []
    for p in sorted(paths):
        src, dst = Path(src_wt) / p, Path(dst_wt) / p
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            touched.append(p)
        elif dst.exists() or dst.is_symlink():
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
            touched.append(p)
    return touched


def make_lane_dir(a: Path, lane: str, lane_wt: Path) -> Path:
    """Per-lane artifact dir so orchestrate.py --phase implement sees one worktree."""
    a = Path(a)
    d = a / "lanes" / lane
    d.mkdir(parents=True, exist_ok=True)
    summary: dict = {"worktree": str(lane_wt),
                     "phases": {"setup": {"status": "success"}},
                     "files": {}}
    try:
        desc = json.loads((a / "summary.json").read_text(encoding="utf-8")).get("taskDescription")
        if desc is not None:
            summary["taskDescription"] = desc
    except (OSError, ValueError):
        pass
    (d / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    for name in ("design.md", "intent-summary.md"):
        src = a / name
        if src.exists():
            shutil.copy2(src, d / name)
    return d


# ---------- dispatch ----------

class OrchestrateDispatcher:
    """Calls orchestrate.py --phase implement with all four executor values.

    With ``health`` set, implement() also runs a lane watchdog: the child is
    started in its own process group and lane health is polled every
    ``interval`` seconds; ``misses`` consecutive non-200 checks kill the child
    (LANE_HEALTH_LOST, exit code 1) so a silently-dead server is classified
    ``server`` instead of burning the 1800s timeout.
    """

    def __init__(self, health: Callable[[], int] | None = None, interval: float = 60,
                 misses: int = 3):
        self.health = health
        self.interval = interval
        self.misses = misses

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
        if self.health is None:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=IMPL_TIMEOUT + 120)
                code, text = res.returncode, res.stdout + res.stderr
            except subprocess.TimeoutExpired as exc:
                code = 124
                text = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            Path(out_path).write_text(f"{text}\nEXIT_CODE={code}\n", encoding="utf-8")
            return code
        return self._implement_watched(cmd, Path(out_path))

    @staticmethod
    def _kill_group(proc) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError:
            try:
                proc.terminate()
            except OSError:
                pass

    def _implement_watched(self, cmd, out_path: Path) -> int:
        deadline = time.time() + IMPL_TIMEOUT + 120
        code: int | None = None
        trailer = ""
        with out_path.open("w", encoding="utf-8") as fh:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            missed = 0
            next_check = time.time() + self.interval
            while code is None:
                try:
                    proc.wait(timeout=1.0)
                    code = proc.returncode
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.time()
                if now >= deadline:
                    self._kill_group(proc)
                    proc.wait()
                    code = 124
                    break
                if now >= next_check:
                    if self.health() == 200:
                        missed = 0
                    else:
                        missed += 1
                        if missed >= self.misses:
                            self._kill_group(proc)
                            proc.wait()
                            code = 1
                            trailer = "LANE_HEALTH_LOST\n"
                            break
                    next_check = now + self.interval
        text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        out_path.write_text(f"{text}{trailer}EXIT_CODE={code}\n", encoding="utf-8")
        return code


# ---------- runner ----------

_STATE_LOCK = threading.Lock()


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
    lane: str | None = None
    moved: str | None = None


def format_result(r: TaskResult) -> str:
    if r.verdict == "STOP":
        base = f"TASK={r.task} VERDICT=STOP STOP={r.stop} DETAIL={r.detail}".replace("\n", " ")
    else:
        parts = [f"TASK={r.task}", f"VERDICT={r.verdict}", f"EXIT={r.exit_code}", f"CLASS={r.klass}",
                 f"SECONDS={r.seconds}", f"PROMPT={r.prompt_lines}"]
        parts += [f"{k}={v}" for k, v in r.checks.items()]
        base = " ".join(parts)
    if r.lane is not None:
        base += f" LANE={r.lane}"
    if r.moved is not None:
        base += f" MOVED={r.moved}"
    return base


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
                 test_command: str | None = None, worktree=None, dispatch_dir=None,
                 lane: str | None = None, count_server_attempts: bool = True):
        self.a = Path(artifact_dir)
        self.ex = executor
        self.dispatcher = dispatcher or OrchestrateDispatcher()
        self.health = health or executor_health
        if worktree is not None:
            self.wt = Path(worktree)
        else:
            self.wt = Path(json.loads((self.a / "summary.json").read_text(encoding="utf-8"))["worktree"])
        # dispatch_dir: per-lane artifact dir in pool mode; fbl state stays in self.a
        self.dd = Path(dispatch_dir) if dispatch_dir is not None else self.a
        self.lane = lane
        self.tag = f"-{lane}" if lane else ""
        self.count_server_attempts = count_server_attempts
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
        return TaskResult(tid, "STOP", stop=stop, detail=detail, lane=self.lane)

    def _save_task(self, tid: int, record: dict | None, pre: str | None, post: str | None) -> None:
        """Merge one task's record into state.json under the lock (thread-safe)."""
        with _STATE_LOCK:
            state = self._state()
            if record is not None:
                state.setdefault("tasks", {})[str(tid)] = record
                state["last"] = tid
            if pre is not None:
                state.setdefault("pre", {})[str(tid)] = pre
            if post is not None:
                state.setdefault("post", {})[str(tid)] = post
            self._save(state)

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
        pre: str | None = None
        shutil.copytree(staged, self.wt, dirs_exist_ok=True)
        if retry_feedback is None:
            rc, _ = run_shell(self.test_command, self.wt)
            if rc == 0:
                return self._stop(tid, "RED_ALREADY_PASSES", "rewrite the Red test")
            pre = snapshot_tree(self.wt, self.dir / f"idx-pre{self.tag}")
            state["pre"][str(tid)] = pre

        task_text = spec.rstrip("\n") + "\n" + "\n".join(self.FIXED_LINES).format(cmd=self.test_command)
        prompt = self.dispatcher.dry_run(task_text, self.dd, self.ex, retry_feedback=retry_feedback)
        prompt_lines = len(Path(prompt).read_text(encoding="utf-8").splitlines())
        if prompt_lines > self.ex.prompt_max:
            return self._stop(tid, "GATE", f"prompt {prompt_lines}>{self.ex.prompt_max}")

        out = self.dd / f"implement-task-{tid}{'r' if retry_feedback else ''}{self.tag}.out"
        t0 = time.time()
        exit_code = self.dispatcher.implement(task_text, self.dd, self.ex, out,
                                              retry_feedback=retry_feedback)
        seconds = int(time.time() - t0)
        out_text = out.read_text(encoding="utf-8") if out.exists() else ""
        r = TaskResult(tid, exit_code=exit_code, seconds=seconds, prompt_lines=prompt_lines,
                       lane=self.lane)
        row = f"Task {tid}"
        post: str | None = None
        if exit_code != 0:
            r.klass = classify_failure(out_text, exit_code, over_budget=False)
            if r.klass == "model" and self.health(self.ex) != 200:
                r.klass = "server"  # the lane stopped serving this model: infrastructure, not a model failure
            r.log_tail = _tail(out_text)
            if not self.count_server_attempts and r.klass == "server":
                result, saved_attempts = "moved", attempts  # a move is not a model retry
            else:
                result = "retry" if attempt == 1 else "failed"
                saved_attempts = attempt
            changed = 0
        else:
            result, changed, post = self._check(r, tid, staged, owned, state)
            saved_attempts = attempt
        with _STATE_LOCK:
            append_metrics(self.a / "executor-metrics.md", row, spec_lines, prompt_lines,
                           seconds, changed, result, lane=self.lane)
        record = {"verdict": r.verdict, "klass": r.klass, "attempts": saved_attempts}
        if self.lane:
            record["lane"] = self.lane
        self._save_task(tid, record, pre, post)
        return r

    def _check(self, r: TaskResult, tid: int, staged: Path, owned: list[str], state: dict):
        rc, test_out = run_shell(self.test_command, self.wt)
        post = snapshot_tree(self.wt, self.dir / f"idx-post{self.tag}")
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
            return "failed", len(changed), post
        flagged = any(r.checks[k] != "none" for k in ("TAMPER", "SCOPE", "SKIPS", "SCRIPT"))
        r.verdict = "FLAG" if flagged else "CLEAN"
        return ("flagged" if flagged else "success"), len(changed), post


def _repo_root(wt: Path) -> Path:
    """The repository's main worktree (first entry of git worktree list)."""
    first = _git(wt, "worktree", "list", "--porcelain").splitlines()[0]
    return Path(first.split(" ", 1)[1])


class LanePool:
    """Runs independent tasks on every live local lane at the same time.

    The main thread owns the main worktree: it syncs each lane worktree to the
    merged main state before every dispatch and merges CLEAN results back.
    One worker thread per busy lane runs TaskRunner._run_one. A lane that dies
    (server-class failure or failed pre-dispatch health check) is never
    re-probed during the run; its in-flight task moves to another lane without
    spending the retry budget.
    """

    def __init__(self, artifact_dir, lanes: list[str], *,
                 dispatcher_factory: Callable[[Executor], object],
                 health: Callable[[Executor], int], test_command: str | None = None,
                 interval: float = 60):
        self.a = Path(artifact_dir)
        self.lanes = list(lanes)
        self.dispatcher_factory = dispatcher_factory
        self.health = health
        self.test_command = test_command
        self.interval = interval

    def _read_state(self) -> dict:
        p = self.a / ".fbl" / "state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"tasks": {}, "pre": {}}

    def run(self, ids: list[int], retry_feedback: str | None = None,
            emit: Callable[[TaskResult], None] | None = None) -> list[TaskResult]:
        results: list[TaskResult] = []

        def out(r: TaskResult) -> None:
            results.append(r)
            if emit:
                emit(r)

        if not self.lanes:
            out(TaskResult(ids[0], "STOP", stop="ALL_LANES_DOWN", detail="no live lanes"))
            return results
        plain = TaskRunner(self.a, EXECUTORS[self.lanes[0]], health=self.health,
                           test_command=self.test_command)
        if plain.test_command is None:
            out(TaskResult(ids[0], "STOP", stop="NO_TEST_COMMAND", detail="pass --test-command once"))
            return results
        main_wt = plain.wt
        plain._checkpoint(retry=retry_feedback is not None)

        specs = {}
        for tid in ids:
            spec_path = self.a / "tasks" / f"task-{tid}.md"
            specs[tid] = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        tasks_state = self._read_state().get("tasks", {})
        for tid in ids:
            for dep in parse_depends(specs[tid], tid, ids):
                if dep not in ids and tasks_state.get(str(dep), {}).get("verdict") != "CLEAN":
                    out(TaskResult(tid, "STOP", stop="DEPENDS",
                                   detail=f"task {dep} is not CLEAN in state.json"))
                    return results
        deps = {tid: parse_depends(specs[tid], tid, ids) for tid in ids}
        paths = {tid: task_paths(specs[tid], self.a / "tests" / f"task-{tid}") for tid in ids}

        repo = _repo_root(main_wt)
        lane_wts: dict[str, Path] = {}
        lane_dirs: dict[str, Path] = {}
        for lane in self.lanes:
            lane_wts[lane] = create_lane_worktree(main_wt, repo / ".worktrees" / f"fbl-{self.a.name}-{lane}")
            lane_dirs[lane] = make_lane_dir(self.a, lane, lane_wts[lane])

        work_queue: list[int] = list(ids)
        done: set[int] = set()
        running: dict[str, int] = {}
        dead: set[str] = set()
        moves: dict[int, int] = {}
        moved_from: dict[int, str] = {}
        busy: set[str] = set()
        stop_new = False
        completions: queue.Queue = queue.Queue()

        def spawn(lane: str, tid: int, runner: TaskRunner, feedback, origin: str | None) -> None:
            def work() -> None:
                try:
                    r = runner._run_one(tid, feedback)
                except Exception as exc:  # a worker must always report back
                    r = TaskResult(tid, "FAIL", klass="unknown", detail=f"lane worker crashed: {exc}",
                                   log_tail=_tail(str(exc)))
                if origin is not None:
                    r.moved = f"{origin}->{lane}"
                completions.put((lane, tid, r))
            threading.Thread(target=work, daemon=True).start()

        def handle(lane: str, tid: int, r: TaskResult) -> None:
            nonlocal stop_new, busy
            running.pop(lane, None)
            busy -= paths.get(tid, set())
            if r.verdict == "CLEAN":
                done.add(tid)
                st = self._read_state()
                pre = st.get("pre", {}).get(str(tid))
                post = st.get("post", {}).get(str(tid))
                merge = set(paths.get(tid, set()))
                if pre and post:
                    raw = diff_trees(lane_wts[lane], pre, post, include_tests=True)
                    merge |= {p for p, _ in _split_files(raw)}
                merge_paths(lane_wts[lane], main_wt, merge)
                out(r)
                return
            if r.klass == "server" or r.stop == "PREFLIGHT":
                dead.add(lane)
                if moves.get(tid, 0) >= 1:
                    out(TaskResult(tid, "STOP", stop="MOVE_BUDGET",
                                   detail=f"moved off {moved_from.get(tid)} once; {lane} died too"))
                    stop_new = True
                else:
                    moves[tid] = moves.get(tid, 0) + 1
                    moved_from[tid] = lane
                    work_queue.append(tid)  # back of the queue; no retry budget spent
                return
            stop_new = True  # first FLAG/FAIL/STOP that is not a move ends new assignments
            out(r)

        def dispatch_some() -> bool:
            nonlocal busy
            started = False
            for lane in self.lanes:
                if stop_new or not work_queue:
                    break
                if lane in dead or lane in running:
                    continue
                tid = pick_task(work_queue, deps, done, busy, paths)
                if tid is None:
                    break  # nothing ready on any idle lane
                if self.health(EXECUTORS[lane]) != 200:
                    dead.add(lane)  # task never dispatched: keeps its queue slot, no move
                    continue
                sync_lane(lane_wts[lane], main_wt, self.a / ".fbl" / f"idx-lane-{lane}")
                runner = TaskRunner(self.a, EXECUTORS[lane],
                                    dispatcher=self.dispatcher_factory(EXECUTORS[lane]),
                                    health=self.health, worktree=lane_wts[lane],
                                    dispatch_dir=lane_dirs[lane], lane=lane,
                                    count_server_attempts=False)
                if retry_feedback is not None:
                    staged = self.a / "tests" / f"task-{tid}"
                    shutil.copytree(staged, lane_wts[lane], dirs_exist_ok=True)
                    pre = snapshot_tree(lane_wts[lane], self.a / ".fbl" / f"idx-lane-{lane}")
                    runner._save_task(tid, None, pre, None)
                    post = self._read_state().get("post", {}).get(str(tid))
                    if post:
                        overlay_paths(lane_wts[lane], post, set(parse_owned(specs[tid])))
                work_queue.remove(tid)
                running[lane] = tid
                busy = busy | paths.get(tid, set())
                spawn(lane, tid, runner, retry_feedback, moved_from.get(tid))
                started = True
            return started

        try:
            while work_queue or running:
                try:
                    while True:
                        handle(*completions.get_nowait())
                except queue.Empty:
                    pass
                if not work_queue and not running:
                    break
                dispatch_some()
                if not running:
                    if stop_new or not work_queue:
                        break
                    if all(lane in dead for lane in self.lanes):
                        for tid in list(work_queue):
                            out(TaskResult(tid, "STOP", stop="ALL_LANES_DOWN",
                                           detail="every lane died during this run"))
                        work_queue.clear()
                        break
                    if pick_task(work_queue, deps, done, busy, paths) is None:
                        for tid in list(work_queue):
                            out(TaskResult(tid, "STOP", stop="DEPENDS",
                                           detail="nothing running and nothing ready"))
                        work_queue.clear()
                        break
                    continue
                try:
                    handle(*completions.get(timeout=1.0))
                except queue.Empty:
                    pass
        finally:
            for lane, wt_path in lane_wts.items():
                remove_lane_worktree(main_wt, wt_path)
        return results


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

def _executor(name: str | None) -> Executor:
    return EXECUTORS[name or DEFAULT_EXECUTOR]


def current_candidates() -> tuple[list[str], dict[str, str], list[str]]:
    """Eligible candidate names, skipped {name: reason}, and WARN= lines.

    Reads the Pi registry and fiftybox-config at call time (the paths are module
    globals); an unreadable registry skips the registration check with a warning."""
    registry = load_json(PI_MODELS_PATH)
    names, skipped = eligible_candidates(registry, load_json(CONFIG_PATH))
    warnings = [] if registry is not None else ["WARN=pi registry unreadable; registration check skipped"]
    return names, skipped, warnings


def select_mode(lanes_arg: str | None, executor_arg: str | None, health: Callable[[Executor], int],
                state: dict, ids: list[int], *,
                candidates: list[str] | None = None) -> tuple[str, list[str]]:
    """single | pool | down, plus the lanes to use.

    An explicit --executor keeps the old single-lane path. Otherwise the names
    are --lanes or every table entry, limited to ``candidates`` (None = all) and
    filtered by health, one lane per PC: two live lanes dispatch in parallel, one
    live lane stays sequential unless this batch already recorded a lane (a run
    in progress or moved)."""
    if executor_arg:
        return "single", [executor_arg]
    names = [s.strip() for s in lanes_arg.split(",") if s.strip()] if lanes_arg else list(EXECUTORS)
    unknown = [n for n in names if n not in EXECUTORS]
    if unknown:
        raise ValueError(f"unknown lane: {unknown[0]}")
    allowed = list(EXECUTORS) if candidates is None else candidates
    live = live_lanes([n for n in names if n in allowed], health)
    if not live:
        return "down", []
    if len(live) >= 2:
        return "pool", live
    tasks = (state or {}).get("tasks", {})
    if any(tasks.get(str(i), {}).get("lane") for i in ids):
        return "pool", live
    return "single", live


def _preflight_executor(args) -> int:
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


def _preflight_pool(args) -> int:
    """Pool preflight: every candidate in EXECUTORS, ok if at least one lane is up.

    The studio is never auto-started; when ioh alone answers, runs proceed on
    ioh (see reference.md for the studio start procedure)."""
    names, skipped, warnings = current_candidates()
    for line in warnings:
        print(line)
    for name, reason in skipped.items():
        print(f"SKIP={name} REASON={reason}")
    if not names:
        print("PREFLIGHT=none (every candidate is off in fiftybox-config or missing from Pi; "
              "run /fiftybox-config)")
        return 1
    codes: dict[str, int] = {}
    served: dict[str, bool] = {}
    for lane in names:
        ex = EXECUTORS[lane]
        codes[lane] = executor_health(ex)
        served[lane] = codes[lane] == 200 and (ex.host != "studio" or ex.model in executor_models(ex))
        suffix = f" SERVED={'yes' if served[lane] else 'no'}" if codes[lane] == 200 else ""
        print(f"LANE={lane} HEALTH={codes[lane]}{suffix}")
    live = live_lanes(names, lambda ex: 200 if served[ex.name] else 0)
    if live:
        print("PICK=" + ",".join(f"{EXECUTORS[lane].host}:{lane}" for lane in live))
    for lane in live:
        marker = "warmed" if lane == "flash-next" else f"warmed-{lane}"
        warmed = Path(args.artifact_dir, ".fbl", marker) if args.artifact_dir else None
        if warmed is None or not warmed.exists():
            wcode = warm_up(EXECUTORS[lane])
            print(f"WARM={lane}:{'ok' if wcode == 200 else wcode}")
            if wcode == 200 and warmed is not None:
                warmed.parent.mkdir(exist_ok=True)
                warmed.write_text("1", encoding="utf-8")
    if live:
        print(f"LANES_UP={','.join(live)}")
        print("PREFLIGHT=ok")
        return 0
    print(f"LANES={probe_lanes()}")
    if any(codes[n] == 401 for n in names if EXECUTORS[n].host == "studio"):
        print("PREFLIGHT=auth (key file and studio auth.api_key disagree; do not reissue the key)")
    else:
        print("PREFLIGHT=down (start procedure: reference.md)")
    return 1


def cmd_preflight(args) -> int:
    if args.executor:
        return _preflight_executor(args)
    return _preflight_pool(args)


def cmd_run(args) -> int:
    try:
        ids = parse_task_range(args.tasks)
    except ValueError as exc:
        print(f"STOP=BAD_TASKS DETAIL={exc}")
        return 2
    if args.detach:
        a = Path(args.artifact_dir)
        out = a / "fbl-run.out"
        cmd = [sys.executable, str(Path(__file__).resolve()), "run", "--artifact-dir", str(a),
               "--tasks", args.tasks]
        if args.executor:
            cmd += ["--executor", args.executor]
        if args.lanes:
            cmd += ["--lanes", args.lanes]
        cmd.append("--emit-done")
        for flag, val in (("--test-command", args.test_command),
                          ("--retry-feedback-file", args.retry_feedback_file)):
            if val:
                cmd += [flag, val]
        with out.open("w", encoding="utf-8") as fh:
            subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        print(f"DETACHED OUT={out}")
        return 0
    feedback = Path(args.retry_feedback_file).read_text(encoding="utf-8") if args.retry_feedback_file else None
    state_path = Path(args.artifact_dir) / ".fbl" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    candidates, _skipped, _warnings = current_candidates()
    if not args.executor and not candidates:
        print("STOP=NO_CANDIDATES DETAIL=every candidate is off in fiftybox-config or missing from Pi")
        return 2
    try:
        mode, lanes = select_mode(args.lanes, args.executor, executor_serving, state, ids,
                                  candidates=candidates)
    except ValueError as exc:
        print(f"STOP=BAD_LANES DETAIL={exc}")
        return 2
    shown: list[TaskResult] = []

    def emit(r: TaskResult) -> None:
        shown.append(r)
        print(format_result(r), flush=True)
        if r.log_tail:
            print("\n".join("  | " + l for l in r.log_tail.splitlines()), flush=True)

    if mode == "down":
        emit(TaskResult(ids[0], "STOP", stop="ALL_LANES_DOWN",
                        detail="no lane answers health; run preflight"))
        results = shown
    elif mode == "pool":
        def dispatcher_factory(ex: Executor):
            return OrchestrateDispatcher(health=lambda: executor_serving(ex),
                                         interval=60, misses=3)

        pool = LanePool(args.artifact_dir, lanes, dispatcher_factory=dispatcher_factory,
                        health=executor_serving, test_command=args.test_command, interval=60)
        results = pool.run(ids, retry_feedback=feedback, emit=emit)
    else:
        ex = _executor(args.executor) if args.executor else EXECUTORS[lanes[0]]
        runner = TaskRunner(args.artifact_dir, ex, test_command=args.test_command,
                            health=executor_serving)
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
    lanes = calibrate_by_lane(rows) or {"flash-next": calibrate([])}
    note = False
    for lane, info in lanes.items():
        print(f"LANE={lane} N={info['n']} STREAK={info['streak']} "
              f"LAST5={info['last5_rate']:.2f} ADVICE={info['advice']}")
        if info["advice"] != "KEEP":
            note = True
    if note:
        print("NOTE=show these rows to the user; change limits only after approval")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fbl_task.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, executor=True):
        if executor:
            sp.add_argument("--executor", choices=sorted(EXECUTORS), default=None)

    sp = sub.add_parser("preflight")
    common(sp)
    sp.add_argument("--artifact-dir")
    sp.set_defaults(fn=cmd_preflight)

    sp = sub.add_parser("run")
    common(sp)
    sp.add_argument("--lanes", help="comma-separated candidate names from EXECUTORS (default: every eligible candidate)")
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
