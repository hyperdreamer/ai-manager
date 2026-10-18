from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
import tempfile
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
        self._staged: dict[Path, Path] = {}
        self._locks: list[int] = []
        self._temps: set[Path] = set()

    def __enter__(self) -> Transaction:
        if self._entered or self._state != "initial":
            raise ValueError("A transaction context may be entered once.")
        self._entered = True
        return self

    def _release(self) -> None:
        """Unlock and close every descriptor, even if one of them fails.

        An individual unlock or close failure must not strand the remaining
        sidecar locks for the process lifetime, so failures are collected while
        the loop keeps draining ``_locks``. The first failure is re-raised only
        after every descriptor has been unlocked and closed.
        """
        first_error: BaseException | None = None
        while self._locks:
            fd = self._locks.pop()
            try:
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        break
                    except InterruptedError:
                        continue
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
            finally:
                try:
                    os.close(fd)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        cleanup_error: BaseException | None = None
        try:
            for path in tuple(self._temps):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # Only unconsumed private temps; no target-state assertion
                    # depends on deletion.
                    pass
                self._temps.discard(path)
        except BaseException as exc:
            cleanup_error = exc
        finally:
            try:
                self._release()
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            finally:
                # Context state is finalized before any cleanup error escapes.
                self._entered = False
                self._state = "closed"
        if cleanup_error is not None:
            raise cleanup_error
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
            try:
                self._release()
            except BaseException:
                # The primary prepare failure is the meaningful error; every
                # descriptor was still unlocked and closed above.
                pass
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

    def _write_temp(self, path: Path, raw: bytes, mode: int, label: str) -> Path:
        fd, name = tempfile.mkstemp(
            prefix=f".{path.name}.ai-manager-{label}-", suffix=".tmp", dir=path.parent
        )
        temp = Path(name)
        self._temps.add(temp)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
            return temp
        except BaseException:
            temp.unlink(missing_ok=True)
            self._temps.discard(temp)
            raise

    def stage(self, rendered: dict[Path, bytes]) -> None:
        self._require("backed-up")
        if set(rendered) != set(self._paths) or any(
            type(value) is not bytes for value in rendered.values()
        ):
            raise ValueError(
                "Stage requires exactly the prepared paths and sealed byte values."
            )
        self._staged = {}
        try:
            for path in self._paths:
                self._staged[path] = self._write_temp(
                    path, rendered[path], self.original_mode(path), "stage"
                )
            self._state = "staged"
        except OSError as exc:
            self._state = "failed"
            raise TransactionError(
                self._report(
                    "stage",
                    "Could not stage configuration files; no configuration "
                    f"files were changed. {exc}",
                )
            ) from exc

    def replace_all(self) -> TransactionReport:
        self._require("staged")
        self._state = "replacing"
        replaced: list[Path] = []
        report = TransactionReport("replace_all", backups=self._backups.copy())
        path = self._paths[0]
        try:
            for path in self._paths:
                os.replace(self._staged[path], path)
                replaced.append(path)
                report.replaced = tuple(replaced)
                self._temps.discard(self._staged[path])
                self._fsync_dir(path.parent)
                report.files[path] = "new"
            report.phase, report.committed = "complete", True
            self._state = "complete"
            return report
        except OSError as exc:
            report.error = f"Configuration save failed at {path}: {exc}"
            for untouched in self._paths:
                if untouched not in replaced:
                    report.files[untouched] = (
                        "restored" if self._verify_original(untouched) else "unknown"
                    )
            recovered = self.rollback(report)
            raise TransactionError(recovered) from exc

    def rollback(self, report: TransactionReport) -> TransactionReport:
        self._require("replacing")
        self._state = "rolling-back"
        report.phase, report.committed = "rollback", False
        for path in reversed(report.replaced):
            try:
                old, mode = self._original[path]
                if old is None:
                    path.unlink()
                    self._fsync_dir(path.parent)
                else:
                    backup = self._backups[path]
                    restored = backup.read_bytes()
                    if restored != old:
                        raise OSError("Backup no longer matches the prepared bytes.")
                    temp = self._write_temp(path, restored, mode, "restore")
                    os.replace(temp, path)
                    self._temps.discard(temp)
                    self._fsync_dir(path.parent)
                if not self._verify_original(path):
                    raise OSError("Restoration could not be verified.")
                report.files[path] = "restored"
            except Exception as exc:
                report.files[path] = "unknown"
                report.restore_failures[path] = str(exc)
        for path in self._paths:
            report.files.setdefault(
                path, "restored" if self._verify_original(path) else "unknown"
            )
        self._state = "failed"
        return report
