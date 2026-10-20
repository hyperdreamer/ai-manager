"""Cross-target acceptance for the launcher capability gate.

These tests run :func:`ai_manager.services.launcher_gate.probe_launcher` against the
**real** chat2api launcher, in both directions:

* the fixed launcher must pass the gate, and
* the pre-fix baseline launcher must fail closed, because it has no
  ``--print-listener`` capability.

Neither case may bind a socket: the gate asks the launcher what it *would* bind and
exits before any uvicorn import or bind.

The target checkout is selected by ``CHAT2API_LAUNCHER_CHECKOUT``. Without it the tests
skip, so the suite stays green where Target B is not installed.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

from ai_manager.services.launcher_gate import probe_launcher

_CONFIGURED = os.environ.get("CHAT2API_LAUNCHER_CHECKOUT", "").strip()

#: Absolute path to a chat2api checkout, or ``None`` when the operator has not
#: supplied one. There is deliberately no default: acceptance must never depend on
#: a machine-specific worktree path baked into the test source.
CHECKOUT: Path | None = Path(_CONFIGURED) if _CONFIGURED else None

BASELINE_COMMIT = "c40e3c6"
PRODUCTION_PORT = 8000


def _require_checkout() -> Path:
    if CHECKOUT is None:
        pytest.skip(
            "CHAT2API_LAUNCHER_CHECKOUT is not set; cross-target acceptance requires "
            "an explicit chat2api checkout"
        )
    if not (CHECKOUT / "app").is_dir():
        pytest.skip(f"Target B checkout not available at {CHECKOUT}")
    return CHECKOUT


def _free_port() -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port != PRODUCTION_PORT:
            return port


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _virtualenv(checkout: Path) -> Path | None:
    """Locate a virtualenv that can import the service's dependencies.

    Worktrees do not carry ``.venv`` (it is untracked), so fall back to the canonical
    checkout's virtualenv, then to the running interpreter's own prefix.
    """
    import sys

    candidates = [
        checkout / ".venv",
        checkout / "venv",
        Path("/data/home/guest/Development/ai/chat2api/.venv"),
        Path("/data/home/guest/Development/ai/chat2api/venv"),
        Path(sys.prefix),
    ]
    for candidate in candidates:
        if (candidate / "bin" / "activate").is_file():
            return candidate
    return None


def _sandbox(tmp_path: Path, launcher_text: str) -> tuple[Path, int]:
    """Build a temporary app root containing *launcher_text* and the real packages.

    ``start.sh`` does ``cd -- "$(dirname -- "$0")"``, so the launcher must live in the
    sandbox and the packages plus interpreter must resolve from there.
    """
    checkout = _require_checkout()

    root = tmp_path / "root"
    root.mkdir()
    script = root / "start.sh"
    script.write_text(launcher_text, encoding="utf-8")
    script.chmod(0o755)

    for package in ("app", "providers"):
        (root / package).symlink_to(checkout / package, target_is_directory=True)
    venv = _virtualenv(checkout)
    if venv is not None:
        (root / ".venv").symlink_to(venv, target_is_directory=True)

    port = _free_port()
    (root / "config.json").write_text(
        json.dumps(
            {
                "server": {"host": "127.0.0.1", "port": port, "auth_token_env": None},
                "models": {"echo-1": {"provider": "echo"}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "config.json").chmod(0o600)
    return root, port


def _fixed_launcher() -> str:
    launcher = _require_checkout() / "start.sh"
    if not launcher.is_file():
        pytest.skip(f"no launcher at {launcher}")
    return launcher.read_text(encoding="utf-8")


def _baseline_launcher() -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(_require_checkout()), "show", f"{BASELINE_COMMIT}:start.sh"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("baseline launcher revision unavailable")
    return completed.stdout


def test_fixed_launcher_passes_the_gate(tmp_path: Path) -> None:
    root, port = _sandbox(tmp_path, _fixed_launcher())

    result = probe_launcher(root)

    assert result.passed is True, result.detail
    reported = [line.strip() for line in result.stdout.splitlines() if line.strip()][-1]
    assert reported == str(port)
    assert not _listening(port), "the gate must not bind the port it reports"


def test_baseline_launcher_fails_closed(tmp_path: Path) -> None:
    """The pre-fix launcher has no capability flag, so the gate must refuse it.

    This is the direction that matters for safety: an installed-but-stale launcher
    must disable listener editing rather than silently claiming support.
    """
    root, port = _sandbox(tmp_path, _baseline_launcher())

    result = probe_launcher(root)

    assert result.passed is False
    assert result.detail
    assert not _listening(port), "a refused launcher must not bind anything"


def test_gate_reports_the_configured_port_not_a_default(tmp_path: Path) -> None:
    """A fixed launcher must report the config value, never a hardcoded default."""
    root, port = _sandbox(tmp_path, _fixed_launcher())

    result = probe_launcher(root)

    assert result.passed is True, result.detail
    reported = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert reported[-2:] == ["127.0.0.1", str(port)]
    assert str(PRODUCTION_PORT) != str(port)
    assert reported[-1] != str(PRODUCTION_PORT)
