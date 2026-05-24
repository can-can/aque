from datetime import datetime, timedelta, timezone

import pytest
from textual.app import App, ComposeResult

from aque.sessions import SessionSummary
from aque.widgets.resume_picker import PickerResult, ResumePickerScreen


def _summary(uuid: str, age_days: int = 1, first: str | None = "hello", last: str | None = "world") -> SessionSummary:
    return SessionSummary(
        uuid=uuid,
        first_prompt=first,
        last_activity=last,
        mtime=datetime.now(timezone.utc) - timedelta(days=age_days),
        size_bytes=1024,
    )


@pytest.mark.asyncio
async def test_picker_default_selection_is_start_fresh():
    received: list[PickerResult | None] = []

    class _App(App):
        def on_mount(self) -> None:
            self.push_screen(
                ResumePickerScreen([_summary("aaaa")], "/tmp/x", "claude"),
                callback=received.append,
            )

    app = _App()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert received == [PickerResult(action="fresh", session_id=None)]


@pytest.mark.asyncio
async def test_picker_resume_returns_selected_uuid():
    received: list[PickerResult | None] = []

    class _App(App):
        def on_mount(self) -> None:
            self.push_screen(
                ResumePickerScreen([_summary("aaaa"), _summary("bbbb", age_days=2)],
                                   "/tmp/x", "claude"),
                callback=received.append,
            )

    app = _App()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Down arrow once selects the first prior session (aaaa).
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
    assert received == [PickerResult(action="resume", session_id="aaaa")]


@pytest.mark.asyncio
async def test_picker_escape_dismisses_with_none():
    received: list[PickerResult | None] = []

    class _App(App):
        def on_mount(self) -> None:
            self.push_screen(
                ResumePickerScreen([_summary("aaaa")], "/tmp/x", "claude"),
                callback=received.append,
            )

    app = _App()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert received == [None]
