"""Stateless capability gate for chat2api listener editing.

Editing ``server.host``/``server.port`` is only useful when the installed
launcher actually forwards them to uvicorn. Verifying that by starting the
server is unsafe and cannot be isolated: the launcher needs its application
tree, so any copy or symlink exposes the real ``config.json``/``.env`` to a
child process, and a probe would race with the production listener on the real
port.

Instead the gate asks the launcher what it *would* serve. ``start.sh
--print-listener`` resolves the configuration with the same interpreter and
loader as the serving path, prints the host and port, and exits before any
uvicorn import or port bind. A launcher that does not implement the flag exits
non-zero, which is treated as "capability absent" (fail-closed).

The module is deliberately stateless: it creates no network object, reserves no
port, starts no process session or group, and runs no polling loop waiting for
the service. Its only interaction with the launcher is one captured
``subprocess.run`` call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ai_manager.config.structured_models import LauncherProbeResult

FLAG = "--print-listener"
LAUNCHER_NAME = "start.sh"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
TIMEOUT_S = 10.0


def _parse_listener(stdout: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` from a two-line answer, or ``None`` if invalid.

    Exactly two non-empty lines are accepted: the host, then the port. Blank
    lines around them are ignored, but the values themselves are used verbatim -
    no whitespace is stripped, because a padded host would be written and
    forwarded to uvicorn verbatim and produce an unusable endpoint. The host
    must be exactly one of the three loopback spellings (``localhost`` compared
    case-insensitively) and the port must be plain ASCII digits in ``1..65535``.
    """
    lines = stdout.splitlines()
    values = [line for line in lines if line.strip()]
    if len(values) != 2:
        return None
    host, raw_port = values
    if host not in LOOPBACK_HOSTS and not (
        host.isascii() and host.lower() == "localhost"
    ):
        return None
    if not (raw_port.isascii() and raw_port.isdigit()):
        return None
    try:
        port = int(raw_port)
    except ValueError:
        # A very long digit string is still just an invalid answer: ``int()``
        # refuses conversions beyond the interpreter's digit limit, and that
        # must not escape the failed-result contract.
        return None
    if not 1 <= port <= 65535:
        return None
    return host, port


def _text(value: str | bytes | None) -> str:
    """Return a timeout payload as text, decoding bytes if the call yielded them."""
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def probe_launcher(app_dir: Path, *, timeout_s: float = TIMEOUT_S) -> LauncherProbeResult:
    """Ask the launcher which host and port it would bind, without binding.

    Runs ``start.sh --print-listener`` with an argv list, ``shell=False``, the
    resolved application directory as cwd and the inherited environment. Success
    requires exit status 0, exactly two non-empty stdout lines, a loopback host
    and a port in ``1..65535``. Every other outcome - non-zero exit, timeout,
    missing or unrunnable launcher, malformed answer - returns
    ``passed=False`` with the captured stderr as ``detail``.

    The result is never cached here; the caller caches it per resolved
    application directory for its own session so each case stays testable.
    """
    launcher = Path(app_dir) / LAUNCHER_NAME
    if not launcher.is_file():
        return LauncherProbeResult(
            passed=False,
            detail=f"No launcher at {launcher}",
        )
    try:
        completed = subprocess.run(
            [str(launcher), FLAG],
            cwd=str(Path(app_dir)),
            env=None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # The launcher may have explained itself before hanging, so keep what it
        # captured instead of discarding the diagnostics.
        timeout_message = (
            f"Launcher capability check timed out after {timeout_s:g} seconds."
        )
        captured_stdout = _text(exc.stdout)
        captured_stderr = _text(exc.stderr)
        detail = (captured_stderr or captured_stdout or "").strip() or timeout_message
        return LauncherProbeResult(
            passed=False,
            detail=detail,
            stdout=captured_stdout,
            stderr=captured_stderr,
        )
    except OSError as exc:
        return LauncherProbeResult(
            passed=False,
            detail=f"Could not run the launcher: {exc}",
        )

    parsed = _parse_listener(completed.stdout) if completed.returncode == 0 else None
    if parsed is None:
        detail = (completed.stderr or completed.stdout or "").strip()
        return LauncherProbeResult(
            passed=False,
            detail=detail or "Launcher did not report a valid listener.",
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
    host, port = parsed
    return LauncherProbeResult(
        passed=True,
        detail=f"Launcher honors configuration: {host}:{port}",
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )
