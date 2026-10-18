import copy
import hashlib
import json
import stat
from dataclasses import replace
import pytest
from ai_manager.config import structured_config as sc
from ai_manager.config.structured_models import Mutation
from ai_manager.config.config_errors import (
    ConfigLoadError, ConfigValidationError, ReadOnlyConfigError,
    StaleDocumentError, SymlinkConfigError,
)

J = '''{
  "_comments": {"keep": "ordinary data", "nested": [1, {"x": true}]},
  "server": {"host": "127.0.0.1", "port": 8000, "auth_token_env": null, "future": {"keep": "yes"}},
  "models": {
    "gemini.fast/v2": {"provider": "gemini_webapi", "options": {"account": "fixture@example.invalid", "password": "fixture-password", "future": {"keep": [1, "雪"]}, "headless": true}, "route_extra": 17},
    "echo-1": {"provider": "echo"}
  },
  "tail": ["untouched", {"a": 1, "b": 2}]
}
'''
Y = "# Bridge configuration\nsave_root: '../storage' # preserve destination spelling\nmax_text_bytes: 1048576 # keep limit\n# Selected listener\nport: 8964\n# end\n"


@pytest.mark.parametrize("kind,name,text,address,value", [
    ("chat2api", "config.json", J, ("server", "port"), 8123),
    ("file-bridge", "config.yaml", Y, ("port",), 8970),
])
def test_load_render_fidelity(tmp_path, kind, name, text, address, value):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    doc = sc.load(kind, path)
    assert doc.path == path.absolute() and doc.resolved_path == path
    assert doc.raw_bytes == text.encode() and doc.raw_sha256 == hashlib.sha256(text.encode()).digest()
    assert doc.existed and not doc.mutations and not doc.input_issues
    old_tree = copy.deepcopy(doc.doc)
    draft = replace(doc, mutations=(Mutation(address, "set", value),))
    rendered = sc.render(kind, draft)
    assert path.read_bytes() == text.encode() and doc.doc == old_tree
    if kind == "chat2api":
        expected = json.loads(J)
        expected["server"]["port"] = 8123
        assert rendered == (json.dumps(expected, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        actual = json.loads(rendered)
        assert actual["models"] == old_tree["models"] and actual["tail"] == old_tree["tail"]
        assert list(actual) == list(old_tree)
        assert list(actual["models"]["gemini.fast/v2"]["options"]) == list(old_tree["models"]["gemini.fast/v2"]["options"])
        assert "options" not in actual["models"]["echo-1"]
    else:
        assert rendered.decode() == Y.replace("port: 8964", "port: 8970")


def test_literal_address_rename_and_deletion(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(J)
    d = sc.load("chat2api", p)
    one = replace(d, mutations=(Mutation(("models", "gemini.fast/v2", "options", "headless"), "set", False),))
    result = json.loads(sc.render("chat2api", one))
    assert result["models"]["gemini.fast/v2"]["options"]["headless"] is False
    assert "gemini" not in result["models"]
    changed = replace(d, mutations=(Mutation(("models", "echo-1"), "delete"), Mutation(("models", "gemini.fast/v2"), "delete"), Mutation(("models", "renamed"), "set", copy.deepcopy(d.doc["models"]["gemini.fast/v2"]))))
    assert json.loads(sc.render("chat2api", changed))["models"] == {"renamed": d.doc["models"]["gemini.fast/v2"]}
    overlap = replace(d, mutations=(Mutation(("server",), "set", {}), Mutation(("server", "port"), "set", 9)))
    with pytest.raises(ConfigValidationError):
        sc.render("chat2api", overlap)


@pytest.mark.parametrize("raw", [b"[]", b'{"models":[]}', b'{"models":{"x":1}}', b'{"models":{"x":{"provider":"echo","options":null}}}', b'{"models":{"x":{"options":[]}}}', b'{"server":[]}', b'{"models":{"same":{},"same":{}}}', b'{"server":', b'\xff', b'{"x":NaN}'])
def test_bad_json_is_a_load_error(tmp_path, raw):
    p = tmp_path / "config.json"
    p.write_bytes(raw)
    with pytest.raises(ConfigLoadError):
        sc.load("chat2api", p)
    assert p.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [p]


@pytest.mark.parametrize("text", ["- not\n- a mapping\n", "null\n", "port: 8964\nport: 8970\n", "save_root: [unterminated\n"])
def test_bad_yaml(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    with pytest.raises(ConfigLoadError):
        sc.load("file-bridge", p)


def test_absence_example_and_race(tmp_path):
    p, example = tmp_path / "config.json", tmp_path / "config.example.json"
    example.write_text('{"models":{}}\n')
    d = sc.load("chat2api", p)
    assert not d.existed and d.raw_bytes == b"" and d.raw_sha256 is None and d.mode is None
    assert d.read_only_reasons == ("missing-config",) and not d.create_requested
    with pytest.raises(ReadOnlyConfigError):
        sc.render("chat2api", d)
    draft = sc.load_example("chat2api", p, example)
    assert draft.create_requested and not draft.read_only_reasons and not p.exists()
    assert sorted(x.name for x in tmp_path.iterdir()) == ["config.example.json"]
    p.write_text('{}\n')
    with pytest.raises(StaleDocumentError):
        sc.load_example("chat2api", p, example)
    assert p.read_bytes() == b'{}\n'


@pytest.mark.parametrize("dangling", [False, True])
def test_symlink_leaf_rejected_before_read(tmp_path, dangling, monkeypatch):
    referent = tmp_path / "real.json"
    if not dangling:
        referent.write_text('{}')
    link = tmp_path / "config.json"
    link.symlink_to(referent)
    calls = []
    original = type(link).lstat
    def spy(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(type(link), "lstat", spy)
    with pytest.raises(SymlinkConfigError):
        sc.load("chat2api", link)
    assert calls[0] == link and link.is_symlink()
    if not dangling:
        assert referent.read_bytes() == b'{}'


def test_readonly_anchors_and_punctuation(tmp_path):
    p = tmp_path / "config.yaml"
    text = 'save_root: &root "../storage"\nmax_text_bytes: &limit 1048576\nport: 8964\nextra_alias: *limit\n'
    p.write_text(text)
    d = sc.load("file-bridge", p)
    assert "yaml-anchors-aliases" in d.read_only_reasons
    with pytest.raises(ReadOnlyConfigError):
        sc.render("file-bridge", d)
    assert p.read_text() == text
    p.write_text('save_root: "../storage&star*"\nport: 8964\n')
    assert not sc.load("file-bridge", p).read_only_reasons
    p.chmod(0o444)
    try:
        d = sc.load("file-bridge", p)
        assert "non-writable" in d.read_only_reasons
        inode = p.lstat().st_ino
        with pytest.raises(ReadOnlyConfigError):
            sc.render("file-bridge", d)
        assert p.lstat().st_ino == inode and stat.S_IMODE(p.lstat().st_mode) == 0o444
    finally:
        p.chmod(0o600)


def test_empty_comments_and_normalized_noop(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("# comment only\n\n")
    assert sc.load("file-bridge", p).doc == {}
    p = tmp_path / "config.json"
    p.write_text('{"models":{}}\n')
    d = sc.load("chat2api", p)
    assert sc.render(d.kind, d) != d.raw_bytes
    assert sc.render(d.kind, d) == sc.render(d.kind, copy.deepcopy(d))
