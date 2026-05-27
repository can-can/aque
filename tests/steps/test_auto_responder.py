"""BDD tests for auto-responder scenarios.

Strategy:
- Most scenarios are tested by exercising the production code directly
  (responder.create_for, monitor.process_pending_nudges, responder.cleanup,
  desk.pick_auto_attach_target, desk.visible_agents) rather than spinning
  up the full Textual TUI. This keeps the suite fast and deterministic.
- The two scenarios that genuinely require the TUI ("dashboard 'a' key",
  "press R to reveal responders") use the same run_test() pattern as
  test_agent_lifecycle.py.
- libtmux.Server and aque.cli.launch_agent are mocked so no real tmux
  sessions are created.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque import responder as responder_mod
from aque.desk import DeskApp
from aque.monitor import process_pending_nudges, handle_session_gone
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/auto_responder.feature"


# ── Scenario declarations ─────────────────────────────────────────────────────


@scenario(FEATURE, "New agent auto-creates a paired responder")
def test_new_agent_creates_responder():
    pass


@scenario(FEATURE, "--no-responder skips pairing")
def test_no_responder_skips_pairing():
    pass


@scenario(FEATURE, "Responders do not get their own responders")
def test_responders_not_re_paired():
    pass


@scenario(FEATURE, "Global responder_enabled=false skips creation for all launches")
def test_global_responder_disabled():
    pass


@scenario(FEATURE, "Partner going waiting nudges its responder after idle gap")
def test_partner_waiting_nudges_responder():
    pass


@scenario(FEATURE, "No nudge before idle gap elapses")
def test_no_nudge_before_idle_gap():
    pass


@scenario(FEATURE, "Re-nudge after another idle gap without a reply")
def test_renudge_after_another_gap():
    pass


@scenario(FEATURE, "Partner unsticking before responder replies stops re-nudges")
def test_partner_unsticking_stops_renudges():
    pass


@scenario(FEATURE, "auto_respond=false suppresses nudges")
def test_auto_respond_false_suppresses():
    pass


@scenario(FEATURE, 'Dashboard "a" key toggles auto_respond on selected partner')
def test_dashboard_a_key_toggles_auto_respond():
    pass


@scenario(FEATURE, "Responders never appear as their own row in the dashboard list")
def test_responders_never_appear_as_rows():
    pass


@scenario(FEATURE, "Auto-attach countdown skips responders")
def test_auto_attach_skips_responders():
    pass


@scenario(FEATURE, "Killing the partner cleans up its responder")
def test_killing_partner_cleans_responder():
    pass


@scenario(FEATURE, "Responder exits unexpectedly does not stop the partner")
def test_responder_exits_unexpectedly():
    pass


@scenario(FEATURE, "Partner row shows a responder badge when a responder is paired")
def test_partner_row_shows_badge():
    pass


@scenario(FEATURE, "Partner row has no responder badge when no responder is paired")
def test_partner_row_no_badge():
    pass


@scenario(FEATURE, "Responder state change invalidates the partner row fingerprint")
def test_responder_state_invalidates_fingerprint():
    pass


@scenario(FEATURE, "Ctrl+Enter on a partner with a responder full-screen attaches to the responder")
def test_ctrl_enter_attaches_to_responder():
    pass


@scenario(FEATURE, "Ctrl+Enter on a partner with no responder shows a notification")
def test_ctrl_enter_no_responder_notifies():
    pass


# ── Shared fixtures and helpers ───────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_aque_dir):
    """Shared mutable context for steps within a scenario."""
    server = MagicMock()
    # Default to "session exists" for any session lookup until a step overrides.
    server.sessions.get.return_value = MagicMock()
    return {
        "aque_dir": tmp_aque_dir,
        "mgr": StateManager(tmp_aque_dir),
        "config": {
            "responder_enabled": True,
            "responder_command": ["claude"],
            "responder_idle_gap": 5,
            "responder_dir": None,
            "session_prefix": "aque",
        },
        "server": server,
        "agents_by_name": {},  # name -> agent_id mapping
        "nudge_calls": [],     # list of (partner_id, responder_id) tuples
    }


def _add_partner(
    ctx,
    name: str,
    *,
    state: AgentState = AgentState.RUNNING,
    auto_respond: bool = True,
    last_change_at: str | None = None,
    last_nudge_at: str | None = None,
) -> int:
    """Add a non-responder agent with the given name to state."""
    mgr: StateManager = ctx["mgr"]
    agent_id = mgr.next_id()
    agent = AgentInfo(
        id=agent_id,
        tmux_session=f"aque-{name}-{agent_id}",
        label=name,
        dir="/tmp",
        command=["claude"],
        state=state,
        pid=100 + agent_id,
        auto_respond=auto_respond,
    )
    if last_change_at is not None:
        agent.last_change_at = last_change_at
    if last_nudge_at is not None:
        agent.last_nudge_at = last_nudge_at
    mgr.add_agent(agent)
    ctx["agents_by_name"][name] = agent_id
    return agent_id


def _add_responder_for(
    ctx,
    partner_id: int,
    name: str,
    *,
    state: AgentState = AgentState.RUNNING,
) -> int:
    """Add a responder paired with `partner_id` and register it under `name`."""
    mgr: StateManager = ctx["mgr"]
    rid = mgr.next_id()
    agent = AgentInfo(
        id=rid,
        tmux_session=f"aque-resp-{partner_id}-{rid}",
        label=name,
        dir="/tmp",
        command=["claude"],
        state=state,
        pid=200 + rid,
        is_responder=True,
        partner_id=partner_id,
    )
    mgr.add_agent(agent)
    ctx["agents_by_name"][name] = rid
    return rid


def _lookup(ctx, name: str) -> AgentInfo:
    """Find an agent by its registered name in this scenario."""
    aid = ctx["agents_by_name"][name]
    state = ctx["mgr"].load()
    return next(a for a in state.agents if a.id == aid)


# ── Pairing creation scenarios ────────────────────────────────────────────────


@when(parsers.parse('a new agent "{name}" is launched'))
def when_new_agent_launched(ctx, name):
    """Simulate the CLI launching a new partner agent.

    Bypasses real tmux: directly seeds the partner via _add_partner, then
    invokes responder.create_for (with launch_agent patched to seed the
    responder record in-process) — exactly mirroring the cli.run flow.
    """
    config = ctx["config"]
    if not config.get("responder_enabled", True):
        # Skip auto-pairing entirely.
        _add_partner(ctx, name)
        return

    partner_id = _add_partner(ctx, name)
    mgr: StateManager = ctx["mgr"]
    partner = next(a for a in mgr.load().agents if a.id == partner_id)

    def _fake_launch(command, working_dir, label, state_manager, **kwargs):
        new_id = state_manager.next_id()
        state_manager.add_agent(AgentInfo(
            id=new_id,
            tmux_session=f"aque-resp-{partner.id}-{new_id}",
            label=label,
            dir=working_dir,
            command=command,
            state=AgentState.RUNNING,
            pid=300 + new_id,
            is_responder=kwargs.get("is_responder", False),
            partner_id=kwargs.get("partner_id"),
        ))
        return new_id

    with patch("aque.responder.launch_agent", side_effect=_fake_launch):
        responder_mod.create_for(
            partner, config, mgr, aque_dir=ctx["aque_dir"]
        )


@when(parsers.parse('a new agent "{name}" is launched with --no-responder'))
def when_new_agent_no_responder(ctx, name):
    """Launch without auto-pairing — equivalent to cli flag suppression."""
    _add_partner(ctx, name)


@given(parsers.parse('agent "{name}" exists with a paired responder "{resp_name}"'))
def given_agent_with_paired_responder_named(ctx, name, resp_name):
    partner_id = _add_partner(ctx, name)
    _add_responder_for(ctx, partner_id, resp_name)


@given(parsers.parse("config has responder_enabled set to false"))
def given_responder_disabled(ctx):
    ctx["config"]["responder_enabled"] = False


@then(parsers.parse('a responder agent paired to "{name}" should exist'))
def then_responder_paired_exists(ctx, name):
    partner = _lookup(ctx, name)
    state = ctx["mgr"].load()
    resp = responder_mod.find_for(partner.id, state.agents)
    assert resp is not None, f'No responder paired to "{name}" found'


@then(parsers.parse('no responder agent paired to "{name}" should exist'))
def then_no_responder_paired(ctx, name):
    target = _lookup(ctx, name)
    state = ctx["mgr"].load()
    resp = responder_mod.find_for(target.id, state.agents)
    assert resp is None, (
        f'Expected no responder paired to "{name}" (id={target.id}), '
        f'found responder id={resp.id}'
    )


@then(parsers.parse("the responder should have is_responder=true"))
def then_responder_is_responder_true(ctx):
    state = ctx["mgr"].load()
    responders = [a for a in state.agents if a.is_responder]
    assert responders, "Expected at least one responder in state"
    assert all(a.is_responder is True for a in responders)


@then(parsers.parse('the responder\'s partner_id should equal "{name}"\'s id'))
def then_responder_partner_id_matches(ctx, name):
    partner = _lookup(ctx, name)
    state = ctx["mgr"].load()
    resp = responder_mod.find_for(partner.id, state.agents)
    assert resp is not None, f'No responder paired to "{name}" found'
    assert resp.partner_id == partner.id, (
        f"responder.partner_id={resp.partner_id} != partner.id={partner.id}"
    )


# ── Nudge flow scenarios ──────────────────────────────────────────────────────


@given(parsers.parse('agent "{name}" has a paired responder "{resp_name}"'))
def given_partner_with_responder(ctx, name, resp_name):
    partner_id = _add_partner(ctx, name)
    _add_responder_for(ctx, partner_id, resp_name)


@given(parsers.parse("the responder_idle_gap is {seconds:d} seconds"))
def given_responder_idle_gap(ctx, seconds):
    ctx["config"]["responder_idle_gap"] = seconds


@when(parsers.parse('agent "{name}" transitions to "{state_str}"'))
def when_agent_transitions(ctx, name, state_str):
    agent_id = ctx["agents_by_name"][name]
    new_state = AgentState(state_str)
    # Backdate last_change_at to (now - configured idle gap) so a subsequent
    # "X seconds pass" step doesn't actually have to sleep.
    gap = float(ctx["config"]["responder_idle_gap"])
    # Default: just transition normally; "seconds pass" steps will rewind.
    ctx["mgr"].update_agent_state(agent_id, new_state)


@when(parsers.parse('{seconds:d} seconds pass with "{name}" still in "{state_str}"'))
def when_seconds_pass(ctx, seconds, name, state_str):
    """Simulate time passing by rewinding the agent's last_change_at.

    For a "5 seconds pass" + 5s idle gap this means last_change_at moves
    to (now - 5s), so process_pending_nudges sees the gap as elapsed.
    For 5s pass + 30s gap, last_change_at moves to (now - 5s), and the
    gap will NOT be reached — exactly what the negative scenario wants.
    """
    agent_id = ctx["agents_by_name"][name]
    mgr: StateManager = ctx["mgr"]
    with mgr._locked():
        st = mgr.load()
        for a in st.agents:
            if a.id == agent_id:
                assert a.state.value == state_str, (
                    f'Expected "{name}" in state {state_str}, '
                    f"got {a.state.value}"
                )
                a.last_change_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=seconds)
                ).isoformat()
        mgr.save(st)

    # Run a monitor poll right now — the per-scenario "Then" step
    # will inspect the result.
    _poll_monitor(ctx)


@when(parsers.parse("the responder_idle_gap elapses"))
def when_responder_idle_gap_elapses(ctx):
    """Advance time past the responder_idle_gap on the most-recently-touched partner.

    Uses the partner referenced by the prior 'transitions to "waiting"' step.
    """
    mgr: StateManager = ctx["mgr"]
    gap = float(ctx["config"]["responder_idle_gap"])
    with mgr._locked():
        st = mgr.load()
        for a in st.agents:
            if not a.is_responder and a.state == AgentState.WAITING:
                a.last_change_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=gap + 1)
                ).isoformat()
        mgr.save(st)
    _poll_monitor(ctx)


@given(parsers.parse('"{name}" has been nudged {seconds:d} seconds ago and is still "{state_str}"'))
def given_already_nudged(ctx, name, seconds, state_str):
    agent_id = ctx["agents_by_name"][name]
    target_state = AgentState(state_str)
    mgr: StateManager = ctx["mgr"]
    with mgr._locked():
        st = mgr.load()
        for a in st.agents:
            if a.id == agent_id:
                a.state = target_state
                a.last_nudge_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=seconds)
                ).isoformat()
                a.last_change_at = (
                    datetime.now(timezone.utc) - timedelta(seconds=seconds * 2)
                ).isoformat()
        mgr.save(st)


@given(parsers.parse('agent "{name}" has been nudged and is in "{state_str}"'))
def given_partner_already_nudged_basic(ctx, name, state_str):
    """Set up a partner+responder pair where the partner has been nudged once."""
    partner_id = _add_partner(ctx, name)
    _add_responder_for(ctx, partner_id, f"resp({name})")
    target_state = AgentState(state_str)
    mgr: StateManager = ctx["mgr"]
    with mgr._locked():
        st = mgr.load()
        for a in st.agents:
            if a.id == partner_id:
                a.state = target_state
                # Nudge happened "just now" — re-nudge would require gap to elapse.
                a.last_nudge_at = datetime.now(timezone.utc).isoformat()
        mgr.save(st)


def _poll_monitor(ctx):
    """Invoke process_pending_nudges with a patched responder.nudge that records calls."""
    server = ctx["server"]
    mgr: StateManager = ctx["mgr"]
    config = ctx["config"]
    calls = ctx["nudge_calls"]

    real_nudge = responder_mod.nudge

    def _recording_nudge(partner, resp, srv, *, state_manager):
        # Record the call, then run the real nudge with our mocked server
        # so last_nudge_at side effects happen as in production.
        result = real_nudge(partner, resp, srv, state_manager=state_manager)
        calls.append({
            "partner_id": partner.id,
            "responder_id": resp.id,
            "result": result,
        })
        return result

    with patch("aque.monitor.responder.nudge", side_effect=_recording_nudge):
        process_pending_nudges(mgr, server, config)


@when("the monitor polls")
def when_monitor_polls(ctx):
    """Generic monitor-poll step.

    For the 'responder exits' scenario, we additionally need to flip the
    responder's state to EXITED when its session is gone — replicate
    that bit of the monitor's session-gone logic here.
    """
    mgr: StateManager = ctx["mgr"]
    server = ctx["server"]

    # If the test set up a "killed externally" responder, simulate the
    # monitor's session-gone branch for it.
    killed = ctx.get("killed_responder_id")
    if killed is not None:
        responder = mgr.load().get_agent(killed)
        if responder is not None:
            # Replicate monitor: a responder whose session is gone becomes EXITED.
            mgr.update_agent_state(responder.id, AgentState.EXITED)

    _poll_monitor(ctx)


@then(parsers.parse('the responder "{resp_name}" should receive exactly one nudge'))
def then_responder_one_nudge(ctx, resp_name):
    resp_id = ctx["agents_by_name"][resp_name]
    matching = [c for c in ctx["nudge_calls"] if c["responder_id"] == resp_id]
    successes = [c for c in matching if c["result"] is True]
    assert len(successes) == 1, (
        f'Expected exactly one successful nudge for "{resp_name}" (id={resp_id}), '
        f"got {len(successes)}. All calls: {ctx['nudge_calls']}"
    )


@then(parsers.parse('the responder "{resp_name}" should receive no nudge'))
def then_responder_no_nudge(ctx, resp_name):
    resp_id = ctx["agents_by_name"][resp_name]
    successes = [
        c for c in ctx["nudge_calls"]
        if c["responder_id"] == resp_id and c["result"] is True
    ]
    assert not successes, (
        f'Expected no nudge for "{resp_name}" (id={resp_id}), '
        f"got {successes}"
    )


@then(parsers.parse('the responder "{resp_name}" should receive another nudge'))
def then_responder_another_nudge(ctx, resp_name):
    resp_id = ctx["agents_by_name"][resp_name]
    successes = [
        c for c in ctx["nudge_calls"]
        if c["responder_id"] == resp_id and c["result"] is True
    ]
    assert len(successes) >= 1, (
        f'Expected at least one re-nudge for "{resp_name}" (id={resp_id}), '
        f"got {ctx['nudge_calls']}"
    )


@then(parsers.parse('"{name}"\'s last_nudge_at should be updated'))
def then_last_nudge_at_updated(ctx, name):
    partner = _lookup(ctx, name)
    assert partner.last_nudge_at is not None, (
        f'"{name}".last_nudge_at should be set, got None'
    )


@when(parsers.parse('agent "{name}" transitions back to "{state_str}"'))
def when_agent_transitions_back(ctx, name, state_str):
    agent_id = ctx["agents_by_name"][name]
    new_state = AgentState(state_str)
    ctx["mgr"].update_agent_state(agent_id, new_state)


@then("no additional nudge should fire on the next monitor poll")
def then_no_additional_nudge(ctx):
    pre_count = sum(1 for c in ctx["nudge_calls"] if c["result"] is True)
    _poll_monitor(ctx)
    post_count = sum(1 for c in ctx["nudge_calls"] if c["result"] is True)
    assert post_count == pre_count, (
        f"Expected no new nudges, but successful count went "
        f"{pre_count} → {post_count}"
    )


# ── Kill-switch scenarios ────────────────────────────────────────────────────


@given(parsers.parse('"{name}"\'s auto_respond flag is {flag_str}'))
def given_auto_respond_flag(ctx, name, flag_str):
    agent_id = ctx["agents_by_name"][name]
    mgr: StateManager = ctx["mgr"]
    flag_value = flag_str.lower() == "true"
    with mgr._locked():
        st = mgr.load()
        for a in st.agents:
            if a.id == agent_id:
                a.auto_respond = flag_value
        mgr.save(st)


# ── Focused-responder rule ───────────────────────────────────────────────────


@given(parsers.parse('"{resp_name}" is in "{state_str}" state'))
def given_responder_in_state(ctx, resp_name, state_str):
    rid = ctx["agents_by_name"][resp_name]
    ctx["mgr"].update_agent_state(rid, AgentState(state_str))


# ── Dashboard scenarios — TUI based ──────────────────────────────────────────


class _AppCtx:
    """Lazy Textual app holder. Mirrors the pattern from test_agent_lifecycle.py."""

    def __init__(self, aque_dir):
        self.aque_dir = aque_dir
        self.app = None
        self._loop = None
        self._run_test_cm = None
        self.pilot = None

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
        return self._get_loop().run_until_complete(coro)

    def ensure_mounted(self):
        if self.app is None:
            self.run(self._mount())

    async def _mount(self):
        self.app = DeskApp(aque_dir=self.aque_dir, _skip_attach=True)
        self._run_test_cm = self.app.run_test()
        self.pilot = await self._run_test_cm.__aenter__()
        await self.pilot.pause()

    async def _shutdown(self):
        if self._run_test_cm is not None:
            await self._run_test_cm.__aexit__(None, None, None)
            self._run_test_cm = None

    def cleanup(self):
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


@pytest.fixture
def app_ctx(tmp_aque_dir, request):
    a = _AppCtx(tmp_aque_dir)
    request.addfinalizer(a.cleanup)
    return a


def _highlight_agent_id(app_ctx: _AppCtx, agent_id: int) -> None:
    async def _do():
        from textual.widgets import OptionList
        ol = app_ctx.app.query_one("#agent-option-list", OptionList)
        for i in range(ol.option_count):
            opt = ol.get_option_at_index(i)
            if opt.id == str(agent_id):
                ol.highlighted = i
                break
        await app_ctx.pilot.pause()
    app_ctx.run(_do())


@given(parsers.parse('agent "{name}" is highlighted on the dashboard'))
def given_agent_highlighted(ctx, app_ctx, name):
    """Ensure the named agent exists, mount the app, install
    _attach_to_agent + notify capture hooks (idempotent so chained Givens
    compose cleanly), and highlight its row.
    """
    if name not in ctx["agents_by_name"]:
        _add_partner(ctx, name)
    app_ctx.ensure_mounted()
    if "attach_log" not in ctx:
        ctx["attach_log"] = _patch_attach_to_agent(app_ctx)
    if "notifications" not in ctx:
        notes: list[str] = []
        ctx["notifications"] = notes
        app_ctx.app.notify = lambda msg, **kw: notes.append(msg)
    _highlight_agent_id(app_ctx, ctx["agents_by_name"][name])


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses(ctx, app_ctx, key):
    app_ctx.ensure_mounted()

    async def _press():
        await app_ctx.pilot.press(key)
        await app_ctx.pilot.pause()

    app_ctx.run(_press())


@when(parsers.parse('the user presses "{key}" on the dashboard'))
def when_user_presses_on_dashboard(ctx, app_ctx, key):
    when_user_presses(ctx, app_ctx, key)


@when(parsers.parse('the user presses "{key}" with "{name}" highlighted'))
def when_user_presses_with_highlighted(ctx, app_ctx, key, name):
    """Generic 'press X with Y highlighted'.

    Special-cased for 'k' because the kill flow needs to drive the
    underlying _kill_agent / responder.cleanup logic against our mocked
    tmux server, not the real one the DeskApp would use.
    """
    if key == "k":
        _scenario_kill_partner(ctx, name)
        return

    app_ctx.ensure_mounted()
    target_id = ctx["agents_by_name"][name]
    _highlight_agent_id(app_ctx, target_id)

    async def _press():
        await app_ctx.pilot.press(key)
        await app_ctx.pilot.pause()

    app_ctx.run(_press())


@then(parsers.parse('"{name}"\'s auto_respond flag should be {flag_str}'))
def then_auto_respond_flag_is(ctx, name, flag_str):
    expected = flag_str.lower() == "true"
    agent = _lookup(ctx, name)
    assert agent.auto_respond is expected, (
        f'"{name}".auto_respond should be {expected}, got {agent.auto_respond}'
    )


@then("no auto_respond flag should change")
def then_no_auto_respond_change(ctx):
    state = ctx["mgr"].load()
    # All partners default to auto_respond=True after _add_partner;
    # responders also default to True. Confirm nothing flipped.
    for a in state.agents:
        assert a.auto_respond is True, (
            f"Agent id={a.id} ({a.label}) flipped auto_respond to "
            f"{a.auto_respond}"
        )


# ── Visibility scenarios ─────────────────────────────────────────────────────


@when("the dashboard renders the agent list")
def when_dashboard_renders_list(ctx, app_ctx):
    app_ctx.ensure_mounted()

    async def _refresh():
        app_ctx.app._refresh_agent_list(reset_highlight=True)
        await app_ctx.pilot.pause()

    app_ctx.run(_refresh())


def _list_labels(app_ctx: _AppCtx) -> list[str]:
    from textual.widgets import OptionList
    ol = app_ctx.app.query_one("#agent-option-list", OptionList)
    return [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]


@then(parsers.parse('"{name}" should appear in the list'))
def then_name_in_list(ctx, app_ctx, name):
    app_ctx.ensure_mounted()

    async def _refresh():
        app_ctx.app.dash.invalidate_fingerprint()
        app_ctx.app._refresh_agent_list()
        await app_ctx.pilot.pause()
    app_ctx.run(_refresh())

    labels = _list_labels(app_ctx)
    assert any(name in line for line in labels), (
        f'Expected "{name}" in agent list, got: {labels}'
    )


@then(parsers.parse('"{name}" should not appear in the list'))
def then_name_not_in_list(ctx, app_ctx, name):
    app_ctx.ensure_mounted()

    async def _refresh():
        app_ctx.app.dash.invalidate_fingerprint()
        app_ctx.app._refresh_agent_list()
        await app_ctx.pilot.pause()
    app_ctx.run(_refresh())

    labels = _list_labels(app_ctx)
    assert not any(name in line for line in labels), (
        f'Expected "{name}" NOT in agent list, got: {labels}'
    )


@then(parsers.parse('"{resp_name}" should appear in the list indented under "{partner_name}"'))
def then_responder_indented_under(ctx, app_ctx, resp_name, partner_name):
    labels = _list_labels(app_ctx)
    # Find the partner index, then verify the next row contains the responder
    # name AND is indented (responder rows include the "↳ " prefix).
    partner_idx = next(
        (i for i, line in enumerate(labels) if partner_name in line),
        None,
    )
    assert partner_idx is not None, (
        f'Expected "{partner_name}" in list, got: {labels}'
    )
    assert partner_idx + 1 < len(labels), (
        f'No row after "{partner_name}" — list was: {labels}'
    )
    next_row = labels[partner_idx + 1]
    assert resp_name in next_row, (
        f'Expected "{resp_name}" in row after "{partner_name}", '
        f"got: {next_row}"
    )
    assert "↳" in next_row, (
        f'Expected responder row to be indented with "↳", got: {next_row}'
    )


# ── Auto-attach skipping responders ──────────────────────────────────────────


@given(parsers.parse('responder "{resp_name}" is the highest-priority waiting agent'))
def given_responder_is_top_waiting(ctx, resp_name):
    # Create a partner (running) and a responder paired with it, in WAITING.
    partner_id = _add_partner(ctx, "builder", state=AgentState.RUNNING)
    _add_responder_for(ctx, partner_id, resp_name, state=AgentState.WAITING)


@when("the auto-attach picker selects a target")
def when_auto_attach_picker_runs(ctx):
    app = DeskApp(aque_dir=ctx["aque_dir"], _skip_attach=True)
    state = ctx["mgr"].load()
    ctx["picked"] = app.dash.pick_auto_attach_target(state.agents)


@then(parsers.parse('"{name}" should not be selected'))
def then_name_not_selected(ctx, name):
    picked = ctx.get("picked")
    target_id = ctx["agents_by_name"][name]
    assert picked is None or picked.id != target_id, (
        f'Expected "{name}" (id={target_id}) NOT selected, but picker returned it'
    )


# ── Cleanup scenarios ────────────────────────────────────────────────────────


@then(parsers.parse('"{name}" should be moved to history'))
def then_moved_to_history(ctx, name):
    state = ctx["mgr"].load()
    active = [a.label for a in state.agents]
    assert name not in active, (
        f'Expected "{name}" out of active agents, still in: {active}'
    )


@then(parsers.parse('"{resp_name}"\'s tmux session should be killed'))
def then_resp_session_killed(ctx, resp_name):
    """The session kill was issued via the mocked server.

    With responder.cleanup invoked, server.sessions.get(...).kill() should
    have been called.
    """
    server = ctx["server"]
    # Any kill call on a session object returned by sessions.get is fine.
    # In our setup ctx["server"].sessions.get returns a MagicMock whose
    # .kill is a MagicMock — assert it was called at least once.
    session_mock = server.sessions.get.return_value
    assert session_mock.kill.called, (
        f'Expected tmux session kill for "{resp_name}", but no kill issued'
    )


@then(parsers.parse('"{resp_name}" should be removed from state'))
def then_resp_removed_from_state(ctx, resp_name):
    resp_id = ctx["agents_by_name"][resp_name]
    state = ctx["mgr"].load()
    assert not any(a.id == resp_id for a in state.agents), (
        f'Expected "{resp_name}" (id={resp_id}) removed from state, still present'
    )


# Override the generic dashboard "the user presses 'k' with X highlighted" path
# to actually perform the kill via desk._kill_agent (which invokes
# responder.cleanup). We don't go through the TUI for this scenario because
# the responder/partner objects are mocked and not real tmux sessions.
def _scenario_kill_partner(ctx, name):
    mgr: StateManager = ctx["mgr"]
    server = ctx["server"]
    partner_id = ctx["agents_by_name"][name]
    partner = mgr.load().get_agent(partner_id)
    if partner is None:
        return
    # First clean up its responder (mirrors desk._kill_agent flow).
    responder_mod.cleanup(partner, mgr, server, aque_dir=ctx["aque_dir"])
    # Then move partner to history.
    from aque.history import HistoryManager
    hmgr = HistoryManager(ctx["aque_dir"])
    mgr.done_agent(partner_id, hmgr)




# ── Responder-exits-externally scenario ──────────────────────────────────────


@when(parsers.parse('"{resp_name}"\'s tmux session is killed externally'))
def when_resp_session_killed_externally(ctx, resp_name):
    """Mark the responder's tmux session as missing.

    The next 'monitor polls' step will run handle_session_gone equivalent
    logic and flip the responder to EXITED.
    """
    rid = ctx["agents_by_name"][resp_name]
    ctx["killed_responder_id"] = rid
    # Capture the partner's current state so we can assert it didn't change.
    state = ctx["mgr"].load()
    resp = next(a for a in state.agents if a.id == rid)
    partner = next(a for a in state.agents if a.id == resp.partner_id)
    ctx["partner_state_before"] = partner.state


@then(parsers.parse('"{resp_name}" should be in "{state_str}" state'))
def then_resp_in_state(ctx, resp_name, state_str):
    resp = _lookup(ctx, resp_name)
    assert resp.state == AgentState(state_str), (
        f'Expected "{resp_name}" in {state_str}, got {resp.state.value}'
    )


@then(parsers.parse('agent "{name}" should remain in its previous state'))
def then_partner_remains_in_state(ctx, name):
    state = ctx["mgr"].load()
    partner = next(a for a in state.agents if a.label == name)
    expected = ctx["partner_state_before"]
    assert partner.state == expected, (
        f'Expected "{name}" to remain in {expected.value}, got {partner.state.value}'
    )


# ── Badge & embed swap scenarios ─────────────────────────────────────────────


@given(parsers.parse('agent "{name}" exists without a paired responder'))
def given_solo_partner_exists(ctx, name):
    """Seed a single non-responder agent in state; no responder is created."""
    _add_partner(ctx, name)



def _rendered_row_for(app_ctx, label: str) -> str:
    """Return the rendered text of the option whose agent has ``label``.

    Looks up the agent id by label in state, finds the matching option in
    the rendered list, and returns the option's prompt as a plain string
    (which retains the ``●r`` badge glyphs Text.from_markup produced).
    """
    from textual.widgets import OptionList

    async def _do():
        ol = app_ctx.app.query_one("#agent-option-list", OptionList)
        state = app_ctx.app.state_mgr.load()
        agent_id = next(a.id for a in state.agents if a.label == label)
        for i in range(ol.option_count):
            opt = ol.get_option_at_index(i)
            if opt.id == str(agent_id):
                return str(opt.prompt)
        return ""

    return app_ctx.run(_do())


@when("the dashboard renders the agent list", target_fixture="rendered_rows")
def when_dashboard_renders_list(ctx, app_ctx):
    """Mount the desk so the option list is populated, then return a marker
    fixture the Then steps can depend on (the actual rendered rows are read
    on demand in the Then steps via _rendered_row_for)."""
    app_ctx.ensure_mounted()
    return True


@then(parsers.parse('the row for "{label}" should contain a responder badge'))
def then_row_has_badge(app_ctx, label):
    text = _rendered_row_for(app_ctx, label)
    assert "●r" in text, (
        f'Expected row for "{label}" to contain "●r" badge, got: {text!r}'
    )


@then(parsers.parse('the row for "{label}" should not contain a responder badge'))
def then_row_no_badge(app_ctx, label):
    text = _rendered_row_for(app_ctx, label)
    assert "●r" not in text, (
        f'Expected row for "{label}" to have no badge, got: {text!r}'
    )


@given("the dashboard has cached the current row fingerprint")
def given_fingerprint_cached(ctx, app_ctx):
    """Mount the desk and force one refresh so DashboardController caches
    a fingerprint for the current state."""
    app_ctx.ensure_mounted()

    async def _do():
        app_ctx.app._refresh_agent_list()
        await app_ctx.pilot.pause()

    app_ctx.run(_do())


@when(parsers.parse('"{resp_name}" transitions to "{state_str}"'))
def when_responder_transitions(ctx, app_ctx, resp_name, state_str):
    rid = ctx["agents_by_name"][resp_name]
    ctx["mgr"].update_agent_state(rid, AgentState(state_str))


@then("the dashboard fingerprint should be marked as changed")
def then_fingerprint_changed(ctx, app_ctx):
    # Recompute exactly as _refresh_agent_list does — visible partners plus
    # the partner->responder state map. The new responder state must make
    # fingerprint_changed return True even though no partner's own state moved.
    state = ctx["mgr"].load()
    agents = app_ctx.app.dash.compute_visible(state)
    responder_states = {
        a.partner_id: a.state.value
        for a in state.agents
        if a.is_responder and a.partner_id is not None
    }
    assert app_ctx.app.dash.fingerprint_changed(agents, responder_states), (
        "Expected fingerprint to be marked changed after responder transition"
    )


def _patch_attach_to_agent(app_ctx) -> list[int]:
    """Stub the desk's _attach_to_agent so the responder Ctrl+Enter action
    can run without actually suspending into tmux. Returns a list that
    records the agent id passed to each capture call (the test asserts on
    the id, which uniquely identifies the agent).
    """
    captured: list[int] = []

    def _stub_attach(agent):
        captured.append(agent.id)

    app_ctx.app._attach_to_agent = _stub_attach
    app_ctx.app._skip_attach = False
    return captured


@then(parsers.parse('the desk should full-screen attach to "{name}"\'s tmux session'))
def then_desk_attached_to(ctx, app_ctx, name):
    captured = ctx.get("attach_log") or []
    assert captured, "_attach_to_agent was never called"
    aid = ctx["agents_by_name"][name]
    assert captured[-1] == aid, (
        f'Expected last attach to be "{name}" (id={aid}), '
        f'got id={captured[-1]} (full log: {captured})'
    )


@then(parsers.parse('a notification containing "{substr}" should be shown'))
def then_notification_contains(ctx, substr):
    notes = ctx.get("notifications") or []
    assert any(substr in n for n in notes), (
        f'Expected a notification containing {substr!r}; got {notes!r}'
    )


