"""Autostart of the dashboard as systemd user services.

The switch in the settings window writes the same units that
``scripts/install.sh`` renders and then runs ``systemctl --user enable`` or
``disable`` on them. Both paths lead to the same place; whoever used the
script already sees that state reflected in the switch.

systemd is assumed — the app targets CachyOS and Arch, where it is standard.
What *is* checked is whether a *user instance* is reachable: that depends on
the session rather than the distribution, and without a bus there would only
be an incomprehensible error message.

Deliberately *without* ``--now``: the backend is answering the very request
that flips the switch, and ``disable --now`` would kill its own process
mid-response. The switch governs the *next* login, nothing else.

Both units are switched together. Splitting them would offer a state — data
collection without a display — that nobody asked for, and the kiosk without
the backend only ever shows its waiting screen.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "systemd"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

#: Order matters on enable: the backend before the window that talks to it.
UNITS = ("edge-dashboard.service", "edge-kiosk.service")

COMMAND_TIMEOUT_S = 5.0


class AutostartUnavailable(RuntimeError):
    """No systemd user instance reachable."""


class AutostartError(RuntimeError):
    """systemctl refused."""


@dataclass(slots=True)
class AutostartStatus:
    #: Can the autostart be switched at all right now?
    supported: bool
    enabled: bool
    #: Which of the units are installed in ~/.config/systemd/user.
    units: list[str]
    #: Filled when ``supported`` is false — text for the settings window.
    reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------


def status() -> AutostartStatus:
    """Current state — without changing anything."""
    installed = [unit for unit in UNITS if (UNIT_DIR / unit).exists()]
    reason = _unsupported_reason()
    if reason is not None:
        return AutostartStatus(
            supported=False, enabled=False, units=installed, reason=reason
        )

    # Only "enabled" really means autostart — "linked", "static" and
    # "disabled" do not. Both units have to be on for the switch to be on:
    # a half-enabled pair would start a kiosk with no backend.
    states = [_systemctl("is-enabled", unit).stdout.strip() for unit in UNITS]
    return AutostartStatus(
        supported=True,
        enabled=all(state == "enabled" for state in states),
        units=installed,
    )


def set_enabled(enabled: bool) -> AutostartStatus:
    """Switches the autostart and returns the new state."""
    reason = _unsupported_reason()
    if reason is not None:
        raise AutostartUnavailable(reason)

    if enabled:
        # Rewritten on every enable. That is idempotent and heals the case
        # where the checkout moved since the last install and the old unit
        # points nowhere.
        for unit in UNITS:
            _write_unit(unit)
        _systemctl("daemon-reload")
        result = _systemctl("enable", *UNITS)
    else:
        present = [unit for unit in UNITS if (UNIT_DIR / unit).exists()]
        if not present:
            # Nothing to switch off — the goal is already reached.
            return status()
        result = _systemctl("disable", *present)

    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise AutostartError(message or "systemctl failed without a message")

    return status()


# --------------------------------------------------------------------------
# Internal
# --------------------------------------------------------------------------


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_S,
        check=False,
    )


def _unsupported_reason() -> str | None:
    """``None`` when it can be switched — otherwise the reason in plain text."""
    try:
        probe = _systemctl("is-system-running")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"systemctl not runnable: {exc}")
        return f"systemctl could not be run: {exc}"
    # A non-zero return code here usually only means "degraded", which is no
    # obstacle. A missing bus, on the other hand, means there is no user
    # instance that could enable a unit.
    if "bus" in (probe.stderr or "").lower():
        return "No systemd user session reachable."
    return None


def _write_unit(unit: str) -> Path:
    """Renders one unit template into ~/.config/systemd/user."""
    template = TEMPLATE_DIR / unit
    try:
        text = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise AutostartError(f"unit template unreadable: {template} ({exc})") from exc

    uv = shutil.which("uv")
    if uv is None and "__UV__" in text:
        raise AutostartError("'uv' not found — cannot render the backend unit")

    text = text.replace("__PROJECT_DIR__", str(ROOT)).replace("__UV__", uv or "")

    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    target = UNIT_DIR / unit
    target.write_text(text, encoding="utf-8")
    logger.info(f"unit written: {target}")
    return target


__all__ = ["AutostartError", "AutostartStatus", "AutostartUnavailable", "set_enabled", "status"]
