"""TriageBanner — a non-blocking, full-width banner surfacing a waiting agent.

Replaces the old right-edge ``TriagePill``. The banner is a normal-flow widget
mounted directly above the dashboard (the status bar and footer keep their
docked edges; the banner takes auto height from the remaining middle region),
so it pushes the dashboard down rather than floating over the preview. It does
**not** push a modal screen, so the agent list and preview remain interactive
while it's up.

Two lines, no inline output peek:

  line 1: ● {label} needs you · {dir}            + N more waiting
  line 2: [ attach ↵ ]  [ peek space ]  [ snooze 5m s ]

The action row renders as filled "pills": an accent-filled primary (attach)
and two subtle-filled secondaries (peek, snooze). Each pill shows its label
followed by an inset key cap (the key that triggers it).

Three explicit actions are wired to keys handled in ``DeskApp.on_key``:

  * **Enter** — attach to the waiting agent
  * **Space** — peek (load the agent's output into the preview pane, no attach)
  * **s** / **Esc** — snooze (the same agent won't re-surface until its state
    changes again)
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from aque.state import AgentInfo


class TriageBanner(Vertical):
    """A full-width peek-and-decide banner for a waiting agent."""

    DEFAULT_CSS = """
    TriageBanner {
        width: 100%;
        height: auto;
        padding: 0 2;
        background: $surface;
        border-left: tall $warning;
    }
    TriageBanner .triage-row1 {
        height: 1;
    }
    TriageBanner .triage-title {
        width: 1fr;
    }
    TriageBanner .triage-stack {
        width: auto;
        color: $text-muted;
    }
    TriageBanner .triage-actions {
        height: 1;
    }
    TriageBanner .act {
        height: 1;
        padding: 0 1;
        margin-right: 1;
        width: auto;
    }
    TriageBanner .act-primary {
        background: $warning;
        color: auto;
        text-style: bold;
    }
    TriageBanner .act-default {
        background: $surface-lighten-1;
        color: $text;
    }
    """

    # Each action pill: (label, key-cap glyph). The cap is the key that fires
    # the action; keys are routed in DeskApp.on_key.
    _PRIMARY = ("attach", "↵")
    _SECONDARY = (("peek", "space"), ("snooze 5m", "s"))

    def __init__(self, agent: AgentInfo, queue_len: int) -> None:
        super().__init__(id="triage-banner")
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
        yield Horizontal(*row1, classes="triage-row1")

        pills = [self._pill(*self._PRIMARY, primary=True)]
        pills += [self._pill(label, cap) for label, cap in self._SECONDARY]
        yield Horizontal(*pills, classes="triage-actions")

    @staticmethod
    def _pill(label: str, cap: str, primary: bool = False) -> Static:
        # Label, then the key cap as an inset chip (a translucent $boost
        # overlay reads as a slightly darker recessed key on either fill).
        variant = "act-primary" if primary else "act-default"
        return Static(
            f"{label} [on $boost] {cap} [/]",
            classes=f"act {variant}",
        )
