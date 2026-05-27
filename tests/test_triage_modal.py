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
async def test_attach_does_not_immediately_resurface_same_agent(tmp_aque_dir):
    # Live bug: attach to a waiting agent that stays waiting (it's idle waiting
    # for input, so attaching doesn't move it to running); on detach the modal
    # re-popped for the same agent over and over until Esc was used. Attaching
    # must acknowledge the agent so it doesn't instantly re-nag — it re-surfaces
    # only when its state changes again.
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "ios")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        attached: list[str] = []

        def _fake_attach(agent):
            # Detach returns to the dashboard with the agent still waiting.
            attached.append(agent.label)
            app._show_dashboard()

        app._attach_to_agent = _fake_attach
        await pilot.press("enter")
        await pilot.pause()
        assert attached == ["ios"]
        assert not isinstance(app.screen, TriageModal)


@pytest.mark.asyncio
async def test_triage_suppressed_while_search_focused(tmp_aque_dir):
    """The triage modal must not pop while the user is typing in the search
    input (or any non-list focus). It re-surfaces when focus returns to the
    agent list."""
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        app.action_focus_search()
        await pilot.pause()
        search = app.query_one("#search-input")
        assert app.focused is search
        app._on_refresh()
        await pilot.pause()
        assert not isinstance(app.screen, TriageModal)
        # Focus the list again — modal surfaces.
        app._focus_dashboard()
        await pilot.pause()
        app._on_refresh()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)


@pytest.mark.asyncio
async def test_triage_only_surfaces_when_list_has_focus(tmp_aque_dir, monkeypatch):
    """Regression: the triage queue must stay quiet while any non-list widget
    holds focus (search input, modals, etc.). The dashboard agent list is the
    one focus state that allows the modal to surface."""
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "waiter")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        # Move focus off the list onto the search input.
        app.action_focus_search()
        await pilot.pause()
        app._skip_attach = False
        # Multiple poll cycles with search focused must NOT surface the modal.
        for _ in range(5):
            app._on_refresh()
            await pilot.pause()
            assert not isinstance(app.screen, TriageModal), \
                "Modal must not pop while non-list widget has focus"
        # Returning focus to the list surfaces the queued agent.
        ol = app.query_one("#agent-option-list")
        ol.focus()
        await pilot.pause()
        app._on_refresh()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)


@pytest.mark.asyncio
async def test_modal_has_only_attach_pill(tmp_aque_dir):
    """After the triage strip the modal advertises a single action: attach.
    Peek is gone (no preview surface), snooze was never a pill, dismissal
    is via the silent Esc binding."""
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        pills = [str(w.render()) for w in app.screen.query(".act")]
        assert len(pills) == 1, f"Expected single pill, got: {pills}"
        joined = pills[0].lower()
        assert "attach" in joined
        assert "peek" not in joined
        assert "snooze" not in joined


@pytest.mark.asyncio
async def test_escape_still_dismisses_with_snooze(tmp_aque_dir):
    """Esc is no longer an advertised action but must still close the modal
    AND mark the agent as snoozed (so it doesn't immediately re-pop on the
    next refresh)."""
    mgr = StateManager(tmp_aque_dir)
    aid = _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TriageModal)
        assert aid in app.dash.snoozed
