"""CommandPalette — fuzzy-search across agents and actions.

Mounted as a modal screen via ``DeskApp.action_command_palette``. The user
types into a small input; the list updates live. Enter triggers the
selected item, Esc closes. Returns the chosen ``CommandItem`` to the
caller via ``dismiss(result)``.

Each item carries a ``kind`` ('attach' / 'peek' / 'action') and a
``payload`` (the agent id for attach/peek, or an action string for
actions like ``new``, ``help``, ``responders``, ``filter:waiting``).
"""
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from aque.state import AgentInfo


@dataclass(frozen=True)
class CommandItem:
    label: str           # what the user sees
    kind: str            # "attach" | "peek" | "action"
    payload: object      # int agent_id or str action key


class CommandPalette(ModalScreen[CommandItem | None]):
    """Modal fuzzy-finder over agents and global actions."""

    DEFAULT_CSS = """
    CommandPalette {
        align: center top;
    }
    CommandPalette #cmdk-box {
        width: 60;
        max-width: 90%;
        height: auto;
        background: $surface;
        border: round $primary;
        padding: 1 1 0 1;
        margin: 4 0 0 0;
    }
    CommandPalette #cmdk-input {
        border: blank;
        background: $surface;
    }
    CommandPalette #cmdk-list {
        max-height: 18;
        border: blank;
        background: $surface;
    }
    CommandPalette #cmdk-count {
        color: $text-muted;
        text-align: right;
        height: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, agents: list[AgentInfo]) -> None:
        super().__init__()
        # Exclude responders from the fuzzy-finder; they're addressable via
        # the parent agent's responder panel and clutter the result list.
        self._agents = [a for a in agents if not a.is_responder]

    def compose(self) -> ComposeResult:
        box = Vertical(id="cmdk-box")
        box._add_child(Input(placeholder="Search agents and commands…", id="cmdk-input"))
        box._add_child(OptionList(id="cmdk-list"))
        box._add_child(Static("", id="cmdk-count"))
        yield box

    def on_mount(self) -> None:
        self._rebuild_items(query="")
        self.query_one("#cmdk-input", Input).focus()

    def _all_items(self) -> list[CommandItem]:
        items: list[CommandItem] = []
        for a in self._agents:
            items.append(CommandItem(
                label=f"Attach {a.label}  [{a.state.value}]",
                kind="attach", payload=a.id,
            ))
            items.append(CommandItem(
                label=f"Peek {a.label}",
                kind="peek", payload=a.id,
            ))
        items.extend([
            CommandItem("New agent…", "action", "new"),
            CommandItem("Toggle responders", "action", "responders"),
            CommandItem("Show shortcuts (?)", "action", "help"),
            CommandItem("Filter: waiting", "action", "filter:waiting"),
            CommandItem("Filter: running", "action", "filter:running"),
            CommandItem("Filter: on_hold", "action", "filter:on_hold"),
            CommandItem("Filter: exited", "action", "filter:exited"),
            CommandItem("Clear filter", "action", "filter:none"),
        ])
        return items

    @staticmethod
    def _group_of(item: CommandItem) -> str:
        return "agents" if item.kind in ("attach", "peek") else "actions"

    def _rebuild_items(self, query: str) -> None:
        q = query.lower().strip()
        items = self._all_items()
        if q:
            items = [it for it in items if q in it.label.lower()]
        self._items = items  # remember for selection (index = option id)
        ol = self.query_one("#cmdk-list", OptionList)
        ol.clear_options()
        # Render with a dim, non-selectable header before each group. Real
        # items keep ``id == str(index into self._items)`` so selection maps
        # back regardless of where headers land.
        last_group = None
        first_enabled_pos: int | None = None
        pos = 0
        for i, it in enumerate(items):
            group = self._group_of(it)
            if group != last_group:
                ol.add_option(Option(f"[dim]{group}[/dim]", disabled=True))
                pos += 1
                last_group = group
            ol.add_option(Option(it.label, id=str(i)))
            if first_enabled_pos is None:
                first_enabled_pos = pos
            pos += 1
        if first_enabled_pos is not None:
            ol.highlighted = first_enabled_pos
        try:
            count = self.query_one("#cmdk-count", Static)
            n = len(items)
            count.update(f"[dim]{n} result{'' if n == 1 else 's'}[/dim]")
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "cmdk-input":
            self._rebuild_items(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "cmdk-input":
            self._select_current()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._select_current()

    def _select_current(self) -> None:
        ol = self.query_one("#cmdk-list", OptionList)
        if ol.option_count == 0 or ol.highlighted is None:
            return
        option = ol.get_option_at_index(ol.highlighted)
        if option.id is None:  # a group header — not selectable
            return
        idx = int(option.id)
        try:
            self.dismiss(self._items[idx])
        except Exception:
            pass

    def on_key(self, event) -> None:
        # Forward up/down from the input to the option list so the user
        # never has to leave the search field.
        focused = self.focused
        if focused and getattr(focused, "id", None) == "cmdk-input":
            if event.key in ("down", "up"):
                ol = self.query_one("#cmdk-list", OptionList)
                if ol.option_count == 0:
                    return
                step = 1 if event.key == "down" else -1
                cur = ol.highlighted if ol.highlighted is not None else -step
                idx = cur + step
                # Skip non-selectable group headers (id is None).
                while 0 <= idx < ol.option_count and ol.get_option_at_index(idx).id is None:
                    idx += step
                if 0 <= idx < ol.option_count:
                    ol.highlighted = idx
                event.stop()
