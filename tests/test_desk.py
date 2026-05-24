from unittest.mock import patch
from click.exceptions import Exit
import pytest
from textual.widgets import OptionList

from aque import desk_tokens
import aque.desk as desk
from aque.desk import DeskApp, STATE_PRIORITY, sorted_agents
from aque.state import AgentState, AgentInfo, StateManager


def _agent(id: int, dir: str, label: str, state: AgentState = AgentState.RUNNING) -> AgentInfo:
    return AgentInfo(
        id=id,
        tmux_session=f"aque-{id}",
        label=label,
        dir=dir,
        command=["claude"],
        state=state,
        pid=1000 + id,
    )


def test_no_focused_in_token_maps():
    assert AgentState.RUNNING in desk_tokens.STATE_COLORS
    assert all(
        getattr(s, "name", "") != "FOCUSED" for s in desk_tokens.STATE_COLORS
    )
    assert all(
        getattr(s, "name", "") != "FOCUSED" for s in desk.STATE_PRIORITY
    )


class TestStatePriority:
    def test_waiting_sorted_before_running(self):
        assert STATE_PRIORITY[AgentState.WAITING] < STATE_PRIORITY[AgentState.RUNNING]

    def test_exited_sorted_before_running(self):
        assert STATE_PRIORITY[AgentState.EXITED] < STATE_PRIORITY[AgentState.RUNNING]

    def test_on_hold_sorted_after_running(self):
        assert STATE_PRIORITY[AgentState.ON_HOLD] > STATE_PRIORITY[AgentState.RUNNING]


class TestSortedAgents:
    def test_sorts_by_last_two_dir_elements(self):
        agents = [
            _agent(1, "/Users/cancan/Projects/zeta", "a"),
            _agent(2, "/Users/cancan/Projects/alpha", "b"),
            _agent(3, "/home/x/Work/beta", "c"),
        ]
        ordered = [a.id for a in sorted_agents(agents)]
        # ("Projects", "alpha") < ("Projects", "zeta") < ("Work", "beta")
        assert ordered == [2, 1, 3]

    def test_same_folder_sorts_by_label(self):
        agents = [
            _agent(1, "/Users/cancan/Projects/aque", "charlie"),
            _agent(2, "/Users/cancan/Projects/aque", "alice"),
            _agent(3, "/Users/cancan/Projects/aque", "bob"),
        ]
        ordered = [a.id for a in sorted_agents(agents)]
        assert ordered == [2, 3, 1]

    def test_status_does_not_affect_order(self):
        # A RUNNING agent in an earlier folder beats a WAITING one later,
        # even though WAITING used to sort first.
        agents = [
            _agent(1, "/p/zeta", "z", state=AgentState.WAITING),
            _agent(2, "/p/alpha", "a", state=AgentState.RUNNING),
        ]
        ordered = [a.id for a in sorted_agents(agents)]
        assert ordered == [2, 1]


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
    async def test_narrow_stacks_and_keeps_preview(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            # Narrow now STACKS (list over terminal) instead of hiding the
            # preview — the terminal stays visible at the bottom.
            assert app.query_one("#dashboard").has_class("stacked")
            assert app.query_one("#preview-panel").display is True

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
            # Wide: two columns, not stacked.
            assert not app.query_one("#dashboard").has_class("stacked")
            await pilot.resize_terminal(45, 24)
            await pilot.pause()
            assert app.query_one("#dashboard").has_class("stacked")
            await pilot.resize_terminal(120, 24)
            await pilot.pause()
            assert not app.query_one("#dashboard").has_class("stacked")
            # Preview stays displayed throughout (terminal is never hidden now).
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
            dir="/tmp/my-project", command=["claude"], state=AgentState.RUNNING,
            pid=100, agent_type="claude",
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            opt = ol.get_option_at_index(0)
            label = str(opt.prompt)
            # Project layout: dot (colour only), name, mode chip. The state
            # word, dir, and agent type live in the preview pane, not the row.
            assert "running" not in label.lower()
            # The agent type is no longer shown on the row, so "claude" appears
            # only once — as part of the name.
            assert label.count("claude") == 1
            assert "claude . my-project" in label
            assert "auto" in label  # mode chip present in the full layout


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
            # Wide pads the name into a right-hand column; resize must rebuild.
            assert "claude . proj" in wide_label
            assert "running" not in wide_label.lower()

            await pilot.resize_terminal(45, 24)
            await pilot.pause()
            narrow_label = str(ol.get_option_at_index(0).prompt)
            assert "running" not in narrow_label.lower()
            assert "claude . proj" in narrow_label
            # Resize rebuilds the row — the mode chip re-aligns to the new
            # column width — so the rendered label differs between layouts.
            assert narrow_label != wide_label


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


def test_handle_orphan_action_resume_rebuilds_responder(monkeypatch, tmp_aque_dir):
    """After Resume succeeds, the partner's dead responder is cleaned up and a
    fresh one is created. Verifies spec edge case for responder lifecycle."""
    from aque import desk, responder
    from aque.state import AgentInfo, AgentState

    app = desk.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    app.config = {"responder_enabled": True, "responder_command": ["claude"], "session_prefix": "aque"}

    app.state_mgr.add_agent(AgentInfo(
        id=1, tmux_session="aque-1", label="builder", dir="/tmp",
        command=["claude"], state=AgentState.RUNNING, pid=1,
        agent_type="claude", session_id="uuid-1",
    ))

    cleanup_calls: list = []
    create_calls: list = []
    monkeypatch.setattr(responder, "cleanup",
                        lambda partner, sm, server, *, aque_dir: cleanup_calls.append(partner.id))
    monkeypatch.setattr(responder, "create_for",
                        lambda partner, cfg, sm, *, aque_dir: create_calls.append(partner.id) or 99)
    monkeypatch.setattr(desk, "relaunch_agent",
                        lambda agent_id, command, state_manager, *, preserve_session_id=True: None)
    monkeypatch.setattr(desk.libtmux, "Server", lambda: object())

    result = app._handle_orphan_action("resume", 1)

    assert result is None
    assert cleanup_calls == [1]
    assert create_calls == [1]


def test_handle_orphan_action_forget_cleans_up_responder(monkeypatch, tmp_aque_dir):
    """Forget on a partner orphan must also clean up the paired responder."""
    from aque import desk, responder
    from aque.state import AgentInfo, AgentState

    app = desk.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)

    app.state_mgr.add_agent(AgentInfo(
        id=1, tmux_session="aque-1", label="builder", dir="/tmp",
        command=["claude"], state=AgentState.RUNNING, pid=1,
        agent_type="claude",
    ))

    cleanup_calls: list = []
    monkeypatch.setattr(responder, "cleanup",
                        lambda partner, sm, server, *, aque_dir: cleanup_calls.append(partner.id))
    monkeypatch.setattr(desk.libtmux, "Server", lambda: object())

    app._handle_orphan_action("forget", 1)

    assert cleanup_calls == [1]
    assert all(a.id != 1 for a in app.state_mgr.load().agents)


def test_handle_orphan_action_returns_error_on_failure(monkeypatch, tmp_aque_dir):
    """When relaunch_agent raises, _handle_orphan_action returns the error
    string so OrphanModal can show an inline error and keep the orphan listed."""
    from aque import desk
    from aque.state import AgentInfo, AgentState

    app = desk.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)

    app.state_mgr.add_agent(AgentInfo(
        id=1, tmux_session="aque-1", label="x", dir="/nonexistent",
        command=["claude"], state=AgentState.RUNNING, pid=1,
        agent_type="claude",
    ))

    def boom(*a, **kw):
        raise RuntimeError("dir missing")
    monkeypatch.setattr(desk, "relaunch_agent", boom)

    result = app._handle_orphan_action("relaunch", 1)
    assert result == "dir missing"
    # Agent still in state
    assert any(a.id == 1 for a in app.state_mgr.load().agents)


class TestEnsureMonitorRunning:
    def _app(self, tmp_aque_dir):
        from aque.desk import DeskApp
        return DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)

    def test_starts_when_no_pid(self, tmp_aque_dir, monkeypatch):
        import aque.desk as desk
        started = {"n": 0}
        monkeypatch.setattr(desk, "start_monitor_daemon", lambda d: started.__setitem__("n", started["n"] + 1))
        app = self._app(tmp_aque_dir)
        app._ensure_monitor_running()
        assert started["n"] == 1

    def test_no_restart_when_alive_and_fresh(self, tmp_aque_dir, monkeypatch):
        import os, aque.desk as desk
        started = {"n": 0}
        monkeypatch.setattr(desk, "start_monitor_daemon", lambda d: started.__setitem__("n", started["n"] + 1))
        monkeypatch.setattr(os, "kill", lambda pid, sig: None)  # pretend alive
        (tmp_aque_dir / "monitor.pid").write_text("4242")  # fresh mtime = now
        app = self._app(tmp_aque_dir)
        state = app.state_mgr.load(); state.monitor_pid = 4242; app.state_mgr.save(state)
        app._ensure_monitor_running()
        assert started["n"] == 0

    def test_restart_when_heartbeat_stale(self, tmp_aque_dir, monkeypatch):
        import os, signal, aque.desk as desk
        started = {"n": 0}
        killed = []
        monkeypatch.setattr(desk, "start_monitor_daemon", lambda d: started.__setitem__("n", started["n"] + 1))
        def fake_kill(pid, sig):
            if sig == 0:
                return  # alive
            killed.append((pid, sig))
        monkeypatch.setattr(os, "kill", fake_kill)
        pid_file = tmp_aque_dir / "monitor.pid"
        pid_file.write_text("4242")
        old = pid_file.stat().st_mtime
        os.utime(pid_file, (old - 3600, old - 3600))  # 1h stale
        app = self._app(tmp_aque_dir)
        state = app.state_mgr.load(); state.monitor_pid = 4242; app.state_mgr.save(state)
        app._ensure_monitor_running()
        assert started["n"] == 1
        assert (4242, signal.SIGTERM) in killed  # hung monitor was terminated first


class TestAgentSwitching:
    def _app_with_three(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        for i in (1, 2, 3):
            mgr.add_agent(AgentInfo(
                id=i, tmux_session=f"s-{i}", label=f"a{i}", dir="/tmp",
                command=["a"], state=AgentState.RUNNING, pid=100 + i,
            ))
        return DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)

    @pytest.mark.asyncio
    async def test_next_and_prev_wrap(self, tmp_aque_dir):
        app = self._app_with_three(tmp_aque_dir)
        async with app.run_test():
            ol = app.query_one("#agent-option-list", OptionList)
            ol.highlighted = 0
            app.action_next_agent()
            assert ol.highlighted == 1
            app.action_prev_agent()
            assert ol.highlighted == 0
            app.action_prev_agent()                 # wraps to last
            assert ol.highlighted == ol.option_count - 1


class TestTerminalFocus:
    @pytest.mark.asyncio
    async def test_agent_list_focusable_and_focused_on_mount(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            ol = app.query_one("#agent-option-list", OptionList)
            assert ol.can_focus is True       # focusable (Tab cycles into embed)
            assert app.focused is ol          # list is the default surface

    @pytest.mark.asyncio
    async def test_highlight_previews_without_stealing_focus(self, tmp_aque_dir, monkeypatch):
        from aque.terminal.widget import TerminalView
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            term = app.query_one("#embedded-terminal", TerminalView)
            monkeypatch.setattr(term, "attach", lambda argv, size_sync=None: None)  # no focus steal
            app._skip_attach = False
            ol = app.query_one("#agent-option-list", OptionList)
            ol.focus()
            ol.highlighted = 0
            app._attach_highlighted_terminal()
            await pilot.pause()
            assert app.focused is ol          # hover preview kept list focus

    @pytest.mark.asyncio
    async def test_enter_focuses_terminal(self, tmp_aque_dir, monkeypatch):
        from aque.terminal.widget import TerminalView
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            term = app.query_one("#embedded-terminal", TerminalView)
            monkeypatch.setattr(term, "attach", lambda argv, size_sync=None: None)
            app._skip_attach = False
            ol = app.query_one("#agent-option-list", OptionList)
            ol.focus()
            ol.highlighted = 0
            await pilot.press("enter")        # Enter pops into the embed
            await pilot.pause()
            assert app.focused is term

    @pytest.mark.asyncio
    async def test_check_action_gates_plain_letters_when_embed_focused(self, tmp_aque_dir):
        from aque.terminal.widget import TerminalView
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            term = app.query_one("#embedded-terminal", TerminalView)
            assert app.check_action("new_agent", ()) is True   # list focused
            term.focus()
            await pilot.pause()
            assert app.check_action("new_agent", ()) is False  # gated in embed
            assert app.check_action("next_agent", ()) is True  # priority never gated

class TestTriageCoexistence:
    @pytest.mark.asyncio
    async def test_triage_suppressed_while_terminal_focused(self, tmp_aque_dir):
        from aque.terminal.widget import TerminalView
        from aque.widgets.triage_modal import TriageModal
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.WAITING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        app._scan_for_orphans = lambda: None
        async with app.run_test() as pilot:
            await pilot.pause()            # let mount focus settle on the list
            term = app.query_one("#embedded-terminal", TerminalView)
            term.focus()
            await pilot.pause()
            assert app.focused is term
            app._skip_attach = False       # allow triage to surface
            app._try_show_triage()         # ...but the embed has focus
            await pilot.pause()
            # Suppressed: no modal pops and the terminal keeps focus, so a
            # notification can't steal keystrokes mid-command.
            assert not isinstance(app.screen, TriageModal)
            assert app._triage_agent is None
            assert app.focused is term


class TestAttachDoesNotChangeState:
    def test_attach_does_not_change_agent_state(self, tmp_path, monkeypatch):
        import contextlib
        import subprocess
        from aque.desk import DeskApp
        from aque.state import AgentInfo, AgentState, StateManager

        aque_dir = tmp_path / ".aque"
        aque_dir.mkdir()
        mgr = StateManager(aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="test-agent",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))

        app = DeskApp(aque_dir=aque_dir)
        agent = app.state_mgr.load().agents[0]

        calls = []
        monkeypatch.setattr(app.state_mgr, "update_agent_state",
                            lambda *a, **k: calls.append(a))
        # Stub suspend() so the body runs without a real terminal
        monkeypatch.setattr(app, "suspend", lambda: contextlib.nullcontext())
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        # Stub screen-side-effect methods that need a live Textual app
        monkeypatch.setattr(app, "_dismiss_triage_modal", lambda: None)
        monkeypatch.setattr(app, "_stop_refresh", lambda: None)
        monkeypatch.setattr(app, "_show_dashboard", lambda: None)

        app._attach_to_agent(agent)

        assert calls == []  # no state mutation during attach/detach
        assert app.state_mgr.load().agents[0].state == AgentState.RUNNING


class TestEmbedShortcuts:
    @pytest.mark.asyncio
    async def test_back_to_list_focuses_list(self, tmp_aque_dir):
        from aque.terminal.widget import TerminalView
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            term = app.query_one("#embedded-terminal", TerminalView)
            term.focus()
            await pilot.pause()
            assert app.focused is term
            app.action_back_to_list()
            await pilot.pause()
            assert app.focused is app.query_one("#agent-option-list", OptionList)

    def test_palette_lists_every_management_action(self):
        from aque.widgets.command_palette import CommandPalette
        payloads = {i.payload for i in CommandPalette([])._all_items() if i.kind == "action"}
        for needed in ("new", "quick_launch", "kill", "hold", "auto",
                       "fullscreen", "undo", "responders", "help"):
            assert needed in payloads, f"palette missing action: {needed}"

    def test_palette_dispatch_routes_management_actions(self, tmp_aque_dir, monkeypatch):
        from aque.widgets.command_palette import CommandItem
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        calls = []
        routes = {
            "kill": "action_kill_agent", "hold": "action_hold_agent",
            "auto": "action_toggle_auto_respond", "quick_launch": "action_quick_launch",
            "undo": "action_undo", "fullscreen": "action_attach_fullscreen",
        }
        for method in set(routes.values()):
            monkeypatch.setattr(app, method, (lambda m: (lambda: calls.append(m)))(method))
        for payload, method in routes.items():
            app._on_command_picked(CommandItem("x", "action", payload))
        assert sorted(calls) == sorted(routes.values())


class TestKillConfirmation:
    @pytest.mark.asyncio
    async def test_kill_requires_confirmation(self, tmp_aque_dir, monkeypatch):
        from aque.widgets.confirm_modal import ConfirmModal
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a", dir="/tmp",
            command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            killed = []
            monkeypatch.setattr(app, "_kill_agent", lambda aid: killed.append(aid))
            app.query_one("#agent-option-list", OptionList).highlighted = 0

            # Kill action only opens the prompt — nothing dies yet.
            app.action_kill_agent()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmModal)
            assert killed == []

            # Cancelling kills nothing.
            await pilot.press("escape")
            await pilot.pause()
            assert killed == []

            # Confirming kills.
            app.action_kill_agent()
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert killed == [1]


class TestPerformLaunchClaudeRouting:
    @pytest.mark.asyncio
    async def test_no_prior_sessions_skips_picker(self, tmp_aque_dir, monkeypatch):
        """When summarize() returns [], _perform_launch goes straight to launch
        with a pre-assigned session_id (no picker shown)."""
        from aque import sessions, desk as desk_mod

        monkeypatch.setattr(
            sessions.ClaudeCapturer, "summarize", lambda self, cwd: [],
        )
        launched: dict = {}

        def fake_launch(**kwargs):
            launched.update(kwargs)
            return 1

        monkeypatch.setattr(desk_mod, "launch_agent", fake_launch)

        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._perform_launch(
                command=["cc"], working_dir="/tmp/x",
                label="t", agent_type="claude",
            )
            await pilot.pause()

        assert launched["session_id"] is not None
        assert launched["agent_type"] == "claude"
        # Command was rewritten by preassign to include --session-id.
        assert "--session-id" in launched["command"]

    @pytest.mark.asyncio
    async def test_prior_sessions_shows_picker(self, tmp_aque_dir, monkeypatch):
        """When summarize() returns sessions, ResumePickerScreen is pushed."""
        from datetime import datetime, timezone
        from aque import sessions, desk as desk_mod
        from aque.sessions import SessionSummary
        from aque.widgets.resume_picker import ResumePickerScreen

        fake_summary = SessionSummary(
            uuid="aaaa", first_prompt="hi", last_activity="there",
            mtime=datetime.now(timezone.utc), size_bytes=100,
        )
        monkeypatch.setattr(
            sessions.ClaudeCapturer, "summarize", lambda self, cwd: [fake_summary],
        )

        pushed: list = []

        def fake_push_screen(screen, callback=None):
            pushed.append(screen)

        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        monkeypatch.setattr(app, "push_screen", fake_push_screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            app._perform_launch(
                command=["cc"], working_dir="/tmp/x",
                label="t", agent_type="claude",
            )
            await pilot.pause()

        assert len(pushed) == 1
        assert isinstance(pushed[0], ResumePickerScreen)

    @pytest.mark.asyncio
    async def test_non_claude_skips_picker_entirely(self, tmp_aque_dir, monkeypatch):
        """agent_type=None or 'codex' or 'aider' bypasses the picker."""
        from aque import desk as desk_mod

        launched: dict = {}

        def fake_launch(**kwargs):
            launched.update(kwargs)
            return 1

        monkeypatch.setattr(desk_mod, "launch_agent", fake_launch)

        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._perform_launch(
                command=["aider"], working_dir="/tmp/x",
                label="t", agent_type="aider",
            )
            await pilot.pause()

        assert launched.get("session_id") is None
        assert launched["agent_type"] == "aider"

    @pytest.mark.asyncio
    async def test_picker_fresh_choice_pre_assigns_session_id(self, tmp_aque_dir, monkeypatch):
        """When picker returns action='fresh', the agent still gets a
        pre-assigned session_id (--session-id in command, sid not None)."""
        from datetime import datetime, timezone
        from aque import sessions, desk as desk_mod
        from aque.sessions import SessionSummary
        from aque.widgets.resume_picker import PickerResult

        fake_summary = SessionSummary(
            uuid="aaaa", first_prompt="hi", last_activity="there",
            mtime=datetime.now(timezone.utc), size_bytes=100,
        )
        monkeypatch.setattr(
            sessions.ClaudeCapturer, "summarize", lambda self, cwd: [fake_summary],
        )

        launched: dict = {}
        def fake_launch(**kwargs):
            launched.update(kwargs)
            return 1
        monkeypatch.setattr(desk_mod, "launch_agent", fake_launch)

        # Capture the on_pick callback that _perform_launch passes to push_screen
        captured_callback: list = []
        def fake_push_screen(screen, callback=None):
            captured_callback.append(callback)
        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "push_screen", fake_push_screen)
            app._perform_launch(
                command=["cc"], working_dir="/tmp/x",
                label="t", agent_type="claude",
            )
            await pilot.pause()
            # Now simulate the user picking "Start fresh"
            assert captured_callback, "_perform_launch did not push a picker"
            captured_callback[0](PickerResult(action="fresh", session_id=None))
            await pilot.pause()

        assert launched["session_id"] is not None
        assert "--session-id" in launched["command"]

    @pytest.mark.asyncio
    async def test_picker_resume_choice_passes_session_id_through(self, tmp_aque_dir, monkeypatch):
        """When picker returns action='resume', launch_agent receives the
        picked session_id and the command is rewritten via resume_command."""
        from datetime import datetime, timezone
        from aque import sessions, desk as desk_mod
        from aque.sessions import SessionSummary
        from aque.widgets.resume_picker import PickerResult

        fake_summary = SessionSummary(
            uuid="aaaa", first_prompt="hi", last_activity="there",
            mtime=datetime.now(timezone.utc), size_bytes=100,
        )
        monkeypatch.setattr(
            sessions.ClaudeCapturer, "summarize", lambda self, cwd: [fake_summary],
        )

        launched: dict = {}
        def fake_launch(**kwargs):
            launched.update(kwargs)
            return 1
        monkeypatch.setattr(desk_mod, "launch_agent", fake_launch)

        captured_callback: list = []
        def fake_push_screen(screen, callback=None):
            captured_callback.append(callback)
        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(app, "push_screen", fake_push_screen)
            app._perform_launch(
                command=["cc"], working_dir="/tmp/x",
                label="t", agent_type="claude",
            )
            await pilot.pause()
            assert captured_callback, "_perform_launch did not push a picker"
            captured_callback[0](PickerResult(action="resume", session_id="aaaa"))
            await pilot.pause()

        assert launched["session_id"] == "aaaa"
        # Command should have been rewritten by resume_command (claude uses --resume for resuming)
        assert "--resume" in launched["command"]
        assert "aaaa" in launched["command"]


class TestQuickLaunchPickerRouting:
    @pytest.mark.asyncio
    async def test_quick_launch_claude_routes_through_picker(self, tmp_aque_dir, monkeypatch):
        """_launch_quick_task_with_type for a claude task must delegate to
        _perform_launch, which (after Task 9) pushes ResumePickerScreen when
        prior sessions exist in the target directory."""
        from datetime import datetime, timezone
        from aque import sessions, desk as desk_mod
        from aque.sessions import SessionSummary
        from aque.widgets.resume_picker import ResumePickerScreen

        fake_summary = SessionSummary(
            uuid="aaaa", first_prompt="hi", last_activity="there",
            mtime=datetime.now(timezone.utc), size_bytes=100,
        )
        monkeypatch.setattr(
            sessions.ClaudeCapturer, "summarize", lambda self, cwd: [fake_summary],
        )

        pushed: list = []

        def fake_push_screen(screen, callback=None):
            pushed.append(screen)

        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        monkeypatch.setattr(app, "push_screen", fake_push_screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            task = {
                "command": ["cc"], "dir": "/tmp/x",
                "label": "quick", "agent_type": "claude",
            }
            app._launch_quick_task_with_type(task, "claude")
            await pilot.pause()

        assert len(pushed) == 1
        assert isinstance(pushed[0], ResumePickerScreen)
        # Mode must be reset off the form so on_key doesn't try to
        # query_one(QuickLaunchForm) while the picker modal is on top.
        assert app._mode != "quick_launch_form"


class TestFormCompletionResetsMode:
    """Both NewAgentForm and QuickLaunchForm submission paths must reset
    _mode away from the form mode before _perform_launch can push a modal.
    Otherwise the next keypress crashes in on_key on a missing widget."""

    @pytest.mark.asyncio
    async def test_quick_launch_resets_mode_before_picker(self, tmp_aque_dir, monkeypatch):
        from datetime import datetime, timezone
        from aque import sessions, desk as desk_mod
        from aque.sessions import SessionSummary

        monkeypatch.setattr(
            sessions.ClaudeCapturer, "summarize",
            lambda self, cwd: [SessionSummary(
                uuid="aaaa", first_prompt="hi", last_activity="there",
                mtime=datetime.now(timezone.utc), size_bytes=100,
            )],
        )
        monkeypatch.setattr(desk_mod, "launch_agent", lambda **kw: 1)

        pushed: list = []
        app = desk_mod.DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        monkeypatch.setattr(app, "push_screen", lambda s, cb=None: pushed.append(s))

        async with app.run_test() as pilot:
            await pilot.pause()
            app._mode = "quick_launch_form"  # simulate mid-form state
            app._launch_quick_task_with_type(
                {"command": ["cc"], "dir": "/tmp/x", "label": "q", "agent_type": "claude"},
                "claude",
            )
            await pilot.pause()

        assert app._mode != "quick_launch_form"
