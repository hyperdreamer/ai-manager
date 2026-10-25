import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_manager.config.protocols import ENDPOINT_VALUES
from ai_manager.services import protocol_capability as pc
from tests.endpoint_helpers import meta_for


VALUES = (
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/messages",
)


def execute(tmp_path: Path, app_id: str, source: str):
    meta = meta_for(tmp_path, app_id)
    name = "config.py" if app_id == "ai-grammar" else "main.py"
    (meta.relative_path / name).write_text(source, encoding="utf-8")
    result = pc._run_uncached_probe(
        meta, Path(sys.executable), meta.relative_path.resolve()
    )
    assert not list(meta.relative_path.rglob("__pycache__"))
    return meta, result


def _sentinel(nonce: str, accepted: list[object], rejected: list[object]) -> str:
    return "PROBE_RESULT:" + nonce + ":" + json.dumps(
        {"accepted": accepted, "rejected": rejected}
    )


def test_protocol_support_records_enforce_status_partition():
    supported = pc.ProtocolSupport(
        pc.ProtocolSupportStatus.SUPPORTED, frozenset(ENDPOINT_VALUES), "detail"
    )
    partial = pc.ProtocolSupport(
        pc.ProtocolSupportStatus.PARTIAL, frozenset({VALUES[0]}), ""
    )
    unsupported = pc.ProtocolSupport(pc.ProtocolSupportStatus.UNSUPPORTED)
    unknown = pc.ProtocolSupport(pc.ProtocolSupportStatus.UNVERIFIABLE)

    assert supported.accepted == ENDPOINT_VALUES
    assert partial.accepted == frozenset({VALUES[0]})
    assert unsupported.accepted == frozenset()
    assert unknown.accepted == frozenset()
    with pytest.raises(FrozenInstanceError):
        supported.status = pc.ProtocolSupportStatus.PARTIAL

    invalid = [
        (pc.ProtocolSupportStatus.SUPPORTED, frozenset()),
        (pc.ProtocolSupportStatus.SUPPORTED, frozenset({VALUES[0]})),
        (pc.ProtocolSupportStatus.PARTIAL, frozenset()),
        (pc.ProtocolSupportStatus.PARTIAL, frozenset(ENDPOINT_VALUES)),
        (pc.ProtocolSupportStatus.UNSUPPORTED, frozenset({VALUES[0]})),
        (pc.ProtocolSupportStatus.UNVERIFIABLE, frozenset({VALUES[0]})),
        (pc.ProtocolSupportStatus.PARTIAL, frozenset({"/v1/unknown"})),
    ]
    for status, accepted in invalid:
        with pytest.raises(ValueError):
            pc.ProtocolSupport(status, accepted)


@pytest.mark.parametrize(
    "rejected,status",
    [
        ((), pc.ProtocolSupportStatus.SUPPORTED),
        (("/v1/responses",), pc.ProtocolSupportStatus.PARTIAL),
        (tuple(ENDPOINT_VALUES), pc.ProtocolSupportStatus.UNSUPPORTED),
    ],
)
def test_grammar_uses_loader_guard(tmp_path, rejected, status):
    source = (
        "from dataclasses import dataclass\n@dataclass\nclass AIConfig:\n"
        " endpoint: str = ''\n"
        f"def _resolve_endpoint(ai):\n if ai['endpoint'] in {rejected!r}:"
        " raise RuntimeError('rejected')\n return ai['endpoint']\n"
    )
    meta, result = execute(tmp_path, "ai-grammar", source)
    assert result.status is status
    assert result.accepted == ENDPOINT_VALUES - set(rejected)
    assert not list(meta.relative_path.rglob("__pycache__"))


@pytest.mark.parametrize(
    "guard,model_reject,want",
    [
        (("/v1/chat/completions", "/v1/messages"), (),
         {"/v1/chat/completions", "/v1/messages"}),
        (tuple(ENDPOINT_VALUES), ("/v1/messages",),
         {"/v1/chat/completions", "/v1/responses"}),
    ],
)
def test_textkit_guard_and_validator_both_participate(
    tmp_path, guard, model_reject, want
):
    source = (
        f"SUPPORTED_ENDPOINTS = {guard!r}\nclass AIConfig:\n @staticmethod\n"
        f" def model_validate(data):\n  assert data['api_key'] == 'probe'\n"
        f"  if data['endpoint'] in {model_reject!r}: raise ValueError('rejected')\n"
        "  return data\n"
    )
    _, result = execute(tmp_path, "textkit", source)
    assert result.status is pc.ProtocolSupportStatus.PARTIAL
    assert result.accepted == frozenset(want)


@pytest.mark.parametrize(
    "app,source",
    [
        (
            "ai-grammar",
            "from dataclasses import dataclass\n@dataclass\nclass AIConfig:\n"
            " endpoint: str = ''\n",
        ),
        ("ai-grammar", "raise SystemExit(0)\n"),
        (
            "ai-grammar",
            "def _resolve_endpoint(x): raise TypeError('unexpected')\n",
        ),
        ("textkit", "class AIConfig: pass\n"),
        (
            "textkit",
            "SUPPORTED_ENDPOINTS = 'bad'\nclass AIConfig:\n"
            " model_validate = None\n",
        ),
        (
            "textkit",
            "SUPPORTED_ENDPOINTS = (42,)\nclass AIConfig:\n"
            " model_validate = None\n",
        ),
        (
            "textkit",
            "SUPPORTED_ENDPOINTS = ()\nclass AIConfig:\n"
            " model_validate = None\n",
        ),
    ],
)
def test_unusable_interface_is_unknown_not_verified_rejection(
    tmp_path, app, source
):
    _, result = execute(tmp_path, app, source)
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE and not result.accepted


def test_import_side_effects_are_not_claimed_sandboxed(tmp_path):
    meta, result = execute(
        tmp_path,
        "ai-grammar",
        "from pathlib import Path\nPath('import-marker').write_text('ran')\n"
        "def _resolve_endpoint(x): return x['endpoint']\n",
    )
    assert result.status is pc.ProtocolSupportStatus.SUPPORTED
    assert (meta.relative_path / "import-marker").read_text() == "ran"


def test_parse_partition_accepts_final_matching_sentinel():
    nonce = "a" * 32
    output = "import banner\n\n" + _sentinel(nonce, list(ENDPOINT_VALUES), []) + "\n\n"
    assert pc._parse_partition(output, nonce) == ENDPOINT_VALUES


def test_parse_partition_accepts_zero_accepted_partition():
    nonce = "b" * 32
    assert pc._parse_partition(
        _sentinel(nonce, [], list(ENDPOINT_VALUES)), nonce
    ) == frozenset()


def test_parse_partition_rejects_malformed_grammar():
    nonce = "c" * 32
    first = VALUES[0]
    rest = list(VALUES[1:])
    valid = _sentinel(nonce, [first], rest)
    duplicate_key = (
        "PROBE_RESULT:" + nonce + ":"
        + '{"accepted":[' + json.dumps(first) + '],'
        + '"accepted":[],"rejected":' + json.dumps(rest) + "}"
    )
    cases = [
        json.dumps({"accepted": list(ENDPOINT_VALUES), "rejected": []}),
        _sentinel("d" * 32, list(ENDPOINT_VALUES), []),
        valid + "\n" + valid,
        valid + "\nclosing banner",
        " " + valid,
        "PROBE_RESULT:" + nonce + ":{not-json",
        duplicate_key,
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": list(ENDPOINT_VALUES), "rejected": [], "extra": 1}),
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": first, "rejected": rest}),
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": [first, 42], "rejected": rest}),
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": [first, first], "rejected": rest}),
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": [first], "rejected": [first, *rest]}),
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": ["/v1/unknown"], "rejected": rest}),
        "PROBE_RESULT:" + nonce + ":"
        + json.dumps({"accepted": [first], "rejected": []}),
    ]
    for output in cases:
        with pytest.raises(ValueError):
            pc._parse_partition(output, nonce)


def test_valid_zero_partition_is_reported_as_unsupported(tmp_path):
    _, result = execute(
        tmp_path,
        "ai-grammar",
        "def _resolve_endpoint(value): raise RuntimeError('rejected')\n",
    )
    assert result.status is pc.ProtocolSupportStatus.UNSUPPORTED
    assert result.accepted == frozenset()


class _StaticProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.killed = False

    def communicate(self, timeout):
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True

    def poll(self):
        return self.returncode


@pytest.mark.parametrize("returncode", [75, 1])
def test_nonzero_exit_with_valid_sentinel_is_unverifiable(monkeypatch, tmp_path, returncode):
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        nonce = argv[-1]
        return _StaticProcess(
            _sentinel(nonce, list(ENDPOINT_VALUES), []), returncode=returncode
        )

    monkeypatch.setattr(pc.subprocess, "Popen", fake_popen)
    meta = meta_for(tmp_path)
    result = pc._run_uncached_probe(
        meta, Path(sys.executable), meta.relative_path.resolve()
    )
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail.startswith(
        f"Protocol capability check exited {returncode}."
    )


def test_probe_spawn_contract_and_redaction(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setenv("CAPABILITY_INHERITED_MARKER", "inherited")
    stderr = "api_key=not-a-real-secret\nvalidation input_value='fixture'"

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _StaticProcess(_sentinel(argv[-1], list(ENDPOINT_VALUES), []), stderr)

    monkeypatch.setattr(pc.subprocess, "Popen", fake_popen)
    meta = meta_for(tmp_path)
    app_dir = meta.relative_path.resolve()
    result = pc._run_uncached_probe(meta, Path(sys.executable), app_dir)

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert argv[1] == "-B"
    assert len(argv) == 5
    assert argv[0] == str(Path(sys.executable))
    assert argv[2] == "-c"
    assert argv[3] == pc.GRAMMAR_PROGRAM
    assert re.fullmatch(r"[0-9a-f]{32}", argv[4])
    assert kwargs["cwd"] == app_dir
    assert kwargs["shell"] is False
    assert kwargs["env"]["CAPABILITY_INHERITED_MARKER"] == "inherited"
    assert kwargs["env"].get("PYTHONDONTWRITEBYTECODE") == "1"
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert result.status is pc.ProtocolSupportStatus.SUPPORTED
    assert "not-a-real-secret" not in result.detail
    assert "fixture" not in result.detail
    assert "input_value=***" in result.detail


def test_probe_timeout_kills_and_reaps_direct_child(monkeypatch, tmp_path):
    real_popen = subprocess.Popen
    captured = {}

    class RecordingProcess:
        def __init__(self, child):
            self._child = child
            self.pid = child.pid

        @property
        def returncode(self):
            return self._child.returncode

        def communicate(self, timeout=None):
            result = self._child.communicate(timeout=timeout)
            captured["wait_result"] = self._child.returncode
            return result

        def kill(self):
            return self._child.kill()

        def poll(self):
            return self._child.poll()

    def recording_popen(argv, **kwargs):
        child = real_popen(argv, **kwargs)
        captured["pid"] = child.pid
        captured["child"] = child
        return RecordingProcess(child)

    monkeypatch.setattr(pc.subprocess, "Popen", recording_popen)
    meta = meta_for(tmp_path)
    (meta.relative_path / "config.py").write_text(
        "import time\ntime.sleep(30)\n", encoding="utf-8"
    )
    result = pc._run_uncached_probe(
        meta, Path(sys.executable), meta.relative_path.resolve()
    )

    assert captured["pid"] > 0
    assert captured["wait_result"] is not None
    assert captured["child"].poll() is not None
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail.startswith(
        "Protocol capability check timed out after 5 seconds."
    )


def test_probe_spawn_failure_uses_exact_run_failure_prefix(monkeypatch, tmp_path):
    def fail_popen(argv, **kwargs):
        raise OSError("spawn boom")

    monkeypatch.setattr(pc.subprocess, "Popen", fail_popen)
    meta = meta_for(tmp_path)
    result = pc._run_uncached_probe(
        meta, Path(sys.executable), meta.relative_path.resolve()
    )
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail.startswith("Could not run protocol capability check: spawn boom")


def test_unknown_app_id_is_unverifiable(tmp_path):
    meta = meta_for(tmp_path, "unknown")
    result = pc._run_uncached_probe(
        meta, Path(sys.executable), meta.relative_path.resolve()
    )
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail == "No protocol probe is defined for unknown."


SUPERSEDED_DETAIL = (
    "Protocol capability check was superseded; retry after the restart or update."
)
SUPPORTED = pc.ProtocolSupport(pc.ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES)
PARTIAL = pc.ProtocolSupport(pc.ProtocolSupportStatus.PARTIAL, frozenset({VALUES[0]}))


@pytest.fixture
def cache_app(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    interpreter = tmp_path / "environment" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"fixture interpreter\n")
    interpreter.chmod(0o755)
    monkeypatch.setattr(pc, "resolve_app_interpreter", Mock(return_value=interpreter))
    run = Mock(return_value=SUPPORTED)
    monkeypatch.setattr(pc, "_run_uncached_probe", run)
    pc.invalidate_protocol_support(meta.id)
    return meta, interpreter, run


def assert_superseded(result):
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail == SUPERSEDED_DETAIL


def test_content_key_misses_equal_size_same_mtime_replacement(cache_app):
    meta, _, run = cache_app
    source = meta.relative_path / "config.py"
    source.write_bytes(b"first\n")
    old = source.stat()
    assert pc.probe_protocol_support(meta).accepted == ENDPOINT_VALUES
    pc.probe_protocol_support(meta)
    assert run.call_count == 1
    source.write_bytes(b"other\n")
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
    pc.probe_protocol_support(meta)
    assert run.call_count == 2
    latest = source.stat()
    os.utime(source, ns=(latest.st_atime_ns, latest.st_mtime_ns + 10_000))
    pc.probe_protocol_support(meta)
    assert run.call_count == 2
    source.write_bytes(b"changed contents and size\n")
    pc.probe_protocol_support(meta)
    assert run.call_count == 3


@pytest.mark.parametrize("count,want_runs", [(200, 1), (201, 2)])
def test_exact_threshold_and_overflow_never_cache(cache_app, count, want_runs):
    meta, _, run = cache_app
    for n in range(count):
        (meta.relative_path / f"m{n:03}.py").write_text("pass\n")
    pc.probe_protocol_support(meta)
    pc.probe_protocol_support(meta)
    assert run.call_count == want_runs


def test_growing_cached_tree_past_threshold_skips_lookup_and_insertion(cache_app):
    meta, _, run = cache_app
    (meta.relative_path / "config.py").write_text("pass\n")
    pc.probe_protocol_support(meta)
    pc.probe_protocol_support(meta)
    assert run.call_count == 1
    for n in range(200):
        (meta.relative_path / f"m{n:03}.py").write_text("pass\n")
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert run.call_count == 3


def test_use_cache_false_bypasses_lookup_and_cannot_overwrite_cached_answer(cache_app):
    meta, _, run = cache_app
    assert pc.probe_protocol_support(meta) == SUPPORTED
    run.return_value = PARTIAL
    assert pc.probe_protocol_support(meta, use_cache=False) == PARTIAL
    assert pc.probe_protocol_support(meta, use_cache=False) == PARTIAL
    assert run.call_count == 3
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert run.call_count == 3


def test_complete_key_unknown_can_cache_and_recover_after_invalidation(cache_app):
    meta, _, run = cache_app
    unknown = pc._unknown("Could not run protocol capability check: fixture failure")
    run.return_value = unknown
    assert pc.probe_protocol_support(meta) == unknown
    assert pc.probe_protocol_support(meta) == unknown
    assert run.call_count == 1
    pc.invalidate_protocol_support(meta.id)
    run.return_value = PARTIAL
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert run.call_count == 2


def test_interpreter_mtime_is_part_of_full_key(cache_app):
    meta, interpreter, run = cache_app
    pc.probe_protocol_support(meta)
    pc.probe_protocol_support(meta)
    assert run.call_count == 1
    old = interpreter.stat()
    os.utime(interpreter, ns=(old.st_atime_ns, old.st_mtime_ns + 10_000))
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert interpreter.read_bytes() == b"fixture interpreter\n"
    assert run.call_count == 2


def test_lexical_interpreter_path_keys_cache_and_is_passed_to_child(cache_app, monkeypatch):
    meta, interpreter, run = cache_app
    first = interpreter.parent / "first-python"
    second = interpreter.parent / "second-python"
    first.symlink_to(interpreter)
    second.symlink_to(interpreter)
    monkeypatch.setattr(pc, "resolve_app_interpreter", lambda path: first)
    pc.probe_protocol_support(meta)
    assert run.call_args.args == (meta, first, meta.relative_path.resolve())
    monkeypatch.setattr(pc, "resolve_app_interpreter", lambda path: second)
    pc.probe_protocol_support(meta)
    assert run.call_count == 2
    assert run.call_args.args == (meta, second, meta.relative_path.resolve())
    pc.probe_protocol_support(meta)
    assert run.call_count == 2


def test_resolved_launch_directory_and_original_resolver_argument(cache_app, monkeypatch):
    meta, interpreter, run = cache_app
    lexical = meta.relative_path.parent / "launch-link"
    lexical.symlink_to(meta.relative_path, target_is_directory=True)
    meta = meta.model_copy(update={"relative_path": lexical})
    resolver = Mock(return_value=interpreter)
    monkeypatch.setattr(pc, "resolve_app_interpreter", resolver)
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert resolver.call_args.args == (lexical,)
    assert run.call_args.args == (meta, interpreter, lexical.resolve())


@pytest.mark.parametrize(
    "selectable,app_id,status,detail",
    [
        (False, "ai-grammar", pc.ProtocolSupportStatus.UNSUPPORTED,
         "Protocol selection is not available for this application."),
        (True, "unknown", pc.ProtocolSupportStatus.UNVERIFIABLE,
         "No protocol probe is defined for unknown."),
    ],
)
def test_ineligible_metadata_never_resolves_scans_or_runs(
    cache_app, monkeypatch, selectable, app_id, status, detail
):
    meta, _, run = cache_app
    meta = meta.model_copy(update={"id": app_id, "supports_protocol_selection": selectable})
    fingerprint = Mock(return_value=("full", b"f" * 32))
    monkeypatch.setattr(pc, "source_fingerprint", fingerprint)
    result = pc.probe_protocol_support(meta)
    assert result.status is status
    assert result.accepted == frozenset()
    assert result.detail == detail
    assert pc.resolve_app_interpreter.call_count == 0
    assert fingerprint.call_count == 0
    assert run.call_count == 0


def test_source_fingerprint_hashes_exact_sorted_posix_stream(tmp_path, monkeypatch):
    (tmp_path / "nested").mkdir()
    sources = {
        "z.py": b"last\x00bytes\n",
        "nested/\u03b2.py": b"middle\r\n",
        "a.py": b"first\n",
    }
    for relative, content in sources.items():
        (tmp_path / relative).write_bytes(content)
    for name in (".env", "config.yaml", "credentials.json", "settings.toml"):
        (tmp_path / name).write_text("api_key=never-read-me\n")
    read_bytes = Path.read_bytes
    reads = []

    def python_only(path):
        assert path.suffix == ".py", f"fingerprint read unrelated content: {path}"
        reads.append(path.relative_to(tmp_path).as_posix())
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", python_only)
    stream = (
        b"a.py\0" + hashlib.sha256(b"first\n").hexdigest().encode("ascii") + b"\n"
        + "nested/\u03b2.py\0".encode("utf-8")
        + hashlib.sha256(b"middle\r\n").hexdigest().encode("ascii") + b"\n"
        + b"z.py\0" + hashlib.sha256(b"last\x00bytes\n").hexdigest().encode("ascii") + b"\n"
    )
    assert pc.source_fingerprint(tmp_path) == ("full", hashlib.sha256(stream).digest())
    assert reads == ["a.py", "nested/\u03b2.py", "z.py"]


def test_source_exclusions_ignore_virtualenvs_cache_and_directory_symlinks(
    tmp_path, monkeypatch
):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    visible = app_dir / "visible.py"
    visible.write_bytes(b"visible\n")
    excluded = []
    for name in ("__pycache__", ".venv", "venv", "custom-environment"):
        directory = app_dir / "nested" / name
        directory.mkdir(parents=True)
        excluded.append(directory / "hidden.py")
    (app_dir / "nested/custom-environment/pyvenv.cfg").write_text("never read marker\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    excluded.append(outside / "hidden.py")
    (app_dir / "linked-directory").symlink_to(outside, target_is_directory=True)
    for path in excluded:
        path.write_bytes(b"excluded\n")
    read_bytes = Path.read_bytes

    def visible_only(path):
        assert path == visible, f"fingerprint read excluded content: {path}"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", visible_only)
    stream = b"visible.py\0" + hashlib.sha256(b"visible\n").hexdigest().encode("ascii") + b"\n"
    expected = ("full", hashlib.sha256(stream).digest())
    assert pc.source_fingerprint(app_dir) == expected
    for path in excluded:
        path.write_bytes(b"different excluded contents\n")
        path.with_name("another.py").write_bytes(b"new excluded source\n")
    assert pc.source_fingerprint(app_dir) == expected
    visible.write_bytes(b"changed\n")
    assert pc.source_fingerprint(app_dir) != expected


def test_nonregular_virtualenv_marker_does_not_exclude_sources(tmp_path):
    directory = tmp_path / "normal"
    directory.mkdir()
    (directory / "pyvenv.cfg").mkdir()
    (directory / "code.py").write_bytes(b"pass\n")
    stream = b"normal/code.py\0" + hashlib.sha256(b"pass\n").hexdigest().encode("ascii") + b"\n"
    assert pc.source_fingerprint(tmp_path) == ("full", hashlib.sha256(stream).digest())


def test_python_leaf_symlink_hashes_regular_target_bytes_only(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    target = tmp_path / "external-source.txt"
    target.write_bytes(b"first\n")
    (app_dir / "alias.py").symlink_to(target)
    os.mkfifo(app_dir / "pipe.py")
    (app_dir / "pipe-link.py").symlink_to(app_dir / "pipe.py")
    (app_dir / "directory.py").symlink_to(tmp_path / "empty-dir", target_is_directory=True)
    (tmp_path / "empty-dir").mkdir()
    first_stream = b"alias.py\0" + hashlib.sha256(b"first\n").hexdigest().encode("ascii") + b"\n"
    expected = ("full", hashlib.sha256(first_stream).digest())
    assert pc.source_fingerprint(app_dir) == expected
    old = target.stat()
    target.write_bytes(b"other\n")
    os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert pc.source_fingerprint(app_dir) != expected


@pytest.mark.parametrize("mtime_base", [1_700_000_000_000_000_000, -2_000_000_000])
def test_overflow_reports_full_set_metadata_without_reading_source_contents(
    tmp_path, monkeypatch, mtime_base
):
    for n in range(201):
        path = tmp_path / f"m{n:03}.py"
        path.write_text("pass\n")
        os.utime(path, ns=(mtime_base + n, mtime_base + n))
    directory_mtime = tmp_path.stat().st_mtime_ns
    reads = Mock(side_effect=AssertionError("overflow must not read file contents"))
    monkeypatch.setattr(Path, "read_bytes", reads)
    assert pc.source_fingerprint(tmp_path) == (
        "coarse", 201, mtime_base + 200, directory_mtime
    )
    assert reads.call_count == 0


@pytest.mark.parametrize(
    "stage",
    ["resolver", "interpreter_stat", "read", "iteration", "directory_lstat",
     "marker_stat", "source_lstat", "symlink_stat"],
)
def test_preparation_failures_are_redacted_unknown_and_never_cached(
    cache_app, monkeypatch, stage
):
    meta, interpreter, run = cache_app
    source = meta.relative_path / "config.py"
    source.write_text("pass\n")
    directory = meta.relative_path / "nested"
    directory.mkdir()
    (directory / "code.py").write_text("pass\n")
    marker = directory / "pyvenv.cfg"
    link = meta.relative_path / "alias.py"
    link.symlink_to(source)
    failure = PermissionError("api_key=preparation-secret")
    with monkeypatch.context() as patch:
        if stage == "resolver":
            patch.setattr(pc, "resolve_app_interpreter", Mock(side_effect=failure))
        elif stage == "read":
            original = Path.read_bytes

            def fail_read(path):
                if path == source:
                    raise failure
                return original(path)

            patch.setattr(Path, "read_bytes", fail_read)
        elif stage == "iteration":
            def fail_walk(top, *, followlinks, onerror):
                onerror(failure)
                yield from ()  # a suppressed walk error must end enumeration normally

            patch.setattr(pc.os, "walk", fail_walk)
        elif stage in ("directory_lstat", "source_lstat"):
            original = Path.lstat
            failing_path = directory if stage == "directory_lstat" else source

            def fail_lstat(path):
                if path == failing_path:
                    raise failure
                return original(path)

            patch.setattr(Path, "lstat", fail_lstat)
        else:
            original = Path.stat
            failing_path = {
                "interpreter_stat": interpreter, "marker_stat": marker, "symlink_stat": link
            }[stage]

            def fail_stat(path, **kwargs):
                if path == failing_path and kwargs.get("follow_symlinks", True):
                    raise failure
                return original(path, **kwargs)

            patch.setattr(Path, "stat", fail_stat)
        for _ in range(2):
            result = pc.probe_protocol_support(meta)
            assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
            assert result.accepted == frozenset()
            assert result.detail.startswith("Protocol capability check could not be prepared:")
            assert "preparation-secret" not in result.detail
        assert run.call_count == 0
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert run.call_count == 1


def test_dangling_python_symlink_is_unverifiable_without_cached_acceptance(cache_app):
    meta, _, run = cache_app
    link = meta.relative_path / "broken.py"
    link.symlink_to(meta.relative_path / "missing-source")
    for _ in range(2):
        result = pc.probe_protocol_support(meta)
        assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
        assert result.accepted == frozenset()
    assert run.call_count == 0
    link.unlink()
    assert pc.probe_protocol_support(meta) == SUPPORTED
    assert run.call_count == 1


def test_second_identity_failure_does_not_publish_or_cache_old_result(cache_app, monkeypatch):
    meta, _, run = cache_app
    original = pc.source_fingerprint
    calls = 0

    def fail_second_scan(app_dir):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("api_key=second-scan-secret")
        return original(app_dir)

    monkeypatch.setattr(pc, "source_fingerprint", fail_second_scan)
    result = pc.probe_protocol_support(meta)
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail.startswith("Protocol capability check could not be prepared:")
    assert "second-scan-secret" not in result.detail
    assert run.call_count == 1
    run.return_value = PARTIAL
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert run.call_count == 2


def test_unexpected_execution_failure_becomes_redacted_unknown(cache_app):
    meta, _, run = cache_app
    run.side_effect = RuntimeError("api_key=worker-secret")
    result = pc.probe_protocol_support(meta)
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE
    assert result.accepted == frozenset()
    assert result.detail.startswith("Protocol capability check failed:")
    assert "worker-secret" not in result.detail


def test_generations_start_zero_and_invalidation_is_per_app(tmp_path):
    app_id = f"unseen-{tmp_path.name}"
    unrelated = f"unrelated-{tmp_path.name}"
    assert pc.protocol_support_generation(app_id) == 0
    assert pc.protocol_support_generation(unrelated) == 0
    pc.invalidate_protocol_support(app_id)
    assert pc.protocol_support_generation(app_id) == 1
    assert pc.protocol_support_generation(unrelated) == 0
    pc.invalidate_protocol_support(app_id)
    assert pc.protocol_support_generation(app_id) == 2


def test_invalidation_evicts_every_key_for_app_and_preserves_other_apps(cache_app):
    meta, _, run = cache_app
    other = meta.model_copy(update={"id": "textkit"})
    pc.invalidate_protocol_support(other.id)
    source = meta.relative_path / "config.py"
    source.write_bytes(b"first\n")
    pc.probe_protocol_support(meta)
    source.write_bytes(b"other\n")
    pc.probe_protocol_support(meta)
    pc.probe_protocol_support(other)
    assert run.call_count == 3
    before = pc.protocol_support_generation(meta.id)
    pc.invalidate_protocol_support(meta.id)
    assert pc.protocol_support_generation(meta.id) == before + 1
    assert pc.probe_protocol_support(other) == SUPPORTED
    assert run.call_count == 3
    pc.probe_protocol_support(meta)
    source.write_bytes(b"first\n")
    pc.probe_protocol_support(meta)
    assert run.call_count == 5


@pytest.mark.parametrize("use_cache", [True, False])
def test_old_generation_cannot_publish_over_new_result(cache_app, use_cache):
    meta, _, run = cache_app
    started = threading.Event()
    release = threading.Event()

    def execute_probe(*args):
        if run.call_count == 1:
            started.set()
            assert release.wait(2), "old probe was never released"
            return SUPPORTED
        return PARTIAL

    run.side_effect = execute_probe
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(pc.probe_protocol_support, meta, use_cache=use_cache)
        try:
            assert started.wait(2), "old probe never started"
            invalidation = pool.submit(pc.invalidate_protocol_support, meta.id)
            assert invalidation.result(timeout=2) is None
            assert not old.done(), "invalidation waited for the blocked probe"
            fresh = pool.submit(pc.probe_protocol_support, meta).result(timeout=2)
            assert fresh == PARTIAL
        finally:
            release.set()
        old_result = old.result(timeout=2)
    assert_superseded(old_result)
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert run.call_count == 2


@pytest.mark.parametrize("change", ["source", "interpreter_mtime", "activation"])
def test_identity_changed_during_probe_cannot_publish(cache_app, monkeypatch, change):
    meta, interpreter, run = cache_app
    source = meta.relative_path / "config.py"
    source.write_bytes(b"first\n")
    old_stat = source.stat()
    started = threading.Event()
    release = threading.Event()

    def execute_probe(*args):
        if run.call_count == 1:
            started.set()
            assert release.wait(2), "probe was never released"
            return SUPPORTED
        return PARTIAL

    run.side_effect = execute_probe
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(pc.probe_protocol_support, meta)
        try:
            assert started.wait(2), "probe never started"
            if change == "source":
                source.write_bytes(b"other\n")
                os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            elif change == "interpreter_mtime":
                old = interpreter.stat()
                os.utime(interpreter, ns=(old.st_atime_ns, old.st_mtime_ns + 10_000))
            else:
                alternate = interpreter.parent / "other-python"
                alternate.symlink_to(interpreter)
                monkeypatch.setattr(pc, "resolve_app_interpreter", lambda path: alternate)
        finally:
            release.set()
        result = future.result(timeout=2)
    assert_superseded(result)
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert run.call_count == 2


def test_queued_obsolete_generation_never_resolves_or_spawns(cache_app, monkeypatch):
    meta, _, run = cache_app
    generation = pc.protocol_support_generation(meta.id)
    pc.invalidate_protocol_support(meta.id)
    fingerprint = Mock(return_value=("full", b"f" * 32))
    monkeypatch.setattr(pc, "source_fingerprint", fingerprint)
    result = pc._probe_protocol_support_at_generation(meta, generation=generation)
    assert_superseded(result)
    assert pc.resolve_app_interpreter.call_count == 0
    assert fingerprint.call_count == 0
    assert run.call_count == 0


def test_invalidation_during_cache_hit_scan_rejects_cached_answer(cache_app, monkeypatch):
    meta, _, run = cache_app
    pc.probe_protocol_support(meta)
    pc.probe_protocol_support(meta)
    assert run.call_count == 1
    original = pc.source_fingerprint
    started = threading.Event()
    release = threading.Event()

    def blocked_fingerprint(app_dir):
        if not started.is_set():
            started.set()
            assert release.wait(2), "cache-hit scan was never released"
        return original(app_dir)

    monkeypatch.setattr(pc, "source_fingerprint", blocked_fingerprint)
    run.return_value = PARTIAL
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(pc.probe_protocol_support, meta)
        try:
            assert started.wait(2), "cache-hit scan never started"
            invalidation = pool.submit(pc.invalidate_protocol_support, meta.id)
            assert invalidation.result(timeout=2) is None
            assert not future.done(), "invalidation waited for the blocked scan"
            # Refill the identical key in the new generation before the old lookup.
            fresh = pool.submit(pc.probe_protocol_support, meta).result(timeout=2)
            assert fresh == PARTIAL
        finally:
            release.set()
        result = future.result(timeout=2)
    assert_superseded(result)
    assert pc.probe_protocol_support(meta) == PARTIAL
    assert run.call_count == 2
