"""Unit tests for ``LaunchCoordinator`` — no Textual app required.

The coordinator's three branches:
    - claude with prior sessions → push picker, callback drives finish
    - claude with no prior sessions → preassign + finish synchronously
    - non-claude → finish synchronously, no capture
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from aque.launch import LaunchCoordinator
from aque.sessions import SessionSummary
from aque.state import AgentInfo, AgentState, StateManager
from aque.dir_history import DirHistoryManager
from aque.widgets.resume_picker import PickerResult, ResumePickerScreen


@pytest.fixture
def coordinator(tmp_aque_dir):
    """A coordinator wired with a real state manager but stubbed UI hooks."""
    pushed: list = []
    monitor_calls: list = []

    def push_modal(screen, callback):
        pushed.append((screen, callback))

    def ensure_monitor():
        monitor_calls.append(True)

    coord = LaunchCoordinator(
        state_mgr=StateManager(tmp_aque_dir),
        config={"session_prefix": "aque-test"},
        aque_dir=tmp_aque_dir,
        dir_history_mgr=DirHistoryManager(tmp_aque_dir),
        push_modal=push_modal,
        ensure_monitor=ensure_monitor,
    )
    # Attach probes so tests can inspect.
    coord._pushed = pushed
    coord._monitor_calls = monitor_calls
    return coord


def _fake_launch_agent(launched):
    """Build a launch_agent stub that appends kwargs and registers the agent."""
    def fake(**kwargs):
        launched.append(kwargs)
        # Register the agent so on_launched can find it via state.get_agent.
        kwargs["state_manager"].add_agent(AgentInfo(
            id=1,
            tmux_session="aque-test-1",
            label=kwargs.get("label") or "test",
            dir=kwargs["working_dir"],
            command=kwargs["command"],
            state=AgentState.RUNNING,
            pid=12345,
            agent_type=kwargs.get("agent_type"),
            session_id=kwargs.get("session_id"),
        ))
        return 1
    return fake


class TestNonClaudeBypassesPicker:
    def test_launches_directly_with_no_session_capture(self, coordinator):
        launched: list = []
        delivered: list = []
        with patch("aque.launch.launch_agent", _fake_launch_agent(launched)):
            coordinator.launch(
                command=["echo", "hi"],
                working_dir="/tmp/x",
                label="t",
                agent_type=None,
                on_launched=delivered.append,
            )

        assert coordinator._pushed == []  # no picker
        assert len(launched) == 1
        assert launched[0]["session_id"] is None
        assert launched[0]["agent_type"] is None
        assert len(delivered) == 1
        assert delivered[0].label == "t"


class TestClaudeWithNoPriorSessions:
    def test_preassigns_session_id_and_skips_picker(self, coordinator):
        launched: list = []
        delivered: list = []
        with (
            patch("aque.plugins.claude.summarize", lambda cwd: []),
            patch("aque.launch.launch_agent", _fake_launch_agent(launched)),
        ):
            coordinator.launch(
                command=["claude"],
                working_dir="/tmp/x",
                label="fresh",
                agent_type="claude",
                on_launched=delivered.append,
            )

        assert coordinator._pushed == []  # no picker for empty dir
        assert len(launched) == 1
        # Preassign wrote a fresh --session-id into the command.
        assert "--session-id" in launched[0]["command"]
        assert launched[0]["session_id"] is not None
        assert len(delivered) == 1


def _one_summary():
    return SessionSummary(
        uuid="x", first_prompt=None, last_activity=None,
        mtime=datetime.now(timezone.utc), size_bytes=1,
    )


class TestClaudeWithPriorSessions:
    def test_pushes_picker_and_does_not_launch_synchronously(self, coordinator):
        launched: list = []
        delivered: list = []
        with (
            patch("aque.plugins.claude.summarize",
                  lambda cwd: [_one_summary()]),
            patch("aque.launch.launch_agent", _fake_launch_agent(launched)),
        ):
            coordinator.launch(
                command=["claude"],
                working_dir="/tmp/x",
                label="t",
                agent_type="claude",
                on_launched=delivered.append,
            )

        assert len(coordinator._pushed) == 1
        screen, callback = coordinator._pushed[0]
        assert isinstance(screen, ResumePickerScreen)
        assert launched == []  # didn't launch yet
        assert delivered == []  # nothing delivered yet

    def test_picker_cancel_invokes_on_cancelled_and_skips_launch(
        self, coordinator
    ):
        launched: list = []
        delivered: list = []
        cancelled: list = []
        with (
            patch("aque.plugins.claude.summarize",
                  lambda cwd: [_one_summary()]),
            patch("aque.launch.launch_agent", _fake_launch_agent(launched)),
        ):
            coordinator.launch(
                command=["claude"], working_dir="/tmp/x",
                label="t", agent_type="claude",
                on_launched=delivered.append,
                on_cancelled=lambda: cancelled.append(True),
            )
            _, callback = coordinator._pushed[0]
            callback(None)  # user dismissed

        assert cancelled == [True]
        assert launched == []
        assert delivered == []

    def test_picker_fresh_preassigns_and_finishes(self, coordinator):
        launched: list = []
        delivered: list = []
        with (
            patch("aque.plugins.claude.summarize",
                  lambda cwd: [_one_summary()]),
            patch("aque.launch.launch_agent", _fake_launch_agent(launched)),
        ):
            coordinator.launch(
                command=["claude"], working_dir="/tmp/x",
                label="fresh", agent_type="claude",
                on_launched=delivered.append,
            )
            _, callback = coordinator._pushed[0]
            callback(PickerResult(action="fresh", session_id=None))

        assert len(launched) == 1
        assert "--session-id" in launched[0]["command"]
        assert launched[0]["session_id"] is not None
        assert len(delivered) == 1

    def test_picker_resume_rewrites_command_with_session_id(self, coordinator):
        launched: list = []
        delivered: list = []
        with (
            patch("aque.plugins.claude.summarize",
                  lambda cwd: [_one_summary()]),
            patch("aque.launch.launch_agent", _fake_launch_agent(launched)),
        ):
            coordinator.launch(
                command=["claude"], working_dir="/tmp/x",
                label="resume", agent_type="claude",
                on_launched=delivered.append,
            )
            _, callback = coordinator._pushed[0]
            callback(PickerResult(action="resume", session_id="aaa-bbb"))

        assert len(launched) == 1
        assert "--resume" in launched[0]["command"]
        assert "aaa-bbb" in launched[0]["command"]
        assert launched[0]["session_id"] == "aaa-bbb"


class TestResponderPairing:
    def test_paired_when_include_responder_true(self, coordinator):
        paired: list = []
        with (
            patch("aque.launch.launch_agent", _fake_launch_agent([])),
            patch("aque.launch.responder.create_for",
                  lambda partner, cfg, sm, *, aque_dir: paired.append(partner.id)),
        ):
            coordinator.launch(
                command=["echo"], working_dir="/tmp/x",
                label="t", agent_type=None,
                on_launched=lambda a: None,
                include_responder=True,
            )
        assert paired == [1]

    def test_not_paired_by_default(self, coordinator):
        """``include_responder`` defaults to False — pairing is opt-in."""
        paired: list = []
        with (
            patch("aque.launch.launch_agent", _fake_launch_agent([])),
            patch("aque.launch.responder.create_for",
                  lambda partner, cfg, sm, *, aque_dir: paired.append(partner.id)),
        ):
            coordinator.launch(
                command=["echo"], working_dir="/tmp/x",
                label="t", agent_type=None,
                on_launched=lambda a: None,
            )
        assert paired == []


class TestResume:
    def test_calls_relaunch_with_capturer_rewritten_command(
        self, coordinator, tmp_aque_dir
    ):
        agent = AgentInfo(
            id=7, tmux_session="aque-7", label="x", dir="/tmp",
            command=["claude"], state=AgentState.RUNNING, pid=1,
            agent_type="claude", session_id="uuid-1",
        )
        coordinator.state_mgr.add_agent(agent)
        relaunch_args: dict = {}

        def fake_relaunch(**kwargs):
            relaunch_args.update(kwargs)

        with patch("aque.launch.relaunch_agent", fake_relaunch):
            coordinator.resume(agent)

        assert relaunch_args["agent_id"] == 7
        assert "--resume" in relaunch_args["command"]
        assert "uuid-1" in relaunch_args["command"]
        assert relaunch_args["preserve_session_id"] is True
