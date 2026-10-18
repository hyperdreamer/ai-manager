"""Selection and verification of an application's launch interpreter.

Selection follows activation-file precedence so the manager validates with the
same interpreter the launcher would bind. The selected path is preserved
lexically: a virtualenv ``python`` symlink is never resolved to its base
interpreter, because that would change virtualenv selection.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from ai_manager.config.config_errors import (
    InterpreterUnavailableError,
    UnknownConfigKindError,
)
from ai_manager.config.structured_models import StructuredKind

IMPORT_TIMEOUT_S = 10.0

IMPORT_PROGRAMS: dict[str, str] = {
    "chat2api": "import app, fastapi",
    "file-bridge": "import main, fastapi",
}


def resolve_app_interpreter(app_dir: Path) -> Path:
    """Return the absolute, lexical interpreter path for ``app_dir``.

    Precedence: ``.venv/bin/activate``, then ``venv/bin/activate``, then
    ``python`` on PATH. A selected-but-broken interpreter is unavailable; it
    never falls back to a different environment.
    """
    directory = app_dir.resolve()
    selected: Path | None = None
    for env in (".venv", "venv"):
        if (directory / env / "bin/activate").is_file():
            selected = directory / env / "bin/python"
            break
    if selected is None:
        ambient = shutil.which("python")
        if ambient is not None:
            selected = Path(os.path.abspath(ambient))
    if selected is None or not selected.is_file() or not os.access(selected, os.X_OK):
        raise InterpreterUnavailableError(
            f"Application interpreter is unavailable: {selected or 'python on PATH'}"
        )
    return selected


def verify_app_interpreter(
    kind: StructuredKind, app_dir: Path, interpreter: Path
) -> None:
    """Run the import probe for ``kind`` with ``interpreter``.

    A spawn error, nonzero exit or timeout raises ``InterpreterUnavailableError``.
    The probe process is always reaped.
    """
    if not isinstance(kind, str):
        raise UnknownConfigKindError(kind)
    try:
        program = IMPORT_PROGRAMS[kind]
    except KeyError:
        raise UnknownConfigKindError(kind) from None
    try:
        child = subprocess.Popen(
            [str(interpreter), "-c", program],
            cwd=app_dir.resolve(),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise InterpreterUnavailableError(str(exc)) from exc
    try:
        stdout, stderr = child.communicate(timeout=IMPORT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        child.kill()
        stdout, stderr = child.communicate()
        raise InterpreterUnavailableError(
            f"Interpreter import probe timed out.\n{stdout}{stderr}"
        ) from exc
    if child.returncode != 0:
        raise InterpreterUnavailableError(
            f"Interpreter import probe exited {child.returncode}.\n{stdout}{stderr}"
        )
