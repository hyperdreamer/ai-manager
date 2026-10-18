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
    flags_seen, locks_seen, fsyncs_seen = [], [], []
    original_open, original_flock, original_fsync = (
        tm.os.open, tm.fcntl.flock, tm.os.fsync
    )
    def opened(path, flags, mode=0o777):
        flags_seen.append((str(path), flags))
        return original_open(path, flags, mode)
    def locked(fd, op):
        if op == fcntl.LOCK_EX:
            locks_seen.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return original_flock(fd, op)
    def synced(fd):
        fsyncs_seen.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return original_fsync(fd)
    monkeypatch.setattr(tm.os, "open", opened)
    monkeypatch.setattr(tm.fcntl, "flock", locked)
    monkeypatch.setattr(tm.os, "fsync", synced)
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
    # Every backup descriptor is fsynced and immediately followed by its parent
    # directory fsync: three completed backups, six durability calls in total.
    assert len(fsyncs_seen) == 6
    assert all(
        backup.suffix == ".bak" and parent == tmp_path.resolve()
        for backup, parent in zip(fsyncs_seen[::2], fsyncs_seen[1::2])
    )


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


def test_backup_fsyncs_descriptor_before_parent_directory(tmp_path, monkeypatch):
    paths = files(tmp_path)
    root = tmp_path.resolve()
    original_fsync = tm.os.fsync
    order = []
    def fsync(fd):
        order.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return original_fsync(fd)
    monkeypatch.setattr(tm.os, "fsync", fsync)
    with tm.Transaction() as tx:
        tx.prepare(paths, {p: digest(p) for p in paths})
        tx.backups()
        created = list(tx._backups.values())
    assert order == [created[0], root, created[1], root]
    assert all(name.suffix == ".bak" for name in order[::2])
    assert all(name.suffix != ".bak" for name in order[1::2])


@pytest.mark.parametrize("failing", ["backup-file", "parent-directory"])
def test_backup_fsync_failure_aborts_targets_and_releases_locks(
    tmp_path, monkeypatch, failing
):
    paths = files(tmp_path)
    root = tmp_path.resolve()
    old = {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths}
    original_fsync = tm.os.fsync
    injected = []
    def fsync(fd):
        name = Path(os.readlink(f"/proc/self/fd/{fd}"))
        matches = name.suffix == ".bak" if failing == "backup-file" else name == root
        if matches and not injected:
            injected.append(name)
            raise OSError(5, "fixture fsync failure")
        return original_fsync(fd)
    monkeypatch.setattr(tm.os, "fsync", fsync)
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare(paths, {p: digest(p) for p in paths})
            tx.backups()
    assert injected
    assert err.value.report.phase == "backups"
    assert err.value.report.backups == {}
    assert set(err.value.report.files.values()) == {"restored"}
    assert {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths} == old
    assert not list(tmp_path.glob("*.bak"))
    for p in paths:
        with open(str(p) + ".lock", "r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


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


@pytest.mark.parametrize("failing", ["unlock", "close"])
def test_release_attempts_every_descriptor_after_one_failure(
    tmp_path, monkeypatch, failing
):
    paths = files(tmp_path, 3)
    original_flock, original_close = tm.fcntl.flock, tm.os.close
    attempted, injected = [], []
    def locked(fd, op):
        if op == fcntl.LOCK_UN:
            name = Path(os.readlink(f"/proc/self/fd/{fd}"))
            attempted.append(name)
            if failing == "unlock" and not injected:
                injected.append(name)
                raise OSError(5, "fixture unlock failure")
        return original_flock(fd, op)
    def closed(fd):
        name = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if failing == "close" and name.name.endswith(".lock") and not injected:
            injected.append(name)
            raise OSError(5, "fixture close failure")
        return original_close(fd)
    monkeypatch.setattr(tm.fcntl, "flock", locked)
    monkeypatch.setattr(tm.os, "close", closed)
    tx = tm.Transaction()
    with pytest.raises(OSError, match=f"fixture {failing} failure"):
        with tx:
            tx.prepare(paths, {p: digest(p) for p in paths})
    assert sorted(attempted) == sorted(Path(str(p) + ".lock") for p in paths)
    assert len(injected) == 1
    assert tx._locks == [] and tx._entered is False and tx._state == "closed"
    for p in paths:
        with open(str(p) + ".lock", "r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_interrupted_unlock_is_retried(tmp_path, monkeypatch):
    paths = files(tmp_path)
    original_flock = tm.fcntl.flock
    attempted, interrupted = [], []
    def locked(fd, op):
        if op == fcntl.LOCK_UN:
            attempted.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
            if not interrupted:
                interrupted.append(fd)
                raise InterruptedError(4, "Interrupted system call")
        return original_flock(fd, op)
    monkeypatch.setattr(tm.fcntl, "flock", locked)
    with tm.Transaction() as tx:
        tx.prepare(paths, {p: digest(p) for p in paths})
    assert interrupted
    expected = sorted(Path(str(p) + ".lock") for p in paths)
    # The interrupted descriptor is attempted twice, then unlocked for real; the
    # remaining descriptors are still visited exactly once.
    assert sorted(set(attempted)) == expected
    assert len(attempted) == len(expected) + 1
    assert tx._locks == [] and tx._state == "closed"
    for p in paths:
        with open(str(p) + ".lock", "r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("dependent_count", [0, 1, 3])
def test_sealed_stage_and_sorted_replace(tmp_path, dependent_count, monkeypatch):
    paths = files(tmp_path, dependent_count + 1)
    old = {p: p.read_bytes() for p in paths}
    new = {p: b"new-" + p.name.encode() for p in paths}
    replacements = []
    original = tm.os.replace
    def spy(src, dst):
        replacements.append(Path(dst))
        return original(src, dst)
    monkeypatch.setattr(tm.os, "replace", spy)
    with tm.Transaction() as tx:
        tx.prepare(list(reversed(paths)), {p: digest(p) for p in paths})
        tx.backups()
        tx.stage(new)
        assert {p: p.read_bytes() for p in paths} == old
        assert all(t.parent == tmp_path and t.name.startswith(".") for t in tx._temps)
        report = tx.replace_all()
    assert replacements == sorted(paths, key=str)
    assert report.committed and report.phase == "complete"
    assert report.files == {p: "new" for p in paths}
    assert {p: p.read_bytes() for p in paths} == new
    assert all(stat.S_IMODE(p.lstat().st_mode) == 0o640 for p in paths)
    assert all(b.read_bytes() == old[p] for p, b in report.backups.items())
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("phase", ["stage", "replace", "parent-fsync", "restore"])
def test_fault_reports_real_bytes_modes_and_all_paths(tmp_path, monkeypatch, phase):
    paths = files(tmp_path, 3)
    old = {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths}
    original_replace = tm.os.replace
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare(paths, {p: digest(p) for p in paths})
            tx.backups()
            replaced, restore_order = [], []
            original_temp, original_sync = tx._write_temp, tx._fsync_dir
            def temporary(path, raw, mode, label):
                if phase == "stage" and path == paths[1] and label == "stage":
                    raise OSError("fixture stage failure")
                return original_temp(path, raw, mode, label)
            def replace_file(src, dst):
                label = "restore" if "restore" in str(src) else "stage"
                dst = Path(dst)
                if label == "stage" and dst == paths[2] and phase in ("replace", "restore"):
                    raise OSError("fixture replace failure")
                if label == "restore":
                    restore_order.append(dst)
                    if phase == "restore" and dst == paths[1]:
                        raise OSError("fixture restore failure")
                result = original_replace(src, dst)
                if label == "stage":
                    replaced.append(dst)
                return result
            sync_failed = False
            def sync(parent):
                nonlocal sync_failed
                if phase == "parent-fsync" and replaced and not sync_failed:
                    sync_failed = True
                    raise OSError("fixture directory fsync failure")
                return original_sync(parent)
            monkeypatch.setattr(tx, "_write_temp", temporary)
            monkeypatch.setattr(tx, "_fsync_dir", sync)
            monkeypatch.setattr(tm.os, "replace", replace_file)
            tx.stage({p: b"new" for p in paths})
            tx.replace_all()
    report = err.value.report
    assert not report.committed and set(report.files) == set(paths)
    if phase == "stage":
        assert replaced == [] and report.phase == "stage"
    else:
        assert report.phase == "rollback"
        assert restore_order == list(reversed(replaced))
        if phase == "parent-fsync":
            assert replaced == [paths[0]]
    if phase == "restore":
        assert report.files[paths[1]] == "unknown"
        assert paths[1] in report.restore_failures
        assert p_original(paths[0]) == old[paths[0]] and p_original(paths[2]) == old[paths[2]]
    else:
        assert report.files == {p: "restored" for p in paths}
        assert {p: p_original(p) for p in paths} == old
    assert not list(tmp_path.glob(".*.tmp"))
    assert all(b.exists() for b in report.backups.values())


def p_original(path):
    return path.read_bytes(), stat.S_IMODE(path.lstat().st_mode)


def test_explicit_create_mode_and_rollback_to_absence(tmp_path, monkeypatch):
    created = tmp_path / "0.json"
    other = files(tmp_path, 1)[0]
    old = other.read_bytes()
    original = tm.os.replace
    def fail(src, dst):
        if Path(dst) == other and "stage" in str(src):
            raise OSError("fixture later replace failure")
        return original(src, dst)
    monkeypatch.setattr(tm.os, "replace", fail)
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare([other, created], {created: None, other: digest(other)})
            tx.backups()
            tx.stage({created: b"{}\n", other: b"new"})
            assert tx.original_mode(created) == 0o600
            tx.replace_all()
    assert not created.exists() and other.read_bytes() == old
    assert err.value.report.files[created] == "restored"
    assert created not in err.value.report.backups
    monkeypatch.setattr(tm.os, "replace", original)
    with tm.Transaction() as tx:
        tx.prepare([created], {created: None})
        tx.backups()
        tx.stage({created: b"{}\n"})
        assert tx.replace_all().committed
    assert stat.S_IMODE(created.lstat().st_mode) == 0o600


def test_invalid_phase_and_key_sets_write_nothing(tmp_path):
    p = files(tmp_path, 1)[0]
    with tm.Transaction() as tx:
        with pytest.raises(ValueError):
            tx.stage({p: b"bad"})
        with pytest.raises(ValueError):
            tx.prepare([p], {})
        tx.prepare([p], {p: digest(p)})
        with pytest.raises(ValueError):
            tx.prepare([p], {p: digest(p)})
        tx.backups()
        with pytest.raises(ValueError):
            tx.stage({})
        assert p.read_bytes() == b"old-0\n"


def test_two_processes_reverse_input_order_finish_or_refuse_stale(tmp_path):
    paths = files(tmp_path)
    ctx = multiprocessing.get_context("fork")
    start, out = ctx.Event(), ctx.Queue()
    expected = {p: digest(p) for p in paths}
    def writer(order, value):
        start.wait(2)
        try:
            with tm.Transaction() as tx:
                tx.prepare(order, expected)
                tx.backups()
                tx.stage({p: value for p in order})
                tx.replace_all()
            out.put("saved")
        except StaleDocumentError:
            out.put("stale")
    children = [ctx.Process(target=writer, args=(paths, b"first")), ctx.Process(target=writer, args=(list(reversed(paths)), b"second"))]
    try:
        for child in children:
            child.start()
        start.set()
        for child in children:
            child.join(4)
            assert child.exitcode == 0
        assert sorted([out.get(timeout=1), out.get(timeout=1)]) == ["saved", "stale"]
        assert len({p.read_bytes() for p in paths}) == 1
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(2)
