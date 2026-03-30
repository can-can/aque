"""DirectoryPicker widget — search, pin, and select directories."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from aque.dir_history import DirHistoryManager


def key_hint(key: str, action: str) -> str:
    """Format a key hint with escaped brackets for Rich markup."""
    return f"\\[{key}] {action}"


def _display_path(path: str) -> str:
    """Show path with ~ shorthand for home directory."""
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


class DirectoryPicker(Vertical):
    """A widget for searching and selecting directories."""

    class DirectorySelected(Message):
        def __init__(self, path: str) -> None:
            super().__init__()
            self.path = path

    DEFAULT_CSS = """
    DirectoryPicker {
        height: 100%;
        padding: 1 2;
    }
    #dir-search-input {
        margin-bottom: 1;
    }
    #dir-list {
        height: 1fr;
    }
    #dir-picker-hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        dir_history_mgr: DirHistoryManager,
        default_dir: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._history_mgr = dir_history_mgr
        self._default_dir = default_dir
        self._tree_mode = False
        self._current_results: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search directories...", id="dir-search-input")
        yield OptionList(id="dir-list")
        yield Static(
            "  ".join([
                key_hint("Enter", "select"),
                key_hint("p", "pin/unpin"),
                key_hint("b", "browse tree"),
                key_hint("Esc", "cancel"),
            ]),
            id="dir-picker-hint",
        )

    def on_mount(self) -> None:
        self._refresh_list("")
        self.query_one("#dir-search-input").focus()

    def _refresh_list(self, query: str) -> None:
        """Rebuild the option list from history/search results."""
        option_list = self.query_one("#dir-list", OptionList)
        option_list.clear_options()

        if query:
            results = self._history_mgr.search(query, self._default_dir)
        else:
            results = self._history_mgr.get_ranked_dirs()

        self._current_results = results

        pinned = [r for r in results if r.get("pinned")]
        unpinned = [r for r in results if not r.get("pinned")]

        for entry in pinned:
            display = f"* {_display_path(entry['path'])}"
            option_list.add_option(Option(display, id=entry["path"]))

        if pinned and unpinned:
            option_list.add_option(Option("\u2500\u2500 recent \u2500\u2500", id="__separator__"))

        for entry in unpinned:
            display = f"  {_display_path(entry['path'])}"
            count = entry.get("count", 0)
            if count > 0:
                display += f"  ({count}x)"
            option_list.add_option(Option(display, id=entry["path"]))

        # Ensure first option is highlighted after repopulating
        if option_list.option_count > 0:
            option_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "dir-search-input":
            self._refresh_list(event.value)

    def get_selected_path(self) -> str | None:
        """Return the path of the highlighted option, or None."""
        option_list = self.query_one("#dir-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        option = option_list.get_option_at_index(highlighted)
        if option.id == "__separator__":
            return None
        return str(option.id)

    def select_current(self) -> None:
        """Post a DirectorySelected message for the highlighted option."""
        path = self.get_selected_path()
        if path is not None:
            self.post_message(self.DirectorySelected(path))

    def toggle_pin(self) -> None:
        """Toggle the pinned state of the highlighted directory."""
        path = self.get_selected_path()
        if path is None:
            return
        pinned = self._history_mgr.get_pinned()
        if path in pinned:
            self._history_mgr.unpin(path)
        else:
            self._history_mgr.pin(path)
        # Re-render with current search query
        search_input = self.query_one("#dir-search-input", Input)
        self._refresh_list(search_input.value)

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id != "__separator__":
            self.post_message(self.DirectorySelected(str(event.option.id)))

    def on_key(self, event) -> None:
        # Only handle shortcuts when the option list is focused (not the search input)
        focused = self.app.focused
        if focused is not None and focused.id == "dir-list" and event.character == "p":
            self.toggle_pin()
            event.prevent_default()
            event.stop()
