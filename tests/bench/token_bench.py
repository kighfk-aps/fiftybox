#!/usr/bin/env python3
"""Claude token bench: local executor via fiftybox-local vs Sonnet implementing directly.

Same toy workload (4 tiny textkit tasks, Red tests pre-written) goes through:
  sonnet     one fresh headless Sonnet session per task implements it (baseline)
  local-new  ONE headless orchestrator session drives the new fiftybox-local flow
             (fbl_task.py); the local model (gemma4 by default) implements
  local-old  the same, but following the pre-change SKILL.md (git HEAD) by hand
  local-notify  like local-new, but models the real Claude Code path: the session starts the batch
             and ends its turn, the harness waits, then resumes the session with a completion
             notice (no wait/poll turns)

Claude usage comes from `claude -p --output-format json` (tokens + total_cost_usd).
Tokens used by the local model are free and not counted. Test writing (Step 4) is
pre-staged for every arm, so it is excluded everywhere.

  python3 tests/bench/token_bench.py --arms sonnet,local-new --report docs/reviews/X.md
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_COMMAND = "PYTHONPATH=. python3 -m unittest discover -s tests -q"
ORCHESTRATE = Path("~/.claude/skills/fiftybox-orchestration/scripts/orchestrate.py").expanduser()
FBL_INSTALLED = "~/.claude/skills/fiftybox-local/scripts/fbl_task.py"


class BenchError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Task:
    id: int
    title: str
    spec: str
    red: dict
    reference: dict


DESIGN = """# textkit design
Package `textkit`: small pure-Python text helpers. Python 3.9+, standard library only, no I/O.
Files (one module per concern):
- textkit/slug.py: URL slugs
- textkit/stats.py: word statistics (exposes words(text), reused by other modules)
- textkit/wrap.py: truncation
- textkit/readability.py: sentence and word-length metrics (imports words from textkit.stats)
Conventions: type hints on public functions, no global state, raise ValueError on invalid arguments.
Tests: unittest files under tests/. Run: PYTHONPATH=. python3 -m unittest discover -s tests -q
"""

_HEAD = "import unittest\n\n"
_TAIL = "\n\nif __name__ == \"__main__\":\n    unittest.main()\n"

TASKS = [
    Task(1, "slugify",
         "Task 1: slugify\n"
         "Modify ONLY: textkit/slug.py\n"
         "- Add slugify(text: str) -> str.\n"
         "- Lowercase the text, then replace every run of characters outside a-z and 0-9 with a single \"-\".\n"
         "- No leading or trailing \"-\". Empty or symbol-only input returns \"\".",
         {"tests/test_slug.py": _HEAD + "from textkit.slug import slugify\n\n\n"
          "class SlugifyTest(unittest.TestCase):\n"
          "    def test_basic(self):\n        self.assertEqual(slugify(\"Hello World\"), \"hello-world\")\n\n"
          "    def test_runs_collapse(self):\n        self.assertEqual(slugify(\"a  --  b!!c\"), \"a-b-c\")\n\n"
          "    def test_trims_edges(self):\n        self.assertEqual(slugify(\"  --Hi--  \"), \"hi\")\n\n"
          "    def test_empty_and_symbols(self):\n        self.assertEqual(slugify(\"\"), \"\")\n"
          "        self.assertEqual(slugify(\"!!!\"), \"\")\n\n"
          "    def test_digits_kept(self):\n        self.assertEqual(slugify(\"Top 10 Tips\"), \"top-10-tips\")\n" + _TAIL},
         {"textkit/slug.py": "import re\n\n\ndef slugify(text: str) -> str:\n"
          "    return re.sub(r\"[^a-z0-9]+\", \"-\", text.lower()).strip(\"-\")\n"}),
    Task(2, "word statistics",
         "Task 2: word statistics\n"
         "Modify ONLY: textkit/stats.py\n"
         "- A word is a run of ASCII letters, digits or apostrophes. Matching is case-insensitive; words are lowercased.\n"
         "- words(text) -> list[str]: the words in order of appearance.\n"
         "- word_count(text) -> int: the number of words.\n"
         "- top_words(text, n) -> list[tuple[str, int]]: the n most common words, highest count first, ties in\n"
         "  alphabetical order. n <= 0 returns [].",
         {"tests/test_stats.py": _HEAD + "from textkit.stats import top_words, word_count, words\n\n\n"
          "class StatsTest(unittest.TestCase):\n"
          "    def test_words(self):\n        self.assertEqual(words(\"Hello, world! It's 9AM\"), [\"hello\", \"world\", \"it's\", \"9am\"])\n\n"
          "    def test_word_count(self):\n        self.assertEqual(word_count(\"Hello, world! It's 9AM\"), 4)\n"
          "        self.assertEqual(word_count(\"\"), 0)\n\n"
          "    def test_top_words_orders_ties_alphabetically(self):\n"
          "        self.assertEqual(top_words(\"b a b A c\", 2), [(\"a\", 2), (\"b\", 2)])\n\n"
          "    def test_top_words_n_larger_than_vocabulary(self):\n"
          "        self.assertEqual(top_words(\"x y\", 5), [(\"x\", 1), (\"y\", 1)])\n\n"
          "    def test_top_words_non_positive_n(self):\n        self.assertEqual(top_words(\"x\", 0), [])\n"
          "        self.assertEqual(top_words(\"x\", -2), [])\n" + _TAIL},
         {"textkit/stats.py": "import re\nfrom collections import Counter\n\n_WORD = re.compile(r\"[a-z0-9']+\")\n\n\n"
          "def words(text: str) -> list[str]:\n    return _WORD.findall(text.lower())\n\n\n"
          "def word_count(text: str) -> int:\n    return len(words(text))\n\n\n"
          "def top_words(text: str, n: int) -> list[tuple[str, int]]:\n    if n <= 0:\n        return []\n"
          "    counts = Counter(words(text))\n    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]\n"}),
    Task(3, "truncate",
         "Task 3: truncate\n"
         "Modify ONLY: textkit/wrap.py\n"
         "- Add truncate(text: str, width: int, suffix: str = \"...\") -> str.\n"
         "- Raise ValueError first if width < len(suffix).\n"
         "- If len(text) <= width return text unchanged.\n"
         "- Otherwise keep the first width - len(suffix) characters, strip trailing whitespace from them,\n"
         "  then append suffix.",
         {"tests/test_wrap.py": _HEAD + "from textkit.wrap import truncate\n\n\n"
          "class TruncateTest(unittest.TestCase):\n"
          "    def test_short_text_is_unchanged(self):\n        self.assertEqual(truncate(\"short\", 10), \"short\")\n\n"
          "    def test_cuts_and_appends_suffix(self):\n        self.assertEqual(truncate(\"hello world\", 8), \"hello...\")\n\n"
          "    def test_strips_trailing_space_before_suffix(self):\n        self.assertEqual(truncate(\"hello world\", 9), \"hello...\")\n\n"
          "    def test_custom_suffix(self):\n        self.assertEqual(truncate(\"abcdef\", 5, suffix=\"~\"), \"abcd~\")\n\n"
          "    def test_width_smaller_than_suffix(self):\n        with self.assertRaises(ValueError):\n"
          "            truncate(\"abcdef\", 2)\n        with self.assertRaises(ValueError):\n            truncate(\"a\", 2)\n" + _TAIL},
         {"textkit/wrap.py": "def truncate(text: str, width: int, suffix: str = \"...\") -> str:\n"
          "    if width < len(suffix):\n        raise ValueError(\"width is smaller than the suffix\")\n"
          "    if len(text) <= width:\n        return text\n    return text[: width - len(suffix)].rstrip() + suffix\n"}),
    Task(4, "readability metrics",
         "Task 4: readability metrics\n"
         "Modify ONLY: textkit/readability.py\n"
         "- sentence_count(text) -> int: count the non-empty pieces after splitting on runs of \".\", \"!\" or \"?\".\n"
         "- avg_word_length(text) -> float: mean length of the words returned by textkit.stats.words,\n"
         "  rounded to 2 decimals; 0.0 when there are no words.",
         {"tests/test_readability.py": _HEAD + "from textkit.readability import avg_word_length, sentence_count\n\n\n"
          "class ReadabilityTest(unittest.TestCase):\n"
          "    def test_sentence_count(self):\n        self.assertEqual(sentence_count(\"Hi. Bye!\"), 2)\n"
          "        self.assertEqual(sentence_count(\"\"), 0)\n        self.assertEqual(sentence_count(\"No end\"), 1)\n"
          "        self.assertEqual(sentence_count(\"Wait... what?!\"), 2)\n\n"
          "    def test_avg_word_length(self):\n        self.assertEqual(avg_word_length(\"aa bbbb\"), 3.0)\n"
          "        self.assertEqual(avg_word_length(\"a bb ccc\"), 2.0)\n        self.assertEqual(avg_word_length(\"it's\"), 4.0)\n\n"
          "    def test_avg_word_length_without_words(self):\n        self.assertEqual(avg_word_length(\"\"), 0.0)\n"
          "        self.assertEqual(avg_word_length(\"!!! ???\"), 0.0)\n" + _TAIL},
         {"textkit/readability.py": "import re\n\nfrom textkit.stats import words\n\n\n"
          "def sentence_count(text: str) -> int:\n    return len([p for p in re.split(r\"[.!?]+\", text) if p.strip()])\n\n\n"
          "def avg_word_length(text: str) -> float:\n    found = words(text)\n    if not found:\n        return 0.0\n"
          "    return round(sum(len(w) for w in found) / len(found), 2)\n"}),
]


# ---------- fixture ----------

def write_files(repo: Path, files: dict) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), "-c", "user.email=bench@local", "-c", "user.name=bench", *args],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise BenchError(f"git {' '.join(args)} failed: {res.stderr.strip()[:300]}")
    return res.stdout


def build_skeleton(dest: Path) -> Path:
    dest.mkdir(parents=True)
    git(dest, "init", "-q", "-b", "main")
    write_files(dest, {"README.md": "# textkit\n", "textkit/__init__.py": "",
                       ".gitignore": "__pycache__/\n.omx/\n.worktrees/\n"})
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "skeleton")
    return dest


# ---------- claude headless ----------

def claude_cmd(prompt: str, *, model: str, tools: str, budget: float,
               append_system_prompt: str | None = None, session_id: str | None = None,
               resume: str | None = None) -> list[str]:
    persist = bool(session_id or resume)
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "json",
           "--max-budget-usd", f"{budget:.2f}"]
    if not persist:
        cmd.append("--no-session-persistence")
    cmd += ["--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "",
            "--tools", tools, "--allowedTools", tools]
    if append_system_prompt:
        cmd += ["--append-system-prompt", append_system_prompt]
    if session_id:
        cmd += ["--session-id", session_id]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def parse_claude_json(stdout: str) -> dict:
    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        raise BenchError(f"claude did not return JSON: {stdout[:200]!r}") from None
    u = d.get("usage") or {}
    return {
        "input": u.get("input_tokens", 0), "cache_write": u.get("cache_creation_input_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0), "output": u.get("output_tokens", 0),
        "cost": d.get("total_cost_usd", 0.0), "turns": d.get("num_turns", 0),
        "duration_ms": d.get("duration_ms", 0), "error": d.get("subtype") if d.get("is_error") else None,
        "models": list((d.get("modelUsage") or {}).keys()), "result": d.get("result", ""),
    }


def run_claude(cmd: list[str], cwd: Path, timeout: int = 1800) -> dict:
    env = dict(os.environ, BASH_DEFAULT_TIMEOUT_MS="600000", BASH_MAX_TIMEOUT_MS="600000")
    try:
        res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise BenchError(f"claude session exceeded {timeout}s") from None
    return parse_claude_json(res.stdout)


# ---------- aggregation ----------

def aggregate(runs: list[dict]) -> dict:
    keys = ("input", "cache_write", "cache_read", "output", "cost", "turns", "duration_ms")
    agg = {k: sum(r.get(k, 0) for r in runs) for k in keys}
    agg["calls"] = len(runs)
    agg["total_tokens"] = agg["input"] + agg["cache_write"] + agg["cache_read"] + agg["output"]
    agg["errors"] = [r["error"] for r in runs if r.get("error")]
    return agg


def render_report(results: dict, baseline: str) -> str:
    rows = ["| arm | Claude calls | turns | input | cache write | cache read | output | total tokens | cost USD | vs baseline |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    base = results.get(baseline, {}).get("cost") or 0
    for name, a in results.items():
        if name == baseline:
            delta = "baseline"
        elif base:
            delta = f"{(a['cost'] - base) / base * 100:+.0f}%"
        else:
            delta = "-"
        rows.append(f"| {name} | {a['calls']} | {a['turns']} | {a['input']:,} | {a['cache_write']:,} | "
                    f"{a['cache_read']:,} | {a['output']:,} | {a['total_tokens']:,} | {a['cost']:.4f} | {delta} |")
    return "\n".join(rows)


# ---------- arms ----------

SONNET_PROMPT = """You are implementing one task in a small Python repo (standard library only).

Design:
{design}

Task:
{spec}

The failing tests for this task are already in tests/. Do not edit any test file.
Make them pass, touching only the file named in "Modify ONLY".
Run: {cmd}
Keep comments and docstrings minimal. When the tests pass, reply with the single word DONE.
"""

LOCAL_NEW_PROMPT = """Benchmark run of the fiftybox-local skill (its text is in your system prompt).
Steps 1-4 are done: artifact dir A={A}; tasks 1-4 are staged; the test command is: {cmd}
Start at Step 5 and finish Step 6 for all four tasks as ONE batch (--tasks 1-4).
Benchmark rules:
- Add `--executor {ex}` to every fbl_task.py call (benchmark lane).
- This headless session gets no background notifications, so use the non-notification path of Step 5
  (`run --detach`, then `wait` until it reports done).
- Do not run Step 7 or later. Do not edit files.
Finish with one line: BATCH_REVIEW: OK, or BATCH_REVIEW: ISSUES <short list>.
"""

LOCAL_NOTIFY_START = """Benchmark run of the fiftybox-local skill (its text is in your system prompt).
Steps 1-4 are done: artifact dir A={A}; tasks 1-4 are staged; the test command is: {cmd}
Do Step 5 for all four tasks as ONE batch (--tasks 1-4), then stop.
Benchmark rules:
- Add `--executor {ex}` to every fbl_task.py call (benchmark lane).
- Start the batch with `run --detach` (the headless stand-in for run_in_background), then end your turn
  at once with one short sentence. A completion notice arrives as the next message. Do not poll or sleep.
- Do not run Step 7 or later. Do not edit files.
- When the notice arrives, do Step 6 and finish with one line: BATCH_REVIEW: OK, or BATCH_REVIEW: ISSUES <short list>.
"""

LOCAL_OLD_PROMPT = """Benchmark run of the fiftybox-local skill (its text is in your system prompt).
Steps 1-3 are done. Artifact dir A={A}; worktree W={W}; design is A/design.md; setup already ran.
Four tasks, run them in order one at a time exactly as the skill says (preflight, Red check, dry-run length gate,
detached dispatch with EXIT_CODE sentinel, polling, review gate, executor-metrics row). Task specs are in A/tasks/task-N.md.
Step 4 shortcut: the Red tests are pre-written; instead of writing them, run `cp -r A/tests/task-N/. W/` for task N.
Benchmark rules:
- The executor for this run is {ex}: provider {provider}, model {model}, health URL {base}/v1/models,
  {auth}. Budget limits for this executor: design <= {design_max} lines, prompt <= {prompt_max} lines.
- Test command: {cmd} (run it inside W).
- Do not run Step 7 or later.
Finish with one line: BATCH_REVIEW: OK, or BATCH_REVIEW: ISSUES <short list>.
"""


def deduct_resumed_cost(first: dict, second: dict) -> dict:
    """A --resume call reports total_cost_usd for the whole session, so remove the earlier call's share."""
    fixed = dict(second)
    fixed["cost"] = round(second["cost"] - first["cost"], 6)
    return fixed


def notification_text(a_dir: Path, exit_code: int) -> str:
    """What Claude Code sends when a background command ends: a summary and the output file, not the output."""
    return ("<task-notification>\n<status>completed</status>\n"
            f"<summary>Background command \"fbl_task.py run --detach\" completed (exit code {exit_code})</summary>\n"
            f"<output-file>{a_dir}/fbl-run.out</output-file>\n</task-notification>")


def out_dir(arg: str) -> Path:
    """Absolute output dir: orchestrate.py gets it as --cwd while the subprocess cwd is the same path."""
    return Path(arg).expanduser().resolve()


def load_fbl():
    spec = importlib.util.spec_from_file_location("fbl_task", ROOT / "skills/fiftybox-local/scripts/fbl_task.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fbl_task"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_sonnet_arm(work: Path, a) -> dict:
    repo = build_skeleton(work / "repo-sonnet")
    runs = []
    for t in TASKS:
        write_files(repo, t.red)
        prompt = SONNET_PROMPT.format(design=DESIGN, spec=t.spec, cmd=TEST_COMMAND)
        runs.append(run_claude(claude_cmd(prompt, model=a.sonnet_model, tools="Bash,Read,Edit,Write",
                                          budget=a.task_budget), repo))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"task {t.id}", "--allow-empty")
    ok = subprocess.run(TEST_COMMAND, shell=True, cwd=repo, capture_output=True).returncode == 0
    return {"runs": runs, "tests_pass": ok, "local_seconds": 0}


def stage_local(work: Path, name: str, ex) -> tuple[Path, Path, Path]:
    repo = build_skeleton(work / name)
    res = subprocess.run(
        ["python3", str(ORCHESTRATE), "--phase", "setup", "--task", "textkit bench", "--cwd", str(repo),
         "--implement-agent", "pi", "--provider", ex.provider],
        cwd=repo, capture_output=True, text=True)
    if res.returncode != 0:
        raise BenchError(f"orchestrate setup failed: {(res.stdout + res.stderr)[-400:]}")
    summary = json.loads(res.stdout.strip().splitlines()[-1])
    a_dir, wt = Path(summary["artifactDir"]), Path(summary["worktree"])
    (a_dir / "design.md").write_text(DESIGN, encoding="utf-8")
    (a_dir / "tasks").mkdir(exist_ok=True)
    for t in TASKS:
        (a_dir / "tasks" / f"task-{t.id}.md").write_text(t.spec + "\n", encoding="utf-8")
        write_files(a_dir / "tests" / f"task-{t.id}", t.red)
    return repo, a_dir, wt


def local_outcome(a_dir: Path, wt: Path) -> tuple[bool, int, list[str]]:
    ok = subprocess.run(TEST_COMMAND, shell=True, cwd=wt, capture_output=True).returncode == 0
    metrics = a_dir / "executor-metrics.md"
    rows = []
    seconds = 0
    if metrics.exists():
        fbl = load_fbl()
        for r in fbl.parse_metrics(metrics.read_text(encoding="utf-8")):
            rows.append(r["result"].split()[0] if r["result"] else "?")
            seconds += int(r["duration"].rstrip("s") or 0) if r["duration"].rstrip("s").isdigit() else 0
    return ok, seconds, rows


def run_notify_flow(a, ex, repo: Path, a_dir: Path, wt: Path) -> dict:
    """Two headless calls on one persisted session; the harness, not Claude, waits for the batch."""
    system = (ROOT / "skills/fiftybox-local/SKILL.md").read_text(encoding="utf-8")
    sid = str(uuid.uuid4())
    kw = dict(model=a.orch_model, tools="Bash,Read", budget=a.orch_budget, append_system_prompt=system)
    first = run_claude(claude_cmd(LOCAL_NOTIFY_START.format(A=a_dir, cmd=TEST_COMMAND, ex=ex.name),
                                  session_id=sid, **kw), repo)
    out = a_dir / "fbl-run.out"
    if not out.exists():
        raise BenchError("the orchestrator did not start the batch (no fbl-run.out)")
    waited = load_fbl().wait_for_done(out, max_seconds=1500, poll=3)
    if not waited["done"]:
        raise BenchError("batch did not finish within 1500s")
    second = deduct_resumed_cost(
        first, run_claude(claude_cmd(notification_text(a_dir, 0), resume=sid, **kw), repo))
    ok, seconds, rows = local_outcome(a_dir, wt)
    return {"runs": [first, second], "tests_pass": ok, "local_seconds": seconds, "task_results": rows,
            "session_id": sid, "project_dir": str(repo),
            "final_line": second["result"].strip().splitlines()[-1] if second["result"].strip() else ""}


def run_local_arm(work: Path, a, flow: str) -> dict:
    fbl = load_fbl()
    ex = fbl.EXECUTORS[a.executor]
    repo, a_dir, wt = stage_local(work, f"repo-local-{flow}", ex)
    if flow == "notify":
        return run_notify_flow(a, ex, repo, a_dir, wt)
    if flow == "new":
        system = (ROOT / "skills/fiftybox-local/SKILL.md").read_text(encoding="utf-8")
        prompt = LOCAL_NEW_PROMPT.format(A=a_dir, cmd=TEST_COMMAND, ex=ex.name)
        tools = "Bash,Read"
    else:
        system = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:skills/fiftybox-local/SKILL.md"],
                                capture_output=True, text=True, check=True).stdout
        auth = ("no Authorization header (keyless server)" if not ex.needs_key
                else "Authorization: Bearer $(cat ~/.config/opencode/macstudio-omlx.key)")
        prompt = LOCAL_OLD_PROMPT.format(A=a_dir, W=wt, ex=ex.name, provider=ex.provider, model=ex.model,
                                         base=ex.base_url, auth=auth, design_max=ex.design_max,
                                         prompt_max=ex.prompt_max, cmd=TEST_COMMAND)
        tools = "Bash,Read,Write,Edit"
    run = run_claude(claude_cmd(prompt, model=a.orch_model, tools=tools, budget=a.orch_budget,
                                append_system_prompt=system), repo)
    ok, seconds, rows = local_outcome(a_dir, wt)
    return {"runs": [run], "tests_pass": ok, "local_seconds": seconds, "task_results": rows,
            "final_line": run["result"].strip().splitlines()[-1] if run["result"].strip() else ""}


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arms", default="local-new,sonnet")
    p.add_argument("--executor", default="gemma4", choices=("gemma4", "flash-next"))
    p.add_argument("--orch-model", default="sonnet", help="model for the orchestrator session")
    p.add_argument("--sonnet-model", default="sonnet", help="model for the direct-implementation baseline")
    p.add_argument("--task-budget", type=float, default=0.60, help="USD cap per Sonnet task session")
    p.add_argument("--orch-budget", type=float, default=2.00, help="USD cap per orchestrator session")
    p.add_argument("--out", default=str(ROOT / ".omx/artifacts/bench" / datetime.datetime.now().strftime("%Y%m%dT%H%M%S")))
    p.add_argument("--report", help="write a markdown report to this path")
    a = p.parse_args(argv)

    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    unknown = set(arms) - {"sonnet", "local-new", "local-old", "local-notify"}
    if unknown:
        p.error(f"unknown arms: {sorted(unknown)}")
    fbl = load_fbl()
    if any(x.startswith("local") for x in arms):
        ex = fbl.EXECUTORS[a.executor]
        code = fbl.executor_health(ex)
        if code != 200:
            print(f"executor {ex.name} is not healthy (HTTP {code}); start it first", file=sys.stderr)
            return 1
    work = out_dir(a.out)
    work.mkdir(parents=True)
    outcomes: dict[str, dict] = {}
    for arm in arms:
        print(f"== arm {arm} ...", flush=True)
        if arm == "sonnet":
            outcomes[arm] = run_sonnet_arm(work, a)
        else:
            outcomes[arm] = run_local_arm(work, a, arm.split("-")[1])
        agg = aggregate(outcomes[arm]["runs"])
        outcomes[arm].update(agg=agg)
        print(f"   cost ${agg['cost']:.4f} tokens {agg['total_tokens']:,} tests_pass={outcomes[arm]['tests_pass']}"
              f" errors={agg['errors']}", flush=True)
    results = {k: v["agg"] for k, v in outcomes.items()}
    baseline = "sonnet" if "sonnet" in results else next(iter(results))
    (work / "results.json").write_text(json.dumps(outcomes, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    table = render_report(results, baseline)
    print("\n" + table)
    for arm, o in outcomes.items():
        print(f"- {arm}: tests_pass={o['tests_pass']} local_model_seconds={o['local_seconds']} "
              f"task_results={o.get('task_results', '-')} final={o.get('final_line', '-')!r}")
    if a.report:
        Path(a.report).write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
