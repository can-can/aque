"""TriagePill — a non-blocking notification surfacing a waiting agent.

Replaces the old forced ``AutoAttachModal``. The pill mounts inside the
dashboard layout (right side on wide, bottom on narrow) and does **not**
push a modal screen, so the agent list and preview remain interactive while
it's up. Three explicit actions are wired to keys handled in
``DeskApp.on_key``:

  * **Enter** — attach to the waiting agent
  * **Space** — peek (preview only, no attach)
  * **s** / **Esc** — snooze (the same agent won't re-surface until its
    state changes again)
"""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from aque.state import AgentInfo


class TriagePill(Vertical):
    """A peek-and-decide notification for a waiting agent."""

    DEFAULT_CSS = """
    TriagePill {
        dock: right;
        width: 38;
        height: auto;
        padding: 1 2;
        margin: 1 2;
        background: $surface;
        border: tall $warning;
        layer: notification;
    }
    TriagePill.narrow {
        dock: bottom;
        width: 100%;
        margin: 0;
        padding: 1 2;
        border: tall $warning;
    }
    TriagePill .triage-title {
        text-style: bold;
        color: $warning;
    }
    TriagePill .triage-sub {
        color: $text-muted;
    }
    TriagePill .triage-peek {
        background: $surface-lighten-1;
        margin: 1 0;
        padding: 0 1;
        max-height: 5;
    }
    TriagePill .triage-actions {
        color: $text;
        margin-top: 1;
    }
    TriagePill .triage-stack {
        color: $text-muted;
    }
    """

    def __init__(self, agent: AgentInfo, queue_len: int, preview: str, narrow: bool = False) -> None:
        super().__init__(id="triage-pill")
        self.agent = agent
        self.queue_len = queue_len
        self.preview_text = preview or "(no output yet)"
        if narrow:
            self.add_class("narrow")

    def compose(self) -> ComposeResult:
        yield Static(
            f"● [bold yellow]{self.agent.label}[/bold yellow] needs you",
            classes="triage-title",
            id="triage-title",
        )
        sub = (
            f"waiting · {self.agent.dir}"
            if self.agent.dir
            else "waiting"
        )
        yield Static(f"[dim]{sub}[/dim]", classes="triage-sub")

        peek_lines = "\n".join(self.preview_text.splitlines()[:4])
        yield Static(peek_lines, classes="triage-peek")

        yield Static(
            "[bold]Enter[/bold] attach   "
            "[bold]Space[/bold] peek   "
            "[bold]s[/bold] snooze",
            classes="triage-actions",
        )

        if self.queue_len > 1:
            yield Static(
                f"[dim]+ {self.queue_len - 1} more waiting[/dim]",
                classes="triage-stack",
            )
