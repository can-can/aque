import shlex
import subprocess
import sys
import time
from pathlib import Path

import libtmux
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import (
    DirectoryTree,
    Header,
    Input,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option
from rich.text import Text


class FolderTree(DirectoryTree):
    """DirectoryTree that only shows non-hidden directories."""

    def filter_paths(self, paths):
        return [
            p for p in paths
            if p.is_dir() and not p.name.startswith(".")
        ]

from aque import responder
from aque.config import load_config
from aque.debug import dbg
from aque.desk_tokens import STATE_COLORS, auto_chip_markup, type_chip_markup
from aque.dir_history import DirHistoryManager
from aque.history import HistoryManager
from aque.monitor import capture_pane_content, start_monitor_daemon, stop_monitor
from aque.orphans import find_orphans
from aque.run import launch_agent, relaunch_agent
from aque.sessions import CAPTURERS
from aque.state import AgentInfo, AppState, AgentState, StateManager
from aque.widgets.command_palette import CommandItem, CommandPalette
from aque.widgets.confirm_modal import ConfirmModal
from aque.widgets.dir_picker import DirectoryPicker, key_hint
from aque.widgets.help_modal import HelpModal
from aque.widgets.orphan_modal import OrphanModal
from aque.widgets.resume_picker import PickerResult, ResumePickerScreen
from aque.widgets.triage_modal import ATTACH, PEEK, SNOOZE, TriageModal
from aque.widgets.undo_bar import UndoBar
from aque.terminal.widget import TerminalView

STATE_PRIORITY = {
    AgentState.WAITING: 0,
    AgentState.EXITED: 1,
    AgentState.RUNNING: 2,
    AgentState.ON_HOLD: 3,
    AgentState.DONE: 4,
}

# How long the row state-change cue (the leading ``▴``) stays visible after
# we detect a transition. Three seconds is roughly one-and-a-half periodic
# refreshes, so the marker is reliably caught by a glancing user.
CHANGE_CUE_SECS = 3.0

NARROW_BREAKPOINT = 80  # columns; below this, auto layout stacks and labels compact


def _dir_sort_key(dir_path: str) -> tuple[str, str]:
    """Folder key for the dashboard list: the directory's last two path
    components, e.g. ``/Users/cancan/Projects/aque`` → ``("Projects", "aque")``.
    Shorter paths are left-padded with ``""`` so every key is a 2-tuple."""
    last_two = Path(dir_path).parts[-2:]
    return ("",) * (2 - len(last_two)) + last_two


def sorted_agents(agents: list[AgentInfo]) -> list[AgentInfo]:
    """Order the dashboard list by folder, then by name.

    Agents in the same project (same last-two-path-components folder) sit
    together; ties within a folder break on the agent's label. State no longer
    influences ordering — the list is a stable, navigable index rather than a
    priority queue (urgency surfaces via the triage banner instead)."""
    return sorted(agents, key=lambda a: (_dir_sort_key(a.dir), a.label))


# ── Widgets ──────────────────────────────────────────────────────────


class StatusBar(Static):
    def __init__(self) -> None:
        super().__init__("[dim]No agents[/dim]", id="status-bar")


class ActionMenu(Vertical):
    def __init__(self, agent: AgentInfo, waiting_count: int, config: dict, was_exited: bool) -> None:
        super().__init__(id="action-menu")
        self.agent = agent
        self.waiting_count = waiting_count
        self.config = config
        self.was_exited = was_exited

    def compose(self) -> ComposeResult:
        keys = self.config["action_keys"]
        if self.was_exited:
            yield Static(f"Reviewing: {self.agent.label} (exited)", id="action-label")
            yield Static(f"{self.waiting_count} more waiting\n")
            yield OptionList(
                Option(f"{key_hint(keys['done'], 'done')} — move to history", id="done"),
                Option(f"{key_hint(keys['hold'], 'hold')} — keep for later", id="hold"),
                id="action-option-list",
            )
        else:
            yield Static(f"Back from: {self.agent.label}", id="action-label")
            yield Static(f"{self.waiting_count} more waiting\n")
            yield OptionList(
                Option(f"{key_hint(keys['dismiss'], 'dismiss')} — send back to work, review later", id="dismiss"),
                Option(f"{key_hint(keys['done'], 'done')} — task finished, move to history", id="done"),
                Option(f"{key_hint(keys['skip'], 'skip')} — next waiting agent", id="skip"),
                Option(f"{key_hint(keys['hold'], 'hold')} — pause, come back later", id="hold"),
                id="action-option-list",
            )
        yield Static(f"{key_hint('Enter', 'select')}   or press shortcut key", id="action-hint")


class NewAgentForm(Vertical):
    def __init__(self, dir_history_mgr: DirHistoryManager, default_dir: str, plugin_names: list[str] | None = None) -> None:
        super().__init__(id="new-agent-form")
        self._step = "type"
        self._selected_type: str | None = None
        self._selected_dir: str = ""
        self._command: str = ""
        self._label: str = ""
        self._dir_history_mgr = dir_history_mgr
        self._default_dir = default_dir
        self._tree_mode = False
        self._plugin_names = plugin_names or []

    def compose(self) -> ComposeResult:
        yield Static("New Agent", id="new-agent-title")
        yield Static("Step 1/4: Select agent type", id="new-agent-step")
        type_options = [Option("none (polling only)", id="none")]
        for name in self._plugin_names:
            type_options.append(Option(name, id=name))
        yield OptionList(*type_options, id="type-list")
        yield Static(
            "   ".join([key_hint("Enter", "select"), key_hint("Esc", "cancel")]),
            id="new-agent-hint",
        )

    def on_mount(self) -> None:
        # Focus the type list on open so the user can arrow + Enter without
        # first having to Tab into the list. Deferred via call_after_refresh
        # so we win against Textual's initial auto-focus pass.
        def _focus():
            try:
                self.query_one("#type-list", OptionList).focus()
            except Exception:
                pass
        self.call_after_refresh(_focus)

    def select_type(self) -> None:
        """Handle type selection and advance to dir step."""
        try:
            type_list = self.query_one("#type-list", OptionList)
        except Exception:
            return
        if type_list.highlighted is None:
            return
        option = type_list.get_option_at_index(type_list.highlighted)
        self._selected_type = None if option.id == "none" else option.id
        type_list.remove()
        self._show_dir_from_type()

    def _show_dir_from_type(self) -> None:
        """Advance from type to directory step."""
        self._step = "dir"
        type_label = self._selected_type or "none"
        self.query_one("#new-agent-step").update(
            f"Step 2/4: Select working directory  (type: {type_label})"
        )
        self.mount(
            DirectoryPicker(
                dir_history_mgr=self._dir_history_mgr,
                default_dir=self._default_dir,
                id="dir-picker",
            ),
            after=self.query_one("#new-agent-step"),
        )
        self.query_one("#new-agent-hint").update(
            "   ".join([key_hint("Enter", "select"), key_hint("b", "browse"), key_hint("Esc", "back")])
        )

    def show_type_step(self) -> None:
        """Go back to the type selection step."""
        self._step = "type"
        self.query_one("#new-agent-step").update("Step 1/4: Select agent type")
        try:
            self.query_one("#dir-picker").remove()
        except Exception:
            pass
        type_options = [Option("none (polling only)", id="none")]
        for name in self._plugin_names:
            type_options.append(Option(name, id=name))
        self.mount(
            OptionList(*type_options, id="type-list"),
            after=self.query_one("#new-agent-step"),
        )
        self.query_one("#new-agent-hint").update(
            "   ".join([key_hint("Enter", "select"), key_hint("Esc", "cancel")])
        )
        self.query_one("#type-list", OptionList).focus()
        self.query_one("#type-list", OptionList).focus()

    def show_command_step(self) -> None:
        self._step = "command"
        self.query_one("#new-agent-step").update(
            f"Step 3/4: Enter command  (dir: {self._selected_dir})"
        )
        # Remove dir picker or label input depending on direction
        for selector in ("#dir-picker", "#label-input"):
            try:
                self.query_one(selector).remove()
            except Exception:
                pass
        self.mount(
            Input(value=self._command, placeholder="e.g. claude --model opus", id="command-input"),
            after=self.query_one("#new-agent-step"),
        )
        hint_text = "   ".join([key_hint("Enter", "next"), key_hint("Esc", "back")])
        try:
            self.query_one("#new-agent-hint").update(hint_text)
        except Exception:
            self.mount(
                Static(hint_text, id="new-agent-hint"),
                after=self.query_one("#command-input"),
            )
        self.query_one("#command-input").focus()

    def show_label_step(self) -> None:
        self._step = "label"
        self._label = ""
        self.query_one("#new-agent-step").update(
            f"Step 4/4: Label  (dir: {self._selected_dir}, cmd: {self._command})"
        )
        self.query_one("#command-input").remove()
        self.mount(
            Input(
                value="",
                placeholder="Agent label (optional)",
                id="label-input",
            ),
            after=self.query_one("#new-agent-step"),
        )
        self.query_one("#new-agent-hint").update(
            "   ".join([key_hint("Enter", "launch"), key_hint("Esc", "back")])
        )
        self.query_one("#label-input").focus()

    def show_dir_step(self) -> None:
        """Go back to directory selection step."""
        self._step = "dir"
        type_label = self._selected_type or "none"
        self.query_one("#new-agent-step").update(
            f"Step 2/4: Select working directory  (type: {type_label})"
        )
        try:
            self.query_one("#command-input").remove()
        except Exception:
            pass
        self.mount(
            DirectoryPicker(
                dir_history_mgr=self._dir_history_mgr,
                default_dir=self._default_dir,
                id="dir-picker",
            ),
            after=self.query_one("#new-agent-step"),
        )
        # Update the existing hint in place — ``Widget.remove`` is async,
        # so removing-and-remounting races the new mount and trips a
        # DuplicateIds error.
        hint_text = "   ".join([
            key_hint("Enter", "select"),
            key_hint("b", "browse"),
            key_hint("Esc", "back"),
        ])
        try:
            self.query_one("#new-agent-hint").update(hint_text)
        except Exception:
            self.mount(
                Static(hint_text, id="new-agent-hint"),
                after=self.query_one("#dir-picker"),
            )

    def show_tree_fallback(self) -> None:
        """Switch to tree browse mode."""
        self._tree_mode = True
        self.query_one("#dir-picker").display = False
        self.mount(
            FolderTree(self._default_dir, id="dir-tree"),
            after=self.query_one("#new-agent-step"),
        )
        self.mount(
            Static(f"[bold]Selected:[/bold] {self._default_dir}", id="dir-display"),
            before=self.query_one("#dir-tree"),
        )
        tree_hint = "   ".join([
            key_hint("Enter", "expand/collapse"),
            key_hint("s", "select"),
            key_hint("Esc", "back to picker"),
        ])
        self.mount(
            Static(tree_hint, id="tree-hint"),
            after=self.query_one("#dir-tree"),
        )
        self.query_one("#dir-tree").focus()

    def hide_tree_fallback(self) -> None:
        """Return from tree browse to picker."""
        self._tree_mode = False
        try:
            self.query_one("#dir-tree").remove()
        except Exception:
            pass
        try:
            self.query_one("#dir-display").remove()
        except Exception:
            pass
        try:
            self.query_one("#tree-hint").remove()
        except Exception:
            pass
        self.query_one("#dir-picker").display = True
        self.query_one("#dir-search-input").focus()

    def update_dir_display(self, path: str) -> None:
        self._selected_dir = path
        try:
            self.query_one("#dir-display").update(f"[bold]Selected:[/bold] {path}")
        except Exception:
            pass


class QuickLaunchForm(Vertical):
    """Relaunch a recent task. Lists `recent_tasks()`; selecting one launches.

    When a task's type is unknown (legacy entry with no inferrable type), the
    form shows a one-step type picker before launching.
    """

    def __init__(self, tasks: list[dict], plugin_names: list[str] | None = None) -> None:
        super().__init__(id="quick-launch-form")
        self._tasks = tasks
        self._plugin_names = plugin_names or []
        self._step = "tasks"  # "tasks" | "type"
        self._pending_task: dict | None = None

    def _task_options(self) -> list:
        opts = []
        for i, t in enumerate(self._tasks):
            label = t["label"] or " ".join(t["command"])
            chip = type_chip_markup(t["agent_type"])
            opts.append(Option(f"{label}   [dim]{t['dir']}[/dim] {chip}", id=str(i)))
        return opts

    def compose(self) -> ComposeResult:
        yield Static("Quick Launch", id="quick-launch-title")
        if not self._tasks:
            yield Static("[dim]No recent tasks yet[/dim]", id="quick-launch-empty")
            yield Static(key_hint("Esc", "back"), id="quick-launch-hint")
            return
        yield OptionList(*self._task_options(), id="quick-launch-list")
        yield Static(
            "   ".join([key_hint("Enter", "launch"), key_hint("Esc", "back")]),
            id="quick-launch-hint",
        )

    def on_mount(self) -> None:
        try:
            self.query_one("#quick-launch-list", OptionList).focus()
        except Exception:
            pass

    def selected_task(self) -> dict | None:
        try:
            ol = self.query_one("#quick-launch-list", OptionList)
        except Exception:
            return None
        if ol.highlighted is None:
            return None
        idx = int(ol.get_option_at_index(ol.highlighted).id)
        return self._tasks[idx]

    def show_type_step(self, task: dict) -> None:
        """Prompt for an agent type for a task whose type is unknown."""
        self._step = "type"
        self._pending_task = task
        try:
            self.query_one("#quick-launch-list").remove()
        except Exception:
            pass
        type_options = [Option("none (polling only)", id="none")]
        for name in self._plugin_names:
            type_options.append(Option(name, id=name))
        self.mount(
            OptionList(*type_options, id="quick-launch-type-list"),
            after=self.query_one("#quick-launch-title"),
        )
        self.query_one("#quick-launch-hint").update(
            "   ".join([key_hint("Enter", "launch"), key_hint("Esc", "back")])
        )
        self.query_one("#quick-launch-type-list", OptionList).focus()

    def show_tasks_step(self) -> None:
        """Restore the recent-task list (used when stepping back from type)."""
        self._step = "tasks"
        self._pending_task = None
        try:
            self.query_one("#quick-launch-type-list").remove()
        except Exception:
            pass
        self.mount(
            OptionList(*self._task_options(), id="quick-launch-list"),
            after=self.query_one("#quick-launch-title"),
        )
        self.query_one("#quick-launch-list", OptionList).focus()

    def selected_type(self) -> str | None:
        try:
            ol = self.query_one("#quick-launch-type-list", OptionList)
        except Exception:
            return None
        if ol.highlighted is None:
            return None
        option = ol.get_option_at_index(ol.highlighted)
        return None if option.id == "none" else option.id


# ── Main App ─────────────────────────────────────────────────────────


class DeskApp(App):
    TITLE = "aque desk"
    # The agent list is the default surface on mount (not the embedded
    # terminal, which is also focusable for Tab). Without this, Textual's
    # auto-focus lands on the embed and gates the plain-letter shortcuts.
    AUTO_FOCUS = "#agent-option-list"
    CSS = """
    #status-bar {
        dock: top;
        padding: 0 2;
        height: 1;
        background: $surface;
    }
    #key-hint-footer {
        dock: bottom;
        padding: 0 2;
        height: 1;
        background: $surface;
        color: $text-muted;
    }
    #dashboard {
        height: 1fr;
    }
    #agent-panel {
        width: 40%;
        border-right: solid $surface-lighten-1;
    }
    /* Stacked (narrow/forced): #dashboard flips to vertical; list takes the
       height it needs up to a 30% cap, terminal fills the rest. */
    #dashboard.stacked {
        layout: vertical;
    }
    #dashboard.stacked #agent-panel {
        width: 100%;
        height: auto;
        max-height: 30%;
        border-right: none;
        border-bottom: solid $surface-lighten-1;
    }
    #dashboard.stacked #agent-option-list {
        height: auto;
        max-height: 100%;
    }
    #dashboard.stacked #preview-panel {
        width: 100%;
        height: 1fr;
    }
    #preview-panel {
        width: 60%;
    }
    #agent-option-list {
        height: 100%;
    }
    #action-menu {
        align: center middle;
        height: 100%;
        padding: 2 4;
    }
    #action-label {
        text-style: bold;
    }
    #action-option-list {
        height: auto;
        max-height: 50%;
        margin-top: 1;
    }
    #action-hint {
        color: $text-muted;
        margin-top: 1;
    }
    #new-agent-form {
        padding: 2 4;
    }
    #new-agent-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #new-agent-step {
        color: $text-muted;
        margin-bottom: 1;
    }
    #dir-picker {
        height: 55%;
    }
    #command-input, #label-input {
        margin-top: 1;
    }
    #new-agent-hint {
        color: $text-muted;
        margin-top: 1;
    }
    #tree-hint {
        color: $text-muted;
        margin-top: 1;
    }
    #action-menu.narrow {
        padding: 1 1;
    }
    #new-agent-form.narrow {
        padding: 1 1;
    }
    #quick-launch-form {
        padding: 2 4;
    }
    #quick-launch-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #quick-launch-hint {
        color: $text-muted;
        margin-top: 1;
    }
    #quick-launch-form.narrow {
        padding: 1 1;
    }
    """

    BINDINGS = [
        ("n", "new_agent", "New"),
        ("k", "kill_agent", "Kill"),
        ("h", "hold_agent", "Hold"),
        ("a", "toggle_auto_respond", "Auto"),
        ("ctrl+k", "command_palette", "⌘K"),
        ("question_mark", "show_help", "?"),
        Binding("R", "toggle_responders", "Responders", show=False),
        Binding("r", "quick_launch", "Relaunch", show=False),
        Binding("1", "filter_state('running')", "Filter running", show=False),
        Binding("2", "filter_state('waiting')", "Filter waiting", show=False),
        Binding("3", "filter_state('on_hold')", "Filter on_hold", show=False),
        Binding("4", "filter_state('exited')", "Filter exited", show=False),
        Binding("slash", "focus_search", "Search", show=False),
        Binding("u", "undo", "Undo", show=False),
    ]

    def __init__(
        self,
        aque_dir: Path | None = None,
        _skip_attach: bool = False,
    ) -> None:
        super().__init__()
        self.aque_dir = Path(aque_dir or Path.home() / ".aque")
        self.state_mgr = StateManager(self.aque_dir)
        self.history_mgr = HistoryManager(self.aque_dir)
        self.config = load_config(self.aque_dir)
        self.dir_history_mgr = DirHistoryManager(self.aque_dir)
        self._skip_attach = _skip_attach
        self._mode = "dashboard"
        self._action_agent: AgentInfo | None = None
        self._action_was_exited: bool = False
        self._refresh_timer: Timer | None = None
        self._tmux_server: libtmux.Server | None = None
        self._post_detach_debounce_until: float = 0.0
        self._preview_debounce_timer: Timer | None = None
        # (session, cols, rows) the embed last pinned the tmux window to, so we
        # skip redundant resize-window calls during rapid resizes.
        self._embed_pinned: tuple[str, int, int] | None = None
        self._last_agent_fingerprint: list | None = None
        self._narrow: bool = False  # Cached narrow state, updated by _apply_layout
        # Arrangement override, independent of _narrow (width). Session-only:
        # not persisted, resets to "auto" each launch. "auto" | "wide" | "stacked".
        self._layout_mode: str = "auto"
        self.show_responders: bool = False
        # Filter / search: in-memory only. Filter is one of the AgentStates
        # (or None); search is a substring matched against name, dir, type,
        # and state. Both apply on top of the existing visible_agents rules.
        self._filter: AgentState | None = None
        self._search: str = ""
        # Agents the user has explicitly snoozed in this session — they
        # won't re-trigger the triage pill until their state changes again.
        self._snoozed: set[int] = set()
        # Remembered last_change_at per snoozed agent — when this changes,
        # the agent has re-entered waiting from a different code path and
        # should re-trigger the pill.
        self._snoozed_last_change: dict[int, str] = {}
        # Currently-surfaced waiting agent, if any. The triage modal is up
        # while this is non-None and the dashboard is foregrounded.
        self._triage_agent: AgentInfo | None = None
        # The pushed TriageModal screen while it's up (None otherwise). Guards
        # against pushing a second triage modal on top of the first.
        self._triage_modal: TriageModal | None = None
        # Undo: one-slot stack. ``_undo_entry`` is a (message, restore_fn)
        # tuple; ``_undo_timer`` is the auto-dismiss handle. Both clear on
        # pop, expiry, or a fresh destructive action overwriting them.
        self._undo_entry: tuple[str, callable] | None = None
        self._undo_timer: Timer | None = None
        # Row state-change cue: ``_prev_row_state`` remembers each agent's
        # last-rendered state; ``_change_at`` records when we noticed a
        # transition. Rows changed within the last ``CHANGE_CUE_SECS``
        # seconds carry a leading ``▴`` so the eye catches the reorder.
        self._prev_row_state: dict[int, AgentState] = {}
        self._change_at: dict[int, float] = {}

    def _get_tmux_server(self) -> libtmux.Server:
        if self._tmux_server is None:
            self._tmux_server = libtmux.Server()
        return self._tmux_server

    @property
    def _is_narrow(self) -> bool:
        return self._narrow

    def _effective_layout(self, width: int) -> str:
        """Return the arrangement to apply: "wide" or "stacked".

        Forced modes ignore width; "auto" stacks below the 80-col breakpoint.
        This is the single seam that decides arrangement; _narrow stays width-
        based and only governs text compaction.
        """
        if self._layout_mode == "wide":
            return "wide"
        if self._layout_mode == "stacked":
            return "stacked"
        return "stacked" if width < NARROW_BREAKPOINT else "wide"

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._make_status_bar()
        # The triage notification is a centered TriageModal (a separate
        # ModalScreen pushed on demand), not an in-flow widget — so surfacing it
        # never reflows the dashboard's 1fr region.
        yield self._make_dashboard()
        yield Static(id="key-hint-footer")

    def _make_status_bar(self) -> StatusBar:
        return StatusBar()

    def _refresh_footer(self) -> None:
        """Render the curated key-hint footer from the design.

        Wide carries ``key + label`` pairs; narrow keeps only the key glyphs
        (the design hides the labels below the narrow breakpoint). The version
        descriptor hugs the right edge, padded the same way as the status-bar
        brand.
        """
        try:
            footer = self.query_one("#key-hint-footer", Static)
        except Exception:
            return
        from aque import __version__

        hints = [
            ("n", "new"),
            ("r", "relaunch"),
            ("↵", "attach"),
            ("Space", "peek"),
            ("/", "filter"),
            ("⌘K", "command"),
            ("?", "help"),
        ]
        if self._is_narrow:
            footer.update("  ".join(f"[b]{k}[/b]" for k, _ in hints))
            return
        left = "   ".join(f"[b]{k}[/b] [dim]{lbl}[/dim]" for k, lbl in hints)
        tag = f"[dim]v{__version__} · improved interactions[/dim]"
        try:
            avail = max(self.size.width - 4, 0)
            gap = max(2, avail - Text.from_markup(left).cell_len - Text.from_markup(tag).cell_len)
        except Exception:
            gap = 4
        footer.update(f"{left}{' ' * gap}{tag}")

    def _make_dashboard(self) -> Horizontal:
        dashboard = Horizontal(id="dashboard")
        agent_panel = Vertical(id="agent-panel")
        preview_panel = Vertical(id="preview-panel")

        # The list is focusable: it is the default dashboard surface, and Tab
        # cycles focus from it into the embedded terminal.
        agent_panel._add_child(OptionList(id="agent-option-list"))

        preview_panel._add_child(TerminalView(id="embedded-terminal"))
        dashboard._add_child(agent_panel)
        dashboard._add_child(preview_panel)
        return dashboard

    def _apply_layout(self, width: int | None = None) -> None:
        """Apply the effective arrangement (wide two-column or stacked
        single-column (agent list over the terminal; the notification banner,
        when present, sits above)).

        ``_narrow`` (width < NARROW_BREAKPOINT) governs text compaction and is
        computed here; the arrangement comes from ``_effective_layout`` so a
        forced layout can differ from what the width implies. The embedded
        terminal is shown in both arrangements now — stacked puts it at the
        bottom rather than hiding and detaching it.
        """
        w = width if width is not None else self.size.width
        self._narrow = w < NARROW_BREAKPOINT
        stacked = self._effective_layout(w) == "stacked"
        try:
            self.query_one("#dashboard").set_class(stacked, "stacked")
            self.query_one("#preview-panel").display = True
        except Exception:
            pass
        # No unpin-on-narrow: the embed is shown in stacked too, so it pins the
        # tmux window to its (bottom-region) size via the normal attach path.
        for selector in ("#action-menu", "#new-agent-form", "#quick-launch-form"):
            try:
                self.query_one(selector).set_class(self._narrow, "narrow")
            except Exception:
                pass

    def on_resize(self, event) -> None:
        self._apply_layout(width=event.size.width)
        self._refresh_footer()
        if self._mode == "dashboard":
            self._last_agent_fingerprint = None  # Force label rebuild
            self._refresh_agent_list()
            self._refresh_status_bar()

    def on_mount(self) -> None:
        self._apply_layout()
        self._refresh_agent_list(reset_highlight=True)
        self._refresh_status_bar()
        self._refresh_footer()
        self._start_refresh()
        self._scan_for_orphans()
        # After layout: preview the highlighted agent in the embed (no focus
        # steal), then focus the list. Focusing after the refresh cycle ensures
        # the list wins over Textual's initial auto-focus (which would otherwise
        # land on the embed and gate the plain-letter shortcuts).
        self.call_after_refresh(self._attach_highlighted_terminal)
        self.call_after_refresh(self._focus_dashboard)
        # Only the priority chords are bound here — they must work even while
        # the embedded terminal is focused. The plain-letter desk actions
        # (n/k/h/a/r/1-4/// etc.) live in BINDINGS and are gated by check_action
        # when the embed has focus, so they reach the agent instead.
        sc = self.config["shortcuts"]
        self.bind(sc["quit"], "quit_app", description="Quit")
        self.bind(sc["attach_fullscreen"], "attach_fullscreen", description="Full-screen")
        self.bind(sc["next_agent"], "next_agent", description="Next agent")
        self.bind(sc["prev_agent"], "prev_agent", description="Prev agent")
        self.bind(sc["back_to_list"], "back_to_list", description="List")
        self.bind(sc["cycle_layout"], "cycle_layout", description="Layout")

    def _start_refresh(self) -> None:
        if self._refresh_timer is None:
            self._refresh_timer = self.set_interval(2.0, self._on_refresh)

    def _stop_refresh(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    # Plain-letter desk actions that must reach the agent (not fire) while the
    # embedded terminal is focused. Priority Ctrl+Shift chords and the command
    # palette are never gated.
    _EMBED_GATED_ACTIONS = frozenset({
        "new_agent", "kill_agent", "hold_agent", "toggle_auto_respond",
        "quick_launch", "toggle_responders", "filter_state", "focus_search",
        "undo", "show_help",
    })

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        """Disable plain-letter desk shortcuts while the embed has focus so the
        keystrokes are typed into the agent instead of triggering desk actions."""
        if action in self._EMBED_GATED_ACTIONS:
            try:
                term = self.query_one("#embedded-terminal", TerminalView)
            except Exception:
                return True
            if self.focused is term:
                return False
        return True

    def on_descendant_blur(self, event) -> None:
        """When focus leaves the embedded terminal, a triage notification that
        was deferred (suppressed while the embed had focus) can surface now,
        without waiting for the next 2s poll. ``_try_show_triage`` itself
        verifies the list now holds focus before surfacing, so a blur into
        the search box (or any other non-list focus) still leaves the queue
        quiet."""
        try:
            term = self.query_one("#embedded-terminal", TerminalView)
        except Exception:
            return
        if event.widget is term and self._mode == "dashboard":
            self.call_after_refresh(self._try_show_triage)

    def _focus_dashboard(self) -> None:
        """Give keyboard focus to the agent list (the default dashboard surface).

        Highlighting an agent hover-attaches it in the embed (list keeps focus);
        Enter or Tab moves focus into the embed to type. Ensures a default
        highlight so there is an agent to preview.
        """
        try:
            ol = self.query_one("#agent-option-list", OptionList)
            if ol.option_count > 0 and ol.highlighted is None:
                ol.highlighted = 0
            ol.focus()
        except Exception:
            pass

    def _scan_for_orphans(self) -> None:
        if self._skip_attach:
            return
        state = self.state_mgr.load()
        server = libtmux.Server()
        orphans = find_orphans(state, server)
        if not orphans:
            return
        self.push_screen(OrphanModal(orphans, on_action=self._handle_orphan_action))

    def _handle_orphan_action(self, action: str, agent_id: int) -> "str | None":
        """Apply an orphan action. Returns None on success, error message on failure.

        Resume/Relaunch also rebuild the partner's responder (the old one died
        with the same tmux server that took the partner). Forget cleans up the
        paired responder so it doesn't sit in state.json with a dangling
        partner_id.
        """
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            return "Agent not found"
        try:
            if action == "resume" and agent.session_id and agent.agent_type in CAPTURERS:
                capturer = CAPTURERS[agent.agent_type]
                cmd = capturer.resume_command(agent.command, agent.session_id)
                relaunch_agent(
                    agent_id=agent_id, command=cmd,
                    state_manager=self.state_mgr, preserve_session_id=True,
                )
                self._rebuild_responder(agent_id)
            elif action == "relaunch":
                relaunch_agent(
                    agent_id=agent_id, command=agent.command,
                    state_manager=self.state_mgr, preserve_session_id=False,
                )
                self._rebuild_responder(agent_id)
            elif action == "mark_exited":
                self.state_mgr.update_agent_state(agent_id, AgentState.EXITED)
            elif action == "forget":
                if not agent.is_responder:
                    server = libtmux.Server()
                    responder.cleanup(agent, self.state_mgr, server, aque_dir=self.aque_dir)
                self.state_mgr.remove_agent(agent_id)
            return None
        except Exception as e:
            dbg("desk.orphan_action.error", self.aque_dir, action=action, agent_id=agent_id, err=str(e))
            return str(e)

    def _rebuild_responder(self, agent_id: int) -> None:
        """After a partner agent is recovered, drop the dead responder and
        create a fresh one. No-op for responders themselves or when responder
        support is globally disabled."""
        if not self.config.get("responder_enabled", True):
            return
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None or agent.is_responder:
            return
        server = libtmux.Server()
        responder.cleanup(agent, self.state_mgr, server, aque_dir=self.aque_dir)
        responder.create_for(
            agent, self.config, self.state_mgr, aque_dir=self.aque_dir,
        )

    def _on_refresh(self) -> None:
        if self._mode != "dashboard":
            return
        # Self-heal a dead monitor: it's a shared singleton, so another desk's
        # quit (or a crash) can stop it out from under us. Without this the desk
        # only revived it on attach/detach, so a desk left sitting would freeze
        # every agent in RUNNING (no idle/signal processing). The check is cheap
        # when the monitor is alive and fresh. (_skip_attach: tests/headless
        # must never fork a real daemon.)
        if not self._skip_attach:
            self._ensure_monitor_running()
        state = self.state_mgr.load()
        self._refresh_status_bar(state)
        self._refresh_agent_list(state=state)
        self._try_show_triage(state)

    def _refresh_status_bar(self, state: AppState | None = None) -> None:
        try:
            old = self.query_one("#status-bar", Static)
            if state is None:
                state = self.state_mgr.load()
            counts: dict[AgentState, int] = {}
            for a in state.agents:
                counts[a.state] = counts.get(a.state, 0) + 1
            parts = []
            narrow = self._is_narrow
            state_labels = {
                AgentState.RUNNING: ("run", "running"),
                AgentState.WAITING: ("wait", "waiting"),
                AgentState.ON_HOLD: ("hold", "on_hold"),
                AgentState.EXITED: ("exit", "exited"),
            }
            for st, color in [
                (AgentState.RUNNING, "green"),
                (AgentState.WAITING, "yellow"),
                (AgentState.ON_HOLD, "magenta"),
                (AgentState.EXITED, "grey50"),
            ]:
                c = counts.get(st, 0)
                if c:
                    short, full = state_labels[st]
                    name = short if narrow else full
                    sep = "" if narrow else " "
                    text = f"●{sep}{c} {name}"
                    if self._filter == st:
                        # Active filter — bracket and bold so it's obvious.
                        parts.append(f"[bold {color}]\\[{text}][/bold {color}]")
                    else:
                        parts.append(f"[{color}]{text}[/{color}]")
            hcount = self.history_mgr.count()
            if hcount:
                sep = "" if narrow else " "
                parts.append(f"[dim]●{sep}{hcount} done[/dim]")
            if self._search:
                parts.append(f"[dim]/[/dim] [italic]{self._search}[/italic]")
            joiner = " " if narrow else "    "
            left = joiner.join(parts) if parts else "[dim]No agents[/dim]"
            # Right-aligned brand watermark, matching the design's StatusBar
            # (``● aque desk``). Pad with spaces computed from the bar's plain
            # widths so it hugs the right edge without a layout container —
            # callers read the bar via ``str(render())`` for substring checks.
            brand = "[green]●[/green] [b]aque[/b] [dim]desk[/dim]"
            if self._layout_mode != "auto":
                brand = f"[dim]\\[Layout: {self._layout_mode.capitalize()}][/dim]  {brand}"
            try:
                avail = max(self.size.width - 4, 0)
                left_w = Text.from_markup(left).cell_len
                brand_w = Text.from_markup(brand).cell_len
                gap = max(2, avail - left_w - brand_w)
            except Exception:
                gap = 4
            old.update(f"{left}{' ' * gap}{brand}")
        except Exception:
            pass

    def visible_agents(self, agents: list[AgentInfo]) -> list[AgentInfo]:
        """Filter agents for the main list.

        Layered filters (all applied):

        1. ``show_responders`` — when True, each non-responder is followed by
           its paired responder so the list reads as parent → child.
        2. ``self._filter`` — restrict to a single ``AgentState``.
        3. ``self._search`` — substring match against name, dir, type, state.
        """
        if self.show_responders:
            partners = [a for a in agents if not a.is_responder]
            responders_by_partner = {
                a.partner_id: a for a in agents if a.is_responder
            }
            base: list[AgentInfo] = []
            for p in partners:
                base.append(p)
                r = responders_by_partner.get(p.id)
                if r is not None:
                    base.append(r)
        else:
            base = [a for a in agents if not a.is_responder]

        if self._filter is not None:
            base = [a for a in base if a.state == self._filter]

        q = self._search.strip().lower()
        if q:
            def matches(a: AgentInfo) -> bool:
                return (
                    q in a.label.lower()
                    or q in a.dir.lower()
                    or q in a.state.value.lower()
                    or (a.agent_type or "").lower().find(q) != -1
                )
            base = [a for a in base if matches(a)]

        return base

    def _set_filter(self, state: AgentState | None) -> None:
        """Toggle or set the active state filter."""
        if self._filter == state:
            self._filter = None
        else:
            self._filter = state
        self._last_agent_fingerprint = None
        self._refresh_agent_list()
        self._refresh_status_bar()

    def _set_search(self, value: str) -> None:
        self._search = value
        self._last_agent_fingerprint = None
        self._refresh_agent_list()
        self._refresh_status_bar()

    def _clear_filters(self) -> None:
        if self._filter is None and not self._search:
            return
        self._filter = None
        self._search = ""
        self._last_agent_fingerprint = None
        self._refresh_agent_list()
        self._refresh_status_bar()
        # Also unmount the search input if it's up.
        for w in self.query("#search-input"):
            w.remove()

    def _build_row_label(self, agent: AgentInfo, width: int = 0) -> Text:
        """Render an agent row in the locked Project layout.

            ●  name                                        auto

        The layout encodes three cells — state dot, bold name, soft auto/manual
        chip — and nothing else. State is carried by the dot's colour alone (the
        design dropped the state word from the row; it lives in the preview
        header). The agent type is intentionally not shown on the row; it lives
        in the preview header and stays searchable.

        The mode chip is right-aligned to ``width`` (the list's content width);
        when a name would push the chip past the edge it is truncated with an
        ellipsis rather than wrapping onto a second line.

        Returns a ``rich.text.Text`` so ``str(prompt)`` yields the plain row
        without markup tags — callers can still substring-search for labels.
        """
        state_color = STATE_COLORS.get(agent.state, "white")
        state_dot = f"[{state_color}]●[/{state_color}]"
        indent = "↳ " if agent.is_responder else ""
        # Brief state-change cue: a leading ``▴`` for ~3 s after we detect this
        # agent's state changing — the TUI stand-in for the design's animated
        # row reorder.
        recent = (
            time.monotonic() - self._change_at.get(agent.id, 0.0) < CHANGE_CUE_SECS
        )
        cue = f"[{state_color}]▴[/{state_color}]" if recent else " "

        # Mode chip shows on every partner row; responder sub-rows don't own a
        # toggle, so they omit it.
        if agent.is_responder:
            chip_markup, chip_w = "", 0
        else:
            chip_markup = auto_chip_markup(agent.auto_respond)
            chip_w = len(" auto " if agent.auto_respond else " manual ")

        # Fixed glyphs before the name: "cue space dot 2sp indent".
        prefix_w = 1 + 1 + 1 + 2 + len(indent)
        # Pad so the mode chip lands at the right edge. The name is never
        # truncated (so callers can still match on it); a name long enough to
        # crowd the chip simply collapses the gap to a single space.
        avail = (width or 36) - 1
        pad = max(1, avail - prefix_w - len(agent.label) - chip_w)

        return Text.from_markup(
            f"{cue} {state_dot}  {indent}[bold]{agent.label}[/bold]"
            f"{' ' * pad}{chip_markup}"
        )

    def _refresh_agent_list(self, reset_highlight: bool = False, state: AppState | None = None) -> None:
        try:
            option_list = self.query_one("#agent-option-list", OptionList)
        except Exception:
            return

        if state is None:
            state = self.state_mgr.load()
        active = [a for a in state.agents if a.state != AgentState.DONE]
        sorted_active = sorted_agents(active)
        agents = self.visible_agents(sorted_active)

        new_fingerprint = [(a.id, a.state.value) for a in agents]
        if not reset_highlight and new_fingerprint == self._last_agent_fingerprint:
            return
        self._last_agent_fingerprint = new_fingerprint

        # Record per-agent state transitions before we rebuild the list so
        # the change cue can highlight rows that just moved positions.
        now = time.monotonic()
        for a in agents:
            prev = self._prev_row_state.get(a.id)
            if prev is not None and prev != a.state:
                self._change_at[a.id] = now
            self._prev_row_state[a.id] = a.state
        # Forget agents that aren't in the list any more.
        gone = set(self._prev_row_state) - {a.id for a in agents}
        for aid in gone:
            self._prev_row_state.pop(aid, None)
            self._change_at.pop(aid, None)

        current_highlighted_id = None
        if not reset_highlight and option_list.highlighted is not None:
            try:
                current_option = option_list.get_option_at_index(option_list.highlighted)
                current_highlighted_id = current_option.id
            except Exception:
                pass

        row_width = option_list.content_size.width
        option_list.clear_options()
        for agent in agents:
            label = self._build_row_label(agent, width=row_width)
            option_list.add_option(Option(label, id=str(agent.id)))

        if current_highlighted_id is not None:
            for i in range(option_list.option_count):
                opt = option_list.get_option_at_index(i)
                if opt.id == current_highlighted_id:
                    option_list.highlighted = i
                    break

        if option_list.option_count > 0 and option_list.highlighted is None:
            option_list.highlighted = 0


    def _build_action_strip(self, agent: AgentInfo) -> str:
        """Quick-action affordances for the currently-selected agent.

        Replaces the per-row hover buttons from the web design — no hover
        in a TUI, so the same affordances live in a strip below the
        preview header. The set adapts to the agent's state and role.
        """
        if agent.is_responder:
            parts = ["[bold]Enter[/bold] attach", "[bold]k[/bold]ill"]
        elif agent.state == AgentState.EXITED:
            parts = [
                "[bold]Enter[/bold] review",
                "[bold]k[/bold] done",
                "[bold]h[/bold] hold",
            ]
        else:
            parts = [
                "[bold]Enter[/bold] attach",
                "[bold]k[/bold]ill",
                "[bold]h[/bold]old",
                "[bold]a[/bold]uto",
            ]
        return "\n[dim]actions:[/dim] " + " [dim]·[/dim] ".join(parts)

    # ── Mode switching ───────────────────────────────────────────

    def _diag_geometry(self, where: str) -> None:
        """Temporary diagnostic: log the dashboard region geometry so we can see
        whether a blank screen after suspend/resume is a collapsed layout
        (zero-height middle) or correct-size-but-not-repainted."""
        def _sz(selector):
            try:
                w = self.query_one(selector)
                return f"{w.size.width}x{w.size.height} disp={getattr(w, 'display', '?')}"
            except Exception as e:
                return f"<{type(e).__name__}>"
        try:
            ol = self.query_one("#agent-option-list", OptionList)
            ol_info = f"count={ol.option_count} hi={ol.highlighted}"
        except Exception:
            ol_info = "<no-list>"
        # Every widget mounted on the screen, so a broken run reveals any overlay
        # (triage banner, auto-attach modal, undo bar) sitting over the dashboard.
        try:
            children = " ".join(
                f"{type(w).__name__}({w.size.width}x{w.size.height})"
                for w in self.screen.children
            )
        except Exception as e:
            children = f"<{type(e).__name__}>"
        dbg(
            f"desk.diag.{where}",
            self.aque_dir,
            mode=self._mode,
            app=f"{self.size.width}x{self.size.height}",
            narrow=self._narrow,
            dashboard=_sz("#dashboard"),
            agent_panel=_sz("#agent-panel"),
            option_list=_sz("#agent-option-list"),
            preview=_sz("#preview-panel"),
            embed=_sz("#embedded-terminal"),
            list_state=ol_info,
            triage=str(self._triage_agent.id if self._triage_agent else None),
            screen_children=children,
        )

    def _show_dashboard(self) -> None:
        self._dismiss_triage_modal()
        self._triage_agent = None
        self._mode = "dashboard"
        for w in self.query("ActionMenu, NewAgentForm, QuickLaunchForm"):
            w.remove()
        try:
            self.query_one("#dashboard").display = True
            self.query_one("#status-bar").display = True
        except Exception:
            pass
        self._refresh_agent_list(reset_highlight=True)
        self._refresh_status_bar()
        self._attach_highlighted_terminal()
        self._start_refresh()
        self._focus_dashboard()
        self._ensure_monitor_running()
        self._try_show_triage()

    def pick_auto_attach_target(self, agents: list[AgentInfo]) -> AgentInfo | None:
        """Top-priority WAITING agent that is NOT a responder.

        Used by the auto-attach modal/countdown to choose which waiting agent
        to surface to the user.
        """
        candidates = [
            a for a in agents
            if a.state == AgentState.WAITING and not a.is_responder
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (STATE_PRIORITY.get(a.state, 99), a.last_change_at))
        return candidates[0]

    def _list_has_focus(self) -> bool:
        """True when the dashboard agent list currently holds focus.

        Triage notifications only fire while the list is the focused widget —
        typing in the embedded terminal, the search box, or any other non-list
        focus must suppress the modal so a notification can't steal keystrokes
        mid-task. When focus leaves the embed (see ``on_descendant_blur``) the
        queue re-evaluates immediately rather than waiting for the 2s poll.
        """
        try:
            return self.focused is self.query_one("#agent-option-list", OptionList)
        except Exception:
            return False

    def _try_show_triage(self, state: AppState | None = None) -> None:
        """Surface the top waiting agent in a centered, blocking TriageModal.

        The modal is a separate ModalScreen pushed on demand, so surfacing it
        never reflows the dashboard's 1fr region (the old in-flow banner did).
        Suppressed unless the dashboard agent list holds focus — typing in the
        embed, the search input, or any other widget blocks the modal so a
        notification can't grab the keyboard mid-task. Also suppressed while
        another screen is up or a triage modal is already showing.

        Snooze semantics: when the user dismisses with Esc or ``s``, the
        agent's id is added to ``_snoozed`` with its current ``last_change_at``.
        The next call clears that snooze if the agent has since changed state,
        so a fresh waiting transition re-surfaces.
        """
        if self._skip_attach or self._mode != "dashboard":
            return
        if state is None:
            state = self.state_mgr.load()

        # Decay stale snooze entries: any snoozed agent whose last_change_at
        # has moved (or whose record is gone) is fair game again.
        for aid in list(self._snoozed):
            agent = next((a for a in state.agents if a.id == aid), None)
            if agent is None:
                self._snoozed.discard(aid)
                self._snoozed_last_change.pop(aid, None)
                continue
            if self._snoozed_last_change.get(aid) != agent.last_change_at:
                self._snoozed.discard(aid)
                self._snoozed_last_change.pop(aid, None)

        candidates = [
            a for a in state.agents
            if a.state == AgentState.WAITING
            and not a.is_responder
            and a.id not in self._snoozed
        ]
        candidates.sort(key=lambda a: (STATE_PRIORITY.get(a.state, 99), a.last_change_at))

        if not candidates:
            self._dismiss_triage_modal()
            return

        # A triage modal is already up — leave it (queue length isn't updated
        # live; the next agent surfaces when this one is resolved).
        if self._triage_modal is not None:
            return
        # Don't stack over another modal (kill/help/palette), and only fire
        # while the dashboard list has focus — typing in the embed or search
        # must not be interrupted by a surfacing notification.
        if len(self.screen_stack) > 1 or not self._list_has_focus():
            dbg(
                "desk.triage.suppressed",
                self.aque_dir,
                top_id=candidates[0].id,
                screens=len(self.screen_stack),
                focused=type(self.focused).__name__ if self.focused else None,
                focused_id=getattr(self.focused, "id", None),
            )
            return

        top = candidates[0]
        dbg(
            "desk.triage.show",
            self.aque_dir,
            agent_id=top.id,
            label=top.label,
            queue_len=len(candidates),
        )
        self._triage_agent = top
        modal = TriageModal(top, queue_len=len(candidates))
        self._triage_modal = modal
        self.push_screen(modal, self._on_triage_result)

    def _dismiss_triage_modal(self) -> None:
        """Pop the triage modal if it's up (e.g. on a mode transition)."""
        self._triage_agent = None
        modal, self._triage_modal = self._triage_modal, None
        if modal is None:
            return
        try:
            modal.dismiss(None)
        except Exception:
            pass

    def _snooze_agent(self, agent: AgentInfo) -> None:
        """Suppress triage for ``agent`` until its state changes again."""
        self._snoozed.add(agent.id)
        self._snoozed_last_change[agent.id] = agent.last_change_at

    def _on_triage_result(self, result: str | None) -> None:
        """Apply the modal's chosen action.

        Any resolution acknowledges the agent (snoozes it at its current
        last_change_at) so it won't immediately re-nag — including attach,
        because attaching to an idle agent that's waiting for input doesn't move
        it out of WAITING, so returning to the dashboard would otherwise re-pop
        the same modal in a loop. The snooze decays when the agent's state
        changes again, so a genuinely-new waiting transition re-surfaces it.

        The next queued agent is surfaced by the regular 2s poll (or the
        embed-blur hook), not re-pushed here — that keeps a calm cadence and
        avoids a modal cascade when several agents are waiting.
        """
        agent = self._triage_agent
        self._triage_agent = None
        self._triage_modal = None
        if agent is None or result is None:
            return
        self._snooze_agent(agent)
        dbg(f"desk.triage.{result}", self.aque_dir, agent_id=agent.id)
        if result == ATTACH:
            self._attach_to_agent(agent)
        elif result == PEEK:
            self._select_agent_in_list(agent.id)
        if self._mode == "dashboard" and len(self.screen_stack) == 1:
            self._focus_dashboard()

    def _select_agent_in_list(self, agent_id: int) -> None:
        """Highlight the given agent in the option list without attaching."""
        try:
            ol = self.query_one("#agent-option-list", OptionList)
            for i in range(ol.option_count):
                opt = ol.get_option_at_index(i)
                if opt.id == str(agent_id):
                    ol.highlighted = i
                    break
            self._attach_highlighted_terminal()
        except Exception:
            pass

    def _show_action_menu(self, agent: AgentInfo, was_exited: bool) -> None:
        self._dismiss_triage_modal()
        self._triage_agent = None
        self._mode = "action_menu"
        self._action_agent = agent
        self._action_was_exited = was_exited
        self._stop_refresh()
        try:
            self.query_one("#dashboard").display = False
            self.query_one("#status-bar").display = False
        except Exception:
            pass
        waiting = self.state_mgr.get_agents_by_state(AgentState.WAITING)
        count = len([a for a in waiting if a.id != agent.id])
        self.mount(
            ActionMenu(agent=agent, waiting_count=count, config=self.config, was_exited=was_exited),
            after=self.query_one(Header),
        )
        self._apply_layout()
        try:
            ol = self.query_one("#action-option-list", OptionList)
            ol.focus()
            if ol.option_count > 0 and ol.highlighted is None:
                ol.highlighted = 0
        except Exception:
            pass

    def _show_new_agent_form(self) -> None:
        self._dismiss_triage_modal()
        self._triage_agent = None
        self._mode = "new_agent_form"
        self._stop_refresh()
        try:
            self.query_one("#dashboard").display = False
            self.query_one("#status-bar").display = False
        except Exception:
            pass
        from aque.plugins import discover_plugins
        plugin_names = sorted(discover_plugins().keys())
        self.mount(
            NewAgentForm(
                dir_history_mgr=self.dir_history_mgr,
                default_dir=self.config.get("default_dir", str(Path.home())),
                plugin_names=plugin_names,
            ),
            after=self.query_one(Header),
        )
        self._apply_layout()

    def _show_quick_launch_form(self) -> None:
        self._dismiss_triage_modal()
        self._triage_agent = None
        self._mode = "quick_launch_form"
        self._stop_refresh()
        try:
            self.query_one("#dashboard").display = False
            self.query_one("#status-bar").display = False
        except Exception:
            pass
        from aque.plugins import discover_plugins
        plugin_names = sorted(discover_plugins().keys())
        tasks = self.history_mgr.recent_tasks()
        self.mount(
            QuickLaunchForm(tasks=tasks, plugin_names=plugin_names),
            after=self.query_one(Header),
        )
        self._apply_layout()

    def _quick_launch_task(self, task: dict) -> None:
        """Launch a recent task. Prompt for a type first when it's unknown."""
        if not task["type_known"]:
            self.query_one(QuickLaunchForm).show_type_step(task)
            return
        self._launch_quick_task_with_type(task, task["agent_type"])

    def _launch_quick_task_with_type(self, task: dict, agent_type: str | None) -> None:
        for w in self.query("QuickLaunchForm"):
            w.remove()
        # Reset mode now that the form widget is gone — _perform_launch
        # may push a modal (resume picker) and we don't want the on_key
        # handler trying to query a QuickLaunchForm that no longer exists.
        self._mode = "dashboard"
        self._perform_launch(
            command=list(task["command"]),
            working_dir=task["dir"],
            label=task["label"] or None,
            agent_type=agent_type,
        )

    def _perform_launch(
        self,
        command: list[str],
        working_dir: str,
        label: str | None,
        agent_type: str | None,
    ) -> int:
        """Launch an agent and run the shared post-launch flow.

        For claude with prior sessions in the target dir, this opens
        ResumePickerScreen first; the actual launch happens in the picker
        callback. For all other types (and claude in empty dirs), launch
        proceeds directly via _finish_perform_launch.

        Returns the agent_id for the direct (non-picker) path; the picker
        path returns -1 because the actual id isn't known until the callback
        fires. Callers that care about the id (none today) should be reworked
        to use a callback.
        """
        if agent_type == "claude":
            capturer = CAPTURERS["claude"]
            summaries = capturer.summarize(working_dir)
            if summaries:
                def on_pick(result: PickerResult | None) -> None:
                    if result is None:
                        # User cancelled. The form that opened this picker
                        # hid #dashboard/#status-bar before pushing us; if we
                        # don't restore them we leave the user staring at a
                        # blank screen (just the Header).
                        self._show_dashboard()
                        return
                    if result.action == "fresh":
                        # Pre-assign a fresh UUID, exactly like the empty-dir path.
                        cmd, sid = capturer.preassign(command)
                    else:
                        # Resume — keep the original command; finisher will rewrite with
                        # the picked session id.
                        cmd, sid = command, result.session_id
                    self._finish_perform_launch(
                        command=cmd, working_dir=working_dir,
                        label=label, agent_type="claude",
                        session_id=sid,
                    )
                self.push_screen(
                    ResumePickerScreen(summaries, working_dir, "claude"),
                    on_pick,
                )
                return -1
            # No prior sessions — still pre-assign so we skip capture.
            cmd, sid = capturer.preassign(command)
            return self._finish_perform_launch(
                command=cmd, working_dir=working_dir,
                label=label, agent_type="claude", session_id=sid,
            )
        return self._finish_perform_launch(
            command=command, working_dir=working_dir,
            label=label, agent_type=agent_type, session_id=None,
        )

    def _finish_perform_launch(
        self,
        command: list[str],
        working_dir: str,
        label: str | None,
        agent_type: str | None,
        session_id: str | None,
    ) -> int:
        """The deterministic tail of _perform_launch. Plugin hook install,
        launch_agent, responder pairing, dir-history record, attach."""
        # If caller passed a session_id but the command wasn't already rewritten
        # (e.g. picker returned a resume id), rewrite it now.
        if session_id is not None and agent_type in CAPTURERS:
            capturer = CAPTURERS[agent_type]
            # Only rewrite if --session-id isn't already in the command.
            if "--session-id" not in command:
                command = capturer.resume_command(command, session_id)

        if agent_type:
            from aque.plugins import get_plugin
            plugin = get_plugin(agent_type)
            if plugin and not plugin.is_installed():
                plugin.install_hook()
        agent_id = launch_agent(
            command=command,
            working_dir=working_dir,
            label=label or None,
            state_manager=self.state_mgr,
            prefix=self.config["session_prefix"],
            background=True,
            agent_type=agent_type,
            session_id=session_id,
        )
        if self.config.get("responder_enabled", True):
            partner = next(
                (a for a in self.state_mgr.load().agents if a.id == agent_id),
                None,
            )
            if partner is not None:
                responder.create_for(
                    partner, self.config, self.state_mgr, aque_dir=self.aque_dir
                )
        self.dir_history_mgr.record_use(working_dir)
        self._ensure_monitor_running()
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent and not self._skip_attach:
            self._attach_to_agent(agent)
        else:
            self._show_dashboard()
        return agent_id

    # ── Agent actions ────────────────────────────────────────────

    def _attach_to_agent(self, agent: AgentInfo) -> None:
        dbg("desk.attach.start", self.aque_dir, agent_id=agent.id,
            from_state=agent.state.value)
        self._diag_geometry("attach.pre-suspend")
        self._dismiss_triage_modal()
        self._triage_agent = None
        self._stop_refresh()

        # The embed pins the window to its small size (and hides the status
        # line); undo that so the full-screen client gets the full terminal and
        # its status bar back. The embed re-pins when it re-attaches on return
        # (via _show_dashboard).
        self._unpin_embed_window()

        # Tear down the embed's own tmux client before suspending. The embed is
        # a background ``tmux attach-session`` whose fd reader keeps firing on
        # the asyncio loop during ``suspend()``; left attached it becomes a
        # second client on the session and size-fights the full-screen client,
        # leaving the pyte screen blank/garbled on return. Detaching means only
        # the full-screen client is attached, and the return path
        # (_show_dashboard → _attach_highlighted_terminal) re-spawns a fresh PTY
        # for a clean full redraw instead of no-op'ing on the still-live session.
        try:
            self.query_one("#embedded-terminal", TerminalView).detach()
        except Exception:
            pass

        with self.suspend():
            subprocess.run(["tmux", "attach-session", "-t", agent.tmux_session])
            # Erase tmux's "[detached (from session ...)]" line so it doesn't
            # accumulate in the terminal scrollback on each detach.
            try:
                sys.stdout.write("\x1b[1A\x1b[2K\r")
                sys.stdout.flush()
            except Exception:
                pass
        self._post_detach_debounce_until = time.monotonic() + 0.5

        state = self.state_mgr.load()
        updated_agent = next((a for a in state.agents if a.id == agent.id), agent)
        dbg(
            "desk.attach.resumed",
            self.aque_dir,
            agent_id=agent.id,
            state_after_detach=updated_agent.state.value,
        )
        if updated_agent.state == AgentState.EXITED:
            self._kill_agent(updated_agent.id)
        self._diag_geometry("attach.post-suspend")
        self._show_dashboard()
        self.call_after_refresh(lambda: self._diag_geometry("attach.after-refresh"))

    def _kill_agent(self, agent_id: int) -> None:
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            return
        # Snapshot the agent (and its responder, if any) so undo can put
        # the rows back. The tmux session can't be revived once killed —
        # the orphan scanner will flag the restored agent as session-less
        # the next time the desk runs.
        snapshot = AgentInfo.from_dict(agent.to_dict())
        responder_snapshot: AgentInfo | None = None
        if not agent.is_responder:
            resp = next(
                (a for a in state.agents if a.is_responder and a.partner_id == agent.id),
                None,
            )
            if resp is not None:
                responder_snapshot = AgentInfo.from_dict(resp.to_dict())

        server = self._get_tmux_server()
        try:
            session = server.sessions.get(session_name=agent.tmux_session)
            if session:
                session.kill()
        except Exception:
            pass
        # If killing a partner, also clean up its responder.
        if not agent.is_responder:
            responder.cleanup(agent, self.state_mgr, server, aque_dir=self.aque_dir)
        self.state_mgr.done_agent(agent_id, self.history_mgr)

        def _restore() -> None:
            # Re-add the agent (and its responder) into the live state and
            # drop the matching history entry so counts stay honest.
            self.state_mgr.add_agent(snapshot)
            if responder_snapshot is not None:
                self.state_mgr.add_agent(responder_snapshot)
            self.history_mgr.remove_entry(agent_id)

        self._show_undo(f"Killed {agent.label}", _restore)

    def _show_undo(self, message: str, restore: callable) -> None:
        """Mount the undo bar and arm the 5s auto-dismiss."""
        # Replace any previous entry — the user's most recent action is the
        # only thing reachable via ``u``.
        self._dismiss_undo()
        self._undo_entry = (message, restore)
        bar = UndoBar(message)
        try:
            self.mount(bar)
        except Exception:
            pass
        self._undo_timer = self.set_timer(5.0, self._dismiss_undo)

    def _dismiss_undo(self) -> None:
        if self._undo_timer is not None:
            self._undo_timer.stop()
            self._undo_timer = None
        self._undo_entry = None
        for w in self.query("#undo-bar"):
            w.remove()

    def _perform_undo(self) -> None:
        if self._undo_entry is None:
            return
        _, restore = self._undo_entry
        try:
            restore()
        except Exception as e:
            dbg("desk.undo.error", self.aque_dir, err=str(e))
        self._dismiss_undo()
        self._last_agent_fingerprint = None
        self._refresh_agent_list()
        self._refresh_status_bar()

    def _hold_agent(self, agent_id: int) -> None:
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            return
        if agent.state == AgentState.ON_HOLD:
            self.state_mgr.update_agent_state(agent_id, AgentState.RUNNING)
        else:
            self.state_mgr.update_agent_state(agent_id, AgentState.ON_HOLD)

    def _ensure_monitor_running(self) -> None:
        import os
        import signal
        import time as _time

        state = self.state_mgr.load()
        pid = state.monitor_pid
        pid_file = self.aque_dir / "monitor.pid"

        if pid:
            alive = True
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                alive = False

            fresh = False
            try:
                age = _time.time() - pid_file.stat().st_mtime
                staleness = max(self.config["snapshot_interval"] * 3, 6)
                fresh = age <= staleness
            except OSError:
                fresh = False

            if alive and fresh:
                return

            # Dead, hung, or PID reused. If something is still holding the pid
            # (a hung monitor), terminate it so we don't end up with two.
            if alive:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            state.monitor_pid = None
            self.state_mgr.save(state)

        start_monitor_daemon(self.aque_dir)

    def _get_highlighted_agent_id(self) -> int | None:
        try:
            option_list = self.query_one("#agent-option-list", OptionList)
        except Exception:
            return None
        if option_list.highlighted is None:
            return None
        option = option_list.get_option_at_index(option_list.highlighted)
        return int(option.id)

    # ── Event handlers ───────────────────────────────────────────

    def _do_action(self, action_id: str) -> None:
        """Execute an action menu choice by its id."""
        if self._action_agent is None:
            return
        agent = self._action_agent
        was_exited = self._action_was_exited

        if action_id == "dismiss" and not was_exited:
            self.state_mgr.update_agent_state(agent.id, AgentState.RUNNING)
            self._show_dashboard()
        elif action_id == "done":
            self._kill_agent(agent.id)
            self._show_dashboard()
        elif action_id == "skip" and not was_exited:
            self.state_mgr.update_agent_state(agent.id, AgentState.WAITING)
            self._show_dashboard()
        elif action_id == "hold":
            self.state_mgr.update_agent_state(agent.id, AgentState.ON_HOLD)
            self._show_dashboard()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self._mode == "action_menu":
            self._do_action(event.option.id)
            return
        if self._mode == "new_agent_form" and event.option_list.id == "type-list":
            form = self.query_one(NewAgentForm)
            form.select_type()
            return
        if self._mode == "quick_launch_form":
            form = self.query_one(QuickLaunchForm)
            if event.option_list.id == "quick-launch-list":
                task = form.selected_task()
                if task is not None:
                    self._quick_launch_task(task)
            elif event.option_list.id == "quick-launch-type-list":
                task = form._pending_task
                if task is not None:
                    self._launch_quick_task_with_type(task, form.selected_type())
            return
        if self._mode != "dashboard":
            return
        if time.monotonic() < self._post_detach_debounce_until:
            dbg("desk.list_select.debounced", self.aque_dir, option_id=event.option.id)
            return
        agent_id = int(event.option.id)
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            return
        if self._skip_attach:
            return
        # Enter "pops into" the embedded terminal for the highlighted agent:
        # attach (if not already) and move keyboard focus into the embed so the
        # user types to the agent. Full-screen attach is the Ctrl+Shift+F action.
        try:
            term = self.query_one("#embedded-terminal", TerminalView)
        except Exception:
            return
        term.attach(
            ["tmux", "attach-session", "-t", agent.tmux_session],
            size_sync=self._embed_size_sync(agent.tmux_session),
        )
        term.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self._mode != "dashboard":
            return
        if self._preview_debounce_timer is not None:
            self._preview_debounce_timer.stop()
        self._preview_debounce_timer = self.set_timer(0.15, self._attach_highlighted_terminal)

    def _attach_highlighted_terminal(self) -> None:
        self._preview_debounce_timer = None
        if self._skip_attach:
            return  # tests / headless: never spawn a real tmux client
        try:
            ol = self.query_one("#agent-option-list", OptionList)
            term = self.query_one("#embedded-terminal", TerminalView)
        except Exception:
            return
        if ol.highlighted is None or ol.option_count == 0:
            term.detach()
            self._unpin_embed_window()
            return
        option = ol.get_option_at_index(ol.highlighted)
        agent_id = int(option.id)
        agent = next((a for a in self.state_mgr.load().agents if a.id == agent_id), None)
        if agent is None:
            term.detach()
            self._unpin_embed_window()
            return
        if self._triage_agent is not None:
            # A triage pill owns input right now; don't steal focus back.
            return
        # Hover-attach: preview the highlighted agent without stealing focus
        # from the list. If the embed already had focus (e.g. switching agents
        # via Ctrl+Shift+J/K from inside it), keep focus there across the swap.
        was_focused = self.focused is term
        term.attach(
            ["tmux", "attach-session", "-t", agent.tmux_session],
            size_sync=self._embed_size_sync(agent.tmux_session),
        )
        if was_focused:
            term.focus()

    @staticmethod
    def _tmux(*args: str) -> None:
        try:
            subprocess.run(["tmux", *args], check=False, capture_output=True)
        except Exception:
            pass

    def _embed_size_sync(self, session: str):
        """Return a (cols, rows) callback that pins ``session``'s tmux window to
        the embed's size. The embed renders a pyte screen sized to the widget;
        if the tmux window is a different size (another client, or a transient
        resize when a notification mounts), tmux feeds wrong-sized frames into
        the pyte screen and the embed shows duplicated/garbled rows.

        We disable the session's status line (so the window height equals the
        client height — leaving it on steals a row and offsets every line by
        one) and pin ``window-size manual`` + ``resize-window`` to the embed's
        size. Larger external clients letterbox; that's the accepted trade-off
        for a clean embed. The status bar stays off to give the borderless embed
        every row for the agent's own output. The pin is reverted in
        ``_unpin_embed_window`` when we switch away, go full-screen, or quit.
        """
        def _sync(cols: int, rows: int) -> None:
            if self._skip_attach:
                return
            prev = self._embed_pinned
            if prev is not None and prev[0] != session:
                self._unpin_embed_window()  # restore the agent we left
            if self._embed_pinned == (session, cols, rows):
                return
            self._embed_pinned = (session, cols, rows)
            self._tmux("set-option", "-t", session, "status", "off")
            self._tmux("set-option", "-t", session, "window-size", "manual")
            self._tmux("resize-window", "-t", session, "-x", str(cols), "-y", str(rows))
        return _sync

    def _unpin_embed_window(self) -> None:
        """Undo the embed's window pin: revert status and window-size to the
        session's inherited (global) values so the agent sizes normally again
        for a full-screen or external attach."""
        if self._embed_pinned is None:
            return
        session = self._embed_pinned[0]
        self._embed_pinned = None
        self._tmux("set-option", "-u", "-t", session, "window-size")
        self._tmux("set-option", "-u", "-t", session, "status")

    def on_directory_picker_directory_selected(self, event) -> None:
        """Handle directory selection from the picker."""
        if self._mode != "new_agent_form":
            return
        form = self.query_one(NewAgentForm)
        form._selected_dir = event.path
        form.show_command_step()

    def on_tree_node_highlighted(self, event) -> None:
        """Update selected path as the user navigates the tree (fallback mode)."""
        if self._mode != "new_agent_form":
            return
        form = self.query_one(NewAgentForm)
        if not form._tree_mode:
            return
        node = event.node
        if node.data and hasattr(node.data, 'path'):
            path = node.data.path
        elif hasattr(node, 'data') and isinstance(node.data, Path):
            path = node.data
        else:
            return
        if Path(path).is_dir():
            form.update_dir_display(str(path))

    def on_input_changed(self, event) -> None:
        """Live-update the agent-list filter as the user types in search."""
        if getattr(event.input, "id", None) == "search-input":
            self._set_search(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            # Enter on search returns focus to the agent list so the user
            # can immediately ↑↓ through the filtered results.
            self._focus_dashboard()
            return
        if self._mode != "new_agent_form":
            return
        form = self.query_one(NewAgentForm)
        if event.input.id == "command-input":
            if not event.value.strip():
                return
            form._command = event.value.strip()
            form.show_label_step()
        elif event.input.id == "label-input":
            form._label = event.value.strip()
            agent_type = form._selected_type
            command = shlex.split(form._command)
            working_dir = form._selected_dir
            label = form._label or None
            for w in self.query("NewAgentForm"):
                w.remove()
            # Reset mode now that the form widget is gone — _perform_launch
            # may push a modal (resume picker) and we don't want the on_key
            # handler trying to query a NewAgentForm that no longer exists.
            self._mode = "dashboard"
            self._perform_launch(
                command=command,
                working_dir=working_dir,
                label=label,
                agent_type=agent_type,
            )

    # ── Key handling ─────────────────────────────────────────────

    def action_new_agent(self) -> None:
        if self._mode == "dashboard":
            self._show_new_agent_form()

    def action_quick_launch(self) -> None:
        if self._mode == "dashboard":
            self._show_quick_launch_form()

    def action_kill_agent(self) -> None:
        if self._mode != "dashboard":
            return
        agent_id = self._get_highlighted_agent_id()
        if agent_id is None:
            return
        agent = next((a for a in self.state_mgr.load().agents if a.id == agent_id), None)
        label = agent.label if agent is not None else f"agent {agent_id}"

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._kill_agent(agent_id)
            self._refresh_agent_list()
            self._refresh_status_bar()

        # Killing is irreversible (the tmux session can't be revived), so guard
        # it behind an explicit confirmation — a stray 'k' just shows the prompt.
        self.push_screen(
            ConfirmModal(
                f"Kill {label}?",
                subtext="The tmux session can't be revived.",
                confirm_label="Kill",
            ),
            _on_confirm,
        )

    def action_hold_agent(self) -> None:
        if self._mode == "dashboard":
            agent_id = self._get_highlighted_agent_id()
            if agent_id is not None:
                self._hold_agent(agent_id)
                self._refresh_agent_list()
                self._refresh_status_bar()

    def action_undo(self) -> None:
        """Restore whatever the last destructive action removed."""
        if self._mode != "dashboard":
            return
        self._perform_undo()

    def action_show_help(self) -> None:
        """Open the keyboard-shortcuts overlay."""
        if self._mode != "dashboard":
            return
        self.push_screen(HelpModal())

    def action_command_palette(self) -> None:
        """Open the fuzzy-finder over agents and global commands."""
        if self._mode != "dashboard":
            return
        state = self.state_mgr.load()
        self.push_screen(CommandPalette(state.agents), self._on_command_picked)

    def _on_command_picked(self, item: CommandItem | None) -> None:
        if item is None:
            return
        if item.kind in ("attach", "peek"):
            state = self.state_mgr.load()
            agent = next((a for a in state.agents if a.id == item.payload), None)
            if agent is None:
                return
            if item.kind == "attach":
                self._attach_to_agent(agent)
            else:
                self._select_agent_in_list(agent.id)
            return
        # action items
        action = item.payload
        if action == "new":
            self._show_new_agent_form()
        elif action == "quick_launch":
            self.action_quick_launch()
        elif action == "kill":
            self.action_kill_agent()
        elif action == "hold":
            self.action_hold_agent()
        elif action == "auto":
            self.action_toggle_auto_respond()
        elif action == "fullscreen":
            self.action_attach_fullscreen()
        elif action == "cycle_layout":
            self.action_cycle_layout()
        elif action == "undo":
            self.action_undo()
        elif action == "responders":
            self.action_toggle_responders()
        elif action == "help":
            self.action_show_help()
        elif action == "filter:none":
            self._clear_filters()
        elif isinstance(action, str) and action.startswith("filter:"):
            try:
                self._set_filter(AgentState(action.split(":", 1)[1]))
            except ValueError:
                pass

    def action_cycle_layout(self) -> None:
        """Cycle the forced layout: auto → wide → stacked → auto."""
        order = ("auto", "wide", "stacked")
        self._layout_mode = order[(order.index(self._layout_mode) + 1) % len(order)]
        self._apply_layout()
        self._refresh_status_bar()

    def action_filter_state(self, state_value: str) -> None:
        """Toggle the active filter to ``state_value``."""
        if self._mode != "dashboard":
            return
        try:
            state = AgentState(state_value)
        except ValueError:
            return
        self._set_filter(state)

    def action_focus_search(self) -> None:
        """Show an inline search Input and focus it."""
        if self._mode != "dashboard":
            return
        # Already up? Just focus it.
        existing = self.query("#search-input")
        if existing:
            existing.first().focus()
            return
        search = Input(
            value=self._search, placeholder="filter agents (esc to close)…",
            id="search-input",
        )
        agent_panel = self.query_one("#agent-panel")
        agent_panel.mount(search, before="#agent-option-list")
        search.focus()

    def action_toggle_responders(self) -> None:
        if self._mode != "dashboard":
            return
        self.show_responders = not self.show_responders
        # Force rebuild since the agent list shape changes.
        self._last_agent_fingerprint = None
        self._refresh_agent_list()

    def action_toggle_auto_respond(self) -> None:
        if self._mode != "dashboard":
            return
        agent_id = self._get_highlighted_agent_id()
        if agent_id is None:
            return
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            return
        if agent.is_responder:
            self.notify(
                "Auto-response toggle only applies to non-responder agents.",
                timeout=2,
            )
            return
        new_val = self.state_mgr.toggle_auto_respond(agent.id)
        self.notify(f"Auto-response: {'on' if new_val else 'off'}", timeout=2)
        self._last_agent_fingerprint = None
        self._refresh_agent_list()

    def action_quit_app(self) -> None:
        self._unpin_embed_window()  # don't leave the agent's window stuck at embed size
        stop_monitor(self.aque_dir)
        self.exit()

    def action_attach_fullscreen(self) -> None:
        if self._mode != "dashboard":
            return
        try:
            ol = self.query_one("#agent-option-list", OptionList)
        except Exception:
            return
        if ol.highlighted is None:
            return
        agent_id = int(ol.get_option_at_index(ol.highlighted).id)
        agent = next((a for a in self.state_mgr.load().agents if a.id == agent_id), None)
        if agent is not None and not self._skip_attach:
            self._attach_to_agent(agent)

    def action_next_agent(self) -> None:
        self._move_highlight(+1)

    def action_prev_agent(self) -> None:
        self._move_highlight(-1)

    def action_back_to_list(self) -> None:
        """Return keyboard focus from the embedded terminal to the agent list,
        so arrow navigation and the plain-letter shortcuts work again."""
        if self._mode != "dashboard":
            return
        self._focus_dashboard()

    def _move_highlight(self, delta: int) -> None:
        if self._mode != "dashboard":
            return
        try:
            ol = self.query_one("#agent-option-list", OptionList)
        except Exception:
            return
        if ol.option_count == 0:
            return
        cur = 0 if ol.highlighted is None else ol.highlighted
        ol.highlighted = (cur + delta) % ol.option_count
        # Changing the highlight posts OptionHighlighted -> debounced re-attach
        # + refocus of the terminal, so the user stays "in" the new agent.

    def on_key(self, event) -> None:
        # Triage keys are handled by the TriageModal screen's own bindings while
        # it's up; no routing needed here.
        if self._mode == "dashboard" and event.key == "escape":
            # Esc on the dashboard clears active filter + search, and closes
            # the inline search input if it's open.
            had_search_focus = bool(self.query("#search-input"))
            if had_search_focus or self._filter is not None or self._search:
                self._clear_filters()
                self._focus_dashboard()
                event.stop()
                return

        if self._mode == "new_agent_form":
            form = self.query_one(NewAgentForm)

            if form._step == "type":
                if event.key == "escape":
                    for w in self.query("NewAgentForm"):
                        w.remove()
                    self._show_dashboard()
                    return
                if event.key == "enter":
                    form.select_type()
                    return
                return

            if event.key == "escape":
                if form._tree_mode:
                    form.hide_tree_fallback()
                    return
                if form._step == "label":
                    form.show_command_step()
                    return
                if form._step == "command":
                    form.show_dir_step()
                    return
                if form._step == "dir":
                    form.show_type_step()
                    return
                return

            if form._step == "dir":
                if event.character == "b" and not form._tree_mode:
                    form.show_tree_fallback()
                    return
                if form._tree_mode and event.character == "s":
                    if form._selected_dir:
                        form.show_command_step()
                    return
            return

        if self._mode == "quick_launch_form":
            if event.key == "escape":
                form = self.query_one(QuickLaunchForm)
                if form._step == "type":
                    form.show_tasks_step()
                    return
                for w in self.query("QuickLaunchForm"):
                    w.remove()
                self._show_dashboard()
                return
            return

        if self._mode == "action_menu":
            if self._action_agent is None:
                return
            keys = self.config["action_keys"]
            key_to_action = {
                keys.get("dismiss"): "dismiss",
                keys.get("done"): "done",
                keys.get("skip"): "skip",
                keys.get("hold"): "hold",
            }
            action_id = key_to_action.get(event.character)
            if action_id:
                self._do_action(action_id)
            return
