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

import re
import subprocess
from pathlib import Path

from ai_manager.config.structured_models import LauncherProbeResult

FLAG = "--print-listener"
LAUNCHER_NAME = "start.sh"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
TIMEOUT_S = 10.0


#: Option keys whose values must never appear in diagnostics.
_SECRET_KEYS = (
    "password",
    "account",
    "access_token",
    "api_key",
    "token",
    "secure_1psid",
    "secure_1psidts",
)
_REDACTED = "***"

#: Marker written in place of redacted content.
_REDACTED = "***"

#: From ``input_value=`` onward, pydantic dumps the offending configuration. That
#: dump is unbalanced-brace-hostile: a credential may itself contain ``}``,
#: ``input_type=`` or quotes, so no pattern can find its end reliably. Everything
#: from the marker to the end of that line is therefore discarded wholesale. The
#: error class, location and message come earlier on the line and survive.
_INPUT_VALUE_MARKER = "input_value="

#: A secret key followed by ``: "value"`` in non-pydantic output. Escaped quotes are
#: handled by refusing to cross a line boundary; the truncation above is the primary
#: defence for structured dumps, this covers plain-text diagnostics.
_SECRET_PAIR = re.compile(
    r"(?P<key>['\"]?(?:" + "|".join(_SECRET_KEYS) + r")['\"]?\s*[:=]\s*)"
    r"(?P<quote>['\"])(?P<value>[^\n]*?)(?P=quote)",
    re.IGNORECASE,
)


def redact_diagnostics(text: str) -> str:
    """Strip credential-bearing values from service diagnostics.

    The launcher runs the service's real configuration loader, so a validation
    error can quote the offending configuration verbatim - including a password or
    token held in an option value. Those diagnostics reach a details panel that
    expands automatically, which would bypass the editor's Reveal controls.

    Truncating at ``input_value=`` is deliberate. An earlier pattern-based version
    tried to match the end of the dumped mapping; a credential containing ``}``
    defeated it and survived into the UI. Discarding the remainder of the line
    cannot be defeated by the credential's *contents*, which is the property that
    matters.
    """
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        marker = line.find(_INPUT_VALUE_MARKER)
        if marker != -1:
            line = f"{line[:marker]}{_INPUT_VALUE_MARKER}{_REDACTED}"
        lines.append(_SECRET_PAIR.sub(
            lambda m: f"{m.group('key')}{m.group('quote')}{_REDACTED}{m.group('quote')}",
            line,
        ))
    redacted = "\n".join(lines)
    return redacted + ("\n" if text.endswith("\n") else "")


def _parse_listener(stdout: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` from the launcher's closing two lines.

    The launcher may print informational output before the answer - the real
    chat2api launcher prints its version banner first - so the **last two** non-empty
    lines are the answer, in order: the host, then the port. Any
    earlier output is ignored rather than treated as a parse error; cross-target
    acceptance against the real launcher is what established this.

    The values are used verbatim: no whitespace is stripped, because a padded
    host would be written and forwarded to uvicorn verbatim and produce an
    unusable endpoint. The host must be exactly one of the three loopback
    spellings (``localhost`` compared case-insensitively) and the port must be
    plain ASCII digits in ``1..65535``.
    """
    values = [line for line in stdout.splitlines() if line.strip()]
    if len(values) < 2:
        return None
    host, raw_port = values[-2:]
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
    requires exit status 0, at least two non-empty stdout lines (the last two are
    the answer), a loopback host
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
        # The launcher may have explained itself on stderr before hanging, so keep
        # that instead of discarding the diagnostics. Standard output is kept in
        # the result for inspection but never explains the timeout: a printed
        # listener answer describes what the launcher *would* serve, not why the
        # probe gave up.
        timeout_message = (
            f"Launcher capability check timed out after {timeout_s:g} seconds."
        )
        captured_stdout = redact_diagnostics(_text(exc.stdout))
        captured_stderr = redact_diagnostics(_text(exc.stderr))
        detail = captured_stderr.strip() or timeout_message
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
        detail = redact_diagnostics(
            (completed.stderr or completed.stdout or "").strip()
        )
        return LauncherProbeResult(
            passed=False,
            detail=detail or "Launcher did not report a valid listener.",
            stdout=redact_diagnostics(completed.stdout),
            stderr=redact_diagnostics(completed.stderr),
            returncode=completed.returncode,
        )
    host, port = parsed
    return LauncherProbeResult(
        passed=True,
        detail=f"Launcher honors configuration: {host}:{port}",
        stdout=redact_diagnostics(completed.stdout),
        stderr=redact_diagnostics(completed.stderr),
        returncode=completed.returncode,
    )
