# Endpoint Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, installed-build-aware upstream protocol selection for ai-grammar and textkit, with exact YAML preservation, coherent saved snapshots, recoverable failures, and protocol-aware discovery.

**Architecture:** A shared protocol vocabulary feeds canonical models, metadata-aware snapshots, a diff-only checked writer, and a nonce-authenticated capability service. The existing Qt coordinator owns saved/draft state and the only LLM commit path; the editor presents availability independently of the ordered save gate. Generation-checked workers, terminal restart completion, explicit reload, and per-field dependent rebasing preserve pending edits across asynchronous events.

**Tech Stack:** Python; Pydantic 2; ruamel.yaml round-trip YAML; PyQt6 widgets, QRunnable and QProcess; httpx; pytest, pytest-qt and respx.

## Global Constraints

- Authority: `docs/superpowers/specs/2026-10-20-endpoint-types-spec.md`, revision 7, and approved `2026-10-20-endpoint-types-design.md`; read the task-relevant sections. The spec is authoritative where earlier design shorthand differs. Review 7 is the clean acceptance pass; review 4 is incomplete.
- Keep the project dependency declarations exactly `PyQt6>=6.5.0`, `pydantic>=2.0.0`, `ruamel.yaml>=0.18.0`, `httpx>=0.25.0`; dev extras remain `pytest>=7.0.0`, `pytest-qt>=4.2.0`, `respx>=0.20.0`. No new runtime dependencies. `pyproject.toml` has no `requires-python`; do not invent a Python floor or dependency bump. The inspected executable is `/usr/bin/python` through Python 3.14; system metadata reports Pydantic 2.14.1 and PyQt6 6.11.0. ruamel.yaml's declared floor is 0.18.0; its installed version was not established. Use the existing integration test environment, not a newly invented `.venv` path.
- Participating apps are exactly `ai-grammar` and `textkit`; `supports_protocol_selection` defaults false. `yt2txt` has no protocol control: its endpoint is unmanaged, read as `(None, None)`, never set/popped by ordinary saves, and preserved through base-only dependent rewrites. `chat2api` and `file-bridge` retain their structured adapters and validation pipeline.
- Exact endpoint literals, in order: `/v1/chat/completions`, `/v1/responses`, `/v1/messages`. Reuse `EndpointValue`; no aliases, full URLs, trimming, case folding, extra versions, or independent unions. `None` means omit the YAML key; a present YAML null/blank is invalid raw evidence. OpenAI uses Bearer; Messages uses `x-api-key` and `anthropic-version: 2023-06-01`.
- No-write-on-no-op: canonical equality, after refusal guards, skips renderer, writer, transaction, backups and replacement for BOTH save buttons, including read-only files and unusual formatting. Save-and-Restart may restart without writing. Only `_on_save_requested` writes an LLM config, with its owned saved baseline and digest. Presets, combo handlers, draft signals, probes, reloads, restart helpers and error handlers never write.
- Keep checked saves synchronous. A cold capability lookup may wait for the child execution timeout `5.0`; source scan/spawn/cleanup are outside that bound. No asynchronous LLM save pipeline, real provider call, service start, port bind, general LLM candidate validator, or automatic base repair is introduced.
- Snapshots always contain an owned `AppAIConfig`, a 32-byte binary SHA-256, and exact bool base-key presence from the SAME bytes. Install configuration/digest/presence together. Advance presence with `old_present or draft.api_base != old_config.api_base`. Separate deep copies belong to saved and editable draft stores.
- `replace_all()` returning is the commit point. Pre-commit failures retain the old snapshot; an unknown transaction state blocks saving until reload. `CommittedWriteError` and display failure after writer return retain the installed candidate snapshot, require reload, and dispatch no restart. Cleanup during unwinding must preserve the primary `TransactionError` and report.
- Snapshot reads/reloads/reconciliation/checked saves are non-creating. Only the compatibility reader and initial coordinator load retain ensure-from-example behavior. Never convert a read/display/deep-copy error into an owned default draft. Do not open FIFOs or follow config-leaf symlinks.
- Preserve ruamel settings: `YAML(typ="rt")`, `preserve_quotes=True`, mapping indent 2, sequence indent 4, offset 2, width 4096. Ordinary saves change only differing managed leaves. Only an intentional split/unified toggle removes inactive sections. Base-only dependent rewrites do not use the full config mutator.
- Capability acceptance requires the specified loader guard/validator, exit 0 AND one final matching nonce sentinel with an exact complete accepted/rejected partition. Unknown always has empty acceptance. Child argv is `[str(interpreter), "-B", "-c", program, nonce]`, cwd is resolved launch directory, shell false, inherited environment plus `PYTHONDONTWRITEBYTECODE="1"`, UTF-8 replacement decoding, separate streams, timeout `5.0`, and direct child kill/reap on timeout. Imported target modules may have side effects; do not claim sandboxing.
- Cache identity is `(app_id, str(lexical_interpreter), interpreter.stat().st_mtime_ns, source_fingerprint(app_dir))`. Full fingerprints hash sorted relative paths and Python bytes with the specified NUL/LF framing. Exactly 200 files may cache; over 200 skips lookup AND insertion. Never hold the mutex while scanning, waiting or calling Qt. Capture generation at job creation; check generation and token before publication. Restart terminal completion, including FailedToStart and immediate busy refusal, invalidates once for the correct app.
- Availability enables Auto plus verified literals plus the saved valid literal exemption; unknown enables all four normal choices. Keep a newly rejected pending selection visible. Disabled labels have ONE trailing ` unavailable` suffix; item data remains the literal. Invalid display is not a fifth protocol. Capability results cannot clear recovery blocks or alter any draft field.
- All task paths are relative to the integration checkout. Modification ranges are ORIGINAL-source navigation ranges, not permission to overwrite intervening work. Locate the named existing method in the current tree before editing. Tasks execute in numeric order; repeated regions extend the current implementation and preserve preceding tasks' interfaces. New methods are inserted adjacent to the named anchor, never by replacing an entire shared class.
- New tests use isolated `tmp_path` apps, synthetic modules, mocked HTTP and controlled Qt workers. Preserve existing isolation/autostart guards. Every mechanism needs a behavioral failing assertion before its fix, or a narrow mutant in a disposable copy proving that assertion fails; a missing-module/import/keyword TypeError alone is insufficient red evidence. Record the actual failing assertion and green result in task evidence. Never weaken assertions to manufacture a red phase. These commands are IMPLEMENTATION instructions; drafting this plan runs no tests or app.
- Fixed copy: `Upstream protocol`; `Auto — omit the key`; `OpenAI Chat Completions — /v1/chat/completions`; `OpenAI Responses — /v1/responses`; `Anthropic Messages — /v1/messages`; ` unavailable`; `legacy Chat Completions - Authorization: Bearer`; `Sends Authorization: Bearer`; `Sends x-api-key + anthropic-version: 2023-06-01`; `Request URL: {url}`; `Invalid: {raw}`.
- Fixed invalid copy: `Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.`; `Unavailable — Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.`; `Request URL: unavailable — Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.`; detail `Stored ai.endpoint: {endpoint_raw}`.
- Fixed availability copy: `Installed build failed protocol compatibility checks. Update the service to enable protocol selection. Auto stays selectable so a saved protocol can be removed.`; `Protocol support could not be verified — validated by ai-manager only.`
- Fixed recovery copy: `Reload configuration`; `Reload the configuration before saving.`; `Configuration changed while you were editing. Reload the configuration before saving.`; `Conflicting fields: {comma_separated_ordered_names}.`; `Configuration changed on disk; save refused. Reload the configuration before saving.`; `Reload configuration and discard unsaved changes?`; `Configuration saved, but the file must be reloaded before another save.`
- Fixed gate copy: `Unsupported protocol value: {value!r}. Pick one of the three supported protocols or Auto.`; `The protocol path already includes /v1. Enter the gateway prefix, e.g. https://api.openai.com.` with detail `Request URL: {exact_url}`; `Protocol selection is not available for this application.`; `Installed build rejected protocol {literal}. Update the service or select Auto.`; `Cannot verify this build; introducing or changing ai.endpoint is refused. Select Auto to remove the key, or restore the saved protocol.`
- Fixed status copy: `Configuration saved.`; `Configuration saved. Restart requested.`; `Configuration saved, but service restart failed: {message}`; `service restart succeeded`. Details priority is recovery error, then gate/local/transaction error, then current non-supported probe detail. Ordinary success/restart notices allow probe-detail fallback. All labels use `Qt.TextFormat.PlainText`; details use `setPlainText`.
- Fixed probe reason prefixes: `Protocol capability check could not be prepared: {exception}`; `Could not run protocol capability check: {exception}`; `Protocol capability check timed out after 5 seconds.`; `Protocol capability check exited {returncode}.`; `Protocol capability check did not report a valid result.`; `Protocol capability check was superseded; retry after the restart or update.`; `Protocol capability check failed: {exception}`; unknown id `No protocol probe is defined for {app_id}.`. Append labelled `stdout:\n...` / `stderr:\n...` when present and redact the complete detail through existing `redact_diagnostics` before storing/displaying.
- Preserve discovery copy: `API Base URL cannot be empty.`, `Invalid JSON received from {url}: {error}`, `HTTP 404 Not Found at {url}`, `HTTP 401 Unauthorized: Invalid or missing API key at {url}`, `HTTP {status} ({reason}) from {url}`, `Connection refused connecting to {url}`, `Request timed out connecting to {url}`, `Network error connecting to {url}: {error}`, `Failed to fetch models from provider.`, `Fetching models from provider...`, `✓ Fetched {count} models from {endpoint}` and the existing warning prefix. Keep `/v1/models` then `/models`, `httpx.Timeout(10.0, connect=5.0)`, redirects, normalization, token and origin routing, and `User-Agent: ai-manager/0.1.0`.

### File responsibilities and dependency order

`config/protocols.py` owns vocabulary/composition/defaults (1); `models.py` owns canonical values/snapshots and registry flags (2); `yaml_manager.py` owns coherent reads (3) and diff-only commit (4); `protocol_capability.py` owns authenticated execution (5) and cache/generation (6). `AppDetailView` owns snapshot presentation (7), `config_jobs.py`/`supervisor.py` own queued probing and terminal restarts (8), and `MainWindow` owns ordered saves (9) and recovery (10). View three-way merge (11) precedes path-valued dependent reconciliation (12). Presets/discovery (13) and README/final acceptance (14) complete the feature. This is one feature with shared state, executed serially; no parallel shared-file edits.

### Spec coverage map

§2–3 / §11.2 → 1–2; §4.1–4.3 / §11.3 read/pure-render → 3; §4.4–4.5 / §7 / §11.3 write and cleanup → 4; §5.1–5.4 / §11.4 → 5; §5.5–5.6 service / §11.5 cache → 6; §8.2/8.5/8.6 / §11.6 → 7; §5.6 Qt/restart / §11.5 GUI → 8; §6 / §11.7 and commit ownership in §11.8 → 9; §8.1 / §11.8 reload/stale → 10; §8.3 / §11.9 field merge → 11; §2.6/8.4 / §11.9 transaction integration → 12; §9 / §11.10 → 13; §12.3 and §11.11 → 14. Exact copy in §10 and resolutions A01–A22 apply throughout.

## Task 1: Define the protocol vocabulary and exact URL helpers

**Implementer tier:** Standard

**Files:**

- Create: `src/ai_manager/config/protocols.py`
- Create: `tests/test_protocols.py`
- Test: `tests/test_protocols.py`

**Interfaces:**

- Consumes: Python standard-library `urlsplit(url: str) -> SplitResult`, which may raise `ValueError`; no project runtime dependency.
- Produces: `EndpointValue = Literal["/v1/chat/completions", "/v1/responses", "/v1/messages"]`, `LEGACY: Final[None]`, frozen `Protocol(value: EndpointValue, label: str, auth_hint: str)`, ordered `PROTOCOLS: tuple[Protocol, ...]`, `ENDPOINT_VALUES: frozenset[str]`.
- Produces: `is_valid_endpoint(value: object) -> bool`, `compose_request_url(app_id: str, api_base: str, endpoint: str | None) -> str`, `base_conflicts_with_endpoint(api_base: str, endpoint: str | None) -> bool`, `effective_api_base(app_id: str, draft: AppAIConfig, snapshot: ConfigSnapshot) -> str`. The latter types come from `config.models` under `TYPE_CHECKING` only; Task 2 adds the snapshot record. Pure helpers do no I/O or mutation.

- [ ] **Step 1: Add the behavioral matrix before implementing helpers.** Use these exact top-level names once each; parametrization expands them.

```python
from types import SimpleNamespace
import pytest
from ai_manager.config.protocols import (
    ENDPOINT_VALUES, PROTOCOLS, is_valid_endpoint, compose_request_url,
    base_conflicts_with_endpoint, effective_api_base,
)

VALUES = ("/v1/chat/completions", "/v1/responses", "/v1/messages")

def test_explicit_vocabulary_is_exact():
    assert tuple(p.value for p in PROTOCOLS) == VALUES
    assert ENDPOINT_VALUES == frozenset(VALUES)
    for value in VALUES:
        assert is_valid_endpoint(value)
    for value in (None, "", " /v1/messages", "/v1/messages ", "messages",
                  "/v1/completions", "/v1/other", "https://x/v1/messages",
                  True, 42, [], {}, set()):
        assert not is_valid_endpoint(value), repr(value)

@pytest.mark.parametrize("app,base,want", [
    ("ai-grammar", "https://x", "https://x/v1/chat/completions"),
    ("ai-grammar", "https://x/v1", "https://x/v1/chat/completions"),
    ("ai-grammar", "https://x/v1/", "https://x/v1//chat/completions"),
    ("textkit", "https://x", "https://x/v1/chat/completions"),
    ("textkit", "https://x/v1", "https://x/v1/v1/chat/completions"),
    ("textkit", "https://x/v1/", "https://x/v1/v1/chat/completions"),
])
def test_request_url_exact_legacy_matrix(app, base, want):
    assert compose_request_url(app, base, None) == want

@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
@pytest.mark.parametrize("endpoint", VALUES)
@pytest.mark.parametrize("base", ["https://x", "https://x/", "https://x/gateway/",
                                  "https://x/v1", "https://x/v1/"])
def test_explicit_request_url_preserves_gateway_prefix(app, endpoint, base):
    assert compose_request_url(app, " " + base + " ", endpoint) == base.rstrip("/") + endpoint

def test_base_conflict_is_path_only_and_total():
    for base in ("https://x/v1", "https://x/v1/", "https://x/gateway/v1///"):
        assert base_conflicts_with_endpoint(base, "/v1/messages")
        assert not base_conflicts_with_endpoint(base, None)
    for base in ("https://v1.example.com", "https://x?x=/v1", "https://x#/v1",
                 "https://x/v10", "https://x/V1", "https://[", "https://[::1"):
        assert not base_conflicts_with_endpoint(base, "/v1/messages")
    assert base_conflicts_with_endpoint("https://[::1]/v1", "/v1/messages")

@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
def test_omitted_base_uses_mode_specific_target_default(app):
    loaded = SimpleNamespace(api_base="http://127.0.0.1:3000")
    snap = SimpleNamespace(config=loaded, api_base_present=False)
    draft = SimpleNamespace(api_base=loaded.api_base, endpoint=None)
    want = "https://api.openai.com/v1" if app == "ai-grammar" else "https://api.openai.com"
    assert effective_api_base(app, draft, snap) == want
    draft.endpoint = "/v1/messages"
    assert effective_api_base(app, draft, snap) == "https://api.openai.com"
    draft.api_base = "https://pending/gateway"
    assert effective_api_base(app, draft, snap) == draft.api_base
    draft.api_base = loaded.api_base
    assert effective_api_base(app, draft, snap) == "https://api.openai.com"
    snap.api_base_present = True
    assert effective_api_base(app, draft, snap) == loaded.api_base
```

- [ ] **Step 2: Run red and capture an assertion, not just a missing import.** Run `python -B -m pytest -q tests/test_protocols.py`. A missing module establishes scaffolding only. Once the module is importable, in a disposable copy change the ai-grammar legacy branch to the textkit branch and run `python -B -m pytest -q tests/test_protocols.py -k request_url_exact_legacy_matrix`; expect the ai-grammar `/v1` and `/v1/` URL assertions to fail. Also prove predicate truthiness and removal of its `ValueError` catch are killed by their named tests. Restore the copy before green evidence.

- [ ] **Step 3: Implement the complete pure module.**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, TypeAlias
from urllib.parse import urlsplit
if TYPE_CHECKING:
    from ai_manager.config.models import AppAIConfig, ConfigSnapshot

EndpointValue: TypeAlias = Literal["/v1/chat/completions", "/v1/responses", "/v1/messages"]
LEGACY: Final[None] = None

@dataclass(frozen=True)
class Protocol:
    value: EndpointValue
    label: str
    auth_hint: str

PROTOCOLS: Final[tuple[Protocol, ...]] = (
    Protocol("/v1/chat/completions", "OpenAI Chat Completions", "Authorization: Bearer"),
    Protocol("/v1/responses", "OpenAI Responses", "Authorization: Bearer"),
    Protocol("/v1/messages", "Anthropic Messages", "x-api-key + anthropic-version: 2023-06-01"),
)
ENDPOINT_VALUES: Final[frozenset[str]] = frozenset(p.value for p in PROTOCOLS)

def is_valid_endpoint(value: object) -> bool:
    return isinstance(value, str) and value in ENDPOINT_VALUES

def compose_request_url(app_id: str, api_base: str, endpoint: str | None) -> str:
    raw = api_base.strip()
    if endpoint is not None:
        return raw.rstrip("/") + endpoint
    if app_id == "ai-grammar":
        base = raw if raw.rstrip("/").endswith("/v1") else raw.rstrip("/") + "/v1"
        return base + "/chat/completions"
    return raw.rstrip("/") + "/v1/chat/completions"

def base_conflicts_with_endpoint(api_base: str, endpoint: str | None) -> bool:
    if endpoint is None:
        return False
    try:
        path = urlsplit(api_base.strip()).path
    except ValueError:
        return False
    return path.rstrip("/").endswith("/v1")

def effective_api_base(app_id: str, draft: AppAIConfig, snapshot: ConfigSnapshot) -> str:
    if snapshot.api_base_present or draft.api_base != snapshot.config.api_base:
        return draft.api_base
    if app_id == "ai-grammar" and draft.endpoint is None:
        return "https://api.openai.com/v1"
    return "https://api.openai.com"
```

- [ ] **Step 4: Run green.** Run `python -B -m pytest -q tests/test_protocols.py`; expect exit 0, all matrix cases passing. Confirm no network/filesystem operations exist in the module.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/config/protocols.py tests/test_protocols.py
git commit -m "feat(protocols): define exact endpoint vocabulary and URL composition"
```

## Task 2: Add canonical endpoint models, snapshots and registry ownership

**Implementer tier:** Advanced

**Files:**

- Modify: `src/ai_manager/config/models.py:1-114` — imports, AppAIConfig, AppMetadata, ProviderPreset, ModelFetchRequest; retain status/settings definitions.
- Modify: `src/ai_manager/config/app_registry.py:6-76` — ai-grammar/textkit entries only.
- Modify: `tests/test_models.py:1-73`
- Modify: `tests/test_app_registry.py:1-79`
- Create: `tests/endpoint_helpers.py`
- Test: `tests/test_models.py`
- Test: `tests/test_app_registry.py`

**Interfaces:**

- Consumes: `EndpointValue = Literal["/v1/chat/completions", "/v1/responses", "/v1/messages"]` from `config.protocols`; Pydantic `field_validator`, `model_validator`, `BaseModel.model_validate(obj)`, `model_copy(deep=True)`.
- Produces: `AppAIConfig(api_base: str="http://127.0.0.1:3000", api_key: str="", model: str|None=None, is_split_model: bool=False, ocr_model: str|None=None, text_model: str|None=None, endpoint: EndpointValue|None=None, endpoint_raw: str|None=None)` with canonical equality; `get_display_model(self) -> str` stays compatible.
- Produces: `AppMetadata.supports_protocol_selection: bool=False`, `ProviderPreset.endpoint: EndpointValue|None=None`, `ModelFetchRequest.endpoint: str|None=None`; existing strict origin and kind validators stay intact.
- Produces: frozen `ConfigSnapshot(config: AppAIConfig, sha256: bytes, api_base_present: bool)` validating all three fields and deep-copying config.
- Produces test helpers: `meta_for(root: Path, app_id: str="ai-grammar", *, selectable: bool=True) -> AppMetadata` and `snapshot(config: AppAIConfig|None=None, *, present: bool=True, digest: bytes=b"s"*32) -> ConfigSnapshot`. These are explicitly isolated test factories, not production ownership shortcuts.

- [ ] **Step 1: Add construction, canonicalization and snapshot tests.** Retain existing strict kind/origin assertions and add:

```python
from dataclasses import FrozenInstanceError
import pytest
from pydantic import ValidationError
from ai_manager.config.models import AppAIConfig, ConfigSnapshot, ProviderPreset, ModelFetchRequest

@pytest.mark.parametrize("value", ["", " /v1/messages", "/v1/other", "https://x/v1/messages", 42, True])
@pytest.mark.parametrize("cls,fields", [
    (AppAIConfig, {}), (ProviderPreset, {"id": "x", "name": "X", "api_base": "https://x"}),
])
def test_endpoint_literal_rejects_non_vocabulary(cls, fields, value):
    with pytest.raises(ValidationError) as caught:
        cls(**fields, endpoint=value)
    assert any(e["loc"] == ("endpoint",) and e["type"] == "literal_error"
               for e in caught.value.errors())

def test_canonical_values_clear_only_inactive_models():
    unified = AppAIConfig(api_base=" https://x/ ", api_key=" $TOKEN ", model=" ",
                          ocr_model="hidden", text_model="hidden")
    assert (unified.api_base, unified.api_key) == ("https://x/", "$TOKEN")
    assert (unified.model, unified.ocr_model, unified.text_model) == (None, None, None)
    split = AppAIConfig(is_split_model=True, model="hidden", ocr_model=" ocr ", text_model=" ")
    assert (split.model, split.ocr_model, split.text_model) == (None, "ocr", None)
    assert split.get_display_model() == "OCR: ocr | Text: none"
    assert AppAIConfig(endpoint_raw="None").endpoint_raw == "None"
    assert AppAIConfig().endpoint is None
    req = ModelFetchRequest(token=1, app_id="a", api_base="x", api_key="", endpoint="transport-only")
    assert req.endpoint == "transport-only"
    with pytest.raises(ValidationError):
        AppAIConfig(api_base={})

def test_snapshot_is_validated_and_owns_configuration():
    config = AppAIConfig(model="old")
    saved = ConfigSnapshot(config, b"d" * 32, False)
    config.model = "new"
    assert saved.config.model == "old"
    with pytest.raises(FrozenInstanceError):
        saved.api_base_present = True
    for args, message in [
        (({}, b"d" * 32, False), "Snapshot config must be an AppAIConfig."),
        ((AppAIConfig(), "d" * 32, False), "Snapshot digest must be a 32-byte SHA-256 value."),
        ((AppAIConfig(), b"d", False), "Snapshot digest must be a 32-byte SHA-256 value."),
        ((AppAIConfig(), b"d" * 32, 1), "Snapshot base presence must be a boolean."),
    ]:
        with pytest.raises(ValueError, match="^" + __import__("re").escape(message) + "$"):
            ConfigSnapshot(*args)
```

In `test_app_registry.py` add `test_protocol_flags_are_structural_and_exact`: `assert {k for k,v in get_managed_apps(tmp_path).items() if v.supports_protocol_selection} == {"ai-grammar", "textkit"}` and assert textkit alone retains split support. Add an old `UserSettings(custom_presets=[{"id":"c","name":"C","api_base":"https://x"}])` assertion that endpoint defaults to None.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_models.py tests/test_app_registry.py`; expect literal/canonical/flag assertions to fail on existing behavior. A missing snapshot import alone is not evidence: after construction works, remove endpoint Literal typing in a disposable copy and require `test_endpoint_literal_rejects_non_vocabulary` to fail for a string; remove registry flags and require the exact-set assertion to fail.

- [ ] **Step 3: Add validators and record, preserving unrelated model fields.**

```python
@field_validator("api_base", "api_key", mode="before")
@classmethod
def strip_strings(cls, value: object) -> object:
    return value.strip() if isinstance(value, str) else value

@field_validator("model", "ocr_model", "text_model", mode="before")
@classmethod
def canonical_model(cls, value: object) -> object:
    return (value.strip() or None) if isinstance(value, str) else value

@model_validator(mode="after")
def active_models_only(self):
    if self.is_split_model:
        self.model = None
    else:
        self.ocr_model = self.text_model = None
    return self

@dataclass(frozen=True)
class ConfigSnapshot:
    config: AppAIConfig
    sha256: bytes
    api_base_present: bool

    def __post_init__(self) -> None:
        if not isinstance(self.config, AppAIConfig):
            raise ValueError("Snapshot config must be an AppAIConfig.")
        if type(self.sha256) is not bytes or len(self.sha256) != 32:
            raise ValueError("Snapshot digest must be a 32-byte SHA-256 value.")
        if type(self.api_base_present) is not bool:
            raise ValueError("Snapshot base presence must be a boolean.")
        object.__setattr__(self, "config", self.config.model_copy(deep=True))
```

Import `dataclass`, `model_validator` and shared `EndpointValue`. Add the four fields from Interfaces with their exact defaults. Set the two registry flags explicitly. Do not normalize endpoint strings. Create reusable factories:

```python
from pathlib import Path
from ai_manager.config.models import AppAIConfig, AppMetadata, ConfigSnapshot

def meta_for(root: Path, app_id: str = "ai-grammar", *, selectable: bool = True) -> AppMetadata:
    launch = root / app_id / "backend"
    launch.mkdir(parents=True, exist_ok=True)
    return AppMetadata(id=app_id, display_name=app_id, relative_path=launch,
                       default_port=8000, supports_split_models=(app_id == "textkit"),
                       supports_protocol_selection=selectable)

def snapshot(config: AppAIConfig | None = None, *, present: bool = True,
             digest: bytes = b"s" * 32) -> ConfigSnapshot:
    return ConfigSnapshot(config if config is not None else AppAIConfig(), digest, present)
```

- [ ] **Step 4: Run green.** Run `python -B -m pytest -q tests/test_protocols.py tests/test_models.py tests/test_app_registry.py`; expect exit 0, literal errors at `endpoint`, strict origin/kind checks retained, and no import cycle.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/config/models.py src/ai_manager/config/app_registry.py tests/test_models.py tests/test_app_registry.py tests/endpoint_helpers.py
git commit -m "feat(config): add canonical endpoint models and coherent snapshots"
```

## Task 3: Read coherent metadata-aware LLM snapshots without creating files

**Implementer tier:** Advanced

**Files:**

- Modify: `src/ai_manager/config/yaml_manager.py:1-101` — imports, `_config_from_document`, compatibility reader; insert snapshot/parser helpers before rendering.
- Modify: `src/ai_manager/config/blast_radius.py:74-123` — normalization call in `find_affected_dependents` only.
- Modify: `src/ai_manager/config/structured_config.py:381-399` — sealed dependent normalization call only.
- Modify: `tests/test_yaml_manager.py:1-196` — imports and new reader/pure-render tests, preserve writer tests for Task 4 migration.
- Test: `tests/test_yaml_manager.py`
- Test: `tests/test_blast_radius.py`

**Interfaces:**

- Consumes: `AppMetadata` with `id`, `config_kind`, `relative_path: Path`, `config_file_name`, `supports_split_models: bool`, `supports_protocol_selection: bool`; canonical `AppAIConfig` and `ConfigSnapshot(config, sha256: bytes, api_base_present: bool)` from `config.models`.
- Consumes: `is_valid_endpoint(value: object) -> bool`; existing `_snapshot(path: Path) -> tuple[Path, bytes|None, int|None, tuple[str,...]]` from `structured_config` (import locally to avoid its yaml-manager cycle), `require_llm(meta) -> None`, `ConfigLoadError(path: Path, detail: str, reason: str="load-error")`, `ConfigShapeError` and existing symlink errors.
- Consumes test factory: `meta_for(root: Path, app_id: str="ai-grammar", *, selectable: bool=True) -> AppMetadata`.
- Produces: `_parse_llm_document(path: Path, raw: bytes) -> MutableMapping[str, Any]`, `_config_from_document(doc: MutableMapping[str, Any], meta: AppMetadata) -> AppAIConfig`, `read_app_config_snapshot(app_meta: AppMetadata) -> ConfigSnapshot`; compatibility `read_app_config(app_meta: AppMetadata) -> AppAIConfig` still ensures an example first and returns a deep copy.
- Retains: `render_app_config(meta: AppMetadata, doc: MutableMapping[str, Any], mutate: Callable[[MutableMapping[str, Any]], None]) -> bytes`, a pure deep-copy renderer.

- [ ] **Step 1: Add the complete endpoint/read-failure matrix with the prescribed names.**

```python
from collections.abc import MutableMapping
from hashlib import sha256
from unittest.mock import Mock
from ai_manager.config.config_errors import ConfigLoadError
from ai_manager.config.yaml_manager import read_app_config_snapshot, _config_from_document
from tests.endpoint_helpers import meta_for

@pytest.mark.parametrize("app", ["ai-grammar", "textkit", "yt2txt"])
@pytest.mark.parametrize("line,value,raw", [
    ("", None, None), ("  endpoint: /v1/chat/completions\n", "/v1/chat/completions", None),
    ("  endpoint: /v1/responses\n", "/v1/responses", None),
    ("  endpoint: /v1/messages\n", "/v1/messages", None),
    ("  endpoint: null\n", None, "None"), ("  endpoint: ''\n", None, "''"),
    ("  endpoint: /v1/completions\n", None, "'/v1/completions'"),
    ("  endpoint: 42\n", None, "42"), ("  endpoint: true\n", None, "True"),
])
def test_endpoint_read_matrix_with_metadata(tmp_path, app, line, value, raw):
    meta = meta_for(tmp_path, app, selectable=app != "yt2txt")
    (meta.relative_path / "config.yaml").write_text("ai:\n  model: m\n" + line)
    config = read_app_config_snapshot(meta).config
    assert (config.endpoint, config.endpoint_raw) == ((value, raw) if app != "yt2txt" else (None, None))

@pytest.mark.parametrize("base_line,present", [(b"", False),
    (b"  api_base: http://127.0.0.1:3000\n", True), (b"  api_base: null\n", True)])
def test_snapshot_hashes_the_same_bytes_it_parses(tmp_path, monkeypatch, base_line, present):
    import ai_manager.config.structured_config as sc
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    raw = b"# spelling matters\nai:\n" + base_line + b"  model: exact\n"
    path.write_bytes(raw)
    actual = sc._snapshot
    calls = []
    def once(p):
        calls.append(p)
        result = actual(p)
        path.write_bytes(b"ai: {model: different}\n")
        return result
    monkeypatch.setattr(sc, "_snapshot", once)
    snap = read_app_config_snapshot(meta)
    assert snap.config.model == "exact" and snap.sha256 == sha256(raw).digest()
    assert snap.api_base_present is present and len(calls) == 1

@pytest.mark.parametrize("raw", [b"[\n", b"ai: {model: a, model: b}\n", b"[]\n",
    b"null\n", b"false\n", b"0\n", b"ai: []\n", b"ai: false\n", b"\xff"])
def test_load_failures_never_become_successful_default_snapshot(tmp_path, raw):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(raw)
    with pytest.raises(ConfigLoadError) as error:
        read_app_config_snapshot(meta)
    assert error.value.path == path
    assert path.read_bytes() == raw

def test_snapshot_read_is_noncreating_and_regular_file_only(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    (path.parent / "config.example.yaml").write_text("ai: {model: example}\n")
    with pytest.raises(ConfigLoadError, match="Configuration file is missing"):
        read_app_config_snapshot(meta)
    assert not path.exists()
    path.symlink_to(path.parent / "config.example.yaml")
    with pytest.raises(ConfigLoadError):
        read_app_config_snapshot(meta)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ConfigLoadError):
        read_app_config_snapshot(meta)
    path.unlink()
    for raw in (b"", b"# comments only\n", b"ai: null\n"):
        path.write_bytes(raw)
        path.chmod(0o444)
        assert read_app_config_snapshot(meta).sha256 == sha256(raw).digest()
        path.chmod(0o600)

def test_reader_split_classification_uses_metadata(tmp_path):
    tree = {"ai": {"model": "inactive", "ocr": {"api_key_env": "VISION_KEY"}}}
    grammar = _config_from_document(tree, meta_for(tmp_path))
    text = _config_from_document(tree, meta_for(tmp_path, "textkit"))
    assert not grammar.is_split_model and grammar.model == "inactive"
    assert text.is_split_model and text.model is None and text.ocr_model is None

def test_render_remains_pure(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    original = b"ai:\n  model: 'old' # keep\n"
    path.write_bytes(original)
    tree = _get_yaml_engine().load(original.decode())
    seen = []
    def mutate(candidate):
        seen.append(candidate)
        candidate["ai"]["model"] = "new"
    rendered = render_app_config(meta, tree, mutate)
    assert len(seen) == 1 and seen[0] is not tree
    assert tree["ai"]["model"] == "old" and path.read_bytes() == original
    assert b"'new' # keep" in rendered
```

Also assert direct helper shape errors use the exact spec messages and reasons: root `non-dict-root`, AI `load-error`. An empty mapping is valid; an explicit null root is not. Run the existing dependent-inspection tests after changing both metadata call sites.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_yaml_manager.py -k 'endpoint_read_matrix or snapshot or load_failures or reader_split or render_remains'`; expect endpoint/null/split/hash assertions to fail when the old reader is exercised. After import scaffolding, in an isolated copy replace presence with `config.api_base != AppAIConfig().api_base` and require explicit-placeholder presence to fail; remove metadata gating and require the grammar split assertion to fail.

- [ ] **Step 3: Implement shape-safe parsing, metadata normalization and same-byte snapshots.**

```python
def _parse_llm_document(path, raw):
    text = raw.decode("utf-8")
    engine = _get_yaml_engine()
    doc = engine.load(text)
    if doc is None and engine.compose(text) is None:
        doc = CommentedMap()
    if not isinstance(doc, MutableMapping):
        raise ConfigShapeError(path, "Configuration root must be a mapping; save is disabled.", "non-dict-root")
    ai = doc.get("ai")
    if ai is not None and not isinstance(ai, MutableMapping):
        raise ConfigShapeError(path, "AI must be a mapping when present; save is disabled.", "load-error")
    return doc

def _config_from_document(doc: MutableMapping[str, Any], meta: AppMetadata) -> AppAIConfig:
    require_llm(meta)
    if not isinstance(doc, MutableMapping):
        raise ValueError("Configuration root must be a mapping; save is disabled.")
    ai = doc.get("ai")
    if ai is None:
        ai = {}
    elif not isinstance(ai, MutableMapping):
        raise ValueError("AI must be a mapping when present; save is disabled.")
    endpoint = endpoint_raw = None
    if meta.supports_protocol_selection and "endpoint" in ai:
        value = ai["endpoint"]
        if is_valid_endpoint(value):
            endpoint = value
        else:
            endpoint_raw = repr(value)
    ocr, text = ai.get("ocr"), ai.get("text")
    split = meta.supports_split_models and any(isinstance(section, MutableMapping) for section in (ocr, text))
    def model_value(value: object) -> str | None:
        return str(value) if value else None
    return AppAIConfig(
        api_base=str(ai.get("api_base") or "http://127.0.0.1:3000"),
        api_key=str(ai.get("api_key") or ""),
        model=None if split else model_value(ai.get("model")),
        is_split_model=split,
        ocr_model=model_value(ocr.get("model")) if split and isinstance(ocr, MutableMapping) else None,
        text_model=model_value(text.get("model")) if split and isinstance(text, MutableMapping) else None,
        endpoint=endpoint,
        endpoint_raw=endpoint_raw,
    )


def read_app_config_snapshot(app_meta):
    from ai_manager.config.structured_config import _snapshot
    require_llm(app_meta)
    path = get_config_path(app_meta)
    try:
        path, raw, _mode, _reasons = _snapshot(path)
        if raw is None:
            raise ConfigLoadError(path, "Configuration file is missing.")
        tree = _parse_llm_document(path, raw)
        config = _config_from_document(tree, app_meta)
        ai = tree.get("ai")
        present = isinstance(ai, MutableMapping) and "api_base" in ai
        return ConfigSnapshot(config, hashlib.sha256(raw).digest(), present)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigLoadError(path, str(exc)) from exc


def read_app_config(app_meta):
    require_llm(app_meta)
    ensure_config_exists(app_meta)
    return read_app_config_snapshot(app_meta).config.model_copy(deep=True)
```

Use the exact declared signatures; the scalar construction above retains the existing base/key/falsey-model conventions and makes inactive fields None. Preserve duplicate-key rejection. In blast-radius inspection change to `_config_from_document(tree, meta)` and in dependent commit change to `_config_from_document(parsed, match.meta)`. Do not change the existing base-only mutator or dependent payload in this task.

- [ ] **Step 4: Run green.** Run `python -B -m pytest -q tests/test_yaml_manager.py tests/test_blast_radius.py`; expect exit 0. Missing snapshot reads leave the example uncopied, read-only regular files load, and no second byte read supplies the digest.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/config/yaml_manager.py src/ai_manager/config/blast_radius.py src/ai_manager/config/structured_config.py tests/test_yaml_manager.py
git commit -m "feat(config): load metadata-aware LLM snapshots from one byte read"
```

## Task 4: Implement diff-only writers and distinguish committed cleanup failure

**Implementer tier:** Capable

**Files:**

- Modify: `src/ai_manager/config/yaml_manager.py:104-187` — `_apply_ai_config`, both writer branches; retain Task 3 readers/parser and pure render signature.
- Modify: `src/ai_manager/config/config_errors.py:91-103` — add CommittedWriteError adjacent to TransactionError.
- Modify: `src/ai_manager/config/transaction.py:90-120` — `__exit__` primary-error preservation only.
- Modify: `tests/test_yaml_manager.py:68-196` — migrate every writer call to keyword baseline/digest and update intentional no-op expectations; append writer acceptance cases after current tests.
- Modify: `tests/test_app_registry.py:52-64` — non-LLM writer guard call supplies the now-required baseline while retaining its ConfigError assertion.
- Modify: `tests/test_transaction.py:1-518` — append primary-error/cleanup fault coverage without changing existing rollback tests.
- Test: `tests/test_yaml_manager.py`
- Test: `tests/test_transaction.py`

**Interfaces:**

- Consumes: canonical `AppAIConfig` with base/key, mode/active model leaves, `endpoint: EndpointValue|None`, `endpoint_raw: str|None`; `AppMetadata` ownership flags; `_parse_llm_document(path: Path, raw: bytes) -> MutableMapping[str, Any]`, `_config_from_document(doc, meta) -> AppAIConfig`, `_snapshot(path) -> (Path, bytes|None, int|None, tuple[str,...])`, pure `render_app_config(meta, doc, mutate) -> bytes`.
- Consumes: `Transaction` context manager; `prepare(paths: list[Path], expected: dict[Path, bytes|None]) -> None`, `backups() -> None`, `stage(rendered: dict[Path, bytes]) -> None`, `replace_all() -> TransactionReport`. `TransactionReport` fields include `phase: str`, `files: dict[Path, Literal["new","restored","unknown"]]`, `backups: dict[Path,Path]`, `committed: bool`, `error: str|None`, `restore_failures: dict[Path,str]`.
- Consumes: `StaleDocumentError(path: Path, expected_sha256: bytes|None, actual_sha256: bytes|None)`, `TransactionError(report: TransactionReport)`, test `meta_for(root: Path, app_id: str="ai-grammar", *, selectable: bool=True) -> AppMetadata`.
- Produces: `_apply_ai_config(meta: AppMetadata, doc: MutableMapping[str, Any], new_config: AppAIConfig, baseline: AppAIConfig) -> None`; `write_app_config(app_meta: AppMetadata, new_config: AppAIConfig, *, baseline: AppAIConfig, expected_sha256: bytes|None=None) -> bytes`.
- Produces: `CommittedWriteError(path: Path, installed_sha256: bytes, report: TransactionReport, cause: BaseException)` exposing `.path`, `.installed_sha256`, `.report`, `.cause`; its message is exactly `Configuration saved, but the file must be reloaded before another save.`. Use `.installed_sha256` consistently in the coordinator.

- [ ] **Step 1: Add exact-byte preservation and commit-boundary tests first.** Migrate old calls by reading the baseline BEFORE making a candidate and using `baseline=baseline`, `expected_sha256=digest`. In test_app_registry's structured-app guard use `write_app_config(meta, AppAIConfig(), baseline=AppAIConfig())` so argument binding reaches the kind guard and its existing ConfigError assertion. Existing tests that expect rendering/fixed backup on an unchanged config must edit a model first; separate no-op tests forbid those operations.

```python
from ai_manager.config.config_errors import CommittedWriteError, TransactionError
from ai_manager.config.transaction import Transaction
from ai_manager.config.structured_models import TransactionReport

PROVIDER_ONLY = (b'ai:\n  api_base: "https://gateway.example.test"\n'
    b'  api_key: "$EXAMPLE_API_KEY"\n  model: "non-default-base-model"\n'
    b'  messages_default_max_tokens: 6000\n  temperature: 0.2\n'
    b'  endpoints:\n    check: 0.1\n  ocr:\n    api_base: "https://vision.example.test"\n'
    b'    api_key_env: "VISION_KEY"\n  text:\n    api_key_env: "TEXT_KEY"\n')

def test_protocol_only_save_preserves_provider_only_mappings_and_base_model(tmp_path):
    meta = meta_for(tmp_path, "textkit")
    path = meta.relative_path / "config.yaml"
    path.write_bytes(PROVIDER_ONLY)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint": "/v1/messages"})
    installed = write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == PROVIDER_ONLY + b"  endpoint: /v1/messages\n"
    assert installed == hashlib.sha256(path.read_bytes()).digest()

@pytest.mark.parametrize("spelling", [b'"/v1/completions"', b"null", b"''", b"42", b"true"])
def test_invalid_to_auto_removes_exact_key_bytes(tmp_path, spelling):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b'ai:\n  api_base: "https://gateway.example.test"\n  endpoint: ' + spelling + b'\n  model: "model-a"\n'
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint_raw": None})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == b'ai:\n  api_base: "https://gateway.example.test"\n  model: "model-a"\n'

@pytest.mark.parametrize("checked", [True, False])
def test_noop_writer_has_no_backup_or_replace(tmp_path, monkeypatch, checked):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    raw = b"# odd formatting\nai: {model: 'm'}\n"
    path.write_bytes(raw)
    path.chmod(0o444)
    saved = read_app_config_snapshot(meta)
    forbidden = Mock(side_effect=AssertionError("no-op attempted a write"))
    monkeypatch.setattr(yaml_manager, "render_app_config", forbidden)
    monkeypatch.setattr(yaml_manager.os, "replace", forbidden)
    result = write_app_config(meta, saved.config, baseline=saved.config,
                              expected_sha256=saved.sha256 if checked else None)
    assert result == hashlib.sha256(raw).digest() and path.read_bytes() == raw
    assert not list(path.parent.glob("*.bak")) and not list(path.parent.glob("*.tmp*"))

def test_checked_writer_stale_refuses_before_render(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(b"ai: {model: old}\n")
    saved = read_app_config_snapshot(meta)
    external = b"ai: {model: old, endpoint: /v1/messages}\n"
    path.write_bytes(external)
    monkeypatch.setattr(yaml_manager, "render_app_config", Mock(side_effect=AssertionError("render before stale")))
    with pytest.raises(StaleDocumentError) as caught:
        write_app_config(meta, AppAIConfig(model="pending"), baseline=saved.config, expected_sha256=saved.sha256)
    assert caught.value.expected_sha256 == saved.sha256
    assert caught.value.actual_sha256 == hashlib.sha256(external).digest()
    assert path.read_bytes() == external and not list(path.parent.glob("*.bak"))

def test_cleanup_after_commit_reports_installed_digest(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(b"ai: {model: old}\n")
    saved = read_app_config_snapshot(meta)
    original_exit = Transaction.__exit__
    def failing_exit(self, kind, error, tb):
        result = original_exit(self, kind, error, tb)
        if error is None:
            raise OSError("post-commit unlock fixture")
        return result
    monkeypatch.setattr(Transaction, "__exit__", failing_exit)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "installed"})
    with pytest.raises(CommittedWriteError) as caught:
        write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert caught.value.installed_sha256 == hashlib.sha256(path.read_bytes()).digest()
    assert caught.value.report.committed and b"installed" in path.read_bytes()
    assert isinstance(caught.value.cause, OSError)
```

Add the remaining prescribed top-level tests with these concrete arrangements/assertions: `test_unmanaged_endpoint_survives_other_edits` uses yt2txt and exact `endpoint: "/hand-written/value" # unmanaged by this editor` bytes before/after a model change; `test_diff_does_not_materialize_omitted_fields` uses §7.4 bytes and expects only appended `endpoint: /v1/messages`; `test_only_mode_toggle_removes_inactive_sections` starts with PROVIDER_ONLY, exercises protocol/key/model-leaf edits preserving provider mappings, then explicit split→unified and unified→split and asserts only toggles remove their inactive sections; blank leaves pop keys, keep task mappings/provider keys, and never serialize `""`.

`test_checked_writer_returns_installed_bytes_digest_and_backup` writes a changed model at 0640 and asserts actual-byte digest, one timestamped backup containing original bytes/mode, final 0640, and no stage temp. `test_checked_writer_rechecks_under_transaction_lock` wraps `Transaction.prepare` to edit bytes immediately before calling the original; asserts StaleDocumentError and original expected hash forwarded. `test_legacy_writer_branch_still_uses_fixed_backup` supplies a real change and baseline, no expected hash, asserts old bytes at `config.yaml.bak`, actual-byte result hash and no timestamped backup. Add direct invalid-raw and forged-endpoint calls to prove defensive errors precede no-op return.

In `test_transaction.py`, append this independent fault test:

```python
def test_cleanup_preserves_primary_unknown_report(tmp_path, monkeypatch):
    path = files(tmp_path, 1)[0]
    report = tm.TransactionReport(phase="rollback", files={path: "unknown"}, error="primary")
    primary = TransactionError(report)
    actual_release = tm.Transaction._release
    def release(self):
        actual_release(self)
        raise OSError("cleanup fixture")
    monkeypatch.setattr(tm.Transaction, "_release", release)
    with pytest.raises(TransactionError) as caught:
        with tm.Transaction() as tx:
            tx.prepare([path], {path: digest(path)})
            raise primary
    assert caught.value is primary and caught.value.report is report
    assert isinstance(caught.value.__cause__, OSError)
    assert tx._state == "closed" and tx._locks == []
```

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_yaml_manager.py tests/test_transaction.py`; after signature migration, require exact-byte/preservation/fault assertions to fail on the former behavior. In disposable copies, remove ONLY `baseline.endpoint_raw` from the endpoint mutation condition and require the invalid-to-Auto bytes test to fail; replace the installed-byte hash with a model-JSON hash and require the digest assertion to fail. Record these mechanism-specific failures.

- [ ] **Step 3: Implement lazy diff mutation in application order.** Assert raw/invalid endpoint boundaries before equality or mutation. `require_llm` first. For nonparticipating metadata never pop/set an endpoint. Use a lazy mapping accessor and leaf helper; removals from an absent mapping do not create a section.

```python
def set_or_pop(mapping, key, value):
    if value is None:
        mapping.pop(key, None)
    else:
        mapping[key] = value

# Process in order: changed api_base, changed api_key, endpoint, active models.
# Insert ai only for a real assignment or an intentional model-mode toggle.
if meta.supports_protocol_selection and (
    new_config.endpoint != baseline.endpoint or baseline.endpoint_raw is not None
):
    if new_config.endpoint is None:
        if isinstance(doc.get("ai"), MutableMapping):
            doc["ai"].pop("endpoint", None)
    else:
        ai_mapping()["endpoint"] = new_config.endpoint
```

For unchanged unified mode mutate only differing `model`; unchanged split mode mutate only differing `ocr.model`/`text.model`, preserving the task mapping if its model is removed. For unified→split remove base model, ensure both task mappings (preserve provider keys), set/pop each leaf even if inactive baseline was None. For split→unified remove whole task sections and set/pop base model. Assert exact `ValueError("Invalid ai.endpoint must be explicitly repaired before saving.")` for participating raw drafts and `ValueError(f"Unsupported ai.endpoint value: {new_config.endpoint!r}.")` for a forged non-None endpoint. Retain quote/order behavior by assigning existing keys rather than deleting and reinserting them.

- [ ] **Step 4: Implement checked commit and compatibility return values.** Keep the initial expected comparison before parsing/rendering and the locked prepare comparison, and wrap only local unowned failures as `ConfigError(f"Configuration save failed: {exc}")`.

```python
installed = None
report = None
try:
    with Transaction() as tx:
        tx.prepare([path], {path: expected_sha256})
        tx.backups()
        tx.stage({path: rendered})
        report = tx.replace_all()
        installed = hashlib.sha256(rendered).digest()
except Exception as exc:
    if installed is not None:
        raise CommittedWriteError(path, installed, report, exc) from exc
    raise
return installed
```

Validate expected digest type/length. Snapshot once, compare before parsing; a missing file is stale with actual None. After assertions and stale comparison, equal canonical configs with no raw repair return the original bytes' hash without render or artifacts. The unchecked branch retains ensure, fixed copy2 backup, private same-directory temp, flush/fsync/mode/os.replace and cleanup, and returns `sha256(rendered).digest()`. Both branches call the same baseline-aware mutator.

In `Transaction.__exit__`, rename cleanup exception bindings so they do not overwrite/delete the `exc` parameter. Always finish releasing every descriptor and closing state. If cleanup fails while `exc is not None`, raise that SAME primary with original traceback from cleanup; if no primary exists, raise cleanup. Do not change rollback/report semantics. Add the specified CommittedWriteError fields/message without changing TransactionError.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_yaml_manager.py tests/test_transaction.py tests/test_blast_radius.py tests/test_app_registry.py`; expect exit 0, including existing transaction/fsync/mode/rollback cases. The GUI call-site migration occurs with snapshot ownership in Task 7 and the ordered gate in Task 9; do not weaken the new writer signature to accommodate old UI calls.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/config/yaml_manager.py src/ai_manager/config/config_errors.py src/ai_manager/config/transaction.py tests/test_yaml_manager.py tests/test_transaction.py tests/test_app_registry.py
git commit -m "feat(config): preserve diff-only writes and committed cleanup outcomes"
```

## Task 5: Execute authenticated installed-build protocol probes

**Implementer tier:** Capable

**Files:**

- Create: `src/ai_manager/services/protocol_capability.py`
- Create: `tests/test_protocol_capability.py`
- Test: `tests/test_protocol_capability.py`

**Interfaces:**

- Consumes: `ENDPOINT_VALUES: frozenset[str]` from `config.protocols`; `AppMetadata` fields `id: str`, `relative_path: Path`, `supports_protocol_selection: bool`; `redact_diagnostics(text: str) -> str` from `services.launcher_gate`.
- Produces: `ProtocolSupportStatus(str, Enum)` with SUPPORTED=`supported`, PARTIAL=`partial`, UNSUPPORTED=`unsupported`, UNVERIFIABLE=`unverifiable`; frozen `ProtocolSupport(status: ProtocolSupportStatus, accepted: frozenset[str]=frozenset(), detail: str="")` enforcing the §2.4 set/status invariants.
- Produces: `_unknown(reason: str, stdout: str="", stderr: str="") -> ProtocolSupport`, `_parse_partition(stdout: str, nonce: str) -> frozenset[str]` (raises ValueError for malformed grammar), `_run_uncached_probe(meta: AppMetadata, interpreter: Path, app_dir: Path) -> ProtocolSupport`, and immutable program strings `GRAMMAR_PROGRAM`, `TEXTKIT_PROGRAM`. Resolution/cache/public entrypoints are added in Task 6; this task tests the real execution core directly.

- [ ] **Step 1: Write child-fixture and parent-parser tests.** Include imports `json`, `os`, `sys`, `subprocess`, `Path`, `pytest`, `meta_for`, `ENDPOINT_VALUES` from `ai_manager.config.protocols`, and the capability module as `pc`. Add a helper that writes exactly one synthetic module and invokes the real child interpreter:

```python
def execute(tmp_path, app_id, source):
    meta = meta_for(tmp_path, app_id)
    name = "config.py" if app_id == "ai-grammar" else "main.py"
    (meta.relative_path / name).write_text(source)
    result = pc._run_uncached_probe(meta, Path(sys.executable), meta.relative_path.resolve())
    return meta, result

@pytest.mark.parametrize("rejected,status", [
    ((), pc.ProtocolSupportStatus.SUPPORTED),
    (("/v1/responses",), pc.ProtocolSupportStatus.PARTIAL),
    (tuple(ENDPOINT_VALUES), pc.ProtocolSupportStatus.UNSUPPORTED),
])
def test_grammar_uses_loader_guard(tmp_path, rejected, status):
    source = ("from dataclasses import dataclass\n@dataclass\nclass AIConfig:\n endpoint: str = ''\n"
              f"def _resolve_endpoint(ai):\n if ai['endpoint'] in {rejected!r}: raise RuntimeError('rejected')\n return ai['endpoint']\n")
    meta, result = execute(tmp_path, "ai-grammar", source)
    assert result.status is status
    assert result.accepted == ENDPOINT_VALUES - set(rejected)
    assert not list(meta.relative_path.rglob("__pycache__"))

@pytest.mark.parametrize("guard,model_reject,want", [
    (("/v1/chat/completions", "/v1/messages"), (), {"/v1/chat/completions", "/v1/messages"}),
    (tuple(ENDPOINT_VALUES), ("/v1/messages",), {"/v1/chat/completions", "/v1/responses"}),
])
def test_textkit_guard_and_validator_both_participate(tmp_path, guard, model_reject, want):
    source = (f"SUPPORTED_ENDPOINTS = {guard!r}\nclass AIConfig:\n @staticmethod\n"
              f" def model_validate(data):\n  assert data['api_key'] == 'probe'\n"
              f"  if data['endpoint'] in {model_reject!r}: raise ValueError('rejected')\n  return data\n")
    _, result = execute(tmp_path, "textkit", source)
    assert result.status is pc.ProtocolSupportStatus.PARTIAL
    assert result.accepted == frozenset(want)

@pytest.mark.parametrize("app,source", [
    ("ai-grammar", "from dataclasses import dataclass\n@dataclass\nclass AIConfig:\n endpoint: str = ''\n"),
    ("ai-grammar", "raise SystemExit(0)\n"),
    ("ai-grammar", "def _resolve_endpoint(x): raise TypeError('unexpected')\n"),
    ("textkit", "class AIConfig: pass\n"),
    ("textkit", "SUPPORTED_ENDPOINTS = 'bad'\nclass AIConfig:\n model_validate = None\n"),
    ("textkit", "SUPPORTED_ENDPOINTS = (42,)\nclass AIConfig:\n model_validate = None\n"),
    ("textkit", "SUPPORTED_ENDPOINTS = ()\nclass AIConfig:\n model_validate = None\n"),
])
def test_unusable_interface_is_unknown_not_verified_rejection(tmp_path, app, source):
    _, result = execute(tmp_path, app, source)
    assert result.status is pc.ProtocolSupportStatus.UNVERIFIABLE and not result.accepted


def test_import_side_effects_are_not_claimed_sandboxed(tmp_path):
    meta, result = execute(tmp_path, "ai-grammar",
        "from pathlib import Path\nPath('import-marker').write_text('ran')\n"
        "def _resolve_endpoint(x): return x['endpoint']\n")
    assert result.status is pc.ProtocolSupportStatus.SUPPORTED
    assert (meta.relative_path / "import-marker").read_text() == "ran"
```

Build parameterized parser tests by constructing `prefix="PROBE_RESULT:" + nonce + ":"` and `json.dumps({"accepted": list(ENDPOINT_VALUES), "rejected": []})`. Require one final matching line; allow unrelated import banners. Reject bare JSON, a wrong nonce, two matching lines, matching non-final line, whitespace prefix before sentinel, malformed JSON, duplicate JSON keys, extra keys, string instead of list, non-string entry, duplicates, overlap, unknown member and incomplete union. Test the valid zero-accepted/full-rejected partition separately as UNSUPPORTED. Mock process exit 75 and exit 1 with a valid sentinel and require empty-accepted UNVERIFIABLE.

Add `test_probe_spawn_contract_and_redaction`: capture Popen argv/kwargs, assert five argv entries including `-B` and a 32-character lowercase hex nonce, cwd resolved, shell False, inherited environment marker and `PYTHONDONTWRITEBYTECODE="1"`, separate PIPE streams and UTF-8 replacement. Use stderr `api_key=not-a-real-secret\nvalidation input_value='fixture'`; assert secrets/tail are scrubbed in `.detail`. Add `test_probe_timeout_kills_and_reaps_direct_child`: run an isolated module that sleeps past 5 seconds, wrap the actual Popen to record its PID and wait result, assert timeout detail and `poll() is not None`; never leave the child alive. Spawn failure gets the exact run-failure prefix. No existing config is needed or read.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_protocol_capability.py`; missing exports are scaffolding only. In disposable copies falsify the ai-grammar resolver by using the declared dataclass field, drop ONLY textkit membership checking, and accept exit 0 without sentinel. The corresponding status/set assertions must fail. Drop `-B` and the environment flag separately and require argv/environment assertions to fail.

- [ ] **Step 3: Add invariant-checked records and copy both normative programs literally.**

```python
GRAMMAR_PROGRAM = r'''
import json
import sys
nonce = sys.argv[1]
values = ("/v1/chat/completions", "/v1/responses", "/v1/messages")
try:
    import config
    resolve = config._resolve_endpoint
    if not callable(resolve):
        raise AttributeError("config._resolve_endpoint is not callable")
except (ImportError, AttributeError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
accepted, rejected = [], []
for value in values:
    try:
        resolve({"endpoint": value})
    except RuntimeError:
        rejected.append(value)
    else:
        accepted.append(value)
print("PROBE_RESULT:" + nonce + ":" + json.dumps({"accepted": accepted, "rejected": rejected}))
raise SystemExit(0)
'''

TEXTKIT_PROGRAM = r'''
import json
import sys
nonce = sys.argv[1]
values = ("/v1/chat/completions", "/v1/responses", "/v1/messages")
try:
    import main
    supported = main.SUPPORTED_ENDPOINTS
    model = main.AIConfig
    validate = model.model_validate
    if not isinstance(supported, (tuple, list, set, frozenset)):
        raise AttributeError("main.SUPPORTED_ENDPOINTS is not a collection of strings")
    if not all(isinstance(value, str) for value in supported) or not callable(validate):
        raise AttributeError("textkit endpoint validation interface is unavailable")
except (ImportError, AttributeError) as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
base = {"api_base": "https://api.openai.com", "api_key": "probe", "model": "probe"}
accepted, rejected = [], []
for value in values:
    try:
        if value not in supported:
            raise ValueError("not in SUPPORTED_ENDPOINTS")
        validate({**base, "endpoint": value})
    except Exception:
        rejected.append(value)
    else:
        accepted.append(value)
print("PROBE_RESULT:" + nonce + ":" + json.dumps({"accepted": accepted, "rejected": rejected}))
raise SystemExit(0)
'''
```

Validate record acceptance against the shared set; supported must have 3, partial 1–2, and either unsupported/unknown must be empty. Scrub detail before storing it (including successful stderr). `_parse_partition` uses a duplicate-key-rejecting `object_pairs_hook` with `json.loads`, exact object keys/list types/string membership, no duplicate entries, disjointness and complete union; `json.loads` rejects trailing non-whitespace. Find matching prefix lines without stripping leading whitespace, require exactly one and last nonempty stdout position. Return only accepted frozenset.

- [ ] **Step 4: Add direct-child execution with reason-specific failure mapping.**

```python
def _run_uncached_probe(meta, interpreter, app_dir):
    program = {"ai-grammar": GRAMMAR_PROGRAM, "textkit": TEXTKIT_PROGRAM}.get(meta.id)
    if program is None:
        return _unknown(f"No protocol probe is defined for {meta.id}.")
    nonce = secrets.token_hex(16)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        child = subprocess.Popen([str(interpreter), "-B", "-c", program, nonce],
            cwd=app_dir, shell=False, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except Exception as exc:
        return _unknown(f"Could not run protocol capability check: {exc}")
    try:
        stdout, stderr = child.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        child.kill()
        stdout, stderr = child.communicate()
        return _unknown("Protocol capability check timed out after 5 seconds.", stdout, stderr)
    except Exception as exc:
        child.kill()
        stdout, stderr = child.communicate()
        return _unknown(f"Could not run protocol capability check: {exc}", stdout, stderr)
    if child.returncode != 0:
        return _unknown(f"Protocol capability check exited {child.returncode}.", stdout, stderr)
    try:
        accepted = _parse_partition(stdout, nonce)
    except (ValueError, TypeError):
        return _unknown("Protocol capability check did not report a valid result.", stdout, stderr)
    status = (ProtocolSupportStatus.SUPPORTED if accepted == ENDPOINT_VALUES else
              ProtocolSupportStatus.PARTIAL if accepted else ProtocolSupportStatus.UNSUPPORTED)
    return ProtocolSupport(status, accepted, redact_diagnostics(stderr.strip()))
```

`_unknown` joins reason then nonempty labelled stdout/stderr sections and redacts the COMPLETE string once before record storage. Handle cleanup errors with a best-effort reap and a redacted unknown result; never leak an operational failure or stale acceptance to callers. Do not add candidate validation, full-config loaders, environment-key resolution, service launch, or structured import verification.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_protocol_capability.py`; expect all child/parser/timeout cases to pass and no target bytecode directories. A marker written by imports is expected evidence of the documented side-effect limit.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/services/protocol_capability.py tests/test_protocol_capability.py
git commit -m "feat(capability): authenticate installed protocol acceptance probes"
```

## Task 6: Cache capabilities by content and guard every generation

**Implementer tier:** Capable

**Files:**

- Modify: `src/ai_manager/services/protocol_capability.py:1-400` — the module created by Task 5; add fingerprint/cache/public wrapper around its execution core, preserving child strings/parser.
- Modify: `tests/test_protocol_capability.py:1-400` — append scan/cache/concurrency acceptance cases; retain real child tests.
- Test: `tests/test_protocol_capability.py`

**Interfaces:**

- Consumes: `resolve_app_interpreter(app_dir: Path) -> Path` from `services.app_interpreter`, preserving lexical absolute executable path; no `verify_app_interpreter` call.
- Consumes: `ProtocolSupport(status: ProtocolSupportStatus, accepted: frozenset[str], detail: str)`, `_run_uncached_probe(meta: AppMetadata, interpreter: Path, app_dir: Path) -> ProtocolSupport`, `_unknown(reason: str, stdout: str="", stderr: str="") -> ProtocolSupport`; AppMetadata's selection flag/id/path; shared `ENDPOINT_VALUES`.
- Produces: `source_fingerprint(app_dir: Path) -> tuple[Literal["full"], bytes] | tuple[Literal["coarse"], int, int, int]`, `probe_protocol_support(meta: AppMetadata, *, use_cache: bool=True) -> ProtocolSupport`, `_probe_protocol_support_at_generation(meta: AppMetadata, *, generation: int, use_cache: bool=True) -> ProtocolSupport`, `invalidate_protocol_support(app_id: str) -> None`, `protocol_support_generation(app_id: str) -> int`.
- Internal cache key: `tuple[str, str, int, Fingerprint]`, where `Fingerprint` is the tagged union above. Entries and generations share one short `threading.Lock`; do not expose dictionaries as integration seams.

- [ ] **Step 1: Extend tests with deterministic source/key and race fixtures.** Use local patches of `_run_uncached_probe` for cache counts; keep real execution tests from Task 5. In each cache test use a fresh app id or call invalidation to isolate process-local state. Resolver patch returns a lexical path under the fixture; touch interpreter mtime without editing its executable bytes.

```python
def test_content_key_misses_equal_size_same_mtime_replacement(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    source = meta.relative_path / "config.py"
    source.write_bytes(b"first\n")
    old = source.stat()
    monkeypatch.setattr(pc, "resolve_app_interpreter", lambda path: Path(sys.executable))
    run = Mock(return_value=pc.ProtocolSupport(pc.ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES))
    monkeypatch.setattr(pc, "_run_uncached_probe", run)
    pc.invalidate_protocol_support(meta.id)
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

@pytest.mark.parametrize("count,want_runs", [(200, 1), (201, 2)])
def test_exact_threshold_and_overflow_never_cache(tmp_path, monkeypatch, count, want_runs):
    meta = meta_for(tmp_path)
    for n in range(count):
        (meta.relative_path / f"m{n:03}.py").write_text("pass\n")
    monkeypatch.setattr(pc, "resolve_app_interpreter", lambda path: Path(sys.executable))
    run = Mock(return_value=pc.ProtocolSupport(pc.ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES))
    monkeypatch.setattr(pc, "_run_uncached_probe", run)
    pc.invalidate_protocol_support(meta.id)
    pc.probe_protocol_support(meta)
    pc.probe_protocol_support(meta)
    assert run.call_count == want_runs
```

Add a transition from a cached one-file supported tree to 201 files and assert two further executions, not a retained hit. Add `use_cache=False` with a different return result: two bypass calls execute twice and cannot overwrite the pre-existing cached full-key answer. Complete-key unknown results may cache; resolver/stat/read/iteration failures before key completion may not.

Test exclusions with `__pycache__`, `.venv`, `venv`, a differently named directory containing a regular `pyvenv.cfg`, and a directory symlink. Test included Python leaf symlink target bytes; reject required stat/read errors. Test the exact sorted stream by computing its expected hash independently from known relative POSIX names and contents; non-Python `.env`, YAML, credentials and configs must never be read for fingerprinting.

Use `threading.Event` and `ThreadPoolExecutor`, with event waits bounded to 2 seconds and `finally` releasing all blocked threads, for `test_old_generation_cannot_publish_over_new_result`: block the first run, invalidate, complete a fresh run returning partial, then release old supported; assert old result is empty unknown and next call returns fresh partial. Mutate source during a blocked run to require superseded unknown without insertion. Capture a generation, invalidate, call `_probe_protocol_support_at_generation` and assert no resolver/spawn; it is already obsolete. Invalidate while returning a cache hit using a controlled fingerprint callback and require the hit to be rejected. Assert no deadlock by letting invalidation finish while the probe is blocked.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_protocol_capability.py`; after public scaffolding require the content/count/generation assertions to fail for no cache or unsafe cache. In disposable copies replace the content digest with size+mtime, cache coarse keys, and remove generation checks separately; the corresponding count/result assertions must fail. Avoid an unbounded wait in any race test.

- [ ] **Step 3: Implement the fingerprint scan without reading unrelated content.** Use `os.walk(..., followlinks=False, onerror=raise_scan_error)` and lstat directory entries to prune directory symlinks and directories named `__pycache__`, `.venv`, or `venv`, plus every directory containing a regular `pyvenv.cfg`. Inspect only that marker's existence/type, never its contents. Do not silently suppress required enumeration/stat errors. Track regular `.py` leaves, including symlink leaves only if their targets are regular. The file set, count and max mtime cover all included source files. For count <=200 read their bytes sorted by relative POSIX path:

```python
hasher = hashlib.sha256()
for relative, path in sorted(files, key=lambda entry: entry[0]):
    hasher.update(relative.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
    hasher.update(b"\n")
return ("full", hasher.digest())
```

For >200 return `("coarse", count, newest_file_mtime_ns, app_dir.stat().st_mtime_ns)` and never read source contents just to create a purported authoritative digest. Complete interpreter identity with `str(interpreter)` and `interpreter.stat().st_mtime_ns`; never resolve the executable symlink.

- [ ] **Step 4: Add short-lock generation/cache state and wrap all operational failures.**

```python
_lock = threading.Lock()
_cache = {}
_generations = {}
SUPERSEDED = "Protocol capability check was superseded; retry after the restart or update."

def protocol_support_generation(app_id):
    with _lock:
        return _generations.get(app_id, 0)

def invalidate_protocol_support(app_id):
    with _lock:
        _generations[app_id] = _generations.get(app_id, 0) + 1
        for key in tuple(_cache):
            if key[0] == app_id:
                del _cache[key]

def probe_protocol_support(meta, *, use_cache=True):
    generation = protocol_support_generation(meta.id)
    return _probe_protocol_support_at_generation(meta, generation=generation, use_cache=use_cache)
```

The internal implementation follows this complete sequence: flag-false → unsupported fixed detail with no resolver/scan; unknown program id → unknown fixed detail; lock check supplied generation; resolve lexical interpreter and launch dir, compute full identity outside lock with prepared-failure translation; lock check generation and lookup only when use_cache AND full; run child outside lock; recompute interpreter stat/path/source identity outside lock; on mismatch return superseded and do not cache; lock recheck generation and insert only when use_cache AND both full keys equal; return result. Check generation before returning cached answers. Re-resolution may detect a changed activation choice. Wrap errors from the second scan as prepared-failure unknown and do not publish the old answer. Each unknown detail is redacted through `_unknown`. No mutex spans I/O, child waits or GUI calls.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_protocol_capability.py tests/test_validator_orchestration.py`; expect exit 0, exact threshold counts, lexical path preserved, and all blocked-test threads released. Existing interpreter-resolution and import-validation regressions live in test_validator_orchestration.py; no standalone test_app_interpreter.py exists.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/services/protocol_capability.py tests/test_protocol_capability.py
git commit -m "feat(capability): key probe cache by contents and generation"
```

## Task 7: Present snapshot-owned protocol controls and fail closed on load

**Implementer tier:** Capable

**Files:**

- Modify: `src/ai_manager/ui/app_detail_view.py:1-316` — imports, constructor/UI, load/draft/adopt/error/button state; retain model chip/log/status behavior.
- Modify: `src/ai_manager/ui/app_detail_view.py:401-414` — field change and emit-save canonicalization only; presets/fetch stay for Task 13.
- Modify: `src/ai_manager/ui/main_window.py:1-78` — imports for snapshot readers/errors.
- Modify: `src/ai_manager/ui/main_window.py:110-175` — add snapshot/load/conflict stores, preserving structured stores and startup order.
- Modify: `src/ai_manager/ui/main_window.py:200-263` — LLM view signal hookups only.
- Modify: `src/ai_manager/ui/main_window.py:269-330` — LLM initial-load branch; preserve structured load behavior.
- Modify: `src/ai_manager/ui/main_window.py:406-465` — ignore failed-load fallback draft signals, migrate current LLM writer/view call to snapshots; Task 9 adds the ordered gate and all post-commit handling.
- Modify: `src/ai_manager/ui/main_window.py:621-630` — interim snapshot re-read at existing dependent view call; keep current result shape until Task 12.
- Modify: `tests/test_app_views.py:1-285` — snapshot migration and protocol presentation cases.
- Modify: `tests/test_mnemonic.py:1-297` — migrate direct LLM `load_config` calls only.
- Modify: `tests/conftest.py:140-186` — add endpoint_window fixture after isolation setup.
- Create: `tests/test_endpoint_main_window.py`
- Test: `tests/test_app_views.py`
- Test: `tests/test_mnemonic.py`
- Test: `tests/test_endpoint_main_window.py`

**Interfaces:**

- Consumes: `ConfigSnapshot(config: AppAIConfig, sha256: bytes, api_base_present: bool)`, canonical AppAIConfig fields, `read_app_config_snapshot(meta: AppMetadata) -> ConfigSnapshot`, `ensure_config_exists(meta: AppMetadata) -> Path`, checked `write_app_config(meta, candidate: AppAIConfig, *, baseline: AppAIConfig, expected_sha256: bytes|None=None) -> bytes`.
- Consumes: `PROTOCOLS: tuple[Protocol(value: EndpointValue, label: str, auth_hint: str), ...]`, `compose_request_url(app_id: str, base: str, endpoint: str|None) -> str`, `effective_api_base(app_id: str, draft: AppAIConfig, snapshot: ConfigSnapshot) -> str`, `base_conflicts_with_endpoint(base: str, endpoint: str|None) -> bool`; frozen `ProtocolSupport(status: ProtocolSupportStatus, accepted: frozenset[str], detail: str)` with `ProtocolSupportStatus` members SUPPORTED=`supported`, PARTIAL=`partial`, UNSUPPORTED=`unsupported`, UNVERIFIABLE=`unverifiable`.
- Produces view: `load_config(snapshot: ConfigSnapshot) -> None`, `get_current_draft() -> AppAIConfig`, `set_protocol_support(support: ProtocolSupport) -> None`, `adopt_saved_baseline(snapshot: ConfigSnapshot, *, preserve_draft: bool) -> tuple[str,...]`, existing `show_config_error(message: str, detail: str="") -> None`, `set_recovery_state(*, load_failed: bool, conflicts: tuple[str,...]=(), message: str="", detail: str="") -> None`, `set_save_in_progress(saving: bool) -> None`, `reload_requested = pyqtSignal(str)`.
- Produces view private helpers: `_display_draft(self, draft: AppAIConfig) -> None` silently populates base/key/model/protocol widgets under finally-cleared loading/signal guards without changing the saved snapshot, loaded endpoint pair, capability/recovery state or emitting config_changed; `_on_protocol_selected(self, index: int) -> None`; `_refresh_protocol_presentation(self) -> None`; `_refresh_save_enablement(self) -> None`.
- Produces view private state: `_snapshot: ConfigSnapshot|None`, `_loaded_endpoint`, `_loaded_endpoint_raw`, `_endpoint`, `_endpoint_raw`, `_protocol_edited: bool`, `_protocol_combo: QComboBox|None`, `_protocol_hint`, `_request_url_label`, `_capability_notice`, `_reload_btn`; no-row apps create no protocol/hint/URL widgets. Existing `_model_combo`, base/key/model widget names and save signals stay compatible.
- Produces coordinator stores: `_snapshots: dict[str,ConfigSnapshot]`, `_load_failed: dict[str,bool]`, `_baseline_conflict: dict[str,tuple[str,...]]`; `endpoint_window` pytest fixture gives an isolated five-app MainWindow with controlled pool/restarts and modal teardown answers.

- [ ] **Step 1: Migrate direct view loads and add availability/invalid-state tests.** Import `snapshot` from `tests.endpoint_helpers` and wrap ONLY LLM `view.load_config(config)` calls with it; structured view calls still receive StructuredDoc. The view test metadata must set `supports_protocol_selection=True` explicitly. Add this matrix:

```python
@pytest.mark.parametrize("stored", [None, "/v1/responses", "invalid"])
@pytest.mark.parametrize("status,accepted", [
    (ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES),
    (ProtocolSupportStatus.PARTIAL, frozenset({"/v1/chat/completions", "/v1/messages"})),
    (ProtocolSupportStatus.UNSUPPORTED, frozenset()),
    (ProtocolSupportStatus.UNVERIFIABLE, frozenset()),
])
def test_all_availability_cells(qtbot, tmp_path, stored, status, accepted):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    config = AppAIConfig(endpoint=stored if stored != "invalid" else None,
                         endpoint_raw="'/bad'" if stored == "invalid" else None)
    view.load_config(snapshot(config))
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    support = ProtocolSupport(status, accepted, "probe <not markup>")
    view.set_protocol_support(support)
    view.set_protocol_support(support)
    enabled = {view._protocol_combo.itemData(i) for i in range(4)
               if view._protocol_combo.model().item(i).isEnabled()}
    want = {None} | (set(ENDPOINT_VALUES) if status in (
        ProtocolSupportStatus.SUPPORTED, ProtocolSupportStatus.UNVERIFIABLE) else set(accepted))
    if stored in ENDPOINT_VALUES:
        want.add(stored)
    assert enabled == want and events == []
    for i in range(4):
        label = view._protocol_combo.itemText(i)
        assert label.count(" unavailable") == (0 if view._protocol_combo.itemData(i) in want else 1)
    assert (view.get_current_draft().endpoint, view.get_current_draft().endpoint_raw) == (config.endpoint, config.endpoint_raw)


def test_raw_evidence_requires_explicit_activation(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(endpoint_raw="None")))
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    view._model_combo.setCurrentText("pending")
    assert view.get_current_draft().endpoint_raw == "None"
    assert view._request_url_label.text().startswith("Request URL: unavailable — ")
    auto = view._protocol_combo.findData(None)
    view._protocol_combo.setCurrentIndex(auto)
    view._protocol_combo.activated.emit(auto)
    assert view.get_current_draft().endpoint_raw is None
    assert view._protocol_edited and events
```

Add `test_support_refresh_keeps_rejected_pending_selection`: select Messages, then unsupported result with saved Auto; assert current data Messages, disabled item, no signal during refresh. Add initial failed-load/no-fallback test through endpoint_window and monkeypatched read/display/deep-copy seams: no `_snapshots`/`_saved_configs`/`_draft_configs` entry on initial failure; controls/save disabled, logs/restart available; direct `_on_config_changed` cannot publish an AppAIConfig default.

Add URL/hint tests with both ids, all three protocols and the six legacy rows from §3.2, including omitted presence, explicit placeholder, base edit/reversion and partial IPv6. Assert exact labels/data/order/row position, PlainText formats, noneditable combo, invalid disabled placeholder, and no protocol widgets for yt2txt. Capability refresh must preserve a recovery error/details and disabled saves. Model-list refresh on an untouched blank form must not emit a dirty event or turn None into a selected discovered model.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_app_views.py tests/test_mnemonic.py tests/test_endpoint_main_window.py`; expect availability/raw/failed-load behavioral assertions to fail on old semantics. After scaffolding, in isolated copies drop the saved-item exemption, clear raw on ordinary edits, or reset rejected selection to Auto; require their specific flag/pair/signal assertions to fail.

- [ ] **Step 3: Implement the view snapshot and presentation state.** Add reload action to the existing error area and protocol row immediately after the preset row. Four normal items carry None/exact literals; the optional invalid item is disabled and selected, with display `Invalid: {raw}` and no serializable endpoint value. Keep original labels in a tuple. Batch all programmatic control changes with `_is_loading` and QSignalBlocker, releasing guards in `finally` even if a widget throws. Extract the existing widget population into `_display_draft(draft)` with the exact private contract above; load_config and adoption own baseline publication separately. `_display_draft` updates the current endpoint/raw pair and its selected/invalid combo display, then recomputes intent against the unchanged loaded pair. It does not replace `_snapshot` or `_current_config`. Add a direct test that calling it preserves snapshot identity, recovery/capability details and zero draft-signal count. Install deep-copied baseline/presence only as a complete snapshot; return fresh canonical models and force unsupported split/protocol fields inactive.

```python
def _on_protocol_selected(self, index: int) -> None:
    if self._is_loading or self._protocol_combo is None or index not in range(4):
        return
    before = (self._endpoint, self._endpoint_raw)
    self._endpoint = self._protocol_combo.itemData(index)
    self._endpoint_raw = None
    self._protocol_edited = (self._endpoint, self._endpoint_raw) != (
        self._loaded_endpoint, self._loaded_endpoint_raw)
    self._refresh_protocol_presentation()
    if before != (self._endpoint, self._endpoint_raw):
        self._on_field_changed()
```

Connect both activated and currentIndexChanged to this idempotent path; blocked programmatic selection never counts as repair. Render exact hints and URL with `effective_api_base`; raw invalid short-circuits URL composition, and base conflict marks URL/base red while retaining exact doubled URL. Unknown/partial notices are amber; no version claims. `set_protocol_support` updates flags/labels silently and never changes selected index; preserve a pending rejected item even though disabled.

Centralize `_refresh_save_enablement`: snapshot exists AND no load/reload block AND no conflicts AND not saving. Editing groups require baseline and not saving, so recovery with an existing baseline preserves editable controls. Store recovery details, ordinary errors and probe details separately; choose the fixed global priority and keep probe detail fallback for ordinary success/restart notices. `set_protocol_support` must not overwrite recovery state. The initial implementation of `adopt_saved_baseline(..., preserve_draft=True)` retains the full current draft silently and installs the snapshot; Task 11 replaces this conservative merge with the specified per-field merge. Do not leave a config-only overload.

- [ ] **Step 4: Install coherent initial coordinator ownership and migrate every LLM call site.** Add the three stores before initial loading. For initial LLM load only, call ensure then noncreating snapshot read; stage saved/draft deep copies and view display before publishing coordinator entries. A read/copy/display exception uses typed load information, sets recovery block, and publishes no fallback. Ignore config_changed without an owned snapshot. Connect reload_requested to the existing `_reload_config`; Task 10 implements its digest-aware behavior.

For the current LLM save branch migrate to `digest = write_app_config(meta, canonical, baseline=old.config, expected_sha256=old.sha256)`, produce presence with the global formula, construct ConfigSnapshot and pass it at the view call site. Do not omit the digest to retain old tests. Task 9 replaces this branch with the full gate and committed-failure handling. For the interim dependent callback, ignore the incoming bare config for ownership and read a snapshot from the registered path, pass it to view adoption, install saved/draft copies and actual digest; Task 12 migrates the result payload and adds path validation/conflict publication. All new displays/read failures retain old coordinator ownership and require reload.

Add endpoint_window to conftest using five_app_workspace, `qtbot.addWidget`, patched QMessageBox question default Discard for teardown, MagicMock thread_pool and `supervisor_manager.restart_service`. It must construct the real MainWindow; do not replace SupervisorManager globally. Tests may override the question answer locally. Imports of new factories are local if needed to avoid collection cycles.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_app_views.py tests/test_mnemonic.py tests/test_endpoint_main_window.py tests/test_main_window.py`; expect exit 0, including draft survival across tabs and existing sidebar status behavior. `rg -n 'load_config\(|adopt_saved_baseline\(' src/ai_manager/ui tests` must show every LLM call supplies a ConfigSnapshot and structured calls retain StructuredDoc. Do not modify unrelated structured fixtures for this migration.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/ui/app_detail_view.py src/ai_manager/ui/main_window.py tests/test_app_views.py tests/test_mnemonic.py tests/test_endpoint_main_window.py tests/conftest.py
git commit -m "feat(ui): present protocol states from coherent LLM snapshots"
```

## Task 8: Deliver generation-bound jobs and complete restart attempts exactly once

**Implementer tier:** Frontier

**Files:**

- Modify: `src/ai_manager/services/config_jobs.py:1-58` — add ProtocolProbeJob and GUI-context forwarding QObject alongside existing launcher worker; preserve StructuredSaveJob.
- Modify: `src/ai_manager/services/supervisor.py:110-124` — action-process signal setup/attempt state.
- Modify: `src/ai_manager/services/supervisor.py:207-214` — qualify app-scoped attempt dispatch; retain immediate busy result.
- Modify: `src/ai_manager/services/supervisor.py:245-253` — terminal finished/error bridge.
- Modify: `src/ai_manager/ui/main_window.py:1-78` — imports.
- Modify: `src/ai_manager/ui/main_window.py:110-175` — protocol maps and startup call after view construction/loading.
- Modify: `src/ai_manager/ui/main_window.py:511-520` — manual restart attribution; remove the earlier shadowed `_request_saved_restart` definition.
- Modify: `src/ai_manager/ui/main_window.py:557-589` — insert separate protocol start/completion methods beside launcher methods, without changing launcher cache.
- Modify: `src/ai_manager/ui/main_window.py:687-694` — keep and extend the effective saved-restart helper with immutable attempt origin.
- Modify: `src/ai_manager/ui/main_window.py:722-737` — terminal invalidation/reprobe and existing notices.
- Modify: `tests/conftest.py:160-186` — extend isolate_manager with controlled protocol starter, preserving a `_production_start_protocol_probes` alias.
- Modify: `tests/test_supervisor.py:1-106` — append FailedToStart/exactly-once tests.
- Modify: `tests/test_endpoint_main_window.py:1-400` — append jobs, delivery, race and restart tests after Task 7 ownership tests.
- Test: `tests/test_supervisor.py`
- Test: `tests/test_endpoint_main_window.py`

**Interfaces:**

- Consumes: `_probe_protocol_support_at_generation(meta: AppMetadata, *, generation: int, use_cache: bool=True) -> ProtocolSupport`, `protocol_support_generation(app_id: str) -> int`, `invalidate_protocol_support(app_id: str) -> None`; `_unknown(reason: str, stdout: str="", stderr: str="") -> ProtocolSupport` for unexpected worker exceptions. `ProtocolSupport` is frozen with `status: ProtocolSupportStatus`, `accepted: frozenset[str]`, `detail: str`; status members are SUPPORTED=`supported`, PARTIAL=`partial`, UNSUPPORTED=`unsupported`, UNVERIFIABLE=`unverifiable`.
- Consumes: existing `ConfigJobSignals.probe_finished = pyqtSignal(str, object)`, existing `SupervisorManager.action_completed = pyqtSignal(str, bool, str)`, `restart_service(service_name: str) -> None`, `QThreadPool.start(job: QRunnable) -> None` and view `set_protocol_support(support: ProtocolSupport) -> None`.
- Produces: `ProtocolProbeJob(meta: AppMetadata, token: int, generation: int)`, `.signals: ConfigJobSignals`, `.token: int`, `.generation: int`, `.run() -> None`; exactly one terminal probe_finished.
- Produces: GUI-owned `ProtocolProbeDelivery(QObject)` constructed with `window: MainWindow`, `app_id: str`, `token: int`, `generation: int`; `@pyqtSlot(str, object) finished(emitted_id: str, support: ProtocolSupport) -> None` forwards immutable context. Keep it owned with the matching job until completion.
- Produces coordinator: `_start_protocol_probes() -> None`, `_start_protocol_probe(app_id: str) -> None`, `_on_protocol_probe_finished(app_id: str, token: int, generation: int, support: ProtocolSupport) -> None`, stores `_protocol_probe_tokens: dict[str,int]`, `_protocol_probe_jobs: dict[tuple[str,int],ProtocolProbeJob]`, `_protocol_support: dict[str,ProtocolSupport]`, plus delivery ownership.
- Produces supervisor private terminal seam: `_complete_action(attempt: int, action: str, success: bool, message: str) -> None`; connects BOTH finished and FailedToStart with the immutable attempt id/action, suppresses duplicate completion for that attempt, clears active state before emitting. Existing action signal shape/notices remain compatible.

- [ ] **Step 1: Test workers, GUI affinity, obsolete tokens and all restart origins.** Add a real QThreadPool test rather than only calling run() directly:

```python
def test_probe_completion_is_delivered_in_gui_context(qtbot, endpoint_window, monkeypatch):
    from PyQt6.QtCore import QThread, QThreadPool
    from PyQt6.QtWidgets import QApplication
    import ai_manager.services.config_jobs as jobs
    window = endpoint_window
    observed = []
    monkeypatch.setattr(jobs, "_probe_protocol_support_at_generation",
        lambda meta, **kw: ProtocolSupport(ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES))
    original = window._on_protocol_probe_finished
    def completion(*args):
        observed.append(QThread.currentThread() == QApplication.instance().thread())
        original(*args)
    monkeypatch.setattr(window, "_on_protocol_probe_finished", completion)
    pool = QThreadPool(window)
    window.thread_pool = pool
    window._start_protocol_probe("ai-grammar")
    qtbot.waitUntil(lambda: bool(observed), timeout=2000)
    assert observed == [True]
    assert window._protocol_support["ai-grammar"].accepted == ENDPOINT_VALUES
```

Add controlled jobs completed in reverse token order: retain newer `(app_id,token)` entry when old completion arrives; only current token/current generation can change UI/details. Queue generation g, invalidate before job.run, assert no spawn. Mutate original metadata after job construction and assert worker uses owned original metadata. Unexpected worker exception produces one redacted unknown signal. Protocol startup creates exactly two jobs after views exist and never uses the launcher map.

Add parametrized saved/manual × success/failure/immediate-busy restart tests: snapshot full current draft (including endpoint raw/model/base/key), assert no invalidation on dispatch, then one invalidation and fresh job at terminal origin, and identical draft afterward. Fully qualified callback uses its own id; unqualified immediate busy callback uses `_submitting_restart` for both dispatchers. Status refresh and save-only produce no invalidation; unrelated structured app restart produces no protocol job.

For `test_failed_to_start_finishes_once_without_finished`, instantiate real SupervisorManager with controlled QProcess (local fixture, no real command). Capture action_completed; dispatch ai-grammar restart; emit only `errorOccurred(FailedToStart)` with errorString `missing launcher fixture`. Assert exactly one `("restart ai-grammar", False, message)` callback. Emit finished afterward and assert still one. Repeat at coordinator level for saved restart: pending set cleared, failure copy shown, exactly one invalidation/new job, draft unchanged. Start a second attempt after the first completes, deliver an old attempt callback, assert the second remains active; capture immutable attempt context in callbacks instead of consulting only the mutable `_current_action`.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_supervisor.py tests/test_endpoint_main_window.py`; expect missing FailedToStart terminal/count assertions and obsolete publication assertions to fail. In isolated copies remove the GUI token check, capture generation at run time, invalidate at dispatch only, and remove the FailedToStart connection separately. Each targeted test must fail its state/count/thread assertion; a manually called worker does not prove thread affinity.

- [ ] **Step 3: Implement owned worker and GUI-bound delivery.**

```python
class ProtocolProbeJob(QRunnable):
    def __init__(self, meta, token, generation):
        super().__init__()
        self.meta = meta.model_copy(deep=True)
        self.token, self.generation = token, generation
        self.signals = ConfigJobSignals()

    def run(self):
        try:
            result = _probe_protocol_support_at_generation(self.meta, generation=self.generation)
        except Exception as exc:
            result = _unknown(f"Protocol capability check failed: {exc}")
        self.signals.probe_finished.emit(self.meta.id, result)
```

The delivery QObject is created in MainWindow's thread and parented to it. Its bound decorated slot checks emitted id matches captured id and forwards to the current window method; connect with `Qt.ConnectionType.QueuedConnection`. Its annotation imports MainWindow only under TYPE_CHECKING to avoid a cycle. Own it in a separate `(id,token)` map or on an owned job; never use an unbound worker-thread lambda as the delivery context. On completion remove only the matching owned job/delivery, then test app existence, flag, token and generation before storing/applying support. A stale result must not clear a newer job or diagnostic. Token capture and generation capture happen before pool.start.

- [ ] **Step 4: Implement the terminal bridge and connect re-probing to terminal attempts.** Add a monotonically increasing attempt id and completed-id guard in SupervisorManager. For each dispatched action bind id/action to both finished and error callbacks, disconnect retired callbacks safely, and route only FailedToStart from errorOccurred to `_complete_action`. Other QProcess errors may still finish normally. `_complete_action` marks complete and clears active state BEFORE emitting; decode existing stdout/stderr on finished and `errorString()` for FailedToStart. A later finished from that attempt is ignored. Keep busy refusal synchronous and unqualified to preserve existing behavior.

Consolidate the two MainWindow `_request_saved_restart` definitions into ONE effective definition at the later anchor. Preserve saved notice and pending set, and wrap both manual and saved restart dispatch in `_submitting_restart` try/finally. `_on_supervisor_action` resolves qualified or synchronous origin, clears saved pending/show success or failure as before, then for an eligible origin invalidates once and starts one new job. It does not reload or write config and cannot clear recovery flags. Do not hook polling or command dispatch.

Extend isolate_manager to save `_production_start_protocol_probes` before replacing startup with deterministic unknown presentation; allow explicit tests to call the original starter with a controlled pool. Do not replace SupervisorManager class globally. Worker maps and launch-probe fixtures remain separate.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_supervisor.py tests/test_endpoint_main_window.py tests/test_structured_main_window.py`; expect exit 0 with all real-thread/terminal/count assertions and existing saved-restart notices preserved. Verify exactly one `_request_saved_restart` definition via `rg -n '^    def _request_saved_restart' src/ai_manager/ui/main_window.py`.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/services/config_jobs.py src/ai_manager/services/supervisor.py src/ai_manager/ui/main_window.py tests/conftest.py tests/test_supervisor.py tests/test_endpoint_main_window.py
git commit -m "feat(capability): deliver generation-safe jobs after every terminal restart"
```

## Task 9: Enforce the ordered gate at the sole LLM commit seam

**Implementer tier:** Frontier

**Files:**

- Modify: `src/ai_manager/ui/main_window.py:1-78` — imports and LLMGateResult before MainWindow.
- Modify: `src/ai_manager/ui/main_window.py:395-465` — add gate beside payload checking and replace only the LLM save branch introduced in Task 7; preserve structured worker dispatch.
- Modify: `src/ai_manager/ui/main_window.py:651-685` — LLM error routing before structured recovery, transaction unknown block; keep structured dialogs.
- Modify: `tests/test_endpoint_main_window.py:1-800` — append ordered real-slot, writer-argument and commit-boundary cases.
- Test: `tests/test_endpoint_main_window.py`
- Test: `tests/test_yaml_manager.py`
- Test: `tests/test_transaction.py`

**Interfaces:**

- Consumes: canonical `AppAIConfig(api_base: str, api_key: str, model: str|None, is_split_model: bool, ocr_model: str|None, text_model: str|None, endpoint: EndpointValue|None, endpoint_raw: str|None)`, `ConfigSnapshot(config: AppAIConfig, sha256: bytes, api_base_present: bool)`.
- Consumes: `is_valid_endpoint(value: object) -> bool`, `effective_api_base(app_id: str, draft: AppAIConfig, snapshot: ConfigSnapshot) -> str`, `base_conflicts_with_endpoint(base: str, endpoint: str|None) -> bool`, `compose_request_url(app_id: str, base: str, endpoint: str|None) -> str`.
- Consumes: `probe_protocol_support(meta: AppMetadata, *, use_cache: bool=True) -> ProtocolSupport`, with status enum SUPPORTED/PARTIAL/UNSUPPORTED/UNVERIFIABLE, accepted frozenset and redacted detail; the coordinator's `_protocol_support` is presentation, never authority for a changed endpoint.
- Consumes: `write_app_config(meta: AppMetadata, candidate: AppAIConfig, *, baseline: AppAIConfig, expected_sha256: bytes|None=None) -> bytes`; `CommittedWriteError(path: Path, installed_sha256: bytes, report: TransactionReport, cause: BaseException)`; `TransactionError.report.files: dict[Path,Literal["new","restored","unknown"]]`; `StaleDocumentError(path, expected_sha256: bytes|None, actual_sha256: bytes|None)`.
- Consumes: `AppDetailView.load_config(snapshot: ConfigSnapshot) -> None`, `set_protocol_support(support: ProtocolSupport) -> None`, `set_recovery_state(*, load_failed: bool, conflicts: tuple[str,...]=(), message: str="", detail: str="") -> None`, `show_config_error(message: str, detail: str="") -> None`, existing `_request_saved_restart(app_id: str) -> None`, `_check_payload(app_id: str, config: object) -> None`, `_set_dirty_indicator(app_id: str) -> None`, `_update_auth_warnings() -> None`.
- Produces: frozen `LLMGateResult(refused: bool=False, no_op: bool=False, message: str="", detail: str="")`; `_evaluate_llm_gate(self, app_id: str, draft: AppAIConfig, saved: AppAIConfig|None) -> LLMGateResult`; fully checked `_on_save_requested(self, app_id: str, config: object, should_restart: bool) -> None` as the only production LLM writer.
- Produces private `_committed_llm_snapshot(self, prepared: ConfigSnapshot, digest: bytes) -> ConfigSnapshot`: validate the binary digest, make a shallow copy of an unpublished, already deep-owned prepared snapshot, set only its digest with `object.__setattr__`, and return it. This internal assembly never changes a published snapshot/config and avoids post-commit deep-copy failures; all public snapshot construction still validates/deep-copies through `__post_init__`.

- [ ] **Step 1: Add real save-slot tests with forbidden-call guards and exact ownership assertions.** Import main_window as mw and pytest/Mock, ConfigSnapshot, protocol records, ConfigError/CommittedWriteError/TransactionError/StaleDocumentError. Each test calls `_on_save_requested`, not only the gate. Arrange fresh baseline through the real fixture or a snapshot installed in all three stores and `view.load_config(snap)` before editing. Add helper `install_saved(window, app_id, config, *, present=True, digest=b"b"*32)` locally, returning its ConfigSnapshot and storing independent saved/draft copies; do not patch the gate in tests intended to cover gate order.

```python
def test_real_save_slot_obeys_gate_refusal(endpoint_window, monkeypatch):
    window = endpoint_window
    refused = mw.LLMGateResult(refused=True, message="fixture refusal", detail="<plain>")
    gate = Mock(return_value=refused)
    writer = Mock(side_effect=AssertionError("refused write"))
    monkeypatch.setattr(window, "_evaluate_llm_gate", gate)
    monkeypatch.setattr(mw, "write_app_config", writer)
    before = window._snapshots["ai-grammar"]
    draft = window.views["ai-grammar"].get_current_draft()
    window._on_save_requested("ai-grammar", draft, True)
    gate.assert_called_once_with("ai-grammar", draft, before.config)
    writer.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()
    assert window._snapshots["ai-grammar"] is before
    assert window.views["ai-grammar"]._config_error_label.text() == "fixture refusal"

@pytest.mark.parametrize("status", [ProtocolSupportStatus.UNSUPPORTED, ProtocolSupportStatus.UNVERIFIABLE])
@pytest.mark.parametrize("removal", [True, False])
def test_removal_and_unchanged_skip_probe(endpoint_window, monkeypatch, status, removal):
    window = endpoint_window
    old = install_saved(window, "ai-grammar", AppAIConfig(api_base="https://x", endpoint="/v1/messages"))
    forbidden = Mock(side_effect=AssertionError("preserved/removed endpoint probed"))
    monkeypatch.setattr(mw, "probe_protocol_support", forbidden)
    window._protocol_support["ai-grammar"] = ProtocolSupport(status, frozenset(), "unknown detail")
    candidate = AppAIConfig.model_validate({**old.config.model_dump(), "model": "pending",
                                           "endpoint": None if removal else old.config.endpoint})
    writer = Mock(return_value=b"n" * 32)
    monkeypatch.setattr(mw, "write_app_config", writer)
    window._on_save_requested("ai-grammar", candidate, False)
    writer.assert_called_once_with(window.apps["ai-grammar"], candidate,
                                   baseline=old.config, expected_sha256=old.sha256)
    assert window._snapshots["ai-grammar"].sha256 == b"n" * 32
    assert window._saved_configs["ai-grammar"] == candidate
    forbidden.assert_not_called()
```

Add parametrized ordered cases: missing snapshot/failed load before all other checks; conflict before invalid literal; forged invalid `model_construct(endpoint="/bad")` before model revalidation; raw before base/no-op; explicit conflict before equal/unchanged endpoints; metadata false before any probe; partial allowed Messages vs refused Responses; unknown introduction/change; raw repair to Auto reaches writer despite equal normalized endpoints. Assert exact message/details from globals, pending draft retained and no restart. For rule 4 set unchanged Messages and edit only base to `https://x/v1/`; expect `Request URL: https://x/v1/v1/messages`. For forged other model shape use bad base type and require existing local-save ConfigError translation, not protocol evidence.

No-op: parametrize both save buttons, read-only file and omitted fields/odd YAML formatting. Patch writer, renderer and Transaction to fail if reached; patch probe forbidden; assert identical bytes/mode, no backup/temp, snapshot identity unchanged, only requested restart. Repeat equality with load/conflict/raw/base guards and require refusal.

Add `test_two_saves_advance_actual_digest_and_presence`: use real writer against the fixture; edit model twice and assert second expected digest equals first actual bytes; originally omitted base protocol-only save retains false, explicit base change makes true, and preview uses saved explicit value thereafter. Add precommit local/TransactionError(restored)/TransactionError(unknown) failures; snapshot identity and all saved/draft values retained, no restart; unknown blocks saves.

For `test_coordinator_installs_committed_cleanup_outcome`, wrap actual Transaction.__exit__ as in the writer test so it releases then raises after replace_all; call the real save slot with model `committed-fixture`. Assert actual bytes contain candidate; coordinator snapshot hash equals those bytes and candidate fields/presence; error text is the fixed committed copy, details name the cleanup cause; save buttons disabled, reload shown, no restart. Repeat with a mocked writer throwing a constructed CommittedWriteError to pin typed routing. Add `test_post_commit_display_failure_retains_committed_snapshot`: real writer succeeds but view.load_config raises; assert new installed triple/draft retained, blocked saves, no restart. Add actual primary TransactionError(unknown) plus cleanup fault via the Transaction seam; primary report identity survives and old snapshot remains blocked.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_endpoint_main_window.py`; require gate-bypass/old-digest/cleanup/display state assertions to fail before the implementation. In disposable copies move no-op ahead of refusal guards, use displayed support instead of fresh keyed probe, keep old digest after success, and catch CommittedWriteError as an ordinary failure. Each corresponding exact assertion must fail. Preserve the primary unknown report in fault tests; do not flatten it to a generic message.

- [ ] **Step 3: Add the gate with this exact evaluation sequence.**

```python
def _evaluate_llm_gate(self, app_id, draft, saved):
    snap = self._snapshots.get(app_id)
    def refuse(message, detail=""):
        return LLMGateResult(refused=True, message=message, detail=detail)
    if self._load_failed.get(app_id, False) or snap is None or saved is None:
        return refuse("Reload the configuration before saving.")
    conflicts = self._baseline_conflict.get(app_id, ())
    if conflicts:
        return refuse("Configuration changed while you were editing. Reload the configuration before saving.",
                      "Conflicting fields: " + ", ".join(conflicts) + ".")
    if draft.endpoint is not None and not is_valid_endpoint(draft.endpoint):
        return refuse(f"Unsupported protocol value: {draft.endpoint!r}. Pick one of the three supported protocols or Auto.")
    if draft.endpoint_raw is not None:
        return refuse("Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.",
                      f"Stored ai.endpoint: {draft.endpoint_raw}")
    canonical = AppAIConfig.model_validate(draft.model_dump())
    saved = snap.config
    base = effective_api_base(app_id, canonical, snap)
    if canonical.endpoint is not None and base_conflicts_with_endpoint(base, canonical.endpoint):
        return refuse("The protocol path already includes /v1. Enter the gateway prefix, e.g. https://api.openai.com.",
                      "Request URL: " + compose_request_url(app_id, base, canonical.endpoint))
    if canonical == saved:
        return LLMGateResult(no_op=True)
    if canonical.endpoint is None and saved.endpoint is not None:
        return LLMGateResult()
    if canonical.endpoint == saved.endpoint:
        return LLMGateResult()
    meta = self.apps[app_id]
    if not meta.supports_protocol_selection:
        return refuse("Protocol selection is not available for this application.")
    support = probe_protocol_support(meta)
    self._protocol_support[app_id] = support
    self.views[app_id].set_protocol_support(support)
    if canonical.endpoint in support.accepted:
        return LLMGateResult()
    if support.status is not ProtocolSupportStatus.UNVERIFIABLE:
        return refuse(f"Installed build rejected protocol {canonical.endpoint}. Update the service or select Auto.", support.detail)
    return refuse("Cannot verify this build; introducing or changing ai.endpoint is refused. Select Auto to remove the key, or restore the saved protocol.", support.detail)
```

Only run this after managed-app and `_check_payload` checks; use `.get()` for missing saved values. LLMGateResult validates not(refused and no_op). The gate mutates no snapshot/draft/file/restart state; availability updates may occur only at the final support step.

- [ ] **Step 4: Implement checked save publication and typed error ownership.** Prepare canonical data and all independent owned copies BEFORE entering the writer. A practical complete commit skeleton, within the checked LLM branch, is:

```python
snap = self._snapshots.get(app_id)
result = self._evaluate_llm_gate(app_id, config, self._saved_configs.get(app_id))
if result.refused:
    view.show_config_error(result.message, result.detail)
    return
if result.no_op:
    if should_restart:
        self._request_saved_restart(app_id)
    else:
        view.show_config_error("Configuration saved.")
    return
candidate = AppAIConfig.model_validate(config.model_dump())
saved_copy, draft_copy = candidate.model_copy(deep=True), candidate.model_copy(deep=True)
present = snap.api_base_present or candidate.api_base != snap.config.api_base
prepared = ConfigSnapshot(candidate, snap.sha256, present)
committed_error = None
try:
    installed = write_app_config(meta, candidate, baseline=snap.config, expected_sha256=snap.sha256)
except CommittedWriteError as exc:
    installed, committed_error = exc.installed_sha256, exc
new_snapshot = self._committed_llm_snapshot(prepared, installed)
self._snapshots[app_id] = new_snapshot
self._saved_configs[app_id], self._draft_configs[app_id] = saved_copy, draft_copy
if committed_error is not None:
    self._load_failed[app_id] = True
    view.set_recovery_state(load_failed=True,
        conflicts=self._baseline_conflict.get(app_id, ()),
        message="Configuration saved, but the file must be reloaded before another save.",
        detail=str(committed_error.cause))
    self._set_dirty_indicator(app_id)
    return
try:
    view.load_config(new_snapshot)
    self._set_dirty_indicator(app_id)
    self._update_auth_warnings()
except Exception as exc:
    self._load_failed[app_id] = True
    view.set_recovery_state(load_failed=True, message="Configuration saved, but the file must be reloaded before another save.", detail=str(exc))
    return
if should_restart:
    self._request_saved_restart(app_id)
else:
    view.show_config_error("Configuration saved.")
```

Implement `_committed_llm_snapshot` using `copy.copy(prepared)`, validate `type(digest) is bytes and len(digest)==32`, then set digest only on that unpublished copy; it owns config already deep-copied before writer entry. Never mutate the old record. Ordinary successful publication clears only resolved ordinary errors; recovery flags cannot be cleared without reload. Post-commit handlers must retain the new triple even if dirty/auth display fails.

Before structured recovery in `_on_structured_save_failed`, dispatch LLM errors separately: StaleDocumentError sets load/reload block and exact stale message; TransactionError preserves report, shows existing transaction report detail/dialog, and sets block if any state unknown; ordinary precommit errors retain all ownership, display local-save information, no restart. Every LLM path returns before StructuredDoc `.kind`, StaleDocumentDialog or structured rendering. Unknown app/kind/payload checks stay exhaustive. No save originates from any other handler.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_endpoint_main_window.py tests/test_yaml_manager.py tests/test_transaction.py tests/test_structured_main_window.py`; expect exit 0. Inspect `rg -n 'write_app_config\(' src` and confirm one production call in MainWindow with both keyword arguments, plus the writer definition. Passing helper-only tests is insufficient.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/ui/main_window.py tests/test_endpoint_main_window.py
git commit -m "feat(save): enforce ordered LLM gate and preserve committed snapshots"
```

## Task 10: Reload LLM files without discarding drafts or entering structured recovery

**Implementer tier:** Capable

**Files:**

- Modify: `src/ai_manager/ui/main_window.py:269-334` — add a staged LLM snapshot installer next to load and replace only LLM `_reload_config`; preserve initial-only ensure and structured reload.
- Modify: `src/ai_manager/ui/main_window.py:651-685` — typed LLM stale/reload error path from Task 9, before structured dialogs.
- Modify: `tests/test_endpoint_main_window.py:1-1200` — append reload confirmation/state tables and stale/commit recovery assertions.
- Test: `tests/test_endpoint_main_window.py`
- Test: `tests/test_structured_main_window.py`

**Interfaces:**

- Consumes: `read_app_config_snapshot(meta: AppMetadata) -> ConfigSnapshot(config: AppAIConfig, sha256: bytes, api_base_present: bool)`; never `read_app_config` or `ensure_config_exists` during reload.
- Consumes: view `load_config(snapshot: ConfigSnapshot) -> None`, `_display_draft(draft: AppAIConfig) -> None` (silent widgets only, preserves baseline/capability/recovery), `get_current_draft() -> AppAIConfig`, `set_recovery_state(*, load_failed: bool, conflicts: tuple[str,...]=(), message: str="", detail: str="") -> None`; coordinator `_snapshots`, `_saved_configs`, `_draft_configs`, `_load_failed`, `_baseline_conflict`; `_is_dirty(app_id: str) -> bool` and existing auth/dirty refresh.
- Consumes: `QMessageBox.question(parent, title: str, text: str, buttons: StandardButton, defaultButton: StandardButton) -> StandardButton`; StaleDocumentError's path/expected/actual bytes; ConfigLoadError path/detail/reason; ConfigError and post-commit block from Task 9.
- Produces: `_reload_config(self, app_id: str) -> None`; `_install_llm_reload(self, app_id: str, snapshot: ConfigSnapshot, draft: AppAIConfig) -> None`, which stages independent saved/draft copies and silent view restoration before coordinator publication, clears recovery flags only after successful installation, then refreshes dirty/auth. It retains prior ownership on any read/display/deep-copy failure.

- [ ] **Step 1: Add the full reload state table and real typed stale case.** Reuse endpoint_window; avoid a modal by monkeypatching QMessageBox.question in each confirmation case. Always read before asking. Capture old snapshot identity, copies of saved/draft, visible widgets, and capability result.

```python
def test_same_digest_reload_preserves_pending_edits(endpoint_window, monkeypatch):
    window = endpoint_window
    view = window.views["ai-grammar"]
    view._model_combo.setCurrentText("pending-model")
    before = window._snapshots["ai-grammar"]
    pending = view.get_current_draft()
    window._load_failed["ai-grammar"] = True
    monkeypatch.setattr(mw.QMessageBox, "question", Mock(side_effect=AssertionError("same digest must not prompt")))
    writer = Mock(side_effect=AssertionError("reload writes"))
    monkeypatch.setattr(mw, "write_app_config", writer)
    window._reload_config("ai-grammar")
    assert window._snapshots["ai-grammar"].sha256 == before.sha256
    assert window._draft_configs["ai-grammar"] == pending == view.get_current_draft()
    assert not window._load_failed["ai-grammar"]
    assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
    writer.assert_not_called()

@pytest.mark.parametrize("answer,discard", [(mw.QMessageBox.StandardButton.Cancel, False),
                                            (mw.QMessageBox.StandardButton.Discard, True)])
def test_changed_digest_pending_reload_requires_confirmation(endpoint_window, monkeypatch, answer, discard):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setCurrentText("pending")
    before = window._snapshots[app_id]
    pending = view.get_current_draft()
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_text("ai: {api_base: 'https://new', model: external, endpoint: /v1/messages}\n")
    question = Mock(return_value=answer)
    monkeypatch.setattr(mw.QMessageBox, "question", question)
    window._reload_config(app_id)
    question.assert_called_once()
    args = question.call_args
    assert "Reload configuration" in args.args
    assert "Reload configuration and discard unsaved changes?" in args.args
    if discard:
        assert window._snapshots[app_id].sha256 == hashlib.sha256(path.read_bytes()).digest()
        assert view.get_current_draft().model == "external" and not window._is_dirty(app_id)
    else:
        assert window._snapshots[app_id] is before
        assert window._draft_configs[app_id] == pending == view.get_current_draft()
```

Add first successful reload after initial failure; changed digest clean draft installs without prompt; same digest WITH conflict prompts and Cancel keeps block, Discard clears it; failed read/display/deepcopy retains all prior coordinator ownership and pending widgets and never prompts after read failure. Delete config while example exists; reload refuses without copying it. CommittedWriteError→failed reload retains new snapshot/block; successful reload clears it.

For typed stale integration use the real writer: change the on-disk file to add endpoint, keep pending model, save. Patch `StaleDocumentDialog` constructor to fail if reached. Assert external exact bytes untouched, pending draft/old snapshot retained, reload button shown, both saves disabled, exact stale text. Complete a supported probe and assert the stale block and error details remain. Discard reload then installs actual digest/presence and enables saves. Probe status is preserved across reload and is never the condition that clears recovery.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_endpoint_main_window.py -k 'reload or stale or committed or display'`; expect pending widgets/Cancel/typed-path assertions to fail with unconditional `_load_config` reload. In a disposable copy use the compatibility reader, discard before reading, or let same-digest conflict skip confirmation; require exact no-copy/no-discard/block assertions to fail.

- [ ] **Step 3: Implement noncreating read, guarded confirmation and staged installation.**

```python
# Inside the LLM branch of _reload_config, after managed/kind checks:
old = self._snapshots.get(app_id)
try:
    incoming = read_app_config_snapshot(meta)
except Exception as exc:
    self._load_failed[app_id] = True
    view.set_recovery_state(load_failed=True, conflicts=self._baseline_conflict.get(app_id, ()),
                            message=str(exc), detail=getattr(exc, "detail", str(exc)))
    return
conflicts = self._baseline_conflict.get(app_id, ())
pending = view.get_current_draft() if old is not None else None
changed = old is not None and incoming.sha256 != old.sha256
needs_discard = bool(conflicts) or (changed and pending != old.config)
if needs_discard:
    answer = QMessageBox.question(self, "Reload configuration",
        "Reload configuration and discard unsaved changes?",
        QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if answer != QMessageBox.StandardButton.Discard:
        return
keep_pending = old is not None and not changed and not conflicts
draft = pending if keep_pending else incoming.config
self._install_llm_reload(app_id, incoming, draft)
```

The installer prepares copies and remembers the old view snapshot/current draft for restoration if display fails. Call `view.load_config(incoming)` then `view._display_draft(draft)` while signals remain blocked; the latter helper's saved snapshot and loaded endpoint pair remain incoming, while same-digest pending widgets return silently. Only then publish all coordinator stores and clear load/conflict flags. Preserve capability status/details and recompute endpoint intent against incoming when restoring a pending draft. Both helper signatures already exist; no view API/file changes are part of this task. No I/O, restart, discovery or probe is triggered by installation.

If `view.get_current_draft` or copy/display fails, retain old ownership, set load block, restore previous visible draft best-effort under finally-cleared blockers, show typed load context. For structured kinds retain the existing `_load_config` and auth refresh behavior. Typed stale routing from Task 9 returns before any structured dialog/diff branch; no hash is advanced from observed stale error data.

- [ ] **Step 4: Run green.** Run `python -B -m pytest -q tests/test_endpoint_main_window.py tests/test_structured_main_window.py`; expect exit 0 for all confirmation/no-copy/recovery states and existing structured reload/diff behavior. Repeat successful reload after committed failure only when the prior run exposed a new failure; otherwise proceed without redundant tests.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/ui/main_window.py tests/test_endpoint_main_window.py
git commit -m "feat(recovery): reload LLM snapshots without silently discarding drafts"
```

## Task 11: Rebase each managed field and retain cross-mode conflicts visibly

**Implementer tier:** Capable

**Files:**

- Modify: `src/ai_manager/ui/app_detail_view.py:243-301` — extend the Task 7 silent-population helper and replace `adopt_saved_baseline` conservative behavior with three-way merge; preserve snapshot-only loading.
- Modify: `tests/test_app_views.py:168-188` — update the old dirty-tab coarse-preservation assertions to per-field adoption.
- Modify: `tests/test_app_views.py:270-285` — update trailing baseline-adoption regression and append complete field/mode matrices.
- Test: `tests/test_app_views.py`

**Interfaces:**

- Consumes: `ConfigSnapshot(config: AppAIConfig, sha256: bytes, api_base_present: bool)`, canonical AppAIConfig fields and logical endpoint pair `(endpoint: EndpointValue|None, endpoint_raw: str|None)`.
- Consumes view: `get_current_draft() -> AppAIConfig`, `load_config(snapshot: ConfigSnapshot) -> None`, private `_display_draft(draft: AppAIConfig) -> None` (silent widget-only population, no baseline change, no signals), `_refresh_protocol_presentation() -> None`, `_refresh_save_enablement() -> None`; ProtocolSupport state remains unchanged.
- Produces: `adopt_saved_baseline(snapshot: ConfigSnapshot, *, preserve_draft: bool) -> tuple[str,...]`; deterministic field order `("api_base","api_key","endpoint","is_split_model","model","ocr_model","text_model")`; returned conflicts name logical endpoint once and mode/leaf conflicts in that order. C's config/digest/presence always becomes the saved view baseline; D is read from widgets immediately before merge, not a captured worker-start value.

- [ ] **Step 1: Test every field's four merge cases and raw endpoint equality.** Define field-aware configurations so canonicalization does not invalidate the fixture: unified for `model`, split for OCR/text, and a mode-only transition with no leaf edits for `is_split_model`. Endpoint cases use pairs, including `(None,"None")` vs `(None,"'/bad'")` vs `(None,None)`.

```python
@pytest.mark.parametrize("field,old,user,committed", [
    ("api_base", "https://old", "https://user", "https://committed"),
    ("api_key", "$OLD", "$USER", "$COMMITTED"),
    ("endpoint", (None, None), ("/v1/messages", None), ("/v1/responses", None)),
    ("model", "old", "user", "committed"),
    ("ocr_model", "old", "user", "committed"),
    ("text_model", "old", "user", "committed"),
])
@pytest.mark.parametrize("case", ["unedited", "user-only", "agree", "disagree"])
def test_rebase_four_field_cases(qtbot, tmp_path, field, old, user, committed, case):
    meta = meta_for(tmp_path, "textkit")
    view = AppDetailView(meta)
    qtbot.addWidget(view)
    def config(value):
        data = {"api_base": "https://base", "is_split_model": field in ("ocr_model", "text_model")}
        if field == "endpoint":
            data.update(endpoint=value[0], endpoint_raw=value[1])
        else:
            data[field] = value
        return AppAIConfig(**data)
    local = config(old)
    draft = config(old if case == "unedited" else user)
    disk = config(old if case == "user-only" else user if case == "agree" else committed)
    view.load_config(snapshot(local, digest=b"l"*32))
    view._display_draft(draft)
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    conflicts = view.adopt_saved_baseline(snapshot(disk, digest=b"c"*32, present=False), preserve_draft=True)
    result = view.get_current_draft()
    expected = disk if case == "unedited" else draft
    assert result == expected
    assert conflicts == ((field,) if case == "disagree" else ())
    assert view._snapshot.config == disk and view._snapshot.api_base_present is False
    assert events == []
```

Add mode-only D/C truth-table tests and cross-mode dependency tests in BOTH directions: C changes mode while D edits old active leaf; D changes mode while C edits old active leaf; originally absent leaf becomes edited; retain D's mode/active value, return mode+leaf names ordered, never clear the pending model before conflict detection. Independent OCR and text leaf changes merge without group conflict. Add endpoint-raw four cases, away-and-back activation clearing nonsticky `_protocol_edited`, agreeing protocol updates, and `preserve_draft=False` equivalence to snapshot load with `()`.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_app_views.py -k 'rebase or baseline or adopt'`; coarse preserve-all must fail unedited-field adoption; a naive canonicalize-first merge must fail the cross-mode visible-leaf assertion. In disposable copies ignore raw pair or overwrite user-only fields; require named conflict/value assertions to fail.

- [ ] **Step 3: Implement deterministic logical merge before normalization.**

```python
order = ("api_base", "api_key", "endpoint", "is_split_model", "model", "ocr_model", "text_model")
def values(config):
    result = config.model_dump()
    result["endpoint"] = (config.endpoint, config.endpoint_raw)
    result.pop("endpoint_raw")
    return result
L, D, C = values(self._snapshot.config), values(self.get_current_draft()), values(snapshot.config)
merged, conflicts = {}, set()
for name in order:
    if D[name] == L[name]:
        merged[name] = C[name]
    elif C[name] == L[name] or D[name] == C[name]:
        merged[name] = D[name]
    else:
        merged[name] = D[name]
        conflicts.add(name)
cross = []
for leaf in ("model", "ocr_model", "text_model"):
    if (C["is_split_model"] != L["is_split_model"] and D[leaf] != L[leaf] and D[leaf] != C[leaf]) or (
        D["is_split_model"] != L["is_split_model"] and C[leaf] != L[leaf] and C[leaf] != D[leaf]):
        cross.append(leaf)
if cross:
    conflicts.update(("is_split_model", *cross))
    merged["is_split_model"] = D["is_split_model"]
    for leaf in ("model", "ocr_model", "text_model"):
        merged[leaf] = D[leaf]
endpoint, raw = merged.pop("endpoint")
merged.update(endpoint=endpoint, endpoint_raw=raw)
merged_config = AppAIConfig.model_validate(merged)
```

Capture L and D before installing C. Stage C's new snapshot/deep copies, display merged draft silently with `_display_draft`, update `_loaded_endpoint`/raw from C and raw selection from merged D, recompute `_protocol_edited` against C, preserve capability state, and return `tuple(name for name in order if name in conflicts)`. If there is no prior baseline, snapshot load and return `()`. With `preserve_draft=False`, load snapshot and return `()`. Failures restore loading guards and old view ownership for coordinator recovery; this method never emits a draft signal, writes bytes, probes, or silently clears an existing coordinator conflict.

- [ ] **Step 4: Run green.** Run `python -B -m pytest -q tests/test_app_views.py tests/test_mnemonic.py`; expect exit 0 with every merge case and mode conflict. Confirm absence of sticky flag or whole-tab-dirty shortcuts.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/ui/app_detail_view.py tests/test_app_views.py
git commit -m "feat(rebase): merge managed fields and retain visible model conflicts"
```

## Task 12: Reconcile path-valued dependent results from actual installed files

**Implementer tier:** Frontier

**Files:**

- Modify: `src/ai_manager/config/structured_models.py:86-92` — SaveResult.saved_dependents values become Path.
- Modify: `src/ai_manager/config/structured_config.py:344-427` — metadata-aware validation, sealed base-only render, publish canonical paths after commit.
- Modify: `src/ai_manager/ui/main_window.py:621-630` — `_reconcile_dependent_views` selected-dependent success loop only; preserve primary `_on_structured_saved` publication/restart/port/listener behavior at lines 632-650.
- Modify: `tests/test_structured_config.py:331-352` — assert canonical paths and normalized reread, not result config attributes.
- Modify: `tests/test_validator_orchestration.py:350-374` — preserve real orchestrated save with Path payload assertions.
- Modify: `tests/test_blast_radius.py:180-269` — append byte-ownership tests to dependent commit regressions.
- Modify: `tests/test_structured_main_window.py:1-620` — append real structured worker/dependent merge, failure and second-save cases; migrate result fixtures.
- Test: `tests/test_structured_config.py`
- Test: `tests/test_validator_orchestration.py`
- Test: `tests/test_blast_radius.py`
- Test: `tests/test_structured_main_window.py`

**Interfaces:**

- Consumes: `commit(kind: Literal["chat2api","file-bridge"], path: Path, doc: StructuredDoc, expected_sha256: bytes|None, *, dependents: tuple[DependentMatch,...]=()) -> SaveResult`; `DependentMatch(meta: AppMetadata, path: Path, doc: MutableMapping[str,Any], raw_bytes: bytes, raw_sha256: bytes, saved_config: AppAIConfig, old_api_base: str, new_api_base: str, auth_warning: str|None=None)`; `SaveResult(document: StructuredDoc, transaction: TransactionReport, validation: ValidationResult, saved_dependents=...)`.
- Consumes: `render_app_config(meta: AppMetadata, doc: CommentedMap, updater: Callable[[CommentedMap],None]) -> bytes`, `_config_from_document(doc: CommentedMap, meta: AppMetadata) -> AppAIConfig`, `read_app_config_snapshot(meta: AppMetadata) -> ConfigSnapshot(config: AppAIConfig, sha256: bytes, api_base_present: bool)`, frozen saved-config snapshots and typed load errors.
- Consumes view `adopt_saved_baseline(snapshot: ConfigSnapshot, *, preserve_draft: bool) -> tuple[str,...]`, `get_current_draft() -> AppAIConfig`, `set_recovery_state(*, load_failed: bool, conflicts: tuple[str,...]=(), message: str="", detail: str="") -> None`; coordinator stores from Task 9.
- Produces `SaveResult.saved_dependents: dict[str,Path]`: `match.path.parent.resolve() / match.path.name`, emitted only after successful transaction, never a bare AppAIConfig. Produces `_reconcile_dependent_views(self, saved_dependents: dict[str,Path]) -> None`: validate each path against registered metadata, re-read through that metadata, merge CURRENT widgets, install one coherent config/hash/presence, and store/retain ordered conflict names. Existing `_on_structured_saved(self, app_id: str, result: SaveResult) -> None` calls this helper after primary publication; retain its exact signature and worker signal shape.

- [ ] **Step 1: Test sealed bytes, path payloads and real second-save behavior first.** Migrate existing assertions that read `.saved_dependents[id].api_base` to canonical Path assertions and a metadata-aware snapshot read. Keep all stale/FIFO/rollback tests behaviorally identical. In blast-radius tests install different endpoint lines in selected fixtures: valid Messages with comment, invalid `/bad` with quote/comment, explicit YAML null, and unmanaged yt2txt `endpoint: [legacy, keep]`. Include anchors/formatting/absent model/base cases already supported by dependent discovery. Assert only selected `ai.api_base` changes, endpoint lines and unselected files byte-identical; spy `_apply_ai_config` and `write_app_config` to fail if called during structured commit. `_config_from_document` spy must receive exact `match.meta`.

```python
def test_dependent_result_paths_and_actual_snapshots(five_app_workspace, monkeypatch):
    import ai_manager.services.service_validation as validation
    monkeypatch.setattr(validation, "validate_candidate", lambda *a: ValidationResult("manager-only", "fixture"))
    apps = get_managed_apps(five_app_workspace)
    path = apps["chat2api"].relative_path / "config.json"
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    matches = find_affected_dependents(apps, before, after)
    result = sc.commit("chat2api", path, after, before.raw_sha256, dependents=matches)
    assert result.transaction.committed
    for match in matches:
        target = match.path.parent.resolve() / match.path.name
        assert result.saved_dependents[match.meta.id] == target
        assert isinstance(result.saved_dependents[match.meta.id], Path)
        observed = read_app_config_snapshot(match.meta)
        assert observed.config.api_base == "http://127.0.0.1:8123"
        assert observed.sha256 == hashlib.sha256(target.read_bytes()).digest()
        assert observed.config.endpoint == match.saved_config.endpoint
        assert observed.config.endpoint_raw == match.saved_config.endpoint_raw
```

In test_structured_main_window use its existing `window`, `port_draft` and `run_save(qtbot, window, monkeypatch, app_id="chat2api", draft=None, restart=False) -> None` helpers; fixture threadpool retains the StructuredSaveJob until explicitly run. Select only textkit via BlastRadiusDialog.selected_app_ids; patch service validation to manager-only. Set textkit to unified mode if needed, then begin the structured save, edit its `_model_combo` AFTER job creation, run the real captured job, and wait for callback. Assert base becomes the committed listener, pending model survives, snapshots hash actual bytes, and `_draft_configs` equals current widgets. Save textkit through the real LLM slot without reload and assert actual bytes keep the new base and new model with no false stale failure.

Add current-endpoint cases: external endpoint added in C with unedited D adopts it; user-only pending endpoint survives; agreeing edits clear intent; disagreeing edits block with `("endpoint",)`; mode/leaf cases assert complete conflict names and pending visible values. Turn combo away/back before completion and require adoption, not sticky conflict. Existing `_load_failed` or conflict flags cannot clear merely because a dependent result arrives.

Inject post-commit dependent read failure (delete or symlink its config, no creating reader) and wrong-path payload. Capture old dependent ownership before callback; require unchanged dependent triple/draft, disabled saves and Reload; primary structured snapshot/port/transaction remain successfully committed and primary success message must not claim rollback/failure. Spy reader to receive registered metadata and never the returned path as sole ownership authority. Add mixed success/failure among selected dependents; one failed reread must not suppress other coherent adoptions. Complete capability result while conflicted/failed; save controls and copy remain blocked.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_blast_radius.py tests/test_structured_config.py tests/test_structured_main_window.py`; expect Path/type/digest/second-save/value assertions to fail, not just annotations. In disposable copies return bare config, call creating reader, use worker-start draft, keep all old widgets when dirty, omit conflict flag, or call `_apply_ai_config` for dependent bases. Require the corresponding exact payload/no-create/current-widget/second-save/byte assertions to fail. Red evidence belongs to each mechanism; one failing import cannot stand in for the battery.

- [ ] **Step 3: Return canonical paths only after sealed base-only commit.**

```python
# structured_models.py
saved_dependents: dict[str, Path] = field(default_factory=dict)

# In structured_config.commit: retain captured raw tree and expected digest;
# this is the ONLY mutation for each selected dependent.
def update(tree, value=match.new_api_base):
    tree["ai"]["api_base"] = value
raw = _save_boundary(lambda: render_app_config(match.meta, match.doc, update))
parsed = _save_boundary(lambda: _get_yaml_engine().load(raw.decode("utf-8")))
_save_boundary(lambda: _config_from_document(parsed, match.meta))
dependent_paths[match.meta.id] = match.path.parent.resolve() / match.path.name
# Preserve scalar checks, sealed candidate validation, Transaction prepare/backups/
# stage/replace, and return only after the successful commit scope:
return SaveResult(baseline, report, validation, dependent_paths)
```

Rename dependent_baselines to dependent_paths; retain existing mapping/duplicate/digest checks. Do not reread inside commit to manufacture path payload configs, and do not alter endpoint during rendering. Existing metadata-aware `_config_from_document` from Task 3 remains required even though normalized configs are no longer returned.

- [ ] **Step 4: Re-read and rebase inside the selected-dependent success loop.**

```python
for dependent_id, reported_path in saved_dependents.items():
    if dependent_id not in self.apps or dependent_id not in self.views:
        continue
    meta = self.apps[dependent_id]
    registered = meta.relative_path / meta.config_file_name
    canonical = registered.parent.resolve() / registered.name
    try:
        if meta.config_kind != "llm" or not isinstance(reported_path, Path) or reported_path != canonical:
            raise ConfigLoadError(registered, "Dependent result path does not match the registered configuration path.")
        observed = read_app_config_snapshot(meta)
        saved_copy = observed.config.model_copy(deep=True)
        view = self.views[dependent_id]
        conflicts = view.adopt_saved_baseline(observed, preserve_draft=True)
        draft_copy = view.get_current_draft().model_copy(deep=True)
    except Exception as exc:
        self._load_failed[dependent_id] = True
        self.views[dependent_id].set_recovery_state(load_failed=True,
            conflicts=self._baseline_conflict.get(dependent_id, ()),
            message=str(exc), detail=getattr(exc, "detail", str(exc)))
        continue
    self._snapshots[dependent_id] = observed
    self._saved_configs[dependent_id], self._draft_configs[dependent_id] = saved_copy, draft_copy
    order = ("api_base", "api_key", "endpoint", "is_split_model", "model", "ocr_model", "text_model")
    conflict_set = set(self._baseline_conflict.get(dependent_id, ())) | set(conflicts)
    owned_conflicts = tuple(name for name in order if name in conflict_set)
    self._baseline_conflict[dependent_id] = owned_conflicts
    view.set_recovery_state(load_failed=self._load_failed.get(dependent_id, False),
        conflicts=owned_conflicts,
        message="Configuration changed while you were editing. Reload the configuration before saving." if owned_conflicts else "",
        detail="Conflicting fields: " + ", ".join(owned_conflicts) + "." if owned_conflicts else "")
    self._set_dirty_indicator(dependent_id)
```

Guard registry membership before lookup; invalid ids may be recorded in primary diagnostics but cannot create a fake view/snapshot or undo the committed primary. Retain previous view state until all per-dependent staging succeeds: if get_current_draft/deepcopy fails after adoption, restore the captured previous view baseline/current widgets under guards before marking reload required. `_load_failed` remains a block until explicit successful reload. If existing load failure has committed/stale copy, keep it instead of replacing it with empty availability text. Refresh auth after all successful adoptions. Primary publication occurs exactly once and survives dependent reread errors; no secondary LLM writer is called here. Unknown transaction states retain prior safeguards.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_blast_radius.py tests/test_structured_config.py tests/test_structured_main_window.py tests/test_validator_orchestration.py tests/test_transaction.py tests/test_endpoint_main_window.py`; expect exit 0. Literal/raw/unmanaged endpoint byte ownership, selected-only rewrites, stale dialog snapshots, nonregular paths, coherent second save and transaction rollback must all pass.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/config/structured_models.py src/ai_manager/config/structured_config.py src/ai_manager/ui/main_window.py tests/test_structured_config.py tests/test_validator_orchestration.py tests/test_blast_radius.py tests/test_structured_main_window.py
git commit -m "feat(reconcile): install observed dependent snapshots and rebase current drafts"
```

## Task 13: Apply typed presets and propagate the current endpoint through model discovery

**Implementer tier:** Capable

**Files:**

- Modify: `src/ai_manager/config/presets.py:1-41` — append Anthropic after all existing entries, add shared resolver.
- Modify: `src/ai_manager/ui/app_detail_view.py:102-137` — populate/filter presets using resolver, preserve protocol row.
- Modify: `src/ai_manager/ui/app_detail_view.py:243-301` — load-time matching uses base+optional pinned endpoint; preserve silent snapshot population/merge.
- Modify: `src/ai_manager/ui/app_detail_view.py:378-401` — current-draft fetch and shared idempotent preset application.
- Modify: `src/ai_manager/services/model_fetcher.py:35-54` — auth header branch only.
- Modify: `src/ai_manager/services/model_fetcher.py:105-117` — worker-owned complete request copy.
- Modify: `tests/test_model_fetcher.py:1-74` — extend HTTP header/discovery compatibility matrix.
- Modify: `tests/test_app_views.py:1-285` — append preset activation/matching/row/filter/signal and current-draft request tests.
- Modify: `tests/test_endpoint_main_window.py:1-1800` — append full view→coordinator→worker→HTTP and origin-routing case.
- Create: `tests/test_presets.py`
- Test: `tests/test_presets.py`
- Test: `tests/test_model_fetcher.py`
- Test: `tests/test_app_views.py`
- Test: `tests/test_endpoint_main_window.py`

**Interfaces:**

- Consumes: `ProviderPreset(id: str, name: str, api_base: str, default_key_env_var: str|None=None, endpoint: EndpointValue|None=None, docs_url: str|None=None, description: str="")`; canonical endpoint pair and `is_valid_endpoint(value: object) -> bool`.
- Consumes: `ModelFetchRequest(token: int, api_base: str, api_key: str, app_id: str, endpoint: str|None=None)` where app_id is required, strict and nonempty and endpoint is a transport hint; `ModelFetchResponse(token: int, success: bool, models: list[str]=[], error_message: str|None=None, endpoint_used: str|None=None)`; `resolve_api_key(raw: str) -> str|None`; existing `fetch_models_sync(request: ModelFetchRequest) -> ModelFetchResponse` and `ModelFetchWorker(request)` with `.request` and `.signals.finished`.
- Consumes: view `get_current_draft() -> AppAIConfig`, `_display_draft(draft: AppAIConfig) -> None` (silent); coordinator `_on_fetch_models(self, request: ModelFetchRequest) -> None`, origin-captured response route `_on_models_fetched(self, app_id: str, response: ModelFetchResponse) -> None` and independent view tokens. Preserve these existing route names and signal connections.
- Produces: `resolve_preset(preset_id: str, *, presets: Sequence[ProviderPreset]|None=None) -> ProviderPreset|None`, `AppDetailView._apply_preset(self, preset: ProviderPreset) -> None`, shared by both activated/currentIndexChanged; fetch request uses exactly one complete CURRENT draft and worker owns a full request copy including endpoint. No endpoint input to discovery URL composition.

- [ ] **Step 1: Test typed record, shared lookup, reactivation and HTTP before implementation.**

```python
# tests/test_presets.py
import pytest
from ai_manager.config.models import ProviderPreset
from ai_manager.config.presets import DEFAULT_PRESETS, resolve_preset

def test_anthropic_preset_is_appended_with_exact_contract():
    assert [p.id for p in DEFAULT_PRESETS] == ["one_api_local", "chat2api_local", "tencent_tokenhub", "openai_official", "custom", "anthropic_official"]
    p = resolve_preset("anthropic_official")
    assert (p.name, p.api_base, p.default_key_env_var, p.endpoint, p.docs_url, p.description) == (
        "Official Anthropic API", "https://api.anthropic.com", "ANTHROPIC_API_KEY", "/v1/messages",
        "https://docs.anthropic.com", "Claude models over the Anthropic Messages protocol")
    assert all(p.endpoint is None for p in DEFAULT_PRESETS[:-1])
    assert resolve_preset("missing") is None
    first = ProviderPreset(id="x", name="First", api_base="https://first")
    second = ProviderPreset(id="x", name="Second", api_base="https://second")
    assert resolve_preset("x", presets=[first, second]) is first
    assert resolve_preset("x", presets=[]) is None
    with pytest.raises(ValueError):
        ProviderPreset(id="bad", name="Bad", api_base="https://x", endpoint="/bad")

# Append HTTP cases to tests/test_model_fetcher.py.
@pytest.mark.parametrize("endpoint", [None, "/v1/chat/completions", "/v1/responses", "/v1/messages", "transport-only"])
@pytest.mark.parametrize("raw_key,resolved", [("literal", "literal"), ("$EP_UNSET_KEY", ""), ("", "")])
@respx.mock
def test_discovery_auth_preserves_urls(endpoint, raw_key, resolved, monkeypatch):
    monkeypatch.delenv("EP_UNSET_KEY", raising=False)
    first = respx.get("https://x/v1/models").mock(return_value=httpx.Response(404))
    fallback = respx.get("https://x/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "Z"}, {"id": "a"}, {"id": "Z"}]}))
    req = ModelFetchRequest(token=31, app_id="textkit", api_base="https://x/", api_key=raw_key, endpoint=endpoint)
    response = fetch_models_sync(req)
    assert response.success and response.token == 31
    assert response.endpoint_used == "https://x/models" and response.models == ["a", "Z"]
    for route in (first, fallback):
        headers = route.calls[0].request.headers
        assert headers["Accept"] == "application/json" and headers["User-Agent"] == "ai-manager/0.1.0"
        if endpoint == "/v1/messages":
            assert "authorization" not in headers
            assert headers["x-api-key"] == resolved
            assert headers["anthropic-version"] == "2023-06-01"
        else:
            assert "x-api-key" not in headers and "anthropic-version" not in headers
            assert headers.get("authorization") == ("Bearer " + resolved if resolved else None)
```

Add spies proving resolve_preset handles population/matching/application; unknown id/Custom change no fields; endpoint-free preset preserves raw invalid evidence and selected pair. With invalid raw loaded, select Anthropic: base/env/Messages/raw-cleared, exactly one final config_changed, no writer. Manually edit all pinned fields and emit activated for the already-selected index: all restored. Emit currentIndexChanged then activated and assert idempotent complete draft and at most one final dirty event. Simulate disabled Messages and apply programmatically: display draft may change, but the real save gate refuses unverified introduction; no preset writes.

Load Anthropic base with Messages and assert pinned match; same base with Responses must match Custom; yt2txt combo lacks only endpoint-bearing entries. Existing other preset ids/order stay intact and endpoint-free matching remains base-only.

Discovery cases preserve unauthorized/non-200/malformed JSON/connect/timeout/error strings, 10.0/5.0 httpx timeout and follow_redirects=True. Empty base remains `API Base URL cannot be empty.` even if preview has an omitted-base default. Existing URL behavior for base ending /v1 remains unchanged, including its historical doubled discovery segment. Test worker copies endpoint: mutate caller request after construction and assert worker uses captured Messages.

Full integration in test_endpoint_main_window: saved snapshot Chat, current combo Messages, provider base https://fixture/key literal; preserve pending complete draft and patch threadpool.start to capture ModelFetchWorker without running. Click `_fetch_btn`; capture request from the real signal and assert endpoint Messages/current base/key/app_id/token. Run captured worker under respx, process queued delivery, assert Messages headers, correct view models, unchanged saved snapshot/no disk write. Add equal tokens on different apps and reversed completions to prove captured origin route and view token filtering still work.

- [ ] **Step 2: Run red.** Run `python -B -m pytest -q tests/test_presets.py tests/test_app_views.py tests/test_model_fetcher.py tests/test_endpoint_main_window.py`; require final draft, resolver call-site, reactivation, request/transport/header assertions to fail with old behavior. Disposable mutants: saved endpoint in request, lost worker endpoint, Bearer Messages, changed discovery URL, base-only pinned matching, index-change-only activation, endpoint-free protocol reset, yt2txt Anthropic entry. Each must be killed by its corresponding full result assertion.

- [ ] **Step 3: Add exact preset/resolver and one complete application path.**

```python
# Append after the existing custom record.
ProviderPreset(
    id="anthropic_official",
    name="Official Anthropic API",
    api_base="https://api.anthropic.com",
    default_key_env_var="ANTHROPIC_API_KEY",
    endpoint="/v1/messages",
    docs_url="https://docs.anthropic.com",
    description="Claude models over the Anthropic Messages protocol",
)

# Also import Sequence from collections.abc.
def resolve_preset(preset_id: str, *, presets: Sequence[ProviderPreset] | None = None) -> ProviderPreset | None:
    offered = DEFAULT_PRESETS if presets is None else presets
    return next((preset for preset in offered if preset.id == preset_id), None)
```

Population iterates stable IDs, resolves once, skips pinned entries only when metadata flag false. Matching resolves item ids, compares `rstrip("/")` bases and additionally endpoint/raw validity for a pinned record; endpoint-free records never constrain endpoint. Application resolves the selected id and calls `_apply_preset`; custom/unknown return. Capture before draft, set base/key and (only when pinned) the literal, clear raw, recompute intent, and refresh under finally-cleared `_is_loading`/QSignalBlocker. Emit one final config_changed only when the complete canonical before/after drafts differ. Endpoint-free preserves `_protocol_edited`, raw and literal. Repeated index/activation calls cannot add multiple final events for an already-applied result. Do not reset the save/recovery state or perform I/O.

- [ ] **Step 4: Propagate one current draft and branch headers without changing discovery.**

```python
# _on_fetch_clicked
self._fetch_token += 1
draft = self.get_current_draft()
req = ModelFetchRequest(token=self._fetch_token, api_base=draft.api_base,
                       api_key=draft.api_key, endpoint=draft.endpoint,
                       app_id=self.app_meta.id)
self._fetch_status_label.setText("Fetching models from provider...")
self._fetch_status_label.setStyleSheet("font-size: 11px; color: #3b82f6;")
self.fetch_models_requested.emit(req)

# fetch_models_sync, after base header construction, with resolved_key existing:
if request.endpoint == "/v1/messages":
    headers["x-api-key"] = resolved_key or ""
    headers["anthropic-version"] = "2023-06-01"
elif resolved_key:
    headers["Authorization"] = f"Bearer {resolved_key}"

# ModelFetchWorker.__init__: keep signal construction and QRunnable setup.
self.request = ModelFetchRequest.model_validate(request.model_dump())
```

Retain all normalization/URL/error/timeout/redirect/token code and origin routing. Discovery neither composes the generation endpoint nor calls effective_api_base. Invalid raw maps to the canonical current endpoint None; discovery cannot clear that evidence or save. All fetch/status labels remain PlainText as set in Task 7.

- [ ] **Step 5: Run green.** Run `python -B -m pytest -q tests/test_presets.py tests/test_app_views.py tests/test_model_fetcher.py tests/test_endpoint_main_window.py tests/test_mnemonic.py`; expect exit 0. Confirm resolver has all three UI call sites and no independent ad hoc preset search remains outside it. No runtime dependency declaration changes.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/config/presets.py src/ai_manager/ui/app_detail_view.py src/ai_manager/services/model_fetcher.py tests/test_presets.py tests/test_model_fetcher.py tests/test_app_views.py tests/test_endpoint_main_window.py
git commit -m "feat(providers): apply typed presets and discover models with current protocol auth"
```

## Task 14: Document protocol scope and collect complete acceptance evidence

**Implementer tier:** Advanced

**Files:**

- Modify: `README.md:1-80` — add a short application/protocol subsection under Applications Managed; no dependency/version changes.
- Test: `tests/test_protocols.py`
- Test: `tests/test_protocol_capability.py`
- Test: `tests/test_models.py`
- Test: `tests/test_app_registry.py`
- Test: `tests/test_yaml_manager.py`
- Test: `tests/test_presets.py`
- Test: `tests/test_model_fetcher.py`
- Test: `tests/test_app_views.py`
- Test: `tests/test_endpoint_main_window.py`
- Test: `tests/test_blast_radius.py`
- Test: `tests/test_structured_main_window.py`
- Test: `tests/test_transaction.py`
- Test: `tests/test_supervisor.py`

**Interfaces:**

- Consumes completed public behavior: row on ai-grammar/textkit only, exact three literals, Auto means omitted key, per-literal installed-build capability, saved/removal exemptions, path-conflict refusal, typed recovery, shared Anthropic preset, model discovery auth. No new runtime API is produced.
- Consumes verification commands from spec §11.11 and per-mechanism red evidence from implementing tasks. Historical references ai-grammar `6f8c42d` and textkit `2.1.4` / `f0cc6ce` are verified baselines, never a capability shortcut or promise about all older/newer releases.
- Produces README application/protocol guidance and a final review response containing exact executed commands, exit codes/counts and meaningful red assertions. Do not add an extra tracking/audit file or change the controller-pinned plan to tick boxes.

- [ ] **Step 1: Run a documentation acceptance check before editing README.** This check is the task's failing example; it runs from integration root without starting the app or services.

```bash
python -B - <<'PY'
from pathlib import Path
text = Path("README.md").read_text()
for required in (
    "Upstream protocol", "ai-grammar", "textkit", "yt2txt",
    "/v1/chat/completions", "/v1/responses", "/v1/messages",
    "Auto omits", "6f8c42d", "2.1.4", "f0cc6ce",
    "https://api.openai.com", "https://api.openai.com/v1",
    "Sends Authorization: Bearer", "anthropic-version: 2023-06-01",
    "capability probe", "model discovery",
):
    assert required in text, f"Missing protocol guidance: {required}"
PY
```

Expected before edit: assertion naming missing protocol guidance. If already present, remove only the new subsection in a disposable copy and require that failure. This is a content check; it does not replace runtime acceptance.

- [ ] **Step 2: Add the following accurate short subsection in existing README style.**

```markdown
### Upstream protocol

ai-grammar and textkit expose an Upstream protocol selector: `/v1/chat/completions`
(OpenAI Chat Completions), `/v1/responses` (OpenAI Responses), and `/v1/messages`
(Anthropic Messages). Auto omits `ai.endpoint` and keeps that app's legacy behavior.
Null and empty endpoint values are invalid and require an explicit selection.
yt2txt continues to use its existing configuration without a protocol row;
chat2api and file-bridge retain their structured editors.

Explicit protocol paths already contain `/v1`: enter a gateway prefix such as
`https://api.openai.com`, not `https://api.openai.com/v1`. The request URL preview
shows the exact target. Conflicting bases are refused without automatic repair.
With no saved base, ai-grammar's Auto fallback is `https://api.openai.com/v1`;
textkit and explicit protocols use `https://api.openai.com`.

The capability probe checks the installed service's actual accepted literals.
A partial build enables its accepted protocols; an unverifiable build refuses
introducing or changing a protocol. You can keep a saved valid protocol or select
Auto to remove it. The documented historical support baseline is textkit `2.1.4` or newer
(`f0cc6ce` was verified), with ai-grammar verified at `6f8c42d`;
installed capability checking decides acceptance for every checkout.
Probing imports local service modules, so import side effects remain possible;
bytecode writes are disabled. A reload is required after stale/conflicted or
committed-but-unreconciled configuration outcomes.

OpenAI protocols use the “Sends Authorization: Bearer” authentication hint.
Messages uses `x-api-key` and `anthropic-version: 2023-06-01`; selecting the
Anthropic preset fills its base, environment key reference and Messages protocol.
The model discovery URLs remain `/v1/models` with `/models` fallback for every
protocol; Messages changes their authentication headers only.
```

Keep the existing launch/install/test instructions and dependency declarations intact. Explain “unavailable” using per-literal evidence and saved-item exemption if adding detail; do not claim all literals supported from a release number or all older builds unsupported.

- [ ] **Step 3: Re-run the exact content check, then run the spec's focused acceptance command.**

```bash
AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART=1 QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
  python -B -m pytest -q tests/test_protocols.py tests/test_protocol_capability.py \
  tests/test_models.py tests/test_app_registry.py tests/test_yaml_manager.py \
  tests/test_presets.py tests/test_model_fetcher.py tests/test_app_views.py \
  tests/test_endpoint_main_window.py tests/test_blast_radius.py tests/test_structured_main_window.py
```

Expected: exit 0, every listed module collected, no skipped real-seam acceptance case substituted by a helper-only check. Use the existing project environment. If dependency installation is needed during implementation, follow the checkout's development setup rather than inventing a Python floor or runtime dependency.

- [ ] **Step 4: Run the full suite once after focused checks pass.**

```bash
AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART=1 QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
  python -B -m pytest -q
```

Expected: exit 0 including Transaction cleanup/unknown and Supervisor FailedToStart no-finished regressions. Record command, exit and collected/pass counts. If a newly exposed defect requires a source change, report the exact owning interface/test to the controller instead of making undeclared production edits under this README-only task; completion requires the controller's normal repair/review path to resolve it.

- [ ] **Step 5: Check the completed changes against the spec's acceptance inventory.** `rg -n 'write_app_config\(|_config_from_document\(|read_app_config_snapshot\(|def _request_saved_restart|resolve_preset\(|endpoint=request|endpoint=draft' src tests` must show: one checked production LLM call, metadata at every normalization site, noncreating reload/reconcile, exactly one saved-restart definition, shared preset resolver and complete request propagation. Review recorded red assertions against §11.1–11.10: protocol URL/default matrix; model validation; exact byte/no-op/raw removal; execution/partition/redaction; full-content/cache overflow/generation/GUI; 12 UI cells; real gate and bypass substitution; two saves/stale/committed fault/cleanup primary; current-widget three-way rebase/second save; presets/full transport. Each mechanism needs a targeted falsification in its implementing task, not a blanket import failure or assumed helper coverage. Existing snapshots, rollback, nonregular path, origin routing, no-service-launch and plaintext tests must remain intact. Review code and assertions; do not rerun passed suites without a new change/failure.

- [ ] **Step 6: Commit the documentation and report evidence.**

```bash
git add README.md
git commit -m "docs: explain application protocol scope and capability checks"
```

The final implementation review response includes both successful acceptance commands, test counts, transaction/restart fault results and per-mechanism red assertion evidence; it does not claim that a historical version number proves capability.



