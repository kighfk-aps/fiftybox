#!/usr/bin/env python3
"""Unit tests for tests/bench/token_bench.py (pure parts only: no model calls)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fbl = load("fbl_task", "skills/fiftybox-local/scripts/fbl_task.py")
bench = load("token_bench", "tests/bench/token_bench.py")


def run_tests(repo: Path) -> int:
    return subprocess.run(bench.TEST_COMMAND, shell=True, cwd=repo, capture_output=True).returncode


class FixtureTest(unittest.TestCase):
    def test_tasks_fit_the_executor_budget(self):
        self.assertEqual(len(bench.TASKS), 4)
        for t in bench.TASKS:
            self.assertLessEqual(len(t.spec.splitlines()), fbl.TASK_SPEC_MAX_LINES, t.id)
            self.assertLessEqual(len(fbl.parse_owned(t.spec)), fbl.TASK_MAX_FILES, t.id)
            self.assertTrue(fbl.parse_owned(t.spec), f"task {t.id} needs a Modify ONLY line")
        self.assertLessEqual(len(bench.DESIGN.splitlines()), fbl.EXECUTORS["gemma4"].design_max)

    def test_red_fails_then_reference_passes_cumulatively(self):
        with tempfile.TemporaryDirectory() as td:
            repo = bench.build_skeleton(Path(td) / "repo")
            for t in bench.TASKS:
                bench.write_files(repo, t.red)
                self.assertNotEqual(run_tests(repo), 0, f"task {t.id} Red must fail before implementation")
                bench.write_files(repo, t.reference)
                self.assertEqual(run_tests(repo), 0, f"task {t.id} reference must satisfy its tests")

    def test_reference_touches_only_owned_files(self):
        for t in bench.TASKS:
            self.assertEqual(sorted(t.reference), sorted(fbl.parse_owned(t.spec)), t.id)


class ClaudeJsonTest(unittest.TestCase):
    SAMPLE = {
        "type": "result", "subtype": "success", "is_error": False, "result": "ok",
        "num_turns": 3, "duration_ms": 4200, "total_cost_usd": 0.0421,
        "usage": {"input_tokens": 5, "cache_creation_input_tokens": 1000,
                  "cache_read_input_tokens": 9000, "output_tokens": 300},
        "modelUsage": {"claude-sonnet-5-5": {}},
    }

    def test_parse_flattens_usage(self):
        r = bench.parse_claude_json(json.dumps(self.SAMPLE))
        self.assertEqual((r["input"], r["cache_write"], r["cache_read"], r["output"]), (5, 1000, 9000, 300))
        self.assertEqual((r["turns"], r["cost"], r["error"]), (3, 0.0421, None))
        self.assertEqual(r["models"], ["claude-sonnet-5-5"])

    def test_parse_marks_budget_errors_without_raising(self):
        bad = dict(self.SAMPLE, subtype="error_max_budget_usd", is_error=True)
        self.assertEqual(bench.parse_claude_json(json.dumps(bad))["error"], "error_max_budget_usd")

    def test_parse_rejects_non_json(self):
        with self.assertRaises(bench.BenchError):
            bench.parse_claude_json("Not logged in")

    def test_cmd_has_isolation_and_safety_flags(self):
        cmd = bench.claude_cmd("hi", model="sonnet", tools="Bash,Read", budget=1.5, append_system_prompt="SYS")
        self.assertEqual(cmd[:3], ["claude", "-p", "hi"])
        for flag in ("--output-format", "--no-session-persistence", "--strict-mcp-config",
                     "--disable-slash-commands", "--max-budget-usd", "--tools", "--allowedTools"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--max-budget-usd") + 1], "1.50")
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertEqual(cmd[cmd.index("--append-system-prompt") + 1], "SYS")
        self.assertNotIn("--append-system-prompt", bench.claude_cmd("hi", model="m", tools="", budget=1))


class NotifyArmTest(unittest.TestCase):
    def test_persistent_session_flags(self):
        start = bench.claude_cmd("go", model="m", tools="Bash", budget=1, session_id="sid-1")
        self.assertEqual(start[start.index("--session-id") + 1], "sid-1")
        self.assertNotIn("--no-session-persistence", start)
        resume = bench.claude_cmd("done", model="m", tools="Bash", budget=1, resume="sid-1")
        self.assertEqual(resume[resume.index("--resume") + 1], "sid-1")
        self.assertNotIn("--no-session-persistence", resume)
        self.assertIn("--no-session-persistence", bench.claude_cmd("x", model="m", tools="Bash", budget=1))

    def test_notification_points_at_the_output_file_only(self):
        text = bench.notification_text(Path("/tmp/A"), 0)
        self.assertIn("/tmp/A/fbl-run.out", text)
        self.assertIn("completed", text)
        self.assertIn("exit code 0", text)
        self.assertNotIn("VERDICT", text)  # the model must read the output itself, like a real notification

    def test_start_prompt_forbids_polling_and_names_the_detached_path(self):
        text = bench.LOCAL_NOTIFY_START.format(A="/tmp/A", cmd="T", ex="gemma4")
        self.assertIn("--detach", text)
        self.assertIn("stop", text.lower())
        self.assertNotIn("wait", text.lower().replace("wait for", ""))


class ResumedCostTest(unittest.TestCase):
    def test_resumed_call_cost_is_session_cumulative_so_the_first_call_is_deducted(self):
        # observed: a --resume call reports total_cost_usd = its own cost + the earlier calls' cost
        first = dict(cost=0.0442, input=2, cache_write=9995, cache_read=15065, output=271, turns=2)
        second = dict(cost=0.0657, input=4, cache_write=2492, cache_read=53728, output=613, turns=4)
        fixed = bench.deduct_resumed_cost(first, second)
        self.assertAlmostEqual(fixed["cost"], 0.0215, places=6)
        self.assertEqual(fixed["cache_write"], 2492)  # token usage is already per call
        self.assertEqual(second["cost"], 0.0657)  # input is not mutated


class OutDirTest(unittest.TestCase):
    def test_relative_output_dir_becomes_absolute(self):
        # a relative --out was passed as a relative --cwd to orchestrate.py and the path doubled
        self.assertTrue(bench.out_dir("rel/run").is_absolute())
        self.assertEqual(bench.out_dir("rel/run").name, "run")


class ReportTest(unittest.TestCase):
    def runs(self, cost, turns):
        return [dict(input=2, cache_write=100, cache_read=1000, output=50, cost=cost,
                     turns=turns, duration_ms=1000, error=None)] * 2

    def test_aggregate_sums_every_field(self):
        agg = bench.aggregate(self.runs(0.1, 4))
        self.assertEqual((agg["calls"], agg["turns"]), (2, 8))
        self.assertEqual((agg["input"], agg["cache_write"], agg["cache_read"], agg["output"]),
                         (4, 200, 2000, 100))
        self.assertAlmostEqual(agg["cost"], 0.2)
        self.assertEqual(agg["total_tokens"], 2304)

    def test_report_compares_arms_against_the_baseline(self):
        results = {"sonnet": bench.aggregate(self.runs(0.30, 5)),
                   "local-new": bench.aggregate(self.runs(0.10, 3))}
        text = bench.render_report(results, baseline="sonnet")
        self.assertIn("| sonnet |", text)
        self.assertIn("| local-new |", text)
        self.assertIn("-67%", text)  # 0.20 vs 0.60 total cost
        self.assertIn("baseline", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
