"""Tests for gpt_review."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import gpt_review as gr  # noqa: E402


SHIM_BODY = """#!/usr/bin/env bash
# Codex shutout shim — installed 2026-07-27.
cat >&2 <<'MSG'
[codex] disabled
MSG
exit 1
"""


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

class TestIsShim:
    def test_detects_shim_by_marker(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text(SHIM_BODY, encoding="utf-8")
        assert gr.is_shim(p) is True

    def test_real_script_without_marker_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_text("#!/bin/sh\nexec real-codex \"$@\"\n", encoding="utf-8")
        assert gr.is_shim(p) is False

    def test_binary_file_is_not_shim(self, tmp_path):
        p = tmp_path / "codex"
        p.write_bytes(b"\x7fELF\x02\x01\x01\x00\xff\xfe\xfd")
        assert gr.is_shim(p) is False

    def test_missing_file_is_not_shim(self, tmp_path):
        assert gr.is_shim(tmp_path / "nope") is False


class TestFindCodex:
    def test_returns_path_when_on_path(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "codex"
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        assert gr.find_codex() == exe

    def test_returns_none_when_absent(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert gr.find_codex() is None


class TestLoadModelSlugs:
    def test_reads_slugs_from_cache(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text(json.dumps({"models": [
            {"slug": "gpt-5.6-terra"}, {"slug": "gpt-5.4-mini"},
        ]}), encoding="utf-8")
        assert gr.load_model_slugs(cache) == ["gpt-5.6-terra", "gpt-5.4-mini"]

    def test_missing_cache_returns_none(self, tmp_path):
        assert gr.load_model_slugs(tmp_path / "absent.json") is None

    def test_malformed_cache_returns_none(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text("{ not json", encoding="utf-8")
        assert gr.load_model_slugs(cache) is None

    def test_entries_without_slug_are_skipped(self, tmp_path):
        cache = tmp_path / "models_cache.json"
        cache.write_text(json.dumps({"models": [
            {"slug": "gpt-5.5"}, {"display_name": "no slug"}, "junk",
        ]}), encoding="utf-8")
        assert gr.load_model_slugs(cache) == ["gpt-5.5"]


class TestCodexCachePath:
    def test_uses_codex_home_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ch"))
        assert gr.codex_cache_path() == tmp_path / "ch" / "models_cache.json"

    def test_falls_back_to_home_dot_codex(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CODEX_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert gr.codex_cache_path() == Path(tmp_path) / ".codex" / "models_cache.json"


# ---------------------------------------------------------------------------
# Review contract
# ---------------------------------------------------------------------------

class TestParseVerdict:
    def test_approved_first_line(self):
        assert gr.parse_verdict("APPROVED\n\n- nothing to fix") == "APPROVED"

    def test_revise_with_trailing_summary(self):
        assert gr.parse_verdict("REVISE: 세 군데 빠졌다\n...") == "REVISE"

    def test_blocked(self):
        assert gr.parse_verdict("BLOCKED — 설계 전제가 틀림") == "BLOCKED"

    def test_leading_blank_lines_are_skipped(self):
        assert gr.parse_verdict("\n\n  APPROVED\n") == "APPROVED"

    def test_off_contract_output_is_unknown(self):
        assert gr.parse_verdict("Sure! Here are my thoughts:") == "UNKNOWN"

    def test_empty_is_unknown(self):
        assert gr.parse_verdict("") == "UNKNOWN"

    def test_verdict_word_only_on_later_line_is_unknown(self):
        assert gr.parse_verdict("notes\nAPPROVED") == "UNKNOWN"


class TestReviewLogPath:
    def test_uses_date_and_doc_slug(self, tmp_path):
        p = gr.review_log_path(tmp_path, Path("docs/specs/my-design.md"), "2026-08-03")
        assert p == tmp_path / "2026-08-03-my-design-gpt-review.md"

    def test_second_run_same_day_gets_suffix(self, tmp_path):
        first = gr.review_log_path(tmp_path, Path("a/my-design.md"), "2026-08-03")
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text("x", encoding="utf-8")
        second = gr.review_log_path(tmp_path, Path("a/my-design.md"), "2026-08-03")
        assert second == tmp_path / "2026-08-03-my-design-gpt-review-2.md"

    def test_third_run_same_day_gets_next_suffix(self, tmp_path):
        for name in ("2026-08-03-d-gpt-review.md", "2026-08-03-d-gpt-review-2.md"):
            (tmp_path / name).write_text("x", encoding="utf-8")
        p = gr.review_log_path(tmp_path, Path("a/d.md"), "2026-08-03")
        assert p == tmp_path / "2026-08-03-d-gpt-review-3.md"


class TestBuildCodexCmd:
    def test_includes_readonly_and_isolation_flags(self, tmp_path):
        cmd = gr.build_codex_cmd("gpt-5.6-terra", "high", tmp_path / "out.txt")
        assert cmd[:2] == ["codex", "exec"]
        assert "--model" in cmd and "gpt-5.6-terra" in cmd
        for flag in ("-s", "read-only", "--ephemeral",
                     "--skip-git-repo-check", "--ignore-user-config"):
            assert flag in cmd
        assert "-c" in cmd and "model_reasoning_effort=high" in cmd
        assert cmd[-1] == "-", "prompt must come from stdin"
        assert str(tmp_path / "out.txt") in cmd


class TestBuildPrompt:
    def test_inlines_document_and_contract(self):
        prompt = gr.build_prompt("design.md", "# Design\nbody here", [])
        assert "body here" in prompt
        assert "APPROVED" in prompt and "BLOCKED" in prompt
        assert "blocking" in prompt

    def test_inlines_context_files(self):
        prompt = gr.build_prompt("d.md", "doc", [("notes.md", "context body")])
        assert "context body" in prompt
        assert "notes.md" in prompt


# ---------------------------------------------------------------------------
# main() end-to-end with a stubbed codex
# ---------------------------------------------------------------------------

def _stub_codex(bin_dir: Path, *, reply: str = "APPROVED\n\nlooks fine",
                exit_code: int = 0, sleep: float = 0.0) -> Path:
    """Install a fake `codex` on PATH that copies `reply` into -o's target."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    reply_file = bin_dir / "reply.txt"
    reply_file.write_text(reply, encoding="utf-8")
    exe = bin_dir / "codex"
    exe.write_text(
        "#!/usr/bin/env bash\n"
        f"sleep {sleep}\n"
        'out=""\n'
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ $1 == -o ]]; then out=$2; shift; fi\n'
        "  shift\n"
        "done\n"
        "cat >/dev/null\n"
        f'if [[ -n "$out" ]]; then cp "{reply_file}" "$out"; fi\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return exe


@pytest.fixture
def doc(tmp_path) -> Path:
    d = tmp_path / "docs" / "specs"
    d.mkdir(parents=True)
    p = d / "my-design.md"
    p.write_text("# My Design\n\nSome content.\n", encoding="utf-8")
    return p


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Path:
    ch = tmp_path / "codex-home"
    ch.mkdir()
    (ch / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-5.6-terra"}, {"slug": "gpt-5.4-mini"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(ch))
    return ch / "models_cache.json"


class TestMain:
    def test_shim_exits_3(self, tmp_path, doc, cache, monkeypatch, capsys):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "codex").write_text(SHIM_BODY, encoding="utf-8")
        (bin_dir / "codex").chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        rc = gr.main(["--doc", str(doc), "--out", str(tmp_path / "reviews")])
        assert rc == gr.EXIT_NO_CODEX
        assert "rm /opt/homebrew/bin/codex" in capsys.readouterr().err

    def test_missing_codex_exits_3(self, tmp_path, doc, cache, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert gr.main(["--doc", str(doc)]) == gr.EXIT_NO_CODEX

    def test_missing_doc_exits_2(self, tmp_path, cache, monkeypatch):
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert gr.main(["--doc", str(tmp_path / "nope.md")]) == gr.EXIT_ARGS

    def test_missing_context_file_exits_2(self, tmp_path, doc, cache, monkeypatch):
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--context", str(tmp_path / "gone.md"),
                      "--out", str(tmp_path / "reviews")])
        assert rc == gr.EXIT_ARGS

    def test_unknown_model_exits_4_and_lists_options(self, tmp_path, doc, cache,
                                                     monkeypatch, capsys):
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--model", "gpt-9-nope"])
        assert rc == gr.EXIT_BAD_MODEL
        assert "gpt-5.6-terra" in capsys.readouterr().err

    def test_absent_cache_skips_validation_and_succeeds(self, tmp_path, doc,
                                                        monkeypatch, capsys):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-such-home"))
        _stub_codex(tmp_path / "bin")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--model", "gpt-9-unverifiable",
                      "--out", str(tmp_path / "reviews")])
        assert rc == 0
        assert "cannot validate" in capsys.readouterr().err.lower()

    def test_success_writes_log_and_json(self, tmp_path, doc, cache, monkeypatch, capsys):
        _stub_codex(tmp_path / "bin", reply="REVISE: 두 군데\n\n- [severity: major] x")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        out = tmp_path / "reviews"
        rc = gr.main(["--doc", str(doc), "--out", str(out)])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["verdict"] == "REVISE"
        assert payload["model"] == gr.DEFAULT_MODEL
        log = Path(payload["reviewPath"])
        assert log.exists()
        body = log.read_text(encoding="utf-8")
        assert "REVISE: 두 군데" in body
        assert gr.DEFAULT_MODEL in body
        assert str(doc) in body

    def test_codex_failure_exits_6(self, tmp_path, doc, cache, monkeypatch):
        _stub_codex(tmp_path / "bin", reply="", exit_code=1)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert gr.main(["--doc", str(doc), "--out", str(tmp_path / "r")]) == gr.EXIT_CODEX_FAILED

    def test_empty_review_exits_6(self, tmp_path, doc, cache, monkeypatch):
        _stub_codex(tmp_path / "bin", reply="   \n", exit_code=0)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert gr.main(["--doc", str(doc), "--out", str(tmp_path / "r")]) == gr.EXIT_CODEX_FAILED

    def test_timeout_exits_5(self, tmp_path, doc, cache, monkeypatch):
        _stub_codex(tmp_path / "bin", sleep=2)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        rc = gr.main(["--doc", str(doc), "--out", str(tmp_path / "r"), "--timeout", "1"])
        assert rc == gr.EXIT_TIMEOUT
