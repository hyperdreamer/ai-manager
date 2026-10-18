import fcntl
import hashlib
import multiprocessing
import os
from pathlib import Path
import stat
import pytest
from ai_manager.config import transaction as tm
from ai_manager.config.config_errors import (
    ConfigLoadError, ReadOnlyConfigError, StaleDocumentError, SymlinkConfigError,
    TransactionError,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest() if path.exists() else None


def files(tmp_path, count=2):
    paths = [tmp_path / f"{i}.yaml" for i in range(count)]
    for index, path in enumerate(paths):
        path.write_bytes(f"old-{index}\n".encode())
        path.chmod(0o640)
    return paths


@pytest.mark.parametrize("member", [0, 1])
def test_stale_member_leaves_all_bytes_and_no_artifacts(tmp_path, member):
    paths = files(tmp_path)
    expected = {p: digest(p) for p in paths}
    paths[member].write_bytes(b"hand edit\n")
    before = {p: p.read_bytes() for p in paths}
    with pytest.raises(StaleDocumentError) as err:
        with tm.Transaction() as tx:
            tx.prepare(list(reversed(paths)), expected)
    assert err.value.expected_sha256 == expected[paths[member]]
    assert err.value.actual_sha256 == digest(paths[member])
    assert {p: p.read_bytes() for p in paths} == before
    assert not list(tmp_path.glob("*.bak")) and not list(tmp_path.glob(".*.tmp"))
    for p in paths:
        with open(str(p) + ".lock", "r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("race", ["deleted", "created", "empty"])
def test_none_digest_semantics(tmp_path, race):
    p = tmp_path / "config.json"
    if race == "deleted":
        p.write_bytes(b"old")
        expected = digest(p)
        p.unlink()
    else:
        expected = None
        p.write_bytes(b"" if race == "empty" else b"appeared")
    with pytest.raises(StaleDocumentError):
        with tm.Transaction() as tx:
            tx.prepare([p], {p: expected})
    assert p.exists() == (race != "deleted")


def test_symlink_swapped_after_load_is_rejected(tmp_path):
    p = files(tmp_path, 1)[0]
    old_hash = digest(p)
    target = tmp_path / "referent"
    target.write_bytes(b"untouched")
    p.unlink()
    p.symlink_to(target)
    with pytest.raises(SymlinkConfigError):
        with tm.Transaction() as tx:
            tx.prepare([p], {p: old_hash})
    assert p.is_symlink() and target.read_bytes() == b"untouched"


def test_backups_exclusive_collision_and_order(tmp_path, monkeypatch):
    paths = files(tmp_path)
    class Clock:
        @classmethod
        def now(cls, tz):
            from datetime import datetime, timezone
            return datetime(2026, 10, 17, 16, 7, 34, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(tm, "datetime", Clock)
    monkeypatch.setattr(tm.os, "getpid", lambda: 4321)
    nonces = iter(["a1b2c3", "a1b2c3", "d4e5f6", "a1b2c3", "d4e5f6", "abcdef"])
    monkeypatch.setattr(tm.secrets, "token_hex", lambda n: next(nonces))
    flags_seen, locks_seen = [], []
    original_open, original_flock = tm.os.open, tm.fcntl.flock
    def opened(path, flags, mode=0o777):
        flags_seen.append((str(path), flags))
        return original_open(path, flags, mode)
    def locked(fd, op):
        if op == fcntl.LOCK_EX:
            locks_seen.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return original_flock(fd, op)
    monkeypatch.setattr(tm.os, "open", opened)
    monkeypatch.setattr(tm.fcntl, "flock", locked)
    with tm.Transaction() as tx:
        tx.prepare(list(reversed(paths)), {p: digest(p) for p in paths})
        tx.backups()
        first = tx._backups.copy()
        assert list(tx._paths) == sorted(paths, key=str)
        assert all(stat.S_IMODE(b.lstat().st_mode) == 0o640 for b in first.values())
    paths[0].write_bytes(b"next")
    with tm.Transaction() as tx:
        tx.prepare([paths[0]], {paths[0]: digest(paths[0])})
        tx.backups()
        second = tx._backups[paths[0]]
    assert second != first[paths[0]]
    assert first[paths[0]].read_bytes() == b"old-0\n" and second.read_bytes() == b"next"
    assert locks_seen[:2] == [Path(str(p) + ".lock") for p in sorted(paths, key=str)]
    assert all(flags & os.O_EXCL for name, flags in flags_seen if name.endswith(".bak"))
    assert all(flags & os.O_NOFOLLOW for name, flags in flags_seen if name.endswith(".lock"))
    assert first[paths[0]].name == "0.yaml.20261017T160734123456Z.4321-a1b2c3.bak"


def test_backup_failure_keeps_targets_and_completed_backup(tmp_path, monkeypatch):
    paths = files(tmp_path)
    old = {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths}
    original = tm.os.open
    def fail(path, flags, mode=0o777):
        if str(path).startswith(str(paths[1]) + ".") and str(path).endswith(".bak"):
            raise OSError("fixture backup failure")
        return original(path, flags, mode)
    monkeypatch.setattr(tm.os, "open", fail)
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare(paths, {p: digest(p) for p in paths})
            tx.backups()
    assert err.value.report.phase == "backups"
    assert set(err.value.report.files.values()) == {"restored"}
    assert len(err.value.report.backups) == 1
    assert {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths} == old


def test_sidecar_identity_survives_target_inode_replace(tmp_path):
    p = files(tmp_path, 1)[0]
    ctx = multiprocessing.get_context("fork")
    ready, acquired = ctx.Event(), ctx.Event()
    output = ctx.Queue()
    def reader():
        with open(str(p) + ".lock", "a+b") as lock:
            ready.set()
            fcntl.flock(lock, fcntl.LOCK_EX)
            output.put(p.read_bytes())
            acquired.set()
    child = None
    try:
        with tm.Transaction() as tx:
            tx.prepare([p], {p: digest(p)})
            child = ctx.Process(target=reader)
            child.start()
            assert ready.wait(2) and not acquired.wait(0.1)
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"new inode")
            os.replace(replacement, p)
            assert not acquired.wait(0.1)
        assert acquired.wait(2)
        assert output.get(timeout=2) == b"new inode"
        child.join(2)
        assert child.exitcode == 0 and Path(str(p) + ".lock").exists()
    finally:
        if child is not None and child.is_alive():
            child.terminate()
            child.join(2)


def test_original_mode_reports_captured_mode_and_defaults_for_absent(tmp_path):
    present = files(tmp_path, 1)[0]
    absent = tmp_path / "new.json"
    with tm.Transaction() as tx:
        tx.prepare([present, absent], {present: digest(present), absent: None})
        assert tx.original_mode(present) == 0o640
        assert tx.original_mode(absent) == 0o600
        with pytest.raises(ValueError):
            tx.original_mode(tmp_path / "unprepared.json")
    assert not absent.exists() and not list(tmp_path.glob("*.bak"))


def test_state_machine_and_argument_validation(tmp_path):
    p = files(tmp_path, 1)[0]
    (tmp_path / "sub").mkdir()
    alias = tmp_path / "sub" / ".." / p.name
    tx = tm.Transaction()
    with pytest.raises(ValueError):
        tx.backups()
    with tx:
        with pytest.raises(ValueError):
            tx.backups()
        with pytest.raises(ValueError):
            tx.prepare([], {})
        with pytest.raises(ValueError):
            tx.prepare([p, p], {p: digest(p)})
        with pytest.raises(ValueError):
            tx.prepare([p], {p: b"short"})
        with pytest.raises(ValueError):
            tx.prepare([p], {})
        with pytest.raises(ValueError):
            tx.prepare([p, alias], {p: digest(p), alias: digest(p)})
        tx.prepare([p], {p: digest(p)})
        with pytest.raises(ValueError):
            tx.prepare([p], {p: digest(p)})
    with pytest.raises(ValueError):
        with tx:
            pass
    assert not list(tmp_path.glob("*.bak")) and not list(tmp_path.glob(".*.tmp"))
    with open(str(p) + ".lock", "r+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_read_only_mode_refuses_even_when_effective_access_allows(tmp_path):
    p = files(tmp_path, 1)[0]
    p.chmod(0o444)
    with pytest.raises(ReadOnlyConfigError):
        with tm.Transaction() as tx:
            tx.prepare([p], {p: digest(p)})
    assert p.read_bytes() == b"old-0\n"
    assert not list(tmp_path.glob("*.bak")) and not list(tmp_path.glob(".*.tmp"))


def test_non_regular_leaf_is_rejected(tmp_path):
    directory = tmp_path / "0.yaml"
    directory.mkdir()
    with pytest.raises(ConfigLoadError):
        with tm.Transaction() as tx:
            tx.prepare([directory], {directory: None})
    assert not list(tmp_path.glob("*.lock"))
