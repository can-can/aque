"""Tests for the DirectoryPicker widget."""

import pytest

from textual.app import App, ComposeResult

from aque.dir_history import DirHistoryManager
from aque.widgets.dir_picker import DirectoryPicker


class PickerTestApp(App):
    def __init__(self, dir_history_mgr: DirHistoryManager, default_dir: str):
        super().__init__()
        self.dir_history_mgr = dir_history_mgr
        self.default_dir = default_dir
        self.selected_dir = None

    def compose(self) -> ComposeResult:
        yield DirectoryPicker(
            dir_history_mgr=self.dir_history_mgr,
            default_dir=self.default_dir,
            id="dir-picker",
        )

    def on_directory_picker_directory_selected(self, event) -> None:
        self.selected_dir = event.path


class TestDirectoryPickerRender:
    @pytest.mark.asyncio
    async def test_picker_shows_search_input(self, tmp_aque_dir, tmp_path):
        mgr = DirHistoryManager(tmp_aque_dir)
        app = PickerTestApp(dir_history_mgr=mgr, default_dir=str(tmp_path))
        async with app.run_test() as pilot:
            search_input = app.query_one("#dir-search-input")
            assert search_input is not None

    @pytest.mark.asyncio
    async def test_picker_shows_pinned_dirs(self, tmp_aque_dir, tmp_path):
        d = tmp_path / "pinned_project"
        d.mkdir()
        mgr = DirHistoryManager(tmp_aque_dir)
        mgr.pin(str(d))
        app = PickerTestApp(dir_history_mgr=mgr, default_dir=str(tmp_path))
        async with app.run_test() as pilot:
            option_list = app.query_one("#dir-list")
            assert option_list.option_count >= 1

    @pytest.mark.asyncio
    async def test_picker_shows_recent_dirs(self, tmp_aque_dir, tmp_path):
        d = tmp_path / "recent_project"
        d.mkdir()
        mgr = DirHistoryManager(tmp_aque_dir)
        mgr.record_use(str(d))
        app = PickerTestApp(dir_history_mgr=mgr, default_dir=str(tmp_path))
        async with app.run_test() as pilot:
            option_list = app.query_one("#dir-list")
            assert option_list.option_count >= 1


class TestDirectoryPickerInteraction:
    @pytest.mark.asyncio
    async def test_select_emits_message(self, tmp_aque_dir, tmp_path):
        d = tmp_path / "select_project"
        d.mkdir()
        mgr = DirHistoryManager(tmp_aque_dir)
        mgr.record_use(str(d))
        app = PickerTestApp(dir_history_mgr=mgr, default_dir=str(tmp_path))
        async with app.run_test() as pilot:
            # Focus the option list and select first item
            option_list = app.query_one("#dir-list")
            option_list.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.selected_dir == str(d.resolve())

    @pytest.mark.asyncio
    async def test_search_filters_list(self, tmp_aque_dir, tmp_path):
        d1 = tmp_path / "alpha_project"
        d1.mkdir()
        d2 = tmp_path / "beta_project"
        d2.mkdir()
        mgr = DirHistoryManager(tmp_aque_dir)
        mgr.record_use(str(d1))
        mgr.record_use(str(d2))
        app = PickerTestApp(dir_history_mgr=mgr, default_dir=str(tmp_path))
        async with app.run_test() as pilot:
            search_input = app.query_one("#dir-search-input")
            search_input.focus()
            await pilot.pause()
            # Type a search query that matches only alpha
            await pilot.press("a", "l", "p", "h", "a")
            await pilot.pause()
            option_list = app.query_one("#dir-list")
            # Should have filtered to only alpha_project
            assert option_list.option_count >= 1
            # Check that all visible options contain "alpha"
            for i in range(option_list.option_count):
                opt = option_list.get_option_at_index(i)
                assert "alpha" in opt.id.lower() or opt.id == "__separator__"

    @pytest.mark.asyncio
    async def test_pin_toggle(self, tmp_aque_dir, tmp_path):
        d = tmp_path / "pin_project"
        d.mkdir()
        mgr = DirHistoryManager(tmp_aque_dir)
        mgr.record_use(str(d))
        app = PickerTestApp(dir_history_mgr=mgr, default_dir=str(tmp_path))
        async with app.run_test() as pilot:
            option_list = app.query_one("#dir-list")
            option_list.focus()
            await pilot.pause()
            # Press "p" to toggle pin
            await pilot.press("p")
            await pilot.pause()
            # Verify the dir is now pinned
            assert str(d.resolve()) in mgr.get_pinned()
