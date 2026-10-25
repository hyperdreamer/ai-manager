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
from ruamel.yaml.error import YAMLError
from ruamel.yaml.tokens import AnchorToken, AliasToken
from ai_manager.config.config_errors import (
    ConfigError, ConfigLoadError, ConfigShapeError, ConfigValidationError, MissingExampleError,
    ReadOnlyConfigError, StaleDocumentError, SymlinkConfigError, UnknownConfigKindError,
    require_llm,
)
from ai_manager.config.structured_models import (
    DependentMatch, FieldIssue, Mutation, SaveResult, StructuredDoc, StructuredKind,
)
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
    # Depth is checked before ANY early return. A chat2api document without a
    # ``models`` key used to skip the guard entirely, so an example file with
    # deeply nested ``options`` passed shape validation and then raised
    # RecursionError inside ``load_example``'s deep copy - outside the exception
    # translation, in a Qt slot, which aborted the process.
    _check_depth(path, tree)
    if "models" not in tree:
        return
    if not isinstance(tree["models"], dict):
        raise ConfigShapeError(path, "Models must be a mapping; save is disabled.")
    for name, route in tree["models"].items():
        if not isinstance(route, dict):
            raise ConfigShapeError(path, f"Model {name!r} must be a mapping; save is disabled.")
        if "options" in route and not isinstance(route["options"], dict):
            raise ConfigShapeError(path, f"Options for model {name!r} must be a mapping when present; save is disabled.")
        # The service tolerates any provider value, but the editor uses it as a
        # combo-box key and a string. A non-string provider must therefore fail
        # at load with an explanation instead of raising inside the widget, which
        # would escape the load-error handler and abort MainWindow construction.
        if "provider" in route and not isinstance(route["provider"], str):
            raise ConfigShapeError(
                path,
                f"Provider for model {name!r} must be a string; save is disabled.",
            )


#: Maximum container nesting accepted from a configuration file.
#:
#: The editor deep-copies a parsed document several times (baseline capture, draft
#: derivation, transaction staging). A pathologically nested file - trivially
#: expressible in JSON - parses fine but raises ``RecursionError`` inside those
#: copies, which is not a ``ConfigLoadError`` and therefore escaped the load-error
#: handler and aborted ``MainWindow`` construction. Detect it at the boundary.
MAX_CONFIG_DEPTH = 32


def _check_depth(path: Path, tree: object) -> None:
    """Reject documents nested deeper than ``MAX_CONFIG_DEPTH``."""
    stack: list[tuple[object, int]] = [(tree, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_CONFIG_DEPTH:
            raise ConfigShapeError(
                path,
                f"Configuration is nested more than {MAX_CONFIG_DEPTH} levels deep; "
                "save is disabled.",
            )
        if isinstance(node, dict):
            for value in node.values():
                stack.append((value, depth + 1))
        elif isinstance(node, list):
            for value in node:
                stack.append((value, depth + 1))


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
    except (ConfigShapeError, SymlinkConfigError, ReadOnlyConfigError):
        # The example exists and was read, but its CONTENT is unusable. Reporting
        # "missing example" here would send the user looking for the wrong problem,
        # and swallowing it invites a later copy of an unvalidated tree.
        raise
    except Exception as exc:
        raise MissingExampleError(example_path, f"Cannot create draft from example: {example_path}") from exc
    reasons = tuple(r for r in target.read_only_reasons if r == "non-writable")
    reasons += tuple(r for r in example.read_only_reasons if r == "yaml-anchors-aliases")
    try:
        document = copy.deepcopy(example.doc)
    except RecursionError:
        raise ConfigShapeError(
            example_path, "Example configuration is nested too deeply to edit; save is disabled."
        ) from None
    return replace(target, doc=document, read_only_reasons=reasons, create_requested=True)

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


def _save_boundary(action):
    """Translate unowned local I/O/parse failures into a save ConfigError.

    Existing ``ConfigError`` subclasses pass through untouched so callers keep
    the specific stale/validation/transaction error. Nothing is retried and no
    supplied expected hash is ever replaced.
    """
    try:
        return action()
    except ConfigError:
        raise
    except (OSError, UnicodeError, YAMLError, ValueError, TypeError) as exc:
        raise ConfigError(f"Configuration save failed: {exc}") from exc


def commit(
    kind: StructuredKind,
    path: Path,
    doc: StructuredDoc,
    expected_sha256: bytes | None,
    *,
    dependents: tuple[DependentMatch, ...] = (),
) -> SaveResult:
    """Render, validate and atomically replace the primary and selected dependents.

    Rendering happens entirely in memory, every validation stage runs against
    the sealed candidate bytes, and the transaction stages exactly those bytes.
    """
    from ai_manager.config.structured_schema import (
        validate_in_process,
        validate_written_scalars,
    )
    from ai_manager.config.transaction import Transaction
    from ai_manager.config.yaml_manager import (
        _config_from_document,
        _get_yaml_engine,
        render_app_config,
    )
    from ai_manager.services.service_validation import validate_candidate

    _check_kind(kind)
    requested = Path(os.path.abspath(path))
    canonical = requested.parent.resolve() / requested.name
    if (
        kind != doc.kind
        or requested != doc.path
        or canonical != doc.resolved_path
        or expected_sha256 != doc.raw_sha256
    ):
        raise ConfigValidationError(
            (
                FieldIssue(
                    (),
                    "Save must use the loaded document's kind, path, and digest.",
                ),
            )
        )

    primary = _save_boundary(lambda: render(kind, doc))
    sealed = {canonical: primary}
    expected = {canonical: expected_sha256}
    dependent_baselines = {}
    scalar_mutations = list(effective_mutations(doc))
    for match in dependents:
        require_llm(match.meta)
        target = match.path.parent.resolve() / match.path.name
        if target in sealed or match.raw_sha256 != hashlib.sha256(match.raw_bytes).digest():
            raise ConfigValidationError(
                (
                    FieldIssue(
                        (),
                        "Dependent snapshots must be unique and retain their captured digest.",
                    ),
                )
            )

        def update(tree, value=match.new_api_base):
            tree["ai"]["api_base"] = value

        raw = _save_boundary(lambda: render_app_config(match.meta, match.doc, update))
        parsed = _save_boundary(lambda: _get_yaml_engine().load(raw.decode("utf-8")))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ai"), dict):
            raise ConfigValidationError(
                (FieldIssue(("ai",), "Dependent AI configuration must be a mapping."),)
            )
        sealed[target] = raw
        expected[target] = match.raw_sha256
        scalar_mutations.append(Mutation(("ai", "api_base"), "set", match.new_api_base))
        dependent_baselines[match.meta.id] = _config_from_document(parsed, match.meta)

    # Stages 1-2 always run; stage 3 then re-reads only these sealed bytes.
    validate_written_scalars(tuple(scalar_mutations))
    parsed_primary, _parse_reasons = _save_boundary(
        lambda: _parse_bytes(kind, canonical, primary)
    )
    validate_in_process(
        kind, parsed_primary, config_path=canonical, app_dir=canonical.parent
    )
    validation = validate_candidate(kind, canonical, canonical.parent, primary)

    with Transaction() as tx:
        tx.prepare(list(sealed), expected)
        tx.backups()
        tx.stage(sealed)
        report = tx.replace_all()

    baseline = StructuredDoc(
        kind=kind,
        path=requested,
        resolved_path=canonical,
        doc=parsed_primary,
        raw_bytes=primary,
        raw_sha256=hashlib.sha256(primary).digest(),
        existed=True,
        mode=doc.mode if doc.existed else 0o600,
    )
    return SaveResult(baseline, report, validation, dependent_baselines)
