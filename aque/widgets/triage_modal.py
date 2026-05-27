"""TriageModal — a centered, blocking card surfacing a waiting agent.

Replaces the in-flow ``TriageBanner``. The banner docked above the ``1fr``
dashboard, so showing it squeezed the list — the layout visibly reflowed
under the user. This is a ``ModalScreen`` (like the kill-confirm
``ConfirmModal``): it floats centered over the dashboard, dims and blocks
it, and is dismissed by an explicit action. Because it is a separate
screen, the dashboard's layout is never touched.

Card contents:

  ● {label} needs you
  [ attach ↵ ]

One action is advertised plus a silent escape hatch:

  * **Enter** — ``"attach"``: full-screen attach to the waiting agent
  * **Esc** — silently dismisses + snoozes; the modal won't re-surface
    until the agent transitions state again.

The peek action (load the agent into the dashboard preview without
attaching) was removed alongside the embedded terminal — there's no
preview surface to load into anymore.
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from aque.state import AgentInfo

# Result values handed back through ``dismiss``.
ATTACH = "attach"
SNOOZE = "snooze"  # Internal-only — Esc dismisses with this result.


class TriageModal(ModalScreen[str]):
    """A centered, blocking single-action card for a waiting agent."""

    BINDINGS = [
        Binding("enter", "attach", "Attach"),
        # Esc is intentionally not advertised in the pill row — it's a silent
        # dismiss-with-snooze so users always have an escape hatch even though
        # the snooze action isn't a first-class affordance.
        Binding("escape", "snooze", "Dismiss", show=False),
    ]

    DEFAULT_CSS = """
    TriageModal {
        align: center middle;
    }
    TriageModal #triage-box {
        width: auto;
        max-width: 56;
        height: auto;
        background: $panel;
        border: thick $warning;
        padding: 1 2;
    }
    TriageModal .triage-title {
        width: auto;
        margin-bottom: 1;
    }
    TriageModal .triage-actions {
        height: 1;
        align-horizontal: center;
    }
    TriageModal .act {
        height: 1;
        padding: 0 1;
        width: auto;
    }
    TriageModal .act-primary {
        background: $warning;
        color: auto;
        text-style: bold;
    }
    """

    # The single advertised action's (label, key-cap) tuple.
    _PRIMARY = ("attach", "↵")

    def __init__(self, agent: AgentInfo, queue_len: int = 1) -> None:
        # No fixed id: attaching from one modal surfaces the next agent's modal
        # synchronously, while the just-dismissed screen is still in the App's
        # node registry — a fixed id would collide (DuplicateIds). The app
        # tracks the live modal via ``DeskApp._triage_modal``, not by id.
        super().__init__()
        self.agent = agent
        # queue_len is accepted for backwards compatibility with the caller
        # signature; the strip removed the "+ N more waiting" indicator.
        self.queue_len = queue_len

    def compose(self) -> ComposeResult:
        title = Static(
            f"[bold yellow]●[/bold yellow] "
            f"[bold]{self.agent.label}[/bold] needs you",
            classes="triage-title",
            id="triage-title",
        )
        pill = self._pill(*self._PRIMARY, primary=True)
        with Vertical(id="triage-box"):
            yield title
            yield Horizontal(pill, classes="triage-actions")

    @staticmethod
    def _pill(label: str, cap: str, primary: bool = False) -> Static:
        variant = "act-primary" if primary else "act-default"
        return Static(
            f"{label} [on $boost] {cap} [/]",
            classes=f"act {variant}",
        )

    def action_attach(self) -> None:
        self.dismiss(ATTACH)

    def action_snooze(self) -> None:
        self.dismiss(SNOOZE)
