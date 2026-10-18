import copy
from pathlib import Path

import pytest

from ai_manager.config import structured_schema as ss
from ai_manager.config.config_errors import ConfigValidationError
from ai_manager.config.structured_models import Mutation

SERVERS = [
    ({"host": "127.0.0.1", "port": True, "auth_token_env": None}, False, "port"),
    ({"host": "127.0.0.1", "port": "8000", "auth_token_env": None}, False, "port"),
    ({"host": "127.0.0.1", "port": 8000.0, "auth_token_env": None}, False, "port"),
    ({"host": "127.0.0.1", "port": 0, "auth_token_env": None}, False, "port"),
    ({"host": "127.0.0.1", "port": 65536, "auth_token_env": None}, False, "port"),
    ({"host": "127.0.0.1", "port": 1, "auth_token_env": None}, True, None),
    ({"host": "127.0.0.1", "port": 65535, "auth_token_env": None}, True, None),
    ({"host": "", "port": 8000, "auth_token_env": None}, False, "host"),
    ({"host": "127.0.0.1", "port": 8000, "auth_token_env": ""}, False, "auth_token_env"),
    ({"host": "127.0.0.1", "port": 8000, "auth_token_env": "BAD-NAME"}, False, "auth_token_env"),
    ({"host": "127.0.0.1", "port": 8000, "auth_token_env": "9BAD"}, False, "auth_token_env"),
    ({"host": "127.0.0.1", "port": 8000, "auth_token_env": "_TOKEN_9"}, True, None),
    ({"host": "127.0.0.1", "port": 8000, "auth_token_env": None}, True, None),
    ({"host": "127.0.0.1", "port": 8000}, True, None),
    ({"host": "localhost", "port": 8000, "auth_token_env": None}, True, None),
    ({"host": "LOCALHOST", "port": 8000, "auth_token_env": None}, True, None),
    ({"host": "::1", "port": 8000, "auth_token_env": None}, True, None),
    ({"host": "0.0.0.0", "port": 8000, "auth_token_env": None}, False, "host"),
    ({"host": "::", "port": 8000, "auth_token_env": None}, False, "host"),
    ({"host": "192.0.2.5", "port": 8000, "auth_token_env": None}, False, "host"),
    ({"host": " localhost ", "port": 8000, "auth_token_env": None}, False, "host"),
    ({"host": "localhost\n", "port": 8000, "auth_token_env": None}, False, "host"),
    ({"host": "127.0.0.2", "port": 8000, "auth_token_env": None}, False, "host"),
]
MESSAGES = {
    "port": "Port must be an integer from 1 to 65535.",
    "auth_token_env": "Auth token environment variable must be null or a valid environment variable name.",
    "max_text_bytes": "Maximum text bytes must be an integer from 0 to 104857600.",
}


def validate(kind, doc, workspace):
    app_dir = workspace / kind
    ss.validate_in_process(
        kind,
        doc,
        config_path=app_dir / ("config.json" if kind == "chat2api" else "config.yaml"),
        app_dir=app_dir,
    )


@pytest.mark.parametrize("server,valid,key", SERVERS)
def test_all_chat_server_cases(five_app_workspace, server, valid, key):
    doc = {"server": server, "models": {"echo-1": {"provider": "echo"}}}
    original = copy.deepcopy(doc)
    if valid:
        validate("chat2api", doc, five_app_workspace)
    else:
        with pytest.raises(ConfigValidationError) as err:
            validate("chat2api", doc, five_app_workspace)
        issue = err.value.issues[0]
        assert issue.address == ("server", key)
        if key == "host":
            expected = (
                "Host must be a non-empty string."
                if server[key] == ""
                else "Host must be a loopback address (127.0.0.1, localhost, or ::1). Binding a wildcard or external interface is not supported for this local service."
            )
        else:
            expected = MESSAGES[key]
        assert issue.message == expected
    assert doc == original


@pytest.mark.parametrize("models,valid", [
    ({"": {"provider": "echo"}}, False), ({"x": {"provider": "unknown"}}, False),
    ({"x": {}}, False), ({"x": {"provider": "echo"}}, True),
    ({"x": {"provider": "gemini_webapi", "options": {}}}, True),
    ({"x": {"provider": "copilot_webapi", "options": {"future": [1, None]}}}, True),
    ({"x": {"provider": "browser", "options": {"url": "https://example.invalid"}}}, True),
    ([], False), ({"x": 1}, False), ({"x": {"provider": "echo", "options": None}}, False),
    ({"x": {"provider": "echo", "options": []}}, False),
])
def test_model_maps(five_app_workspace, models, valid):
    doc = {"server": {"auth_token_env": None}, "models": models}
    if valid:
        validate("chat2api", doc, five_app_workspace)
        if models == {"x": {"provider": "echo"}}:
            assert "options" not in doc["models"]["x"]
    else:
        with pytest.raises(ConfigValidationError):
            validate("chat2api", doc, five_app_workspace)


@pytest.mark.parametrize("key,value,valid", [
    *[("port", n, False) for n in (True, "8964", 8964.0, 0, 65536)],
    *[("port", n, True) for n in (1, 65535)],
    *[("max_text_bytes", n, False) for n in (True, "1", 1.0, -1, 104857601)],
    *[("max_text_bytes", n, True) for n in (0, 1048576, 104857600)],
])
def test_bridge_integer_contract(five_app_workspace, key, value, valid):
    doc = {"save_root": "../storage", "max_text_bytes": 1048576, "port": 8964, key: value}
    if valid:
        validate("file-bridge", doc, five_app_workspace)
    else:
        with pytest.raises(ConfigValidationError) as err:
            validate("file-bridge", doc, five_app_workspace)
        assert err.value.issues[0].address == (key,)
        assert err.value.issues[0].message == MESSAGES[key]


@pytest.mark.parametrize("value,valid", [("", False), ("   ", False), (None, False), (42, False), ("../does-not-exist", False), ("../plain-file", False), (".", False), ("./nested", False), ("../storage", True), ("../资料", True)])
def test_bridge_root_rules(five_app_workspace, value, valid):
    w = five_app_workspace
    (w / "plain-file").write_text("not a directory")
    (w / "file-bridge" / "nested").mkdir()
    (w / "资料").mkdir()
    doc = {"save_root": value}
    if valid:
        validate("file-bridge", doc, w)
    else:
        with pytest.raises(ConfigValidationError) as err:
            validate("file-bridge", doc, w)
        assert err.value.issues[0].address == ("save_root",)
    assert doc == {"save_root": value}


def test_tilde_access_probe_unknown_and_path_errors(five_app_workspace, monkeypatch):
    w = five_app_workspace
    original_expand = Path.expanduser
    monkeypatch.setattr(Path, "expanduser", lambda p: w / "storage" if str(p) == "~" else original_expand(p))
    validate("file-bridge", {"save_root": "~"}, w)
    with pytest.raises(ConfigValidationError) as err:
        validate("file-bridge", {"save_root": "../storage", "unexpected": True}, w)
    assert err.value.issues[0].address == ("unexpected",)
    assert err.value.issues[0].message == "Unknown file-bridge configuration key: unexpected"
    with monkeypatch.context() as patch:
        patch.setattr(ss.os, "access", lambda *args: False)
        with pytest.raises(ConfigValidationError, match="invalid fields") as err:
            validate("file-bridge", {"save_root": "../storage"}, w)
        assert err.value.issues[0].message == "Save root must be readable and writable."
    with monkeypatch.context() as patch:
        def fail(**kwargs):
            raise PermissionError("fixture unwritable root")
        patch.setattr(ss.tempfile, "TemporaryFile", fail)
        with pytest.raises(ConfigValidationError):
            validate("file-bridge", {"save_root": "../storage"}, w)
    with monkeypatch.context() as patch:
        def bad_expand(path):
            raise ValueError("fixture invalid path")
        patch.setattr(Path, "expanduser", bad_expand)
        with pytest.raises(ConfigValidationError) as err:
            validate("file-bridge", {"save_root": "../storage"}, w)
        assert err.value.issues[0].address == ("save_root",)


@pytest.mark.parametrize("bad", ["bad\nvalue", "bad\rvalue", "bad\0value"])
@pytest.mark.parametrize("address", [("server", "host"), ("server", "auth_token_env"), ("save_root",), ("models", "echo-1", "options", "prefix")])
def test_written_string_controls(bad, address):
    with pytest.raises(ConfigValidationError) as err:
        ss.validate_written_scalars((Mutation(address, "set", bad),))
    assert err.value.issues[0].address == address
    assert err.value.issues[0].message == "This value must not contain newline, carriage return, or NUL characters."


@pytest.mark.parametrize("bad", ["bad\nvalue", "bad\rvalue", "bad\0value"])
def test_written_keys_and_nested_lists(bad):
    for mutation in (
        Mutation(("models", bad), "set", {"provider": "echo"}),
        Mutation(("models", "echo-1", "options", "future"), "set", {"nested": [1, {bad: "ok"}]}),
        Mutation(("models", "echo-1", "options", "future"), "set", {"nested": [1, bad]}),
    ):
        with pytest.raises(ConfigValidationError):
            ss.validate_written_scalars((mutation,))
    ss.validate_written_scalars((Mutation(("models", bad), "delete"),))


def test_only_addressed_strings_and_no_defaults(five_app_workspace):
    doc = {"models": {"echo-1": {"provider": "echo", "options": {"future": "already\nodd"}}}, "server": {"auth_token_env": None}}
    ss.validate_written_scalars((Mutation(("server", "port"), "set", 8123),))
    validate("chat2api", doc, five_app_workspace)
    for value in ("雪", "资料", "a\tb"):
        ss.validate_written_scalars((Mutation(("models", "echo-1", "options", "prefix"), "set", value),))
    original = copy.deepcopy(doc)
    validate("chat2api", doc, five_app_workspace)
    assert doc == original and "port" not in doc["server"]
    assert "server" not in ss.Chat2ApiSchema.model_validate({}).model_fields_set
