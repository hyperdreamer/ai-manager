"""Pure unit tests for the bounded incremental log tail reader (LT-01 .. LT-20).

Every file is created from explicit byte fixtures under ``tmp_path``.  File
opens go through the module-level ``_open_file`` seam so a recording wrapper can
prove that no ``read(n)`` ever exceeds ``max_batch_bytes``.
"""

import os
from typing import List

import pytest

from ai_manager.services import log_tailer
from ai_manager.services.log_tailer import (
    FilePresence,
    LogFileStatus,
    LogReadBatch,
    LogTailReader,
)

TRUNCATION_MARKER = " \u2026[line truncated]"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


class RecordingHandle:
    """Wrap a binary handle and record every ``read(n)`` request."""

    def __init__(self, raw, reads):
        self._raw, self._reads = raw, reads

    def __enter__(self):
        self._raw.__enter__()
        return self

    def __exit__(self, *args):
        return self._raw.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def read(self, size=-1):
        self._reads.append(size)
        return self._raw.read(size)


@pytest.fixture
def recorded_reads(monkeypatch):
    """Patch the seam and return the list of every requested read size."""
    sizes: List[int] = []
    real_open_file = log_tailer._open_file

    def recording_open(path):
        return RecordingHandle(real_open_file(path), sizes)

    monkeypatch.setattr(log_tailer, "_open_file", recording_open)
    return sizes


def collect_lines(batches: List[LogReadBatch]) -> List[str]:
    return [line for batch in batches for line in batch.lines]


def drain_with_bounds(reader: LogTailReader, recorded_reads: List[int]):
    """Drain ``reader`` and return ``(batches, per-call byte costs)``."""
    batches: List[LogReadBatch] = []
    costs: List[int] = []
    while True:
        mark = len(recorded_reads)
        batch = reader.read_new_lines()
        batches.append(batch)
        costs.append(sum(recorded_reads[mark:]))
        assert len(batches) < 1000, "reader never finished draining"
        if not batch.more_pending:
            return batches, costs


# ---------------------------------------------------------------------------
# LT-01 .. LT-04: unset, missing, stat-only probe, unreadable retention
# ---------------------------------------------------------------------------


def test_lt_01_unset_path_returns_unset_batch(monkeypatch):
    def forbidden(_path):
        raise AssertionError("an unset reader must not open files")

    monkeypatch.setattr(log_tailer, "_open_file", forbidden)
    reader = LogTailReader()
    assert reader.path is None
    assert reader.read_new_lines() == LogReadBatch([], LogFileStatus.UNSET)
    assert reader.probe_health() == (FilePresence.UNSET, None)
    assert reader.set_path(None) is False


def test_lt_02_absent_path_reports_missing_with_reason(tmp_path):
    missing = tmp_path / "missing.log"
    reader = LogTailReader()
    assert reader.set_path(missing) is True

    first = reader.read_new_lines()
    second = reader.read_new_lines()
    for batch in (first, second):
        assert batch.status is LogFileStatus.MISSING
        assert batch.lines == []
        assert batch.reset is None
        assert batch.error
        assert "not found" in batch.error.lower()
        assert str(missing) in batch.error

    presence, reason = reader.probe_health()
    assert presence is FilePresence.MISSING
    assert reason and "not found" in reason.lower()

    # ENOTDIR (a parent that is a regular file) is missing, not unreadable.
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"not a directory")
    reader2 = LogTailReader()
    reader2.set_path(blocker / "child.log")
    batch = reader2.read_new_lines()
    assert batch.status is LogFileStatus.MISSING
    assert batch.error


def test_lt_03_probe_health_is_stat_only_and_side_effect_free(tmp_path, monkeypatch):
    present = tmp_path / "present.log"
    present.write_bytes(b"one\ntwo\n")
    missing = tmp_path / "missing.log"

    def forbidden(_path):
        raise AssertionError("probe_health must not open files")

    monkeypatch.setattr(log_tailer, "_open_file", forbidden)

    reader = LogTailReader()
    reader.set_path(present)
    before = dict(reader.__dict__)
    assert reader.probe_health() == (FilePresence.PRESENT, None)
    assert dict(reader.__dict__) == before

    missing_reader = LogTailReader()
    missing_reader.set_path(missing)
    before_missing = dict(missing_reader.__dict__)
    presence, reason = missing_reader.probe_health()
    assert presence is FilePresence.MISSING
    assert reason and str(missing) in reason
    assert dict(missing_reader.__dict__) == before_missing


@pytest.mark.skipif(IS_ROOT, reason="root can stat through mode 000 parents")
def test_lt_03_probe_reports_unavailable_for_locked_parent(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    target = locked / "svc.log"
    target.write_bytes(b"data\n")
    locked.chmod(0o000)
    try:
        reader = LogTailReader()
        reader.set_path(target)
        before = dict(reader.__dict__)
        presence, reason = reader.probe_health()
        assert presence is FilePresence.UNAVAILABLE
        assert reason and "Permission denied" in reason
        assert dict(reader.__dict__) == before
    finally:
        locked.chmod(0o700)


def test_lt_03_probe_does_not_advance_offset(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"first\n")
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["first"]
    assert recorded_reads == [6]

    assert reader.probe_health() == (FilePresence.PRESENT, None)
    assert reader.read_new_lines() == LogReadBatch([], LogFileStatus.OK)
    assert recorded_reads == [6]

    with path.open("ab") as handle:
        handle.write(b"second\n")
    assert reader.probe_health() == (FilePresence.PRESENT, None)
    assert recorded_reads == [6]
    assert reader.read_new_lines().lines == ["second"]
    assert recorded_reads == [6, 7]


def test_lt_04_unreadable_open_failure_retains_state_and_recovers(tmp_path, monkeypatch):
    path = tmp_path / "svc.log"
    path.write_bytes(b"first\n")
    reader = LogTailReader(initial_bytes=4096)
    assert reader.set_path(path) is True

    first = reader.read_new_lines()
    assert first.status is LogFileStatus.OK
    assert first.reset == "created"
    assert first.lines == ["first"]

    with path.open("ab") as handle:
        handle.write(b"partial")
    second = reader.read_new_lines()
    assert second.status is LogFileStatus.OK
    assert second.lines == []
    assert reader._offset == 13
    assert reader._partial == b"partial"

    # Keep unconsumed input available so the call actually reaches the open seam.
    with path.open("ab") as handle:
        handle.write(b" ")

    real_open_file = log_tailer._open_file

    def denied(_path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(log_tailer, "_open_file", denied)
    unreadable = reader.read_new_lines()
    assert unreadable.status is LogFileStatus.UNREADABLE
    assert unreadable.reset is None
    assert unreadable.lines == []
    assert unreadable.error and "Permission denied" in unreadable.error
    # offset and partial bytes are retained across the transient failure
    assert reader._offset == 13
    assert reader._partial == b"partial"

    monkeypatch.setattr(log_tailer, "_open_file", real_open_file)
    path.write_bytes(b"first\npartial done\n")
    recovered = reader.read_new_lines()
    assert recovered.status is LogFileStatus.OK
    assert recovered.reset is None
    assert recovered.lines == ["partial done"]


def test_lt_04_read_failure_returns_unreadable_and_keeps_offset(tmp_path, monkeypatch):
    path = tmp_path / "svc.log"
    path.write_bytes(b"alpha\n")
    reader = LogTailReader()
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["alpha"]

    real_open_file = log_tailer._open_file

    class ReadDenied:
        def __init__(self, raw):
            self._raw = raw

        def __enter__(self):
            self._raw.__enter__()
            return self

        def __exit__(self, *args):
            return self._raw.__exit__(*args)

        def seek(self, *args):
            return self._raw.seek(*args)

        def read(self, size=-1):
            raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(
        log_tailer, "_open_file", lambda p: ReadDenied(real_open_file(p))
    )
    with path.open("ab") as handle:
        handle.write(b"beta\n")

    bad = reader.read_new_lines()
    assert bad.status is LogFileStatus.UNREADABLE
    assert bad.reset is None
    assert bad.error and "Permission denied" in bad.error
    assert reader._offset == 6

    monkeypatch.setattr(log_tailer, "_open_file", real_open_file)
    good = reader.read_new_lines()
    assert good.status is LogFileStatus.OK
    assert good.reset is None
    assert good.lines == ["beta"]


@pytest.mark.skipif(IS_ROOT, reason="root ignores mode 000 restrictions")
def test_lt_04_stat_failure_is_unreadable(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    target = locked / "svc.log"
    target.write_bytes(b"data\n")
    locked.chmod(0o000)
    try:
        reader = LogTailReader()
        reader.set_path(target)
        batch = reader.read_new_lines()
        assert batch.status is LogFileStatus.UNREADABLE
        assert batch.reset is None
        assert batch.error
    finally:
        locked.chmod(0o700)


# ---------------------------------------------------------------------------
# LT-05 .. LT-08: initial window, batch bounds, budget, no-op
# ---------------------------------------------------------------------------


def test_lt_05_initial_window_drops_leading_partial(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"old-line\n" + b"x" * 40 + b"\n" + b"tail-line\n")
    reader = LogTailReader(initial_bytes=20, max_batch_bytes=32, max_line_bytes=4096)
    assert reader.set_path(path) is True

    batch = reader.read_new_lines()
    assert batch.status is LogFileStatus.OK
    assert batch.reset == "created"
    assert batch.lines == ["tail-line"]
    assert batch.more_pending is False
    assert recorded_reads == [20]

    small = tmp_path / "small.log"
    small.write_bytes(b"a\nb\n")
    reader2 = LogTailReader(initial_bytes=4096)
    reader2.set_path(small)
    assert reader2.read_new_lines().lines == ["a", "b"]


def test_lt_06_batches_are_capped_and_drain_in_order(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    lines = ["line-%03d" % i for i in range(100)]  # 9 bytes each -> 900 bytes
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    reader = LogTailReader(initial_bytes=900, max_batch_bytes=64, max_line_bytes=64)
    reader.set_path(path)

    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert collect_lines(batches) == lines
    assert len(batches) > 1
    assert sum(costs) == 900
    assert all(cost <= 64 for cost in costs)
    assert all(size <= 64 for size in recorded_reads)
    assert batches[0].reset == "created"
    assert all(batch.reset is None for batch in batches[1:])


def test_lt_07_leading_partial_skip_counts_against_budget(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"x" * 40 + b"\n" + b"fresh\n")
    reader = LogTailReader(initial_bytes=20, max_batch_bytes=8, max_line_bytes=4096)
    reader.set_path(path)

    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert collect_lines(batches) == ["fresh"]
    assert sum(costs) == 20
    assert all(cost <= 8 for cost in costs)
    assert len(batches) > 1


def test_lt_07_overlong_discard_counts_against_budget(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"a" * 200 + b"\n" + b"short\n")
    reader = LogTailReader(initial_bytes=4096, max_batch_bytes=32, max_line_bytes=16)
    reader.set_path(path)

    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert collect_lines(batches) == ["a" * 16 + TRUNCATION_MARKER, "short"]
    # the discard of the over-long line cannot ride along for free in call one
    assert batches[0].lines == ["a" * 16 + TRUNCATION_MARKER]
    assert len(batches) > 1
    assert sum(costs) == 207
    assert all(cost <= 32 for cost in costs)


def test_lt_08_unchanged_metadata_performs_no_read(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"hello\n")
    reader = LogTailReader(initial_bytes=1024)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["hello"]

    recorded_reads.clear()
    batch = reader.read_new_lines()
    assert batch == LogReadBatch([], LogFileStatus.OK)
    assert batch.reset is None
    assert batch.error is None
    assert recorded_reads == []


# ---------------------------------------------------------------------------
# LT-09 .. LT-12: truncation, rotation, created transitions
# ---------------------------------------------------------------------------


def test_lt_09_equal_size_rewrite_is_truncated_reset(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"alpha\nbravo\n")
    reader = LogTailReader(initial_bytes=4096, max_batch_bytes=7, max_line_bytes=64)
    reader.set_path(path)
    first_batches, _ = drain_with_bounds(reader, recorded_reads)
    assert collect_lines(first_batches) == ["alpha", "bravo"]

    old_mtime = path.stat().st_mtime_ns
    path.write_bytes(b"gamma\ndelta\n")
    os.utime(path, ns=(old_mtime + 1_000_000_000, old_mtime + 1_000_000_000))
    assert path.stat().st_size == 12

    recorded_reads.clear()
    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert batches[0].status is LogFileStatus.OK
    assert batches[0].reset == "truncated"
    assert collect_lines(batches) == ["gamma", "delta"]
    assert batches[-1].more_pending is False
    assert sum(costs) == 12
    assert all(size <= 7 for size in recorded_reads)


def test_lt_09b_equal_size_rewrite_after_partial_read_is_truncated_reset(
    tmp_path, recorded_reads
):
    path = tmp_path / "svc.log"
    path.write_bytes(b"AAAA\nBBBB\nCCCC\n")
    reader = LogTailReader(initial_bytes=4096, max_batch_bytes=8, max_line_bytes=64)
    reader.set_path(path)

    first = reader.read_new_lines()
    assert first.status is LogFileStatus.OK
    assert first.reset == "created"
    assert first.lines == ["AAAA"]
    assert first.more_pending is True
    assert reader._offset < reader._size
    assert reader._partial == b"BBB"

    # Rewrite in place at the same size with a newer mtime_ns before the
    # retained partial (old bytes) and backlog were drained.
    old_mtime = path.stat().st_mtime_ns
    path.write_bytes(b"1111\n2222\n3333\n")
    os.utime(path, ns=(old_mtime + 1_000_000_000, old_mtime + 1_000_000_000))
    assert path.stat().st_size == 15

    recorded_reads.clear()
    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert batches[0].status is LogFileStatus.OK
    assert batches[0].reset == "truncated"
    lines = collect_lines(batches)
    assert lines == ["1111", "2222", "3333"]
    # never a line splicing retained old bytes ("BBB") onto rewritten bytes
    assert not any(fragment in line for line in lines for fragment in ("AAA", "BBB", "CCC"))
    assert batches[-1].more_pending is False
    assert sum(costs) == 15
    assert all(size <= 8 for size in recorded_reads)


def test_lt_10_size_shrink_is_truncated_and_clears_partial(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"keep\npartial")
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["keep"]
    assert reader._partial == b"partial"

    path.write_bytes(b"new\n")
    batch = reader.read_new_lines()
    assert batch.status is LogFileStatus.OK
    assert batch.reset == "truncated"
    assert batch.lines == ["new"]
    assert batch.more_pending is False
    assert reader._partial == b""


def test_lt_11_identity_change_is_rotated_reset(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"old\n")
    reader = LogTailReader(initial_bytes=11, max_batch_bytes=4, max_line_bytes=64)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["old"]

    replacement = tmp_path / "replacement.log"
    replacement.write_bytes(b"one\ntwo\nthree\nfour\n")
    os.replace(replacement, path)

    recorded_reads.clear()
    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert batches[0].status is LogFileStatus.OK
    assert batches[0].reset == "rotated"
    assert all(batch.reset is None for batch in batches[1:])
    assert collect_lines(batches) == ["four"]
    assert sum(costs) == 11
    assert all(size <= 4 for size in recorded_reads)


def test_lt_12_missing_then_created_is_emitted_once(tmp_path):
    path = tmp_path / "svc.log"
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)

    missing = reader.read_new_lines()
    assert missing.status is LogFileStatus.MISSING
    assert missing.reset is None

    path.write_bytes(b"hello\n")
    created = reader.read_new_lines()
    assert created.status is LogFileStatus.OK
    assert created.reset == "created"
    assert created.lines == ["hello"]

    unchanged = reader.read_new_lines()
    assert unchanged == LogReadBatch([], LogFileStatus.OK)
    assert unchanged.reset is None


# ---------------------------------------------------------------------------
# LT-13 .. LT-16: partial lines, over-long lines, invalid UTF-8, reset windows
# ---------------------------------------------------------------------------


def test_lt_13_trailing_partial_is_emitted_exactly_once(tmp_path):
    path = tmp_path / "svc.log"
    path.write_bytes(b"complete\nincomp")
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)

    first = reader.read_new_lines()
    assert first.lines == ["complete"]
    assert reader.read_new_lines().lines == []

    with path.open("ab") as handle:
        handle.write(b"le")
    assert reader.read_new_lines().lines == []

    with path.open("ab") as handle:
        handle.write(b"te\n")
    third = reader.read_new_lines()
    assert third.lines == ["incomplete"]
    assert reader.read_new_lines().lines == []


def test_lt_14_overlong_line_emits_exact_marker_and_discards(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"P" * 20 + b"Q" * 50 + b"\n" + b"after\n")
    reader = LogTailReader(initial_bytes=4096, max_batch_bytes=64, max_line_bytes=20)
    reader.set_path(path)

    batches, costs = drain_with_bounds(reader, recorded_reads)
    lines = collect_lines(batches)
    assert lines == ["P" * 20 + TRUNCATION_MARKER, "after"]
    assert "\u2026" in lines[0]
    assert lines.count("P" * 20 + TRUNCATION_MARKER) == 1
    assert sum(costs) == 77
    assert all(cost <= 64 for cost in costs)


def test_lt_15_invalid_utf8_decodes_with_replacement(tmp_path):
    path = tmp_path / "svc.log"
    path.write_bytes(b"ok\n" + b"\xff\xfe bad \x80\n" + b"next\n")
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)

    batch = reader.read_new_lines()
    assert batch.status is LogFileStatus.OK
    assert batch.lines == ["ok", "\ufffd\ufffd bad \ufffd", "next"]


def _make_lines(count: int) -> List[str]:
    return ["%02d-%s" % (i, "x" * 7) for i in range(count)]  # 11 bytes per line


def test_lt_16_created_window_drains_within_initial_bytes(tmp_path, recorded_reads):
    lines = _make_lines(40)  # 440 bytes
    path = tmp_path / "svc.log"
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    reader = LogTailReader(initial_bytes=59, max_batch_bytes=16, max_line_bytes=64)
    reader.set_path(path)

    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert batches[0].reset == "created"
    assert all(batch.reset is None for batch in batches[1:])
    assert collect_lines(batches) == lines[35:40]
    assert sum(costs) == 59
    assert len(costs) > 1
    assert all(size <= 16 for size in recorded_reads)
    # the rest of the backlog outside the initial window is never re-read
    assert reader.read_new_lines() == LogReadBatch([], LogFileStatus.OK)


def test_lt_16_truncation_window_drains_within_initial_bytes(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"z" * 1000)
    reader = LogTailReader(initial_bytes=59, max_batch_bytes=16, max_line_bytes=64)
    reader.set_path(path)
    assert reader.read_new_lines().status is LogFileStatus.OK

    lines = _make_lines(40)  # 440 bytes, shrinks below the old offset
    path.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))

    recorded_reads.clear()
    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert batches[0].status is LogFileStatus.OK
    assert batches[0].reset == "truncated"
    assert all(batch.reset is None for batch in batches[1:])
    assert collect_lines(batches) == lines[35:40]
    assert sum(costs) == 59
    assert all(size <= 16 for size in recorded_reads)


def test_lt_16_rotation_window_drains_within_initial_bytes(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"seed\n")
    reader = LogTailReader(initial_bytes=59, max_batch_bytes=16, max_line_bytes=64)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["seed"]

    lines = _make_lines(40)  # 440 bytes
    replacement = tmp_path / "replacement.log"
    replacement.write_bytes("".join(line + "\n" for line in lines).encode("utf-8"))
    os.replace(replacement, path)

    recorded_reads.clear()
    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert batches[0].reset == "rotated"
    assert all(batch.reset is None for batch in batches[1:])
    assert collect_lines(batches) == lines[35:40]
    assert sum(costs) == 59
    assert all(size <= 16 for size in recorded_reads)


# ---------------------------------------------------------------------------
# LT-17 .. LT-20: appends, status invariants, set_path, truncate-regrow
# ---------------------------------------------------------------------------


def test_lt_17_large_append_drains_without_duplication(tmp_path, recorded_reads):
    path = tmp_path / "svc.log"
    path.write_bytes(b"seed\n")
    reader = LogTailReader(initial_bytes=64, max_batch_bytes=16, max_line_bytes=64)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["seed"]

    lines = ["%02d-%s" % (i, "y" * 7) for i in range(30)]  # 11 bytes each -> 330
    with path.open("ab") as handle:
        handle.write("".join(line + "\n" for line in lines).encode("utf-8"))

    recorded_reads.clear()
    batches, costs = drain_with_bounds(reader, recorded_reads)
    assert collect_lines(batches) == lines
    assert len(batches) > 1
    assert sum(costs) == 330
    assert all(size <= 16 for size in recorded_reads)
    assert reader.read_new_lines() == LogReadBatch([], LogFileStatus.OK)


def test_lt_17_short_reads_advance_only_consumed_bytes(tmp_path, monkeypatch):
    path = tmp_path / "svc.log"
    path.write_bytes(b"abcdefghij\n")
    real_open_file = log_tailer._open_file

    class ShortReader:
        def __init__(self, raw):
            self._raw = raw

        def __enter__(self):
            self._raw.__enter__()
            return self

        def __exit__(self, *args):
            return self._raw.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self._raw, name)

        def read(self, size=-1):
            return self._raw.read(min(size, 3))

    monkeypatch.setattr(
        log_tailer, "_open_file", lambda p: ShortReader(real_open_file(p))
    )
    reader = LogTailReader(initial_bytes=4096, max_batch_bytes=64)
    reader.set_path(path)

    batch = reader.read_new_lines()
    assert batch.lines == ["abcdefghij"]
    assert reader._offset == 11
    assert reader.read_new_lines() == LogReadBatch([], LogFileStatus.OK)


def test_lt_18_non_ok_batches_carry_no_reset_and_recovery_is_none(
    tmp_path, monkeypatch
):
    path = tmp_path / "svc.log"
    path.write_bytes(b"one\n")
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)
    assert reader.read_new_lines().reset == "created"

    path.unlink()
    missing = reader.read_new_lines()
    assert missing.status is LogFileStatus.MISSING
    assert missing.reset is None

    path.write_bytes(b"two\n")
    created = reader.read_new_lines()
    assert created.status is LogFileStatus.OK
    assert created.reset == "created"
    assert created.lines == ["two"]

    real_open_file = log_tailer._open_file

    def denied(_path):
        raise PermissionError(13, "Permission denied")

    # Keep unconsumed input available so the call actually reaches the open seam.
    with path.open("ab") as handle:
        handle.write(b"more\n")

    monkeypatch.setattr(log_tailer, "_open_file", denied)
    unreadable = reader.read_new_lines()
    assert unreadable.status is LogFileStatus.UNREADABLE
    assert unreadable.reset is None
    assert unreadable.error

    monkeypatch.setattr(log_tailer, "_open_file", real_open_file)
    recovered = reader.read_new_lines()
    assert recovered.status is LogFileStatus.OK
    assert recovered.reset is None
    assert recovered.lines == ["more"]


def test_lt_19_set_path_normalizes_and_resets_all_state(tmp_path):
    first = tmp_path / "a.log"
    second = tmp_path / "b.log"
    first.write_bytes(b"alpha\npartial")
    second.write_bytes(b"beta\n")

    reader = LogTailReader(initial_bytes=4096)
    assert reader.set_path(str(first)) is True
    assert reader.path == first
    assert reader.read_new_lines().lines == ["alpha"]
    assert reader._partial == b"partial"

    assert reader.set_path(first) is False
    assert reader._partial == b"partial"
    assert reader.read_new_lines().lines == []

    assert reader.set_path(second) is True
    assert reader.path == second
    assert reader._partial == b""
    assert reader._offset == 0
    assert reader._identity is None
    batch = reader.read_new_lines()
    assert batch.reset == "created"
    assert batch.lines == ["beta"]

    assert reader.set_path(None) is True
    assert reader.path is None
    assert reader.read_new_lines() == LogReadBatch([], LogFileStatus.UNSET)
    assert reader.set_path(None) is False


def test_lt_20_truncate_regrow_between_polls_is_safe(tmp_path):
    path = tmp_path / "svc.log"
    path.write_bytes(b"aaaa\nbbbb\n")
    reader = LogTailReader(initial_bytes=4096)
    reader.set_path(path)
    assert reader.read_new_lines().lines == ["aaaa", "bbbb"]

    # truncate and regrow past the old offset within one poll interval
    path.write_bytes(b"cccc\ndddd\neeee\n")
    batch = reader.read_new_lines()
    assert batch.status is LogFileStatus.OK
    assert batch.error is None
    assert reader.probe_health() == (FilePresence.PRESENT, None)

    with path.open("ab") as handle:
        handle.write(b"ffff\n")
    assert reader.read_new_lines().lines == ["ffff"]
    assert reader.probe_health() == (FilePresence.PRESENT, None)

    # size-shrink detection still works
    shrink = tmp_path / "shrink.log"
    shrink.write_bytes(b"12345\nabcdef\n")
    shrink_reader = LogTailReader(initial_bytes=4096)
    shrink_reader.set_path(shrink)
    assert shrink_reader.read_new_lines().status is LogFileStatus.OK
    shrink.write_bytes(b"x\n")
    shrink_batch = shrink_reader.read_new_lines()
    assert shrink_batch.status is LogFileStatus.OK
    assert shrink_batch.reset == "truncated"
    assert shrink_batch.lines == ["x"]

    # equal-size rewrite with a newer mtime_ns is still detected
    equal = tmp_path / "equal.log"
    equal.write_bytes(b"hello\nworld\n")
    equal_reader = LogTailReader(initial_bytes=4096)
    equal_reader.set_path(equal)
    assert equal_reader.read_new_lines().lines == ["hello", "world"]
    mtime = equal.stat().st_mtime_ns
    equal.write_bytes(b"HELLO\nWORLD\n")
    os.utime(equal, ns=(mtime + 1_000_000_000, mtime + 1_000_000_000))
    equal_batch = equal_reader.read_new_lines()
    assert equal_batch.reset == "truncated"
    assert equal_batch.lines == ["HELLO", "WORLD"]
