import json
import os
from pathlib import Path
import sys
import time
import pytest
from ai_manager.services import app_interpreter as ai
from ai_manager.services import service_validation as sv
from ai_manager.config.config_errors import InterpreterUnavailableError, ServiceValidationError, ServiceValidationTimeout

FAKE = '''import json, os, sys, time
from pathlib import Path
if len(sys.argv) == 3:
    if os.environ.get("MANAGER_TEST_IMPORT_SLEEP"):
        time.sleep(30)
    raise SystemExit(int(os.environ.get("MANAGER_TEST_IMPORT_EXIT", "0")))
candidate = Path(sys.argv[3])
Path(os.environ["MANAGER_TEST_RECORD"]).write_text(json.dumps({"pid":os.getpid(), "cwd":str(Path.cwd()), "argv":sys.argv[1:], "candidate":str(candidate), "bytes":candidate.read_text(encoding="utf-8"), "mode":candidate.stat().st_mode & 0o777, "environment":os.environ.get("MANAGER_TEST_SENTINEL")}), encoding="utf-8")
if os.environ.get("MANAGER_TEST_SLEEP"):
    time.sleep(30)
print(os.environ.get("MANAGER_TEST_STDOUT", ""), end="")
print(os.environ.get("MANAGER_TEST_STDERR", ""), end="", file=sys.stderr)
raise SystemExit(int(os.environ.get("MANAGER_TEST_VALIDATOR_EXIT", "0")))
'''


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


@pytest.fixture
def fake_interpreter(tmp_path, monkeypatch):
    app = tmp_path / "application"
    app.mkdir()
    record = tmp_path / "record.json"
    python = executable(app / ".venv" / "bin" / "python", FAKE)
    (python.parent / "activate").write_text("# synthetic activation\n")
    monkeypatch.setenv("MANAGER_TEST_RECORD", str(record))
    monkeypatch.setenv("MANAGER_TEST_SENTINEL", "inherited fixture")
    for name in ("MANAGER_TEST_IMPORT_EXIT", "MANAGER_TEST_VALIDATOR_EXIT", "MANAGER_TEST_IMPORT_SLEEP", "MANAGER_TEST_SLEEP", "MANAGER_TEST_STDOUT", "MANAGER_TEST_STDERR"):
        monkeypatch.delenv(name, raising=False)
    return app, record, python


@pytest.mark.parametrize("selection", ["both", "venv", "ambient", "directory-only"])
def test_activation_precedence_and_lexical_path(tmp_path, monkeypatch, selection):
    app = tmp_path / "app"
    app.mkdir()
    ambient = executable(tmp_path / "path" / "python", "raise SystemExit(0)\n")
    monkeypatch.setenv("PATH", str(ambient.parent) + os.pathsep + os.environ.get("PATH", ""))
    for env in (".venv", "venv"):
        folder = app / env / "bin"
        folder.mkdir(parents=True)
        (folder / "python").symlink_to(sys.executable)
        if selection == "both" or selection == "venv" and env == "venv":
            (folder / "activate").write_text("# fixture\n")
    selected = ai.resolve_app_interpreter(app)
    expected = app / ".venv/bin/python" if selection == "both" else app / "venv/bin/python" if selection == "venv" else ambient
    assert selected == expected.absolute()
    if selection in ("both", "venv"):
        assert selected.is_symlink() and selected != selected.resolve()


@pytest.mark.parametrize("failure", ["missing", "nonexec", "no-ambient"])
def test_selected_broken_interpreter_never_falls_back(tmp_path, monkeypatch, failure):
    app = tmp_path / "app"
    app.mkdir()
    if failure != "no-ambient":
        folder = app / ".venv/bin"
        folder.mkdir(parents=True)
        (folder / "activate").write_text("# fixture\n")
        if failure == "nonexec":
            (folder / "python").write_text("not executable")
    else:
        monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    with pytest.raises(InterpreterUnavailableError):
        ai.resolve_app_interpreter(app)


@pytest.mark.parametrize("kind,program,module", [("chat2api", "import app, fastapi", "app"), ("file-bridge", "import main, fastapi", "main")])
def test_import_probe_runs_in_app_directory_with_kind_program(tmp_path, monkeypatch, kind, program, module):
    app = tmp_path / "probe-app"
    app.mkdir()
    (app / "fastapi.py").write_text("")
    if module == "app":
        (app / module).mkdir()
        (app / module / "__init__.py").write_text("")
    else:
        (app / "main.py").write_text("")
    record = tmp_path / "probe-record.json"
    interpreter = app / "venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['MANAGER_TEST_PROBE_RECORD']).write_text(\n"
        "    json.dumps({'cwd': str(Path.cwd()), 'argv': sys.argv[1:]}), encoding='utf-8')\n"
        f"os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])\n"
    )
    interpreter.chmod(0o700)
    (interpreter.parent / "activate").write_text("# fixture\n")
    monkeypatch.setenv("MANAGER_TEST_PROBE_RECORD", str(record))
    ai.verify_app_interpreter(kind, app, interpreter)
    data = json.loads(record.read_text(encoding="utf-8"))
    assert Path(data["cwd"]) == app.resolve()
    assert data["argv"] == ["-c", program]


@pytest.mark.parametrize("kind", ["chat2api", "file-bridge"])
def test_validator_success_argv_bytes_cwd_and_adjacent_cleanup(fake_interpreter, kind):
    app, record, selected = fake_interpreter
    target = app / ("config.json" if kind == "chat2api" else "config.yaml")
    raw = b'{"server":{"auth_token_env":null},"models":{}}\n' if kind == "chat2api" else b'save_root: "../storage"\n'
    result = sv.validate_candidate(kind, target, app, raw)
    data = json.loads(record.read_text())
    expected_program = sv.CHAT2API_VALIDATE_PROGRAM if kind == "chat2api" else sv.FILE_BRIDGE_VALIDATE_PROGRAM
    assert data["argv"] == ["-c", expected_program, data["candidate"]]
    candidate = Path(data["candidate"])
    assert candidate.parent == target.parent.resolve() and candidate.name.startswith(f".{target.name}.ai-manager-validate-")
    assert data["cwd"] == str(app.resolve()) and data["bytes"].encode() == raw
    assert data["mode"] == 0o600 and data["environment"] == "inherited fixture"
    assert not candidate.exists() and not target.exists()
    assert result.scope == "service"
    assert result.notice == f"configuration valid — validated by {kind} · ai-manager"


@pytest.mark.parametrize("exit_code,expected", [(1, "reject"), (75, "unavailable"), (-1, "reject")])
def test_validator_exit_is_not_import_probe_exit(fake_interpreter, monkeypatch, exit_code, expected):
    app, record, selected = fake_interpreter
    monkeypatch.setenv("MANAGER_TEST_VALIDATOR_EXIT", str(exit_code))
    monkeypatch.setenv("MANAGER_TEST_STDERR", "fixture schema error\n")
    monkeypatch.setenv("MANAGER_TEST_STDOUT", "fixture stdout\n")
    if expected == "reject":
        with pytest.raises(ServiceValidationError) as err:
            sv.validate_candidate("chat2api", app / "config.json", app, b"{}\n")
        assert err.value.stderr == "fixture schema error\n" and err.value.stdout == "fixture stdout\n"
        assert err.value.returncode == (255 if exit_code == -1 else exit_code)
    else:
        result = sv.validate_candidate("chat2api", app / "config.json", app, b"{}\n")
        assert result.scope == "manager-only" and "fixture schema error\n" in result.detail
        assert result.notice == "validated by ai-manager only — service validator unavailable"
    assert record.exists() and not Path(json.loads(record.read_text())["candidate"]).exists()


def test_import_failure_degrades_without_running_validator(fake_interpreter, monkeypatch):
    app, record, selected = fake_interpreter
    monkeypatch.setenv("MANAGER_TEST_IMPORT_EXIT", "1")
    result = sv.validate_candidate("chat2api", app / "config.json", app, b"{}")
    assert result.scope == "manager-only" and not record.exists()
    selected.unlink()
    assert sv.validate_candidate("chat2api", app / "config.json", app, b"{}").scope == "manager-only"


def test_timeout_kills_reaps_and_cleans(fake_interpreter, monkeypatch):
    app, record, selected = fake_interpreter
    children = []
    original = sv.subprocess.Popen
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(sv.subprocess, "Popen", spawn)
    monkeypatch.setattr(sv, "VALIDATOR_TIMEOUT_S", 0.15)
    monkeypatch.setenv("MANAGER_TEST_SLEEP", "1")
    with pytest.raises(ServiceValidationTimeout):
        sv.validate_candidate("chat2api", app / "config.json", app, b"{}")
    assert all(child.poll() is not None for child in children)
    data = json.loads(record.read_text())
    assert not Path(data["candidate"]).exists()
    monkeypatch.delenv("MANAGER_TEST_SLEEP")
    monkeypatch.setenv("MANAGER_TEST_IMPORT_SLEEP", "1")
    monkeypatch.setattr(ai, "IMPORT_TIMEOUT_S", 0.15)
    assert sv.validate_candidate("chat2api", app / "config.json", app, b"{}").scope == "manager-only"
    assert all(child.poll() is not None for child in children)


def test_validator_cwd_is_the_app_directory_not_the_target_parent(fake_interpreter):
    app, record, selected = fake_interpreter
    nested = app / "profiles"
    nested.mkdir()
    sv.validate_candidate("chat2api", nested / "config.json", app, b'{}\n')
    data = json.loads(record.read_text())
    assert data["cwd"] == str(app.resolve())
    assert Path(data["candidate"]).parent == nested.resolve()
    assert not Path(data["candidate"]).exists()


def test_symlinked_parent_uses_actual_candidate_location(fake_interpreter, tmp_path):
    app, record, selected = fake_interpreter
    link = tmp_path / "linked-parent"
    link.symlink_to(app, target_is_directory=True)
    sv.validate_candidate("file-bridge", link / "config.yaml", app, b'save_root: "../storage"\n')
    data = json.loads(record.read_text())
    assert Path(data["candidate"]).parent == app.resolve()
    assert (Path(data["candidate"]).parent / "../storage").resolve() == (app.parent / "storage").resolve()


CONFIG_MODULE = '''import json, os
from pathlib import Path
from types import SimpleNamespace
def load_config(path):
    dotenv = Path(".env")
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    data = json.loads(Path(path).read_text())
    def validate_auth():
        name = data.get("server", {}).get("auth_token_env", "CHAT2API_TOKEN")
        if name is not None and not os.environ.get(name):
            raise RuntimeError("fixture auth variable is missing or empty")
    return SimpleNamespace(validate_auth=validate_auth, data=data)
'''
REGISTRY_MODULE = '''class Registry:
    def __init__(self, cfg):
        if cfg.data.get("reject_registry"):
            raise RuntimeError("fixture registry runtime failure")
def startup_login():
    raise AssertionError("network login must never run")
def ensure_discovered():
    raise AssertionError("discovery must never run")
'''


@pytest.mark.parametrize("auth,env_value,dotenv,valid", [("FIXTURE_TOKEN", None, False, False), ("FIXTURE_TOKEN", "", False, False), ("FIXTURE_TOKEN", None, True, True), (None, None, False, True)])
def test_real_program_auth_and_no_runtime_calls(tmp_path, monkeypatch, auth, env_value, dotenv, valid):
    app = tmp_path / "isolated-app"
    package = app / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (app / "fastapi.py").write_text("")
    (package / "config.py").write_text(CONFIG_MODULE)
    (package / "registry.py").write_text(REGISTRY_MODULE)
    selected = app / "venv/bin/python"
    selected.parent.mkdir(parents=True)
    selected.symlink_to(sys.executable)
    (selected.parent / "activate").write_text("# conventional fixture\n")
    monkeypatch.delenv("FIXTURE_TOKEN", raising=False)
    if env_value is not None:
        monkeypatch.setenv("FIXTURE_TOKEN", env_value)
    if dotenv:
        (app / ".env").write_text("FIXTURE_TOKEN=fixture-bearer-value\n")
    data = {"server": {"auth_token_env": auth}, "models": {"echo-1": {"provider": "echo"}}}
    raw = json.dumps(data).encode()
    if valid:
        assert sv.validate_candidate("chat2api", app / "config.json", app, raw).scope == "service"
        data["reject_registry"] = True
        with pytest.raises(ServiceValidationError) as err:
            sv.validate_candidate("chat2api", app / "config.json", app, json.dumps(data).encode())
        assert "fixture registry runtime failure" in err.value.stderr
    else:
        with pytest.raises(ServiceValidationError) as err:
            sv.validate_candidate("chat2api", app / "config.json", app, raw)
        assert "fixture auth variable is missing or empty" in err.value.stderr
    assert not list(app.glob(".*.ai-manager-validate-*"))


def test_import_probe_timeout_is_bounded_kills_and_reaps(tmp_path, monkeypatch):
    app = tmp_path / "slow-app"
    app.mkdir()
    interpreter = app / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(
        f"#!{sys.executable}\nimport time\ntime.sleep(30)\n", encoding="utf-8"
    )
    interpreter.chmod(0o700)
    (interpreter.parent / "activate").write_text("# fixture\n")
    children = []
    original = ai.subprocess.Popen

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(ai.subprocess, "Popen", spawn)
    monkeypatch.setattr(ai, "IMPORT_TIMEOUT_S", 0.15)
    started = time.monotonic()
    with pytest.raises(InterpreterUnavailableError) as err:
        ai.verify_app_interpreter("chat2api", app, interpreter)
    assert time.monotonic() - started < 10
    assert "timed out" in str(err.value)
    assert children and all(child.poll() is not None for child in children)


@pytest.mark.parametrize("kind", ["llm", "unknown", None, 3])
def test_unknown_kind_raises_unknown_config_kind_error(tmp_path, kind):
    from ai_manager.config.config_errors import UnknownConfigKindError

    app = tmp_path / "app"
    app.mkdir()
    with pytest.raises(UnknownConfigKindError):
        sv.validate_candidate(kind, app / "config.json", app, b"{}\n")
    with pytest.raises(UnknownConfigKindError):
        ai.verify_app_interpreter(kind, app, app / "venv/bin/python")


@pytest.mark.parametrize("kind", [[], {}, set()])
def test_unhashable_unknown_kind_raises_unknown_config_kind_error(tmp_path, kind):
    from ai_manager.config.config_errors import UnknownConfigKindError

    app = tmp_path / "app"
    app.mkdir()
    with pytest.raises(UnknownConfigKindError):
        sv.validate_candidate(kind, app / "config.json", app, b"{}\n")
    with pytest.raises(UnknownConfigKindError):
        ai.verify_app_interpreter(kind, app, app / "venv/bin/python")
