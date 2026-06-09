import json
import subprocess
from typing import Callable

from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from aque.server.auth import token_ok
from aque.state import StateManager

# The wheel's eight keys. Only these tmux key names may be sent; anything else
# is rejected (no arbitrary passthrough). Extend only when the wheel grows.
ALLOWED_KEYS = frozenset(
    {"Up", "Down", "Left", "Right", "Enter", "Escape", "Tab", "C-u"}
)

SendKeys = Callable[[dict, str], None]


def default_send_keys(agent: dict, key: str) -> None:
    """Send one tmux key name to the phone's grouped session for this agent.

    Targets ``phone-<id>`` (the session the phone attaches via
    ``default_terminal_command``); ``send-keys`` lands on that session's active
    pane, which is the window the phone is viewing. No ``-l`` flag: we WANT tmux
    to interpret the key name (e.g. ``Up`` -> the up-arrow sequence in the pane's
    current cursor-key mode, ``C-c`` -> Ctrl-C).
    """
    group = f"phone-{agent['id']}"
    subprocess.run(["tmux", "send-keys", "-t", group, key], check=False)


def register_control_routes(
    app: FastAPI, state_manager: StateManager, token: str, send_keys_for_agent: SendKeys
) -> None:
    """Add the token-gated ``WS /agents/{id}/control`` route."""

    @app.websocket("/agents/{agent_id}/control")
    async def control(ws: WebSocket, agent_id: int) -> None:
        if not token_ok(
            ws.headers.get("authorization"), ws.query_params.get("token"), token
        ):
            await ws.close(code=1008)
            return
        agent = state_manager.load().get_agent(agent_id)
        if agent is None or agent.is_responder:
            await ws.close(code=1011)
            return

        await ws.accept()
        agent_dict = agent.to_dict()
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                text = msg.get("text")
                if text is None:
                    continue
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if data.get("type") != "key":
                    continue
                key = data.get("key")
                if key not in ALLOWED_KEYS:
                    await ws.send_json(
                        {"type": "error", "reason": "key not allowed", "key": key}
                    )
                    continue
                try:
                    send_keys_for_agent(agent_dict, key)
                except Exception:  # a failed send must not kill the socket
                    await ws.send_json(
                        {"type": "error", "reason": "send failed", "key": key}
                    )
                    continue
                await ws.send_json({"type": "ok", "key": key})
        except WebSocketDisconnect:
            return
