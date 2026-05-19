from unittest.mock import patch
from click.exceptions import Exit
import pytest
from textual.widgets import OptionList

from aque.desk import DeskApp, STATE_PRIORITY
from aque.state import AgentState, AgentInfo, StateManager


class TestStatePriority:
    def test_waiting_sorted_before_running(self):
        assert STATE_PRIORITY[AgentState.WAITING] < STATE_PRIORITY[AgentState.RUNNING]

    def test_exited_sorted_before_running(self):
        assert STATE_PRIORITY[AgentState.EXITED] < STATE_PRIORITY[AgentState.RUNNING]

    def test_on_hold_sorted_after_running(self):
        assert STATE_PRIORITY[AgentState.ON_HOLD] > STATE_PRIORITY[AgentState.RUNNING]


class TestDashboardMount:
    @pytest.mark.asyncio
    async def test_dashboard_shows_status_counts(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="db-1", label="a",
            dir="/tmp", command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="db-2", label="b",
            dir="/tmp", command=["b"], state=AgentState.WAITING, pid=101,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            status = str(app.query_one("#status-bar").render())
            assert "1 running" in status.lower() or "1" in status

    @pytest.mark.asyncio
    async def test_dashboard_shows_agent_list(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="db-1", label="claude . api",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            option_list = app.query_one("#agent-option-list")
            assert option_list.option_count == 1


class TestNewAgentFormWithPicker:
    @pytest.mark.asyncio
    async def test_new_agent_form_shows_type_selector(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.press("n")
            type_list = app.query_one("#type-list")
            assert type_list is not None

    @pytest.mark.asyncio
    async def test_new_agent_form_shows_dir_picker_after_type(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.press("n")
            await pilot.press("enter")
            picker = app.query_one("#dir-picker")
            assert picker is not None

    @pytest.mark.asyncio
    async def test_new_agent_form_no_folder_tree(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.press("n")
            await pilot.press("enter")
            trees = app.query("#dir-tree")
            assert len(trees) == 0


class TestNarrowMode:
    @pytest.mark.asyncio
    async def test_narrow_at_45_cols(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            assert app._is_narrow is True

    @pytest.mark.asyncio
    async def test_wide_at_80_cols(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(80, 24)) as pilot:
            assert app._is_narrow is False

    @pytest.mark.asyncio
    async def test_wide_at_120_cols(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            assert app._is_narrow is False

    @pytest.mark.asyncio
    async def test_narrow_hides_preview_panel(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            preview = app.query_one("#preview-panel")
            assert preview.display is False

    @pytest.mark.asyncio
    async def test_wide_shows_preview_panel(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            preview = app.query_one("#preview-panel")
            assert preview.display is True

    @pytest.mark.asyncio
    async def test_resize_toggles_layout(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            assert app.query_one("#preview-panel").display is True
            await pilot.resize_terminal(45, 24)
            await pilot.pause()
            assert app.query_one("#preview-panel").display is False
            await pilot.resize_terminal(120, 24)
            await pilot.pause()
            assert app.query_one("#preview-panel").display is True

    @pytest.mark.asyncio
    async def test_narrow_agent_label_compact(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="claude . my-project",
            dir="/tmp/my-project", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            opt = ol.get_option_at_index(0)
            label = str(opt.prompt)
            # Should NOT contain dir path or state word
            assert "/tmp" not in label
            assert "running" not in label.lower()
            # Should contain the agent label
            assert "claude . my-project" in label

    @pytest.mark.asyncio
    async def test_wide_agent_label_full(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="claude . my-project",
            dir="/tmp/my-project", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            opt = ol.get_option_at_index(0)
            label = str(opt.prompt)
            # Wide mode should contain state text and dir
            assert "running" in label.lower()
            assert "/tmp" in label


    @pytest.mark.asyncio
    async def test_narrow_status_bar_compact(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a",
            dir="/tmp", command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="s-2", label="b",
            dir="/tmp", command=["b"], state=AgentState.WAITING, pid=101,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            status = str(app.query_one("#status-bar").content)
            # Compact: should have abbreviated names
            assert "run" in status.lower()
            assert "wait" in status.lower()
            # Should NOT have the full word with extra spacing
            assert "running" not in status.lower()
            assert "waiting" not in status.lower()

    @pytest.mark.asyncio
    async def test_wide_status_bar_full(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a",
            dir="/tmp", command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            status = str(app.query_one("#status-bar").content)
            assert "running" in status.lower()

    @pytest.mark.asyncio
    async def test_resize_refreshes_agent_labels(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="claude . proj",
            dir="/tmp/proj", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            wide_label = str(ol.get_option_at_index(0).prompt)
            assert "running" in wide_label.lower()

            await pilot.resize_terminal(45, 24)
            await pilot.pause()
            narrow_label = str(ol.get_option_at_index(0).prompt)
            assert "running" not in narrow_label.lower()
            assert "claude . proj" in narrow_label


class TestDeskTmuxCheck:
    @patch("aque.cli.shutil.which", return_value=None)
    def test_desk_exits_when_tmux_not_installed(self, mock_which):
        from aque.cli import desk

        with pytest.raises(Exit):
            desk()

        mock_which.assert_called_once_with("tmux")

    @patch("aque.cli.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.desk.DeskApp")
    def test_desk_proceeds_when_tmux_installed(self, mock_desk_cls, mock_which):
        from aque.cli import desk
        desk()
        mock_which.assert_called_once_with("tmux")


class TestResponderVisibility:
    def test_responders_hidden_by_default(self, tmp_aque_dir):
        from aque.desk import DeskApp
        from aque.state import AgentInfo, AgentState, StateManager

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
        app = DeskApp(aque_dir=tmp_aque_dir)
        visible = app.visible_agents(mgr.load().agents)
        ids = {a.id for a in visible}
        assert ids == {1}

    def test_r_toggle_reveals_responders(self, tmp_aque_dir):
        from aque.desk import DeskApp
        from aque.state import AgentInfo, AgentState, StateManager

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
        app = DeskApp(aque_dir=tmp_aque_dir)
        app.show_responders = True
        visible = app.visible_agents(mgr.load().agents)
        ids = {a.id for a in visible}
        assert ids == {1, 2}


class TestAutoRespondToggle:
    @pytest.mark.asyncio
    async def test_a_key_toggles_auto_respond(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            ol.highlighted = 0
            app.action_toggle_auto_respond()
            assert mgr.load().agents[0].auto_respond is False

    @pytest.mark.asyncio
    async def test_a_key_noop_on_responder(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1, auto_respond=True,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        app.show_responders = True
        async with app.run_test() as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            # Find responder (id=2) in the list and highlight it
            for i in range(ol.option_count):
                if ol.get_option_at_index(i).id == "2":
                    ol.highlighted = i
                    break
            app.action_toggle_auto_respond()
            agents = mgr.load().agents
            by_id = {a.id: a for a in agents}
            assert by_id[1].auto_respond is True
            assert by_id[2].auto_respond is True


class TestAutoAttachSkipsResponders:
    def test_auto_attach_picks_partner_not_responder(self, tmp_aque_dir):
        from aque.desk import DeskApp
        from aque.state import AgentInfo, AgentState, StateManager

        mgr = StateManager(tmp_aque_dir)
        # Partner running.
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        # Responder waiting — must NOT be picked.
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.WAITING, pid=101,
            is_responder=True, partner_id=1,
        ))
        # Another partner waiting — this is the correct pick.
        mgr.add_agent(AgentInfo(
            id=3, tmux_session="aque-3", label="other partner",
            dir="/tmp", command=["claude"], state=AgentState.WAITING, pid=102,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir)
        picked = app.pick_auto_attach_target(mgr.load().agents)
        assert picked is not None
        assert picked.id == 3


class TestPreviewPaneAutoRespondLines:
    def _setup_pair(self, tmp_aque_dir):
        from aque.state import AgentInfo, AgentState, StateManager
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
        return mgr

    def test_preview_for_partner_shows_auto_response_on(self, tmp_aque_dir):
        from aque.desk import build_preview_meta
        mgr = self._setup_pair(tmp_aque_dir)
        agents = mgr.load().agents
        partner = next(a for a in agents if a.id == 1)
        text = build_preview_meta(partner, agents)
        assert "Auto-response: on" in text
        assert "aque-2" in text

    def test_preview_for_partner_shows_off_when_disabled(self, tmp_aque_dir):
        from aque.desk import build_preview_meta
        mgr = self._setup_pair(tmp_aque_dir)
        mgr.toggle_auto_respond(1)
        agents = mgr.load().agents
        partner = next(a for a in agents if a.id == 1)
        assert "Auto-response: off" in build_preview_meta(partner, agents)

    def test_preview_for_partner_without_responder_shows_unavailable(self, tmp_aque_dir):
        from aque.desk import build_preview_meta
        from aque.state import AgentInfo, AgentState, StateManager
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="solo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        agents = mgr.load().agents
        partner = next(a for a in agents if a.id == 1)
        text = build_preview_meta(partner, agents)
        assert "Auto-response: unavailable" in text

    def test_preview_for_responder_shows_partner_label(self, tmp_aque_dir):
        from aque.desk import build_preview_meta
        mgr = self._setup_pair(tmp_aque_dir)
        agents = mgr.load().agents
        responder_agent = next(a for a in agents if a.is_responder)
        text = build_preview_meta(responder_agent, agents)
        assert "Auto-responder for: partner" in text
        assert "id 1" in text or "id=1" in text

    def test_preview_for_partner_shows_exited_when_responder_exited(self, tmp_aque_dir):
        from aque.desk import build_preview_meta
        from aque.state import AgentInfo, AgentState, StateManager

        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.EXITED, pid=101,
            is_responder=True, partner_id=1,
        ))
        agents = mgr.load().agents
        partner = next(a for a in agents if a.id == 1)
        text = build_preview_meta(partner, agents)
        assert "Responder exited" in text
        assert "auto-response disabled" in text


def test_desk_orphan_scan_called_on_startup(monkeypatch, tmp_aque_dir):
    """When state.json has an agent whose tmux session is gone, desk's
    startup pushes an OrphanModal."""
    import json
    from aque import desk
    from aque.widgets.orphan_modal import OrphanModal

    state_path = tmp_aque_dir / "state.json"
    state_path.write_text(json.dumps({
        "agents": [{
            "id": 1, "tmux_session": "aque-1", "label": "x", "dir": "/tmp",
            "command": ["claude"], "state": "running", "pid": 1,
            "created_at": "2026-05-18T00:00:00Z",
            "last_change_at": "2026-05-18T00:00:00Z",
            "agent_type": "claude", "session_id": "uuid-1",
        }],
        "monitor_pid": None,
    }))

    pushed: list = []
    monkeypatch.setattr(desk.DeskApp, "push_screen",
                        lambda self, screen: pushed.append(screen))

    # Fake libtmux.Server so session_exists always returns False (no live session).
    class _FakeServer:
        @property
        def sessions(self):
            class L:
                def get(self, session_name=None, default=None):
                    return default  # nothing live
            return L()
    monkeypatch.setattr(desk.libtmux, "Server", lambda: _FakeServer())

    app = desk.DeskApp(aque_dir=tmp_aque_dir)
    app._scan_for_orphans()

    assert len(pushed) == 1
    assert isinstance(pushed[0], OrphanModal)


def test_desk_orphan_scan_skips_modal_when_no_orphans(monkeypatch, tmp_aque_dir):
    """When all agents have live tmux sessions, no modal is pushed."""
    import json
    from aque import desk

    state_path = tmp_aque_dir / "state.json"
    state_path.write_text(json.dumps({"agents": [], "monitor_pid": None}))

    pushed: list = []
    monkeypatch.setattr(desk.DeskApp, "push_screen",
                        lambda self, screen: pushed.append(screen))
    monkeypatch.setattr(desk.libtmux, "Server", lambda: object())

    app = desk.DeskApp(aque_dir=tmp_aque_dir)
    app._scan_for_orphans()

    assert pushed == []


def test_desk_orphan_scan_skipped_when_skip_attach_true(monkeypatch, tmp_aque_dir):
    """The _skip_attach flag (used by BDD test fixtures) must suppress
    orphan scanning so phantom modals don't steal focus in tests."""
    import json
    from aque import desk

    state_path = tmp_aque_dir / "state.json"
    state_path.write_text(json.dumps({
        "agents": [{
            "id": 1, "tmux_session": "aque-1", "label": "x", "dir": "/tmp",
            "command": ["claude"], "state": "running", "pid": 1,
            "created_at": "2026-05-18T00:00:00Z",
            "last_change_at": "2026-05-18T00:00:00Z",
        }],
        "monitor_pid": None,
    }))

    pushed: list = []
    monkeypatch.setattr(desk.DeskApp, "push_screen",
                        lambda self, screen: pushed.append(screen))

    app = desk.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    app._scan_for_orphans()

    assert pushed == []
