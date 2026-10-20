from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_manager.config.structured_models import FieldIssue, TransactionReport


class ConfigError(Exception):
    pass


class UnknownConfigKindError(ConfigError, ValueError):
    def __init__(self, kind: object) -> None:
        super().__init__(
            f"Unknown config_kind {kind!r}; expected llm, chat2api, or file-bridge."
        )
        self.kind = kind


class ConfigLoadError(ConfigError):
    def __init__(self, path: Path, detail: str, reason: str = "load-error") -> None:
        super().__init__(f"Cannot load configuration {path}: {detail}")
        self.path = path
        self.detail = detail
        self.reason = reason


class ConfigShapeError(ConfigLoadError):
    pass


class SymlinkConfigError(ConfigLoadError):
    def __init__(self, path: Path) -> None:
        super().__init__(
            path, "Configuration path is a symlink; editing is disabled.", "symlink"
        )


class ReadOnlyConfigError(ConfigError):
    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.detail = detail


class MissingExampleError(ConfigLoadError):
    pass


class ConfigValidationError(ConfigError):
    def __init__(self, issues: tuple[FieldIssue, ...]) -> None:
        super().__init__("Configuration has invalid fields; nothing was saved.")
        self.issues = issues


class ServiceValidationError(ConfigError):
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        super().__init__("Service validator rejected the configuration; nothing was saved.")
        self.returncode = returncode
        # Redact in the type, not at the call site: a diagnostic that carries a
        # credential must be safe no matter who constructs or displays it.
        from ai_manager.services.launcher_gate import redact_diagnostics

        self.stdout = redact_diagnostics(stdout)
        self.stderr = redact_diagnostics(stderr)


class ServiceValidationTimeout(ConfigError):
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        super().__init__("Service validator timed out after 10 seconds; nothing was saved.")
        from ai_manager.services.launcher_gate import redact_diagnostics

        self.stdout = redact_diagnostics(stdout)
        self.stderr = redact_diagnostics(stderr)


class InterpreterUnavailableError(ConfigError):
    pass


class StaleDocumentError(ConfigError):
    def __init__(
        self, path: Path, expected_sha256: bytes | None, actual_sha256: bytes | None
    ) -> None:
        super().__init__("Configuration changed on disk; save refused.")
        self.path = path
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256


class TransactionError(ConfigError):
    def __init__(self, report: TransactionReport) -> None:
        super().__init__(report.error or "Configuration transaction failed.")
        self.report = report


def require_llm(meta) -> None:
    if meta.config_kind not in ("llm", "chat2api", "file-bridge"):
        raise UnknownConfigKindError(meta.config_kind)
    if meta.config_kind != "llm":
        raise ConfigError(f"{meta.id} requires its {meta.config_kind} configuration adapter.")
