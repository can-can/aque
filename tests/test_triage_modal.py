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


@pytest.mark.asyncio
async def test_triage_only_surfaces_when_list_has_focus(tmp_aque_dir, monkeypatch):
    """Live bug: pressing Enter on a row pops into the embed (term.focus()), but
    the triage modal could still surface on the 2s poll, stealing focus mid-task.
    The guard checks the list holds focus — not merely that the embed doesn't —
    so any non-list focus (search box, no focus, etc.) keeps the queue quiet."""
    from aque.terminal.widget import TerminalView
    mgr = StateManager(tmp_aque_dir)
    # A RUNNING row plus a WAITING one — Enter on the RUNNING row focuses the
    # embed; the WAITING row must NOT then pop the modal out from under us.
    mgr.add_agent(AgentInfo(
        id=mgr.next_id(), tmux_session="aque-test-r", label="runner",
        dir="/tmp/test", command=["test"], state=AgentState.RUNNING, pid=1000,
    ))
    _add_waiting(mgr, "waiter")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        term = app.query_one("#embedded-terminal", TerminalView)
        monkeypatch.setattr(term, "attach", lambda argv, size_sync=None: None)
        app._skip_attach = False  # let Enter focus the embed
        ol = app.query_one("#agent-option-list")
        ol.focus()
        ol.highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert app.focused is term, "Enter should focus the embed"
        # Multiple poll cycles must not surface the modal while the embed is
        # focused — the user is mid-task typing to the agent.
        for _ in range(5):
            app._on_refresh()
            await pilot.pause()
            assert not isinstance(app.screen, TriageModal), \
                "Modal must not pop while embed has focus"
        # Returning to the list surfaces the queued WAITING agent.
        ol.focus()
        await pilot.pause()
        app._on_refresh()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)


@pytest.mark.asyncio
async def test_modal_has_no_snooze_pill(tmp_aque_dir):
    # The "snooze 5m / s" pill was removed; only attach + peek are
    # advertised. Esc still dismisses (silently snoozing) but isn't a pill.
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        pills = [str(w.render()) for w in app.screen.query(".act")]
        joined = " ".join(pills).lower()
        assert "snooze" not in joined
        assert any("attach" in p.lower() for p in pills)
        assert any("peek" in p.lower() for p in pills)


@pytest.mark.asyncio
async def test_escape_still_dismisses_with_snooze(tmp_aque_dir):
    # Esc is no longer an advertised action but must still close the modal
    # AND mark the agent as snoozed (so it doesn't immediately re-pop on
    # the next refresh).
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


@pytest.mark.asyncio
async def test_modal_adapts_to_narrow_screen(tmp_aque_dir):
    # On a narrow terminal the dir suffix is hidden and the action row
    # stacks vertically — so the pills never overflow the modal box.
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(30, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        actions = app.screen.query_one(".triage-actions")
        assert "narrow" in actions.classes
        dir_widget = app.screen.query_one("#triage-dir")
        assert "hidden" in dir_widget.classes


@pytest.mark.asyncio
async def test_modal_keeps_horizontal_layout_on_wide_screen(tmp_aque_dir):
    # The narrow mode must NOT fire on comfortable widths — the pills row
    # stays horizontal and the dir suffix stays visible.
    mgr = StateManager(tmp_aque_dir)
    _add_waiting(mgr, "fixer")
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(120, 30)) as pilot:
        app._show_dashboard()
        await pilot.pause()
        assert isinstance(app.screen, TriageModal)
        actions = app.screen.query_one(".triage-actions")
        assert "narrow" not in actions.classes
        dir_widget = app.screen.query_one("#triage-dir")
        assert "hidden" not in dir_widget.classes
