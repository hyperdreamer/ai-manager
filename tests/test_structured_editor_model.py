import json
import copy

import pytest

from ai_manager.config.config_errors import ConfigValidationError
from ai_manager.config.structured_config import effective_mutations, load, render
from ai_manager.config.structured_models import Mutation
from ai_manager.ui.structured_editor_model import StructuredEditorModel


def model(workspace):
    return StructuredEditorModel(load("chat2api", workspace / "chat2api/config.json"))


def test_add_rename_remove_and_no_overlap(five_app_workspace):
    state = model(five_app_workspace)
    source = state.rows[0].id
    new = state.add_model("gemini.fast/v2", "echo")
    state.set_option(new, "prefix", present=True, value="hello")
    state.remove_model(source)
    mutations = effective_mutations(state.draft())
    assert {(m.address, m.operation) for m in mutations} == {
        (("models", "echo-1"), "delete"),
        (("models", "gemini.fast/v2"), "set"),
    }
    state.rename_model(new, "qwen&co/7b")
    tree = json.loads(render("chat2api", state.draft()))
    assert list(tree["models"]) == ["qwen&co/7b"]
    assert tree["models"]["qwen&co/7b"] == {
        "provider": "echo",
        "options": {"prefix": "hello"},
    }


def test_revert_absence_null_types_and_opaque_option_key(five_app_workspace):
    state = model(five_app_workspace)
    state.set_field(("server", "port"), present=True, value=8123)
    state.set_field(("server", "port"), present=True, value=8000)
    assert effective_mutations(state.draft()) == ()
    state.set_field(("server", "auth_token_env"), present=False)
    assert effective_mutations(state.draft())[0].operation == "delete"
    state.set_field(("server", "auth_token_env"), present=True, value=None)
    assert effective_mutations(state.draft()) == ()
    row = state.rows[0].id
    state.set_option(row, "opaque.key/path", present=True, value={"a": [1, False, None]})
    assert effective_mutations(state.draft())[0].address == (
        "models",
        "echo-1",
        "options",
        "opaque.key/path",
    )
    state.set_option(row, "opaque.key/path", present=False)
    assert effective_mutations(state.draft()) == ()


def test_duplicate_empty_rows_and_invalid_raw_are_retained(five_app_workspace):
    state = model(five_app_workspace)
    duplicate = state.add_model("echo-1", "echo")
    assert len(state.rows) == 2
    assert state.draft().input_issues[0].message == "Model names must be unique."
    with pytest.raises(ConfigValidationError):
        render("chat2api", state.draft())
    state.rename_model(duplicate, "")
    assert state.draft().input_issues[0].message == "Model names must be non-empty strings."
    state.rename_model(duplicate, "new-echo")
    state.set_raw_options(duplicate, "{broken")
    assert state.draft().raw_option_edits == {"new-echo": "{broken"}
    with pytest.raises(ConfigValidationError, match="invalid fields"):
        render("chat2api", state.draft())
    assert state.row(duplicate).raw_text == "{broken"


def test_provider_switch_reclassifies_without_mutating_options(five_app_workspace):
    state = model(five_app_workspace)
    row = state.rows[0].id
    state.set_option(row, "account", present=True, value="synthetic-account")
    state.set_option(row, "password", present=True, value="synthetic-password")
    state.set_raw_options(row, '{"future":{"keep":[1,"雪"]},"headless":false}')
    state.set_provider(row, "browser")
    after = json.loads(render("chat2api", state.draft()))["models"]["echo-1"]
    assert after["options"] == {
        "account": "synthetic-account",
        "password": "synthetic-password",
        "future": {"keep": [1, "雪"]},
        "headless": False,
    }
    assert state.raw_options(row) == {"future": {"keep": [1, "雪"]}}
    state.set_provider(row, "echo")
    assert "account" not in state.raw_options(row) and "password" not in state.raw_options(row)
    assert "headless" in state.raw_options(row)
    state.set_raw_options(row, '{"password":"raw collision"}')
    with pytest.raises(ConfigValidationError) as err:
        render("chat2api", state.draft())
    assert err.value.issues[0].message == (
        "Edit known or secret options in their fields, not in raw options."
    )


def test_rename_to_later_existing_row_retains_both(five_app_workspace):
    state = model(five_app_workspace)
    second = state.add_model("second", "echo")
    state.rename_model(state.rows[0].id, "second")
    assert len(state.rows) == 2
    assert state.draft().input_issues[0].message == "Model names must be unique."
    state.rename_model(second, "third")
    assert not state.draft().input_issues
    assert list(json.loads(render("chat2api", state.draft()))["models"]) == [
        "second",
        "third",
    ]


def test_row_ids_are_stable_and_never_reused(five_app_workspace):
    state = model(five_app_workspace)
    first = state.rows[0].id
    state.add_model("second", "echo")
    state.remove_model(first)
    third = state.add_model("third", "echo")
    assert third not in (first, first + 1)
    assert [row.name for row in state.rows] == ["second", "third"]
    assert state.row(third).id == third
    with pytest.raises(KeyError):
        state.row(first)


def test_untouched_route_keeps_absence_and_unknown_option_keys(five_app_workspace):
    path = five_app_workspace / "chat2api/config.json"
    tree = json.loads(path.read_bytes())
    tree["models"]["opaque"] = {
        "provider": "echo",
        "options": {"future/path": {"keep": [1, "雪"]}},
    }
    path.write_text(json.dumps(tree), encoding="utf-8")
    state = model(five_app_workspace)
    assert state.draft().mutations == ()
    state.set_field(("server", "port"), present=True, value=8123)
    assert state.draft().mutations == (Mutation(("server", "port"), "set", 8123),)
    rendered = json.loads(render("chat2api", state.draft()))
    assert rendered["models"]["echo-1"] == {"provider": "echo"}
    assert rendered["models"]["opaque"] == {
        "provider": "echo",
        "options": {"future/path": {"keep": [1, "雪"]}},
    }


def test_file_bridge_fields_emit_minimal_top_level_mutations(five_app_workspace):
    state = StructuredEditorModel(
        load("file-bridge", five_app_workspace / "file-bridge/config.yaml")
    )
    assert state.rows == []
    assert state.draft().mutations == ()
    state.set_field(("max_text_bytes",), present=True, value=1048576)
    state.set_field(("port",), present=True, value=8970)
    assert effective_mutations(state.draft()) == (Mutation(("port",), "set", 8970),)
    text = render("file-bridge", state.draft()).decode("utf-8")
    assert "# keep relative to config parent" in text
    assert "port: 8970" in text


def _with_options(workspace, options, provider="echo", name="echo-1"):
    path = workspace / "chat2api/config.json"
    tree = json.loads(path.read_bytes())
    tree["models"][name] = {"provider": provider, "options": options}
    path.write_text(json.dumps(tree), encoding="utf-8")
    return path


def test_provider_switch_folds_raw_edits_like_a_render(five_app_workspace):
    _with_options(five_app_workspace, {"keep": 1, "drop": 2})
    state = model(five_app_workspace)
    row = state.rows[0].id
    assert state.raw_options(row) == {"keep": 1, "drop": 2}
    state.set_raw_options(row, '{"keep": 1}')
    state.set_provider(row, "browser")
    assert state.row(row).raw_text is None
    rendered = json.loads(render("chat2api", state.draft()))["models"]["echo-1"]
    assert rendered["options"] == {"keep": 1}


def test_provider_switch_keeps_colliding_raw_text_instead_of_folding(five_app_workspace):
    state = model(five_app_workspace)
    row = state.rows[0].id
    state.set_raw_options(row, '{"password":"raw collision","future":1}')
    state.set_provider(row, "browser")
    assert state.row(row).raw_text == '{"password":"raw collision","future":1}'
    assert state.draft().raw_option_edits == {"echo-1": '{"password":"raw collision","future":1}'}
    with pytest.raises(ConfigValidationError) as err:
        render("chat2api", state.draft())
    assert err.value.issues[0].message == (
        "Edit known or secret options in their fields, not in raw options."
    )


def test_unchanged_secrets_come_from_the_loaded_document(five_app_workspace):
    _with_options(
        five_app_workspace,
        {"account": "synthetic-account", "password": "synthetic-password", "future": 1},
    )
    state = model(five_app_workspace)
    row = state.rows[0].id
    assert state.raw_options(row) == {"future": 1}
    state.set_field(("server", "port"), present=True, value=8123)
    mutations = effective_mutations(state.draft())
    assert mutations == (Mutation(("server", "port"), "set", 8123),)
    assert json.loads(render("chat2api", state.draft()))["models"]["echo-1"]["options"] == {
        "account": "synthetic-account",
        "password": "synthetic-password",
        "future": 1,
    }


def test_swapping_two_original_names_renders_both_routes(five_app_workspace):
    path = five_app_workspace / "chat2api/config.json"
    tree = json.loads(path.read_bytes())
    tree["models"] = {
        "a": {"provider": "echo", "options": {"prefix": "one"}},
        "b": {"provider": "echo", "options": {"prefix": "two"}},
    }
    path.write_text(json.dumps(tree), encoding="utf-8")
    state = model(five_app_workspace)
    first, second = state.rows[0].id, state.rows[1].id
    state.rename_model(first, "b")
    state.rename_model(second, "a")
    assert not state.draft().input_issues
    rendered = json.loads(render("chat2api", state.draft()))
    assert rendered["models"] == {
        "a": {"provider": "echo", "options": {"prefix": "two"}},
        "b": {"provider": "echo", "options": {"prefix": "one"}},
    }


def test_option_revert_drops_the_created_options_mapping(five_app_workspace):
    state = model(five_app_workspace)
    row = state.rows[0].id
    state.set_option(row, "headless", present=True, value=False)
    assert state.row(row).route == {"provider": "echo", "options": {"headless": False}}
    state.set_option(row, "headless", present=False)
    assert "options" not in state.row(row).route
    assert state.draft().mutations == ()
    rendered = json.loads(render("chat2api", state.draft()))
    assert rendered["models"]["echo-1"] == {"provider": "echo"}


def test_edits_never_mutate_the_loaded_baseline(five_app_workspace):
    state = model(five_app_workspace)
    before = copy.deepcopy(state.baseline.doc)
    state.set_field(("server", "port"), present=True, value=8123)
    state.set_option(state.rows[0].id, "prefix", present=True, value="hello")
    state.add_model("added", "echo")
    state.remove_model(state.rows[0].id)
    assert state.baseline.doc == before
    assert state.baseline.mutations == ()


def test_model_module_has_no_qt_or_filesystem_dependency():
    import ast
    from pathlib import Path

    import ai_manager.ui.structured_editor_model as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not any(name.startswith("PyQt") for name in imported)
    assert not imported.intersection({"os", "pathlib", "shutil", "tempfile", "io"})


def test_route_extra_keys_and_order_survive_field_edits(five_app_workspace):
    path = five_app_workspace / "chat2api/config.json"
    tree = json.loads(path.read_bytes())
    tree["models"] = {
        "first": {"provider": "echo", "route_extra": {"keep": [1, True, None]}},
        "second": {"provider": "gemini_webapi", "options": {"timeout": 30}},
    }
    path.write_text(json.dumps(tree), encoding="utf-8")
    state = model(five_app_workspace)
    state.set_field(("server", "port"), present=True, value=8123)
    rendered = json.loads(render("chat2api", state.draft()))
    assert list(rendered["models"]) == ["first", "second"]
    assert rendered["models"]["first"]["route_extra"] == {"keep": [1, True, None]}
    assert rendered["models"]["second"]["options"] == {"timeout": 30}


def test_add_then_remove_a_row_leaves_no_mutation(five_app_workspace):
    state = model(five_app_workspace)
    added = state.add_model("temporary", "echo")
    state.set_option(added, "prefix", present=True, value="x")
    state.remove_model(added)
    assert state.draft().mutations == ()
    assert state.draft().raw_option_edits == {}
    assert list(json.loads(render("chat2api", state.draft()))["models"]) == ["echo-1"]


def test_removed_row_discards_its_raw_text(five_app_workspace):
    state = model(five_app_workspace)
    row = state.rows[0].id
    state.set_raw_options(row, "{broken")
    state.remove_model(row)
    assert state.draft().raw_option_edits == {}
    assert state.draft().input_issues == ()


def test_file_bridge_removing_a_key_uses_delete(five_app_workspace):
    state = StructuredEditorModel(
        load("file-bridge", five_app_workspace / "file-bridge/config.yaml")
    )
    state.set_field(("max_text_bytes",), present=False)
    assert effective_mutations(state.draft()) == (
        Mutation(("max_text_bytes",), "delete"),
    )
    text = render("file-bridge", state.draft()).decode("utf-8")
    assert "# Local save destination" in text and "max_text_bytes" not in text
