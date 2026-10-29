#!/usr/bin/env python3
"""Unit tests for the served-model lanes of skills/fiftybox-local/scripts/fbl_task.py.

Candidate table, eligibility (table + Pi registry + fiftybox-config), served
detection and the one-lane-per-PC pick. Only the network/subprocess boundary is
replaced; the parsers and selection logic run for real.
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
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/fiftybox-local/scripts/fbl_task.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fbl_task_served", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fbl_task_served"] = mod
    spec.loader.exec_module(mod)
    return mod


fbl = load_module()

STUDIO = ["flash-next", "qwen27b-mlx4", "qwen27b-8bit", "gemma4", "gpt-oss-20b", "qwen35b-a3b"]
IOH = ["iq3s", "gemma31b", "qwen27b"]


def registry_of(*pairs):
    prov = {}
    for p, m in pairs:
        prov.setdefault(p, {"models": []})["models"].append({"id": m})
    return {"providers": prov}


def config_off(provider, model):
    return {"providers": {"pi": {"enabled": True,
            "backends": {provider: {"models": {model: False}}}}}}


class CandidateTableTest(unittest.TestCase):
    def test_names_order_and_hosts(self):
        self.assertEqual(list(fbl.EXECUTORS), STUDIO + IOH)
        self.assertEqual(fbl.HOST_ORDER, ("studio", "ioh"))
        self.assertEqual({n for n, e in fbl.EXECUTORS.items() if e.host == "ioh"}, set(IOH))
        self.assertEqual({n for n, e in fbl.EXECUTORS.items() if e.host == "studio"}, set(STUDIO))

    def test_ioh_has_only_r9700_ports_and_never_8081(self):
        ports = {n: fbl.EXECUTORS[n].base_url.rsplit(":", 1)[1] for n in IOH}
        self.assertEqual(ports, {"iq3s": "8080", "gemma31b": "8083", "qwen27b": "8084"})
        self.assertFalse([n for n, e in fbl.EXECUTORS.items() if e.base_url.endswith(":8081")])

    def test_provider_and_model_are_explicit_and_never_the_cloud_default(self):
        for n, ex in fbl.EXECUTORS.items():
            self.assertTrue(ex.provider and ex.model, n)
            self.assertNotEqual(ex.provider, "opencode-go", n)

    def test_budgets_follow_the_model_family(self):
        for n, ex in fbl.EXECUTORS.items():
            want = (70, 140) if n in ("flash-next", "iq3s") else (60, 120)
            self.assertEqual((ex.design_max, ex.prompt_max), want, n)

    def test_params_decide_the_bigger_model(self):
        e = fbl.EXECUTORS
        self.assertTrue(all(e["flash-next"].params_b > e[n].params_b for n in STUDIO[1:]))
        self.assertEqual(e["iq3s"].params_b, e["flash-next"].params_b)
        self.assertGreater(e["gemma31b"].params_b, e["qwen27b"].params_b)
        self.assertGreater(e["qwen35b-a3b"].params_b, e["qwen27b-8bit"].params_b)
        self.assertEqual(e["qwen27b-mlx4"].params_b, e["qwen27b-8bit"].params_b)

    def test_only_omlx_8000_needs_the_key(self):
        self.assertEqual({n for n, e in fbl.EXECUTORS.items() if e.needs_key},
                         {"flash-next", "qwen27b-mlx4"})


class EligibleCandidatesTest(unittest.TestCase):
    def test_missing_registry_and_config_keep_everything(self):
        self.assertEqual(fbl.eligible_candidates(None, None), (list(fbl.EXECUTORS), {}))

    def test_unregistered_model_is_skipped_even_if_the_provider_exists(self):
        reg = registry_of(*[(e.provider, e.model) for n, e in fbl.EXECUTORS.items() if n != "qwen27b"],
                          ("ioh-qwen27b", "some-other-model"))
        names, skipped = fbl.eligible_candidates(reg, None)
        self.assertNotIn("qwen27b", names)
        self.assertEqual(skipped, {"qwen27b": "not-in-pi"})

    def test_config_off_drops_only_that_candidate(self):
        names, skipped = fbl.eligible_candidates(
            None, config_off("macstudio-qwen-flash-next", "lmstudio-community--Qwen3.8-27B-MLX-4bit"))
        self.assertIn("flash-next", names)
        self.assertEqual(skipped, {"qwen27b-mlx4": "off-in-config"})

    def test_config_without_an_entry_counts_as_on(self):
        names, skipped = fbl.eligible_candidates(
            None, {"providers": {"pi": {"enabled": True, "backends": {}}}})
        self.assertEqual((names, skipped), (list(fbl.EXECUTORS), {}))

    def test_pi_disabled_turns_every_candidate_off(self):
        names, skipped = fbl.eligible_candidates(None, {"providers": {"pi": {"enabled": False}}})
        self.assertEqual(names, [])
        self.assertEqual(set(skipped.values()), {"off-in-config"})


class LoadJsonTest(unittest.TestCase):
    def test_missing_broken_and_valid(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "bad.json").write_text("{nope", encoding="utf-8")
            (t / "ok.json").write_text('{"a": 1}', encoding="utf-8")
            self.assertIsNone(fbl.load_json(t / "missing.json"))
            self.assertIsNone(fbl.load_json(t / "bad.json"))
            self.assertEqual(fbl.load_json(t / "ok.json"), {"a": 1})


def health_for(codes):
    return lambda ex: codes.get(ex.name, 0)


ALL = list(fbl.EXECUTORS)


class LiveLanesPerHostTest(unittest.TestCase):
    def test_todays_state_pairs_flash_next_with_gemma31b(self):
        up = health_for({"flash-next": 200, "gemma31b": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["flash-next", "gemma31b"])

    def test_one_lane_per_pc_and_the_bigger_model_wins(self):
        up = health_for({"flash-next": 200, "gemma4": 200, "iq3s": 200, "gemma31b": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["flash-next", "iq3s"])
        up = health_for({"gemma4": 200, "qwen35b-a3b": 200, "qwen27b-8bit": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["qwen35b-a3b"])

    def test_equal_params_fall_back_to_table_order(self):
        up = health_for({"qwen27b-8bit": 200, "qwen27b-mlx4": 200})
        self.assertEqual(fbl.live_lanes(ALL, up), ["qwen27b-mlx4"])

    def test_a_new_r9700_model_becomes_the_ioh_lane_without_code_changes(self):
        self.assertEqual(fbl.live_lanes(ALL, health_for({"qwen27b": 200})), ["qwen27b"])

    def test_studio_comes_first_and_unknown_names_raise(self):
        up = health_for({"flash-next": 200, "iq3s": 200})
        self.assertEqual(fbl.live_lanes(["iq3s", "flash-next"], up), ["flash-next", "iq3s"])
        with self.assertRaises(ValueError):
            fbl.live_lanes(["nope"], up)


class ExecutorServingTest(unittest.TestCase):
    def setUp(self):
        self._h, self._m = fbl.executor_health, fbl.executor_models

    def tearDown(self):
        fbl.executor_health, fbl.executor_models = self._h, self._m

    def test_studio_candidate_needs_its_model_id_listed(self):
        fbl.executor_health = lambda ex: 200
        fbl.executor_models = lambda ex: ["Jundot--Qwen3.8-Flash-Next-oQ4e-mtp"]
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["flash-next"]), 200)
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["qwen27b-mlx4"]), 0)

    def test_ioh_candidate_only_needs_http_200(self):
        fbl.executor_health = lambda ex: 200
        fbl.executor_models = lambda ex: self.fail("ioh must not consult /v1/models ids")
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["gemma31b"]), 200)

    def test_a_non_200_passes_through_without_listing_models(self):
        fbl.executor_health = lambda ex: 401
        fbl.executor_models = lambda ex: self.fail("no id check when health is not 200")
        self.assertEqual(fbl.executor_serving(fbl.EXECUTORS["flash-next"]), 401)


class SelectModeCandidatesTest(unittest.TestCase):
    def test_candidates_limit_the_pool(self):
        self.assertEqual(fbl.select_mode(None, None, lambda ex: 200, {}, [1], candidates=["iq3s"]),
                         ("single", ["iq3s"]))
        self.assertEqual(fbl.select_mode(None, None, lambda ex: 200, {}, [1], candidates=[]),
                         ("down", []))

    def test_lanes_flag_is_intersected_with_candidates_and_still_validated(self):
        self.assertEqual(fbl.select_mode("flash-next,iq3s", None, lambda ex: 200, {}, [1],
                                         candidates=["iq3s"]), ("single", ["iq3s"]))
        with self.assertRaises(ValueError):
            fbl.select_mode("nope", None, lambda ex: 200, {}, [1], candidates=ALL)

    def test_todays_state_runs_as_a_two_lane_pool(self):
        up = health_for({"flash-next": 200, "gemma31b": 200})
        self.assertEqual(fbl.select_mode(None, None, up, {}, [1, 2]),
                         ("pool", ["flash-next", "gemma31b"]))


class FetchModelsTest(unittest.TestCase):
    """Fake server as in HealthTest (tests/test_fbl_task.py)."""

    def setUp(self):
        outer = self
        outer.seen = []
        outer.reply = (200, b'{"data":[{"id":"a"},{"id":"b"}]}')

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.seen.append((self.path, self.headers.get("Authorization")))
                status, body = outer.reply
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_lists_ids(self):
        self.assertEqual(fbl.fetch_models(self.base), ["a", "b"])
        self.assertEqual(self.seen[0][0], "/v1/models")

    def test_sends_bearer_key(self):
        fbl.fetch_models(self.base, key="k")
        self.assertEqual(self.seen[0][1], "Bearer k")

    def test_errors_give_empty_list(self):
        for reply in ((500, b"boom"), (200, b"not json"), (200, b'{"nodata":1}'),
                      (200, b'{"data":[{"x":1}]}')):
            self.reply = reply
            self.assertEqual(fbl.fetch_models(self.base), [], reply)

    def test_unreachable_gives_empty_list(self):
        self.assertEqual(fbl.fetch_models("http://127.0.0.1:1", timeout=1), [])


class PreflightServedTest(unittest.TestCase):
    def setUp(self):
        self._saved = (fbl.executor_health, fbl.executor_models, fbl.warm_up, fbl.probe_lanes,
                       fbl.PI_MODELS_PATH, fbl.CONFIG_PATH)
        self.td = tempfile.TemporaryDirectory()
        t = Path(self.td.name)
        fbl.PI_MODELS_PATH, fbl.CONFIG_PATH = t / "pi.json", t / "config.json"  # missing files
        fbl.executor_models = lambda ex: [ex.model]
        fbl.warm_up = lambda ex: 200
        fbl.probe_lanes = lambda: "none"

    def tearDown(self):
        (fbl.executor_health, fbl.executor_models, fbl.warm_up, fbl.probe_lanes,
         fbl.PI_MODELS_PATH, fbl.CONFIG_PATH) = self._saved
        self.td.cleanup()

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fbl.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_todays_state_picks_flash_next_and_gemma31b(self):
        warmed = []
        fbl.executor_health = health_for({"flash-next": 200, "gemma31b": 200})
        fbl.warm_up = lambda ex: warmed.append(ex.name) or 200
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 0)
        for line in ("LANE=flash-next HEALTH=200 SERVED=yes", "LANE=gemma31b HEALTH=200",
                     "LANE=iq3s HEALTH=0", "PICK=studio:flash-next,ioh:gemma31b",
                     "LANES_UP=flash-next,gemma31b", "PREFLIGHT=ok"):
            self.assertIn(line, out)
        self.assertEqual(warmed, ["flash-next", "gemma31b"])

    def test_skipped_candidates_are_listed_and_not_probed(self):
        t = Path(self.td.name)
        (t / "pi.json").write_text(json.dumps(registry_of(
            *[(e.provider, e.model) for n, e in fbl.EXECUTORS.items() if n != "qwen27b"])),
            encoding="utf-8")
        (t / "config.json").write_text(json.dumps(config_off(
            "macstudio-qwen-flash-next", "lmstudio-community--Qwen3.8-27B-MLX-4bit")),
            encoding="utf-8")
        fbl.executor_health = health_for({"flash-next": 200})
        rc, out, _ = self.run_main("preflight")
        self.assertIn("SKIP=qwen27b REASON=not-in-pi", out)
        self.assertIn("SKIP=qwen27b-mlx4 REASON=off-in-config", out)
        self.assertNotIn("LANE=qwen27b ", out)
        self.assertNotIn("LANE=qwen27b-mlx4 ", out)

    def test_studio_up_but_model_not_listed_is_not_served(self):
        fbl.executor_health = health_for({n: 200 for n in STUDIO})
        fbl.executor_models = lambda ex: []
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("LANE=flash-next HEALTH=200 SERVED=no", out)
        self.assertNotIn("PICK=", out)

    def test_no_eligible_candidate_stops_with_guidance(self):
        (Path(self.td.name) / "config.json").write_text(
            json.dumps({"providers": {"pi": {"enabled": False}}}), encoding="utf-8")
        fbl.executor_health = lambda ex: self.fail("no server may be touched")
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("PREFLIGHT=none", out)
        self.assertIn("/fiftybox-config", out)

    def test_unreadable_registry_warns_and_checks_nothing(self):
        fbl.executor_health = health_for({"flash-next": 200})
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 0)
        self.assertIn("WARN=pi registry unreadable", out)

    def test_a_401_still_gives_the_auth_message(self):
        fbl.executor_health = health_for({"flash-next": 401})
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("PREFLIGHT=auth", out)

    def test_explicit_executor_prints_no_benchmark_warning(self):
        fbl.executor_health = lambda ex: 200
        rc, _, err = self.run_main("preflight", "--executor", "gemma4")
        self.assertEqual(rc, 0)
        self.assertNotIn("WARN=", err)

    def test_run_without_candidates_stops_before_dispatch(self):
        (Path(self.td.name) / "config.json").write_text(
            json.dumps({"providers": {"pi": {"enabled": False}}}), encoding="utf-8")
        rc, out, _ = self.run_main("run", "--artifact-dir", self.td.name, "--tasks", "1")
        self.assertEqual(rc, 2)
        self.assertIn("STOP=NO_CANDIDATES", out)

    def test_explicit_executor_never_warms_up_a_model_the_server_does_not_list(self):
        fbl.executor_health = lambda ex: 200
        fbl.executor_models = lambda ex: []
        fbl.warm_up = lambda ex: self.fail("must not send a request for an unserved model")
        rc, out, _ = self.run_main("preflight", "--executor", "flash-next")
        self.assertEqual(rc, 1)
        self.assertIn("EXECUTOR=flash-next HEALTH=200 SERVED=no", out)
        self.assertIn("PREFLIGHT=down", out)

    def test_registry_with_the_wrong_shape_warns_instead_of_crashing(self):
        (Path(self.td.name) / "pi.json").write_text(json.dumps({"providers": []}), encoding="utf-8")
        fbl.executor_health = health_for({"flash-next": 200})
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 0)
        self.assertIn("WARN=pi registry unreadable", out)

    def test_a_401_on_a_keyless_port_points_at_needs_key_not_the_key_file(self):
        fbl.executor_health = health_for({"gemma31b": 401})
        rc, out, _ = self.run_main("preflight")
        self.assertEqual(rc, 1)
        self.assertIn("PREFLIGHT=auth", out)
        self.assertIn("gemma31b", out)
        self.assertIn("needs_key", out)
        self.assertNotIn("do not reissue", out)
        self.assertNotIn("start procedure", out)
        fbl.executor_health = lambda ex: 401
        rc, out, _ = self.run_main("preflight", "--executor", "gemma31b")
        self.assertIn("needs_key", out)


class OddJsonShapesTest(unittest.TestCase):
    BAD_REGISTRIES = [{"providers": {"ioh": "x"}}, {"providers": {"ioh": {"models": "x"}}},
                      {"providers": {"ioh": {"models": [1, None]}}}]
    BAD_CONFIGS = [{"providers": []}, {"providers": {"pi": True}}, {"providers": {"pi": {"backends": []}}},
                   {"providers": {"pi": {"backends": {"ioh": [1]}}}},
                   {"providers": {"pi": {"backends": {"ioh": {"models": []}}}}}]

    def test_odd_registry_shapes_never_raise(self):
        for reg in self.BAD_REGISTRIES:
            names, skipped = fbl.eligible_candidates(reg, None)
            self.assertEqual(sorted(names + list(skipped)), sorted(fbl.EXECUTORS), reg)

    def test_odd_config_shapes_count_as_no_information_so_everything_stays_on(self):
        for cfg in self.BAD_CONFIGS:
            self.assertEqual(fbl.eligible_candidates(None, cfg), (list(fbl.EXECUTORS), {}), cfg)


class ProbeLanesTest(unittest.TestCase):
    def test_lsof_checks_the_darkbloom_port_too(self):
        seen = []
        real = fbl.subprocess.run
        fbl.subprocess.run = lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")
        try:
            fbl.probe_lanes()
        finally:
            fbl.subprocess.run = real
        self.assertIn("-iTCP:8001", seen[0][-1])


if __name__ == "__main__":
    unittest.main(verbosity=1)
