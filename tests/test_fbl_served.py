#!/usr/bin/env python3
"""Unit tests for the served-model lanes of skills/fiftybox-local/scripts/fbl_task.py.

Candidate table, eligibility (table + Pi registry + fiftybox-config), served
detection and the one-lane-per-PC pick. Only the network/subprocess boundary is
replaced; the parsers and selection logic run for real.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
