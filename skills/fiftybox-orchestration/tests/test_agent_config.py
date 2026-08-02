"""Tests for BUILTIN_AGENTS, load_agent_config, and build_agent_cmd."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

# Make orchestrate importable without installing the package
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import orchestrate as orc  # noqa: E402


# ---------------------------------------------------------------------------
# BUILTIN_AGENTS
# ---------------------------------------------------------------------------

class TestBuiltinAgents:
    def test_all_six_agents_present(self):
        expected = {"pi", "opencode", "aider", "gemini", "qwen", "cursor"}
        assert set(orc.BUILTIN_AGENTS.keys()) == expected

    def test_each_agent_has_cmd_list(self):
        for name, defn in orc.BUILTIN_AGENTS.items():
            assert isinstance(defn, dict), f"{name} must be a dict"
            assert "cmd" in defn, f"{name} missing 'cmd'"
            assert isinstance(defn["cmd"], list), f"{name}.cmd must be list"
            assert len(defn["cmd"]) > 0, f"{name}.cmd must be non-empty"

    def test_all_cmd_tokens_are_strings(self):
        for name, defn in orc.BUILTIN_AGENTS.items():
            for i, token in enumerate(defn["cmd"]):
                assert isinstance(token, str), f"{name}.cmd[{i}] must be str"

    def test_pi_cmd_contains_provider_and_model(self):
        pi_cmd = orc.BUILTIN_AGENTS["pi"]["cmd"]
        joined = " ".join(pi_cmd)
        assert "{provider}" in joined
        assert "{model}" in joined

    def test_cursor_uses_adapters_dir(self):
        cursor_cmd = orc.BUILTIN_AGENTS["cursor"]["cmd"]
        assert cursor_cmd[0] == "{adapters_dir}/cursor.sh"


# ---------------------------------------------------------------------------
# load_agent_config
# ---------------------------------------------------------------------------

class TestLoadAgentConfig:
    def test_no_config_returns_pi_defaults(self, tmp_path):
        cfg = orc.load_agent_config(tmp_path)
        assert cfg["explore_agent"] == "pi"
        assert cfg["implement_agent"] == "pi"
        assert cfg["agents"] == orc.BUILTIN_AGENTS

    def test_config_overrides_explore_agent(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"explore_agent": "gemini"}), encoding="utf-8"
        )
        cfg = orc.load_agent_config(tmp_path)
        assert cfg["explore_agent"] == "gemini"
        assert cfg["implement_agent"] == "pi"

    def test_config_overrides_implement_agent(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        cfg = orc.load_agent_config(tmp_path)
        assert cfg["explore_agent"] == "pi"
        assert cfg["implement_agent"] == "aider"

    def test_builtins_always_available_even_with_partial_config(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"explore_agent": "opencode"}), encoding="utf-8"
        )
        cfg = orc.load_agent_config(tmp_path)
        for agent in orc.BUILTIN_AGENTS:
            assert agent in cfg["agents"]

    def test_user_agents_merged_over_builtins(self, tmp_path):
        custom = {"my-agent": {"cmd": ["my-agent", "{task}"]}}
        (tmp_path / "config.json").write_text(
            json.dumps({"agents": custom}), encoding="utf-8"
        )
        cfg = orc.load_agent_config(tmp_path)
        assert "my-agent" in cfg["agents"]
        assert "pi" in cfg["agents"]

    def test_user_can_override_builtin_cmd(self, tmp_path):
        override_cmd = ["my-pi", "--custom", "{task}"]
        (tmp_path / "config.json").write_text(
            json.dumps({"agents": {"pi": {"cmd": override_cmd}}}), encoding="utf-8"
        )
        cfg = orc.load_agent_config(tmp_path)
        assert cfg["agents"]["pi"]["cmd"] == override_cmd

    def test_malformed_json_returns_defaults_with_error_key(self, tmp_path):
        (tmp_path / "config.json").write_text("not json!", encoding="utf-8")
        cfg = orc.load_agent_config(tmp_path)
        assert cfg["explore_agent"] == "pi"
        assert cfg["implement_agent"] == "pi"
        assert "_config_error" in cfg

    def test_non_dict_root_returns_defaults_with_error_key(self, tmp_path):
        (tmp_path / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
        cfg = orc.load_agent_config(tmp_path)
        assert cfg["explore_agent"] == "pi"
        assert "_config_error" in cfg

    def test_non_dict_agents_value_ignored_builtins_kept(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"agents": "not-a-dict"}), encoding="utf-8"
        )
        cfg = orc.load_agent_config(tmp_path)
        assert set(cfg["agents"].keys()) == set(orc.BUILTIN_AGENTS.keys())


# ---------------------------------------------------------------------------
# build_agent_cmd
# ---------------------------------------------------------------------------

class TestBuildAgentCmd:
    def _base_config(self):
        return {
            "explore_agent": "pi",
            "implement_agent": "pi",
            "agents": dict(orc.BUILTIN_AGENTS),
        }

    def _call(self, agent_name="pi", config=None, **kwargs):
        if config is None:
            config = self._base_config()
        defaults = dict(
            prompt="sys prompt",
            task="do stuff",
            model="deepseek-v3",
            provider="openrouter",
            adapters_dir=Path("/skills/orchestrate/adapters"),
        )
        defaults.update(kwargs)
        return orc.build_agent_cmd(agent_name, config, **defaults)

    def test_pi_cmd_substitutes_all_variables(self):
        cmd = self._call("pi", model="deepseek-v3", provider="openrouter")
        assert "deepseek-v3" in cmd
        assert "openrouter" in cmd
        assert "sys prompt" in cmd
        assert "do stuff" in cmd

    def test_cursor_resolves_adapters_dir(self):
        cmd = self._call("cursor", adapters_dir=Path("/my/adapters"))
        assert cmd[0] == "/my/adapters/cursor.sh"

    def test_unknown_agent_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown agent 'ghost'"):
            self._call("ghost")

    def test_missing_cmd_key_raises_value_error(self):
        config = self._base_config()
        config["agents"]["bad"] = {"not_cmd": []}
        with pytest.raises(ValueError, match="missing 'cmd' key"):
            self._call("bad", config=config)

    def test_empty_cmd_list_raises_value_error(self):
        config = self._base_config()
        config["agents"]["bad"] = {"cmd": []}
        with pytest.raises(ValueError, match="non-empty list"):
            self._call("bad", config=config)

    def test_non_list_cmd_raises_value_error(self):
        config = self._base_config()
        config["agents"]["bad"] = {"cmd": "pi {task}"}
        with pytest.raises(ValueError, match="non-empty list"):
            self._call("bad", config=config)

    def test_non_string_token_raises_value_error(self):
        config = self._base_config()
        config["agents"]["bad"] = {"cmd": ["pi", 42, "{task}"]}
        with pytest.raises(ValueError, match="not a string"):
            self._call("bad", config=config)

    def test_unknown_template_variable_raises_value_error(self):
        config = self._base_config()
        config["agents"]["bad"] = {"cmd": ["tool", "{unknown_var}"]}
        with pytest.raises(ValueError, match="unknown template variable"):
            self._call("bad", config=config)

    def test_returns_list_of_strings(self):
        cmd = self._call("gemini")
        assert isinstance(cmd, list)
        for token in cmd:
            assert isinstance(token, str)

    def test_all_builtins_resolve_without_error(self):
        for agent_name in orc.BUILTIN_AGENTS:
            cmd = self._call(agent_name)
            assert isinstance(cmd, list)
            assert len(cmd) > 0


# ---------------------------------------------------------------------------
# phase_setup: agent validation at setup time
# ---------------------------------------------------------------------------

class TestPhaseSetupAgentValidation:
    """Black-box tests: call phase_setup with args that trigger agent validation."""

    def _make_args(self, task="test task", dry_run=True, **kwargs):
        import argparse
        ns = argparse.Namespace(
            phase="setup",
            task=task,
            cwd=str(Path.cwd()),
            artifact_dir=None,
            model="deepseek-v3",
            explore_model="deepseek-v3",
            codex_model="codex-mini-latest",
            claude_model="claude-sonnet-4-5",
            provider="openrouter",
            worktree=None,
            is_retry=False,
            feedback=None,
            explore_timeout=600,
            implement_timeout=600,
            deploy_command=None,
            dry_run=dry_run,
        )
        for k, v in kwargs.items():
            setattr(ns, k, v)
        return ns

    def test_unknown_explore_agent_fails_setup(self, tmp_path, monkeypatch):
        bad_config = {
            "explore_agent": "nonexistent-agent",
            "implement_agent": "pi",
            "agents": dict(orc.BUILTIN_AGENTS),
        }
        monkeypatch.setattr(orc, "load_agent_config", lambda _: bad_config)

        args = self._make_args(dry_run=False)
        result = orc.phase_setup(tmp_path, args)
        assert isinstance(result, int)
        assert result != 0

    def test_unknown_implement_agent_fails_setup(self, tmp_path, monkeypatch):
        bad_config = {
            "explore_agent": "pi",
            "implement_agent": "nonexistent-agent",
            "agents": dict(orc.BUILTIN_AGENTS),
        }
        monkeypatch.setattr(orc, "load_agent_config", lambda _: bad_config)

        args = self._make_args(dry_run=False)
        result = orc.phase_setup(tmp_path, args)
        assert isinstance(result, int)
        assert result != 0

    def test_malformed_cmd_fails_setup(self, tmp_path, monkeypatch):
        bad_config = {
            "explore_agent": "bad-agent",
            "implement_agent": "pi",
            "agents": {
                **orc.BUILTIN_AGENTS,
                "bad-agent": {"cmd": "not-a-list"},
            },
        }
        monkeypatch.setattr(orc, "load_agent_config", lambda _: bad_config)

        args = self._make_args(dry_run=False)
        result = orc.phase_setup(tmp_path, args)
        assert isinstance(result, int)
        assert result != 0

    def test_dry_run_does_not_fail_on_unknown_agent(self, tmp_path, monkeypatch):
        bad_config = {
            "explore_agent": "ghost",
            "implement_agent": "pi",
            "agents": dict(orc.BUILTIN_AGENTS),
        }
        monkeypatch.setattr(orc, "load_agent_config", lambda _: bad_config)

        args = self._make_args(dry_run=True)
        result = orc.phase_setup(tmp_path, args)
        # dry_run skips the hard fail; result may be 0 or non-zero but should not raise
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# phase_explore: build_agent_cmd ValueError produces fail_json
# ---------------------------------------------------------------------------

class TestPhaseExploreAgentError:
    def _make_args(self, task="test task"):
        import argparse
        return argparse.Namespace(
            phase="explore",
            task=task,
            cwd=str(Path.cwd()),
            artifact_dir=None,
            model="deepseek-v3",
            explore_model="deepseek-v3",
            provider="openrouter",
            worktree=None,
            is_retry=False,
            feedback=None,
            explore_timeout=600,
            implement_timeout=600,
            deploy_command=None,
            dry_run=False,
        )

    def test_unknown_explore_agent_returns_nonzero(self, tmp_path, monkeypatch):
        bad_config = {
            "explore_agent": "ghost",
            "implement_agent": "pi",
            "agents": dict(orc.BUILTIN_AGENTS),
        }
        monkeypatch.setattr(orc, "load_agent_config", lambda _: bad_config)
        # Provide a minimal summary.json so the phase can read it
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()
        summary = {
            "taskDescription": "test task",
            "worktree": str(tmp_path / "worktree"),
            "branch": "feature/test",
            "artifactDir": str(artifact_dir),
            "phases": {},
        }
        orc.write_json(artifact_dir / "summary.json", summary)

        args = self._make_args()
        args.artifact_dir = str(artifact_dir)

        result = orc.phase_explore(tmp_path, artifact_dir, args)
        assert isinstance(result, int)
        assert result != 0


# ---------------------------------------------------------------------------
# resolve_agent_config / --implement-agent
# ---------------------------------------------------------------------------

class TestResolveAgentConfig:
    """--implement-agent overrides config.json for a single orchestrate call."""

    def _args(self, implement_agent=""):
        return argparse.Namespace(implement_agent=implement_agent)

    def test_no_override_keeps_config_value(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        config = orc.resolve_agent_config(tmp_path, self._args())
        assert config["implement_agent"] == "aider"

    def test_no_override_keeps_pi_default_when_no_config(self, tmp_path):
        config = orc.resolve_agent_config(tmp_path, self._args())
        assert config["implement_agent"] == "pi"

    def test_override_replaces_config_value(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        config = orc.resolve_agent_config(tmp_path, self._args("opencode"))
        assert config["implement_agent"] == "opencode"

    def test_override_does_not_touch_explore_agent(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"explore_agent": "gemini", "implement_agent": "aider"}),
            encoding="utf-8",
        )
        config = orc.resolve_agent_config(tmp_path, self._args("opencode"))
        assert config["explore_agent"] == "gemini"

    def test_empty_string_override_is_ignored(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        assert orc.resolve_agent_config(tmp_path, self._args(""))["implement_agent"] == "aider"

    def test_missing_attribute_is_treated_as_no_override(self, tmp_path):
        (tmp_path / "config.json").write_text(
            json.dumps({"implement_agent": "aider"}), encoding="utf-8"
        )
        config = orc.resolve_agent_config(tmp_path, argparse.Namespace())
        assert config["implement_agent"] == "aider"

    def test_agents_dict_is_preserved(self, tmp_path):
        config = orc.resolve_agent_config(tmp_path, self._args("opencode"))
        assert "opencode" in config["agents"]
        assert "pi" in config["agents"]

    def test_unknown_override_name_survives_to_validation(self, tmp_path):
        """resolve_ does not validate; phase_setup reports the unknown name."""
        config = orc.resolve_agent_config(tmp_path, self._args("nope"))
        assert config["implement_agent"] == "nope"
        with pytest.raises(ValueError, match="Unknown agent 'nope'"):
            orc.build_agent_cmd(
                "nope", config, prompt="p", task="t",
                model="m", provider="pr", adapters_dir=tmp_path,
            )


class TestImplementAgentArg:
    def test_defaults_to_empty_string(self):
        args = orc.parse_args(["--phase", "setup", "--task", "t"])
        assert args.implement_agent == ""

    def test_accepts_value(self):
        args = orc.parse_args(
            ["--phase", "implement", "--task", "t", "--implement-agent", "opencode"]
        )
        assert args.implement_agent == "opencode"


# ---------------------------------------------------------------------------
# opencode adapter command shape
# ---------------------------------------------------------------------------

class TestOpencodeAdapter:
    def test_opencode_cmd_has_no_print_flag(self):
        """opencode run has no --print; it would fail immediately."""
        assert "--print" not in orc.BUILTIN_AGENTS["opencode"]["cmd"]

    def test_opencode_cmd_skips_permissions(self):
        """Non-interactive runs cannot approve edits, so the flag is required."""
        assert "--dangerously-skip-permissions" in orc.BUILTIN_AGENTS["opencode"]["cmd"]

    def test_opencode_cmd_passes_model(self):
        cmd = orc.BUILTIN_AGENTS["opencode"]["cmd"]
        assert cmd[:2] == ["opencode", "run"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "{model}"

    def test_opencode_cmd_substitutes_model(self, tmp_path):
        config = {"agents": dict(orc.BUILTIN_AGENTS)}
        cmd = orc.build_agent_cmd(
            "opencode", config, prompt="PROMPT", task="TASK",
            model="opencode/mimo-v2.5-free", provider="unused", adapters_dir=tmp_path,
        )
        assert cmd[cmd.index("--model") + 1] == "opencode/mimo-v2.5-free"
        assert "--print" not in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert any("PROMPT" in token and "TASK" in token for token in cmd)

    def test_config_example_matches_builtin(self):
        """config.example.json must not ship the broken --print form."""
        example = Path(__file__).parent.parent / "config.example.json"
        raw = json.loads(example.read_text(encoding="utf-8"))
        cmd = raw["agents"]["opencode"]["cmd"]
        assert "--print" not in cmd
        assert "--dangerously-skip-permissions" in cmd
