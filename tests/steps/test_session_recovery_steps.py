"""BDD integration tests for session recovery via a real DeskApp pilot.

Unlike the previous incarnation of this file, these tests construct a real
DeskApp with _skip_attach=False so on_mount's orphan scan actually runs.
libtmux.Server, relaunch_agent, and the responder helpers are monkeypatched
to recorders so we exercise the real on_mount -> _scan_for_orphans -> modal
-> button click -> _handle_orphan_action path without touching tmux.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from pytest_bdd import scenario, given, when, then, parsers
from unittest.mock import patch

from aque import desk as desk_module
from aque import responder as responder_module
from aque.desk import DeskApp
from aque.state import AgentInfo, AgentState, StateManager
from aque.widgets.orphan_modal import OrphanModal

from textual.widgets import Button, Static


FEATURE = "../../features/session_recovery.feature"


# ── Scenario declarations ─────────────────────────────────────────


@scenario(FEATURE, "Orphan modal appears on startup")
def test_orphan_modal_appears_on_startup():
    pass


@scenario(FEATURE, "Forget removes the orphan from state.json")
def test_forget_removes_orphan_from_state():
    pass


@scenario(FEATURE, "Mark exited flips state to EXITED and keeps the record")
def test_mark_exited_keeps_record():
    pass


@scenario(FEATURE, "Resume rebuilds the partner's responder")
def test_resume_rebuilds_responder():
    pass


@scenario(FEATURE, "Relaunch rebuilds the responder with a fresh conversation")
def test_relaunch_rebuilds_responder():
    pass


@scenario(FEATURE, "Forget on a partner cleans up the paired responder")
def test_forget_cleans_up_responder():
    pass


@scenario(FEATURE, "Action failure keeps the orphan in the modal with an inline error")
def test_action_failure_inline_error():
    pass


@scenario(FEATURE, "Resume button is disabled when no session_id was captured")
def test_resume_disabled_without_session_id():
    pass


# ── Fake tmux server ───────────────────────────────────────────────


class _FakeTmuxServer:
    """Reports no live sessions so all seeded agents look like orphans."""

    def __init__(self):
        self._live: set[str] = set()

    @property
    def sessions(self):
        live = self._live

        class _Lookup:
            def get(self, session_name=None, default=None):
                return object() if session_name in live else default

        return _Lookup()


# ── Test context ───────────────────────────────────────────────────


class _RecoveryContext:
    """Shared mutable context for BDD steps.

    Mirrors LifecycleContext from test_agent_lifecycle.py.
    All async operations are driven via self.run() using a dedicated
    event loop created fresh for each test scenario.

    Mount is deferred: given_desk_launched() sets _mount_requested=True but
    does NOT call mount(). The first When/Then step that needs the pilot calls
    ensure_mounted(). This lets Background and scenario-body Given steps both
    seed state before the app mounts and scans for orphans.
    """

    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.app: DeskApp | None = None
        self.pilot = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._run_test_cm = None
        self.relaunch_calls: list[dict] = []
        self.cleanup_calls: list[int] = []
        self.create_calls: list[int] = []
        self.relaunch_should_raise: str | None = None
        self._patches: list = []
        self._mount_requested: bool = False

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
        """Run an async coroutine on the dedicated event loop."""
        return self._get_loop().run_until_complete(coro)

    def install_patches(self) -> None:
        """Install all monkeypatches before mounting the app."""
        ctx = self

        # Patch libtmux.Server so the desk never sees real tmux.
        fake_server = _FakeTmuxServer()
        p1 = patch.object(desk_module.libtmux, "Server", return_value=fake_server)
        p1.start()
        self._patches.append(p1)

        # Patch relaunch_agent to a recorder.
        def fake_relaunch(agent_id, command, state_manager, *,
                          preserve_session_id=True, prefix="aque"):
            ctx.relaunch_calls.append({
                "agent_id": agent_id,
                "command": command,
                "preserve_session_id": preserve_session_id,
            })
            if ctx.relaunch_should_raise:
                raise RuntimeError(ctx.relaunch_should_raise)
            # Simulate the in-place update so _rebuild_responder sees RUNNING.
            state = state_manager.load()
            for a in state.agents:
                if a.id == agent_id:
                    a.state = AgentState.RUNNING
                    a.tmux_session = f"aque-relaunched-{agent_id}"
                    a.command = command
                    if not preserve_session_id:
                        a.session_id = None
            state_manager.save(state)

        # Patch both reference sites: ``desk_module.relaunch_agent`` covers
        # the orphan-relaunch branch (still in desk.py); ``aque.launch.
        # relaunch_agent`` covers the resume branch (now in the launch
        # coordinator). Same fake records both.
        p2 = patch.object(desk_module, "relaunch_agent", fake_relaunch)
        p2.start()
        self._patches.append(p2)
        p2b = patch("aque.launch.relaunch_agent", fake_relaunch)
        p2b.start()
        self._patches.append(p2b)

        # Patch responder.cleanup and responder.create_for to recorders.
        def fake_cleanup(partner, sm, server, *, aque_dir):
            ctx.cleanup_calls.append(partner.id)

        def fake_create_for(partner, config, sm, *, aque_dir):
            ctx.create_calls.append(partner.id)
            return -1

        p3 = patch.object(responder_module, "cleanup", fake_cleanup)
        p3.start()
        self._patches.append(p3)

        p4 = patch.object(responder_module, "create_for", fake_create_for)
        p4.start()
        self._patches.append(p4)

    def ensure_mounted(self) -> None:
        """Mount the app if not already mounted (lazy, called by When/Then steps)."""
        if self.app is None:
            self.mount()

    def mount(self) -> None:
        """Construct, configure, and mount the DeskApp with _skip_attach=False."""
        self.install_patches()
        self.run(self._mount())

    async def _mount(self) -> None:
        self.app = DeskApp(aque_dir=self.tmp_aque_dir, _skip_attach=False)
        # Provide a config so _rebuild_responder doesn't early-return.
        self.app.config = {
            "responder_enabled": True,
            "responder_command": ["claude"],
            "session_prefix": "aque",
        }
        self._run_test_cm = self.app.run_test()
        self.pilot = await self._run_test_cm.__aenter__()
        # Let on_mount + _scan_for_orphans fully propagate.
        await self.pilot.pause()
        await self.pilot.pause()

    async def _shutdown(self) -> None:
        if self._run_test_cm is not None:
            await self._run_test_cm.__aexit__(None, None, None)
            self._run_test_cm = None

    def cleanup(self) -> None:
        """Tear down the pilot and event loop."""
        if self.app is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._shutdown())
            except Exception:
                pass
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
        for p in reversed(self._patches):
            try:
                p.stop()
            except Exception:
                pass
        self._patches.clear()


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = _RecoveryContext(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


# ── Given steps ────────────────────────────────────────────────────


@given(parsers.parse("a captured claude orphan with id {agent_id:d} in the state file"))
def given_captured_claude_orphan(ctx, agent_id):
    ctx.state_mgr.add_agent(AgentInfo(
        id=agent_id,
        tmux_session=f"aque-{agent_id}",
        label=f"agent-{agent_id}",
        dir="/tmp",
        command=["claude"],
        state=AgentState.RUNNING,
        pid=1,
        agent_type="claude",
        session_id=f"uuid-{agent_id}",
    ))


@given(parsers.parse("a claude orphan with id {agent_id:d} and no captured session_id"))
def given_orphan_without_session_id(ctx, agent_id):
    ctx.state_mgr.add_agent(AgentInfo(
        id=agent_id,
        tmux_session=f"aque-{agent_id}",
        label=f"agent-{agent_id}",
        dir="/tmp",
        command=["claude"],
        state=AgentState.RUNNING,
        pid=2,
        agent_type="claude",
    ))


@given("the desk is launched")
def given_desk_launched(ctx):
    """Record that the desk should be launched.

    Actual mounting is deferred to ensure_mounted(), called by the first
    When/Then step. This allows scenario-body Given steps (e.g., seeding
    agent 2) to run before mount so the orphan scan sees all agents.
    """
    ctx._mount_requested = True


@given(parsers.parse('relaunch_agent is configured to fail with "{error_message}"'))
def given_relaunch_fails(ctx, error_message):
    ctx.relaunch_should_raise = error_message


# ── When steps ─────────────────────────────────────────────────────


@when(parsers.parse("I click Forget on agent {agent_id:d}"))
def click_forget(ctx, agent_id):
    ctx.ensure_mounted()

    async def _click():
        await ctx.pilot.click(f"#forget-{agent_id}")
        await ctx.pilot.pause()
        await ctx.pilot.pause()

    ctx.run(_click())


@when(parsers.parse("I click Resume on agent {agent_id:d}"))
def click_resume(ctx, agent_id):
    ctx.ensure_mounted()

    async def _click():
        await ctx.pilot.click(f"#resume-{agent_id}")
        await ctx.pilot.pause()
        await ctx.pilot.pause()

    ctx.run(_click())


@when(parsers.parse("I click Relaunch on agent {agent_id:d}"))
def click_relaunch(ctx, agent_id):
    ctx.ensure_mounted()

    async def _click():
        await ctx.pilot.click(f"#relaunch-{agent_id}")
        await ctx.pilot.pause()
        await ctx.pilot.pause()

    ctx.run(_click())


@when(parsers.parse('I click "Mark exited" on agent {agent_id:d}'))
def click_mark_exited(ctx, agent_id):
    ctx.ensure_mounted()

    async def _click():
        await ctx.pilot.click(f"#mark_exited-{agent_id}")
        await ctx.pilot.pause()
        await ctx.pilot.pause()

    ctx.run(_click())


# ── Then steps ─────────────────────────────────────────────────────


def _get_orphan_modal(ctx) -> OrphanModal | None:
    """Return the OrphanModal currently on screen, or None."""
    try:
        return ctx.app.screen
    except Exception:
        return None


@then("the orphan modal is shown")
def modal_shown(ctx):
    ctx.ensure_mounted()
    modal = _get_orphan_modal(ctx)
    assert modal is not None, "Expected an OrphanModal on screen"
    assert isinstance(modal, OrphanModal), (
        f"Expected OrphanModal, got {type(modal).__name__}"
    )
    assert modal.remaining_orphans(), "Expected at least one orphan in modal"


@then(parsers.parse("the modal lists agent {agent_id:d}"))
def modal_lists_agent(ctx, agent_id):
    ctx.ensure_mounted()
    modal = _get_orphan_modal(ctx)
    assert modal is not None and isinstance(modal, OrphanModal), (
        "Expected an OrphanModal on screen"
    )
    ids = [o.agent.id for o in modal.remaining_orphans()]
    assert agent_id in ids, f"Agent {agent_id} not listed in modal; got {ids}"


@then("the orphan modal is dismissed")
def modal_dismissed(ctx):
    ctx.ensure_mounted()
    # After dismiss, the screen should revert to the DeskApp's main screen,
    # which is not an OrphanModal.
    current = ctx.app.screen
    assert not isinstance(current, OrphanModal), (
        "OrphanModal is still on screen — expected it to be dismissed"
    )


@then("the orphan modal is still shown")
def modal_still_shown(ctx):
    ctx.ensure_mounted()
    modal = _get_orphan_modal(ctx)
    assert modal is not None and isinstance(modal, OrphanModal), (
        "Expected OrphanModal to still be on screen"
    )
    assert modal.remaining_orphans(), "Expected at least one orphan still in modal"


@then(parsers.parse("agent {agent_id:d} is removed from state.json"))
def agent_removed(ctx, agent_id):
    assert all(a.id != agent_id for a in ctx.state_mgr.load().agents), (
        f"Agent {agent_id} is still in state.json"
    )


@then(parsers.parse("agent {agent_id:d} is in state EXITED"))
def agent_state_exited(ctx, agent_id):
    a = ctx.state_mgr.load().get_agent(agent_id)
    assert a is not None, f"Agent {agent_id} not found in state.json"
    assert a.state == AgentState.EXITED, (
        f"Expected EXITED, got {a.state.value}"
    )


@then(parsers.parse("agent {agent_id:d} remains in state.json"))
def agent_remains(ctx, agent_id):
    assert any(a.id == agent_id for a in ctx.state_mgr.load().agents), (
        f"Agent {agent_id} missing from state.json"
    )


@then(parsers.parse("relaunch_agent is called with preserve_session_id={value} for agent {agent_id:d}"))
def relaunch_called(ctx, value, agent_id):
    expected = value.strip() == "True"
    matches = [
        c for c in ctx.relaunch_calls
        if c["agent_id"] == agent_id and c["preserve_session_id"] is expected
    ]
    assert matches, (
        f"No relaunch call for agent {agent_id} with "
        f"preserve_session_id={expected}; got {ctx.relaunch_calls}"
    )


@then(parsers.parse("the dead responder for agent {agent_id:d} is cleaned up"))
def responder_cleaned_up(ctx, agent_id):
    assert agent_id in ctx.cleanup_calls, (
        f"responder.cleanup not called for agent {agent_id}; calls={ctx.cleanup_calls}"
    )


@then(parsers.parse("a fresh responder for agent {agent_id:d} is created"))
def responder_created(ctx, agent_id):
    assert agent_id in ctx.create_calls, (
        f"responder.create_for not called for agent {agent_id}; calls={ctx.create_calls}"
    )


@then(parsers.parse("responder.cleanup is called for agent {agent_id:d}"))
def responder_cleanup_called(ctx, agent_id):
    assert agent_id in ctx.cleanup_calls, (
        f"responder.cleanup not called for agent {agent_id}; calls={ctx.cleanup_calls}"
    )


@then(parsers.parse("the row for agent {agent_id:d} shows an inline error"))
def row_shows_error(ctx, agent_id):
    ctx.ensure_mounted()

    async def _check():
        modal = ctx.app.screen
        assert isinstance(modal, OrphanModal), "Expected OrphanModal on screen"
        error_widgets = modal.query(".orphan-error")
        assert len(error_widgets) > 0, "No .orphan-error widgets found in modal"
        # Verify the error text contains something meaningful.
        error_static = error_widgets.first(Static)
        error_text = error_static.content
        assert "Error:" in error_text, f"Expected 'Error:' prefix, got: {error_text!r}"

    ctx.run(_check())


@then(parsers.parse("the Resume button for agent {agent_id:d} is disabled"))
def resume_disabled(ctx, agent_id):
    ctx.ensure_mounted()

    async def _check():
        modal = ctx.app.screen
        assert isinstance(modal, OrphanModal), "Expected OrphanModal on screen"
        btn = modal.query_one(f"#resume-{agent_id}", Button)
        assert btn.disabled, (
            f"Expected Resume button for agent {agent_id} to be disabled"
        )

    ctx.run(_check())
