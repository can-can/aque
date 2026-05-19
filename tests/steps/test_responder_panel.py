"""BDD tests for responder_panel.feature."""
import asyncio

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/responder_panel.feature"


@scenario(FEATURE, 'Agent with an active responder shows "RESPONDER · AUTO"')
def test_active_responder():
    pass


@scenario(FEATURE, 'Agent with auto_respond off shows "RESPONDER · PAUSED"')
def test_paused_responder():
    pass


@scenario(FEATURE, "Agent with no responder shows the empty state")
def test_no_responder():
    pass


@scenario(FEATURE, 'Selecting a responder shows the "responding for" view')
def test_responder_self_view():
    pass


@scenario(FEATURE, "Responder panel lists recent AQUE: nudges from the pane")
def test_responder_reply_log():
    pass


@scenario(FEATURE, "Responder panel lists rules when a rules file exists")
def test_responder_rules():
    pass


class Ctx:
    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None

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
        self.app = DeskApp(aque_dir=self.tmp_aque_dir, _skip_attach=True)
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
def ctx(tmp_aque_dir, request):
    import aque.desk as desk_mod
    original_capture = desk_mod.capture_pane_content
    c = Ctx(tmp_aque_dir)

    def _teardown():
        c.cleanup()
        # Restore in case a test patched capture_pane_content for fake panes.
        desk_mod.capture_pane_content = original_capture

    request.addfinalizer(_teardown)
    return c


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    return ctx


def _seed_agent(ctx, label, state=AgentState.RUNNING, **kwargs) -> AgentInfo:
    agent_id = ctx.state_mgr.next_id()
    agent = AgentInfo(
        id=agent_id,
        tmux_session=f"aque-test-{agent_id}",
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=state,
        pid=10000 + agent_id,
        **kwargs,
    )
    ctx.state_mgr.add_agent(agent)
    return agent


@given(parsers.parse('agent "{label}" has a paired running responder'))
def given_agent_with_responder(ctx, label):
    partner = _seed_agent(ctx, label, state=AgentState.WAITING, auto_respond=True)
    _seed_agent(
        ctx,
        f"resp({partner.id})",
        state=AgentState.RUNNING,
        is_responder=True,
        partner_id=partner.id,
    )


@given(parsers.parse('agent "{label}" has a paired running responder with auto_respond off'))
def given_agent_with_paused_responder(ctx, label):
    partner = _seed_agent(ctx, label, state=AgentState.WAITING, auto_respond=False)
    _seed_agent(
        ctx,
        f"resp({partner.id})",
        state=AgentState.RUNNING,
        is_responder=True,
        partner_id=partner.id,
    )


@given(parsers.parse('agent "{label}" is running and highlighted'))
def given_agent_running_and_highlighted(ctx, label):
    _seed_agent(ctx, label)
    ctx.ensure_mounted()

    async def _highlight():
        ctx.app._refresh_agent_list(reset_highlight=True)
        ol = ctx.app.query_one("#agent-option-list")
        for i in range(ol.option_count):
            if label in str(ol.get_option_at_index(i).prompt):
                ol.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_highlight())


@given(parsers.parse('agent "{label}" is highlighted'))
def given_agent_highlighted(ctx, label):
    ctx.ensure_mounted()

    async def _highlight():
        ctx.app._refresh_agent_list(reset_highlight=True)
        ol = ctx.app.query_one("#agent-option-list")
        for i in range(ol.option_count):
            if label in str(ol.get_option_at_index(i).prompt):
                ol.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_highlight())


@given(parsers.parse('the responder pane contains "{text}"'))
def given_responder_pane_contains(ctx, text):
    """Stub the pane capture so the responder's pane returns ``text``.

    Avoids spinning up a real tmux session just to fake its scrollback.
    """
    state = ctx.state_mgr.load()
    resp = next((a for a in state.agents if a.is_responder), None)
    assert resp is not None, "No responder seeded — call the prior Given first"

    import aque.desk as desk_mod
    real_capture = desk_mod.capture_pane_content

    def fake_capture(server, session_name):
        if session_name == resp.tmux_session:
            return text + "\n"
        return real_capture(server, session_name)

    ctx._capture_patch = fake_capture
    desk_mod.capture_pane_content = fake_capture


@given(parsers.parse('the responder for "{label}" has rules "{rules}"'))
def given_responder_has_rules(ctx, label, rules):
    """Write a rules.txt file for the partner under ~/.aque/responders/<id>.

    Rules are pipe-separated in the Gherkin step for readability.
    """
    state = ctx.state_mgr.load()
    partner = next((a for a in state.agents if a.label == label), None)
    assert partner is not None, f"Partner '{label}' not found"
    rules_dir = ctx.tmp_aque_dir / "responders" / str(partner.id)
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "rules.txt").write_text("\n".join(rules.split("|")))


@given(parsers.parse('the responder of "{label}" is highlighted'))
def given_responder_highlighted(ctx, label):
    ctx.ensure_mounted()

    async def _highlight():
        ctx.app.show_responders = True
        ctx.app._last_agent_fingerprint = None
        ctx.app._refresh_agent_list(reset_highlight=True)
        ol = ctx.app.query_one("#agent-option-list")
        # Find the responder row whose parent label matches.
        state = ctx.state_mgr.load()
        partner = next((a for a in state.agents if a.label == label), None)
        assert partner is not None, f"Partner '{label}' not found"
        resp = next(
            (a for a in state.agents if a.is_responder and a.partner_id == partner.id),
            None,
        )
        assert resp is not None, f"No responder for '{label}'"
        for i in range(ol.option_count):
            if int(ol.get_option_at_index(i).id) == resp.id:
                ol.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_highlight())


@when("the preview refreshes")
def when_preview_refreshes(ctx):
    async def _refresh():
        ctx.app._refresh_preview()
        await ctx.pilot.pause()

    ctx.run(_refresh())


@then(parsers.parse('the preview pane should show "{text}"'))
def then_preview_shows(ctx, text):
    preview = ctx.app.query_one("#preview-pane")
    rendered = str(preview.render())
    assert text in rendered, (
        f"Expected '{text}' in preview pane, got: {rendered!r}"
    )
