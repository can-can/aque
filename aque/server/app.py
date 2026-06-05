from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, FastAPI

from aque.server.agents import agents_payload
from aque.server.auth import make_http_auth
from aque.server.terminal import default_terminal_command
from aque.state import StateManager


def create_app(
    aque_dir: Path,
    token: str,
    *,
    watch_interval: float = 1.0,
    command_for_agent: Optional[Callable[[dict], list[str]]] = None,
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

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.get("/agents", dependencies=[Depends(require_token)])
    async def agents() -> dict:
        return {"agents": agents_payload(state_manager)}

    return app
