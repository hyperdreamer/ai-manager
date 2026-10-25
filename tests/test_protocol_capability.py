import json
import os
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

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
