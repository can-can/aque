"""Orphan reconciliation for aque.

An orphan is an AgentInfo in state.json whose tmux session no longer exists
(typically after a machine reboot). `find_orphans` returns the list and
marks each one's `resumable` flag based on whether we have a captured
session_id and a plugin that exposes session capture for its agent_type.
"""

from dataclasses import dataclass

import libtmux

from aque.monitor import session_exists
from aque.plugins import get_plugin, has_session_capture
from aque.state import AgentInfo, AgentState, AppState


@dataclass
class OrphanedAgent:
    agent: AgentInfo
    resumable: bool


def find_orphans(state: AppState, server: libtmux.Server) -> list[OrphanedAgent]:
    orphans: list[OrphanedAgent] = []
    for agent in state.agents:
        if agent.state == AgentState.DONE:
            continue
        if agent.is_responder:
            continue
        if session_exists(server, agent.tmux_session):
            continue
        plugin = get_plugin(agent.agent_type) if agent.agent_type else None
        resumable = has_session_capture(plugin) and agent.session_id is not None
        orphans.append(OrphanedAgent(agent=agent, resumable=resumable))
    return orphans
