"""TriageModal — a centered, blocking card surfacing a waiting agent.

Replaces the in-flow ``TriageBanner``. The banner docked above the ``1fr``
dashboard, so showing it squeezed the agent list and embedded terminal — the
layout visibly reflowed under the user. This is a ``ModalScreen`` (like the
kill-confirm ``ConfirmModal``): it floats centered over the dashboard, dims and
blocks it, and is dismissed by an explicit action. Because it is a separate
screen, the dashboard's layout is never touched.

Card contents:

  line 1: ● {label} needs you · {dir}      (+ N more waiting, when queued)
  line 2: [ attach ↵ ]  [ peek space ]

Two actions are advertised, plus a silent escape hatch:

  * **Enter** — ``"attach"``: attach to the waiting agent
  * **Space** — ``"peek"``: load the agent into the dashboard preview, no attach
  * **Esc** — silently dismisses + snoozes; the modal won't re-surface until
    the agent transitions state again. Not labelled as a pill — it's just the
    universal "get me out of here" key.

Adapts to narrow terminals (``width < 40``): the ``· {dir}`` title suffix is
hidden and the action pills stack vertically so they never overflow.
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
SNOOZE = "snooze"  # Internal-only now — Esc dismisses with this result.

# Below this width the modal switches to its narrow layout (no dir suffix,
# pills stacked vertically). 40 cells is roughly an iTerm pane split in half
# on a 14" laptop — the smallest realistic interactive width.
_NARROW_THRESHOLD = 40


class TriageModal(ModalScreen[str]):
    """A centered, blocking peek-and-decide card for a waiting agent."""

    BINDINGS = [
        Binding("enter", "attach", "Attach"),
        Binding("space", "peek", "Peek"),
        # Esc is intentionally not advertised in the pill row — it's a silent
        # dismiss-with-snooze so users always have an escape hatch even though
        # the snooze action isn't a first-class affordance anymore.
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
    TriageModal .triage-row1 {
        height: auto;
        margin-bottom: 1;
    }
    TriageModal .triage-title {
        width: 1fr;
    }
    TriageModal .triage-dir {
        width: auto;
        color: $text-muted;
    }
    TriageModal .triage-dir.hidden {
        display: none;
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
    TriageModal .triage-actions.narrow {
        layout: vertical;
        height: auto;
        align-horizontal: left;
    }
    TriageModal .act {
        height: 1;
        padding: 0 1;
        margin-right: 1;
        width: auto;
    }
    TriageModal .triage-actions.narrow .act {
        margin-right: 0;
        margin-bottom: 0;
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
    _SECONDARY = (("peek", "space"),)

    def __init__(self, agent: AgentInfo, queue_len: int = 1) -> None:
        # No fixed id: attaching from one modal surfaces the next agent's modal
        # synchronously, while the just-dismissed screen is still in the App's
        # node registry — a fixed id would collide (DuplicateIds). The app
        # tracks the live modal via ``DeskApp._triage_modal``, not by id.
        super().__init__()
        self.agent = agent
        self.queue_len = queue_len

    def compose(self) -> ComposeResult:
        title = Static(
            f"[bold yellow]●[/bold yellow] "
            f"[bold]{self.agent.label}[/bold] needs you",
            classes="triage-title",
            id="triage-title",
        )
        row1: list[Static] = [title]
        # Dir suffix lives in its own Static so narrow mode can hide it
        # without rebuilding the title's markup.
        if self.agent.dir:
            row1.append(
                Static(
                    f"[dim]· {self.agent.dir}[/dim]",
                    classes="triage-dir",
                    id="triage-dir",
                )
            )
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

    def on_resize(self, event) -> None:
        """Re-evaluate the narrow layout when the screen size changes.

        Narrow mode hides the dir suffix and stacks the action pills
        vertically. ``self.size`` is the screen size (the full terminal) since
        a ModalScreen is sized to fill the screen and centers its contents.
        """
        self._apply_layout(event.size.width)

    def on_mount(self) -> None:
        # First layout pass — ``on_resize`` doesn't fire on the initial mount.
        self._apply_layout(self.size.width)

    def _apply_layout(self, width: int) -> None:
        narrow = width < _NARROW_THRESHOLD
        try:
            self.query_one(".triage-actions").set_class(narrow, "narrow")
        except Exception:
            pass
        try:
            self.query_one("#triage-dir").set_class(narrow, "hidden")
        except Exception:
            pass  # No dir suffix to hide (agent.dir was empty)

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
