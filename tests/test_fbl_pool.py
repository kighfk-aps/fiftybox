#!/usr/bin/env python3
"""Unit tests for the fiftybox-local lane pool (skills/fiftybox-local/scripts/fbl_task.py).

Same conventions as tests/test_fbl_task.py: only the Pi/orchestrate subprocess
boundary is replaced; git, the filesystem and every parser run for real.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/fiftybox-local/scripts/fbl_task.py"
ORCHESTRATE = ROOT / "skills/fiftybox-orchestration/scripts/orchestrate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fbl_task_pool", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fbl_task_pool"] = mod
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


# ---------- T1: parse_depends ----------

class ParseDependsTest(unittest.TestCase):
    def test_explicit_depends_list(self):
        self.assertEqual(fbl.parse_depends("Add x\nDepends: 1, 2\n- step\n", 3, [1, 2, 3]),
                         {1, 2})

    def test_depends_none_is_independent(self):
        self.assertEqual(fbl.parse_depends("Add x\nDepends: none\n- step\n", 1, [1, 2]), set())
        self.assertEqual(fbl.parse_depends("Add x\nDepends: NONE\n- step\n", 1, [1, 2]), set())

    def test_no_depends_line_means_sequential(self):
        self.assertEqual(fbl.parse_depends("Add x\nModify ONLY: a.py\n", 3, [1, 2, 3]), {1, 2})
        self.assertEqual(fbl.parse_depends("Add x\nModify ONLY: a.py\n", 1, [1, 2, 3]), set())

    def test_bold_depends_marker(self):
        self.assertEqual(fbl.parse_depends("Add x\n**Depends:** 4\n- step\n", 5, [4, 5]), {4})


# ---------- T2: task_paths ----------

class TaskPathsTest(unittest.TestCase):
    def test_owned_paths_plus_staged_test_files(self):
        with tempfile.TemporaryDirectory() as td:
            staged = Path(td) / "task-1"
            (staged / "tests").mkdir(parents=True)
            (staged / "tests/test_calc.py").write_text("assert 1\n", encoding="utf-8")
            (staged / "tests/__pycache__").mkdir()
            (staged / "tests/__pycache__/x.pyc").write_text("x", encoding="utf-8")
            spec = "Add add()\nModify ONLY: calc.py, ./src/u.py\n- add(a, b)\n"
            self.assertEqual(fbl.task_paths(spec, staged),
                             {"calc.py", "src/u.py", "tests/test_calc.py"})

    def test_missing_staged_dir_returns_owned_only(self):
        spec = "Add add()\nModify ONLY: calc.py\n- add(a, b)\n"
        self.assertEqual(fbl.task_paths(spec, Path("/nonexistent/staged")), {"calc.py"})


# ---------- T3: pick_task ----------

class PickTaskTest(unittest.TestCase):
    def test_skips_unmet_dependencies(self):
        self.assertEqual(fbl.pick_task([2, 3], {2: {1}, 3: set()}, set(), set(), {2: set(), 3: set()}), 3)

    def test_returns_earlier_task_once_dependency_done(self):
        self.assertEqual(fbl.pick_task([2, 3], {2: {1}, 3: set()}, {1}, set(), {2: set(), 3: set()}), 2)

    def test_returns_none_when_only_candidate_overlaps_busy_paths(self):
        self.assertIsNone(fbl.pick_task([2, 3], {2: {1}, 3: set()}, set(), {"a.py"},
                                        {2: set(), 3: {"a.py"}}))

    def test_returns_none_when_nothing_ready(self):
        self.assertIsNone(fbl.pick_task([2], {2: {1}}, set(), set(), {2: set()}))

    def test_does_not_modify_inputs(self):
        q, deps, done, busy, paths = [2, 3], {2: {1}, 3: set()}, set(), {"x"}, {2: set(), 3: set()}
        before = (list(q), {k: set(v) for k, v in deps.items()}, set(done), set(busy),
                  {k: set(v) for k, v in paths.items()})
        fbl.pick_task(q, deps, done, busy, paths)
        self.assertEqual((q, deps, done, busy, paths), before)


# ---------- T4: lane table and live lanes ----------

class LanePoolTableTest(unittest.TestCase):
    def test_there_is_no_fixed_pool_constant(self):
        self.assertFalse(hasattr(fbl, "LANE_POOL"))

    def test_gemma4_is_an_ordinary_studio_candidate(self):
        self.assertEqual(fbl.live_lanes(["gemma4"], lambda ex: 200), ["gemma4"])

    def test_live_lanes_ordered_by_pool_preference(self):
        got = fbl.live_lanes(["iq3s", "flash-next"], lambda ex: 200)
        self.assertEqual(got, ["flash-next", "iq3s"])

    def test_dead_lane_is_dropped(self):
        def health(ex):
            return 0 if ex.name == "iq3s" else 200
        self.assertEqual(fbl.live_lanes(["flash-next", "iq3s"], health), ["flash-next"])

    def test_all_down_gives_empty_list(self):
        self.assertEqual(fbl.live_lanes(["flash-next", "iq3s"], lambda ex: 0), [])

    def test_unknown_lane_raises(self):
        with self.assertRaises(ValueError):
            fbl.live_lanes(["nope"], lambda ex: 200)


# ---------- T5: LANE= / MOVED= in result lines ----------

class ResultLaneTest(unittest.TestCase):
    def test_clean_result_carries_lane_and_move(self):
        r = fbl.TaskResult(1, verdict="CLEAN", exit_code=0, klass="-", lane="iq3s",
                           moved="flash-next->iq3s")
        line = fbl.format_result(r)
        self.assertTrue(line.endswith("LANE=iq3s MOVED=flash-next->iq3s"), line)

    def test_no_lane_is_byte_identical(self):
        r = fbl.TaskResult(1, verdict="CLEAN", exit_code=0, klass="-")
        line = fbl.format_result(r)
        self.assertNotIn("LANE=", line)
        self.assertNotIn("MOVED=", line)
        self.assertTrue(line.endswith("PROMPT=0"), line)

    def test_stop_result_carries_lane(self):
        r = fbl.TaskResult(2, "STOP", stop="PREFLIGHT", detail="http 0", lane="iq3s")
        self.assertTrue(fbl.format_result(r).endswith("LANE=iq3s"))


# ---------- T6: lane column in metrics ----------

class MetricsLaneTest(unittest.TestCase):
    def test_no_lane_keeps_six_columns(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "executor-metrics.md"
            fbl.append_metrics(p, "Task 1", 9, 80, 120, 1, "success")
            fbl.append_metrics(p, "Task 2", 7, 81, 90, 2, "flagged")
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 |")
            self.assertEqual(lines[1], "|---|---|---|---|---|---|")
            self.assertEqual(lines[2], "| Task 1 | 9 | 80 | 120s | 1 | success |")
            self.assertEqual(len(lines), 4)

    def test_lane_writes_seventh_column(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "executor-metrics.md"
            fbl.append_metrics(p, "Task 1", 9, 80, 120, 1, "success", lane="iq3s")
            fbl.append_metrics(p, "Task 2", 7, 81, 90, 2, "moved", lane="flash-next")
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines[0].endswith("| lane |"), lines[0])
            self.assertEqual(lines[1], "|---|---|---|---|---|---|---|")
            self.assertTrue(lines[2].endswith("| success | iq3s |"), lines[2])
            self.assertTrue(lines[3].endswith("| moved | flash-next |"), lines[3])

    def test_parse_metrics_reads_lane_and_defaults_old_rows(self):
        text = (
            "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 | lane |\n"
            "|---|---|---|---|---|---|---|\n"
            "| Task 1 | 5 | 80 | 10s | 1 | success | iq3s |\n"
            "| Task 2 | 5 | 80 | 10s | 1 | success |\n"
        )
        rows = fbl.parse_metrics(text)
        self.assertEqual([r["lane"] for r in rows], ["iq3s", "flash-next"])


# ---------- T6b: per-lane calibrate ----------

class CalibrateByLaneTest(unittest.TestCase):
    def test_rows_are_grouped_by_lane(self):
        rows = ([{"result": "success", "lane": "flash-next"}] * 10
                + [{"result": "success", "lane": "iq3s"}] * 3
                + [{"result": "failed", "lane": "iq3s"}] * 2)
        by = fbl.calibrate_by_lane(rows)
        self.assertEqual(by["flash-next"]["advice"], "UP")
        self.assertEqual(by["flash-next"]["n"], 10)
        self.assertEqual(by["iq3s"]["advice"], "DOWN")
        self.assertEqual(by["iq3s"]["n"], 5)

    def test_moved_rows_are_excluded(self):
        rows = ([{"result": "success", "lane": "iq3s"}] * 10
                + [{"result": "moved — server", "lane": "iq3s"}])
        self.assertEqual(fbl.calibrate_by_lane(rows)["iq3s"]["n"], 10)
        self.assertEqual(fbl.calibrate_by_lane(rows)["iq3s"]["streak"], 10)

    def test_old_rows_default_to_flash_next(self):
        self.assertEqual(fbl.calibrate_by_lane([{"result": "success"}] * 10)
                         ["flash-next"]["advice"], "UP")

    def test_calibrate_cli_prints_one_line_per_lane(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            d = repo / ".omx/artifacts/orchestrate" / "20261001T000000Z"
            d.mkdir(parents=True)
            rows = "".join(
                f"| Task {i} | 5 | 80 | 100s | 1 | success | {lane} |\n"
                for lane in ("flash-next", "iq3s") for i in range(10))
            (d / "executor-metrics.md").write_text(
                "| task | spec 줄수 | prompt 줄수 | duration | changedFiles | 결과 | lane |\n"
                "|---|---|---|---|---|---|---|\n" + rows, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = fbl.main(["calibrate", "--repo", str(repo)])
            self.assertEqual(rc, 0)
            self.assertIn("LANE=flash-next N=10", buf.getvalue())
            self.assertIn("LANE=iq3s N=10", buf.getvalue())
            self.assertIn("ADVICE=UP", buf.getvalue())


# ---------- T7: LANE_HEALTH_LOST classifies as server ----------

class LaneHealthLostTest(unittest.TestCase):
    def test_lane_health_lost_is_server(self):
        self.assertEqual(fbl.classify_failure("watchdog: LANE_HEALTH_LOST\n", 1, False), "server")

    def test_empty_log_with_124_still_timeout(self):
        self.assertEqual(fbl.classify_failure("", 124, False), "timeout")


# ---------- T9: lane worktrees ----------

class LaneWorktreeTest(unittest.TestCase):
    def test_create_then_remove_lane_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            lane = Path(td) / "lane"
            fbl.create_lane_worktree(repo, lane)
            self.assertTrue((lane / "README.md").is_file())
            self.assertIn("lane", git(repo, "worktree", "list"))
            self.assertTrue(fbl.remove_lane_worktree(repo, lane))
            self.assertFalse(lane.exists())

    def test_create_reuses_existing_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            lane = Path(td) / "lane"
            fbl.create_lane_worktree(repo, lane)
            (lane / "marker.txt").write_text("keep\n", encoding="utf-8")
            fbl.create_lane_worktree(repo, lane)  # second create must not fail or reset
            self.assertEqual((lane / "marker.txt").read_text(encoding="utf-8"), "keep\n")

    def test_symlinks_for_shared_dependency_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            (repo / "node_modules").mkdir()
            (repo / "node_modules" / "dep.js").write_text("x\n", encoding="utf-8")
            lane = Path(td) / "lane"
            fbl.create_lane_worktree(repo, lane)
            self.assertTrue((lane / "node_modules").is_symlink())
            self.assertTrue((lane / "node_modules" / "dep.js").is_file())

    def test_remove_missing_worktree_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            self.assertFalse(fbl.remove_lane_worktree(repo, Path(td) / "never-existed"))


# ---------- T9b: sync lane worktree ----------

class SyncLaneTest(unittest.TestCase):
    def test_lane_matches_main_uncommitted_and_untracked_state(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = make_repo(td)
            (repo / "calc.py").write_text("v1\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "calc")
            (repo / "calc.py").write_text("v2\n", encoding="utf-8")      # uncommitted edit
            (repo / "new.py").write_text("new\n", encoding="utf-8")      # untracked
            lane = td / "lane"
            fbl.create_lane_worktree(repo, lane)
            (lane / "junk.py").write_text("junk\n", encoding="utf-8")    # stray file
            tree = fbl.sync_lane(lane, repo, td / "idx-sync")
            self.assertEqual((lane / "calc.py").read_text(encoding="utf-8"), "v2\n")
            self.assertTrue((lane / "new.py").is_file())
            self.assertFalse((lane / "junk.py").exists())
            self.assertEqual(fbl.snapshot_tree(lane, td / "idx-check"), tree)


# ---------- T10: overlay owned files from a tree ----------

class OverlayPathsTest(unittest.TestCase):
    def test_overlays_existing_paths_and_skips_missing(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            (repo / "calc.py").write_text("v2\n", encoding="utf-8")
            tree = fbl.snapshot_tree(repo, Path(td) / "idx")
            (repo / "calc.py").write_text("v1\n", encoding="utf-8")
            done = fbl.overlay_paths(repo, tree, {"calc.py", "nope.py"})
            self.assertEqual(done, ["calc.py"])
            self.assertEqual((repo / "calc.py").read_text(encoding="utf-8"), "v2\n")


# ---------- T11: merge paths into the main worktree ----------

class MergePathsTest(unittest.TestCase):
    def test_copies_new_files_and_deletes_removed_ones(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "src", Path(td) / "dst"
            src.mkdir()
            dst.mkdir()
            (src / "a.py").write_text("a\n", encoding="utf-8")
            (dst / "b.py").write_text("b\n", encoding="utf-8")
            (dst / "c.py").write_text("c\n", encoding="utf-8")
            touched = fbl.merge_paths(src, dst, {"a.py", "b.py"})
            self.assertEqual(touched, ["a.py", "b.py"])
            self.assertEqual((dst / "a.py").read_text(encoding="utf-8"), "a\n")
            self.assertFalse((dst / "b.py").exists())
            self.assertEqual((dst / "c.py").read_text(encoding="utf-8"), "c\n")

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "src", Path(td) / "dst"
            src.mkdir()
            dst.mkdir()
            (src / "pkg" / "a.py").parent.mkdir(parents=True)
            (src / "pkg" / "a.py").write_text("a\n", encoding="utf-8")
            fbl.merge_paths(src, dst, {"pkg/a.py"})
            self.assertTrue((dst / "pkg" / "a.py").is_file())


# ---------- T12: lane artifact directory ----------

class MakeLaneDirTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.repo = make_repo(self.td)
        self.art = self.td / "art"
        self.art.mkdir()
        (self.art / "summary.json").write_text(
            json.dumps({"worktree": str(self.repo), "taskDescription": "fix the thing"}),
            encoding="utf-8")
        (self.art / "design.md").write_text("design\n" * 5, encoding="utf-8")
        (self.art / "intent-summary.md").write_text("intent\n" * 3, encoding="utf-8")
        self.lane_wt = self.td / "lane"
        fbl.create_lane_worktree(self.repo, self.lane_wt)

    def tearDown(self):
        self._td.cleanup()

    def test_lane_dir_summary_json_points_at_lane_worktree(self):
        d = fbl.make_lane_dir(self.art, "iq3s", self.lane_wt)
        self.assertEqual(d, self.art / "lanes" / "iq3s")
        summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["worktree"], str(self.lane_wt))
        self.assertEqual(summary["taskDescription"], "fix the thing")
        self.assertEqual(summary["phases"]["setup"]["status"], "success")
        self.assertEqual(summary["files"], {})
        self.assertEqual((d / "design.md").read_text(encoding="utf-8"), "design\n" * 5)
        self.assertFalse((d / "task-batches.md").exists())

    def test_real_orchestrate_dry_run_works_in_lane_worktree(self):
        d = fbl.make_lane_dir(self.art, "iq3s", self.lane_wt)
        cmd = ["python3", str(ORCHESTRATE), "--phase", "implement", "--task", "do it",
               "--cwd", str(self.repo), "--artifact-dir", str(d),
               "--implement-agent", "pi", "--provider", "ioh",
               "--model", "qwen3.8-flash-next-iq3_s", "--implementation-timeout", "1800",
               "--skip-verify", "--dry-run"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("dry_run", res.stdout)
        prompt = (d / "implement-prompt.md").read_text(encoding="utf-8")
        self.assertIn(f"Working directory: {self.lane_wt}", prompt)


# ---------- T8: health watchdog in the dispatcher ----------

class SleepDispatcher(fbl.OrchestrateDispatcher):
    def _cmd(self, task_text, artifact_dir, ex, extra):
        return [sys.executable, "-c", "import time; time.sleep(30)"]


class WatchdogTest(unittest.TestCase):
    def test_dead_lane_kills_child_and_classifies_server(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "task.out"
            d = SleepDispatcher(health=lambda: 0, interval=0.1, misses=2)
            t0 = time.time()
            code = d.implement("task", td, fbl.EXECUTORS["iq3s"], out)
            self.assertLess(time.time() - t0, 5)
            self.assertEqual(code, 1)
            text = out.read_text(encoding="utf-8")
            self.assertIn("LANE_HEALTH_LOST", text)
            self.assertIn("EXIT_CODE=1", text)
            self.assertEqual(fbl.classify_failure(text, 1, False), "server")

    def test_healthy_lane_lets_child_finish(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "task.out"

            class QuickDispatcher(SleepDispatcher):
                def _cmd(self, task_text, artifact_dir, ex, extra):
                    return [sys.executable, "-c", "print('done')"]

            d = QuickDispatcher(health=lambda: 200, interval=0.05, misses=1)
            code = d.implement("task", td, fbl.EXECUTORS["iq3s"], out)
            self.assertEqual(code, 0)
            self.assertIn("done", out.read_text(encoding="utf-8"))
            self.assertIn("EXIT_CODE=0", out.read_text(encoding="utf-8"))

    def test_default_dispatcher_has_no_watchdog(self):
        self.assertIsNone(fbl.OrchestrateDispatcher().health)
        d = fbl.OrchestrateDispatcher(health=lambda: 0)
        self.assertEqual((d.interval, d.misses), (60, 3))


# ---------- T13/T13b: lane parameters and race-safe state ----------

class LaneFakeDispatcher:
    """Stands in for orchestrate.py; edits the worktree named in artifact_dir."""

    def __init__(self, *, exit_code: int = 0, prompt_lines: int = 80, edit=None, hook=None,
                 sleep=0.0, log_tail="log"):
        self.exit_code, self.prompt_lines, self.edit = exit_code, prompt_lines, edit
        self.hook, self.sleep, self.log_tail = hook, sleep, log_tail
        self.calls: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def _worktree(self, artifact_dir) -> Path:
        return Path(json.loads((Path(artifact_dir) / "summary.json").read_text(encoding="utf-8"))["worktree"])

    def dry_run(self, task_text, artifact_dir, executor, *, retry_feedback=None):
        p = Path(artifact_dir) / ("implement-prompt-retry.md" if retry_feedback else "implement-prompt.md")
        p.write_text("line\n" * self.prompt_lines, encoding="utf-8")
        return p

    def implement(self, task_text, artifact_dir, executor, out_path, *, retry_feedback=None):
        wt = self._worktree(artifact_dir)
        with self.lock:
            self.calls.append((executor.name, task_text.splitlines()[0]))
        if self.sleep:
            time.sleep(self.sleep)
        code = self.exit_code
        if self.edit:
            self.edit(wt)
        if self.hook is not None:
            hook_code = self.hook(wt, task_text, executor)
            if hook_code is not None:
                code = hook_code
        Path(out_path).write_text(f"{self.log_tail}\nEXIT_CODE={code}\n", encoding="utf-8")
        return code


class LaneRunnerBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.repo = make_repo(self.td)
        self.art = self.td / "art"
        (self.art / "tasks").mkdir(parents=True)
        (self.art / "summary.json").write_text(
            json.dumps({"worktree": str(self.repo), "taskDescription": "t"}), encoding="utf-8")
        (self.art / "design.md").write_text("design\n" * 5, encoding="utf-8")
        self.ex = fbl.EXECUTORS["flash-next"]

    def tearDown(self):
        self._td.cleanup()

    def add_task(self, tid: int, filename: str):
        (self.art / "tasks" / f"task-{tid}.md").write_text(
            f"Add calc{tid}()\nModify ONLY: {filename}\nDepends: none\n- add returns sum\n",
            encoding="utf-8")
        staged = self.art / "tests" / f"task-{tid}" / "tests"
        staged.mkdir(parents=True)
        (staged / f"test_{tid}.py").write_text(
            f"import unittest\nimport {filename[:-3]}\n\n\nclass T(unittest.TestCase):\n"
            f"    def test_add(self):\n        self.assertEqual({filename[:-3]}.add(1, 2), 3)\n\n\n"
            "if __name__ == '__main__':\n    unittest.main()\n", encoding="utf-8")

    def make_lane(self, lane: str):
        lane_wt = self.td / f"lane-{lane}"
        fbl.create_lane_worktree(self.repo, lane_wt)
        lane_dir = fbl.make_lane_dir(self.art, lane, lane_wt)
        return lane_wt, lane_dir

    TEST_CMD = "PYTHONPATH=. python3 -m unittest discover -s tests -q"


class LaneRunnerTest(LaneRunnerBase):
    def test_lane_runner_writes_lane_outputs(self):
        self.add_task(1, "calc.py")
        lane_wt, lane_dir = self.make_lane("iq3s")

        def edit(wt):
            (wt / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        d = LaneFakeDispatcher(edit=edit)
        runner = fbl.TaskRunner(self.art, fbl.EXECUTORS["iq3s"], dispatcher=d,
                                health=lambda ex: 200, test_command=self.TEST_CMD,
                                worktree=lane_wt, dispatch_dir=lane_dir, lane="iq3s")
        r = runner.run([1])[0]
        self.assertEqual(r.verdict, "CLEAN", r.checks)
        self.assertEqual(r.lane, "iq3s")
        self.assertIn("LANE=iq3s", fbl.format_result(r))
        self.assertTrue((lane_dir / "implement-task-1-iq3s.out").exists())
        self.assertFalse((self.art / "implement-task-1.out").exists())
        metrics = (self.art / "executor-metrics.md").read_text(encoding="utf-8")
        self.assertTrue(metrics.splitlines()[-1].endswith("| iq3s |"), metrics)
        # the lane worktree got the edit; the main worktree did not
        self.assertTrue((lane_wt / "calc.py").exists())
        self.assertFalse((self.repo / "calc.py").exists())
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["1"]["lane"], "iq3s")

    def test_state_survives_two_concurrent_lane_runners(self):
        self.add_task(1, "calc1.py")
        self.add_task(2, "calc2.py")
        runners = []
        for lane, fname in (("flash-next", "calc1.py"), ("iq3s", "calc2.py")):
            lane_wt, lane_dir = self.make_lane(lane)

            def edit(wt, fname=fname):
                (wt / fname).write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            runners.append(fbl.TaskRunner(self.art, fbl.EXECUTORS[lane],
                                dispatcher=LaneFakeDispatcher(edit=edit),
                                health=lambda ex: 200, test_command=self.TEST_CMD,
                                worktree=lane_wt, dispatch_dir=lane_dir, lane=lane,
                                count_server_attempts=False))
        threads = [threading.Thread(target=r._run_one, args=(tid, None))
                   for tid, r in zip((1, 2), runners)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        for tid in ("1", "2"):
            self.assertEqual(state["tasks"][tid]["verdict"], "CLEAN")
            self.assertIn(tid, state["pre"])
            self.assertIn(tid, state["post"])
        metrics = (self.art / "executor-metrics.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([l for l in metrics if l.startswith("| Task")]), 2)

    def test_server_failure_with_flag_off_keeps_attempts_and_writes_moved(self):
        self.add_task(1, "calc.py")
        lane_wt, lane_dir = self.make_lane("iq3s")
        d = LaneFakeDispatcher(exit_code=1, log_tail="curl: Connection refused",
                               edit=lambda wt: (wt / "calc.py").write_text("half\n", encoding="utf-8"))
        runner = fbl.TaskRunner(self.art, fbl.EXECUTORS["iq3s"], dispatcher=d,
                                health=lambda ex: 200, test_command=self.TEST_CMD,
                                worktree=lane_wt, dispatch_dir=lane_dir, lane="iq3s",
                                count_server_attempts=False)
        r = runner._run_one(1, None)
        self.assertEqual(r.klass, "server")
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["1"]["attempts"], 0)
        metrics = (self.art / "executor-metrics.md").read_text(encoding="utf-8")
        self.assertIn("moved", metrics)

    def test_server_failure_with_flag_on_counts_attempt(self):
        self.add_task(1, "calc.py")
        lane_wt, lane_dir = self.make_lane("iq3s")
        d = LaneFakeDispatcher(exit_code=1, log_tail="curl: Connection refused")
        runner = fbl.TaskRunner(self.art, fbl.EXECUTORS["iq3s"], dispatcher=d,
                                health=lambda ex: 200, test_command=self.TEST_CMD,
                                worktree=lane_wt, dispatch_dir=lane_dir, lane="iq3s")
        runner._run_one(1, None)
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["1"]["attempts"], 1)


# ---------- T14-T17: LanePool ----------

GOOD = "def add(a, b):\n    return a + b\n"


def spec_file(task_text: str) -> str:
    m = re.search(r"Modify ONLY: (\S+)", task_text)
    return m.group(1) if m else "?"


class PoolBase(LaneRunnerBase):
    """Artifact dir + repo with N independent tasks ready to run."""

    def factory(self, hook, log_tail):
        return lambda ex: LaneFakeDispatcher(hook=hook, log_tail=log_tail)

    def pool(self, lanes, hook, health=lambda ex: 200, log_tail="log"):
        return fbl.LanePool(self.art, lanes, dispatcher_factory=self.factory(hook, log_tail),
                            health=health, test_command=self.TEST_CMD)

    def good_hook(self, sleep=0.0):
        timings = {}

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            t0 = time.time()
            if sleep:
                time.sleep(sleep)
            (wt / fname).write_text(GOOD, encoding="utf-8")
            timings[fname] = (t0, time.time())
            return 0

        return hook, timings


class LanePoolHappyPathTest(PoolBase):
    def test_four_independent_tasks_use_both_lanes_concurrently(self):
        for tid in range(1, 5):
            self.add_task(tid, f"calc{tid}.py")
        hook, timings = self.good_hook(sleep=0.5)
        pool = self.pool(["flash-next", "iq3s"], hook)
        t0 = time.time()
        results = pool.run([1, 2, 3, 4])
        elapsed = time.time() - t0
        self.assertEqual([r.verdict for r in results], ["CLEAN"] * 4, [fbl.format_result(r) for r in results])
        self.assertEqual({r.lane for r in results}, {"flash-next", "iq3s"})
        self.assertLess(elapsed, 1.6, f"pool took {elapsed:.2f}s; sequential would be >2s")
        for tid in range(1, 5):
            self.assertEqual((self.repo / f"calc{tid}.py").read_text(encoding="utf-8"), GOOD)
        leftovers = list((self.repo / ".worktrees").glob("fbl-*")) \
            if (self.repo / ".worktrees").exists() else []
        self.assertEqual(leftovers, [])


class LanePoolMovesTest(PoolBase):
    def test_dead_ioh_mid_task_moves_task_to_studio(self):
        self.add_task(1, "calc1.py")
        self.add_task(2, "calc2.py")

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            if ex.name == "iq3s":
                time.sleep(0.3)
                (wt / fname).write_text("half-broken\n", encoding="utf-8")
                return 1  # log_tail says Connection refused → server
            time.sleep(0.1)
            (wt / fname).write_text(GOOD, encoding="utf-8")
            return 0

        pool = self.pool(["flash-next", "iq3s"], hook, log_tail="curl: Connection refused")
        results = pool.run([1, 2])
        by_task = {r.task: r for r in results}
        self.assertEqual(by_task[2].verdict, "CLEAN", fbl.format_result(by_task[2]))
        self.assertEqual(by_task[2].moved, "iq3s->flash-next")
        self.assertIn("MOVED=iq3s->flash-next", fbl.format_result(by_task[2]))
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["2"]["attempts"], 1)  # the move spent no retry
        self.assertEqual((self.repo / "calc2.py").read_text(encoding="utf-8"), GOOD)
        metrics = (self.art / "executor-metrics.md").read_text(encoding="utf-8")
        self.assertIn("moved", metrics)

    def test_moved_task_waits_for_busy_studio(self):
        self.add_task(1, "calc1.py")  # long task on the studio
        self.add_task(2, "calc2.py")  # ioh dies immediately
        timings = {}

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            if ex.name == "iq3s":
                (wt / fname).write_text("half\n", encoding="utf-8")
                return 1
            t0 = time.time()
            time.sleep(1.0 if fname == "calc1.py" else 0.1)
            (wt / fname).write_text(GOOD, encoding="utf-8")
            timings[fname] = (t0, time.time())
            return 0

        pool = self.pool(["flash-next", "iq3s"], hook, log_tail="curl: Connection refused")
        results = pool.run([1, 2])
        by_task = {r.task: r for r in results}
        self.assertEqual(by_task[1].verdict, "CLEAN")
        self.assertEqual(by_task[2].verdict, "CLEAN")
        self.assertEqual(by_task[2].moved, "iq3s->flash-next")
        # the moved task started on the studio only after the running task ended
        self.assertGreaterEqual(timings["calc2.py"][0], timings["calc1.py"][1])

    def test_both_lanes_die_reports_all_lanes_down(self):
        self.add_task(1, "calc1.py")
        self.add_task(2, "calc2.py")

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            (wt / fname).write_text("half\n", encoding="utf-8")
            return 1

        pool = self.pool(["flash-next", "iq3s"], hook, log_tail="curl: Connection refused")
        results = pool.run([1, 2])
        self.assertEqual([r.stop for r in results], ["ALL_LANES_DOWN", "ALL_LANES_DOWN"])
        cp = (self.art / ".fbl" / "checkpoint").read_text(encoding="utf-8").strip()
        now = fbl.snapshot_tree(self.repo, self.art / ".fbl" / "idx-after")
        self.assertEqual(now, cp)  # nothing from the dead lanes reached the main worktree

    def test_second_server_failure_after_one_move_is_move_budget(self):
        self.add_task(1, "calc1.py")

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            (wt / fname).write_text("half\n", encoding="utf-8")
            return 1

        pool = self.pool(["flash-next", "iq3s"], hook, log_tail="curl: Connection refused")
        results = pool.run([1])
        self.assertEqual(results[-1].stop, "MOVE_BUDGET")

    def test_lane_dead_before_dispatch_does_not_count_as_move(self):
        self.add_task(1, "calc1.py")
        self.add_task(2, "calc2.py")
        hook, _ = self.good_hook()
        healths = {"flash-next": 200, "iq3s": 200}

        def health(ex):
            return healths[ex.name]

        healths["iq3s"] = 0  # ioh answers nothing from the very start
        pool = self.pool(["flash-next", "iq3s"], hook, health=health)
        results = pool.run([1, 2])
        self.assertEqual([r.verdict for r in results], ["CLEAN", "CLEAN"])
        self.assertIsNone(results[0].moved)
        self.assertIsNone(results[1].moved)


class LanePoolDisciplineTest(PoolBase):
    def intervals_overlap(self, a, b):
        return a[0] < b[1] and b[0] < a[1]

    def test_tasks_without_depends_line_never_overlap(self):
        for tid in range(1, 5):
            self.add_task(tid, f"calc{tid}.py")
            spec = (self.art / "tasks" / f"task-{tid}.md").read_text(encoding="utf-8")
            spec = spec.replace("Depends: none\n", "")
            (self.art / "tasks" / f"task-{tid}.md").write_text(spec, encoding="utf-8")
        hook, timings = self.good_hook(sleep=0.2)
        pool = self.pool(["flash-next", "iq3s"], hook)
        results = pool.run([1, 2, 3, 4])
        self.assertEqual([r.verdict for r in results], ["CLEAN"] * 4)
        marks = [timings[f"calc{tid}.py"] for tid in range(1, 5)]
        for i in range(len(marks)):
            for j in range(i + 1, len(marks)):
                self.assertFalse(self.intervals_overlap(marks[i], marks[j]),
                                 f"tasks {i + 1} and {j + 1} overlapped")

    def test_overlapping_test_paths_never_overlap(self):
        self.add_task(1, "calc1.py")
        self.add_task(2, "calc2.py")
        # both tasks stage a test at the same path — they must serialize
        for tid in (1, 2):
            staged = self.art / "tests" / f"task-{tid}" / "tests"
            (staged / "test_x.py").write_text(
                f"import unittest\nimport calc{tid}\n\n\nclass T(unittest.TestCase):\n"
                f"    def test_add(self):\n        self.assertEqual(calc{tid}.add(1, 2), 3)\n", encoding="utf-8")
        hook, timings = self.good_hook(sleep=0.2)
        pool = self.pool(["flash-next", "iq3s"], hook)
        results = pool.run([1, 2])
        self.assertEqual([r.verdict for r in results], ["CLEAN", "CLEAN"])
        self.assertFalse(self.intervals_overlap(timings["calc1.py"], timings["calc2.py"]))

    def test_external_dependency_not_clean_stops_before_dispatch(self):
        self.add_task(1, "calc1.py")
        (self.art / "tasks" / "task-1.md").write_text(
            "Add calc1()\nModify ONLY: calc1.py\nDepends: 5\n- add returns sum\n", encoding="utf-8")
        (self.art / ".fbl").mkdir(exist_ok=True)
        (self.art / ".fbl" / "state.json").write_text(
            json.dumps({"tasks": {"5": {"verdict": "FAIL", "klass": "-", "attempts": 1}}, "pre": {}}),
            encoding="utf-8")
        calls = []

        def hook(wt, task_text, ex):
            calls.append(spec_file(task_text))
            return 0

        pool = self.pool(["flash-next", "iq3s"], hook)
        results = pool.run([1])
        self.assertEqual(results[0].stop, "DEPENDS")
        self.assertEqual(calls, [])

    def test_first_failure_stops_new_assignments(self):
        for tid in (1, 2, 3):
            self.add_task(tid, f"calc{tid}.py")
        calls = []

        def hook(wt, task_text, ex):
            fname = spec_file(task_text)
            calls.append(fname)
            if fname == "calc1.py":
                (wt / fname).write_text("def add(a, b):\n    return 99\n", encoding="utf-8")
                return 0  # tests will fail → FAIL verdict
            (wt / fname).write_text(GOOD, encoding="utf-8")
            return 0

        pool = self.pool(["flash-next", "iq3s"], hook)
        results = pool.run([1, 2, 3])
        self.assertIn("FAIL", [r.verdict for r in results])
        self.assertNotIn("calc3.py", calls)  # queued task 3 was never dispatched


class LanePoolRetryTest(PoolBase):
    def test_retry_resyncs_then_overlays_owned_files_from_last_post(self):
        self.add_task(1, "calc.py")
        lane_wt, lane_dir = self.make_lane("iq3s")
        seen = {}

        def broken_edit(wt):
            (wt / "calc.py").write_text("def add(a, b):\n    return 99\n", encoding="utf-8")

        # attempt 1 on iq3s: dispatch exits 0 but the edit breaks the tests → FAIL
        attempt1 = fbl.TaskRunner(
            self.art, fbl.EXECUTORS["iq3s"],
            dispatcher=LaneFakeDispatcher(edit=broken_edit), health=lambda ex: 200,
            test_command=self.TEST_CMD, worktree=lane_wt, dispatch_dir=lane_dir,
            lane="iq3s", count_server_attempts=False)
        r1 = attempt1._run_one(1, None)
        self.assertEqual(r1.verdict, "FAIL")
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["1"]["attempts"], 1)
        self.assertIn("1", state["post"])

        def retry_hook(wt, task_text, ex):
            seen[ex.name] = (wt / "calc.py").read_text(encoding="utf-8")  # what the model sees
            (wt / "calc.py").write_text(GOOD, encoding="utf-8")
            return 0

        pool = fbl.LanePool(self.art, ["flash-next"],
                            dispatcher_factory=lambda ex: LaneFakeDispatcher(hook=retry_hook),
                            health=lambda ex: 200, test_command=self.TEST_CMD)
        results = pool.run([1], retry_feedback="tests failed: add is wrong")
        self.assertEqual(results[0].verdict, "CLEAN", fbl.format_result(results[0]))
        # the retry started from the failed attempt's recorded post (broken edit kept)
        self.assertEqual(seen["flash-next"], "def add(a, b):\n    return 99\n")
        self.assertEqual((self.repo / "calc.py").read_text(encoding="utf-8"), GOOD)
        state = json.loads((self.art / ".fbl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["tasks"]["1"]["attempts"], 2)

    def test_retry_budget_still_applies_in_pool(self):
        self.add_task(1, "calc.py")
        (self.art / ".fbl").mkdir(exist_ok=True)
        (self.art / ".fbl" / "state.json").write_text(
            json.dumps({"tasks": {"1": {"verdict": "FAIL", "klass": "timeout", "attempts": 2}},
                        "pre": {}, "post": {}}), encoding="utf-8")
        calls = []

        def hook(wt, task_text, ex):
            calls.append(1)
            return 0

        pool = self.pool(["flash-next"], hook)
        results = pool.run([1], retry_feedback="again")
        self.assertEqual(results[0].stop, "RETRY_BUDGET")
        self.assertEqual(calls, [])


# ---------- T18: mode selection ----------

class SelectModeTest(unittest.TestCase):
    @staticmethod
    def health_for(codes):
        return lambda ex: codes.get(ex.name, 0)

    def test_explicit_executor_forces_single_without_health_check(self):
        def boom(ex):
            raise AssertionError("health must not be consulted for explicit executors")
        self.assertEqual(fbl.select_mode(None, "iq3s", boom, {}, [1]), ("single", ["iq3s"]))
        self.assertEqual(fbl.select_mode(None, "gemma4", boom, {}, [1]), ("single", ["gemma4"]))

    def test_no_live_lanes_is_down(self):
        self.assertEqual(fbl.select_mode(None, None, lambda ex: 0, {}, [1]), ("down", []))

    def test_two_live_lanes_use_the_pool(self):
        self.assertEqual(fbl.select_mode(None, None, lambda ex: 200, {}, [1, 2]),
                         ("pool", ["flash-next", "iq3s"]))
        self.assertEqual(fbl.select_mode("iq3s,flash-next", None, lambda ex: 200, {}, [1, 2]),
                         ("pool", ["flash-next", "iq3s"]))

    def test_one_live_lane_without_recorded_lane_is_single(self):
        self.assertEqual(fbl.select_mode(None, None, self.health_for({"flash-next": 200}), {}, [1]),
                         ("single", ["flash-next"]))
        self.assertEqual(fbl.select_mode(None, None, self.health_for({"iq3s": 200}), {}, [1]),
                         ("single", ["iq3s"]))

    def test_one_live_lane_with_recorded_lane_stays_in_pool(self):
        state = {"tasks": {"1": {"verdict": "FAIL", "klass": "server", "attempts": 0,
                                "lane": "flash-next"}}}
        self.assertEqual(fbl.select_mode(None, None, self.health_for({"iq3s": 200}), state, [1]),
                         ("pool", ["iq3s"]))

    def test_lanes_flag_limits_the_pool(self):
        self.assertEqual(fbl.select_mode("flash-next", None, lambda ex: 200, {}, [1]),
                         ("single", ["flash-next"]))

    def test_run_rejects_unknown_executor(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fbl.main(["run", "--executor", "nope", "--artifact-dir", "x", "--tasks", "1"])


# ---------- T19: preflight over the pool ----------

class PreflightPoolTest(unittest.TestCase):
    def setUp(self):
        self._health, self._warm, self._probe = fbl.executor_health, fbl.warm_up, fbl.probe_lanes
        self._models, self._paths = fbl.executor_models, (fbl.PI_MODELS_PATH, fbl.CONFIG_PATH)
        self._td = tempfile.TemporaryDirectory()
        # missing files: no registry/config filtering, and never the real ~/.pi or ~/.claude
        fbl.PI_MODELS_PATH = Path(self._td.name) / "pi.json"
        fbl.CONFIG_PATH = Path(self._td.name) / "config.json"
        fbl.executor_models = lambda ex: [ex.model]

    def tearDown(self):
        fbl.executor_health, fbl.warm_up, fbl.probe_lanes = self._health, self._warm, self._probe
        fbl.executor_models = self._models
        fbl.PI_MODELS_PATH, fbl.CONFIG_PATH = self._paths
        self._td.cleanup()

    def run_main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fbl.main(list(argv))
        return rc, buf.getvalue()

    def test_one_live_lane_is_ok_without_studio(self):
        fbl.executor_health = lambda ex: 200 if ex.name == "iq3s" else 0
        fbl.warm_up = lambda ex: 200
        fbl.probe_lanes = lambda: "none"
        rc, out = self.run_main("preflight")
        self.assertEqual(rc, 0)
        self.assertIn("LANE=flash-next HEALTH=0", out)
        self.assertIn("LANE=iq3s HEALTH=200", out)
        self.assertIn("WARM=iq3s:ok", out)
        self.assertIn("LANES_UP=iq3s", out)
        self.assertIn("PREFLIGHT=ok", out)

    def test_both_lanes_up_warms_each_once(self):
        with tempfile.TemporaryDirectory() as td:
            warmed = []
            fbl.executor_health = lambda ex: 200
            fbl.warm_up = lambda ex: warmed.append(ex.name) or 200
            rc, out = self.run_main("preflight", "--artifact-dir", td)
            self.assertEqual(rc, 0)
            self.assertEqual(warmed, ["flash-next", "iq3s"])
            self.assertIn("LANES_UP=flash-next,iq3s", out)
            self.assertTrue((Path(td) / ".fbl" / "warmed").exists())
            self.assertTrue((Path(td) / ".fbl" / "warmed-iq3s").exists())
            # second preflight in the same artifact dir warms nothing
            warmed.clear()
            rc, out = self.run_main("preflight", "--artifact-dir", td)
            self.assertEqual(rc, 0)
            self.assertEqual(warmed, [])

    def test_all_lanes_down_keeps_today_output(self):
        fbl.executor_health = lambda ex: 0
        fbl.probe_lanes = lambda: "none"
        rc, out = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("LANES=none", out)
        self.assertIn("PREFLIGHT=down (start procedure: reference.md)", out)

    def test_explicit_executor_output_is_unchanged(self):
        fbl.executor_health = lambda ex: 200
        fbl.warm_up = lambda ex: 200
        rc, out = self.run_main("preflight", "--executor", "gemma4")
        self.assertEqual(rc, 0)
        self.assertIn("EXECUTOR=gemma4 HEALTH=200", out)
        self.assertIn("PREFLIGHT=ok", out)
        self.assertNotIn("LANES_UP=", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
