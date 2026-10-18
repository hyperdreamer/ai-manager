"""Pure row and mutation state for the structured configuration editor.

This module owns no Qt widgets and performs no filesystem I/O. It holds the
loaded baseline, the editable non-model tree, and one row per chat2api model so
duplicate and empty names stay representable instead of collapsing into a
dictionary. ``draft()`` derives the minimal addressed mutation set relative to
the loaded tree.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import Any

from ai_manager.config.structured_config import _apply, _json_object
from ai_manager.config.structured_models import FieldIssue, Mutation, StructuredDoc
from ai_manager.config.structured_schema import PROVIDER_OPTIONS, SECRET_OPTION_KEYS

_MISSING = object()

EMPTY_NAME_MESSAGE = "Model names must be non-empty strings."
DUPLICATE_NAME_MESSAGE = "Model names must be unique."


def _equal(left: Any, right: Any) -> bool:
    """Deep equality that keeps types distinct (``True`` is not ``1``)."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _equal(one, other) for one, other in zip(left, right)
        )
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return type(left) is type(right) and left == right


def _diff(before: Mapping[str, Any], after: Mapping[str, Any], prefix: tuple[str, ...]):
    """Addressed edits turning ``before`` into ``after``; never overlapping."""
    edits: list[Mutation] = []
    for key in before:
        if key not in after:
            edits.append(Mutation(prefix + (key,), "delete"))
    for key, value in after.items():
        if key not in before:
            edits.append(Mutation(prefix + (key,), "set", copy.deepcopy(value)))
            continue
        previous = before[key]
        if isinstance(previous, Mapping) and isinstance(value, Mapping):
            edits.extend(_diff(previous, value, prefix + (key,)))
        elif not _equal(previous, value):
            edits.append(Mutation(prefix + (key,), "set", copy.deepcopy(value)))
    return edits


def _option_edits(
    original: Mapping[str, Any], route: Mapping[str, Any], address: tuple[str, ...]
):
    """Route edits with options expanded so an absent ``options`` stays minimal."""
    edits = _diff(
        {key: value for key, value in original.items() if key != "options"},
        {key: value for key, value in route.items() if key != "options"},
        address,
    )
    before = original["options"] if "options" in original else _MISSING
    after = route["options"] if "options" in route else _MISSING
    options_address = address + ("options",)
    if before is _MISSING and after is _MISSING:
        return edits
    if before is _MISSING:
        # An absent options mapping is created by addressing only its children,
        # so no empty or partially defaulted mapping is written alongside them.
        for key, value in after.items():
            edits.append(Mutation(options_address + (key,), "set", copy.deepcopy(value)))
        return edits
    if after is _MISSING:
        edits.append(Mutation(options_address, "delete"))
        return edits
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        edits.extend(_diff(before, after, options_address))
    elif not _equal(before, after):
        edits.append(Mutation(options_address, "set", copy.deepcopy(after)))
    return edits


@dataclass
class ModelRow:
    id: int
    original_name: str | None
    name: str
    route: dict[str, Any]
    raw_text: str | None = None


class StructuredEditorModel:
    """Editable row/tree state for one loaded :class:`StructuredDoc`."""

    def __init__(self, config: StructuredDoc) -> None:
        self.baseline = copy.deepcopy(config)
        # Keep the round-trip tree type so untouched YAML values retain their
        # comments, quoting and relative order.
        self.tree: MutableMapping[str, Any] = copy.deepcopy(config.doc)
        for mutation in config.mutations:
            _apply(self.tree, mutation)
        self.rows: list[ModelRow] = []
        if config.kind == "chat2api":
            models = self.tree.get("models", {})
            if isinstance(models, Mapping):
                for index, (name, route) in enumerate(models.items()):
                    self.rows.append(
                        ModelRow(
                            id=index,
                            original_name=name,
                            name=name,
                            route=copy.deepcopy(route),
                            raw_text=config.raw_option_edits.get(name),
                        )
                    )
        self._next_id = len(self.rows)

    # -- rows -----------------------------------------------------------------

    def row(self, row_id: int) -> ModelRow:
        for row in self.rows:
            if row.id == row_id:
                return row
        raise KeyError(row_id)

    def add_model(self, name: str = "", provider: str = "") -> int:
        row = ModelRow(
            id=self._next_id,
            original_name=None,
            name=name,
            route={"provider": provider},
        )
        self._next_id += 1
        self.rows.append(row)
        return row.id

    def remove_model(self, row_id: int) -> None:
        self.row(row_id)
        self.rows = [row for row in self.rows if row.id != row_id]

    def rename_model(self, row_id: int, name: str) -> None:
        self.row(row_id).name = name

    # -- fields and options ---------------------------------------------------

    def set_field(self, address: tuple[str, ...], *, present: bool, value: Any = None) -> None:
        _apply(self.tree, Mutation(address, "set" if present else "delete", value))

    def set_option(
        self, row_id: int, key: str, *, present: bool, value: Any = None
    ) -> None:
        row = self.row(row_id)
        options = row.route.get("options")
        if not isinstance(options, dict):
            options = {}
            row.route["options"] = options
        if present:
            options[key] = copy.deepcopy(value)
            return
        options.pop(key, None)
        original = self._original_route(row)
        if not options and "options" not in original:
            # The entry had no options key, so an added-then-removed option
            # leaves the route shaped exactly as it was loaded.
            row.route.pop("options", None)

    def set_provider(self, row_id: int, provider: str) -> None:
        row = self.row(row_id)
        if row.raw_text is not None:
            raw = self._parse_raw(row.raw_text)
            # The retained text was authored against the current classification,
            # so fold it with that classification before the provider changes.
            protected = self._protected_keys(row)
            if raw is not None and not protected.intersection(raw):
                # Fold the edited raw area back into the route exactly as
                # ``effective_mutations`` would: the raw area is the complete
                # replacement of the non-protected options, while known and
                # secret option values are kept untouched. The raw area can then
                # be reclassified against the new provider without rewriting a
                # value. Text that would collide with a newly protected key is
                # retained so the collision stays a visible field error.
                options = row.route.get("options")
                folded = dict(options) if isinstance(options, Mapping) else {}
                for key in [key for key in folded if key not in protected]:
                    if key not in raw:
                        del folded[key]
                for key, value in raw.items():
                    folded[key] = copy.deepcopy(value)
                if folded or "options" in self._original_route(row):
                    row.route["options"] = folded
                else:
                    row.route.pop("options", None)
                row.raw_text = None
        row.route["provider"] = provider

    def set_raw_options(self, row_id: int, text: str) -> None:
        self.row(row_id).raw_text = text

    def raw_options(self, row_id: int) -> dict[str, Any]:
        row = self.row(row_id)
        protected = self._protected_keys(row)
        options = row.route.get("options")
        if not isinstance(options, Mapping):
            return {}
        return copy.deepcopy(
            {key: value for key, value in options.items() if key not in protected}
        )

    # -- draft ----------------------------------------------------------------

    def draft(self) -> StructuredDoc:
        if self.baseline.kind == "file-bridge":
            return replace(
                self.baseline,
                mutations=tuple(_diff(self.baseline.doc, self.tree, ())),
                raw_option_edits={},
                input_issues=(),
            )
        claimed, issues = self._claims()
        old_models = self.baseline.doc.get("models", {})
        if not isinstance(old_models, Mapping):
            old_models = {}
        mutations = _diff(
            {key: value for key, value in self.baseline.doc.items() if key != "models"},
            {key: value for key, value in self.tree.items() if key != "models"},
            (),
        )
        current_names = [row.name for row in self.rows]
        for name in old_models:
            # A removed or renamed-away model leaves no row presenting its name.
            if name not in current_names:
                mutations.append(Mutation(("models", name), "delete"))
        for row in self.rows:
            if row.name not in claimed:
                # Duplicate and empty names stay representable but unrenderable;
                # no parent/child mutation pair is emitted for them.
                continue
            address = ("models", row.name)
            if row.original_name == row.name:
                mutations.extend(
                    _option_edits(self._original_route(row), row.route, address)
                )
            else:
                mutations.append(Mutation(address, "set", copy.deepcopy(row.route)))
        raw_edits = {
            row.name: row.raw_text for row in self.rows if row.raw_text is not None
        }
        return replace(
            self.baseline,
            mutations=tuple(mutations),
            raw_option_edits=raw_edits,
            input_issues=tuple(issues),
        )

    # -- internals ------------------------------------------------------------

    def _claims(self) -> tuple[set[str], list[FieldIssue]]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.name] = counts.get(row.name, 0) + 1
        claimed: set[str] = set()
        issues: list[FieldIssue] = []
        for row in self.rows:
            address = ("models", row.name)
            if not row.name:
                issues.append(FieldIssue(address, EMPTY_NAME_MESSAGE))
            elif counts[row.name] > 1:
                issues.append(FieldIssue(address, DUPLICATE_NAME_MESSAGE))
            else:
                claimed.add(row.name)
        return claimed, issues

    def _original_route(self, row: ModelRow) -> Mapping[str, Any]:
        if row.original_name is None:
            return {}
        models = self.baseline.doc.get("models", {})
        if not isinstance(models, Mapping):
            return {}
        route = models.get(row.original_name, {})
        return route if isinstance(route, Mapping) else {}

    @staticmethod
    def _protected_keys(row: ModelRow) -> set[str]:
        specs = PROVIDER_OPTIONS.get(row.route.get("provider"), ())
        return {spec.key for spec in specs} | SECRET_OPTION_KEYS

    @staticmethod
    def _parse_raw(text: str) -> dict[str, Any] | None:
        try:
            return _json_object(text)
        except (TypeError, ValueError):
            return None
