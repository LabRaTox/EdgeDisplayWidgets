"""Starting other programs, from one place.

Everything the backend runs goes through here: `systemctl`, the commands of
quick actions and their status probes, the settings window and the package
managers. Always an argv list and never a shell, so nothing in a command is
interpreted on the way.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Output:
    """What a finished program left behind."""

    returncode: int | None
    stdout: str
    stderr: str


def run(command: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run a program and wait for it. Blocks, so not from the event loop.

    Raises `OSError` when it cannot start and `subprocess.TimeoutExpired`
    when it does not finish; a non-zero exit is the caller's to judge.
    """
    return subprocess.run(list(command), capture_output=True, text=True, timeout=timeout, check=False)


async def capture(command: Sequence[str], *, timeout: float) -> Output:
    """Run a program from the event loop and collect its output.

    Raises `OSError` when it cannot start. Past the timeout the program is
    killed and `TimeoutError` raised.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return Output(process.returncode, stdout.decode("utf-8", errors="replace"),
                  stderr.decode("utf-8", errors="replace"))


def detach(command: Sequence[str]) -> None:
    """Start a program that outlives this request, and do not wait for it."""
    subprocess.Popen(
        list(command),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def window(command: Sequence[str]) -> asyncio.subprocess.Process:
    """Start a window of our own. In a session of its own: it must not die
    with the backend, and must not inherit its terminal."""
    return await asyncio.create_subprocess_exec(
        *command,
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
