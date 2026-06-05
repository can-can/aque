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


@pytest.mark.asyncio
async def test_pty_close_reaps_child():
    import os
    proc = PtyProcess(["cat"])
    proc.start()
    pid = proc.pid
    proc.close()
    # close() must have reaped the child, so waitpid raises (no such child)
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, 0)


@pytest.mark.asyncio
async def test_pty_close_is_idempotent():
    proc = PtyProcess(["cat"])
    proc.start()
    proc.close()
    proc.close()  # second close must not raise
