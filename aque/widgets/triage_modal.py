"""TriageModal — a centered, blocking card surfacing a waiting agent.

Replaces the in-flow ``TriageBanner``. The banner docked above the ``1fr``
dashboard, so showing it squeezed the agent list and embedded terminal — the
layout visibly reflowed under the user. This is a ``ModalScreen`` (like the
kill-confirm ``ConfirmModal``): it floats centered over the dashboard, dims and
blocks it, and is dismissed by an explicit action. Because it is a separate
screen, the dashboard's layout is never touched.

Card contents (matching the old banner):

  line 1: ● {label} needs you · {dir}      (+ N more waiting, when queued)
  line 2: [ attach ↵ ]  [ peek space ]  [ snooze 5m s ]

Three actions resolve the modal via ``dismiss(result)``:

  * **Enter** — ``"attach"``: attach to the waiting agent
  * **Space** — ``"peek"``: load the agent into the dashboard preview, no attach
  * **s** / **Esc** — ``"snooze"``: don't re-surface until its state changes
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from aque.state import AgentInfo

# Result values handed back through ``dismiss``.
ATTACH = "attach"
PEEK = "peek"
SNOOZE = "snooze"


class TriageModal(ModalScreen[str]):
    """A centered, blocking peek-and-decide card for a waiting agent."""

    BINDINGS = [
        Binding("enter", "attach", "Attach"),
        Binding("space", "peek", "Peek"),
        Binding("s", "snooze", "Snooze"),
        Binding("escape", "snooze", "Snooze"),
    ]

    DEFAULT_CSS = """
    TriageModal {
        align: center middle;
    }
    TriageModal #triage-box {
        width: auto;
        max-width: 70;
        height: auto;
        background: $panel;
        border: thick $warning;
        padding: 1 2;
    }
    TriageModal .triage-row1 {
        height: 1;
        margin-bottom: 1;
    }
    TriageModal .triage-title {
        width: 1fr;
    }
    TriageModal .triage-stack {
        width: auto;
        color: $text-muted;
        margin-left: 2;
    }
    TriageModal .triage-actions {
        height: 1;
        align-horizontal: center;
    }
    TriageModal .act {
        height: 1;
        padding: 0 1;
        margin-right: 1;
        width: auto;
    }
    TriageModal .act-primary {
        background: $warning;
        color: auto;
        text-style: bold;
    }
    TriageModal .act-default {
        background: $surface-lighten-1;
        color: $text;
    }
    """

    # Each action pill: (label, key-cap glyph). The cap is the key that fires
    # the action; keys are routed by this screen's BINDINGS.
    _PRIMARY = ("attach", "↵")
    _SECONDARY = (("peek", "space"), ("snooze 5m", "s"))

    def __init__(self, agent: AgentInfo, queue_len: int = 1) -> None:
        # No fixed id: attaching from one modal surfaces the next agent's modal
        # synchronously, while the just-dismissed screen is still in the App's
        # node registry — a fixed id would collide (DuplicateIds). The app
        # tracks the live modal via ``DeskApp._triage_modal``, not by id.
        super().__init__()
        self.agent = agent
        self.queue_len = queue_len

    def compose(self) -> ComposeResult:
        sub = f" [dim]· {self.agent.dir}[/dim]" if self.agent.dir else ""
        title = Static(
            f"[bold yellow]●[/bold yellow] "
            f"[bold]{self.agent.label}[/bold] needs you{sub}",
            classes="triage-title",
            id="triage-title",
        )
        row1: list[Static] = [title]
        if self.queue_len > 1:
            row1.append(
                Static(
                    f"+ {self.queue_len - 1} more waiting",
                    classes="triage-stack",
                )
            )

        pills = [self._pill(*self._PRIMARY, primary=True)]
        pills += [self._pill(label, cap) for label, cap in self._SECONDARY]

        with Vertical(id="triage-box"):
            yield Horizontal(*row1, classes="triage-row1")
            yield Horizontal(*pills, classes="triage-actions")

    @staticmethod
    def _pill(label: str, cap: str, primary: bool = False) -> Static:
        # Label, then the key cap as an inset chip (a translucent $boost overlay
        # reads as a slightly darker recessed key on either fill).
        variant = "act-primary" if primary else "act-default"
        return Static(
            f"{label} [on $boost] {cap} [/]",
            classes=f"act {variant}",
        )

    def action_attach(self) -> None:
        self.dismiss(ATTACH)

    def action_peek(self) -> None:
        self.dismiss(PEEK)

    def action_snooze(self) -> None:
        self.dismiss(SNOOZE)
