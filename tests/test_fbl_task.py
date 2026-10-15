#!/usr/bin/env python3
"""Unit tests for skills/fiftybox-local/scripts/fbl_task.py.

Only the Pi/orchestrate subprocess boundary is replaced (FakeDispatcher);
git, the filesystem, the HTTP health check and every parser run for real.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/fiftybox-local/scripts/fbl_task.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fbl_task", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fbl_task"] = mod
    spec.loader.exec_module(mod)
    return mod


fbl = load_module()


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True, capture_output=True, text=True,
    )
    return out.stdout


def make_repo(root: Path) -> Path:
    repo = root / "wt"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


class ConstantsTest(unittest.TestCase):
    def test_default_executor_is_flash_next_with_fixed_timeout(self):
        self.assertEqual(fbl.DEFAULT_EXECUTOR, "flash-next")
        ex = fbl.EXECUTORS["flash-next"]
        self.assertEqual(ex.provider, "macstudio-qwen-flash-next")
        self.assertEqual(ex.model, "Jundot--Qwen3.8-Flash-Next-oQ4e-mtp")
        self.assertEqual(ex.base_url, "http://100.115.199.115:8000")
        self.assertTrue(ex.needs_key)
        self.assertEqual(fbl.IMPL_TIMEOUT, 1800)

    def test_gemma4_executor_is_keyless_and_keeps_original_budget(self):
        ex = fbl.EXECUTORS["gemma4"]
        self.assertEqual(ex.provider, "macstudio-gemma4")
        self.assertEqual(ex.base_url, "http://100.115.199.115:11235")
        self.assertFalse(ex.needs_key)
        self.assertEqual((ex.design_max, ex.prompt_max), (60, 120))

    def test_ioh_iq3s_executor_is_keyless_and_shares_flash_next_budget(self):
        ex = fbl.EXECUTORS["iq3s"]
        self.assertEqual(ex.provider, "ioh")
        self.assertEqual(ex.model, "qwen3.8-flash-next-iq3_s")
        self.assertEqual(ex.base_url, "http://100.126.254.22:8080")
        self.assertFalse(ex.needs_key)
        self.assertEqual((ex.design_max, ex.prompt_max), (70, 140))

    def test_flash_next_budget_was_raised_after_forty_clean_tasks(self):
        ex = fbl.EXECUTORS["flash-next"]
        self.assertEqual((ex.design_max, ex.prompt_max), (70, 140))
        self.assertEqual(fbl.TASK_SPEC_MAX_LINES, 15)
        self.assertEqual(fbl.TASK_MAX_FILES, 2)
        self.assertEqual(fbl.INTENT_SUMMARY_MAX_LINES, 14)
        self.assertEqual(fbl.BATCH_MAX_TASKS, 5)


class ParseTest(unittest.TestCase):
    def test_task_range(self):
        self.assertEqual(fbl.parse_task_range("1-3"), [1, 2, 3])
        self.assertEqual(fbl.parse_task_range("2,4"), [2, 4])
        self.assertEqual(fbl.parse_task_range("1-2,5"), [1, 2, 5])

    def test_task_range_rejects_garbage_and_oversized_batches(self):
        with self.assertRaises(ValueError):
            fbl.parse_task_range("a-b")
        with self.assertRaises(ValueError):
            fbl.parse_task_range("3-1")
        with self.assertRaises(ValueError):
            fbl.parse_task_range("1-6")  # BATCH_MAX_TASKS is 5

    def test_exit_code_takes_last_sentinel(self):
        self.assertEqual(fbl.parse_exit_code("x\nEXIT_CODE=1\nmore\nEXIT_CODE=3\n"), 3)
        self.assertIsNone(fbl.parse_exit_code("still running"))

    def test_owned_files(self):
        spec = "Add add()\nModify ONLY: `calc.py`, src/util.py\n- do it\n"
        self.assertEqual(fbl.parse_owned(spec), ["calc.py", "src/util.py"])
        self.assertEqual(fbl.parse_owned("no owner line"), [])


class ClassifyTest(unittest.TestCase):
    def test_table(self):
        c = fbl.classify_failure
        self.assertEqual(c("curl: Connection refused", 1, False), "server")
        self.assertEqual(c("Unknown model foo", 1, False), "model")
        self.assertEqual(c("HTTP 404 model gone", 1, False), "model")
        self.assertEqual(c("", 124, False), "timeout")
        self.assertEqual(c("No files changed", 3, True), "too_long")
        self.assertEqual(c("No files changed", 3, False), "no_changes")
        self.assertEqual(c('"finish_reason": "length"', 1, False), "too_long")
        self.assertEqual(c("x is not in the agents list", 1, False), "orchestrate")
        self.assertEqual(c("unrecognized arguments: --foo", 1, False), "orchestrate")
        self.assertEqual(c("weird", 7, False), "unknown")


class DiffFilterTest(unittest.TestCase):
    def test_strips_docstrings_and_comment_only_lines(self):
        diff = "\n".join([
            "+def add(a, b):",
            '+    """Add two numbers.',
            "+",
            "+    Longer text.",
            '+    """',
            "+    # sum them",
            "+    return a + b",
            '+    x = "a#b"  # trailing stays',
        ])
        out = fbl.strip_comment_lines(diff).splitlines()
        self.assertEqual(out, ["+def add(a, b):", "+    return a + b", '+    x = "a#b"  # trailing stays'])

    def test_strips_single_line_docstring_and_js_comments(self):
        diff = "\n".join([
            '+    """One liner."""',
            "+// note",
            "+/* block",
            "+ * more",
            "+ */",
            "+const a = 1;",
            "-// removed note",
        ])
        self.assertEqual(fbl.strip_comment_lines(diff).splitlines(), ["+const a = 1;"])

    def test_comment_stats_counts_only_added_lines(self):
        diff = "+# c1\n+code\n+# c2\n+code2\n-# old\n"
        self.assertEqual(fbl.comment_stats(diff), (4, 2))

    def test_render_diff_has_file_stats_and_truncates(self):
        raw = (
            "diff --git a/calc.py b/calc.py\nindex 1..2 100644\n--- a/calc.py\n+++ b/calc.py\n"
            "@@ -0,0 +1,3 @@\n+a = 1\n+b = 2\n+# note\n"
            "diff --git a/x.py b/x.py\nindex 1..2 100644\n--- a/x.py\n+++ b/x.py\n"
            "@@ -1 +1 @@\n-old\n+new\n"
        )
        out = fbl.render_diff(raw, max_lines=100)
        self.assertIn("## calc.py +3 -0", out)
        self.assertIn("## x.py +1 -1", out)
        self.assertNotIn("index 1..2", out)
        self.assertNotIn("# note", out)
        small = fbl.render_diff(raw, max_lines=3)
        self.assertIn("truncated", small)


class CheckerTest(unittest.TestCase):
    def test_foreign_scripts(self):
        self.assertEqual(fbl.foreign_scripts("# چاپ"), {"ARABIC"})
        self.assertEqual(fbl.foreign_scripts("привет"), {"CYRILLIC"})
        self.assertIn("CJK", fbl.foreign_scripts("漢字"))
        self.assertEqual(fbl.foreign_scripts("한글 abc 123 — ✓ μ"), set())

    def test_skip_markers(self):
        lines = [
            "+@pytest.mark.skip(reason='x')", "+@pytest.mark.xfail", "+it.skip('a', () => {})",
            "+test.only('a', f)", "+    assert True", "+self.skipTest('x')", "+t.Skip()",
            "+    return 1",
        ]
        found = fbl.find_skips(lines)
        self.assertEqual(len(found), 7)
        self.assertNotIn("+    return 1", found)

    def test_scope_violations(self):
        changed = ["calc.py", "other.py", "tests/test_calc.py", "__pycache__/x.pyc",
                   "node_modules/a/b.js", ".venv/bin/python", "pkg/test_inner.py", "a/b.test.js"]
        self.assertEqual(fbl.scope_violations(changed, {"calc.py"}), ["other.py"])

    def test_tampered_tests(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            staged, wt = td / "staged", td / "wt"
            (staged / "tests").mkdir(parents=True)
            (wt / "tests").mkdir(parents=True)
            (staged / "tests/a.py").write_text("assert 1\n", encoding="utf-8")
            (staged / "tests/b.py").write_text("assert 2\n", encoding="utf-8")
            (wt / "tests/a.py").write_text("assert 1\n", encoding="utf-8")
            (wt / "tests/b.py").write_text("assert True\n", encoding="utf-8")
            self.assertEqual(fbl.tampered_tests(staged, wt), ["tests/b.py"])
            (wt / "tests/b.py").unlink()
            self.assertEqual(fbl.tampered_tests(staged, wt), ["tests/b.py"])

    def test_budget_violations(self):
        ex = fbl.EXECUTORS["flash-next"]
        self.assertEqual(fbl.budget_violations(40, 10, 1, 5, ex), [])
        self.assertEqual(
            fbl.budget_violations(71, 16, 3, 15, ex),
            ["design>70", "spec>15", "files>2", "intent>14"],
        )
        self.assertEqual(fbl.budget_violations(61, 1, 1, 1, fbl.EXECUTORS["gemma4"]), ["design>60"])


class MetricsTest(unittest.TestCase):
    def test_append_creates_header_then_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "executor-metrics.md"
            fbl.append_metrics(p, "Task 1", 9, 80, 120, 1, "success")
            fbl.append_metrics(p, "Task 2", 7, 81, 90, 2, "flagged")
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 |")
            self.assertEqual(lines[1], "|---|---|---|---|---|---|")
            self.assertEqual(lines[2], "| Task 1 | 9 | 80 | 120s | 1 | success |")
            self.assertEqual(len(lines), 4)

    def test_calibrate_advice(self):
        rows = [{"result": "success"}] * 10
        self.assertEqual(fbl.calibrate(rows)["advice"], "UP")
        self.assertEqual(fbl.calibrate(rows)["streak"], 10)
        rows = [{"result": "success"}] * 3 + [{"result": "retry"}, {"result": "failed"}]
        info = fbl.calibrate(rows)
        self.assertEqual(info["advice"], "DOWN")
        self.assertAlmostEqual(info["last5_rate"], 0.6)
        self.assertEqual(fbl.calibrate([{"result": "success"}] * 4)["advice"], "KEEP")

    def test_parse_metrics_reads_markdown_tables(self):
        text = (
            "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 |\n|---|---|---|---|---|---|\n"
            "| Task 1 ego | 5 | 80 | 421s | 1 | success (메모) |\n"
            "| Task 6 | 13 | 88 | 287s | 2(+범위밖 1) | retry — 사유 |\n"
        )
        rows = fbl.parse_metrics(text)
        self.assertEqual([r["result"].split()[0] for r in rows], ["success", "retry"])


class HealthTest(unittest.TestCase):
    def setUp(self):
        outer = self
        outer.seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.seen.append(self.headers.get("Authorization"))
                ok = self.headers.get("Authorization") == "Bearer secret"
                self.send_response(200 if ok else 401)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_bearer_key_is_sent_and_status_returned(self):
        base = f"http://127.0.0.1:{self.port}"
        self.assertEqual(fbl.check_health(base, key="secret"), 200)
        self.assertEqual(fbl.check_health(base, key="wrong"), 401)
        self.assertEqual(self.seen[0], "Bearer secret")

    def test_unreachable_returns_zero(self):
        self.assertEqual(fbl.check_health("http://127.0.0.1:1", key=None, timeout=1), 0)

    def test_read_key_strips_newline(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "k"
            p.write_text("abc\n", encoding="utf-8")
            self.assertEqual(fbl.read_key(p), "abc")
            self.assertIsNone(fbl.read_key(Path(td) / "missing"))


class GitSnapshotTest(unittest.TestCase):
    def test_snapshot_diff_excludes_tests_and_leaves_index_alone(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            idx = Path(td) / "idx1"
            t1 = fbl.snapshot_tree(repo, idx)
            (repo / "calc.py").write_text("def add(a, b):\n    return b + a\n", encoding="utf-8")
            (repo / "new.py").write_text("X = 1\n", encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests/test_x.py").write_text("assert 1\n", encoding="utf-8")
            t2 = fbl.snapshot_tree(repo, Path(td) / "idx2")
            diff = fbl.diff_trees(repo, t1, t2)
            self.assertIn("new.py", diff)
            self.assertIn("calc.py", diff)
            self.assertNotIn("test_x.py", diff)
            self.assertEqual(git(repo, "diff", "--cached", "--name-only").strip(), "")


class FakeDispatcher:
    """Stands in for orchestrate.py --phase implement (the LLM boundary)."""

    def __init__(self, repo: Path, *, exit_code: int = 0, prompt_lines: int = 80, edit=None):
        self.repo, self.exit_code, self.prompt_lines, self.edit = repo, exit_code, prompt_lines, edit
        self.dry_calls, self.real_calls, self.feedbacks = 0, 0, []

    def dry_run(self, task_text, artifact_dir, executor, *, retry_feedback=None):
        self.dry_calls += 1
        p = Path(artifact_dir) / ("implement-prompt-retry.md" if retry_feedback else "implement-prompt.md")
        p.write_text("line\n" * self.prompt_lines, encoding="utf-8")
        return p

    def implement(self, task_text, artifact_dir, executor, out_path, *, retry_feedback=None):
        self.real_calls += 1
        self.feedbacks.append(retry_feedback)
        if self.edit:
            self.edit(self.repo)
        Path(out_path).write_text(f"log\nEXIT_CODE={self.exit_code}\n", encoding="utf-8")
        return self.exit_code


def good_edit(repo: Path):
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.repo = make_repo(self.td)
        self.art = self.td / "art"
        (self.art / "tasks").mkdir(parents=True)
        (self.art / "tests/task-1/tests").mkdir(parents=True)
        (self.art / "summary.json").write_text(json.dumps({"worktree": str(self.repo)}), encoding="utf-8")
        (self.art / "design.md").write_text("design\n" * 5, encoding="utf-8")
        (self.art / "tasks/task-1.md").write_text(
            "Add add()\nModify ONLY: calc.py\n- add(a, b) returns a + b\n", encoding="utf-8")
        (self.art / "tests/task-1/tests/test_calc.py").write_text(
            "import unittest\nimport calc\n\n\nclass T(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(calc.add(1, 2), 3)\n\n\n"
            "if __name__ == '__main__':\n    unittest.main()\n", encoding="utf-8")
        self.ex = fbl.EXECUTORS["flash-next"]

    def tearDown(self):
        self._td.cleanup()

    def runner(self, dispatcher, health=lambda ex: 200):
        return fbl.TaskRunner(self.art, self.ex, dispatcher=dispatcher, health=health,
                              test_command="PYTHONPATH=. python3 -m unittest discover -s tests -q")

    def test_clean_task(self):
        d = FakeDispatcher(self.repo, edit=good_edit)
        results = self.runner(d).run([1])
        r = results[0]
        self.assertEqual(r.verdict, "CLEAN", r.checks)
        self.assertEqual(r.checks["TESTS"], "pass")
        self.assertEqual(d.real_calls, 1)
        metrics = (self.art / "executor-metrics.md").read_text(encoding="utf-8")
        self.assertIn("| Task 1 | 3 | 80 |", metrics)
        self.assertIn("success", metrics)
        line = fbl.format_result(r)
        self.assertIn("TASK=1", line)
        self.assertIn("VERDICT=CLEAN", line)
        self.assertEqual(line.count("\n"), 0)

    def test_red_that_already_passes_stops_before_dispatch(self):
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        d = FakeDispatcher(self.repo, edit=good_edit)
        r = self.runner(d).run([1])[0]
        self.assertEqual(r.stop, "RED_ALREADY_PASSES")
        self.assertEqual(d.real_calls, 0)

    def test_prompt_gate_blocks_dispatch(self):
        d = FakeDispatcher(self.repo, prompt_lines=141, edit=good_edit)
        r = self.runner(d).run([1])[0]
        self.assertEqual(r.stop, "GATE")
        self.assertEqual((d.dry_calls, d.real_calls), (1, 0))

    def test_spec_over_budget_stops_before_dry_run(self):
        (self.art / "tasks/task-1.md").write_text(
            "Add add()\nModify ONLY: calc.py\n" + "- step\n" * 20, encoding="utf-8")
        d = FakeDispatcher(self.repo, edit=good_edit)
        r = self.runner(d).run([1])[0]
        self.assertEqual(r.stop, "BUDGET")
        self.assertIn("spec>15", r.detail)
        self.assertEqual(d.dry_calls, 0)

    def test_health_down_stops(self):
        d = FakeDispatcher(self.repo, edit=good_edit)
        r = self.runner(d, health=lambda ex: 0).run([1])[0]
        self.assertEqual(r.stop, "PREFLIGHT")
        self.assertEqual(d.dry_calls, 0)

    def test_tampered_test_is_flagged(self):
        def edit(repo):
            good_edit(repo)
            (repo / "tests/test_calc.py").write_text(
                "import unittest\n\n\nclass T(unittest.TestCase):\n"
                "    def test_x(self):\n        self.assertTrue(True)\n", encoding="utf-8")
        r = self.runner(FakeDispatcher(self.repo, edit=edit)).run([1])[0]
        self.assertEqual(r.verdict, "FLAG")
        self.assertNotEqual(r.checks["TAMPER"], "none")

    def test_out_of_scope_file_foreign_script_and_skip_are_flagged(self):
        def edit(repo):
            (repo / "calc.py").write_text(
                "def add(a, b):\n    # چاپ\n    return a + b\n", encoding="utf-8")
            (repo / "other.py").write_text("@pytest.mark.skip\nX = 1\n", encoding="utf-8")
        r = self.runner(FakeDispatcher(self.repo, edit=edit)).run([1])[0]
        self.assertEqual(r.verdict, "FLAG")
        self.assertIn("other.py", r.checks["SCOPE"])
        self.assertIn("ARABIC", r.checks["SCRIPT"])
        self.assertNotEqual(r.checks["SKIPS"], "none")

    def test_failing_tests_give_fail_verdict(self):
        def edit(repo):
            (repo / "calc.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
        r = self.runner(FakeDispatcher(self.repo, edit=edit)).run([1])[0]
        self.assertEqual(r.verdict, "FAIL")
        self.assertEqual(r.checks["TESTS"], "fail")

    def test_timeout_is_classified_and_retry_budget_is_one(self):
        d = FakeDispatcher(self.repo, exit_code=124)
        run1 = self.runner(d).run([1])[0]
        self.assertEqual(run1.klass, "timeout")
        self.assertEqual(run1.verdict, "FAIL")
        fb = self.art / "feedback.txt"
        fb.write_text("tests failed: ...", encoding="utf-8")
        d2 = FakeDispatcher(self.repo, edit=good_edit)
        run2 = self.runner(d2).run([1], retry_feedback=fb.read_text(encoding="utf-8"))[0]
        self.assertEqual(run2.verdict, "CLEAN")
        self.assertEqual(d2.feedbacks, ["tests failed: ..."])
        run3 = self.runner(FakeDispatcher(self.repo, edit=good_edit)).run([1], retry_feedback="again")[0]
        self.assertEqual(run3.stop, "RETRY_BUDGET")

    def test_diff_and_status_use_batch_checkpoint(self):
        runner = self.runner(FakeDispatcher(self.repo, edit=good_edit))
        runner.run([1])
        text = fbl.batch_diff(self.art, max_lines=100)
        self.assertIn("## calc.py +2 -0", text)
        self.assertNotIn("test_calc.py", text)
        status = fbl.status_report(self.art)
        self.assertEqual(status["DONE"], "1")
        self.assertEqual(status["PENDING"], "-")
        self.assertEqual(status["LAST_VERDICT"], "CLEAN")


class WaitTest(unittest.TestCase):
    def test_wait_returns_tail_when_sentinel_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fbl-run.out"
            p.write_text("TASK=1 VERDICT=CLEAN\nFBL_DONE\n", encoding="utf-8")
            res = fbl.wait_for_done(p, max_seconds=2, poll=0.05)
            self.assertTrue(res["done"])
            self.assertIn("TASK=1", res["tail"])

    def test_wait_times_out(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fbl-run.out"
            p.write_text("running\n", encoding="utf-8")
            t0 = time.time()
            res = fbl.wait_for_done(p, max_seconds=0.3, poll=0.05)
            self.assertFalse(res["done"])
            self.assertLess(time.time() - t0, 2)


class CliTest(unittest.TestCase):
    def test_calibrate_cli_reads_every_metrics_file_in_repo(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for ts in ("20261001T000000Z", "20261002T000000Z"):
                d = repo / ".omx/artifacts/orchestrate" / ts
                d.mkdir(parents=True)
                rows = "".join(f"| Task {i} | 5 | 80 | 100s | 1 | success |\n" for i in range(6))
                (d / "executor-metrics.md").write_text(
                    "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 |\n|---|---|---|---|---|---|\n" + rows,
                    encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = fbl.main(["calibrate", "--repo", str(repo)])
            self.assertEqual(rc, 0)
            self.assertIn("N=12", buf.getvalue())
            self.assertIn("STREAK=12", buf.getvalue())
            self.assertIn("ADVICE=UP", buf.getvalue())

    def test_unknown_executor_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fbl.main(["preflight", "--executor", "nope"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
