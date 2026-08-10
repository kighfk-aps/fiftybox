"""Tests for cc_diff_review."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import cc_diff_review as cdr  # noqa: E402


SHIM_BODY = """#!/usr/bin/env bash
# Codex shutout shim — installed 2026-07-27.
exit 1
"""


# ---------------------------------------------------------------------------
# Pure parsing and prompt assembly
# ---------------------------------------------------------------------------

class TestParseVerdict:
    def test_reads_verdict_off_first_nonblank_line(self):
        assert cdr.parse_verdict("\n\nREVISE\n\n- [severity: major] x") == "REVISE"

    def test_accepts_trailing_punctuation(self):
        assert cdr.parse_verdict("APPROVED — no findings") == "APPROVED"

    def test_rejects_verdict_glued_to_more_word(self):
        assert cdr.parse_verdict("APPROVEDLY yours") == "UNKNOWN"

    def test_off_contract_first_line_is_unknown(self):
        assert cdr.parse_verdict("Here is my review:\nAPPROVED") == "UNKNOWN"

    def test_empty_text_is_unknown(self):
        assert cdr.parse_verdict("   \n\n") == "UNKNOWN"

    def test_blocked_is_a_verdict(self):
        assert cdr.parse_verdict("BLOCKED\n") == "BLOCKED"


class TestCountFindings:
    def test_counts_one_line_per_severity_header(self):
        text = (
            "REVISE\n"
            "- [severity: blocking] missing requirement\n"
            "  Evidence: spec line 3\n"
            "  Proposal: add it\n"
            "- [severity: minor] naming\n"
        )
        assert cdr.count_findings(text) == 2

    def test_indented_findings_still_count(self):
        assert cdr.count_findings("REVISE\n  - [severity: major] x\n") == 1

    def test_off_contract_response_counts_zero(self):
        assert cdr.count_findings("REVISE\nI think you should change things.") == 0

    def test_approved_with_no_findings_is_zero(self):
        assert cdr.count_findings("APPROVED\n") == 0

    def test_evidence_lines_are_not_findings(self):
        text = (
            "REVISE\n"
            "- [severity: blocking] one\n"
            "  Evidence: severity is discussed here\n"
        )
        assert cdr.count_findings(text) == 1


class TestBuildPrompt:
    def _prompt(self):
        return cdr.build_prompt(
            "spec-task-1.md", "SPEC BODY",
            "diff-task-1.patch", "DIFF BODY",
            [("test_thing.py", "TEST BODY")],
            [("design.md", "DESIGN BODY")],
        )

    def test_starts_with_the_contract(self):
        assert self._prompt().startswith(cdr.DIFF_REVIEW_CONTRACT)

    def test_inlines_every_input(self):
        prompt = self._prompt()
        for body in ("SPEC BODY", "DIFF BODY", "TEST BODY", "DESIGN BODY"):
            assert body in prompt

    def test_orders_spec_before_diff_before_tests_before_context(self):
        prompt = self._prompt()
        assert (prompt.index("SPEC BODY") < prompt.index("DIFF BODY")
                < prompt.index("TEST BODY") < prompt.index("DESIGN BODY"))

    def test_names_each_input_file(self):
        prompt = self._prompt()
        for name in ("spec-task-1.md", "diff-task-1.patch",
                     "test_thing.py", "design.md"):
            assert name in prompt

    def test_works_without_context_files(self):
        prompt = cdr.build_prompt("s.md", "S", "d.patch", "D",
                                  [("t.py", "T")], [])
        assert "T" in prompt

    def test_contract_forbids_claiming_test_results(self):
        assert "Never claim a test passed or failed" in cdr.DIFF_REVIEW_CONTRACT

    def test_contract_puts_cross_task_integration_out_of_scope(self):
        assert "cross-task integration" in cdr.DIFF_REVIEW_CONTRACT

    def test_contract_demands_the_verdict_on_the_first_line(self):
        assert "APPROVED | REVISE | BLOCKED" in cdr.DIFF_REVIEW_CONTRACT

    def test_contract_forbids_modifying_files(self):
        assert "Do not modify any file" in cdr.DIFF_REVIEW_CONTRACT


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

class TestIsShim:
    def test_detects_shim_by_marker(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text(SHIM_BODY, encoding="utf-8")
        assert cdr.is_shim(p) is True

    def test_real_script_without_marker_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text("#!/bin/sh\nexec real-codex \"$@\"\n", encoding="utf-8")
        assert cdr.is_shim(p) is False

    def test_binary_file_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\xfd")
        assert cdr.is_shim(p) is False

    def test_missing_file_is_not_shim(self, tmp_path):
        assert cdr.is_shim(tmp_path / "nope") is False


class TestLoadModelSlugs:
    def test_reads_slugs(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text('{"models": [{"slug": "gpt-5.6-terra"}]}', encoding="utf-8")
        assert cdr.load_model_slugs(cache) == ["gpt-5.6-terra"]

    def test_unreadable_cache_is_none(self, tmp_path):
        assert cdr.load_model_slugs(tmp_path / "nope.json") is None

    def test_malformed_cache_is_none(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text("not json", encoding="utf-8")
        assert cdr.load_model_slugs(cache) is None

    def test_entries_without_string_slug_are_skipped(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text('{"models": [{"slug": 7}, {"slug": "gpt-5.6-sol"}]}',
                         encoding="utf-8")
        assert cdr.load_model_slugs(cache) == ["gpt-5.6-sol"]


class TestDiffReviewLogPath:
    def test_names_log_by_date_and_task(self, tmp_path):
        got = cdr.diff_review_log_path(tmp_path, "task-1", "2026-08-10")
        assert got == tmp_path / "2026-08-10-task-1-gpt-review.md"

    def test_never_overwrites_an_existing_log(self, tmp_path):
        (tmp_path / "2026-08-10-task-1-gpt-review.md").write_text("x", encoding="utf-8")
        got = cdr.diff_review_log_path(tmp_path, "task-1", "2026-08-10")
        assert got == tmp_path / "2026-08-10-task-1-gpt-review-2.md"

    def test_counter_keeps_climbing(self, tmp_path):
        (tmp_path / "2026-08-10-task-1-gpt-review.md").write_text("x", encoding="utf-8")
        (tmp_path / "2026-08-10-task-1-gpt-review-2.md").write_text("x", encoding="utf-8")
        got = cdr.diff_review_log_path(tmp_path, "task-1", "2026-08-10")
        assert got == tmp_path / "2026-08-10-task-1-gpt-review-3.md"


class TestBuildCodexCmd:
    def test_runs_read_only_and_reads_prompt_from_stdin(self, tmp_path):
        cmd = cdr.build_codex_cmd("gpt-5.6-terra", "high", tmp_path / "out.txt")
        assert cmd[:2] == ["codex", "exec"]
        assert "-s" in cmd and cmd[cmd.index("-s") + 1] == "read-only"
        assert cmd[-1] == "-"

    def test_passes_model_and_effort(self, tmp_path):
        cmd = cdr.build_codex_cmd("gpt-5.6-sol", "medium", tmp_path / "out.txt")
        assert cmd[cmd.index("--model") + 1] == "gpt-5.6-sol"
        assert "model_reasoning_effort=medium" in cmd

    def test_isolates_the_run_from_user_config(self, tmp_path):
        cmd = cdr.build_codex_cmd("gpt-5.6-terra", "high", tmp_path / "out.txt")
        for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
            assert flag in cmd

    def test_writes_the_last_message_to_the_output_file(self, tmp_path):
        out = tmp_path / "out.txt"
        cmd = cdr.build_codex_cmd("gpt-5.6-terra", "high", out)
        assert cmd[cmd.index("-o") + 1] == str(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def inputs(tmp_path):
    """Three valid input files in a scratch directory."""
    (tmp_path / "diff.patch").write_text("+ added line\n", encoding="utf-8")
    (tmp_path / "spec.md").write_text("Task: do the thing\n", encoding="utf-8")
    (tmp_path / "test_thing.py").write_text("def test_thing(): pass\n", encoding="utf-8")
    return tmp_path


def base_argv(inputs, **over):
    argv = [
        "--diff", str(inputs / "diff.patch"),
        "--spec", str(inputs / "spec.md"),
        "--test", str(inputs / "test_thing.py"),
        "--task-name", "task-1",
        "--out", str(inputs / "reviews"),
    ]
    for flag, value in over.items():
        argv += ["--" + flag.replace("_", "-"), value]
    return argv


@pytest.fixture
def fake_codex(inputs, monkeypatch):
    """A real (non-shim) codex on PATH so preflight passes."""
    bin_dir = inputs / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "codex"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("CODEX_HOME", str(inputs / "codex-home"))
    return exe


class TestReadPairs:
    def test_returns_name_and_text_pairs(self, inputs):
        got = cdr.read_pairs([str(inputs / "spec.md")])
        assert got == [("spec.md", "Task: do the thing\n")]

    def test_missing_file_is_none(self, inputs):
        assert cdr.read_pairs([str(inputs / "nope.md")]) is None

    def test_empty_list_is_empty_list(self):
        assert cdr.read_pairs([]) == []


class TestMainArgValidation:
    def test_missing_diff_file_exits_args(self, inputs, fake_codex, capsys):
        argv = base_argv(inputs)
        argv[argv.index("--diff") + 1] = str(inputs / "nope.patch")
        assert cdr.main(argv) == cdr.EXIT_ARGS
        assert "not found" in capsys.readouterr().err

    def test_missing_spec_file_exits_args(self, inputs, fake_codex):
        argv = base_argv(inputs)
        argv[argv.index("--spec") + 1] = str(inputs / "nope.md")
        assert cdr.main(argv) == cdr.EXIT_ARGS

    def test_missing_test_file_exits_args(self, inputs, fake_codex):
        argv = base_argv(inputs)
        argv[argv.index("--test") + 1] = str(inputs / "nope.py")
        assert cdr.main(argv) == cdr.EXIT_ARGS

    def test_missing_context_file_exits_args(self, inputs, fake_codex):
        argv = base_argv(inputs) + ["--context", str(inputs / "nope.md")]
        assert cdr.main(argv) == cdr.EXIT_ARGS

    def test_invalid_effort_exits_args(self, inputs, fake_codex):
        assert cdr.main(base_argv(inputs, effort="turbo")) == cdr.EXIT_ARGS

    def test_nonpositive_timeout_exits_args(self, inputs, fake_codex):
        assert cdr.main(base_argv(inputs, timeout="0")) == cdr.EXIT_ARGS

    def test_shim_codex_exits_no_codex(self, inputs, monkeypatch):
        bin_dir = inputs / "shimbin"
        bin_dir.mkdir()
        exe = bin_dir / "codex"
        exe.write_text(SHIM_BODY, encoding="utf-8")
        exe.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        assert cdr.main(base_argv(inputs)) == cdr.EXIT_NO_CODEX

    def test_absent_codex_exits_no_codex(self, inputs, monkeypatch):
        empty = inputs / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert cdr.main(base_argv(inputs)) == cdr.EXIT_NO_CODEX

    def test_unknown_model_exits_bad_model(self, inputs, fake_codex, monkeypatch):
        home = inputs / "codex-home"
        home.mkdir()
        (home / "models_cache.json").write_text(
            '{"models": [{"slug": "gpt-5.6-terra"}]}', encoding="utf-8")
        assert cdr.main(base_argv(inputs, model="gpt-9")) == cdr.EXIT_BAD_MODEL

    def test_known_model_passes_validation(self, inputs, fake_codex, monkeypatch):
        home = inputs / "codex-home"
        home.mkdir()
        (home / "models_cache.json").write_text(
            '{"models": [{"slug": "gpt-5.6-terra"}]}', encoding="utf-8")

        def fake_run(cmd, **kwargs):
            Path(cmd[cmd.index("-o") + 1]).write_text("APPROVED\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        monkeypatch.setattr(cdr.subprocess, "run", fake_run)
        assert cdr.main(base_argv(inputs)) == 0


class TestMainSuccess:
    def _run(self, inputs, monkeypatch, review_text, returncode=0):
        def fake_run(cmd, **kwargs):
            Path(cmd[cmd.index("-o") + 1]).write_text(review_text, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, returncode, "", "")
        monkeypatch.setattr(cdr.subprocess, "run", fake_run)
        return cdr.main(base_argv(inputs))

    def test_writes_log_and_emits_json(self, inputs, fake_codex, monkeypatch, capsys):
        review = ("REVISE\n"
                  "- [severity: blocking] missing requirement\n"
                  "  Evidence: spec says X\n"
                  "  Proposal: add X\n")
        assert self._run(inputs, monkeypatch, review) == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["ok"] is True
        assert payload["verdict"] == "REVISE"
        assert payload["findingsCount"] == 1
        assert payload["diffPath"] == str(inputs / "diff.patch")
        assert payload["taskName"] == "task-1"
        log = Path(payload["reviewPath"])
        assert log.exists()
        assert "task-1" in log.name
        assert "missing requirement" in log.read_text(encoding="utf-8")

    def test_creates_the_output_directory(self, inputs, fake_codex, monkeypatch, capsys):
        assert self._run(inputs, monkeypatch, "APPROVED\n") == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert Path(payload["reviewPath"]).parent == inputs / "reviews"

    def test_second_review_of_the_same_task_keeps_the_first(
            self, inputs, fake_codex, monkeypatch, capsys):
        self._run(inputs, monkeypatch, "APPROVED\n")
        first = json.loads(capsys.readouterr().out.strip())["reviewPath"]
        self._run(inputs, monkeypatch, "REVISE\n- [severity: minor] x\n")
        second = json.loads(capsys.readouterr().out.strip())["reviewPath"]
        assert first != second
        assert Path(first).exists() and Path(second).exists()

    def test_off_contract_review_reports_unknown(self, inputs, fake_codex,
                                                 monkeypatch, capsys):
        assert self._run(inputs, monkeypatch, "Looks fine to me.\n") == 0
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["verdict"] == "UNKNOWN"
        assert payload["findingsCount"] == 0

    def test_json_is_a_single_line(self, inputs, fake_codex, monkeypatch, capsys):
        assert self._run(inputs, monkeypatch, "APPROVED\n") == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 1

    def test_codex_nonzero_exits_codex_failed(self, inputs, fake_codex, monkeypatch):
        assert self._run(inputs, monkeypatch, "APPROVED\n",
                         returncode=1) == cdr.EXIT_CODEX_FAILED

    def test_empty_review_exits_codex_failed(self, inputs, fake_codex, monkeypatch):
        assert self._run(inputs, monkeypatch, "   \n") == cdr.EXIT_CODEX_FAILED

    def test_timeout_exits_timeout(self, inputs, fake_codex, monkeypatch):
        def raise_timeout(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 900)
        monkeypatch.setattr(cdr.subprocess, "run", raise_timeout)
        assert cdr.main(base_argv(inputs)) == cdr.EXIT_TIMEOUT

    def test_prompt_reaches_codex_on_stdin(self, inputs, fake_codex, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["input"] = kwargs.get("input", "")
            Path(cmd[cmd.index("-o") + 1]).write_text("APPROVED\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        monkeypatch.setattr(cdr.subprocess, "run", fake_run)
        assert cdr.main(base_argv(inputs)) == 0
        assert seen["input"].startswith(cdr.DIFF_REVIEW_CONTRACT)
        assert "Task: do the thing" in seen["input"]
        assert "+ added line" in seen["input"]
