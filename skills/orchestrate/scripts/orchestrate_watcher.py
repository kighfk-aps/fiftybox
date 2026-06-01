#!/usr/bin/env python3
"""Detached watcher that resumes an /orchestrate run after a Claude Code 5h
usage-limit stall.

Spec: docs/superpowers/specs/2026-05-31-orchestrate-auto-resume-on-session-limit-design.md

The watcher latches when a cheap probe shows the account is usage-limited, then
relaunches `/orchestrate --resume <dir>` once the probe shows the window
reopened. A run that was never limited (e.g. user quit) never latches, so the
watcher never relaunches — it exits via TTL.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

CLAUDE_LIMIT_PATTERNS = (
    "usage limit",
    "5-hour limit",
    "5 hour limit",
    "limit reached",
    "resets at",
    "upgrade to",
    "you've reached your",
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_state_files(artifact_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    summary: dict[str, Any] = {}
    state: dict[str, Any] = {}
    sp = artifact_dir / "summary.json"
    stp = artifact_dir / "resume-state.json"
    if sp.exists():
        try:
            summary = _read_json(sp)
        except (json.JSONDecodeError, OSError):
            pass
    if stp.exists():
        try:
            state = _read_json(stp)
        except (json.JSONDecodeError, OSError):
            pass
    return summary, state


def is_run_finished(summary: dict[str, Any]) -> bool:
    return summary.get("finalStatus") in ("success", "aborted")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_heartbeat_stale(state: dict[str, Any], current: datetime, threshold_s: int) -> bool:
    hb = _parse_iso(state.get("heartbeat"))
    if hb is None:
        return True
    return (current - hb).total_seconds() > threshold_s


def output_indicates_limit(output: str) -> bool:
    low = output.lower()
    return any(pattern in low for pattern in CLAUDE_LIMIT_PATTERNS)


def probe_account_limited(probe_cmd: list[str], timeout_s: int = 60) -> bool | None:
    """Tri-state probe of the account's usage-limit status.

    - True  → the probe output shows the account is usage-limited.
    - False → the probe succeeded (exit 0) with no limit marker: window is open.
    - None  → indeterminate (non-zero exit with no limit marker, timeout, or
              spawn error). The caller must NOT treat None as "reopened"; an
              unrelated probe failure must never be mistaken for a fresh window.
    """
    try:
        result = subprocess.run(
            probe_cmd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if output_indicates_limit(result.stdout):
        return True
    if result.returncode == 0:
        return False
    return None


def should_relaunch(
    summary: dict[str, Any],
    state: dict[str, Any],
    current: datetime,
    *,
    limit_latched: bool,
    heartbeat_stale_s: int,
    max_relaunch: int,
) -> bool:
    if is_run_finished(summary):
        return False
    if state.get("relaunchCount", 0) >= max_relaunch:
        return False
    if not is_heartbeat_stale(state, current, heartbeat_stale_s):
        return False
    return bool(limit_latched)


def build_resume_command(state: dict[str, Any]) -> str:
    return f"/orchestrate --resume {state.get('artifactDir', '')}"


def relaunch(state: dict[str, Any], root: Path) -> bool:
    resume_cmd = build_resume_command(state)
    tmux_session = state.get("tmuxSession") or ""
    if tmux_session:
        result = subprocess.run(
            ["tmux", "new-window", "-t", tmux_session, "-n", "orchestrate-resume",
             f'claude "{resume_cmd}"'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if result.returncode == 0:
            return True
    logs = Path(state.get("artifactDir", ".")) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    log_path = logs / f"resume-{stamp}.log"
    with open(log_path, "w", encoding="utf-8") as fh:
        subprocess.Popen(
            ["claude", "-p", resume_cmd],
            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True, cwd=str(root),
        )
    return True


def bump_relaunch_count(artifact_dir: Path) -> None:
    path = artifact_dir / "resume-state.json"
    try:
        state = _read_json(path)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return
    state["relaunchCount"] = state.get("relaunchCount", 0) + 1
    state["lastRelaunch"] = now().isoformat()
    path.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def write_give_up(artifact_dir: Path) -> None:
    (artifact_dir / "resume-give-up.md").write_text(
        f"# Auto-resume gave up\n\nReached the max relaunch attempts at "
        f"{now().isoformat()}.\n",
        encoding="utf-8",
    )


def watch_loop(
    artifact_dir: Path,
    root: Path,
    *,
    poll_interval: int,
    heartbeat_stale_s: int,
    ttl_s: int,
    max_relaunch: int,
    probe_cmd: list[str],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = now,
    probe: Callable[[list[str]], bool] = probe_account_limited,
) -> str:
    # The watcher is a single long-lived daemon: it survives across multiple
    # relaunches (a resumed run can itself hit a fresh 5h limit) until the run
    # finishes, the relaunch cap is reached, or it idles past the TTL. The TTL
    # is measured from the last sign of progress (a fresh heartbeat or a
    # relaunch), not from process start, so a legitimate multi-limit saga does
    # not trip it. Because the watcher persists, the resumed run does not need
    # to re-arm a fresh watcher, which also avoids duplicate-spawn races.
    last_progress = clock()
    limit_latched = False
    while True:
        summary, state = read_state_files(artifact_dir)
        if is_run_finished(summary):
            return "finished"
        if state.get("relaunchCount", 0) >= max_relaunch:
            write_give_up(artifact_dir)
            return "max_relaunch"
        current = clock()
        if not is_heartbeat_stale(state, current, heartbeat_stale_s):
            # The session is alive and making progress; clear the latch so a
            # later limit must be observed afresh before any relaunch.
            last_progress = current
            limit_latched = False
        else:
            probe_result = probe(probe_cmd)  # True=limited, False=open, None=unknown
            if probe_result is True:
                limit_latched = True
            elif (
                probe_result is False
                and limit_latched
                and should_relaunch(
                    summary, state, current, limit_latched=True,
                    heartbeat_stale_s=heartbeat_stale_s, max_relaunch=max_relaunch,
                )
            ):
                # Only relaunch on a confirmed open window after a latched limit.
                # An indeterminate probe (None) is ignored: an unrelated failure
                # must never be mistaken for a reopened window.
                relaunch(state, root)
                bump_relaunch_count(artifact_dir)
                limit_latched = False
                last_progress = clock()
        if (clock() - last_progress).total_seconds() > ttl_s:
            return "ttl_expired"
        sleep(poll_interval)


def daemonize(artifact_dir: Path) -> None:
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    (artifact_dir / "watcher.pid").write_text(str(os.getpid()), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--poll-interval", type=int, default=600)
    parser.add_argument("--heartbeat-stale", type=int, default=900)
    parser.add_argument("--ttl", type=int, default=6 * 3600)
    parser.add_argument("--max-relaunch", type=int, default=3)
    parser.add_argument("--no-daemon", action="store_true",
                        help="Run in the foreground (testing/debugging).")
    args = parser.parse_args(argv)
    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    root = Path(args.root).expanduser().resolve()
    if not args.no_daemon:
        daemonize(artifact_dir)
    try:
        watch_loop(
            artifact_dir, root,
            poll_interval=args.poll_interval,
            heartbeat_stale_s=args.heartbeat_stale,
            ttl_s=args.ttl, max_relaunch=args.max_relaunch,
            probe_cmd=["claude", "-p", "ok"],
        )
    finally:
        try:
            (artifact_dir / "watcher.pid").unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
