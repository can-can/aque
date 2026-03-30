import shlex
import subprocess
from pathlib import Path

import libtmux
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    DirectoryTree,
    Footer,
    Header,
    Input,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option


class FolderTree(DirectoryTree):
    """DirectoryTree that only shows non-hidden directories."""

    def filter_paths(self, paths):
        return [
            p for p in paths
            if p.is_dir() and not p.name.startswith(".")
        ]

from aque.config import load_config
from aque.dir_history import DirHistoryManager
from aque.history import HistoryManager
from aque.monitor import capture_pane_content, start_monitor_daemon, stop_monitor
from aque.run import launch_agent
from aque.state import AgentInfo, AgentState, StateManager
from aque.widgets.dir_picker import DirectoryPicker, key_hint

STATE_COLORS = {
    AgentState.RUNNING: "green",
    AgentState.WAITING: "yellow",
    AgentState.FOCUSED: "blue",
    AgentState.EXITED: "dim",
    AgentState.ON_HOLD: "magenta",
    AgentState.DONE: "red",
}

STATE_PRIORITY = {
    AgentState.WAITING: 0,
    AgentState.EXITED: 1,
    AgentState.RUNNING: 2,
    AgentState.FOCUSED: 3,
    AgentState.ON_HOLD: 4,
    AgentState.DONE: 5,
}


def sorted_agents(agents: list[AgentInfo]) -> list[AgentInfo]:
    return sorted(agents, key=lambda a: (STATE_PRIORITY.get(a.state, 99), a.last_change_at))


# ── Widgets ──────────────────────────────────────────────────────────


class StatusBar(Static):
    def __init__(self, agents: list[AgentInfo], history_count: int) -> None:
        counts: dict[AgentState, int] = {}
        for a in agents:
            counts[a.state] = counts.get(a.state, 0) + 1
        parts = []
        for st, color in [
            (AgentState.RUNNING, "green"),
            (AgentState.WAITING, "yellow"),
            (AgentState.ON_HOLD, "magenta"),
        ]:
            c = counts.get(st, 0)
            if c:
                parts.append(f"[{color}]● {c} {st.value}[/{color}]")
        if history_count:
            parts.append(f"[dim]● {history_count} done[/dim]")
        super().__init__("    ".join(parts) if parts else "[dim]No agents[/dim]", id="status-bar")


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
    def __init__(self, dir_history_mgr: DirHistoryManager, default_dir: str) -> None:
        super().__init__(id="new-agent-form")
        self._step = "dir"
        self._selected_dir: str = ""
        self._command: str = ""
        self._label: str = ""
        self._dir_history_mgr = dir_history_mgr
        self._default_dir = default_dir
        self._tree_mode = False

    def compose(self) -> ComposeResult:
        yield Static("New Agent", id="new-agent-title")
        yield Static("Step 1/3: Select working directory", id="new-agent-step")
        yield DirectoryPicker(
            dir_history_mgr=self._dir_history_mgr,
            default_dir=self._default_dir,
            id="dir-picker",
        )

    def show_command_step(self) -> None:
        self._step = "command"
        self.query_one("#new-agent-step").update(
            f"Step 2/3: Enter command  (dir: {self._selected_dir})"
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
        cmd_name = shlex.split(self._command)[0] if self._command else "agent"
        dir_name = Path(self._selected_dir).name
        default_label = f"{cmd_name} . {dir_name}"
        self._label = default_label
        self.query_one("#new-agent-step").update(
            f"Step 3/3: Label  (dir: {self._selected_dir}, cmd: {self._command})"
        )
        self.query_one("#command-input").remove()
        self.mount(
            Input(value=default_label, placeholder="Agent label", id="label-input"),
            after=self.query_one("#new-agent-step"),
        )
        self.query_one("#new-agent-hint").update(
            "   ".join([key_hint("Enter", "launch"), key_hint("Esc", "back")])
        )
        self.query_one("#label-input").focus()

    def show_dir_step(self) -> None:
        """Go back to directory selection step."""
        self._step = "dir"
        self.query_one("#new-agent-step").update("Step 1/3: Select working directory")
        try:
            self.query_one("#command-input").remove()
        except Exception:
            pass
        try:
            self.query_one("#new-agent-hint").remove()
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


class AutoAttachModal(ModalScreen):
    """Countdown modal for auto-attaching to a waiting agent."""

    DEFAULT_CSS = """
    AutoAttachModal {
        align: center middle;
    }
    #auto-attach-box {
        width: 50;
        height: 7;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
        text-align: center;
    }
    #auto-attach-label {
        width: 100%;
        text-align: center;
    }
    #auto-attach-hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(self, agent_label: str, seconds: int) -> None:
        super().__init__()
        self.agent_label = agent_label
        self.seconds = seconds

    def compose(self) -> ComposeResult:
        box = Vertical(id="auto-attach-box")
        box._add_child(Static(
            f"Attaching to [bold yellow]{self.agent_label}[/] in [bold]{self.seconds}s[/]",
            id="auto-attach-label",
        ))
        box._add_child(Static("[Enter] attach now  [Esc] cancel", id="auto-attach-hint"))
        yield box

    def update_countdown(self, seconds: int) -> None:
        self.seconds = seconds
        try:
            self.query_one("#auto-attach-label", Static).update(
                f"Attaching to [bold yellow]{self.agent_label}[/] in [bold]{seconds}s[/]"
            )
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "enter":
            self.dismiss(True)
        elif event.key == "escape":
            self.dismiss(False)


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
    #dashboard {
        height: 1fr;
    }
    #agent-panel {
        width: 40%;
        border-right: solid $surface-lighten-1;
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
    """

    BINDINGS = [
        ("n", "new_agent", "New Agent"),
        ("k", "kill_agent", "Kill"),
        ("h", "hold_agent", "Hold"),
        ("q", "quit_app", "Quit"),
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
        self._countdown_timer: Timer | None = None
        self._countdown_seconds: int = 0
        self._countdown_agent: AgentInfo | None = None
        self._countdown_modal: AutoAttachModal | None = None
        self._auto_attach_suppressed: bool = False

    def _get_tmux_server(self) -> libtmux.Server:
        if self._tmux_server is None:
            self._tmux_server = libtmux.Server()
        return self._tmux_server

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._make_status_bar()
        yield self._make_dashboard()
        yield Footer()

    def _make_status_bar(self) -> StatusBar:
        state = self.state_mgr.load()
        return StatusBar(state.agents, self.history_mgr.count())

    def _make_dashboard(self) -> Horizontal:
        state = self.state_mgr.load()
        active = [a for a in state.agents if a.state != AgentState.DONE]
        agents = sorted_agents(active)

        options = []
        for agent in agents:
            color = STATE_COLORS.get(agent.state, "white")
            label = (
                f"[{color}]{agent.state.value:<8}[/{color}]  "
                f"{agent.label:<25}  {agent.dir}"
            )
            options.append(Option(label, id=str(agent.id)))

        dashboard = Horizontal(id="dashboard")
        agent_panel = Vertical(id="agent-panel")
        preview_panel = Vertical(id="preview-panel")

        if options:
            agent_panel._add_child(OptionList(*options, id="agent-option-list"))
        else:
            agent_panel._add_child(OptionList(id="agent-option-list"))

        preview_panel._add_child(PreviewPane())
        dashboard._add_child(agent_panel)
        dashboard._add_child(preview_panel)
        return dashboard

    def on_mount(self) -> None:
        self._start_refresh()
        self._focus_agent_list()

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

    def _on_refresh(self) -> None:
        if self._mode not in ("dashboard", "auto_attach"):
            return
        self._refresh_status_bar()
        self._refresh_agent_list()
        self._refresh_preview()
        if self._mode == "dashboard":
            self._try_auto_attach()

    def _refresh_status_bar(self) -> None:
        try:
            old = self.query_one("#status-bar", Static)
            state = self.state_mgr.load()
            counts: dict[AgentState, int] = {}
            for a in state.agents:
                counts[a.state] = counts.get(a.state, 0) + 1
            parts = []
            for st, color in [
                (AgentState.RUNNING, "green"),
                (AgentState.WAITING, "yellow"),
                (AgentState.ON_HOLD, "magenta"),
            ]:
                c = counts.get(st, 0)
                if c:
                    parts.append(f"[{color}]● {c} {st.value}[/{color}]")
            hcount = self.history_mgr.count()
            if hcount:
                parts.append(f"[dim]● {hcount} done[/dim]")
            old.update("    ".join(parts) if parts else "[dim]No agents[/dim]")
        except Exception:
            pass

    def _refresh_agent_list(self, reset_highlight: bool = False) -> None:
        try:
            option_list = self.query_one("#agent-option-list", OptionList)
        except Exception:
            return

        state = self.state_mgr.load()
        active = [a for a in state.agents if a.state != AgentState.DONE]
        agents = sorted_agents(active)

        current_highlighted_id = None
        if not reset_highlight and option_list.highlighted is not None:
            try:
                current_option = option_list.get_option_at_index(option_list.highlighted)
                current_highlighted_id = current_option.id
            except Exception:
                pass

        option_list.clear_options()
        for agent in agents:
            color = STATE_COLORS.get(agent.state, "white")
            label = (
                f"[{color}]{agent.state.value:<8}[/{color}]  "
                f"{agent.label:<25}  {agent.dir}"
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
        if content:
            lines = content.split("\n")
            last_lines = lines[-30:]
            color = STATE_COLORS.get(agent.state, "white")
            preview.update(
                f"[bold]{agent.label}[/bold]  [{color}]{agent.state.value}[/{color}]\n\n"
                + "\n".join(last_lines)
            )
        else:
            preview.update(f"[bold]{agent.label}[/bold]\n[dim]No preview available[/dim]")

    # ── Mode switching ───────────────────────────────────────────

    def _show_dashboard(self) -> None:
        self._cancel_countdown()
        self._mode = "dashboard"
        for w in self.query("ActionMenu, NewAgentForm"):
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
        self._try_auto_attach()

    def _try_auto_attach(self) -> None:
        if self._skip_attach or self._countdown_timer is not None or self._auto_attach_suppressed:
            return
        state = self.state_mgr.load()
        waiting = [a for a in state.agents if a.state == AgentState.WAITING]
        if not waiting:
            return
        top = sorted_agents(waiting)[0]
        self._countdown_agent = top
        self._countdown_seconds = 3
        self._mode = "auto_attach"
        self._countdown_modal = AutoAttachModal(top.label, self._countdown_seconds)
        self.push_screen(self._countdown_modal, self._on_modal_dismiss)
        self._countdown_timer = self.set_interval(1.0, self._countdown_tick)

    def _on_modal_dismiss(self, result: bool | None) -> None:
        if result is True:
            agent = self._countdown_agent
            self._cancel_countdown()
            if agent:
                self._attach_to_agent(agent)
        elif result is False:
            self._auto_attach_suppressed = True
            self._cancel_countdown()

    def _countdown_tick(self) -> None:
        self._countdown_seconds -= 1
        if self._countdown_seconds <= 0:
            agent = self._countdown_agent
            self._cancel_countdown()
            if agent:
                self._attach_to_agent(agent)
            return
        if self._countdown_modal is not None:
            self._countdown_modal.update_countdown(self._countdown_seconds)

    def _cancel_countdown(self) -> None:
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None
        self._countdown_agent = None
        self._countdown_modal = None
        self._countdown_seconds = 0
        try:
            self.pop_screen()
        except Exception:
            pass
        if self._mode == "auto_attach":
            self._mode = "dashboard"

    def _show_action_menu(self, agent: AgentInfo, was_exited: bool) -> None:
        self._auto_attach_suppressed = False
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
        try:
            ol = self.query_one("#action-option-list", OptionList)
            ol.focus()
            if ol.option_count > 0 and ol.highlighted is None:
                ol.highlighted = 0
        except Exception:
            pass

    def _show_new_agent_form(self) -> None:
        self._auto_attach_suppressed = False
        self._mode = "new_agent_form"
        self._stop_refresh()
        try:
            self.query_one("#dashboard").display = False
            self.query_one("#status-bar").display = False
        except Exception:
            pass
        self.mount(
            NewAgentForm(
                dir_history_mgr=self.dir_history_mgr,
                default_dir=self.config.get("default_dir", str(Path.home())),
            ),
            after=self.query_one(Header),
        )

    # ── Agent actions ────────────────────────────────────────────

    def _attach_to_agent(self, agent: AgentInfo) -> None:
        self._auto_attach_suppressed = False
        was_exited = agent.state == AgentState.EXITED
        self.state_mgr.update_agent_state(agent.id, AgentState.FOCUSED)
        self._stop_refresh()

        with self.suspend():
            subprocess.run(["tmux", "attach-session", "-t", agent.tmux_session])

        state = self.state_mgr.load()
        updated_agent = next((a for a in state.agents if a.id == agent.id), agent)
        if updated_agent.state in (AgentState.EXITED,):
            self._kill_agent(updated_agent.id)
        elif updated_agent.state == AgentState.FOCUSED:
            self.state_mgr.update_agent_state(updated_agent.id, AgentState.RUNNING)
        self._show_dashboard()

    def _kill_agent(self, agent_id: int) -> None:
        state = self.state_mgr.load()
        agent = next((a for a in state.agents if a.id == agent_id), None)
        if agent is None:
            return
        try:
            server = self._get_tmux_server()
            session = server.sessions.get(session_name=agent.tmux_session)
            if session:
                session.kill()
        except Exception:
            pass
        self.state_mgr.done_agent(agent_id, self.history_mgr)

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
        state = self.state_mgr.load()
        if state.monitor_pid:
            try:
                os.kill(state.monitor_pid, 0)
                return
            except ProcessLookupError:
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
        if self._mode != "dashboard":
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
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
            command = shlex.split(form._command)
            agent_id = launch_agent(
                command=command,
                working_dir=form._selected_dir,
                label=form._label or None,
                state_manager=self.state_mgr,
                prefix=self.config["session_prefix"],
            )
            self.dir_history_mgr.record_use(form._selected_dir)
            self._ensure_monitor_running()
            for w in self.query("NewAgentForm"):
                w.remove()
            state = self.state_mgr.load()
            agent = next((a for a in state.agents if a.id == agent_id), None)
            if agent and not self._skip_attach:
                self._attach_to_agent(agent)
            else:
                self._show_dashboard()

    # ── Key handling ─────────────────────────────────────────────

    def action_new_agent(self) -> None:
        if self._mode == "dashboard":
            self._show_new_agent_form()

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

    def action_quit_app(self) -> None:
        stop_monitor(self.aque_dir)
        self.exit()

    def on_key(self, event) -> None:
        if self._mode == "new_agent_form":
            form = self.query_one(NewAgentForm)

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
                # Step "dir" — cancel the form
                for w in self.query("NewAgentForm"):
                    w.remove()
                self._show_dashboard()
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
