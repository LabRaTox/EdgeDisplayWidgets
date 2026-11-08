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

import contextlib
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from loguru import logger

from . import host

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "systemd"
#: systemd reads user units from $XDG_CONFIG_HOME, which is not always ~/.config.
UNIT_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
#: Where the package puts its units. Installed that way, there is nothing to
#: render: the switch only enables or disables what the package brought.
PACKAGE_UNIT_DIR = Path("/usr/lib/systemd/user")
IN_CHECKOUT = (ROOT / "pyproject.toml").is_file()

#: A login entry for desktops whose session never reaches
#: graphical-session.target (XFCE, Cinnamon, MATE, LXQt and others): there
#: the enabled units would wait for a target that does not come. KDE and GNOME
#: reach it, so the entry stays out of their way.
LOGIN_ENTRY = (
    Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    / "autostart" / "edge-dashboard-start.desktop"
)
#: What the units need from the session to find a screen. Such sessions do
#: not hand it to the user manager themselves.
SESSION_VARS = "DISPLAY WAYLAND_DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE"

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
    #: Which of the units are installed (~/.config/systemd/user, or the
    #: package's /usr/lib/systemd/user).
    units: list[str]
    #: Filled when ``supported`` is false — text for the settings window.
    reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------


def _installed() -> list[str]:
    return [unit for unit in UNITS
            if (UNIT_DIR / unit).exists() or (not IN_CHECKOUT and (PACKAGE_UNIT_DIR / unit).exists())]


def status() -> AutostartStatus:
    """Current state — without changing anything."""
    installed = _installed()
    reason = _unsupported_reason()
    if reason is not None:
        return AutostartStatus(
            supported=False, enabled=False, units=installed, reason=reason
        )

    # Only "enabled" really means autostart — "linked", "static" and
    # "disabled" do not. Both units have to be on for the switch to be on:
    # a half-enabled pair would start a kiosk with no backend.
    try:
        states = [_systemctl("is-enabled", unit).stdout.strip() for unit in UNITS]
    except (OSError, subprocess.SubprocessError) as exc:
        # A user manager that does not answer in time is no reason for a 500.
        return AutostartStatus(
            supported=False, enabled=False, units=installed, reason=f"systemctl: {exc}"
        )
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
        if IN_CHECKOUT:
            for unit in UNITS:
                _write_unit(unit)
        _systemctl("daemon-reload")
        result = _systemctl("enable", *UNITS)
        if result.returncode == 0:
            _write_login_entry()
    else:
        with contextlib.suppress(OSError):
            LOGIN_ENTRY.unlink(missing_ok=True)
        present = _installed()
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
    return host.run(["systemctl", "--user", *args], timeout=COMMAND_TIMEOUT_S)


def kiosk_python() -> str:
    """What runs the kiosk: its own virtualenv if `install.sh` made one."""
    own = ROOT / ".venv-kiosk" / "bin" / "python"
    return str(own) if own.is_file() else "/usr/bin/python3"


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


def _write_login_entry() -> None:
    """The XDG autostart entry that starts the units at login. Not fatal:
    on KDE and GNOME the units start without it."""
    units = " ".join(UNITS)
    text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Edge Dashboard\n"
        "Comment=Starts the Edge Dashboard services where the session does not\n"
        # Double quotes: the desktop entry spec knows no single ones.
        f'Exec=sh -c "systemctl --user import-environment {SESSION_VARS} 2>/dev/null; '
        f'exec systemctl --user start {units}"\n'
        "NotShowIn=KDE;GNOME;\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    try:
        LOGIN_ENTRY.parent.mkdir(parents=True, exist_ok=True)
        LOGIN_ENTRY.write_text(text, encoding="utf-8")
    except OSError as exc:
        logger.warning(f"login entry not written: {exc}")


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

    text = (text.replace("__PROJECT_DIR__", str(ROOT))
            .replace("__UV__", uv or "")
            .replace("__KIOSK_PYTHON__", kiosk_python()))

    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    target = UNIT_DIR / unit
    target.write_text(text, encoding="utf-8")
    logger.info(f"unit written: {target}")
    return target


__all__ = ["AutostartError", "AutostartStatus", "AutostartUnavailable", "set_enabled", "status"]
