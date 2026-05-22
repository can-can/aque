"""Triage surfaces as a centered modal screen, not an in-flow banner.

The in-flow ``TriageBanner`` was docked above the ``1fr`` dashboard, so showing
it squeezed the agent list and embedded terminal (the layout visibly reflowed
under the user). It is replaced by a centered ``TriageModal`` (a ``ModalScreen``
like the kill-confirm dialog) that floats over the dashboard without touching
its layout. Two behavioural rules are pinned here:

  * surfacing never reflows the dashboard (the modal is a separate screen), and
  * the modal is suppressed while the embedded terminal has focus, so a
    notification can't steal keystrokes mid-command — it waits until focus
    returns to the dashboard.
"""
import pytest

from aque.desk import DeskApp
from aque.state import AgentInfo, AgentState, StateManager
from aque.widgets.triage_modal import TriageModal


@pytest.fixture(autouse=True)
def _no_orphan_scan(monkeypatch):
    # The synthetic agents below have no real tmux sessions, so the startup
    # orphan scan (which needs a live tmux server) would push an OrphanModal
    # over the dashboard. Stub it out — orphan handling is tested elsewhere.
    monkeypatch.setattr(DeskApp, "_scan_for_orphans", lambda self: None)


def _add_waiting(mgr: StateManager, label: str) -> int:
    aid = mgr.next_id()
    mgr.add_agent(AgentInfo(
        id=aid, tmux_session=f"aque-test-{aid}", label=label,
        dir="/tmp/test", command=["test"], state=AgentState.WAITING,
        pid=10000 + aid,
    ))
    return aid


@pytest.mark.asyncio
async def test_triage_surfaces_as_modal_not_inflow_banner(tmp_aque_dir):
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        # No in-flow banner left to squeeze the dashboard.
        assert not app.query("#triage-banner")


@pytest.mark.asyncio
async def test_triage_modal_does_not_reflow_dashboard(tmp_aque_dir):
    mgr = StateManager(tmp_aque_dir)
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        baseline = app.query_one("#dashboard").size.height
        _add_waiting(mgr, "fixer")
        app._on_refresh()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        # The modal is a separate screen, so the dashboard underneath keeps its
        # full height — no squeeze.
        assert app.query_one("#dashboard").size.height == baseline


@pytest.mark.asyncio
async def test_attach_then_next_agent_surfaces_without_duplicate_id(tmp_aque_dir):
    # Attaching from the modal runs the dismiss callback, which (via
    # _attach_to_agent -> _show_dashboard -> _try_show_triage) surfaces the next
    # waiting agent *synchronously while the just-dismissed modal is still in the
    # App's node registry*. If the modal carried a fixed widget id, the second
    # push would raise DuplicateIds. Each push must use a fresh id.
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "first")
    _add_waiting(mgr, "second")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        # Mimic the real attach flow: it returns to the dashboard on detach,
        # which re-evaluates the queue and surfaces the next agent.
        attached: list[str] = []

        def _fake_attach(agent):
            attached.append(agent.label)
            # A real attach leaves the agent no longer waiting (the user has
            # engaged with it); the monitor moves it to running.
            mgr.update_agent_state(agent.id, AgentState.RUNNING)
            app._show_dashboard()

        app._attach_to_agent = _fake_attach
        await pilot.press("enter")
        await pilot.pause()
        # Attached to one agent and the other surfaced — no DuplicateIds crash.
        assert len(attached) == 1
        assert isinstance(app.screen, TriageModal)
        assert app.screen.agent.label != attached[0]


@pytest.mark.asyncio
async def test_triage_suppressed_while_embed_focused(tmp_aque_dir):
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        # Typing in the embed: a notification must not pop and grab the keyboard.
        term = app.query_one("#embedded-terminal")
        app.set_focus(term)
        await pilot.pause()
        app._on_refresh()
        await pilot.pause()
        assert not isinstance(app.screen, TriageModal)
        # Once focus returns to the dashboard, it surfaces.
        app._focus_dashboard()
        await pilot.pause()
        app._on_refresh()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
