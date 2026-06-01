import subprocess
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import orchestrate_watcher as w


def _iso(dt):
    return dt.isoformat()


# --- Task 6: Watcher pure functions ---

def test_is_run_finished():
    assert w.is_run_finished({"finalStatus": "success"}) is True
    assert w.is_run_finished({"finalStatus": "aborted"}) is True
    assert w.is_run_finished({"finalStatus": "in_progress"}) is False
    assert w.is_run_finished({}) is False


def test_is_heartbeat_stale_missing_is_stale():
    assert w.is_heartbeat_stale({}, datetime.now(timezone.utc), 900) is True


def test_is_heartbeat_fresh():
    n = datetime.now(timezone.utc)
    state = {"heartbeat": _iso(n - timedelta(seconds=10))}
    assert w.is_heartbeat_stale(state, n, 900) is False


def test_is_heartbeat_stale_old():
    n = datetime.now(timezone.utc)
    state = {"heartbeat": _iso(n - timedelta(seconds=1200))}
    assert w.is_heartbeat_stale(state, n, 900) is True


def test_output_indicates_limit():
    assert w.output_indicates_limit("You've hit your usage limit") is True
    assert w.output_indicates_limit("5-hour limit reached, resets at 3pm") is True
    assert w.output_indicates_limit("hello world ok") is False


def test_probe_limited_true_when_output_matches():
    res = subprocess.CompletedProcess(args=[], returncode=1,
                                      stdout="usage limit reached")
    with patch("orchestrate_watcher.subprocess.run", return_value=res):
        assert w.probe_account_limited(["claude", "-p", "ok"]) is True


def test_probe_limited_false_when_success():
    res = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok")
    with patch("orchestrate_watcher.subprocess.run", return_value=res):
        assert w.probe_account_limited(["claude", "-p", "ok"]) is False


def test_probe_limited_none_on_unrelated_error():
    """A non-zero exit with no limit marker is indeterminate, not 'open'."""
    res = subprocess.CompletedProcess(args=[], returncode=1,
                                      stdout="some unrelated crash")
    with patch("orchestrate_watcher.subprocess.run", return_value=res):
        assert w.probe_account_limited(["claude", "-p", "ok"]) is None


def test_probe_limited_none_on_timeout():
    with patch("orchestrate_watcher.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=60)):
        assert w.probe_account_limited(["claude", "-p", "ok"]) is None


# --- Task 7: Watcher decision + relaunch + give-up ---

def _state(**kw):
    base = {"artifactDir": "/tmp/x", "tmuxSession": "", "relaunchCount": 0,
            "heartbeat": w.now().isoformat()}
    base.update(kw)
    return base


def test_should_relaunch_requires_limit_latched():
    n = w.now()
    summary = {"finalStatus": "in_progress"}
    state = _state(heartbeat=(n - timedelta(seconds=1200)).isoformat())
    assert w.should_relaunch(summary, state, n, limit_latched=False,
                             heartbeat_stale_s=900, max_relaunch=3) is False
    assert w.should_relaunch(summary, state, n, limit_latched=True,
                             heartbeat_stale_s=900, max_relaunch=3) is True


def test_should_relaunch_false_when_finished():
    n = w.now()
    summary = {"finalStatus": "success"}
    state = _state(heartbeat=(n - timedelta(seconds=1200)).isoformat())
    assert w.should_relaunch(summary, state, n, limit_latched=True,
                             heartbeat_stale_s=900, max_relaunch=3) is False


def test_should_relaunch_false_when_heartbeat_fresh():
    n = w.now()
    summary = {"finalStatus": "in_progress"}
    assert w.should_relaunch(summary, _state(), n, limit_latched=True,
                             heartbeat_stale_s=900, max_relaunch=3) is False


def test_should_relaunch_false_at_max_relaunch():
    n = w.now()
    summary = {"finalStatus": "in_progress"}
    state = _state(relaunchCount=3,
                   heartbeat=(n - timedelta(seconds=1200)).isoformat())
    assert w.should_relaunch(summary, state, n, limit_latched=True,
                             heartbeat_stale_s=900, max_relaunch=3) is False


def test_relaunch_uses_tmux_when_session_present(tmp_path):
    state = {"artifactDir": str(tmp_path), "tmuxSession": "main"}
    res = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
    with patch("orchestrate_watcher.subprocess.run", return_value=res) as m:
        assert w.relaunch(state, tmp_path) is True
        cmd = m.call_args.args[0]
        assert cmd[0] == "tmux" and "new-window" in cmd


def test_relaunch_headless_fallback_without_tmux(tmp_path):
    (tmp_path / "logs").mkdir()
    state = {"artifactDir": str(tmp_path), "tmuxSession": ""}
    with patch("orchestrate_watcher.subprocess.Popen") as mp:
        assert w.relaunch(state, tmp_path) is True
        mp.assert_called_once()
        assert mp.call_args.args[0][0] == "claude"


def test_bump_relaunch_count(tmp_path):
    (tmp_path / "resume-state.json").write_text('{"relaunchCount":1}')
    w.bump_relaunch_count(tmp_path)
    data = w._read_json(tmp_path / "resume-state.json")
    assert data["relaunchCount"] == 2


def test_write_give_up(tmp_path):
    w.write_give_up(tmp_path)
    assert (tmp_path / "resume-give-up.md").exists()


# --- Task 8: Watch loop + daemonize + CLI ---

def test_watch_loop_returns_finished_immediately(tmp_path):
    (tmp_path / "summary.json").write_text('{"finalStatus":"success"}')
    (tmp_path / "resume-state.json").write_text('{"relaunchCount":0}')
    rc = w.watch_loop(tmp_path, tmp_path, poll_interval=0, heartbeat_stale_s=900,
                      ttl_s=10_000, max_relaunch=3, probe_cmd=["claude"],
                      sleep=lambda s: None, probe=lambda c: False)
    assert rc == "finished"


def test_watch_loop_relaunches_after_limit_then_open(tmp_path):
    import datetime as _dt
    stale = (w.now() - _dt.timedelta(seconds=1200)).isoformat()
    (tmp_path / "summary.json").write_text('{"finalStatus":"in_progress"}')
    (tmp_path / "resume-state.json").write_text(
        '{"relaunchCount":0,"artifactDir":"%s","tmuxSession":"","heartbeat":"%s"}'
        % (tmp_path, stale))
    probes = iter([True, False])  # limited, then open

    def finish_after_relaunch(*_a, **_k):
        # The relaunched run starts and (here) completes.
        (tmp_path / "summary.json").write_text('{"finalStatus":"success"}')

    with patch("orchestrate_watcher.relaunch", return_value=True) as mrel, \
         patch("orchestrate_watcher.bump_relaunch_count",
               side_effect=finish_after_relaunch) as mbump:
        rc = w.watch_loop(tmp_path, tmp_path, poll_interval=0,
                          heartbeat_stale_s=900, ttl_s=10_000, max_relaunch=3,
                          probe_cmd=["claude"], sleep=lambda s: None,
                          probe=lambda c: next(probes))
    # The watcher relaunches once, keeps running, then exits when the resumed
    # run finishes (it does NOT exit immediately after relaunching).
    assert rc == "finished"
    mrel.assert_called_once()
    mbump.assert_called_once()


def test_watch_loop_persists_across_multiple_relaunches(tmp_path):
    """A single watcher handles two limit->open cycles without re-arming.

    Regression: the watcher used to exit right after the first relaunch, leaving
    a second limit during the resumed run uncovered.
    """
    import datetime as _dt
    stale = (w.now() - _dt.timedelta(seconds=1200)).isoformat()
    (tmp_path / "summary.json").write_text('{"finalStatus":"in_progress"}')
    (tmp_path / "resume-state.json").write_text(
        '{"relaunchCount":0,"artifactDir":"%s","tmuxSession":"","heartbeat":"%s"}'
        % (tmp_path, stale))
    # limited, open (relaunch #1), limited, open (relaunch #2)
    probes = iter([True, False, True, False])
    calls = {"n": 0}

    def relaunch_side_effect(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 2:
            (tmp_path / "summary.json").write_text('{"finalStatus":"success"}')
        return True

    # bump_relaunch_count is the REAL function so relaunchCount actually rises.
    with patch("orchestrate_watcher.relaunch", side_effect=relaunch_side_effect) as mrel:
        rc = w.watch_loop(tmp_path, tmp_path, poll_interval=0,
                          heartbeat_stale_s=900, ttl_s=10_000, max_relaunch=3,
                          probe_cmd=["claude"], sleep=lambda s: None,
                          probe=lambda c: next(probes))
    assert rc == "finished"
    assert mrel.call_count == 2
    assert w._read_json(tmp_path / "resume-state.json")["relaunchCount"] == 2


def test_watch_loop_does_not_relaunch_on_indeterminate_probe(tmp_path):
    """Latched limit + an indeterminate probe (None) must NOT relaunch.

    Regression: a None probe (unrelated failure/timeout) used to look identical
    to a reopened window (False) and wrongly triggered a relaunch.
    """
    import datetime as _dt
    stale = (w.now() - _dt.timedelta(seconds=1200)).isoformat()
    (tmp_path / "summary.json").write_text('{"finalStatus":"in_progress"}')
    (tmp_path / "resume-state.json").write_text(
        '{"relaunchCount":0,"artifactDir":"%s","tmuxSession":"","heartbeat":"%s"}'
        % (tmp_path, stale))
    # limited (latch), then indeterminate forever — never a confirmed open window
    probes = iter([True] + [None] * 50)
    clock_data = {"t": w.now()}

    def fake_clock():
        clock_data["t"] += _dt.timedelta(seconds=400)
        return clock_data["t"]

    with patch("orchestrate_watcher.relaunch") as mrel:
        rc = w.watch_loop(tmp_path, tmp_path, poll_interval=0,
                          heartbeat_stale_s=900, ttl_s=10_000, max_relaunch=3,
                          probe_cmd=["claude"], sleep=lambda s: None,
                          probe=lambda c: next(probes), clock=fake_clock)
    assert rc == "ttl_expired"
    mrel.assert_not_called()


def test_watch_loop_never_relaunches_when_never_limited(tmp_path):
    import datetime as _dt
    stale = (w.now() - _dt.timedelta(seconds=1200)).isoformat()
    (tmp_path / "summary.json").write_text('{"finalStatus":"in_progress"}')
    (tmp_path / "resume-state.json").write_text(
        '{"relaunchCount":0,"heartbeat":"%s"}' % stale)
    # account never limited (user quit); ttl reached after a couple ticks
    clock_data = {"t": w.now()}

    def fake_clock():
        clock_data["t"] += _dt.timedelta(seconds=20_000)
        return clock_data["t"]

    rc = w.watch_loop(tmp_path, tmp_path, poll_interval=0, heartbeat_stale_s=900,
                      ttl_s=10_000, max_relaunch=3, probe_cmd=["claude"],
                      sleep=lambda s: None, probe=lambda c: False,
                      clock=fake_clock)
    assert rc == "ttl_expired"


def test_watch_loop_max_relaunch_writes_give_up(tmp_path):
    (tmp_path / "summary.json").write_text('{"finalStatus":"in_progress"}')
    (tmp_path / "resume-state.json").write_text('{"relaunchCount":3}')
    rc = w.watch_loop(tmp_path, tmp_path, poll_interval=0, heartbeat_stale_s=900,
                      ttl_s=10_000, max_relaunch=3, probe_cmd=["claude"],
                      sleep=lambda s: None, probe=lambda c: False)
    assert rc == "max_relaunch"
    assert (tmp_path / "resume-give-up.md").exists()
