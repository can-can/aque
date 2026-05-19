"""Modal shown on `aque desk` startup when state.json has agents whose
tmux sessions no longer exist (typically after a machine reboot).

Each orphan row offers four actions: Resume, Relaunch, Mark exited, Forget.
Resume is disabled when the orphan has no captured session_id or its
agent_type has no registered capturer.
"""

from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from aque.orphans import OrphanedAgent

Action = str  # one of: "resume", "relaunch", "mark_exited", "forget"
ActionCallback = Callable[[Action, int], None]


class OrphanModal(ModalScreen):
    """List orphan agents with per-agent action buttons.

    Pass a callback that takes (action_name, agent_id). The modal calls
    `on_action(action, agent_id)`, removes the row, and dismisses itself
    when the list empties. Esc dismisses without action.
    """

    BINDINGS = [Binding("escape", "dismiss_modal", "Dismiss")]

    DEFAULT_CSS = """
    OrphanModal {
        align: center middle;
    }
    OrphanModal > VerticalScroll {
        max-width: 90%;
        max-height: 80%;
        background: $panel;
        padding: 1 2;
        border: thick $primary;
    }
    OrphanModal .orphan-row {
        height: auto;
        padding: 1 0;
    }
    OrphanModal .orphan-meta {
        color: $text-muted;
    }
    OrphanModal Button {
        margin-right: 1;
    }
    """

    def __init__(self, orphans: list[OrphanedAgent], on_action: ActionCallback):
        super().__init__()
        self._orphans: dict[int, OrphanedAgent] = {o.agent.id: o for o in orphans}
        self._on_action = on_action

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(f"Found {len(self._orphans)} orphaned agents", id="orphan-title")
            for orphan in self._orphans.values():
                yield from self._compose_row(orphan)

    def _compose_row(self, orphan: OrphanedAgent) -> ComposeResult:
        a = orphan.agent
        meta = f"[{a.id}] {a.label} · {a.dir} · {a.agent_type or '-'} · {a.state.value}"
        yield Static(meta, classes="orphan-meta", id=f"orphan-meta-{a.id}")
        with Horizontal(id=f"orphan-row-{a.id}", classes="orphan-row"):
            yield Button(
                "Resume", id=f"resume-{a.id}",
                disabled=not orphan.resumable,
            )
            yield Button("Relaunch", id=f"relaunch-{a.id}")
            yield Button("Mark exited", id=f"mark_exited-{a.id}")
            yield Button("Forget", id=f"forget-{a.id}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id is None:
            return
        try:
            agent_id = int(event.button.id.rsplit("-", 1)[1])
            action_name = event.button.id.rsplit("-", 1)[0]
        except (ValueError, IndexError):
            return
        self.handle_action(action_name, agent_id)

    def handle_action(self, action: Action, agent_id: int) -> None:
        if agent_id not in self._orphans:
            return
        self._on_action(action, agent_id)
        del self._orphans[agent_id]
        try:
            self.query_one(f"#orphan-row-{agent_id}").remove()
            self.query_one(f"#orphan-meta-{agent_id}").remove()
        except Exception:
            pass
        if not self._orphans:
            self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()

    # Test helpers ----------
    def remaining_orphans(self) -> list[OrphanedAgent]:
        return list(self._orphans.values())

    def is_resume_disabled(self, agent_id: int) -> bool:
        try:
            return self.query_one(f"#resume-{agent_id}", Button).disabled
        except Exception:
            return True
