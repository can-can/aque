from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aque.run import launch_agent
from aque.state import AgentState, StateManager


class TestLaunchAgent:
    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_creates_session_and_registers_agent(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        agent_id = launch_agent(
            command=["claude", "--model", "opus"],
            working_dir="/tmp/my-api",
            label="auth fix",
            state_manager=mgr,
        )

        assert agent_id == 1
        mock_server.new_session.assert_called_once()
        call_kwargs = mock_server.new_session.call_args.kwargs
        assert "window_command" not in call_kwargs
        assert call_kwargs["start_directory"] == "/tmp/my-api"
        mock_wait.assert_called_once_with(mock_pane)
        mock_pane.send_keys.assert_called_once_with("claude --model opus", enter=True)
        state = mgr.load()
        assert len(state.agents) == 1
        assert state.agents[0].label == "auth fix"
        assert state.agents[0].state == AgentState.RUNNING
        assert state.agents[0].dir == "/tmp/my-api"
        assert state.agents[0].command == ["claude", "--model", "opus"]

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_default_label(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["claude"],
            working_dir="/tmp/my-api",
            label=None,
            state_manager=mgr,
        )

        state = mgr.load()
        assert state.agents[0].label == "claude . my-api"

    @patch("aque.run.shutil.which", return_value=None)
    def test_launch_raises_when_tmux_not_installed(self, mock_which, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)

        with pytest.raises(RuntimeError, match="tmux is not installed"):
            launch_agent(
                command=["claude"],
                working_dir="/tmp/test",
                label="test",
                state_manager=mgr,
            )

        mock_which.assert_called_once_with("tmux")
        state = mgr.load()
        assert len(state.agents) == 0

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_waits_for_shell_then_sends_keys(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["claude", "--arg", "with spaces"],
            working_dir="/tmp/test",
            label="test",
            state_manager=mgr,
        )

        call_kwargs = mock_server.new_session.call_args.kwargs
        assert "window_command" not in call_kwargs
        mock_wait.assert_called_once_with(mock_pane)
        mock_pane.send_keys.assert_called_once_with("claude --arg 'with spaces'", enter=True)

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_background_returns_before_finalize(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        import time
        import aque.run

        # Make _wait_for_shell take a moment so we can observe ordering
        mock_wait.side_effect = lambda pane: time.sleep(0.1)

        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-bg-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        agent_id = launch_agent(
            command=["claude", "--model", "opus"],
            working_dir="/tmp/test",
            label="bg test",
            state_manager=mgr,
            background=True,
        )

        # launch_agent returned immediately — agent is in state
        assert agent_id == 1
        state = mgr.load()
        assert len(state.agents) == 1
        assert state.agents[0].label == "bg test"

        # send_keys has NOT been called yet (thread is still in _wait_for_shell sleep)
        mock_pane.send_keys.assert_not_called()

        # Join the background thread and verify finalization completed
        threads = list(aque.run._background_threads)
        aque.run._background_threads.clear()
        for t in threads:
            t.join(timeout=2.0)

        mock_wait.assert_called_once_with(mock_pane)
        mock_pane.send_keys.assert_called_once_with("claude --model opus", enter=True)


class TestLaunchAgentType:
    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_with_type_stores_agent_type(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["claude", "--model", "opus"],
            working_dir="/tmp/test",
            label="test",
            state_manager=mgr,
            agent_type="claude",
        )
        state = mgr.load()
        assert state.agents[0].agent_type == "claude"

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_without_type_stores_none(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["aider"],
            working_dir="/tmp/test",
            label="test",
            state_manager=mgr,
        )
        state = mgr.load()
        assert state.agents[0].agent_type is None

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_with_type_exports_env_var(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        agent_id = launch_agent(
            command=["claude"],
            working_dir="/tmp/test",
            label="test",
            state_manager=mgr,
            agent_type="claude",
        )

        # send_keys should be called twice: first export, then command
        calls = mock_pane.send_keys.call_args_list
        assert len(calls) == 2
        # First call: export env var
        assert calls[0][0][0] == f"export AQUE_AGENT_ID={agent_id}"
        assert calls[0][1]["enter"] is True
        # Second call: the actual command
        assert calls[1][0][0] == "claude"
        assert calls[1][1]["enter"] is True

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_without_type_no_export(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["aider"],
            working_dir="/tmp/test",
            label="test",
            state_manager=mgr,
        )

        # Only one send_keys call (the command itself)
        calls = mock_pane.send_keys.call_args_list
        assert len(calls) == 1


class TestSignalsDir:
    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_with_type_creates_signals_dir(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["claude"],
            working_dir="/tmp/test",
            label="test",
            state_manager=mgr,
            agent_type="claude",
        )
        assert (tmp_aque_dir / "signals").is_dir()


def test_finalize_captures_claude_session_id(monkeypatch, tmp_path):
    """When agent_type=claude, _finalize polls the session dir and persists
    the newly-appeared UUID via state_manager.set_session_id."""
    from aque import run, sessions
    from aque.state import AgentInfo, AgentState

    monkeypatch.setenv("HOME", str(tmp_path))
    session_dir = tmp_path / ".claude" / "projects" / "-tmp-x"
    session_dir.mkdir(parents=True)

    captured: dict = {}

    class FakeMgr:
        aque_dir = tmp_path / ".aque"
        def set_session_id(self, aid, sid):
            captured["agent_id"] = aid
            captured["session_id"] = sid

    # Spawn the new UUID file partway through the poll window.
    import threading, time
    def delayed_write():
        time.sleep(0.6)
        (session_dir / "new-uuid.jsonl").write_text("")
    threading.Thread(target=delayed_write, daemon=True).start()

    run._capture_session_id(
        agent_id=7,
        agent_type="claude",
        working_dir="/tmp/x",
        state_manager=FakeMgr(),
        timeout=5.0,
    )

    assert captured == {"agent_id": 7, "session_id": "new-uuid"}


def test_finalize_capture_noop_for_unknown_type(tmp_path):
    from aque import run

    class FakeMgr:
        def set_session_id(self, *a, **kw):
            raise AssertionError("should not be called for unsupported types")

    # Should return silently for None / 'aider' / unknown types.
    run._capture_session_id(
        agent_id=7, agent_type=None,
        working_dir="/tmp/x", state_manager=FakeMgr(), timeout=0.1,
    )
    run._capture_session_id(
        agent_id=7, agent_type="aider",
        working_dir="/tmp/x", state_manager=FakeMgr(), timeout=0.1,
    )


def test_finalize_capture_timeout_leaves_session_id_unset(monkeypatch, tmp_path):
    from aque import run
    monkeypatch.setenv("HOME", str(tmp_path))

    class FakeMgr:
        def set_session_id(self, *a, **kw):
            raise AssertionError("should not be called on timeout")

    run._capture_session_id(
        agent_id=7, agent_type="claude",
        working_dir="/tmp/x", state_manager=FakeMgr(), timeout=0.3,
    )


def test_relaunch_agent_updates_existing_record_in_place(tmp_aque_dir, monkeypatch):
    """relaunch_agent reuses the same agent ID, swaps tmux_session/pid/state,
    and (optionally) preserves session_id."""
    from aque import run
    from aque.state import AgentInfo, AgentState, StateManager

    mgr = StateManager(tmp_aque_dir)
    mgr.add_agent(AgentInfo(
        id=5, tmux_session="aque-old", label="x", dir="/tmp",
        command=["claude"], state=AgentState.EXITED, pid=999,
        agent_type="claude", session_id="old-uuid",
    ))

    fake_session = type("S", (), {
        "set_option": lambda self, *a, **kw: None,
        "active_pane": type("P", (), {
            "pane_pid": "1234",
            "capture_pane": lambda self: [""],
            "send_keys": lambda self, *a, **kw: None,
        })(),
    })()
    fake_server = type("Srv", (), {
        "sessions": type("S", (), {
            "get": lambda self, session_name=None, default=None: default,
        })(),
        "new_session": lambda self, **kw: fake_session,
    })()
    monkeypatch.setattr(run.libtmux, "Server", lambda: fake_server)
    monkeypatch.setattr(run.shutil, "which", lambda x: "/usr/bin/tmux")
    monkeypatch.setattr(run, "_wait_for_shell", lambda *a, **kw: None)

    run.relaunch_agent(
        agent_id=5,
        command=["claude", "--resume", "old-uuid"],
        state_manager=mgr,
        preserve_session_id=True,
    )

    loaded = mgr.load()
    a = loaded.agents[0]
    assert a.id == 5
    assert a.state == AgentState.RUNNING
    assert a.pid == 1234
    assert a.tmux_session != "aque-old"  # new session name minted
    assert a.session_id == "old-uuid"   # preserved


def test_relaunch_agent_clears_session_id_when_requested(tmp_aque_dir, monkeypatch):
    from aque import run
    from aque.state import AgentInfo, AgentState, StateManager

    mgr = StateManager(tmp_aque_dir)
    mgr.add_agent(AgentInfo(
        id=5, tmux_session="aque-old", label="x", dir="/tmp",
        command=["claude"], state=AgentState.EXITED, pid=1,
        agent_type="claude", session_id="old-uuid",
    ))

    fake_session = type("S", (), {
        "set_option": lambda self, *a, **kw: None,
        "active_pane": type("P", (), {
            "pane_pid": "1",
            "capture_pane": lambda self: [""],
            "send_keys": lambda self, *a, **kw: None,
        })(),
    })()
    fake_server = type("Srv", (), {
        "sessions": type("S", (), {
            "get": lambda self, session_name=None, default=None: default,
        })(),
        "new_session": lambda self, **kw: fake_session,
    })()
    monkeypatch.setattr(run.libtmux, "Server", lambda: fake_server)
    monkeypatch.setattr(run.shutil, "which", lambda x: "/usr/bin/tmux")
    monkeypatch.setattr(run, "_wait_for_shell", lambda *a, **kw: None)

    run.relaunch_agent(
        agent_id=5,
        command=["claude"],
        state_manager=mgr,
        preserve_session_id=False,
    )

    a = mgr.load().agents[0]
    assert a.session_id is None
