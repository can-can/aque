import asyncio
import json
from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from aque.server.agents import agents_payload
from aque.server.auth import make_http_auth, token_ok
from aque.server.control import default_send_keys, register_control_routes
from aque.server.pty_bridge import PtyProcess
from aque.server.terminal import default_terminal_command
from aque.server.watcher import StateWatcher
from aque.state import StateManager


def create_app(
    aque_dir: Path,
    token: str,
    *,
    watch_interval: float = 1.0,
    command_for_agent: Optional[Callable[[dict], list[str]]] = None,
    send_keys_for_agent: Optional[Callable[[dict, str], None]] = None,
) -> FastAPI:
    """Build the Aque remote server.

    ``command_for_agent`` maps an agent dict to the argv launched in the PTY;
    overridable in tests so the terminal endpoint needn't spawn real tmux.
    """
    app = FastAPI(title="aque serve")
    state_manager = StateManager(Path(aque_dir))
    require_token = make_http_auth(token)
    app.state.aque_dir = Path(aque_dir)
    app.state.token = token
    app.state.watch_interval = watch_interval
    app.state.command_for_agent = command_for_agent or default_terminal_command
    app.state.send_keys_for_agent = send_keys_for_agent or default_send_keys
    register_control_routes(app, state_manager, token, app.state.send_keys_for_agent)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.get("/agents", dependencies=[Depends(require_token)])
    async def agents() -> dict:
        return {"agents": agents_payload(state_manager)}

    @app.websocket("/events")
    async def events(ws: WebSocket) -> None:
        if not token_ok(
            ws.headers.get("authorization"), ws.query_params.get("token"), token
        ):
            await ws.close(code=1008)
            return
        await ws.accept()
        watcher = StateWatcher(app.state.aque_dir / "state.json", app.state.watch_interval)
        try:
            await ws.send_json({"type": "agents", "agents": agents_payload(state_manager)})
            async for _ in watcher.watch():
                await ws.send_json(
                    {"type": "agents", "agents": agents_payload(state_manager)}
                )
        except WebSocketDisconnect:
            pass

    @app.websocket("/agents/{agent_id}/terminal")
    async def terminal(ws: WebSocket, agent_id: int) -> None:
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

        # Wait for the client's initial size before spawning so the terminal is
        # born at the right dimensions (a TUI's first paint must be at the final
        # width, or stale wide cells leave residue on the client). Buffer any
        # input that arrives before the resize.
        init_cols, init_rows = 80, 24
        pending_input = b""
        try:
            first = await asyncio.wait_for(ws.receive(), timeout=3.0)
            if first["type"] == "websocket.disconnect":
                return
            if first.get("text") is not None:
                try:
                    data = json.loads(first["text"])
                    if data.get("type") == "resize":
                        init_cols, init_rows = int(data["cols"]), int(data["rows"])
                except (ValueError, TypeError, KeyError):
                    pass
            elif first.get("bytes") is not None:
                pending_input = first["bytes"]
        except asyncio.TimeoutError:
            pass

        proc = PtyProcess(app.state.command_for_agent(agent.to_dict()))
        proc.start(init_cols, init_rows)
        if pending_input:
            proc.write(pending_input)

        async def pump_out() -> None:
            async for chunk in proc.output():
                await ws.send_bytes(chunk)

        async def pump_in() -> None:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:
                    proc.write(msg["bytes"])
                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                    except (ValueError, TypeError):
                        continue
                    if data.get("type") == "resize":
                        try:
                            proc.resize(int(data["cols"]), int(data["rows"]))
                        except (KeyError, ValueError, TypeError):
                            continue

        out_task = asyncio.create_task(pump_out())
        in_task = asyncio.create_task(pump_in())
        try:
            await asyncio.wait({out_task, in_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            out_task.cancel()
            in_task.cancel()
            # Retrieve exceptions from already-finished tasks so a disconnect
            # doesn't log "Task exception was never retrieved".
            for t in (out_task, in_task):
                if t.done() and not t.cancelled():
                    t.exception()
            proc.close()

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        page = Path(__file__).parent / "static" / "terminal_test.html"
        return page.read_text()

    @app.get("/terminal", response_class=HTMLResponse)
    async def terminal_page() -> str:
        page = Path(__file__).parent / "static" / "terminal.html"
        return page.read_text()

    # Static assets (gestures.js, etc.), served fresh from disk.
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    return app
