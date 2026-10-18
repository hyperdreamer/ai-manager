"""Stage 3: best-effort service configuration validation.

Renders check nothing here; the caller passes already-rendered bytes. The
candidate is written to a hidden adjacent file with mode ``0o600`` and is
always removed after the validator has exited or been reaped.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from ai_manager.config.config_errors import (
    ConfigError,
    InterpreterUnavailableError,
    ServiceValidationError,
    ServiceValidationTimeout,
    UnknownConfigKindError,
)
from ai_manager.config.structured_models import StructuredKind, ValidationResult
from ai_manager.services.app_interpreter import (
    resolve_app_interpreter,
    verify_app_interpreter,
)

VALIDATOR_TIMEOUT_S = 10.0
DEGRADED_NOTICE = "validated by ai-manager only — service validator unavailable"
IMPORT_UNAVAILABLE_EXIT = 75

CHAT2API_VALIDATE_PROGRAM = '''import sys
try:
    from app.config import load_config
    from app.registry import Registry
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
try:
    cfg = load_config(sys.argv[1])
    Registry(cfg)
    cfg.validate_auth()
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
'''
FILE_BRIDGE_VALIDATE_PROGRAM = '''import sys
from pathlib import Path
try:
    import main
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
cfg = main.load_config(Path(sys.argv[1]))
main._probe_save_root(cfg.save_root)
'''

VALIDATE_PROGRAMS: dict[str, str] = {
    "chat2api": CHAT2API_VALIDATE_PROGRAM,
    "file-bridge": FILE_BRIDGE_VALIDATE_PROGRAM,
}


def validate_candidate(
    kind: StructuredKind, target_path: Path, app_dir: Path, rendered: bytes
) -> ValidationResult:
    """Validate ``rendered`` bytes for ``kind`` against the real service.

    Unavailable interpreter/imports degrade to manager-only scope. Rejection,
    timeout and local I/O failures raise; none of them may be mistaken for a
    successful or degraded validation.
    """
    try:
        program = VALIDATE_PROGRAMS[kind]
    except KeyError:
        raise UnknownConfigKindError(kind) from None
    try:
        interpreter = resolve_app_interpreter(app_dir)
        verify_app_interpreter(kind, app_dir, interpreter)
    except InterpreterUnavailableError as exc:
        return ValidationResult("manager-only", DEGRADED_NOTICE, str(exc))
    target = target_path.parent.resolve() / target_path.name
    candidate: Path | None = None
    try:
        fd, name = tempfile.mkstemp(
            prefix=f".{target.name}.ai-manager-validate-",
            suffix=target.suffix,
            dir=target.parent,
        )
        candidate = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        child = subprocess.Popen(
            [str(interpreter), "-c", program, str(candidate)],
            cwd=app_dir.resolve(),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            stdout, stderr = child.communicate(timeout=VALIDATOR_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            child.kill()
            stdout, stderr = child.communicate()
            raise ServiceValidationTimeout(stdout, stderr) from exc
        if child.returncode == IMPORT_UNAVAILABLE_EXIT:
            return ValidationResult("manager-only", DEGRADED_NOTICE, stdout + stderr)
        if child.returncode != 0:
            raise ServiceValidationError(child.returncode, stdout, stderr)
        return ValidationResult(
            "service", f"configuration valid — validated by {kind} · ai-manager"
        )
    except OSError as exc:
        raise ConfigError(f"Configuration save failed: {exc}") from exc
    finally:
        if candidate is not None:
            try:
                candidate.unlink()
            except OSError as exc:
                raise ConfigError(f"Configuration save failed: {exc}") from exc
