from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

from ai_manager.config.config_errors import (
    ConfigLoadError,
    ReadOnlyConfigError,
    StaleDocumentError,
    SymlinkConfigError,
    TransactionError,
)
from ai_manager.config.structured_config import _snapshot
from ai_manager.config.structured_models import TransactionReport


def _canonical(path: Path) -> Path:
    requested = Path(os.path.abspath(path))
    try:
        for candidate in (requested, requested.parent.resolve() / requested.name):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise SymlinkConfigError(requested)
            if not stat.S_ISREG(info.st_mode):
                raise ConfigLoadError(
                    requested, "Configuration path must be a regular file."
                )
        return requested.parent.resolve() / requested.name
    except (OSError, RuntimeError) as exc:
        raise ConfigLoadError(requested, str(exc)) from exc


class Transaction:
    def __init__(self) -> None:
        self._state = "initial"
        self._entered = False
        self._paths: tuple[Path, ...] = ()
        self._original: dict[Path, tuple[bytes | None, int | None]] = {}
        self._backups: dict[Path, Path] = {}
        self._locks: list[int] = []
        self._temps: set[Path] = set()

    def __enter__(self) -> Transaction:
        if self._entered or self._state != "initial":
            raise ValueError("A transaction context may be entered once.")
        self._entered = True
        return self

    def _release(self) -> None:
        while self._locks:
            fd = self._locks.pop()
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            for path in tuple(self._temps):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # Only unconsumed private temps; no target-state assertion
                    # depends on deletion.
                    pass
                self._temps.discard(path)
        finally:
            self._release()
            self._entered = False
            self._state = "closed"
        return False

    def _require(self, state: str) -> None:
        if not self._entered or self._state != state:
            raise ValueError(f"Expected transaction state {state}; got {self._state}.")

    def _fsync_dir(self, parent: Path) -> None:
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def prepare(
        self, paths: list[Path], expected: dict[Path, bytes | None]
    ) -> None:
        self._require("initial")
        if not paths or len(paths) != len(set(paths)) or set(paths) != set(expected):
            raise ValueError(
                "Paths and expected hashes must have the same nonempty unique key set."
            )
        if any(
            value is not None and (type(value) is not bytes or len(value) != 32)
            for value in expected.values()
        ):
            raise ValueError(
                "Expected digests must be 32-byte SHA-256 values or None."
            )
        canonical = {p: _canonical(p) for p in paths}
        if len(set(canonical.values())) != len(paths):
            raise ValueError("Duplicate canonical configuration paths.")
        hashes = {canonical[p]: expected[p] for p in paths}
        self._paths = tuple(sorted(canonical.values(), key=str))
        try:
            for path in self._paths:
                lock = path.with_name(path.name + ".lock")
                fd = os.open(
                    lock,
                    os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                )
                self._locks.append(fd)
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX)
                        break
                    except InterruptedError:
                        continue
            for path in self._paths:
                resolved, raw, mode, reasons = _snapshot(path)
                if resolved != path:
                    raise ConfigLoadError(
                        path, "Configuration parent changed during prepare."
                    )
                if reasons or not os.access(path.parent, os.W_OK | os.X_OK):
                    raise ReadOnlyConfigError(
                        path, "Configuration is not writable; editing is disabled."
                    )
                actual = None if raw is None else hashlib.sha256(raw).digest()
                if actual != hashes[path]:
                    raise StaleDocumentError(path, hashes[path], actual)
                self._original[path] = (raw, mode)
            self._state = "prepared"
        except BaseException:
            self._release()
            self._state = "failed"
            raise

    def original_mode(self, path: Path) -> int:
        if path not in self._original:
            raise ValueError("Path was not prepared.")
        mode = self._original[path][1]
        return mode if mode is not None else 0o600

    def _verify_original(self, path: Path) -> bool:
        try:
            resolved, raw, mode, _reasons = _snapshot(path)
            return resolved == path and (raw, mode) == self._original[path]
        except Exception:
            return False

    def _report(self, phase, error: str) -> TransactionReport:
        return TransactionReport(
            phase,
            files={
                p: "restored" if self._verify_original(p) else "unknown"
                for p in self._paths
            },
            backups=self._backups.copy(),
            error=error,
        )

    def backups(self) -> None:
        self._require("prepared")
        active: Path | None = None
        fd: int | None = None
        try:
            for path in self._paths:
                raw, mode = self._original[path]
                if raw is None:
                    continue
                while True:
                    timestamp = datetime.now(timezone.utc).strftime(
                        "%Y%m%dT%H%M%S%fZ"
                    )
                    backup = path.with_name(
                        f"{path.name}.{timestamp}.{os.getpid()}-"
                        f"{secrets.token_hex(3)}.bak"
                    )
                    try:
                        fd = os.open(
                            backup,
                            os.O_WRONLY
                            | os.O_CREAT
                            | os.O_EXCL
                            | os.O_CLOEXEC,
                            0o600,
                        )
                        break
                    except FileExistsError:
                        continue
                active = backup
                with os.fdopen(fd, "wb") as stream:
                    fd = None
                    stream.write(raw)
                    stream.flush()
                    if mode is not None:
                        os.fchmod(stream.fileno(), mode)
                    os.fsync(stream.fileno())
                self._fsync_dir(path.parent)
                self._backups[path] = backup
                active = None
            self._state = "backed-up"
        except OSError as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if active is not None:
                try:
                    active.unlink(missing_ok=True)
                except OSError:
                    pass
            self._state = "failed"
            raise TransactionError(
                self._report(
                    "backups",
                    "Could not create all backups; no configuration files were "
                    f"changed. {exc}",
                )
            ) from exc
        except BaseException:
            # A non-OSError interruption must not leave the transaction able to
            # create a second set of backups for already-backed-up targets.
            self._state = "failed"
            raise
