"""Tests for the auto-responder module."""
from unittest.mock import MagicMock, patch

import pytest

from aque.state import AgentInfo, AgentState, StateManager


class TestSystemPrompt:
    def test_includes_partner_session_and_id(self):
        from aque.responder import system_prompt

        partner = AgentInfo(
            id=7, tmux_session="aque-foo-7", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        text = system_prompt(partner)
        assert "aque-foo-7" in text
        assert "id 7" in text or "id=7" in text

    def test_mentions_tmux_tools(self):
        from aque.responder import system_prompt

        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        text = system_prompt(partner)
        assert "tmux capture-pane" in text
        assert "tmux send-keys" in text


class TestFindFor:
    def test_returns_responder_when_paired(self, tmp_aque_dir):
        from aque.responder import find_for

        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        ))
        state = mgr.load()
        responder = find_for(1, state.agents)
        assert responder is not None
        assert responder.id == 2

    def test_returns_none_when_no_pair(self, tmp_aque_dir):
        from aque.responder import find_for

        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="solo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        state = mgr.load()
        assert find_for(1, state.agents) is None


class TestCreateFor:
    @patch("aque.responder.launch_agent")
    def test_create_for_spawns_responder_record(self, mock_launch, tmp_aque_dir):
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp/partner", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        # launch_agent is mocked; simulate it adding the responder record itself
        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"aque-resp-1-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {
            "responder_command": ["claude", "--model", "haiku"],
            "responder_dir": None,
            "session_prefix": "aque",
        }
        responder_id = create_for(partner, config, mgr, aque_dir=tmp_aque_dir)

        assert responder_id == 2
        call_kwargs = mock_launch.call_args.kwargs
        assert call_kwargs["command"] == ["claude", "--model", "haiku"]
        assert call_kwargs["working_dir"] == str(tmp_aque_dir / "responders" / "1")
        assert call_kwargs["label"] == "resp(1)"

        state = mgr.load()
        responder = next(a for a in state.agents if a.id == responder_id)
        assert responder.is_responder is True
        assert responder.partner_id == 1

    @patch("aque.responder.launch_agent")
    def test_create_for_uses_explicit_responder_dir(self, mock_launch, tmp_aque_dir):
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"resp-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {
            "responder_command": ["claude"],
            "responder_dir": "/custom/responder/dir",
            "session_prefix": "aque",
        }
        create_for(partner, config, mgr, aque_dir=tmp_aque_dir)
        assert mock_launch.call_args.kwargs["working_dir"] == "/custom/responder/dir"

    @patch("aque.responder.launch_agent")
    def test_create_for_creates_working_dir(self, mock_launch, tmp_aque_dir):
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"resp-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {"responder_command": ["claude"], "responder_dir": None, "session_prefix": "aque"}
        create_for(partner, config, mgr, aque_dir=tmp_aque_dir)

        expected = tmp_aque_dir / "responders" / "1"
        assert expected.is_dir()

    @patch("aque.responder._send_system_prompt")
    @patch("aque.responder.launch_agent")
    def test_create_for_schedules_system_prompt_delivery(self, mock_launch, mock_send, tmp_aque_dir):
        """create_for must arrange for system_prompt to be typed into the responder."""
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"aque-resp-1-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {"responder_command": ["claude"], "responder_dir": None, "session_prefix": "aque"}
        create_for(partner, config, mgr, aque_dir=tmp_aque_dir)

        # _send_system_prompt was called with the responder's session name and the partner's system_prompt
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        # First positional or 'tmux_session' keyword is the responder session
        session_arg = args[0] if args else kwargs.get("tmux_session")
        text_arg = args[1] if len(args) > 1 else kwargs.get("text", kwargs.get("prompt_text"))
        assert session_arg.startswith("aque-resp-1-")
        assert "aque-foo-1" in text_arg  # the prompt mentions the partner


class TestSendSystemPrompt:
    @patch("aque.responder.libtmux.Server")
    @patch("aque.responder.time.sleep")
    def test_send_system_prompt_types_into_pane(self, mock_sleep, mock_server_cls):
        from aque.responder import _send_system_prompt
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        session = MagicMock()
        pane = MagicMock()
        session.active_pane = pane
        mock_server.sessions.get.return_value = session

        _send_system_prompt("aque-resp-1-2", "Hello partner")

        mock_sleep.assert_called_once()  # waited for CLI startup
        pane.send_keys.assert_called_once_with("Hello partner", enter=True)

    @patch("aque.responder.libtmux.Server")
    @patch("aque.responder.time.sleep")
    def test_send_system_prompt_tolerates_missing_session(self, mock_sleep, mock_server_cls):
        from aque.responder import _send_system_prompt
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_server.sessions.get.return_value = None
        # Should not raise.
        _send_system_prompt("aque-resp-1-2", "Hello")


class TestNudge:
    def _make_pair(self):
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.WAITING, pid=100,
        )
        responder = AgentInfo(
            id=2, tmux_session="aque-resp-1-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        )
        return partner, responder

    def test_nudge_types_into_responder_pane(self, tmp_aque_dir):
        from aque.responder import nudge

        partner, responder = self._make_pair()
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(partner)
        mgr.add_agent(responder)

        server = MagicMock()
        session = MagicMock()
        pane = MagicMock()
        session.active_pane = pane
        server.sessions.get.return_value = session

        result = nudge(partner, responder, server, state_manager=mgr)
        assert result is True

        pane.send_keys.assert_called_once()
        line = pane.send_keys.call_args.args[0]
        assert line.startswith("AQUE:")
        assert "aque-foo-1" in line
        assert "id=1" in line

        reloaded = mgr.load()
        partner_now = next(a for a in reloaded.agents if a.id == 1)
        assert partner_now.last_nudge_at is not None

    def test_nudge_skips_when_auto_respond_false(self, tmp_aque_dir):
        from aque.responder import nudge

        partner, responder = self._make_pair()
        partner.auto_respond = False
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(partner)
        mgr.add_agent(responder)

        server = MagicMock()
        result = nudge(partner, responder, server, state_manager=mgr)
        assert result is False
        server.sessions.get.assert_not_called()

    def test_nudge_does_not_reference_focused(self, tmp_aque_dir):
        """A RUNNING responder is nudged normally; no FOCUSED special-case exists."""
        from aque.responder import nudge

        partner, responder = self._make_pair()
        # responder.state is already RUNNING (from _make_pair)
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(partner)
        mgr.add_agent(responder)

        server = MagicMock()
        session = MagicMock()
        pane = MagicMock()
        session.active_pane = pane
        server.sessions.get.return_value = session

        result = nudge(partner, responder, server, state_manager=mgr)
        assert result is True
        pane.send_keys.assert_called_once()

    def test_nudge_skips_when_session_missing(self, tmp_aque_dir):
        from aque.responder import nudge

        partner, responder = self._make_pair()
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(partner)
        mgr.add_agent(responder)

        server = MagicMock()
        server.sessions.get.return_value = None

        result = nudge(partner, responder, server, state_manager=mgr)
        assert result is False


class TestCleanup:
    def test_cleanup_kills_session_and_removes_state(self, tmp_aque_dir):
        from aque.responder import cleanup

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.EXITED, pid=100,
        )
        responder = AgentInfo(
            id=2, tmux_session="aque-resp-1-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        )
        mgr.add_agent(partner)
        mgr.add_agent(responder)

        server = MagicMock()
        session = MagicMock()
        server.sessions.get.return_value = session

        (tmp_aque_dir / "responders" / "1").mkdir(parents=True, exist_ok=True)

        cleanup(partner, mgr, server, aque_dir=tmp_aque_dir)

        session.kill.assert_called_once()
        state = mgr.load()
        assert all(a.id != 2 for a in state.agents)
        assert not (tmp_aque_dir / "responders" / "1").exists()

    def test_cleanup_when_no_responder_is_noop(self, tmp_aque_dir):
        from aque.responder import cleanup

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.EXITED, pid=100,
        )
        mgr.add_agent(partner)
        server = MagicMock()

        cleanup(partner, mgr, server, aque_dir=tmp_aque_dir)
        state = mgr.load()
        assert any(a.id == 1 for a in state.agents)

    def test_cleanup_tolerates_missing_tmux_session(self, tmp_aque_dir):
        from aque.responder import cleanup

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.EXITED, pid=100,
        )
        responder = AgentInfo(
            id=2, tmux_session="aque-resp-1-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        )
        mgr.add_agent(partner)
        mgr.add_agent(responder)

        server = MagicMock()
        server.sessions.get.return_value = None  # session already gone

        cleanup(partner, mgr, server, aque_dir=tmp_aque_dir)
        state = mgr.load()
        assert all(a.id != 2 for a in state.agents)
