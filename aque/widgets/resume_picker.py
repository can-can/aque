"""Modal shown during agent creation when the target dir has prior claude
sessions. Lets the user start fresh or resume one of the existing sessions.

The picker is only invoked when summarize() returns at least one session
(empty list short-circuits to fresh launch at the call site).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from aque.sessions import SessionSummary


@dataclass(frozen=True)
class PickerResult:
    action: Literal["fresh", "resume"]
    session_id: str | None  # set only when action == "resume"


def _humanize_age(when: datetime) -> str:
    delta = datetime.now(timezone.utc) - when
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _humanize_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n // 1024} KB"
    return f"{n // (1024 * 1024)} MB"


class ResumePickerScreen(ModalScreen[PickerResult | None]):
    """List 'Start fresh' + prior sessions; return PickerResult or None on Esc."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ResumePickerScreen {
        align: center middle;
    }
    ResumePickerScreen > VerticalScroll {
        max-width: 90%;
        max-height: 80%;
        background: $panel;
        padding: 1 2;
        border: thick $primary;
    }
    """

    def __init__(self, summaries: list[SessionSummary], cwd: str, agent_type: str):
        super().__init__()
        self._summaries = summaries
        self._cwd = cwd
        self._agent_type = agent_type

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            dir_name = Path(self._cwd).name or self._cwd
            yield Static(f"Create {self._agent_type} agent in {dir_name}",
                         id="resume-picker-title")
            options: list[Option] = [Option("Start fresh (new conversation)", id="fresh")]
            for s in self._summaries:
                age = _humanize_age(s.mtime)
                size = _humanize_size(s.size_bytes)
                first = s.first_prompt or "(empty session)"
                lines = [f"{age} · {size} · \"{first}\""]
                if s.last_activity:
                    lines.append(f"   ↳ last: \"{s.last_activity}\"")
                options.append(Option("\n".join(lines), id=f"resume:{s.uuid}"))
            ol = OptionList(*options, id="resume-picker-list")
            yield ol
            yield Static("[Enter] launch    [Esc] cancel", classes="resume-picker-hint")

    def on_mount(self) -> None:
        ol = self.query_one("#resume-picker-list", OptionList)
        ol.highlighted = 0  # default to "Start fresh"
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = event.option.id or ""
        if opt_id == "fresh":
            self.dismiss(PickerResult(action="fresh", session_id=None))
        elif opt_id.startswith("resume:"):
            self.dismiss(PickerResult(action="resume", session_id=opt_id[len("resume:"):]))

    def action_cancel(self) -> None:
        self.dismiss(None)
