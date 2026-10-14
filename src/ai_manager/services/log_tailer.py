"""Bounded incremental reader for a single service log file.

Pure Python (no Qt imports).  Implements the normative contract in
``docs/superpowers/specs/2026-10-14-live-service-logs-spec.md`` section 3.1:
every call stats before reading, reset reads are bounded by ``initial_bytes``,
every ``read(n)`` request is bounded by ``max_batch_bytes``, and untrusted log
bytes are decoded as UTF-8 with ``errors="replace"``.
"""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, List, Optional, Tuple, Union

_TRUNCATION_MARKER = " \u2026[line truncated]"
_MISSING_ERRNOS = (errno.ENOENT, errno.ENOTDIR)


class LogFileStatus(str, Enum):
    UNSET = "unset"
    OK = "ok"
    MISSING = "missing"
    UNREADABLE = "unreadable"


class FilePresence(str, Enum):
    UNSET = "unset"
    MISSING = "missing"
    PRESENT = "present"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LogReadBatch:
    lines: List[str]
    status: LogFileStatus = LogFileStatus.OK
    reset: Optional[str] = None
    error: Optional[str] = None
    more_pending: bool = False


def _open_file(path: Path) -> BinaryIO:
    """Open ``path`` in binary mode.

    This module-level helper is the only file-open seam; tests replace it with a
    wrapper whose ``read(n)`` records every request.
    """
    return open(path, "rb")


def _missing_message(path: Path) -> str:
    return f"Log file not found: {path}"


def _error_message(exc: OSError) -> str:
    return f"Cannot read log file: {exc}"


class LogTailReader:
    """Incremental, rotation-tolerant reader for one append-only log file.

    All incremental state belongs to the single target path: byte offset,
    ``(st_dev, st_ino)`` identity, size, ``mtime_ns``, a trailing partial line,
    an over-long-line discard flag, and the last read-observed error.
    """

    def __init__(
        self,
        *,
        initial_bytes: int = 65_536,
        max_batch_bytes: int = 262_144,
        max_line_bytes: int = 16_384,
    ) -> None:
        self._initial_bytes = initial_bytes
        self._max_batch_bytes = max_batch_bytes
        self._max_line_bytes = max_line_bytes
        self._path: Optional[Path] = None
        self._offset = 0
        self._identity: Optional[Tuple[int, int]] = None
        self._size = 0
        self._mtime_ns = 0
        self._partial = b""
        self._discarding = False
        self._saw_missing = False
        self._last_error: Optional[str] = None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def set_path(self, path: Optional[Union[str, Path]]) -> bool:
        """Point the reader at a log file; ``True`` when the target changed.

        Changing the normalized target resets byte offset, identity, size,
        ``mtime_ns``, partial-line bytes, over-long-line discard state, pending
        reset state, and the retained read error.
        """
        new_path = None if path is None else Path(os.fspath(path))
        if new_path == self._path:
            return False
        self._path = new_path
        self._offset = 0
        self._identity = None
        self._size = 0
        self._mtime_ns = 0
        self._partial = b""
        self._discarding = False
        self._saw_missing = False
        self._last_error = None
        return True

    def probe_health(self) -> Tuple[FilePresence, Optional[str]]:
        """stat-only presence check used while paused.

        Never opens, reads, advances the offset, mutates reader state, or claims
        readability.
        """
        path = self._path
        if path is None:
            return FilePresence.UNSET, None
        try:
            os.stat(path)
        except OSError as exc:
            if exc.errno in _MISSING_ERRNOS:
                return FilePresence.MISSING, _missing_message(path)
            return FilePresence.UNAVAILABLE, _error_message(exc)
        return FilePresence.PRESENT, None

    def read_new_lines(self) -> LogReadBatch:
        """Return up to ``max_batch_bytes`` of newly appended content."""
        path = self._path
        if path is None:
            return LogReadBatch([], LogFileStatus.UNSET)

        try:
            stat = os.stat(path)
        except OSError as exc:
            if exc.errno in _MISSING_ERRNOS:
                self._saw_missing = True
                error = _missing_message(path)
                self._last_error = error
                return LogReadBatch([], LogFileStatus.MISSING, error=error)
            error = _error_message(exc)
            self._last_error = error
            return LogReadBatch([], LogFileStatus.UNREADABLE, error=error)

        identity = (stat.st_dev, stat.st_ino)
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns
        reset = self._classify_reset(identity, size, mtime_ns)

        if reset is None and size == self._offset:
            # Unchanged metadata and consumption already at EOF: one stat only.
            self._last_error = None
            return LogReadBatch([], LogFileStatus.OK)

        if reset is not None:
            offset = max(0, size - self._initial_bytes)
            partial = b""
            discarding = offset > 0
        else:
            offset = self._offset
            partial = self._partial
            discarding = self._discarding

        lines: List[str] = []
        budget = self._max_batch_bytes
        try:
            with _open_file(path) as handle:
                handle.seek(offset)
                limit = size - offset
                while budget > 0 and limit > 0:
                    chunk = handle.read(min(budget, limit))
                    if not chunk:
                        break
                    partial, discarding = self._consume(
                        chunk, lines, partial, discarding
                    )
                    budget -= len(chunk)
                    offset += len(chunk)
                    limit -= len(chunk)
        except OSError as exc:
            if exc.errno in _MISSING_ERRNOS:
                self._saw_missing = True
                error = _missing_message(path)
                self._last_error = error
                return LogReadBatch([], LogFileStatus.MISSING, error=error)
            error = _error_message(exc)
            self._last_error = error
            # Offsets / partial bytes / discard state are retained: a transient
            # failure resumes later without duplication.
            return LogReadBatch([], LogFileStatus.UNREADABLE, error=error)

        self._offset = offset
        self._partial = partial
        self._discarding = discarding
        self._identity = identity
        self._size = size
        self._mtime_ns = mtime_ns
        self._saw_missing = False
        self._last_error = None
        return LogReadBatch(
            lines,
            LogFileStatus.OK,
            reset=reset,
            more_pending=offset < size,
        )

    def _classify_reset(
        self, identity: Tuple[int, int], size: int, mtime_ns: int
    ) -> Optional[str]:
        """Return the reset marker implied by the observed metadata, if any."""
        if self._identity is None or self._saw_missing:
            return "created"
        if identity != self._identity:
            return "rotated"
        if size < self._offset:
            return "truncated"
        if size == self._offset and mtime_ns != self._mtime_ns:
            return "truncated"
        return None

    def _consume(
        self, data: bytes, lines: List[str], partial: bytes, discarding: bool
    ) -> Tuple[bytes, bool]:
        """Split ``data`` into complete lines, buffering the trailing partial."""
        index = 0
        length = len(data)
        while index < length:
            if discarding:
                newline = data.find(b"\n", index)
                if newline == -1:
                    break
                discarding = False
                index = newline + 1
                continue

            newline = data.find(b"\n", index)
            if newline == -1:
                partial += data[index:]
                if len(partial) > self._max_line_bytes:
                    lines.append(
                        partial[: self._max_line_bytes].decode("utf-8", "replace")
                        + _TRUNCATION_MARKER
                    )
                    partial = b""
                    discarding = True
                break

            combined = partial + data[index:newline]
            if len(combined) > self._max_line_bytes:
                lines.append(
                    combined[: self._max_line_bytes].decode("utf-8", "replace")
                    + _TRUNCATION_MARKER
                )
            else:
                lines.append(combined.decode("utf-8", "replace"))
            partial = b""
            index = newline + 1
        return partial, discarding
