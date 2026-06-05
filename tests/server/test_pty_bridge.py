import asyncio

import pytest

from aque.server.pty_bridge import PtyProcess


@pytest.mark.asyncio
async def test_pty_echoes_written_input():
    proc = PtyProcess(["cat"])
    proc.start()
    proc.write(b"hello\n")

    gen = proc.output()
    got = b""
    try:
        while b"hello" not in got:
            got += await asyncio.wait_for(gen.__anext__(), timeout=3.0)
    finally:
        await gen.aclose()
        proc.close()

    assert b"hello" in got


@pytest.mark.asyncio
async def test_pty_resize_does_not_raise():
    proc = PtyProcess(["cat"])
    proc.start()
    try:
        proc.resize(cols=100, rows=40)  # should not raise
    finally:
        proc.close()
