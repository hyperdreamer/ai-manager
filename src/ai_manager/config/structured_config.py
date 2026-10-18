from __future__ import annotations
import copy
import hashlib
import io
import json
import os
import stat
from collections.abc import MutableMapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.tokens import AnchorToken, AliasToken
from ai_manager.config.config_errors import (
    ConfigLoadError, ConfigShapeError, ConfigValidationError, MissingExampleError,
    ReadOnlyConfigError, StaleDocumentError, SymlinkConfigError, UnknownConfigKindError,
)
from ai_manager.config.structured_models import FieldIssue, Mutation, StructuredDoc, StructuredKind
from ai_manager.config.structured_schema import PROVIDER_OPTIONS, SECRET_OPTION_KEYS
from ai_manager.config.yaml_manager import _get_yaml_engine


def _check_kind(kind: object) -> None:
    if kind not in ("chat2api", "file-bridge"):
        raise UnknownConfigKindError(kind)


def _parent_writable(parent: Path) -> bool:
    try:
        parent_mode = stat.S_IMODE(parent.stat().st_mode)
    except OSError:
        return False
    writable = bool(parent_mode & 0o222) and bool(parent_mode & 0o111)
    return writable and os.access(parent, os.W_OK | os.X_OK)


def _snapshot(path: Path) -> tuple[Path, bytes | None, int | None, tuple[str, ...]]:
    requested = Path(os.path.abspath(path))
    try:
        try:
            initial = requested.lstat()
        except FileNotFoundError:
            initial = None
        if initial is not None and stat.S_ISLNK(initial.st_mode):
            raise SymlinkConfigError(requested)
        resolved = requested.parent.resolve() / requested.name
        try:
            info = resolved.lstat()
        except FileNotFoundError:
            return resolved, None, None, () if _parent_writable(resolved.parent) else ("non-writable",)
        if stat.S_ISLNK(info.st_mode):
            raise SymlinkConfigError(requested)
        if not stat.S_ISREG(info.st_mode):
            raise ConfigLoadError(requested, "Configuration path must be a regular file.")
        raw = resolved.read_bytes()
        mode = stat.S_IMODE(info.st_mode)
        parent_mode = stat.S_IMODE(resolved.parent.stat().st_mode)
        writable = bool(mode & 0o222) and bool(parent_mode & 0o222) and bool(parent_mode & 0o111)
        writable = writable and os.access(resolved, os.W_OK) and os.access(resolved.parent, os.W_OK | os.X_OK)
        return resolved, raw, mode, () if writable else ("non-writable",)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigLoadError(requested, str(exc)) from exc


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate configuration key {key!r}; save is disabled.")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Non-JSON constant {value!r} is not supported.")


def _json_object(text: str) -> dict[str, Any]:
    value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON value must be an object.")
    return value


def _shape(kind: StructuredKind, path: Path, tree) -> None:
    if not isinstance(tree, MutableMapping):
        raise ConfigShapeError(path, "Configuration root must be a mapping; save is disabled.", "non-dict-root")
    if kind != "chat2api":
        return
    if "server" in tree and not isinstance(tree["server"], dict):
        raise ConfigShapeError(path, "Server must be a mapping when present; save is disabled.")
    if "models" not in tree:
        return
    if not isinstance(tree["models"], dict):
        raise ConfigShapeError(path, "Models must be a mapping; save is disabled.")
    for name, route in tree["models"].items():
        if not isinstance(route, dict):
            raise ConfigShapeError(path, f"Model {name!r} must be a mapping; save is disabled.")
        if "options" in route and not isinstance(route["options"], dict):
            raise ConfigShapeError(path, f"Options for model {name!r} must be a mapping when present; save is disabled.")


def _parse_bytes(kind: StructuredKind, path: Path, raw: bytes):
    _check_kind(kind)
    try:
        text = raw.decode("utf-8")
        reasons = ()
        if kind == "chat2api":
            tree = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        else:
            yaml = _get_yaml_engine()
            yaml.allow_duplicate_keys = False
            tokens = list(yaml.scan(text))
            if any(isinstance(t, (AnchorToken, AliasToken)) for t in tokens):
                reasons = ("yaml-anchors-aliases",)
            tree = yaml.load(text)
            if tree is None and all(not line.strip() or line.lstrip().startswith("#") for line in text.splitlines()):
                tree = CommentedMap()
        _shape(kind, path, tree)
        return tree, reasons
    except ConfigLoadError:
        raise
    except Exception as exc:
        raise ConfigLoadError(path, str(exc)) from exc


def load(kind: StructuredKind, path: Path) -> StructuredDoc:
    _check_kind(kind)
    requested = Path(os.path.abspath(path))
    resolved, raw, mode, reasons = _snapshot(requested)
    if raw is None:
        return StructuredDoc(kind, requested, resolved, {}, b"", None, False, None, ("missing-config",) + reasons)
    tree, parse_reasons = _parse_bytes(kind, requested, raw)
    return StructuredDoc(kind, requested, resolved, tree, raw, hashlib.sha256(raw).digest(), True, mode, reasons + parse_reasons)


def load_example(kind: StructuredKind, path: Path, example_path: Path) -> StructuredDoc:
    target = load(kind, path)
    if target.existed:
        raise StaleDocumentError(target.path, None, target.raw_sha256)
    try:
        example = load(kind, example_path)
        if not example.existed:
            raise FileNotFoundError(example_path)
    except Exception as exc:
        raise MissingExampleError(example_path, f"Cannot create draft from example: {example_path}") from exc
    reasons = tuple(r for r in target.read_only_reasons if r == "non-writable")
    reasons += tuple(r for r in example.read_only_reasons if r == "yaml-anchors-aliases")
    return replace(target, doc=copy.deepcopy(example.doc), read_only_reasons=reasons, create_requested=True)

def _apply(tree, mutation: Mutation) -> None:
    parent = tree
    for key in mutation.address[:-1]:
        if key not in parent:
            if mutation.operation == "delete":
                return
            parent[key] = CommentedMap() if isinstance(parent, CommentedMap) else {}
        if not isinstance(parent[key], MutableMapping):
            raise ConfigValidationError((FieldIssue(mutation.address, "An addressed parent must be a mapping."),))
        parent = parent[key]
    key = mutation.address[-1]
    if mutation.operation == "delete":
        parent.pop(key, None)
    else:
        parent[key] = copy.deepcopy(mutation.value)


def _ensure_nonoverlap(mutations: tuple[Mutation, ...]) -> None:
    for index, one in enumerate(mutations):
        for other in mutations[index + 1:]:
            n = min(len(one.address), len(other.address))
            if one.address[:n] == other.address[:n]:
                raise ConfigValidationError((FieldIssue(other.address, "Mutation addresses must not overlap."),))


def effective_mutations(doc: StructuredDoc) -> tuple[Mutation, ...]:
    _check_kind(doc.kind)
    if doc.input_issues:
        raise ConfigValidationError(doc.input_issues)
    mutations = list(copy.deepcopy(doc.mutations))
    _ensure_nonoverlap(tuple(mutations))
    tree = copy.deepcopy(doc.doc)
    for mutation in mutations:
        _apply(tree, mutation)
    for name, text in doc.raw_option_edits.items():
        address = ("models", name, "options")
        try:
            raw = _json_object(text)
        except (ValueError, TypeError) as exc:
            raise ConfigValidationError((FieldIssue(address, "Raw options must be a JSON object with unique keys."),)) from exc
        route = tree.get("models", {}).get(name)
        if not isinstance(route, dict):
            raise ConfigValidationError((FieldIssue(address, "Model must be a mapping."),))
        protected = {o.key for o in PROVIDER_OPTIONS.get(route.get("provider"), ())} | SECRET_OPTION_KEYS
        if protected.intersection(raw):
            raise ConfigValidationError((FieldIssue(address, "Edit known or secret options in their fields, not in raw options."),))
        options = route.get("options", {})
        previous_raw = {k: v for k, v in options.items() if k not in protected}
        edits = [Mutation(address + (k,), "delete") for k in previous_raw if k not in raw]
        edits += [Mutation(address + (k,), "set", v) for k, v in raw.items() if k not in previous_raw or previous_raw[k] != v or type(previous_raw[k]) is not type(v)]
        for edit in edits:
            ancestor = next((m for m in mutations if m.operation == "set" and edit.address[:len(m.address)] == m.address), None)
            if ancestor is not None:
                index = mutations.index(ancestor)
                box = {"value": copy.deepcopy(ancestor.value)}
                _apply(box, Mutation(("value",) + edit.address[len(ancestor.address):], edit.operation, edit.value))
                mutations[index] = Mutation(ancestor.address, "set", box["value"])
            else:
                mutations = [m for m in mutations if m.address != edit.address]
                mutations.append(edit)
    _ensure_nonoverlap(tuple(mutations))
    return tuple(mutations)


def _candidate(doc: StructuredDoc):
    tree = copy.deepcopy(doc.doc)
    for mutation in effective_mutations(doc):
        _apply(tree, mutation)
    _shape(doc.kind, doc.path, tree)
    return tree


def render(kind: StructuredKind, doc: StructuredDoc) -> bytes:
    _check_kind(kind)
    if kind != doc.kind:
        raise ConfigValidationError((FieldIssue((), "Configuration kind does not match its document."),))
    mutations = effective_mutations(doc)
    if doc.read_only_reasons:
        messages = {
            "missing-config": "Create a draft from the example before saving.",
            "non-writable": "Configuration is not writable; editing is disabled.",
            "yaml-anchors-aliases": "YAML anchors or aliases are present; editing is disabled to preserve linked values.",
        }
        reason = doc.read_only_reasons[0]
        raise ReadOnlyConfigError(doc.path, messages.get(reason, "Configuration is read-only."))
    if not doc.existed and not doc.create_requested:
        raise ReadOnlyConfigError(doc.path, "Create a draft from the example before saving.")
    tree = copy.deepcopy(doc.doc)
    for mutation in mutations:
        _apply(tree, mutation)
    _shape(kind, doc.path, tree)
    try:
        if kind == "chat2api":
            return (json.dumps(tree, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        stream = io.StringIO()
        _get_yaml_engine().dump(tree, stream)
        return stream.getvalue().encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError((FieldIssue((), "Configuration contains values that cannot be serialized."),)) from exc
