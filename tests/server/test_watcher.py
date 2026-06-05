import asyncio
import json

import pytest

from aque.server.watcher import StateWatcher


@pytest.mark.asyncio
async def test_watcher_yields_on_change(server_aque_dir):
    state_file = server_aque_dir / "state.json"
    watcher = StateWatcher(state_file, interval=0.02)

    gen = watcher.watch()
    waiter = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0.05)
    assert not waiter.done()  # nothing changed yet

    state_file.write_text(json.dumps({"agents": [{"id": 9}], "monitor_pid": None}))
    await asyncio.wait_for(waiter, timeout=2.0)  # change detected

    await gen.aclose()
