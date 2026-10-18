import copy
import hashlib
import json
import stat
from dataclasses import replace
import pytest
from ai_manager.config import structured_config as sc
from ai_manager.config.app_registry import get_managed_apps
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


@pytest.mark.parametrize("parent_mode", [0o555, 0o500])
def test_absent_target_unwritable_parent_is_not_creatable(tmp_path, parent_mode):
    parent = tmp_path / "locked"
    parent.mkdir()
    example = parent / "config.example.json"
    example.write_text('{"models":{}}\n')
    target = parent / "config.json"
    parent.chmod(parent_mode)
    try:
        d = sc.load("chat2api", target)
        assert not d.existed and d.raw_sha256 is None and d.mode is None
        assert "missing-config" in d.read_only_reasons
        assert "non-writable" in d.read_only_reasons
        draft = sc.load_example("chat2api", target, example)
        assert draft.create_requested and "non-writable" in draft.read_only_reasons
        with pytest.raises(ReadOnlyConfigError):
            sc.render("chat2api", draft)
        assert not target.exists()
        assert sorted(x.name for x in parent.iterdir()) == ["config.example.json"]
    finally:
        parent.chmod(0o755)


def test_absent_target_nonsearchable_parent_is_not_creatable(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir()
    example = parent / "config.example.json"
    example.write_text('{"models":{}}\n')
    target = parent / "config.json"
    parent.chmod(0o444)
    try:
        try:
            draft = sc.load_example("chat2api", target, example)
        except ConfigLoadError:
            # Without the search bit the absence of the target cannot even be
            # established, so no creatable draft may be produced.
            assert not target.exists()
            return
        assert "non-writable" in draft.read_only_reasons
        with pytest.raises(ReadOnlyConfigError):
            sc.render("chat2api", draft)
        assert not target.exists()
    finally:
        parent.chmod(0o755)


def test_absent_target_parent_mode_bits_beat_root_access(tmp_path, monkeypatch):
    parent = tmp_path / "locked"
    parent.mkdir()
    example = parent / "config.example.json"
    example.write_text('{"models":{}}\n')
    target = parent / "config.json"
    parent.chmod(0o555)
    # A root process (or any process whose uid clears DAC) still sees os.access as
    # true; the parent mode bits alone must keep explicit creation disabled.
    monkeypatch.setattr(sc.os, "access", lambda *args, **kwargs: True)
    try:
        d = sc.load("chat2api", target)
        assert "non-writable" in d.read_only_reasons
        draft = sc.load_example("chat2api", target, example)
        assert "non-writable" in draft.read_only_reasons
        with pytest.raises(ReadOnlyConfigError):
            sc.render("chat2api", draft)
        assert not target.exists()
    finally:
        parent.chmod(0o755)
    writable = sc.load("chat2api", target)
    assert writable.read_only_reasons == ("missing-config",)
    writable_draft = sc.load_example("chat2api", target, example)
    assert not writable_draft.read_only_reasons
    assert sc.render("chat2api", writable_draft) == b'{\n  "models": {}\n}\n'


def test_empty_comments_and_normalized_noop(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("# comment only\n\n")
    assert sc.load("file-bridge", p).doc == {}
    p = tmp_path / "config.json"
    p.write_text('{"models":{}}\n')
    d = sc.load("chat2api", p)
    assert sc.render(d.kind, d) != d.raw_bytes
    assert sc.render(d.kind, d) == sc.render(d.kind, copy.deepcopy(d))


# --- Task 9: commit coordinator -------------------------------------------


def test_order_sealed_bytes_and_returned_baseline(five_app_workspace, monkeypatch):
    path = five_app_workspace / "chat2api/config.json"
    draft = replace(sc.load("chat2api", path), mutations=(Mutation(("server", "port"), "set", 8123),))
    events, candidates = [], []
    original_render = sc.render
    def render_once(*args):
        events.append("render")
        return original_render(*args)
    monkeypatch.setattr(sc, "render", render_once)
    import ai_manager.config.structured_schema as schema
    import ai_manager.services.service_validation as service
    from ai_manager.config.structured_models import ValidationResult
    from ai_manager.config.transaction import Transaction
    scalar, validate = schema.validate_written_scalars, schema.validate_in_process
    monkeypatch.setattr(schema, "validate_written_scalars", lambda mutations: (events.append("stage1"), scalar(mutations))[-1])
    monkeypatch.setattr(schema, "validate_in_process", lambda *a, **k: (events.append("stage2"), validate(*a, **k))[-1])
    def validator(kind, target, app_dir, raw):
        events.append("stage3")
        candidates.append(raw)
        # A later mutable source change must never be rerendered into the commit.
        draft.doc["post-validation-source-change"] = True
        return ValidationResult("manager-only", "validated by ai-manager only — service validator unavailable")
    monkeypatch.setattr(service, "validate_candidate", validator)
    for method in ("prepare", "backups", "stage", "replace_all"):
        original = getattr(Transaction, method)
        def wrapped(self, *a, _original=original, _method=method, **k):
            events.append(_method)
            if _method == "stage":
                assert a[0][path.resolve()] == candidates[0]
            return _original(self, *a, **k)
        monkeypatch.setattr(Transaction, method, wrapped)
    result = sc.commit("chat2api", path, draft, draft.raw_sha256)
    assert events == ["render", "stage1", "stage2", "stage3", "prepare", "backups", "stage", "replace_all"]
    assert result.document.raw_bytes == candidates[0] == path.read_bytes()
    assert result.document.raw_sha256 == hashlib.sha256(candidates[0]).digest()
    assert result.document.doc["server"]["port"] == 8123
    assert "post-validation-source-change" not in result.document.doc
    assert result.document.mutations == () and not result.document.raw_option_edits and not result.document.input_issues
    assert result.transaction.committed and result.validation.scope == "manager-only"


@pytest.mark.parametrize("address,value,message", [(("server", "host"), "bad\nhost", "newline"), (("server", "port"), True, "integer")])
def test_manager_rejection_prevents_service_and_transaction(five_app_workspace, monkeypatch, address, value, message):
    import ai_manager.services.service_validation as service
    from ai_manager.config.transaction import Transaction
    path = five_app_workspace / "chat2api/config.json"
    doc = sc.load("chat2api", path)
    draft = replace(doc, mutations=(Mutation(address, "set", value),))
    monkeypatch.setattr(service, "validate_candidate", lambda *a: pytest.fail("stage 3 after manager refusal"))
    monkeypatch.setattr(Transaction, "prepare", lambda *a: pytest.fail("transaction after manager refusal"))
    with pytest.raises(ConfigValidationError) as err:
        sc.commit("chat2api", path, draft, doc.raw_sha256)
    assert message in err.value.issues[0].message
    assert path.read_bytes() == doc.raw_bytes and not list(path.parent.glob("*.bak"))


def test_digest_cannot_be_substituted_and_explicit_create_returns_sealed_mode(five_app_workspace, monkeypatch):
    import ai_manager.services.service_validation as service
    from ai_manager.config.structured_models import ValidationResult
    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    path = five_app_workspace / "chat2api/config.json"
    doc = sc.load("chat2api", path)
    with pytest.raises(ConfigValidationError):
        sc.commit("chat2api", path, doc, b"x" * 32)
    path.unlink()
    draft = sc.load_example("chat2api", path, path.with_name("config.example.json"))
    result = sc.commit("chat2api", path, draft, None)
    assert result.document.existed and result.document.mode == 0o600 and not result.document.create_requested
    assert path.stat().st_mode & 0o777 == 0o600
    assert not result.transaction.backups


def test_primary_stage_bytes_are_the_validated_bytes(five_app_workspace, monkeypatch):
    from ai_manager.config.structured_models import ValidationResult
    from ai_manager.config.transaction import Transaction
    import ai_manager.services.service_validation as service

    path = five_app_workspace / "chat2api/config.json"
    draft = replace(sc.load("chat2api", path), mutations=(Mutation(("server", "port"), "set", 8123),))
    validated, staged = [], []
    monkeypatch.setattr(service, "validate_candidate", lambda kind, target, app_dir, raw: (
        validated.append(raw), ValidationResult("manager-only", "fixture degraded")
    )[-1])
    original = Transaction.stage
    def stage(self, rendered):
        staged.append(dict(rendered))
        return original(self, rendered)
    monkeypatch.setattr(Transaction, "stage", stage)
    result = sc.commit("chat2api", path, draft, draft.raw_sha256)
    assert staged == [{path.resolve(): validated[0]}]
    assert path.read_bytes() == validated[0] == result.document.raw_bytes
    # The single-file save stages no dependent bytes and reports no dependent baseline.
    assert result.saved_dependents == {} and list(result.transaction.files) == [path.resolve()]


def test_dependent_render_never_uses_a_mutating_writer(five_app_workspace, monkeypatch):
    from ai_manager.config.blast_radius import find_affected_dependents
    from ai_manager.config.structured_models import ValidationResult
    from ai_manager.config.yaml_manager import render_app_config
    import ai_manager.config.yaml_manager as yaml_manager
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    monkeypatch.setattr(yaml_manager, "write_app_config", lambda *a, **k: pytest.fail("commit cannot render through a writer"))
    apps = get_managed_apps(five_app_workspace)
    path = apps["chat2api"].relative_path / "config.json"
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    matches = find_affected_dependents(apps, before, after)
    result = sc.commit("chat2api", path, after, before.raw_sha256, dependents=matches)
    for match in matches:
        expected = render_app_config(match.meta, match.doc, lambda tree, m=match: tree["ai"].__setitem__("api_base", m.new_api_base))
        assert match.path.read_bytes() == expected
        assert result.saved_dependents[match.meta.id].api_base == "http://127.0.0.1:8123"
        assert match.saved_config.api_base == "http://127.0.0.1:8000"


def test_duplicate_or_reused_dependent_paths_are_refused_before_any_write(five_app_workspace, monkeypatch):
    from ai_manager.config.blast_radius import find_affected_dependents
    from ai_manager.config.transaction import Transaction
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: pytest.fail("stage 3 after a snapshot refusal"))
    monkeypatch.setattr(Transaction, "prepare", lambda *a: pytest.fail("transaction after a snapshot refusal"))
    path = five_app_workspace / "chat2api/config.json"
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    apps = get_managed_apps(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    snapshots = {m.path: m.path.read_bytes() for m in matches}
    for dependents in ((matches[0], matches[0]), (replace(matches[0], path=path),)):
        with pytest.raises(ConfigValidationError):
            sc.commit("chat2api", path, after, before.raw_sha256, dependents=dependents)
        assert path.read_bytes() == before.raw_bytes
        assert all(p.read_bytes() == raw for p, raw in snapshots.items())


def test_stale_dependent_digest_is_refused_without_writing(five_app_workspace, monkeypatch):
    from ai_manager.config.blast_radius import find_affected_dependents
    from ai_manager.config.transaction import Transaction
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: pytest.fail("stage 3 after a digest refusal"))
    monkeypatch.setattr(Transaction, "prepare", lambda *a: pytest.fail("transaction after a digest refusal"))
    path = five_app_workspace / "chat2api/config.json"
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    apps = get_managed_apps(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    forged = tuple(replace(m, raw_bytes=m.raw_bytes + b"# replaced\n") for m in matches[:1])
    with pytest.raises(ConfigValidationError) as err:
        sc.commit("chat2api", path, after, before.raw_sha256, dependents=forged)
    assert "retain their captured digest" in err.value.issues[0].message
    assert path.read_bytes() == before.raw_bytes
    assert matches[0].path.read_bytes() == matches[0].raw_bytes


@pytest.mark.parametrize("failure", ["reject", "timeout"])
def test_service_rejection_and_timeout_refuse_the_save(five_app_workspace, monkeypatch, failure):
    from ai_manager.config.config_errors import ServiceValidationError, ServiceValidationTimeout
    from ai_manager.config.transaction import Transaction
    import ai_manager.services.service_validation as service

    path = five_app_workspace / "chat2api/config.json"
    draft = replace(sc.load("chat2api", path), mutations=(Mutation(("server", "port"), "set", 8123),))
    error = ServiceValidationError(1, "out", "fixture reject\n") if failure == "reject" else ServiceValidationTimeout("out", "fixture timeout\n")
    monkeypatch.setattr(service, "validate_candidate", lambda *a: (_ for _ in ()).throw(error))
    monkeypatch.setattr(Transaction, "prepare", lambda *a: pytest.fail("transaction after a refused stage 3"))
    with pytest.raises(type(error)) as err:
        sc.commit("chat2api", path, draft, draft.raw_sha256)
    assert err.value is error
    assert path.read_bytes() == draft.raw_bytes
    assert not list(path.parent.glob("*.bak"))


def test_only_unavailable_stage_three_degrades_scope(five_app_workspace, monkeypatch):
    from ai_manager.config.structured_models import ValidationResult
    import ai_manager.services.service_validation as service

    path = five_app_workspace / "chat2api/config.json"
    draft = replace(sc.load("chat2api", path), mutations=(Mutation(("server", "port"), "set", 8123),))
    notice = "validated by ai-manager only — service validator unavailable"
    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("manager-only", notice, "no interpreter"))
    result = sc.commit("chat2api", path, draft, draft.raw_sha256)
    assert result.validation.scope == "manager-only" and result.validation.notice == notice
    assert json.loads(path.read_bytes())["server"]["port"] == 8123


@pytest.mark.parametrize("kind", ["llm", "unknown", None, 3])
def test_commit_rejects_unknown_kinds(five_app_workspace, kind):
    from ai_manager.config.config_errors import UnknownConfigKindError

    path = five_app_workspace / "chat2api/config.json"
    doc = sc.load("chat2api", path)
    with pytest.raises(UnknownConfigKindError):
        sc.commit(kind, path, doc, doc.raw_sha256)
    assert path.read_bytes() == doc.raw_bytes


def test_read_only_document_is_refused_before_any_stage(five_app_workspace, monkeypatch):
    from ai_manager.config.config_errors import ReadOnlyConfigError
    import ai_manager.services.service_validation as service

    path = five_app_workspace / "chat2api/config.json"
    doc = sc.load("chat2api", path)
    draft = replace(doc, read_only_reasons=("non-writable",), mutations=(Mutation(("server", "port"), "set", 8123),))
    monkeypatch.setattr(service, "validate_candidate", lambda *a: pytest.fail("stage 3 after a read-only refusal"))
    with pytest.raises(ReadOnlyConfigError):
        sc.commit("chat2api", path, draft, draft.raw_sha256)
    assert path.read_bytes() == doc.raw_bytes


def test_non_writable_mode_bits_forbid_commit(five_app_workspace, monkeypatch):
    from ai_manager.config.config_errors import ReadOnlyConfigError
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: pytest.fail("stage 3 after a read-only refusal"))
    path = five_app_workspace / "chat2api/config.json"
    path.chmod(0o444)
    try:
        doc = sc.load("chat2api", path)
        assert doc.read_only_reasons == ("non-writable",)
        with pytest.raises(ReadOnlyConfigError):
            sc.commit("chat2api", path, doc, doc.raw_sha256)
    finally:
        path.chmod(0o600)
    assert path.read_bytes() == doc.raw_bytes


def test_existing_mode_survives_and_backups_cover_every_target(five_app_workspace, monkeypatch):
    from ai_manager.config.blast_radius import find_affected_dependents
    from ai_manager.config.structured_models import ValidationResult
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    apps = get_managed_apps(five_app_workspace)
    path = apps["chat2api"].relative_path / "config.json"
    path.chmod(0o640)
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    matches = find_affected_dependents(apps, before, after)
    result = sc.commit("chat2api", path, after, before.raw_sha256, dependents=matches)
    assert result.document.mode == 0o640 and stat.S_IMODE(path.stat().st_mode) == 0o640
    assert set(result.transaction.backups) == {path.resolve()} | {m.path for m in matches}
    originals = {path.resolve(): before.raw_bytes} | {m.path: m.raw_bytes for m in matches}
    for target, backup in result.transaction.backups.items():
        assert backup.read_bytes() == originals[target]
        assert backup.name.startswith(target.name + ".") and backup.suffix == ".bak"
        assert backup != target


def test_dependent_requires_llm_metadata(five_app_workspace, monkeypatch):
    from dataclasses import replace as replace_dc

    from ai_manager.config.blast_radius import find_affected_dependents
    from ai_manager.config.config_errors import ConfigError
    from ai_manager.config.transaction import Transaction
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: pytest.fail("stage 3 after a metadata refusal"))
    monkeypatch.setattr(Transaction, "prepare", lambda *a: pytest.fail("transaction after a metadata refusal"))
    apps = get_managed_apps(five_app_workspace)
    path = apps["chat2api"].relative_path / "config.json"
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    matches = find_affected_dependents(apps, before, after)
    not_llm = replace_dc(matches[0], meta=apps["chat2api"])
    with pytest.raises(ConfigError) as err:
        sc.commit("chat2api", path, after, before.raw_sha256, dependents=(not_llm,))
    assert "chat2api" in str(err.value)
    assert path.read_bytes() == before.raw_bytes
    assert matches[0].path.read_bytes() == matches[0].raw_bytes


def test_file_bridge_commit_preserves_comments_and_dispatches_by_kind(five_app_workspace, monkeypatch):
    from ai_manager.config.structured_models import ValidationResult
    import ai_manager.services.service_validation as service

    app = get_managed_apps(five_app_workspace)["file-bridge"]
    path = app.relative_path / "config.yaml"
    before = sc.load("file-bridge", path)
    draft = replace(before, mutations=(Mutation(("port",), "set", 8970),))
    seen = []
    def validator(kind, target, app_dir, raw):
        seen.append((kind, target, app_dir, raw))
        return ValidationResult("service", "fixture valid")
    monkeypatch.setattr(service, "validate_candidate", validator)
    result = sc.commit("file-bridge", path, draft, before.raw_sha256)
    assert seen == [("file-bridge", path.resolve(), path.parent.resolve(), result.document.raw_bytes)]
    assert result.document.kind == "file-bridge"
    assert b"port: 8970" in path.read_bytes()
    # Untouched comment lines and key order survive the addressed write.
    assert b"# Local save destination" in path.read_bytes()
    assert path.read_bytes().index(b"save_root") < path.read_bytes().index(b"max_text_bytes") < path.read_bytes().index(b"port")
    assert result.document.mutations == ()
