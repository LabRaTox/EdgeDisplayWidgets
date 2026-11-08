"""Starting other programs, from one place.

Everything the backend runs goes through here: `systemctl`, the commands of
quick actions and their status probes, the settings window and the package
managers. Always an argv list and never a shell, so nothing in a command is
interpreted on the way.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
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
    except BaseException:
        # A timeout, but also a cancel: a reload cancels the poll that waits
        # here, and a hanging probe would otherwise outlive every reload.
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        with contextlib.suppress(BaseException):
            await asyncio.shield(process.wait())
        raise
    return Output(process.returncode, stdout.decode("utf-8", errors="replace"),
                  stderr.decode("utf-8", errors="replace"))


def outside_service(command: Sequence[str]) -> list[str]:
    """The command, in a scope of its own when we run as a systemd unit.

    A new session is not enough to outlive the backend: systemd stops a
    service by its control group, and everything started from it is in that
    group. A quick action's app, a game started through Steam and the settings
    window would all die on every restart, update or tray Quit. `systemd-run
    --scope` puts the program in a group of its own; it execs the command, so
    the process started is still the program itself.

    Outside a unit (a terminal, the tests) there is nothing to escape from.
    """
    argv = list(command)
    if os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", *argv]
    return argv


def detach(command: Sequence[str]) -> None:
    """Start a program that outlives this request, and do not wait for it."""
    subprocess.Popen(
        outside_service(command),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def window(command: Sequence[str]) -> asyncio.subprocess.Process:
    """Start a window of our own. In a session of its own: it must not die
    with the backend, and must not inherit its terminal."""
    return await asyncio.create_subprocess_exec(
        *outside_service(command),
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
