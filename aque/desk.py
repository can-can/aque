import hashlib
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
from aque.widgets.dir_picker import DirectoryPicker, key_hint
from aque.widgets.help_modal import HelpModal
from aque.widgets.orphan_modal import OrphanModal
from aque.widgets.triage_pill import TriagePill
from aque.widgets.undo_bar import UndoBar

STATE_PRIORITY = {
    AgentState.WAITING: 0,
    AgentState.EXITED: 1,
    AgentState.RUNNING: 2,
    AgentState.FOCUSED: 3,
    AgentState.ON_HOLD: 4,
    AgentState.DONE: 5,
}

# How long the row state-change cue (the leading ``▴``) stays visible after
# we detect a transition. Three seconds is roughly one-and-a-half periodic
# refreshes, so the marker is reliably caught by a glancing user.
CHANGE_CUE_SECS = 3.0


def sorted_agents(agents: list[AgentInfo]) -> list[AgentInfo]:
    return sorted(agents, key=lambda a: (STATE_PRIORITY.get(a.state, 99), a.last_change_at))


def build_preview_meta(agent: AgentInfo, agents: list[AgentInfo]) -> str:
    """Return the auto-responder meta-line shown in the preview pane.

    Kept for backwards compatibility with callers that want the single-line
    summary. New callers should prefer ``build_responder_panel`` for the
    structured (multi-line) card that mirrors the design.
    """
    if agent.is_responder:
        partner = next(
            (a for a in agents if a.id == agent.partner_id),
            None,
        )
        if partner is None:
            return f"Auto-responder for: (partner id={agent.partner_id} missing)"
        return f"Auto-responder for: {partner.label} (id {partner.id})"

    resp = next(
        (a for a in agents if a.is_responder and a.partner_id == agent.id),
        None,
    )
    if resp is None:
        return "Auto-response: unavailable (no responder)"
    if resp.state == AgentState.EXITED:
        return "Responder exited — auto-response disabled"
    state_word = "on" if agent.auto_respond else "off"
    return f"Auto-response: {state_word} (responder: {resp.tmux_session})"


def extract_responder_log(pane_content: str | None, limit: int = 4) -> list[str]:
    """Pull the last ``limit`` ``AQUE:``-prefixed lines from a responder pane.

    These are the nudges the system has sent the responder — a rough proxy
    for "what the responder has been asked to do lately". The design's
    reply log was prototype-only fake data; this is real activity we can
    surface without changing the responder's storage model.
    """
    if not pane_content:
        return []
    out: list[str] = []
    for line in reversed(pane_content.splitlines()):
        stripped = line.strip()
        if stripped.startswith("AQUE:"):
            # Drop the leading 'AQUE: ' for a cleaner display.
            out.append(stripped[len("AQUE:"):].strip())
            if len(out) >= limit:
                break
    return list(reversed(out))


def load_responder_rules(aque_dir: Path, partner_id: int) -> list[str]:
    """Read optional per-responder rules from
    ``<aque_dir>/responders/<partner_id>/rules.txt``.

    One rule per non-empty line; lines starting with ``#`` are treated as
    comments. Returns an empty list if the file is missing — there is no
    "default" rule set, so the panel just won't render that section.
    """
    rules_path = Path(aque_dir) / "responders" / str(partner_id) / "rules.txt"
    if not rules_path.exists():
        return []
    try:
        text = rules_path.read_text()
    except OSError:
        return []
    rules: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.append(line)
    return rules


def build_responder_panel(
    agent: AgentInfo,
    agents: list[AgentInfo],
    pane_content: str | None = None,
    aque_dir: Path | None = None,
) -> str:
    """Render the responder panel for the preview pane.

    Three branches:

    * **Responder selected** — show "responding for: <partner>" with the
      partner's state and dir, plus a hint that selecting them jumps to
      the partner pane.
    * **Partner without responder** — show a dashed empty-state block.
    * **Partner with responder** — show eyebrow (auto / paused / exited)
      + session id + last_nudge_at timestamp, plus a reply log (recent
      ``AQUE:`` nudges from the responder's pane) and any rules loaded
      from ``rules.txt`` if both are available.

    Returns Rich markup. The caller wraps it in ``Text.from_markup`` and
    appends to the preview pane.
    """
    if agent.is_responder:
        partner = next((a for a in agents if a.id == agent.partner_id), None)
        if partner is None:
            return (
                "\n\n[dim]── RESPONDING FOR ──[/dim]\n"
                f"[red]partner missing (id={agent.partner_id})[/red]"
            )
        partner_color = STATE_COLORS.get(partner.state, "white")
        return (
            "\n\n[dim]── RESPONDING FOR ──[/dim]\n"
            f"[bold]{partner.label}[/bold]  "
            f"[{partner_color}]{partner.state.value}[/{partner_color}]  "
            f"[dim]{partner.dir}[/dim]\n"
            "[dim]select the partner row to jump to its pane[/dim]"
        )

    resp = next(
        (a for a in agents if a.is_responder and a.partner_id == agent.id),
        None,
    )
    if resp is None:
        return (
            "\n\n[dim]── NO RESPONDER ─ ─ ─[/dim]\n"
            "[dim]This agent runs without a paired responder. "
            "Every prompt comes straight to you.[/dim]"
        )

    if resp.state == AgentState.EXITED:
        eyebrow = "[red]● RESPONDER · EXITED[/red]"
    elif agent.auto_respond:
        eyebrow = "[green]● RESPONDER · AUTO[/green]"
    else:
        eyebrow = "[yellow]● RESPONDER · PAUSED[/yellow]"

    lines = [
        "",
        "",
        eyebrow,
        f"[dim]session: {resp.tmux_session}[/dim]",
    ]
    if agent.last_nudge_at:
        lines.append(f"[dim]last nudge: {agent.last_nudge_at}[/dim]")

    # Reply log — recent AQUE: nudges from the responder's pane. Surface
    # whatever the responder has been asked to handle lately.
    log = extract_responder_log(pane_content)
    if log:
        lines.append("[dim]recent activity:[/dim]")
        for entry in log:
            # Truncate to keep the panel readable.
            display = entry if len(entry) <= 70 else entry[:67] + "…"
            lines.append(f"  [dim]·[/dim] {display}")

    # Rules — opt-in per-responder policy file. Skip the section entirely
    # when no rules.txt exists; the panel shouldn't suggest an unconfigured
    # surface.
    if aque_dir is not None:
        rules = load_responder_rules(aque_dir, agent.id)
        if rules:
            lines.append("[dim]rules:[/dim]")
            for rule in rules:
                lines.append(f"  [dim]·[/dim] {rule}")

    lines.append("[dim]press a to toggle auto-response[/dim]")
    return "\n".join(lines)


# ── Widgets ──────────────────────────────────────────────────────────


class StatusBar(Static):
    def __init__(self) -> None:
        super().__init__("[dim]No agents[/dim]", id="status-bar")


class PreviewPane(Static):
    def __init__(self, content: str = "") -> None:
        super().__init__(content or "[dim]Select an agent to preview[/dim]", id="preview-pane")


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
        # Pre-fill a sensible default label: ``<command-word> . <dir-basename>``.
        # Mirrors the prompt-style convention the rest of the desk uses
        # (``aider . docs``, ``claude . monorepo``) so users can launch
        # without typing while still being able to override.
        cmd_word = (self._command.split() or ["agent"])[0]
        dir_base = Path(self._selected_dir).name or "agent"
        self._label = f"{cmd_word} . {dir_base}"
        self.query_one("#new-agent-step").update(
            f"Step 4/4: Label  (dir: {self._selected_dir}, cmd: {self._command})"
        )
        self.query_one("#command-input").remove()
        self.mount(
            Input(
                value=self._label,
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

    def compose(self) -> ComposeResult:
        yield Static("Quick Launch", id="quick-launch-title")
        if not self._tasks:
            yield Static("[dim]No recent tasks yet[/dim]", id="quick-launch-empty")
            yield Static(key_hint("Esc", "back"), id="quick-launch-hint")
            return
        options = []
        for i, t in enumerate(self._tasks):
            label = t["label"] or " ".join(t["command"])
            chip = type_chip_markup(t["agent_type"])
            options.append(Option(f"{label}   [dim]{t['dir']}[/dim] {chip}", id=str(i)))
        yield OptionList(*options, id="quick-launch-list")
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

    def show_tasks_step(self) -> None:
        """Restore the recent-task list (used when stepping back from type)."""
        self._step = "tasks"
        self._pending_task = None


# ── Main App ─────────────────────────────────────────────────────────


class DeskApp(App):
    TITLE = "aque desk"
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
    #agent-panel.narrow {
        width: 100%;
        border-right: none;
    }
    #preview-panel {
        width: 60%;
        padding: 1 2;
    }
    #agent-option-list {
        height: 100%;
    }
    #preview-pane {
        height: 100%;
        overflow-y: auto;
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
        ("q", "quit_app", "Quit"),
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
        self._last_agent_fingerprint: list | None = None
        self._narrow: bool = False  # Cached narrow state, updated by _apply_layout
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
        # Currently-surfaced waiting agent, if any. The pill is mounted
        # while this is non-None and the dashboard is foregrounded.
        self._triage_agent: AgentInfo | None = None
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._make_status_bar()
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

        agent_panel._add_child(OptionList(id="agent-option-list"))

        preview_panel._add_child(PreviewPane())
        dashboard._add_child(agent_panel)
        dashboard._add_child(preview_panel)
        return dashboard

    def _apply_layout(self, width: int | None = None) -> None:
        """Toggle between narrow (single-column) and wide (two-column) layout."""
        w = width if width is not None else self.size.width
        narrow = w < 80
        self._narrow = narrow
        try:
            self.query_one("#preview-panel").display = not narrow
            self.query_one("#agent-panel").set_class(narrow, "narrow")
        except Exception:
            pass
        for selector in ("#action-menu", "#new-agent-form", "#quick-launch-form"):
            try:
                self.query_one(selector).set_class(narrow, "narrow")
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
        self._focus_agent_list()
        self._scan_for_orphans()

    def _start_refresh(self) -> None:
        if self._refresh_timer is None:
            self._refresh_timer = self.set_interval(2.0, self._on_refresh)

    def _stop_refresh(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def _focus_agent_list(self) -> None:
        try:
            ol = self.query_one("#agent-option-list", OptionList)
            ol.focus()
            if ol.option_count > 0 and ol.highlighted is None:
                ol.highlighted = 0
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
        state = self.state_mgr.load()
        self._refresh_status_bar(state)
        self._refresh_agent_list(state=state)
        self._refresh_preview()
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

    def _build_row_label(self, agent: AgentInfo, has_responder: bool) -> Text:
        """Render an agent row in the locked Project layout.

        Wide:    ●  [type]   name                              auto
        Narrow:  ●  [type]   name                              auto

        The layout encodes the design's four cells — state dot, vendor type
        chip, bold name, soft auto chip — and nothing else. State is carried
        by the dot's colour alone (the design dropped the state word from the
        row; it lives in the preview header). Typeless agents show a dim
        bracket-free ``polling`` marker in place of the vendor chip.

        Returns a ``rich.text.Text`` so ``str(prompt)`` yields the plain row
        without markup tags — callers can still substring-search for labels
        without false positives from tags like ``[/bold]``.
        """
        state_color = STATE_COLORS.get(agent.state, "white")
        state_dot = f"[{state_color}]●[/{state_color}]"
        indent = "↳ " if agent.is_responder else ""
        type_chip = type_chip_markup(agent.agent_type)
        # Polling placeholder is intentionally bracket-free so it never reads
        # as a vendor ``[type]`` tag (rows assert on the bracket).
        type_disp = type_chip if type_chip else "[dim]polling[/dim]"
        auto_chip = auto_chip_markup(agent.auto_respond, has_responder)
        auto_part = f"  {auto_chip}" if auto_chip else ""
        # Brief state-change cue: a leading ``▴`` for ~3 s after we detect
        # this agent's state changing. The TUI stand-in for the design's
        # animated (FLIP) row reorder — catches the eye without blocking.
        recent = (
            time.monotonic() - self._change_at.get(agent.id, 0.0) < CHANGE_CUE_SECS
        )
        cue = f"[{state_color}]▴[/{state_color}]" if recent else " "

        if self._is_narrow:
            return Text.from_markup(
                f"{cue} {state_dot}  {type_disp}  {indent}[bold]{agent.label}[/bold]{auto_part}"
            )

        # Wide: pad the name so the auto chip lands in a tidy right column.
        name_padded = f"{indent}{agent.label:<24}"
        return Text.from_markup(
            f"{cue} {state_dot}  {type_disp}  [bold]{name_padded}[/bold]{auto_part}"
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

        responders_by_partner = {
            a.partner_id: a for a in state.agents if a.is_responder
        }

        option_list.clear_options()
        for agent in agents:
            label = self._build_row_label(
                agent,
                has_responder=(
                    not agent.is_responder
                    and agent.id in responders_by_partner
                ),
            )
            option_list.add_option(Option(label, id=str(agent.id)))

        if current_highlighted_id is not None:
            for i in range(option_list.option_count):
                opt = option_list.get_option_at_index(i)
                if opt.id == current_highlighted_id:
                    option_list.highlighted = i
                    break

        if option_list.option_count > 0 and option_list.highlighted is None:
            option_list.highlighted = 0

    def _refresh_preview(self) -> None:
        try:
            option_list = self.query_one("#agent-option-list", OptionList)
            preview = self.query_one("#preview-pane", Static)
        except Exception:
            return

        if option_list.highlighted is None or option_list.option_count == 0:
            preview.update("[dim]Select an agent to preview[/dim]")
            return

        option = option_list.get_option_at_index(option_list.highlighted)
        agent_id = int(option.id)
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            preview.update("[dim]Agent not found[/dim]")
            return

        server = self._get_tmux_server()
        content = capture_pane_content(server, agent.tmux_session)
        # Structured responder panel (replaces the old single-line footnote).
        # The panel mines its own reply log from the responder's pane and
        # reads optional rules from disk, so we pass both inputs through.
        responder_pane = None
        if not agent.is_responder:
            resp = next(
                (a for a in state.agents if a.is_responder and a.partner_id == agent.id),
                None,
            )
            if resp is not None:
                responder_pane = capture_pane_content(server, resp.tmux_session)
        auto_meta = Text.from_markup(build_responder_panel(
            agent, state.agents,
            pane_content=responder_pane,
            aque_dir=self.aque_dir,
        ))
        actions = Text.from_markup(self._build_action_strip(agent))
        if content:
            lines = content.split("\n")
            last_lines = lines[-30:]
            color = STATE_COLORS.get(agent.state, "white")
            header = Text.from_markup(
                f"[bold]{agent.label}[/bold]  [{color}]{agent.state.value}[/{color}]"
            )
            if agent.agent_type:
                meta = Text.from_markup(
                    f"\n[dim]Type: {agent.agent_type}  Detection: hook[/dim]"
                )
            else:
                meta = Text.from_markup(
                    "\n[dim]Detection: polling[/dim]"
                )
            body = Text("\n" + "\n".join(last_lines))
            preview.update(header + meta + actions + body + auto_meta)
        else:
            preview.update(
                Text.from_markup(
                    f"[bold]{agent.label}[/bold]\n[dim]No preview available[/dim]"
                )
                + actions
                + auto_meta
            )

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

    def _show_dashboard(self) -> None:
        self._dismiss_triage_widget()
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
        self._refresh_preview()
        self._start_refresh()
        self._focus_agent_list()
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

    def _try_show_triage(self, state: AppState | None = None) -> None:
        """Surface the top waiting agent in a non-blocking triage pill.

        Replaces the old forced-modal countdown. The pill mounts inside the
        dashboard layout and does not steal focus — the user keeps the
        agent list and preview interactive while triaging.

        Snooze semantics: when the user dismisses the pill (Esc or ``s``),
        the agent's id is added to ``_snoozed`` along with its current
        ``last_change_at``. The next call clears that snooze if the agent
        has since changed state, so a fresh waiting transition re-surfaces.
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
            self._dismiss_triage_widget()
            self._triage_agent = None
            return

        top = candidates[0]
        if self._triage_agent is not None and self._triage_agent.id == top.id:
            # Already showing for this agent; nothing to do (we don't yet
            # update queue length live — a future polish if it matters).
            return

        dbg(
            "desk.triage.show",
            self.aque_dir,
            agent_id=top.id,
            label=top.label,
            queue_len=len(candidates),
        )
        self._dismiss_triage_widget()
        self._triage_agent = top
        preview_text = ""
        try:
            preview_text = (
                capture_pane_content(self._get_tmux_server(), top.tmux_session) or ""
            )
        except Exception:
            preview_text = ""
        pill = TriagePill(
            top,
            queue_len=len(candidates),
            preview=preview_text,
            narrow=self._is_narrow,
        )
        try:
            self.query_one("#dashboard").mount(pill)
        except Exception:
            pass

    def _dismiss_triage_widget(self) -> None:
        for w in self.query("#triage-pill"):
            w.remove()

    def _handle_triage_key(self, key: str) -> bool:
        """Route triage-relevant keys when the pill is up. Returns True if
        the key was consumed."""
        if self._triage_agent is None:
            return False
        if not self.query("#triage-pill"):
            return False
        agent = self._triage_agent
        if key == "enter":
            self._dismiss_triage_widget()
            self._triage_agent = None
            self._attach_to_agent(agent)
            return True
        if key == "space":
            self._dismiss_triage_widget()
            self._triage_agent = None
            self._select_agent_in_list(agent.id)
            return True
        if key in ("s", "escape"):
            self._snoozed.add(agent.id)
            self._snoozed_last_change[agent.id] = agent.last_change_at
            self._dismiss_triage_widget()
            self._triage_agent = None
            dbg("desk.triage.snoozed", self.aque_dir, agent_id=agent.id)
            return True
        return False

    def _select_agent_in_list(self, agent_id: int) -> None:
        """Highlight the given agent in the option list without attaching."""
        try:
            ol = self.query_one("#agent-option-list", OptionList)
            for i in range(ol.option_count):
                opt = ol.get_option_at_index(i)
                if opt.id == str(agent_id):
                    ol.highlighted = i
                    break
            self._refresh_preview()
        except Exception:
            pass

    def _show_action_menu(self, agent: AgentInfo, was_exited: bool) -> None:
        self._dismiss_triage_widget()
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
        self._dismiss_triage_widget()
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
        self._dismiss_triage_widget()
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

    def _perform_launch(
        self,
        command: list[str],
        working_dir: str,
        label: str | None,
        agent_type: str | None,
    ) -> int:
        """Launch an agent and run the shared post-launch flow.

        Used by both the new-agent wizard and Quick Launch. Installs the
        agent-type hook if needed, creates a paired responder (when enabled),
        records directory use, ensures the monitor is running, and attaches to
        the new agent (or returns to the dashboard when attach is skipped).
        """
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
        dbg("desk.attach.start", self.aque_dir, agent_id=agent.id, from_state=agent.state.value)
        self._dismiss_triage_widget()
        self._triage_agent = None
        pre_attach_state = agent.state
        was_exited = agent.state == AgentState.EXITED
        pre_attach_hash = self._pane_hash(agent.tmux_session) if agent.agent_type else None
        self.state_mgr.update_agent_state(agent.id, AgentState.FOCUSED)
        self._stop_refresh()

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
        if updated_agent.state in (AgentState.EXITED,):
            self._kill_agent(updated_agent.id)
        elif updated_agent.state == AgentState.FOCUSED:
            # Typed agents rely on hooks; without a content-hash fallback a
            # no-op attach (user looked but didn't interact) would strand the
            # agent in RUNNING forever. If the pane content is unchanged,
            # revert to whatever state it was in before the attach.
            if agent.agent_type and pre_attach_hash is not None:
                post_hash = self._pane_hash(agent.tmux_session)
                if post_hash == pre_attach_hash:
                    dbg(
                        "desk.attach.no_interaction->revert",
                        self.aque_dir,
                        agent_id=agent.id,
                        revert_to=pre_attach_state.value,
                    )
                    self.state_mgr.update_agent_state(updated_agent.id, pre_attach_state)
                    # Snooze the same agent so the triage pill doesn't
                    # immediately re-surface what the user just looked
                    # through without acting on.
                    self._snoozed.add(updated_agent.id)
                    self._snoozed_last_change[updated_agent.id] = (
                        self.state_mgr.load().agents and
                        next(
                            (a.last_change_at for a in self.state_mgr.load().agents if a.id == updated_agent.id),
                            "",
                        )
                    )
                    self._show_dashboard()
                    return
            dbg("desk.attach.focused->running", self.aque_dir, agent_id=agent.id)
            self.state_mgr.update_agent_state(updated_agent.id, AgentState.RUNNING)
        self._show_dashboard()

    def _pane_hash(self, tmux_session: str) -> str | None:
        try:
            content = capture_pane_content(self._get_tmux_server(), tmux_session)
        except Exception:
            return None
        if content is None:
            return None
        return hashlib.md5(content.encode()).hexdigest()

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
        self._attach_to_agent(agent)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self._mode != "dashboard":
            return
        if self._preview_debounce_timer is not None:
            self._preview_debounce_timer.stop()
        self._preview_debounce_timer = self.set_timer(0.15, self._debounced_preview)

    def _debounced_preview(self) -> None:
        self._preview_debounce_timer = None
        self._refresh_preview()

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
            self._focus_agent_list()
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
        if self._mode == "dashboard":
            agent_id = self._get_highlighted_agent_id()
            if agent_id is not None:
                self._kill_agent(agent_id)
                self._refresh_agent_list()
                self._refresh_status_bar()

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
        stop_monitor(self.aque_dir)
        self.exit()

    def on_key(self, event) -> None:
        # Triage pill takes priority — it's the most recent surface and the
        # user is being asked an explicit question.
        if self._mode == "dashboard" and self._triage_agent is not None:
            if self._handle_triage_key(event.key):
                event.stop()
                return

        if self._mode == "dashboard" and event.key == "escape":
            # Esc on the dashboard clears active filter + search, and closes
            # the inline search input if it's open.
            had_search_focus = bool(self.query("#search-input"))
            if had_search_focus or self._filter is not None or self._search:
                self._clear_filters()
                self._focus_agent_list()
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
