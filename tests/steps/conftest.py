import pytest
from pytest_bdd import given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


@pytest.fixture
def state_mgr(tmp_aque_dir):
    return StateManager(tmp_aque_dir)


@pytest.fixture
def history_mgr(tmp_aque_dir):
    return HistoryManager(tmp_aque_dir)


@pytest.fixture
def desk_app(tmp_aque_dir):
    return DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)


@pytest.fixture
async def pilot_context(desk_app):
    """Keep Textual Pilot context alive across all BDD steps in a scenario."""
    async with desk_app.run_test() as pilot:
        yield {"app": desk_app, "pilot": pilot}


# ── Shared step definitions ──────────────────────────────────────


@given("the aque desk is open", target_fixture="pilot_context")
async def given_desk_is_open(pilot_context):
    return pilot_context


@given("the user is on the dashboard")
async def given_user_on_dashboard(pilot_context):
    await pilot_context["pilot"].pause()


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist(state_mgr, datatable):
    agents = []
    for row in datatable:
        state_str = row["state"]
        state = AgentState(state_str)
        agent_id = state_mgr.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-{agent_id}",
            label=row["label"],
            dir="/tmp/test",
            command=["test"],
            state=state,
            pid=10000 + agent_id,
        )
        if "last_change_at" in row:
            agent.last_change_at = row["last_change_at"]
        state_mgr.add_agent(agent)
        agents.append(agent)
    return agents


@when(parsers.parse('the user presses "{key}"'))
async def when_user_presses(pilot_context, key):
    await pilot_context["pilot"].press(key)
    await pilot_context["pilot"].pause()


@when(parsers.parse("the user presses {key}"))
async def when_user_presses_bare(pilot_context, key):
    key_name = key.lower()
    await pilot_context["pilot"].press(key_name)
    await pilot_context["pilot"].pause()


@when("the dashboard loads")
async def when_dashboard_loads(pilot_context):
    await pilot_context["pilot"].pause()


@when("the app mounts")
async def when_app_mounts(pilot_context):
    await pilot_context["pilot"].pause()
