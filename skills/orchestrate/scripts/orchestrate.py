#!/usr/bin/env python3
"""Multi-agent orchestrate harness helper."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE_CHOICES = (
    "setup",
    "explore",
    "interview",
    "synthesize-interview",
    "design-plan",
    "verify-design",
    "implement",
    "review-test",
    "complete",
    "pi-complete",
    "pi-deploy",
    "cleanup",
    "resume",
)
FAILED_PHASE_STATUSES = {
    "api_error",
    "blocked",
    "deploy_failed",
    "failed",
    "merge_conflict",
    "no_changes",
    "partial_failure",
    "push_failed",
    "rejected",
    "review_rejected",
    "test_failed",
    "timeout",
    "unclear",
}

PHASE_DEPENDENCIES: dict[str, list[str]] = {
    "explore": ["setup"],
    "interview": ["setup", "explore"],
    "synthesize-interview": ["setup", "interview"],
    "design-plan": ["setup"],
    "verify-design": ["design_plan"],
    "implement": ["setup", "verify_design"],
    "review-test": ["implement"],
    "complete": ["review_test"],
    "pi-complete": ["review_test"],
    "pi-deploy": ["pi_complete"],
    "cleanup": [],
    "resume": [],
}

OMX_TEAM_CLI = "omx"

SKILL_DIR = Path.home() / ".claude" / "skills" / "orchestrate"

BUILTIN_AGENTS: dict[str, dict] = {
    "pi": {"cmd": ["pi", "--print", "--provider", "{provider}", "--model", "{model}",
                   "--no-session", "--no-context-files", "--append-system-prompt", "{prompt}", "{task}"]},
    "opencode": {"cmd": ["opencode", "run", "--model", "{model}", "--print", "{prompt}\n{task}"]},
    "aider": {"cmd": ["aider", "--message", "{prompt}\n{task}", "--yes-always", "--no-git"]},
    "gemini": {"cmd": ["gemini", "-p", "{prompt}\n{task}"]},
    "qwen": {"cmd": ["qwen-code", "--model", "{model}", "--message", "{prompt}\n{task}"]},
    "cursor": {"cmd": ["{adapters_dir}/cursor.sh", "{prompt}", "{task}", "{model}"]},
}


def omx_team_api(operation: str, input_data: dict[str, Any], cwd: Path, timeout: int = 60) -> dict[str, Any]:
    """Call OMX team API via CLI interop (the only non-deprecated mutation path)."""
    cmd = [
        OMX_TEAM_CLI, "team", "api", operation,
        "--input", json.dumps(input_data, ensure_ascii=False),
        "--json",
    ]
    result = run(cmd, cwd, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"omx team api {operation} failed (exit {result.returncode}): {result.stdout[-500:]}")
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"omx team api {operation} returned non-JSON: {result.stdout[-500:]}")
    if not envelope.get("ok"):
        err = envelope.get("error", {})
        raise RuntimeError(f"omx team api {operation} error: {err.get('code', 'unknown')} — {err.get('message', result.stdout[-200:])}")
    return envelope.get("data", {})


def detect_interop_paths(cwd: Path) -> dict[str, Any]:
    """Detect available OMC<->OMX interop communication paths."""
    paths: dict[str, Any] = {
        "omx_cli": False,
        "direct_bridge": False,
        "interop_tools_registered": False,
        "legacy_mcp_available": False,
        "recommended": "none",
        "warnings": [],
    }

    if shutil.which(OMX_TEAM_CLI):
        paths["omx_cli"] = True
        paths["recommended"] = "cli"

    env = os.environ
    bridge_enabled = (
        env.get("OMX_OMC_INTEROP_ENABLED") == "1"
        and env.get("OMC_INTEROP_TOOLS_ENABLED") == "1"
        and env.get("OMX_OMC_INTEROP_MODE", "off").lower() == "active"
    )
    paths["direct_bridge"] = bridge_enabled

    paths["interop_tools_registered"] = env.get("OMC_INTEROP_TOOLS_ENABLED") == "1"

    if not paths["omx_cli"] and not bridge_enabled:
        paths["warnings"].append("No OMX communication path available. Team interop will fail.")
    if not paths["omx_cli"] and bridge_enabled:
        paths["warnings"].append("Direct bridge active but omx CLI not found. Read-only interop only.")
    if bridge_enabled and not paths["interop_tools_registered"]:
        paths["warnings"].append("Bridge flags set but interop tools not registered (OMC_INTEROP_TOOLS_ENABLED!=1).")

    return paths


def load_agent_config(skill_dir: Path) -> dict[str, Any]:
    """Load config.json; fall back to Pi defaults for any missing or malformed keys."""
    config_path = skill_dir / "config.json"
    defaults: dict[str, Any] = {"explore_agent": "pi", "implement_agent": "pi", "agents": dict(BUILTIN_AGENTS)}
    if not config_path.exists():
        return defaults
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"config.json must be a JSON object, got {type(raw).__name__}")
        agents_raw = raw.get("agents", {})
        if not isinstance(agents_raw, dict):
            agents_raw = {}
        merged_agents = {**BUILTIN_AGENTS, **agents_raw}
        return {
            **raw,
            "explore_agent": raw.get("explore_agent", "pi"),
            "implement_agent": raw.get("implement_agent", "pi"),
            "agents": merged_agents,
        }
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return {**defaults, "_config_error": str(exc)}


def build_agent_cmd(agent_name: str, config: dict, *, prompt: str, task: str, model: str, provider: str, adapters_dir: Path) -> list[str]:
    if agent_name not in config["agents"]:
        raise ValueError(f"Unknown agent '{agent_name}'. Add it to config.json or run ./configure.sh.")
    agent_def = config["agents"][agent_name]
    if not isinstance(agent_def, dict) or "cmd" not in agent_def:
        raise ValueError(f"Agent '{agent_name}' config is missing 'cmd' key.")
    raw_cmd = agent_def["cmd"]
    if not isinstance(raw_cmd, list) or not raw_cmd:
        raise ValueError(f"Agent '{agent_name}' 'cmd' must be a non-empty list.")
    for i, token in enumerate(raw_cmd):
        if not isinstance(token, str):
            raise ValueError(f"Agent '{agent_name}' cmd[{i}] is {type(token).__name__!r}, not a string.")
    variables = {"prompt": prompt, "task": task, "model": model,
                 "provider": provider, "adapters_dir": str(adapters_dir)}
    try:
        return [token.format(**variables) for token in raw_cmd]
    except KeyError as exc:
        raise ValueError(
            f"Agent '{agent_name}' cmd references unknown template variable {exc}. "
            f"Valid variables: {sorted(variables.keys())}"
        ) from exc


CODEX_API_ERROR_PATTERNS = [
    "you've hit your usage limit",
    "upgrade to pro",
    "rate_limit_exceeded",
    "error: rate limit",
    "tokenauthenticationerror",
    "401 unauthorized",
    "invalid api key",
    "incorrect api key",
    "insufficient_quota",
    "internal server error",
    "503 service unavailable",
    "connection refused",
    "connection reset",
]

RMCP_NOISE_MARKERS = [
    " rmcp::",
    " mcp::",
]

SENSITIVE_FILE_PATTERNS = [
    r"(^|/)\.env($|\.)",
    r"\.(pem|key|p12|pfx|jks)$",
    r"(^|/)credentials(\.|$)",
    r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$",
    r"(^|/)\.secret",
    r"(^|/)secret[s]?(\.|/|$)",
]

CODEX_BANNER_MARKERS = [
    "Reading additional input from stdin",
    "OpenAI Codex v",
    "--------",
    "workdir:",
    "model:",
    "provider:",
    "approval:",
    "sandbox:",
    "reasoning effort:",
    "reasoning summaries:",
    "session id:",
]


class PhaseLogger:
    """Write one structured log file for one orchestrate phase."""

    def __init__(self, artifact_dir: Path, phase_num: int, phase_name: str, is_retry: bool = False):
        logs_dir = artifact_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        suffix = "-retry" if is_retry else ""
        self.log_path = logs_dir / f"phase-{phase_num}-{phase_name}{suffix}.log"
        self.phase_num = phase_num
        self.phase_name = phase_name
        self.start_time: datetime | None = None
        self._lines: list[str] = []

    def start(self, cmd: str = "", cwd: str = "") -> None:
        self.start_time = datetime.now(timezone.utc)
        self._lines.append(f"[START] Phase {self.phase_num}: {self.phase_name.upper()}")
        self._lines.append(f"[TIME]  {self.start_time.isoformat()}")
        if cmd:
            self._lines.append(f"[CMD]   {cmd}")
        if cwd:
            self._lines.append(f"[CWD]   {cwd}")
        self._lines.append("---")

    def log(self, text: str) -> None:
        self._lines.append(text)

    def finish(self, exit_code: int, status: str) -> None:
        end_time = datetime.now(timezone.utc)
        duration = int((end_time - self.start_time).total_seconds()) if self.start_time else 0
        self._lines.append("---")
        self._lines.append(f"[EXIT]  {exit_code}")
        self._lines.append(f"[TIME]  {end_time.isoformat()}")
        self._lines.append(f"[DURATION] {duration}s")
        self._lines.append(f"[STATUS] {status}")
        self._lines.append("[END]")
        self.log_path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self.log_path


def run(cmd: list[str], cwd: Path, timeout: int = 600, text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        input=text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def run_test_command(command: str, cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        shlex.split(command),
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def git_root(cwd: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], cwd)
    if result.returncode != 0:
        raise RuntimeError("Not a git repository")
    return Path(result.stdout.strip()).resolve()


def create_artifact_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = root / ".omx" / "artifacts" / "orchestrate"
    for attempt in range(100):
        suffix = "" if attempt == 0 else f"-{attempt:02d}"
        path = base / f"{stamp}{suffix}"
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise RuntimeError("Could not create unique artifact directory")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_artifact(artifact_dir: Path, name: str, limit: int = 4000, required: bool = False) -> str:
    path = artifact_dir / name
    if not path.exists():
        if required:
            raise RuntimeError(f"{name} not found in artifact directory")
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def write_artifact(artifact_dir: Path, name: str, content: str) -> Path:
    relative_name = Path(name)
    if relative_name.is_absolute() or relative_name.name != name:
        raise RuntimeError(f"artifact name must be a plain filename: {name}")
    path = artifact_dir / name
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def write_orchestrate_lock(root: Path, session_info: str) -> None:
    lock = root / ".omx" / ".orchestrate-active"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(session_info, encoding="utf-8")


def remove_orchestrate_lock(root: Path) -> None:
    lock = root / ".omx" / ".orchestrate-active"
    lock.unlink(missing_ok=True)


def validate_phase_dependencies(
    phase_cli: str, summary: dict[str, Any], skip: set[str] | None = None
) -> str | None:
    phase_key = phase_cli.replace("-", "_")
    deps = PHASE_DEPENDENCIES.get(phase_cli, PHASE_DEPENDENCIES.get(phase_key, []))
    if skip:
        deps = [d for d in deps if d not in skip]
    phases = summary.get("phases", {})
    missing = []
    for dep in deps:
        dep_status = phases.get(dep, {}).get("status")
        if dep_status not in ("success", "dry_run"):
            missing.append(f"{dep} (status: {dep_status or 'not run'})")
    if missing:
        return f"Unmet dependencies for {phase_cli}: {', '.join(missing)}"
    return None


RESUME_PHASE_ORDER = (
    "setup",
    "explore",
    "verify_design",
    "implement",
    "review_test",
    "complete",
)


def compute_next_phase(summary: dict[str, Any]) -> str | None:
    """First helper phase in the main /orchestrate pipeline not yet completed.

    Returns the underscore phase key (e.g. "verify_design"), or None when the
    pipeline is done. Operates only over helper-recorded phases in
    summary["phases"]; Claude-side steps (clarify, design, write-tests, review
    gate) are not recorded here and must be verified from artifacts by the SKILL
    resume flow before running the returned phase.
    """
    phases = summary.get("phases", {})
    for name in RESUME_PHASE_ORDER:
        status = phases.get(name, {}).get("status")
        if status not in ("success", "dry_run"):
            return name
    return None


RESUME_STATE_FILE = "resume-state.json"


def read_resume_state(artifact_dir: Path) -> dict[str, Any]:
    path = artifact_dir / RESUME_STATE_FILE
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except (json.JSONDecodeError, OSError):
        return {}


def write_resume_state(
    artifact_dir: Path,
    summary: dict[str, Any],
    *,
    task: str | None = None,
    tmux_session: str | None = None,
    reset_at: str | None = None,
) -> dict[str, Any]:
    state = read_resume_state(artifact_dir)
    state["artifactDir"] = str(artifact_dir)
    state["nextPhase"] = compute_next_phase(summary)
    state["heartbeat"] = now_iso()
    state["finalStatus"] = summary.get("finalStatus")
    if task is not None:
        state["task"] = task
    else:
        state.setdefault("task", summary.get("taskDescription", ""))
    if tmux_session is not None:
        state["tmuxSession"] = tmux_session
    else:
        state.setdefault("tmuxSession", "")
    if reset_at is not None:
        state["resetAt"] = reset_at
    state.setdefault("relaunchCount", 0)
    write_json(artifact_dir / RESUME_STATE_FILE, state)
    return state


def update_resume_state_if_present(artifact_dir: Path) -> None:
    """Refresh the checkpoint heartbeat/nextPhase after a phase, but only when
    auto-resume armed this run (the resume-state file exists)."""
    if not (artifact_dir / RESUME_STATE_FILE).exists():
        return
    summary_path = artifact_dir / "summary.json"
    if not summary_path.exists():
        return
    try:
        summary = read_json(summary_path)
    except (json.JSONDecodeError, OSError):
        return
    write_resume_state(artifact_dir, summary)


def detect_tmux_session() -> str:
    if not os.environ.get("TMUX"):
        return ""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


WATCHER_SCRIPT = "orchestrate_watcher.py"


def watcher_is_running(artifact_dir: Path) -> bool:
    pid_path = artifact_dir / "watcher.pid"
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def spawn_watcher(artifact_dir: Path, root: Path) -> None:
    if watcher_is_running(artifact_dir):
        return
    script = Path(__file__).resolve().parent / WATCHER_SCRIPT
    subprocess.Popen(
        [sys.executable, str(script), "--artifact-dir", str(artifact_dir),
         "--root", str(root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(root),
    )


def kill_watcher(artifact_dir: Path) -> None:
    pid_path = artifact_dir / "watcher.pid"
    if not pid_path.exists():
        return
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid_path.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    pid_path.unlink(missing_ok=True)


def fence_user_input(label: str, content: str) -> str:
    tag = f"user-{label}"
    safe = content.replace(f"</{tag}>", f"&lt;/{tag}&gt;")
    return f"<{tag}>\n{safe}\n</{tag}>"


_SANITIZE_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"), "sk-***"),
    (re.compile(r"\bkey-[A-Za-z0-9]{8,}\b"), "key-***"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"), "Bearer ***"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"), "ghp_***"),
    (re.compile(r"\bgho_[A-Za-z0-9]{36,}\b"), "gho_***"),
]


def sanitize_output(text: str) -> str:
    for pattern, replacement in _SANITIZE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def filter_sensitive_files(files: list[str]) -> list[str]:
    compiled = [re.compile(p) for p in SENSITIVE_FILE_PATTERNS]
    return [f for f in files if not any(pat.search(f) for pat in compiled)]


def slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9가-힣._-]+", "-", slug)
    slug = "-".join(part for part in slug.split("-") if part)
    return (slug or "task")[:50].strip("-") or "task"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def phase_record(status: str, logger: PhaseLogger, **extra: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "status": status,
        "timestamp": now_iso(),
        "log": str(logger.path),
    }
    record.update(extra)
    return record


def has_failed_phase(summary: dict[str, Any]) -> bool:
    phases = summary.get("phases", {})
    return any(phase.get("status") in FAILED_PHASE_STATUSES for phase in phases.values() if isinstance(phase, dict))


def mark_summary_failed(summary: dict[str, Any], error: str) -> None:
    summary["finalStatus"] = "failed"
    summary["error"] = error


def fail_json(
    *,
    phase: str,
    error: str,
    artifact_dir: Path | None = None,
    exit_code: int = 1,
    extra: dict[str, Any] | None = None,
) -> int:
    out: dict[str, Any] = {"status": "failed", "phase": phase, "error": sanitize_output(error)}
    if artifact_dir:
        out["artifactDir"] = str(artifact_dir)
    if extra:
        out.update(extra)
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":"))
)
    return exit_code


def ensure_summary(artifact_dir: Path) -> dict[str, Any]:
    summary_path = artifact_dir / "summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"summary.json not found: {summary_path}")
    return read_json(summary_path)


def _strip_rmcp_noise(output: str) -> str:
    """Remove RMCP/MCP transport log lines that are not actual Codex API errors."""
    lines = output.splitlines()
    return "\n".join(
        line for line in lines
        if not any(marker in line.lower() for marker in RMCP_NOISE_MARKERS)
    )


def is_codex_api_error(output: str) -> bool:
    """Detect transient Codex API/infrastructure errors (not genuine rejections)."""
    cleaned = _strip_rmcp_noise(output)
    lower = cleaned.lower()
    return any(pattern in lower for pattern in CODEX_API_ERROR_PATTERNS)


def classify_codex_error(output: str) -> str:
    """Return a human-readable root-cause diagnosis for a Codex API error."""
    cleaned = _strip_rmcp_noise(output)
    lower = cleaned.lower()
    if "you've hit your usage limit" in lower or "upgrade to pro" in lower:
        return "usage_limit — Plus/Pro 사용량 한도 초과. 시간 경과 후 재시도하거나 플랜 업그레이드 필요"
    if "rate_limit_exceeded" in lower or "error: rate limit" in lower:
        return "rate_limit — 요청 빈도 제한. 요청 간격을 늘리거나 잠시 후 재시도"
    if "tokenauthenticationerror" in lower or "401 unauthorized" in lower:
        return "auth_failed — 인증 실패. codex CLI 로그인 상태 확인 (codex login)"
    if "invalid api key" in lower or "incorrect api key" in lower:
        return "api_key — API 키 누락 또는 무효. OPENAI_API_KEY 환경변수 또는 codex config 확인"
    if "insufficient_quota" in lower:
        return "quota_exhausted — API 할당량 소진. 결제 정보 또는 플랜 확인"
    if "internal server error" in lower or "503 service unavailable" in lower:
        return "server_error — OpenAI 서버 오류. 일시적 장애일 수 있으므로 잠시 후 재시도"
    if "connection refused" in lower or "connection reset" in lower:
        return "connection_error — 네트워크 연결 실패. 인터넷 및 OpenAI 서비스 상태 확인"
    return "unknown_api_error — 분류 불가. 로그의 원본 출력을 직접 확인하세요"


def strip_codex_banner(output: str) -> str:
    """Strip Codex CLI banner metadata and RMCP noise from output.

    Codex CLI output format: banner → user prompt → codex response → 'tokens used' →
    count → verdict summary (repeated). Extract the verdict summary after 'tokens used'
    when available, otherwise fall back to the response after the role marker.
    """
    lines = [
        line for line in output.splitlines()
        if not any(marker in line.lower() for marker in RMCP_NOISE_MARKERS)
    ]
    content_start = 0
    in_banner = True
    seen_separator = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not in_banner:
            break
        if stripped == "--------":
            seen_separator += 1
            if seen_separator >= 2:
                content_start = i + 1
                in_banner = False
                continue
        if any(stripped.startswith(marker) for marker in CODEX_BANNER_MARKERS):
            content_start = i + 1
            continue
        if seen_separator == 0 and not stripped:
            content_start = i + 1
            continue
        break

    remaining = "\n".join(lines[content_start:]).strip()

    if remaining.startswith("user\n"):
        for role_marker in ["\nassistant\n", "\ncodex\n"]:
            prompt_end = remaining.find(role_marker)
            if prompt_end != -1:
                remaining = remaining[prompt_end + len(role_marker):]
                break
        else:
            remaining = remaining[5:]

    tokens_idx = remaining.rfind("\ntokens used\n")
    if tokens_idx != -1:
        after_tokens = remaining[tokens_idx + len("\ntokens used\n"):]
        newline_pos = after_tokens.find("\n")
        if newline_pos != -1:
            summary = after_tokens[newline_pos + 1:].strip()
            if summary:
                return summary

    return remaining.strip()


def parse_codex_verdict(output: str) -> tuple[str, str]:
    """Parse the Codex verdict by scanning every line of the cleaned output.

    Returns ("approved"|"rejected", line) on the first matching verdict line.
    If no verdict line exists, returns ("unclear", text). This function never
    infers "api_error" from body content -- transient-error detection is done
    separately and is gated on a non-zero Codex exit code.
    """
    cleaned = strip_codex_banner(output)
    text = cleaned or output.strip()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("APPROVED"):
            return "approved", stripped
        if upper.startswith("REJECTED"):
            return "rejected", stripped

    return "unclear", text[:2000]


def parse_prefixed_verdict(output: str, success_prefix: str) -> tuple[str, str]:
    for line in output.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith(success_prefix.upper()):
            return "success", stripped
        if upper.startswith("FAILED"):
            return "failed", stripped
        break
    return "unclear", output.strip()[:2000]


def detect_test_command(root: Path) -> str:
    package_json = root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            if "test" in scripts:
                return "npm test"
            if "typecheck" in scripts:
                return "npm run typecheck"
        except Exception:
            pass
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        return "python3 -m pytest"
    if (root / "go.mod").exists():
        return "go test ./..."
    if (root / "Cargo.toml").exists():
        return "cargo test"
    makefile = root / "Makefile"
    if makefile.exists() and "test:" in makefile.read_text(encoding="utf-8", errors="replace"):
        return "make test"
    return ""


def repo_snapshot(root: Path) -> set[str]:
    result = run(["git", "ls-files", "-co", "--exclude-standard"], root)
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.splitlines() if line}


def changed_files(root: Path, before_files: set[str] | None = None) -> list[str]:
    diff_result = run(["git", "diff", "--name-only"], root)
    changed = [line for line in diff_result.stdout.splitlines() if line] if diff_result.returncode == 0 else []
    cached_result = run(["git", "diff", "--cached", "--name-only"], root)
    cached = [line for line in cached_result.stdout.splitlines() if line] if cached_result.returncode == 0 else []
    untracked = sorted(repo_snapshot(root) - before_files) if before_files is not None else []
    return sorted(set(changed + cached + untracked))


def read_untracked_files(root: Path, paths: list[str], limit: int = 2000) -> str:
    sections: list[str] = []
    remaining = limit
    for rel_path in paths:
        if remaining <= 0:
            break
        path = root / rel_path
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        excerpt = content[:remaining]
        sections.append(f"### {rel_path}\n\n```\n{excerpt}\n```")
        remaining -= len(excerpt)
    return "\n\n".join(sections)


def extract_section(content: str, title: str) -> str:
    pattern = rf"(?ims)^# {re.escape(title)}\s*(.*?)(?=^# |\Z)"
    match = re.search(pattern, content)
    return match.group(1).strip() if match else ""


def extract_questions(content: str) -> str:
    matches = list(re.finditer(r"(?ims)^# Questions\s*(.*?)(?=^# |\Z)", content))
    body = matches[-1].group(1).strip() if matches else content
    lines = [
        line.strip()
        for line in body.splitlines()
        if re.match(r"^\d+[\.)]\s+", line.strip()) or "[CRITICAL]" in line
    ]
    return "# Questions\n\n" + ("\n".join(lines).strip() or "- No questions extracted.")


def make_interview_input_template(questions: str) -> str:
    return f"""# Interview Input

Answer below each question. Keep the raw interview in this file inside the current artifactDir so the orchestration phases can stay artifact-based instead of chat-based.

{questions}

## Answers

1.
2.
3.
"""


def codex_exec(
    root: Path, model: str, prompt: str, timeout: int, logger: PhaseLogger | None = None,
) -> subprocess.CompletedProcess[str]:
    import tempfile
    import time

    def _invoke() -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(
            "w+", suffix=".txt", delete=False, encoding="utf-8"
        ) as handle:
            last_msg_path = handle.name
        cmd = [
            "codex", "exec", "--cd", str(root), "--model", model,
            "--sandbox", "read-only", "--ephemeral",
            "-o", last_msg_path, prompt,
        ]
        proc = run(cmd, root, timeout=timeout)
        try:
            last = Path(last_msg_path).read_text(encoding="utf-8").strip()
        except OSError:
            last = ""
        finally:
            try:
                os.unlink(last_msg_path)
            except OSError:
                pass
        # Prefer the clean last message; fall back to the full transcript.
        if last:
            proc = subprocess.CompletedProcess(proc.args, proc.returncode, last, proc.stderr)
        return proc

    result = _invoke()
    if result.returncode != 0 and is_codex_api_error(result.stdout):
        cause = classify_codex_error(result.stdout)
        if logger:
            logger.log(f"[CODEX ERROR] exit={result.returncode} model={model}")
            logger.log(f"[CODEX ERROR] cause: {cause}")
            logger.log(f"[CODEX ERROR] raw output (last 1500):\n{sanitize_output(result.stdout[-1500:])}")
            logger.log("[CODEX RETRY] waiting 5s before retry...")
        time.sleep(5)
        result = _invoke()
        if logger:
            if result.returncode != 0:
                retry_cause = classify_codex_error(result.stdout) if is_codex_api_error(result.stdout) else "non_api_error"
                logger.log(f"[CODEX RETRY FAILED] exit={result.returncode} cause: {retry_cause}")
                logger.log(f"[CODEX RETRY FAILED] raw output (last 1500):\n{sanitize_output(result.stdout[-1500:])}")
            else:
                logger.log("[CODEX RETRY OK] retry succeeded")
    return result


def claude_exec(root: Path, model: str, prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    cmd = [
        "claude",
        "-p",
        "--model",
        model,
        "--permission-mode",
        "plan",
        "--output-format",
        "text",
        "--tools",
        "",
        prompt,
    ]
    return run(cmd, root, timeout=timeout)


def current_head(root: Path) -> str:
    result = run(["git", "rev-parse", "HEAD"], root, timeout=60)
    return result.stdout.strip() if result.returncode == 0 else ""


def current_branch(root: Path) -> str:
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root, timeout=60)
    return result.stdout.strip() if result.returncode == 0 else ""


def tracked_status(root: Path) -> str:
    result = run(["git", "status", "--short", "--untracked-files=no"], root, timeout=60)
    return result.stdout.strip() if result.returncode == 0 else ""


def untracked_status(root: Path) -> str:
    result = run(["git", "status", "--short"], root, timeout=60)
    if result.returncode != 0:
        return ""
    lines = [line for line in result.stdout.splitlines() if line.startswith("?? ")]
    return "\n".join(lines)


def remote_branch_head(root: Path, branch: str) -> str:
    result = run(["git", "ls-remote", "--heads", "origin", branch], root, timeout=60)
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.split()[0]


def run_codex_phase(
    *,
    artifact_dir: Path,
    worktree: Path,
    args: argparse.Namespace,
    phase_key: str,
    phase_num: int,
    output_name: str,
    prompt: str,
    placeholder: str,
    verdict_required: bool = False,
) -> int:
    summary = ensure_summary(artifact_dir)
    logger = PhaseLogger(artifact_dir, phase_num, phase_key.replace("_", "-"), is_retry=args.is_retry)
    logger.start(cmd=f"codex exec --sandbox read-only --model {args.codex_model} [{phase_key}]", cwd=str(worktree))
    output_path = artifact_dir / output_name

    if args.dry_run:
        output_path.write_text(placeholder.rstrip() + "\n", encoding="utf-8")
        logger.log(f"[DRY RUN] Wrote placeholder {output_name}")
        logger.finish(0, "dry_run")
        summary["phases"][phase_key] = phase_record("dry_run", logger, output=str(output_path))
        summary.setdefault("files", {})[phase_key] = str(output_path)
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": phase_key, "output": str(output_path), "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    try:
        result_proc = codex_exec(worktree, args.codex_model, prompt, args.agent_timeout, logger=logger)
    except subprocess.TimeoutExpired:
        logger.log(f"[TIMEOUT] Codex exceeded {args.agent_timeout}s")
        logger.finish(124, "failed")
        summary["phases"][phase_key] = phase_record("timeout", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase=phase_key, error=f"Codex timeout ({args.agent_timeout}s)", artifact_dir=artifact_dir, exit_code=124)

    output = result_proc.stdout
    logger.log(sanitize_output(output))
    cleaned_output = strip_codex_banner(output)
    output_path.write_text((cleaned_output or output).rstrip() + "\n", encoding="utf-8")

    if result_proc.returncode != 0:
        if is_codex_api_error(output):
            cause = classify_codex_error(output)
            logger.log(f"[DIAGNOSIS] {cause}")
            logger.finish(result_proc.returncode, "api_error")
            summary["phases"][phase_key] = phase_record("api_error", logger, output=str(output_path), cause=cause)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase=phase_key,
                error=f"Codex API error ({cause})",
                artifact_dir=artifact_dir,
                exit_code=result_proc.returncode,
                extra={"retriable": True, "cause": cause},
            )
        logger.finish(result_proc.returncode, "failed")
        summary["phases"][phase_key] = phase_record("failed", logger, output=str(output_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase=phase_key, error=(output or f"Codex exited {result_proc.returncode}")[-2000:], artifact_dir=artifact_dir, exit_code=result_proc.returncode)

    if verdict_required:
        verdict, details = parse_codex_verdict(output)
        if verdict == "api_error":
            cause = classify_codex_error(output)
            logger.log(f"[DIAGNOSIS] {cause}")
            logger.finish(1, "api_error")
            summary["phases"][phase_key] = phase_record("api_error", logger, output=str(output_path), cause=cause)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase=phase_key,
                error=f"Codex API error ({cause})",
                artifact_dir=artifact_dir,
                extra={"retriable": True, "cause": cause},
            )
        if verdict != "approved":
            logger.finish(1, "failed")
            summary["phases"][phase_key] = phase_record(verdict, logger, output=str(output_path), verdict=details)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase=phase_key,
                error=f"Codex verdict {verdict}: {details[:500]}",
                artifact_dir=artifact_dir,
                extra={"codexFeedback": output[-2000:]},
            )
        summary["phases"][phase_key] = phase_record("success", logger, output=str(output_path), verdict=details)
    else:
        summary["phases"][phase_key] = phase_record("success", logger, output=str(output_path))

    logger.finish(0, "success")
    summary.setdefault("files", {})[phase_key] = str(output_path)
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": phase_key, "output": str(output_path), "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_setup(root: Path, args: argparse.Namespace) -> int:
    artifact_dir = Path(args.artifact_dir).resolve() if args.artifact_dir else create_artifact_dir(root)
    logger = PhaseLogger(artifact_dir, 0, "setup")
    logger.start(cmd="git worktree add + prerequisite check", cwd=str(root))

    # codex and claude are always required — they are orchestration tools, not swappable agents
    codex_bin = shutil.which("codex")
    claude_bin = shutil.which("claude")
    missing = [name for name, value in (("codex", codex_bin), ("claude", claude_bin)) if not value]
    if missing and not args.dry_run:
        err = f"Missing required CLIs: {', '.join(missing)}"
        logger.log(err)
        logger.finish(1, "failed")
        return fail_json(phase="setup", error=err, artifact_dir=artifact_dir)

    if args.dry_run:
        logger.log("[DRY RUN] Skipping prerequisite command checks")

    # Agent config validation
    agent_config = load_agent_config(SKILL_DIR)
    if "_config_error" in agent_config:
        logger.log(f"[CONFIG WARNING] Malformed config.json: {agent_config['_config_error']} — falling back to Pi defaults")
    configured_agents = {agent_config["explore_agent"], agent_config["implement_agent"]}

    # Agent definition validation: unknown name and malformed cmd are hard config errors;
    # missing binary is warn-only (binary may be installed later)
    adapters_dir = SKILL_DIR / "adapters"
    config_agents = agent_config["agents"]
    for role in ("explore_agent", "implement_agent"):
        agent_name = agent_config[role]
        if agent_name not in config_agents:
            err = f"{role} '{agent_name}' is not in the agents list. Check config.json or run ./configure.sh."
            logger.log(f"[CONFIG ERROR] {err}")
            if not args.dry_run:
                logger.finish(1, "failed")
                return fail_json(phase="setup", error=err, artifact_dir=artifact_dir)
        else:
            agent_def = config_agents[agent_name]
            # Validate cmd shape now so malformed definitions fail at setup, not mid-pipeline
            if not isinstance(agent_def, dict):
                err = f"{role} '{agent_name}' config must be a JSON object, got {type(agent_def).__name__}."
                logger.log(f"[CONFIG ERROR] {err}")
                if not args.dry_run:
                    logger.finish(1, "failed")
                    return fail_json(phase="setup", error=err, artifact_dir=artifact_dir)
            else:
                raw_cmd = agent_def.get("cmd")
                if not isinstance(raw_cmd, list) or not raw_cmd:
                    err = f"{role} '{agent_name}' 'cmd' must be a non-empty list."
                    logger.log(f"[CONFIG ERROR] {err}")
                    if not args.dry_run:
                        logger.finish(1, "failed")
                        return fail_json(phase="setup", error=err, artifact_dir=artifact_dir)
                elif not isinstance(raw_cmd[0], str):
                    err = f"{role} '{agent_name}' cmd[0] must be a string, got {type(raw_cmd[0]).__name__}."
                    logger.log(f"[CONFIG ERROR] {err}")
                    if not args.dry_run:
                        logger.finish(1, "failed")
                        return fail_json(phase="setup", error=err, artifact_dir=artifact_dir)
                else:
                    bin_path = raw_cmd[0].replace("{adapters_dir}", str(adapters_dir))
                    if bin_path.endswith(".sh"):
                        if not Path(bin_path).exists():
                            logger.log(f"[AGENT WARNING] {role} adapter script not found: {bin_path}")
                    elif bin_path and not shutil.which(bin_path):
                        logger.log(f"[AGENT WARNING] {role} agent binary '{bin_path}' not found — install it before running /orchestrate")

    # Pi provider check: fail-fast for Pi users (preserves backward compatibility)
    if not args.dry_run and "pi" in configured_agents:
        try:
            pi_models = run(["pi", "--list-models", args.provider], root, timeout=60)
            logger.log("$ pi --list-models " + args.provider)
            logger.log(pi_models.stdout)
            if pi_models.returncode != 0 or args.provider not in pi_models.stdout:
                err = f"Pi CLI provider unavailable: {args.provider}. Check `pi --list-models {args.provider}`."
                logger.finish(1, "failed")
                return fail_json(phase="setup", error=err, artifact_dir=artifact_dir)
        except (FileNotFoundError, OSError) as exc:
            logger.log(f"[AGENT WARNING] pi not found — cannot verify provider: {exc}")

    interop_paths = detect_interop_paths(root)
    if interop_paths["warnings"]:
        for w in interop_paths["warnings"]:
            logger.log(f"[INTEROP WARNING] {w}")

    slug = slugify(args.task)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    branch = f"feature/{slug}-{timestamp}"
    worktree_path = root / ".worktrees" / f"orchestrate-{timestamp}"
    summary = {
        "taskDescription": args.task,
        "worktree": str(worktree_path),
        "branch": branch,
        "artifactDir": str(artifact_dir),
        "provider": args.provider,
        "model": args.model,
        "codexModel": args.codex_model,
        "claudeModel": args.claude_model,
        "interop": interop_paths,
        "files": {},
        "phases": {},
        "finalStatus": "in_progress",
        "error": None,
        "mergedCommit": None,
    }

    def _arm_auto_resume() -> None:
        if not getattr(args, "auto_resume", False):
            return
        tmux_session = detect_tmux_session()
        write_resume_state(artifact_dir, summary, task=args.task,
                           tmux_session=tmux_session)
        spawn_watcher(artifact_dir, root)
        logger.log(f"[AUTO-RESUME] watcher armed (tmux={tmux_session or 'none'})")

    if args.dry_run:
        logger.log(f"[DRY RUN] Would create worktree {worktree_path} on branch {branch}")
        logger.finish(0, "dry_run")
        summary["phases"]["setup"] = phase_record("dry_run", logger)
        write_json(artifact_dir / "summary.json", summary)
        _arm_auto_resume()
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    cmd = ["git", "worktree", "add", str(worktree_path), "-b", branch]
    logger.log("$ " + " ".join(cmd))
    result_proc = run(cmd, root)
    logger.log(result_proc.stdout)
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        return fail_json(phase="setup", error=result_proc.stdout.strip(), artifact_dir=artifact_dir, exit_code=result_proc.returncode)

    write_orchestrate_lock(root, f"{branch} | {artifact_dir}")
    logger.finish(0, "success")
    summary["phases"]["setup"] = phase_record("success", logger)
    write_json(artifact_dir / "summary.json", summary)
    _arm_auto_resume()
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_explore(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    logger = PhaseLogger(artifact_dir, 1, "explore")
    system_prompt = (
        "Explore this codebase and produce a structured report containing: "
        "1) file/directory structure overview, 2) key modules and responsibilities, "
        "3) dependency graph between modules, 4) code patterns and conventions, "
        f"5) areas most relevant to this task: {args.task}"
    )
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    agent_name = agent_config["explore_agent"]
    # Always include a no-edit instruction in the task regardless of which agent is configured.
    # This preserves task specificity while enforcing the read-only contract.
    explore_task = f"Explore the repository for task: {args.task}. Do not edit, create, or delete any files."
    try:
        cmd = build_agent_cmd(agent_name, agent_config, prompt=system_prompt, task=explore_task,
                              model=args.explore_model, provider=args.provider, adapters_dir=adapters_dir)
    except ValueError as exc:
        logger.start(cmd=f"{agent_name} [explore] model={args.explore_model}", cwd=str(worktree))
        logger.log(f"[AGENT ERROR] {exc}")
        logger.finish(1, "failed")
        summary["phases"]["explore"] = phase_record("failed", logger, error=str(exc))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="explore", error=str(exc), artifact_dir=artifact_dir)
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
    logger.start(cmd=f"{agent_name} [explore] model={args.explore_model}", cwd=str(worktree))

    if args.dry_run:
        output = f"# Dry Run Explore Report\n\n{agent_name} execution skipped.\n"
        report_path = artifact_dir / "explore-report.md"
        report_path.write_text(output, encoding="utf-8")
        logger.log("[DRY RUN] Wrote placeholder explore-report.md")
        logger.finish(0, "dry_run")
        summary["phases"]["explore"] = phase_record("dry_run", logger, report=str(report_path))
        summary.setdefault("files", {})["exploreReport"] = str(report_path)
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "explore", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    try:
        result_proc = run(cmd, worktree, timeout=args.explore_timeout)
    except subprocess.TimeoutExpired:
        logger.log(f"[TIMEOUT] {agent_name} exceeded {args.explore_timeout}s timeout")
        logger.finish(124, "failed")
        summary["phases"]["explore"] = phase_record("timeout", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="explore", error=f"{agent_name} timeout ({args.explore_timeout}s)", artifact_dir=artifact_dir, exit_code=124)

    logger.log(result_proc.stdout)
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["explore"] = phase_record("failed", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="explore",
            error=(result_proc.stdout or f"Unknown {agent_name} error")[-2000:],
            artifact_dir=artifact_dir,
            exit_code=result_proc.returncode,
        )

    report_path = artifact_dir / "explore-report.md"
    report_path.write_text(result_proc.stdout, encoding="utf-8")
    logger.finish(0, "success")
    summary["phases"]["explore"] = phase_record("success", logger, report=str(report_path))
    summary.setdefault("files", {})["exploreReport"] = str(report_path)
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "explore", "report": str(report_path), "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_interview(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    explore = read_artifact(artifact_dir, "explore-report.md", required=True)
    prompt = f"""You are a skeptical product interviewer preparing a Codex-run interview packet for an existing codebase change.

Do not propose implementation code. Use the repository context to surface ambiguities and risky assumptions.

## Task

{fence_user_input("task", args.task)}

## Codebase Context

{explore}

## Output

Write Markdown with exactly these top-level headings:

# Interview Strategy
# Questions

Under Interview Strategy, challenge contradictions, risky assumptions, hidden stakeholders, integration boundaries, and dangerous scope creep.
Under Questions, provide 8-12 prioritized interview questions. Mark the 3 most important questions with [CRITICAL].
"""
    placeholder = """# Interview Strategy

- Dry-run critique placeholder.

# Questions

1. [CRITICAL] Which workflow must succeed end to end?
2. [CRITICAL] What is explicitly out of scope?
3. [CRITICAL] Which repos or deploy paths must remain untouched?
"""
    result = run_codex_phase(
        artifact_dir=artifact_dir,
        worktree=worktree,
        args=args,
        phase_key="interview",
        phase_num=2,
        output_name="interview.md",
        prompt=prompt,
        placeholder=placeholder,
    )
    interview_path = artifact_dir / "interview.md"
    if interview_path.exists():
        content = interview_path.read_text(encoding="utf-8", errors="replace")
        questions = extract_questions(content)
        questions_path = write_artifact(artifact_dir, "questions.md", questions)
        input_path = write_artifact(artifact_dir, "interview-input.md", make_interview_input_template(questions))
        summary = ensure_summary(artifact_dir)
        summary.setdefault("files", {})["questions"] = str(questions_path)
        summary.setdefault("files", {})["interviewInput"] = str(input_path)
        write_json(artifact_dir / "summary.json", summary)
    return result


def phase_synthesize_interview(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    explore = read_artifact(artifact_dir, "explore-report.md")
    interview = read_artifact(artifact_dir, "interview.md")
    interview_input = read_artifact(artifact_dir, "interview-input.md")
    if not interview_input and not args.dry_run:
        return fail_json(
            phase="synthesize-interview",
            error="interview-input.md is required before interview synthesis",
            artifact_dir=artifact_dir,
        )

    prompt = f"""You are synthesizing a Codex-run implementation interview for an existing codebase task.

Do not write code. Compress the interview into an execution-ready intent summary for a separate architecture/planning model.

## Task

{args.task}

## Codebase Context

{explore}

## Interview Packet

{interview}

## Raw Interview Input

{interview_input}

## Output

Write exactly these top-level headings:

# Interview Transcript
# Answers
# Intent Summary

Under Intent Summary, include objective, in scope, out of scope, constraints, success criteria, risks, affected areas, rollout notes, and defaults that should be assumed during design.
"""
    placeholder = """# Interview Transcript

Dry-run transcript placeholder.

# Answers

- Dry-run answer placeholder.

# Intent Summary

- Objective: Dry-run objective.
- Out of scope: Dry-run non-goal.
- Success criteria: Dry-run success criteria.
"""
    result = run_codex_phase(
        artifact_dir=artifact_dir,
        worktree=worktree,
        args=args,
        phase_key="synthesize_interview",
        phase_num=3,
        output_name="interview-synthesis.md",
        prompt=prompt,
        placeholder=placeholder,
    )
    synthesis_path = artifact_dir / "interview-synthesis.md"
    if synthesis_path.exists():
        content = synthesis_path.read_text(encoding="utf-8", errors="replace")
        transcript = extract_section(content, "Interview Transcript") or content
        answers = extract_section(content, "Answers") or content
        intent = extract_section(content, "Intent Summary") or content
        transcript_path = write_artifact(artifact_dir, "interview-transcript.md", "# Interview Transcript\n\n" + transcript.strip())
        answers_path = write_artifact(artifact_dir, "answers.md", "# Answers\n\n" + answers.strip())
        intent_path = write_artifact(artifact_dir, "intent-summary.md", "# Intent Summary\n\n" + intent.strip())
        summary = ensure_summary(artifact_dir)
        summary.setdefault("files", {})["interviewTranscript"] = str(transcript_path)
        summary.setdefault("files", {})["answers"] = str(answers_path)
        summary.setdefault("files", {})["intentSummary"] = str(intent_path)
        write_json(artifact_dir / "summary.json", summary)
    return result


def phase_design_plan(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    logger = PhaseLogger(artifact_dir, 4, "design-plan")
    logger.start(cmd=f"claude -p --model {args.claude_model} [design-plan prompt]", cwd=str(worktree))

    intent = read_artifact(artifact_dir, "intent-summary.md", required=True)
    explore = read_artifact(artifact_dir, "explore-report.md")
    interview = read_artifact(artifact_dir, "interview-transcript.md")
    prompt = f"""You are writing architecture and implementation planning artifacts for a Codex-led orchestration harness.

Do not write code. Do not assume shared chat memory with later phases. Everything needed by review and implementation must be explicit in the artifacts.

## Task

{fence_user_input("task", args.task)}

## Codebase Context

{explore}

## Interview Transcript

{interview}

## Intent Summary

{intent}

## Output

Write Markdown with exactly these top-level headings:

# Architecture
# Plan
# Implementation Design

Under Architecture, define boundaries, components, responsibilities, data flow, file-level touch points, and failure handling.
Under Plan, define ordered phases, dependencies, validation strategy, and rollback or retry handling.
Under Implementation Design, write the exact implementation-facing spec for Pi CLI and Codex review. Include touched files or directories, interface or contract changes, testing expectations, git or deploy constraints, and explicit non-goals.
"""
    placeholder = """# Architecture

- Dry-run architecture placeholder.

# Plan

1. Dry-run planning step.
2. Dry-run verification step.

# Implementation Design

- Dry-run implementation contract.
"""

    if args.dry_run:
        output = placeholder
    else:
        try:
            result_proc = claude_exec(worktree, args.claude_model, prompt, args.agent_timeout)
        except subprocess.TimeoutExpired:
            logger.log(f"[TIMEOUT] Claude exceeded {args.agent_timeout}s")
            logger.finish(124, "failed")
            summary["phases"]["design_plan"] = phase_record("timeout", logger)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(phase="design-plan", error=f"Claude timeout ({args.agent_timeout}s)", artifact_dir=artifact_dir, exit_code=124)

        output = result_proc.stdout
        logger.log(output)
        if result_proc.returncode != 0:
            logger.finish(result_proc.returncode, "failed")
            summary["phases"]["design_plan"] = phase_record("failed", logger)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase="design-plan",
                error=(output or f"Claude exited {result_proc.returncode}")[-2000:],
                artifact_dir=artifact_dir,
                exit_code=result_proc.returncode,
            )

    design_output_path = write_artifact(artifact_dir, "design.md", output)
    raw_output_path = write_artifact(artifact_dir, "claude-design-plan.md", output)
    architecture = extract_section(output, "Architecture") or output
    plan = extract_section(output, "Plan") or output
    architecture_path = write_artifact(artifact_dir, "architecture.md", "# Architecture\n\n" + architecture.strip())
    plan_path = write_artifact(artifact_dir, "plan.md", "# Plan\n\n" + plan.strip())

    logger.finish(0, "dry_run" if args.dry_run else "success")
    summary["phases"]["design_plan"] = phase_record(
        "dry_run" if args.dry_run else "success",
        logger,
        design=str(design_output_path),
        architecture=str(architecture_path),
        plan=str(plan_path),
    )
    summary.setdefault("files", {})["design"] = str(design_output_path)
    summary.setdefault("files", {})["designPlanRaw"] = str(raw_output_path)
    summary.setdefault("files", {})["architecture"] = str(architecture_path)
    summary.setdefault("files", {})["plan"] = str(plan_path)
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "dry_run" if args.dry_run else "success", "phase": "design-plan", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def _emit_advisory(
    phase_key: str,
    phase_name: str,
    summary: dict,
    artifact_dir: Path,
    logger: "PhaseLogger",
    feedback: str,
    verdict: str,
    review: str | None = None,
    **extra: Any,
) -> int:
    """Record an advisory (non-blocking) Codex review result and return 0."""
    record = phase_record("success", logger, advisory=True, verdict=verdict, **extra)
    if review is not None:
        record["review"] = review
    summary["phases"][phase_key] = record
    write_json(artifact_dir / "summary.json", summary)
    print(
        json.dumps(
            {
                "status": "success",
                "phase": phase_name,
                "advisory": True,
                "codexFeedback": feedback,
                "artifactDir": str(artifact_dir),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def phase_verify_design(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    logger = PhaseLogger(artifact_dir, 5, "verify-design")
    design_path = artifact_dir / "design.md"
    intent_path = artifact_dir / "intent-summary.md"
    explore_path = artifact_dir / "explore-report.md"
    logger.start(cmd=f"codex exec --sandbox read-only --model {args.codex_model} [design review]", cwd=str(worktree))

    if not design_path.exists():
        err = "design.md not found; design-plan must complete first"
        logger.log(err)
        logger.finish(1, "failed")
        summary["phases"]["verify_design"] = phase_record("failed", logger, error=err)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="verify-design", error=err, artifact_dir=artifact_dir)

    if args.dry_run:
        output = "APPROVED: dry-run design review skipped."
        (artifact_dir / "codex-design-review.md").write_text(f"# Codex Design Review\n\n{output}\n", encoding="utf-8")
        logger.log("[DRY RUN] Wrote placeholder codex-design-review.md")
        logger.finish(0, "dry_run")
        summary["phases"]["verify_design"] = phase_record("dry_run", logger, verdict=output)
        summary.setdefault("files", {})["codexDesignReview"] = str(artifact_dir / "codex-design-review.md")
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "verify-design", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    design_content = design_path.read_text(encoding="utf-8", errors="replace")
    intent_content = intent_path.read_text(encoding="utf-8", errors="replace") if intent_path.exists() else ""
    explore_content = explore_path.read_text(encoding="utf-8", errors="replace")[:3000] if explore_path.exists() else ""
    review_prompt = (
        "Review this design for feasibility, contradictions, and missing edge cases.\n\n"
        f"## Design\n\n{design_content[:7000]}\n\n"
        f"## Intent\n\n{intent_content[:2500]}\n\n"
        f"## Codebase Context\n\n{explore_content}\n\n"
        "Respond on the FIRST LINE with exactly one of:\n"
        "APPROVED: <one-line summary>\n"
        "REJECTED: <one-line reason>\n\n"
        "Then provide detailed feedback below."
    )
    try:
        codex_result = codex_exec(worktree, args.codex_model, review_prompt, args.agent_timeout, logger=logger)
    except subprocess.TimeoutExpired:
        logger.log(f"[TIMEOUT] Codex exceeded {args.agent_timeout}s")
        logger.finish(124, "failed")
        if args.strict_review:
            summary["phases"]["verify_design"] = phase_record("timeout", logger)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(phase="verify-design", error=f"Codex timeout ({args.agent_timeout}s)", artifact_dir=artifact_dir, exit_code=124)
        # Advisory mode: record as success with advisory flag and continue
        return _emit_advisory(
            "verify_design", "verify-design", summary, artifact_dir, logger,
            feedback=f"Codex timeout ({args.agent_timeout}s): review unavailable",
            verdict="timeout",
        )

    codex_output = codex_result.stdout
    logger.log(sanitize_output(codex_output))
    review_path = artifact_dir / "codex-design-review.md"
    review_path.write_text(f"# Codex Design Review\n\n{strip_codex_banner(codex_output)}\n", encoding="utf-8")
    summary.setdefault("files", {})["codexDesignReview"] = str(review_path)

    if codex_result.returncode != 0 and is_codex_api_error(codex_output):
        cause = classify_codex_error(codex_output)
        logger.log(f"[DIAGNOSIS] {cause}")
        logger.finish(codex_result.returncode, "api_error")
        if args.strict_review:
            summary["phases"]["verify_design"] = phase_record("api_error", logger, review=str(review_path), cause=cause)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase="verify-design",
                error=f"Codex API error ({cause})",
                artifact_dir=artifact_dir,
                extra={"retriable": True, "cause": cause, "codexOutput": sanitize_output(codex_output[-2000:])},
            )
        # Advisory mode: record as success with advisory flag and continue
        return _emit_advisory(
            "verify_design", "verify-design", summary, artifact_dir, logger,
            feedback=sanitize_output(codex_output[-2000:]) or f"Codex API error: {cause}",
            verdict=cause,
            review=str(review_path),
        )

    verdict, details = parse_codex_verdict(codex_output)
    if codex_result.returncode != 0 and verdict not in ("approved", "api_error"):
        verdict = "rejected"
        details = codex_output[-2000:] or f"Codex exited {codex_result.returncode}"

    if verdict != "approved":
        logger.finish(1, "failed")
        if args.strict_review:
            summary["phases"]["verify_design"] = phase_record(verdict, logger, review=str(review_path))
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase="verify-design",
                error=f"Codex verdict {verdict}: {details[:500]}",
                artifact_dir=artifact_dir,
                extra={"codexFeedback": codex_output[-2000:]},
            )
        # Advisory mode: record as success with advisory flag and continue
        return _emit_advisory(
            "verify_design", "verify-design", summary, artifact_dir, logger,
            feedback=codex_output[-2000:] or f"Codex {verdict}: no output",
            verdict=verdict if verdict != "unclear" else f"unclear: {details[:200]}",
            review=str(review_path),
        )

    logger.finish(0, "success")
    summary["phases"]["verify_design"] = phase_record("success", logger, review=str(review_path), verdict=details)
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "verify-design", "verdict": details, "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_implement(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    is_retry = args.is_retry
    logger = PhaseLogger(artifact_dir, 6, "implement", is_retry=is_retry)
    design_path = artifact_dir / "design.md"
    intent_path = artifact_dir / "intent-summary.md"
    agent_config_pre = load_agent_config(SKILL_DIR)
    logger.start(cmd=f"{agent_config_pre['implement_agent']} [implement] model={args.model}", cwd=str(worktree))

    if not design_path.exists():
        err = "design.md not found in artifact directory"
        logger.log(err)
        logger.finish(1, "failed")
        summary["phases"]["implement"] = phase_record("failed", logger, error=err)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="implement", error=err, artifact_dir=artifact_dir)

    design_content = design_path.read_text(encoding="utf-8", errors="replace")
    intent_content = intent_path.read_text(encoding="utf-8", errors="replace") if intent_path.exists() else "(not provided)"
    feedback = args.feedback if is_retry else ""
    fenced_task = fence_user_input("task", args.task)
    fenced_feedback = fence_user_input("feedback", feedback) if feedback else ""
    prompt = f"""You are implementing a bounded task in this repository.

Working directory: {worktree}

## Task Description

{fenced_task}

## Design Specification

{design_content}

## Intent Summary

{intent_content}

{f"## Feedback from Previous Attempt\n\n{fenced_feedback}" if fenced_feedback else ""}

## Constraints

- Edit workspace files directly to implement the design.
- Keep changes scoped to the design specification.
- Do NOT commit, push, deploy, reset, or run destructive git operations.
- Do NOT modify files outside the designed scope.
- If the design is impossible or unsafe, stop and explain why.

## Final Response

- List all changed/created/deleted files.
- State what verification you ran or why you could not run it.
"""
    prompt_path = artifact_dir / ("implement-prompt-retry.md" if is_retry else "implement-prompt.md")
    prompt_path.write_text(prompt, encoding="utf-8")

    if args.dry_run:
        logger.log("[DRY RUN] Skipping Pi CLI implementation")
        log_path = artifact_dir / ("implement-log-retry.md" if is_retry else "implement-log.md")
        log_path.write_text("# Implementation Log\n\nDry run skipped Pi CLI execution.\n", encoding="utf-8")
        logger.finish(0, "dry_run")
        summary["phases"]["implement"] = phase_record("dry_run", logger, attempt=2 if is_retry else 1, prompt=str(prompt_path), changedFiles=[])
        summary.setdefault("files", {})["implementLog"] = str(log_path)
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "implement", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    before_files = repo_snapshot(worktree)
    agent_config = agent_config_pre
    adapters_dir = SKILL_DIR / "adapters"
    agent_name = agent_config["implement_agent"]
    try:
        cmd = build_agent_cmd(agent_name, agent_config, prompt=prompt, task=args.task,
                              model=args.model, provider=args.provider, adapters_dir=adapters_dir)
    except ValueError as exc:
        logger.log(f"[AGENT ERROR] {exc}")
        logger.finish(1, "failed")
        summary["phases"]["implement"] = phase_record("failed", logger, attempt=2 if is_retry else 1, error=str(exc))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="implement", error=str(exc), artifact_dir=artifact_dir)
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
    try:
        result_proc = run(cmd, worktree, timeout=args.implementation_timeout)
    except subprocess.TimeoutExpired:
        logger.log(f"[TIMEOUT] {agent_name} exceeded {args.implementation_timeout}s timeout")
        logger.finish(124, "failed")
        summary["phases"]["implement"] = phase_record("timeout", logger, attempt=2 if is_retry else 1)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="implement", error=f"{agent_name} timeout ({args.implementation_timeout}s)", artifact_dir=artifact_dir, exit_code=124)

    logger.log(result_proc.stdout)
    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["implement"] = phase_record("failed", logger, attempt=2 if is_retry else 1)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="implement", error=result_proc.stdout[-2000:], artifact_dir=artifact_dir, exit_code=result_proc.returncode)

    all_changed = changed_files(worktree, before_files)
    log_content = "# Implementation Log\n\n## Changed Files\n\n"
    log_content += "".join(f"- {path}\n" for path in all_changed) or "- (none)\n"
    log_content += f"\n## {agent_name} Output\n\n```\n{result_proc.stdout[-5000:]}\n```\n"
    log_path = artifact_dir / ("implement-log-retry.md" if is_retry else "implement-log.md")
    log_path.write_text(log_content, encoding="utf-8")

    if not all_changed:
        pi_output_lower = result_proc.stdout.lower()
        claimed_success = any(kw in pi_output_lower for kw in ["done", "complete", "created", "symlink", "success", "✅"])
        out_of_repo_hints = any(kw in result_proc.stdout for kw in ["~/", "/Users/", os.path.expanduser("~")])
        diagnostic = "No files changed during implementation."
        if claimed_success and out_of_repo_hints:
            diagnostic += (
                " Pi CLI reported success but changes appear to be outside the git worktree"
                f" ({worktree}). The task may involve filesystem changes (symlinks, config files)"
                " in locations not tracked by git. Consider running the task directly instead of"
                " through the orchestrate worktree pipeline."
            )
        elif claimed_success:
            diagnostic += (
                " Pi CLI reported completing the task, but no worktree files were modified."
                " Possible causes: Pi CLI ran in read-only mode, or the task only outputs text."
            )
        logger.log(f"[WARNING] {diagnostic}")
        logger.finish(3, "failed")
        summary["phases"]["implement"] = phase_record(
            "no_changes", logger, attempt=2 if is_retry else 1, changedFiles=[],
            claimedSuccess=claimed_success, outOfRepoHints=out_of_repo_hints,
        )
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="implement", error=diagnostic, artifact_dir=artifact_dir, exit_code=3)

    logger.finish(0, "success")
    summary["phases"]["implement"] = phase_record("success", logger, attempt=2 if is_retry else 1, prompt=str(prompt_path), changedFiles=all_changed)
    summary.setdefault("files", {})["implementLog"] = str(log_path)
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "implement", "changedFiles": all_changed, "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_review_test(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    is_retry = args.is_retry
    logger = PhaseLogger(artifact_dir, 7, "review-test", is_retry=is_retry)
    test_command = args.test_command or detect_test_command(worktree)
    logger.start(cmd=f"{test_command or 'no test command'} + codex review", cwd=str(worktree))

    test_exit = 0
    test_output = ""
    if args.dry_run:
        test_output = "Dry run skipped test execution."
        logger.log("[DRY RUN] Skipping tests and Codex review")
    elif test_command:
        try:
            test_proc = run_test_command(test_command, worktree, timeout=args.test_timeout)
            test_exit = test_proc.returncode
            test_output = test_proc.stdout
        except subprocess.TimeoutExpired:
            test_exit = 124
            test_output = f"Test command timed out ({args.test_timeout}s)"
        logger.log(f"Test command: {test_command}")
        logger.log(f"Test exit code: {test_exit}")
        logger.log(test_output)
    else:
        logger.log("No test command detected; relying on Codex review")

    test_results_path = artifact_dir / ("test-results-retry.md" if is_retry else "test-results.md")
    test_results_path.write_text(
        f"# Test Results\n\n**Command:** `{test_command or 'none'}`\n**Exit Code:** {test_exit}\n\n```\n{test_output[-5000:]}\n```\n",
        encoding="utf-8",
    )

    if args.dry_run:
        codex_output = "APPROVED: dry-run implementation review skipped."
    else:
        diff_result = run(["git", "diff"], worktree)
        staged_diff_result = run(["git", "diff", "--cached"], worktree)
        diff_parts = []
        if diff_result.returncode == 0 and diff_result.stdout:
            diff_parts.append(diff_result.stdout)
        if staged_diff_result.returncode == 0 and staged_diff_result.stdout:
            diff_parts.append("# Staged diff\n" + staged_diff_result.stdout)
        diff_text = "\n\n".join(diff_parts)
        untracked = run(["git", "ls-files", "--others", "--exclude-standard"], worktree)
        untracked_files = [line for line in untracked.stdout.splitlines() if line] if untracked.returncode == 0 else []
        untracked_note = "\n".join(f"- {path}" for path in untracked_files[:50])
        untracked_content = read_untracked_files(worktree, untracked_files[:10])
        design_path = artifact_dir / "design.md"
        intent_path = artifact_dir / "intent-summary.md"
        design_content = design_path.read_text(encoding="utf-8", errors="replace") if design_path.exists() else ""
        intent_content = intent_path.read_text(encoding="utf-8", errors="replace") if intent_path.exists() else ""
        review_prompt = (
            "Review this implementation against the design spec. Check correctness, edge cases, security, and design conformance.\n\n"
            f"## Design Spec\n\n{design_content[:4000]}\n\n"
            f"## Intent\n\n{intent_content[:2000]}\n\n"
            f"## Diff\n\n```diff\n{diff_text[:8000]}\n```\n\n"
            f"## Untracked Files\n\n{untracked_note or '(none)'}\n\n"
            f"## Untracked File Content\n\n{untracked_content or '(none)'}\n\n"
        )
        if test_exit != 0:
            review_prompt += f"## Test Failure\n\nTests failed with exit code {test_exit}.\n```\n{test_output[-3000:]}\n```\n\n"
        review_prompt += (
            "Respond on the FIRST LINE with exactly one of:\n"
            "APPROVED: <one-line summary>\n"
            "REJECTED: <specific issues to fix>\n\n"
            "Then provide detailed feedback below."
        )
        logger.log("--- Codex Review ---")
        logger.log(f"$ codex exec --cd <worktree> --model {args.codex_model} --sandbox read-only [review prompt]")
        codex_result = None
        try:
            codex_result = codex_exec(worktree, args.codex_model, review_prompt, args.agent_timeout, logger=logger)
            codex_output = codex_result.stdout
            if codex_result.returncode != 0:
                codex_output = codex_output or f"Codex exited {codex_result.returncode}"
        except subprocess.TimeoutExpired:
            codex_output = f"REJECTED: Codex review timed out ({args.agent_timeout}s)"
    logger.log(sanitize_output(codex_output))

    cleaned_codex_output = strip_codex_banner(codex_output) if not args.dry_run else codex_output
    review_path = artifact_dir / ("codex-review-retry.md" if is_retry else "codex-review.md")
    review_path.write_text(f"# Codex Review\n\n{cleaned_codex_output}\n", encoding="utf-8")
    summary.setdefault("files", {})["testResults"] = str(test_results_path)
    summary.setdefault("files", {})["codexReview"] = str(review_path)

    if not args.dry_run and codex_result is not None and codex_result.returncode != 0 and is_codex_api_error(codex_output):
        cause = classify_codex_error(codex_output)
        logger.log(f"[DIAGNOSIS] {cause}")
        logger.finish(1, "api_error")
        if args.strict_review:
            summary["phases"]["review_test"] = phase_record(
                "api_error",
                logger,
                attempt=2 if is_retry else 1,
                testCommand=test_command,
                testExitCode=test_exit,
                testResults=str(test_results_path),
                review=str(review_path),
                cause=cause,
            )
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase="review-test",
                error=f"Codex API error ({cause})",
                artifact_dir=artifact_dir,
                extra={"retriable": True, "cause": cause, "codexOutput": sanitize_output(codex_output[-2000:])},
            )
        # Advisory mode: record as success with advisory flag and continue
        return _emit_advisory(
            "review_test", "review-test", summary, artifact_dir, logger,
            feedback=cause,
            verdict=cause,
            review=str(review_path),
            attempt=2 if is_retry else 1,
            testCommand=test_command,
            testExitCode=test_exit,
            testResults=str(test_results_path),
        )

    if test_exit != 0:
        feedback = f"Test failure (exit {test_exit}):\n{test_output[-1000:]}\n\nCodex feedback:\n{cleaned_codex_output[-1500:]}"
        logger.finish(test_exit, "failed")
        summary["phases"]["review_test"] = phase_record(
            "test_failed",
            logger,
            attempt=2 if is_retry else 1,
            testCommand=test_command,
            testExitCode=test_exit,
            testResults=str(test_results_path),
            review=str(review_path),
        )
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="review-test",
            error=f"Tests failed (exit {test_exit})",
            artifact_dir=artifact_dir,
            exit_code=test_exit,
            extra={"testOutput": test_output[-1500:], "codexFeedback": feedback},
        )

    verdict, details = parse_codex_verdict(codex_output)
    if verdict != "approved":
        logger.finish(1, "failed")
        if args.strict_review:
            summary["phases"]["review_test"] = phase_record(
                "review_rejected" if verdict == "rejected" else "unclear",
                logger,
                attempt=2 if is_retry else 1,
                testCommand=test_command,
                testExitCode=test_exit,
                testResults=str(test_results_path),
                review=str(review_path),
            )
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(
                phase="review-test",
                error=f"Codex review {verdict}: {details[:500]}",
                artifact_dir=artifact_dir,
                extra={"codexFeedback": codex_output[-2000:]},
            )
        # Advisory mode: record as success with advisory flag and continue
        return _emit_advisory(
            "review_test", "review-test", summary, artifact_dir, logger,
            feedback=codex_output[-2000:] or f"Codex {verdict}: no output",
            verdict=verdict if verdict != "unclear" else f"unclear: {details[:200]}",
            review=str(review_path),
            attempt=2 if is_retry else 1,
            testCommand=test_command,
            testExitCode=test_exit,
            testResults=str(test_results_path),
        )

    logger.finish(0, "success" if not args.dry_run else "dry_run")
    summary["phases"]["review_test"] = phase_record(
        "dry_run" if args.dry_run else "success",
        logger,
        attempt=2 if is_retry else 1,
        testCommand=test_command,
        testExitCode=test_exit,
        testResults=str(test_results_path),
        review=str(review_path),
        verdict=details,
    )
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "dry_run" if args.dry_run else "success", "phase": "review-test", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_complete(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    branch = summary["branch"]
    logger = PhaseLogger(artifact_dir, 8, "complete")
    logger.start(cmd="git add + commit + merge + push", cwd=str(worktree))

    review_status = summary.get("phases", {}).get("review_test", {}).get("status")
    if review_status != "success" and not args.dry_run:
        err = f"Phase 8 blocked: Phase 7 review_test status is {review_status!r}, expected 'success'"
        logger.log(err)
        logger.finish(1, "failed")
        summary["phases"]["complete"] = phase_record("blocked", logger, error=err)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=err, artifact_dir=artifact_dir)

    if args.dry_run:
        logger.log("[DRY RUN] Would add, commit, merge in a detached merge worktree, and push HEAD:main")
        logger.finish(0, "dry_run")
        summary["phases"]["complete"] = phase_record("dry_run", logger)
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "complete", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    impl_phase = summary.get("phases", {}).get("implement", {})
    staging_files = impl_phase.get("changedFiles", [])
    if not staging_files:
        staging_files = changed_files(worktree)
    staging_files = filter_sensitive_files(staging_files)
    if not staging_files:
        err = "No files to stage after filtering sensitive files"
        logger.log(err)
        logger.finish(1, "failed")
        summary["phases"]["complete"] = phase_record("failed", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=err, artifact_dir=artifact_dir)
    add_result = run(["git", "add", "--"] + staging_files, worktree)
    logger.log(f"$ git add -- {' '.join(staging_files[:10])}{'...' if len(staging_files) > 10 else ''}")
    logger.log(add_result.stdout)
    if add_result.returncode != 0:
        logger.finish(add_result.returncode, "failed")
        summary["phases"]["complete"] = phase_record("failed", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=f"git add failed: {add_result.stdout}", artifact_dir=artifact_dir, exit_code=add_result.returncode)

    commit_msg = (
        f"Enable orchestrated agent handoff for {slugify(args.task)}\n\n"
        "The harness records each agent phase as artifacts so Claude, Pi, and Codex can coordinate without shared session memory.\n\n"
        "Constraint: Pipeline work must stay isolated in a git worktree until completion\n"
        "Confidence: medium\n"
        "Scope-risk: moderate\n"
        f"Tested: Phase 7 review-test passed via {summary.get('phases', {}).get('review_test', {}).get('testCommand') or 'review gate'}\n"
        "Not-tested: Live remote push behavior beyond git push exit status\n"
    )
    commit_result = run(["git", "commit", "-m", commit_msg], worktree)
    logger.log("$ git commit [Lore message]")
    logger.log(commit_result.stdout)
    if commit_result.returncode != 0:
        logger.finish(commit_result.returncode, "failed")
        summary["phases"]["complete"] = phase_record("failed", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=f"git commit failed: {commit_result.stdout}", artifact_dir=artifact_dir, exit_code=commit_result.returncode)

    hash_result = run(["git", "rev-parse", "HEAD"], worktree)
    commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else "unknown"
    merge_worktree = root / ".worktrees" / f"orchestrate-merge-{artifact_dir.name}"
    summary["mergeWorktree"] = str(merge_worktree)
    if not merge_worktree.exists():
        add_merge_tree = run(["git", "worktree", "add", "--detach", str(merge_worktree), "main"], root)
        logger.log(f"$ git worktree add --detach {merge_worktree} main")
        logger.log(add_merge_tree.stdout)
        if add_merge_tree.returncode != 0:
            error = f"merge worktree creation failed: {add_merge_tree.stdout}"
            logger.finish(add_merge_tree.returncode, "failed")
            summary["phases"]["complete"] = phase_record("failed", logger)
            mark_summary_failed(summary, error)
            write_json(artifact_dir / "summary.json", summary)
            return fail_json(phase="complete", error=error, artifact_dir=artifact_dir, exit_code=add_merge_tree.returncode)

    merge_result = run(["git", "merge", branch], merge_worktree)
    logger.log(f"$ git merge {branch}")
    logger.log(merge_result.stdout)
    if merge_result.returncode != 0:
        error = f"Merge conflict:\n{merge_result.stdout}"
        logger.finish(merge_result.returncode, "failed")
        summary["phases"]["complete"] = phase_record("merge_conflict", logger)
        mark_summary_failed(summary, error)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="complete", error=error, artifact_dir=artifact_dir, exit_code=merge_result.returncode)

    merged_hash_result = run(["git", "rev-parse", "HEAD"], merge_worktree)
    merged_hash = merged_hash_result.stdout.strip() if merged_hash_result.returncode == 0 else commit_hash
    push_result = run(["git", "push", "origin", "HEAD:main"], merge_worktree)
    logger.log("$ git push origin HEAD:main")
    logger.log(push_result.stdout)
    if push_result.returncode != 0:
        error = f"Push failed after detached merge:\n{push_result.stdout}"
        logger.finish(push_result.returncode, "failed")
        summary["phases"]["complete"] = phase_record("push_failed", logger)
        summary["mergedCommit"] = merged_hash
        mark_summary_failed(summary, error)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="complete",
            error=error,
            artifact_dir=artifact_dir,
            exit_code=push_result.returncode,
            extra={"mergedCommit": merged_hash, "mergeWorktree": str(merge_worktree)},
        )

    logger.finish(0, "success")
    summary["phases"]["complete"] = phase_record("success", logger)
    summary["mergedCommit"] = merged_hash
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "complete", "mergedCommit": merged_hash, "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_pi_complete(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    _pic_agent = load_agent_config(SKILL_DIR)["implement_agent"]
    logger = PhaseLogger(artifact_dir, 8, "pi-complete")
    logger.start(cmd=f"{_pic_agent} [pi-complete] model={args.model}", cwd=str(worktree))

    review_status = summary.get("phases", {}).get("review_test", {}).get("status")
    if review_status != "success" and not args.dry_run:
        err = f"Phase 8 blocked: Phase 7 review_test status is {review_status!r}, expected 'success'"
        logger.log(err)
        logger.finish(1, "failed")
        summary["phases"]["pi_complete"] = phase_record("blocked", logger, error=err)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-complete", error=err, artifact_dir=artifact_dir)

    if args.dry_run:
        pushed_output = "PUSHED: dry-run commit/push skipped."
        log_path = write_artifact(artifact_dir, "pi-complete-log.md", f"# Pi Complete Log\n\n{pushed_output}\n")
        logger.log("[DRY RUN] Wrote placeholder pi-complete-log.md")
        logger.finish(0, "dry_run")
        summary["phases"]["pi_complete"] = phase_record("dry_run", logger, logPath=str(log_path))
        summary.setdefault("files", {})["piCompleteLog"] = str(log_path)
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "pi-complete", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    before_head = current_head(worktree)
    branch = current_branch(worktree) or summary.get("branch", "")
    prompt = f"""You are closing out a completed implementation in this git worktree.

## Task

{fence_user_input("task", args.task)}

## Constraints

- Work only in the current worktree on the current branch: {branch}.
- Inspect git status before acting.
- Stage only the intended task changes.
- Create one commit using the repository's Lore commit protocol:
  - intent line first
  - optional narrative body if useful
  - trailers as plain git trailer lines such as Constraint:, Rejected:, Confidence:, Scope-risk:, Directive:, Tested:, Not-tested:
- Push the current branch with upstream using: git push -u origin HEAD
- Do NOT deploy.
- Do NOT force push, merge to another branch, rebase, reset, checkout a different branch, or delete branches.
- If commit or push is unsafe or impossible, stop and explain.

## Final Response

Respond on the FIRST LINE with exactly one of:
PUSHED: <branch and commit summary>
FAILED: <one-line reason>

Then provide:
- commands run
- commit subject
- branch pushed
- any remaining warnings
"""
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    agent_name = agent_config["implement_agent"]
    try:
        cmd = build_agent_cmd(agent_name, agent_config, prompt=prompt, task=args.task,
                              model=args.model, provider=args.provider, adapters_dir=adapters_dir)
    except ValueError as exc:
        logger.log(f"[AGENT ERROR] {exc}")
        logger.finish(1, "failed")
        summary["phases"]["pi_complete"] = phase_record("failed", logger, error=str(exc))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-complete", error=str(exc), artifact_dir=artifact_dir)
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
    try:
        result_proc = run(cmd, worktree, timeout=args.implementation_timeout)
    except subprocess.TimeoutExpired:
        logger.log(f"[TIMEOUT] {agent_name} exceeded {args.implementation_timeout}s timeout")
        logger.finish(124, "failed")
        summary["phases"]["pi_complete"] = phase_record("timeout", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-complete", error=f"{agent_name} timeout ({args.implementation_timeout}s)", artifact_dir=artifact_dir, exit_code=124)

    logger.log(result_proc.stdout)
    log_path = write_artifact(artifact_dir, "pi-complete-log.md", f"# {agent_name} Complete Log\n\n```\n{result_proc.stdout}\n```\n")
    summary.setdefault("files", {})["piCompleteLog"] = str(log_path)

    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["pi_complete"] = phase_record("failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-complete", error=result_proc.stdout[-2000:], artifact_dir=artifact_dir, exit_code=result_proc.returncode)

    verdict, details = parse_prefixed_verdict(result_proc.stdout, "PUSHED")
    after_head = current_head(worktree)
    tracked_dirty = tracked_status(worktree)
    remote_head = remote_branch_head(worktree, branch)
    untracked = untracked_status(worktree)

    if verdict != "success":
        logger.finish(1, "failed")
        summary["phases"]["pi_complete"] = phase_record("failed" if verdict == "failed" else "unclear", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="pi-complete",
            error=f"Pi commit/push {verdict}: {details[:500]}",
            artifact_dir=artifact_dir,
            extra={"piFeedback": result_proc.stdout[-2000:]},
        )

    if not after_head or after_head == before_head:
        logger.finish(1, "failed")
        summary["phases"]["pi_complete"] = phase_record("failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-complete", error="Pi did not create a new commit", artifact_dir=artifact_dir)

    if tracked_dirty:
        logger.finish(1, "failed")
        summary["phases"]["pi_complete"] = phase_record("failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-complete", error=f"Tracked changes remain after push:\n{tracked_dirty}", artifact_dir=artifact_dir)

    if not remote_head or remote_head != after_head:
        logger.finish(1, "failed")
        summary["phases"]["pi_complete"] = phase_record("push_failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="pi-complete",
            error=f"Remote branch verification failed for {branch}",
            artifact_dir=artifact_dir,
            extra={"localHead": after_head, "remoteHead": remote_head or None},
        )

    logger.finish(0, "success")
    summary["phases"]["pi_complete"] = phase_record(
        "success",
        logger,
        logPath=str(log_path),
        branch=branch,
        commit=after_head,
        remoteHead=remote_head,
        warnings=untracked or None,
    )
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "pi-complete", "branch": branch, "commit": after_head, "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_pi_deploy(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    worktree = Path(summary["worktree"])
    _pid_agent = load_agent_config(SKILL_DIR)["implement_agent"]
    logger = PhaseLogger(artifact_dir, 9, "pi-deploy")
    logger.start(cmd=f"{_pid_agent} [pi-deploy] model={args.model}", cwd=str(worktree))

    complete_status = summary.get("phases", {}).get("pi_complete", {}).get("status")
    if complete_status != "success" and not args.dry_run:
        err = f"Phase 9 blocked: Phase 8 pi_complete status is {complete_status!r}, expected 'success'"
        logger.log(err)
        logger.finish(1, "failed")
        summary["phases"]["pi_deploy"] = phase_record("blocked", logger, error=err)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-deploy", error=err, artifact_dir=artifact_dir)

    if args.dry_run:
        deployed_output = "DEPLOYED: dry-run deploy skipped."
        log_path = write_artifact(artifact_dir, "deploy-log.md", f"# Deploy Log\n\n{deployed_output}\n")
        logger.log("[DRY RUN] Wrote placeholder deploy-log.md")
        logger.finish(0, "dry_run")
        summary["phases"]["pi_deploy"] = phase_record("dry_run", logger, logPath=str(log_path))
        summary.setdefault("files", {})["deployLog"] = str(log_path)
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "pi-deploy", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    deploy_instruction = args.deploy_command.strip() if args.deploy_command else ""
    prompt = f"""You are running the deploy phase for a finished implementation in this repository.

## Task

{fence_user_input("task", args.task)}

## Constraints

- Inspect the repository and detect the most trustworthy deploy command for this project.
- If an explicit deploy command is provided below, run exactly that command and do not infer another one.
- If no trustworthy deploy command exists, stop instead of guessing.
- Run exactly one deploy path.
- Do NOT commit, push, force push, merge, rebase, reset, or modify unrelated files.

{f"## Explicit Deploy Command\n\n{deploy_instruction}" if deploy_instruction else ""}

## Final Response

Respond on the FIRST LINE with exactly one of:
DEPLOYED: <command and target summary>
FAILED: <one-line reason>

Then provide:
- deploy command used
- evidence of success or failure
- any follow-up checks the operator should run
"""
    agent_config = load_agent_config(SKILL_DIR)
    adapters_dir = SKILL_DIR / "adapters"
    agent_name = agent_config["implement_agent"]
    try:
        cmd = build_agent_cmd(agent_name, agent_config, prompt=prompt, task=args.task,
                              model=args.model, provider=args.provider, adapters_dir=adapters_dir)
    except ValueError as exc:
        logger.log(f"[AGENT ERROR] {exc}")
        logger.finish(1, "failed")
        summary["phases"]["pi_deploy"] = phase_record("deploy_failed", logger, error=str(exc))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-deploy", error=str(exc), artifact_dir=artifact_dir)
    if cmd[0].endswith(".sh"):
        cmd = ["bash"] + cmd
    try:
        result_proc = run(cmd, worktree, timeout=args.implementation_timeout)
    except subprocess.TimeoutExpired:
        logger.log(f"[TIMEOUT] {agent_name} exceeded {args.implementation_timeout}s timeout")
        logger.finish(124, "failed")
        summary["phases"]["pi_deploy"] = phase_record("timeout", logger)
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-deploy", error=f"{agent_name} timeout ({args.implementation_timeout}s)", artifact_dir=artifact_dir, exit_code=124)

    logger.log(result_proc.stdout)
    log_path = write_artifact(artifact_dir, "deploy-log.md", f"# Deploy Log\n\n```\n{result_proc.stdout}\n```\n")
    summary.setdefault("files", {})["deployLog"] = str(log_path)

    if result_proc.returncode != 0:
        logger.finish(result_proc.returncode, "failed")
        summary["phases"]["pi_deploy"] = phase_record("failed", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="pi-deploy", error=result_proc.stdout[-2000:], artifact_dir=artifact_dir, exit_code=result_proc.returncode)

    verdict, details = parse_prefixed_verdict(result_proc.stdout, "DEPLOYED")
    if verdict != "success":
        logger.finish(1, "failed")
        summary["phases"]["pi_deploy"] = phase_record("deploy_failed" if verdict == "failed" else "unclear", logger, logPath=str(log_path))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(
            phase="pi-deploy",
            error=f"Pi deploy {verdict}: {details[:500]}",
            artifact_dir=artifact_dir,
            extra={"piFeedback": result_proc.stdout[-2000:]},
        )

    logger.finish(0, "success")
    summary["phases"]["pi_deploy"] = phase_record("success", logger, logPath=str(log_path), verdict=details)
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "pi-deploy", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def phase_resume(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    out = {
        "status": "success",
        "phase": "resume",
        "nextPhase": compute_next_phase(summary),
        "finalStatus": summary.get("finalStatus"),
        "task": summary.get("taskDescription", ""),
        "resumeState": read_resume_state(artifact_dir),
        "artifactDir": str(artifact_dir),
    }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0


def phase_cleanup(root: Path, artifact_dir: Path, args: argparse.Namespace) -> int:
    summary = ensure_summary(artifact_dir)
    kill_watcher(artifact_dir)
    worktree = Path(summary["worktree"])
    branch = summary["branch"]
    merge_worktree = Path(summary["mergeWorktree"]) if summary.get("mergeWorktree") else None
    logger = PhaseLogger(artifact_dir, 10, "cleanup")
    logger.start(cmd="git worktree remove + branch delete", cwd=str(root))
    errors: list[str] = []

    if args.dry_run:
        logger.log(f"[DRY RUN] Would remove worktree {worktree} and delete branch {branch}")
        logger.finish(0, "dry_run")
        summary["phases"]["cleanup"] = phase_record("dry_run", logger)
        summary["finalStatus"] = "dry_run"
        write_json(artifact_dir / "summary.json", summary)
        print(json.dumps({"status": "dry_run", "phase": "cleanup", "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
        return 0

    remove_orchestrate_lock(root)

    if worktree.exists():
        rm_result = run(["git", "worktree", "remove", str(worktree)], root)
        logger.log(f"$ git worktree remove {worktree}")
        logger.log(rm_result.stdout)
        if rm_result.returncode != 0:
            errors.append(f"worktree remove failed: {rm_result.stdout.strip()}")
    else:
        logger.log(f"Worktree already removed: {worktree}")

    branch_check = run(["git", "branch", "--list", branch], root)
    if branch_check.stdout.strip():
        branch_delete_cwd = merge_worktree if merge_worktree and merge_worktree.exists() else root
        br_result = run(["git", "branch", "-d", branch], branch_delete_cwd)
        logger.log(f"$ git branch -d {branch}")
        logger.log(br_result.stdout)
        if br_result.returncode != 0:
            errors.append(f"branch delete failed: {br_result.stdout.strip()}")
    else:
        logger.log(f"Branch already absent: {branch}")

    if merge_worktree and merge_worktree.exists():
        rm_merge_result = run(["git", "worktree", "remove", str(merge_worktree)], root)
        logger.log(f"$ git worktree remove {merge_worktree}")
        logger.log(rm_merge_result.stdout)
        if rm_merge_result.returncode != 0:
            errors.append(f"merge worktree remove failed: {rm_merge_result.stdout.strip()}")

    if errors:
        logger.finish(1, "partial_failure")
        summary["phases"]["cleanup"] = phase_record("partial_failure", logger, errors=errors)
        mark_summary_failed(summary, "; ".join(errors))
        write_json(artifact_dir / "summary.json", summary)
        return fail_json(phase="cleanup", error="; ".join(errors), artifact_dir=artifact_dir, extra={"errors": errors})

    logger.finish(0, "success")
    summary["phases"]["cleanup"] = phase_record("success", logger)
    summary["finalStatus"] = "failed" if has_failed_phase(summary) else "success"
    write_json(artifact_dir / "summary.json", summary)
    print(json.dumps({"status": "success", "phase": "cleanup", "finalStatus": summary["finalStatus"], "artifactDir": str(artifact_dir)}, ensure_ascii=False, separators=(",", ":"))
)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--phase", required=True, choices=PHASE_CHOICES)
    parser.add_argument("--task", required=True)
    parser.add_argument("--artifact-dir", help="Existing artifact dir for phases after setup")
    parser.add_argument("--provider", default="opencode-go")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument(
        "--explore-model",
        default="deepseek-v4-flash",
        help="Lightweight model for read-only exploration (default: deepseek-v4-flash). "
        "The heavy --model is reserved for implementation.",
    )
    parser.add_argument("--codex-model", default="gpt-5.4")
    parser.add_argument("--claude-model", default="claude-opus-4-6")
    parser.add_argument("--test-command", default="")
    parser.add_argument("--deploy-command", default="")
    parser.add_argument("--is-retry", action="store_true")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Drop the verify_design dependency for implement. Used by the pi-execute "
        "entrypoint, which does design/verification externally and skips those phases.",
    )
    parser.add_argument(
        "--strict-review",
        action="store_true",
        help=(
            "Restore hard-gating on Codex verdicts for Phase 4 (verify-design) and "
            "Phase 6 (review-test). By default both phases are advisory: a "
            "REJECTED, UNCLEAR, API-error, or timeout verdict is recorded and "
            "surfaced but does not stop the pipeline. Objective test failures always "
            "block regardless of this flag."
        ),
    )
    parser.add_argument("--feedback", default="", help="Codex feedback for retry")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agent-timeout", type=int, default=300)
    parser.add_argument(
        "--explore-timeout",
        type=int,
        default=900,
        help="Timeout for the explore phase. Exploration is agentic (many tool-call "
        "rounds) and can outlast the generic --agent-timeout on large repos.",
    )
    parser.add_argument("--implementation-timeout", type=int, default=600)
    parser.add_argument("--test-timeout", type=int, default=300)
    parser.add_argument(
        "--auto-resume",
        action="store_true",
        help="Arm the detached watcher daemon that resumes this run after a "
        "Claude Code 5h usage-limit stall.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cwd = Path(args.cwd).expanduser().resolve()
    root = git_root(cwd)

    if args.phase == "setup":
        return phase_setup(root, args)

    if not args.artifact_dir:
        return fail_json(phase=args.phase, error="--artifact-dir required for non-setup phases")
    artifact_dir = Path(args.artifact_dir).expanduser().resolve()

    if args.phase not in ("cleanup", "resume"):
        summary = ensure_summary(artifact_dir)
        skip = {"verify_design"} if args.skip_verify else None
        dep_error = validate_phase_dependencies(args.phase, summary, skip=skip)
        if dep_error:
            return fail_json(phase=args.phase, error=dep_error, artifact_dir=artifact_dir)

    phases = {
        "explore": phase_explore,
        "interview": phase_interview,
        "synthesize-interview": phase_synthesize_interview,
        "design-plan": phase_design_plan,
        "verify-design": phase_verify_design,
        "implement": phase_implement,
        "review-test": phase_review_test,
        "complete": phase_complete,
        "pi-complete": phase_pi_complete,
        "pi-deploy": phase_pi_deploy,
        "cleanup": phase_cleanup,
        "resume": phase_resume,
    }
    result_code = phases[args.phase](root, artifact_dir, args)
    update_resume_state_if_present(artifact_dir)
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
