from __future__ import annotations
import hashlib
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from ai_manager.config.models import AppAIConfig, AppMetadata

StructuredKind = Literal["chat2api", "file-bridge"]
KeyPath = tuple[str, ...]
ReadOnlyReason = Literal["symlink", "non-writable", "yaml-anchors-aliases", "non-dict-root", "load-error", "missing-config"]
FinalFileState = Literal["new", "restored", "unknown"]
TransactionPhase = Literal["prepare", "backups", "stage", "replace_all", "rollback", "complete"]


@dataclass(frozen=True)
class FieldIssue:
    address: KeyPath
    message: str


@dataclass(frozen=True)
class Mutation:
    address: KeyPath
    operation: Literal["set", "delete"]
    value: Any = None

    def __post_init__(self) -> None:
        if type(self.address) is not tuple or not self.address or any(type(k) is not str for k in self.address):
            raise ValueError("A mutation address must be a non-empty tuple of string keys.")
        if self.operation not in ("set", "delete"):
            raise ValueError("Mutation operation must be set or delete.")
        if self.operation == "delete" and self.value is not None:
            raise ValueError("A delete mutation cannot carry a value.")


@dataclass(frozen=True)
class StructuredDoc:
    kind: StructuredKind
    path: Path
    resolved_path: Path
    doc: MutableMapping[str, Any]
    raw_bytes: bytes
    raw_sha256: bytes | None
    existed: bool
    mode: int | None
    read_only_reasons: tuple[ReadOnlyReason, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    raw_option_edits: dict[str, str] = field(default_factory=dict)
    input_issues: tuple[FieldIssue, ...] = ()
    create_requested: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ("chat2api", "file-bridge"):
            raise ValueError("StructuredDoc kind must be chat2api or file-bridge.")
        if not isinstance(self.doc, MutableMapping):
            raise ValueError("StructuredDoc.doc must be a mapping.")
        if self.existed:
            if self.raw_sha256 != hashlib.sha256(self.raw_bytes).digest():
                raise ValueError("raw_sha256 must hash raw_bytes.")
            if self.mode is None:
                raise ValueError("An existing document must retain its mode.")
        elif self.raw_bytes != b"" or self.raw_sha256 is not None or self.mode is not None:
            raise ValueError("An absent document has no bytes, digest, or mode.")


@dataclass(frozen=True)
class ValidationResult:
    scope: Literal["service", "manager-only"]
    notice: str
    detail: str = ""


@dataclass
class TransactionReport:
    phase: TransactionPhase
    files: dict[Path, FinalFileState] = field(default_factory=dict)
    backups: dict[Path, Path] = field(default_factory=dict)
    replaced: tuple[Path, ...] = ()
    restore_failures: dict[Path, str] = field(default_factory=dict)
    error: str | None = None
    committed: bool = False


@dataclass(frozen=True)
class SaveResult:
    document: StructuredDoc
    transaction: TransactionReport
    validation: ValidationResult
    saved_dependents: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class DependentMatch:
    meta: AppMetadata
    path: Path
    doc: MutableMapping[str, Any]
    raw_bytes: bytes
    raw_sha256: bytes
    saved_config: AppAIConfig
    old_api_base: str
    new_api_base: str
    auth_warning: str | None = None


@dataclass(frozen=True)
class LauncherProbeResult:
    passed: bool
    detail: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
