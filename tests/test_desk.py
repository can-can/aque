from unittest.mock import patch
from click.exceptions import Exit
import pytest

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
