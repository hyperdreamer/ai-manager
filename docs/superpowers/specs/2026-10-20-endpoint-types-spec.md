# Endpoint types — technical specification

- Date: 2026-10-20
- Topic: `endpoint-types`
- Status: implementation-ready elaboration of the approved design, revision 7
- Design: `2026-10-20-endpoint-types-design.md` in this directory
- Normative visual reference: `mockups/endpoint_types_ui.png`
- Acceptance basis: `verification-endpoint-types.md` and design reviews 1–7 in this PM run's `reports` directory; review 4 is incomplete, and review 7 is the clean, zero-blocker pass.
- Verified upstream snapshots: ai-grammar `6f8c42d`; textkit `f0cc6ce`, release `2.1.4`.

This document specifies the implementation, not a claim that the implementation or its tests already exist. The approved design governs scope. The contracts below resolve its integration obligations without replacing capability verification with version guessing or weakening removal, preservation, or stale-write safeguards.

## 1. Scope and terminology

### 1.1 Scope

Add base-level upstream protocol selection to the existing LLM configuration editors for ai-grammar and textkit. Preserve legacy behavior when the key is absent, check installed-build acceptance before introducing or changing a protocol, show the actual request-URL composition, use the selected protocol's authentication shape for model discovery, and append the official Anthropic preset. Integrate these changes with existing saved/draft ownership, transactions, dependent rewrites, reloads, and restart completion.

Participating applications are exactly `ai-grammar` and `textkit`. `yt2txt` remains an LLM editor but owns no endpoint field. `chat2api` and `file-bridge` retain their structured adapters. No provider request, service start, port bind, or general LLM candidate validation is part of a protocol capability check.

### 1.2 Terms

- **Protocol**: one of the three exact endpoint literals in §2.1, including its authentication shape.
- **Auto / legacy**: `endpoint=None` in memory and no `ai.endpoint` key on disk. A present YAML null is not legacy.
- **Stored value**: the endpoint state in the currently installed saved snapshot, not the current combo selection.
- **Invalid raw value**: `repr()` of a present, unrecognized on-disk endpoint; it is display-only evidence, not a value to serialize.
- **Normalized configuration**: the canonical in-memory values in §2.2, independent of YAML spelling, quoting, comments, and omitted defaults.
- **Snapshot**: one coherent normalized configuration, SHA-256 of the bytes from which it was read, and the presence of `ai.api_base` in those bytes.
- **Loaded / committed / draft (`L`, `C`, `D`)**: the previous saved snapshot, newly committed or re-read snapshot, and current widget-derived pending configuration used by the three-way merge.
- **Accepted / rejected**: a literal verified by the target probe. Failure to run or authenticate the probe result is unknown, not a verified rejection.
- **No-op**: a permitted save whose normalized draft equals its saved baseline. It performs no rendering, transaction, backup, or configuration-file write, including when restart is requested.
- **Interface**: the types, invariants, ordering, errors, and side effects a caller must know. Internal helpers may vary, but the specified interfaces and observable outcomes must not.

`MUST`, `MUST NOT`, and `shall` are requirements. Where pseudocode is given, its decision order is normative; implementation syntax may differ.

## 2. Exact data contracts

### 2.1 Protocol vocabulary: `config/protocols.py`

```python
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

EndpointValue: TypeAlias = Literal[
    "/v1/chat/completions", "/v1/responses", "/v1/messages"
]
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
```

Order is fixed: Auto, Chat Completions, Responses, Messages. All persisted endpoint types reuse `EndpointValue`; do not duplicate three independently maintained unions. No aliases, full URLs, additional versions, case folding, or endpoint whitespace trimming are accepted.

`is_valid_endpoint(None)` is **False**: it recognizes explicit literals only. `None` is separately allowed as the in-memory legacy sentinel.

### 2.2 Pydantic models: `config/models.py`

The complete relevant field contracts are:

| Model | Field | Type | Default / requirement |
| --- | --- | --- | --- |
| `AppAIConfig` | `api_base` | `str` | `"http://127.0.0.1:3000"` |
| | `api_key` | `str` | `""` |
| | `model` | `str \| None` | `None` |
| | `is_split_model` | `bool` | `False` |
| | `ocr_model` | `str \| None` | `None` |
| | `text_model` | `str \| None` | `None` |
| | `endpoint` | `EndpointValue \| None` | `None` |
| | `endpoint_raw` | `str \| None` | `None`; display-only |
| `AppMetadata` | `id`, `display_name` | `str` | required |
| | `relative_path` | `Path` | required; application launch directory |
| | `config_file_name` | `str` | `"config.yaml"` |
| | `example_config_file_name` | `str` | `"config.example.yaml"` |
| | `default_port` | `int` | required |
| | `supports_split_models` | `bool` | `False` |
| | `supports_protocol_selection` | `bool` | `False` |
| | `description` | `str` | `""` |
| | `config_kind` | `Literal["llm", "chat2api", "file-bridge"]` | `"llm"` |
| `ProviderPreset` | `id`, `name`, `api_base` | `str` | required |
| | `default_key_env_var`, `docs_url` | `str \| None` | `None` |
| | `description` | `str` | `""` |
| | `endpoint` | `EndpointValue \| None` | `None`; applying this default leaves the protocol alone |
| `ModelFetchRequest` | `token` | `int` | required; monotonically increasing per view |
| | `api_base`, `api_key` | `str` | required |
| | `app_id` | `str` | required; existing `Field(strict=True, min_length=1)` |
| | `endpoint` | `str \| None` | `None`; transport hint, not persistence authority |

Retain existing unrelated model fields and their defaults. `ModelFetchResponse` remains `token: int`, `success: bool`, `models: list[str] = Field(default_factory=list)`, `error_message: str | None = None`, and `endpoint_used: str | None = None`.

#### Validators and canonical equality

1. Add `AppAIConfig` field validators that strip surrounding whitespace from string `api_base` and `api_key`, and normalize each string model field to `value.strip() or None`. `None` remains `None` for model fields. Do not coerce arbitrary non-strings in these validators; let Pydantic report the existing string-type error.
2. Canonical configurations carry only active model values: unified mode has `ocr_model=text_model=None`; split mode has `model=None`. An after-model validator enforces this invariant. Metadata-aware reader and view construction force unified mode when the application does not support split models.
3. The `endpoint` fields of `AppAIConfig` and `ProviderPreset` use native Pydantic literal validation. A non-`None` value outside the union raises `pydantic.ValidationError` with `literal_error` at `endpoint`. No validator turns `""`, padded strings, or a full URL into legacy or into a valid literal.
4. `endpoint_raw` is an optional string, not a second protocol input. The reader constructs `(endpoint=None, endpoint_raw=repr(raw))` for invalid values. Production drafts never carry a non-`None` endpoint together with a non-`None` raw value; the save gate nevertheless refuses any draft with raw evidence, regardless of its endpoint.
5. Preserve the existing before-field `AppMetadata.config_kind` validator: a non-exact string or an unregistered kind raises a Pydantic `value_error` whose message is `Unknown config_kind <repr>; expected llm, chat2api, or file-bridge.` Do not silently route an unknown kind to an LLM adapter.
6. Preserve existing `ModelFetchRequest.app_id` strictness. Missing, `None`, empty, and integer origins fail validation. Its endpoint deliberately remains optional `str`, because the fetcher uses it only to choose headers; this does not broaden `AppAIConfig` or preset persistence.
7. Do not add URL validation, key resolution, model existence checks, or upstream model-length constraints to `AppAIConfig`. This is normalization, not a new LLM service validator.

Pydantic `model_construct()` and unchecked `model_copy(update=...)` can bypass validation. That is why gate rule 2 remains mandatory. Perform that assertion before attempting to revalidate a forged draft. For valid inputs, dirty comparison, diff application, and no-op detection use the canonical values above; UI blanks therefore equal reader `None` values.

`get_display_model()` retains its current results: unified model or `"none"`; split `"OCR: <model-or-none> | Text: <model-or-none>"`.

### 2.3 Snapshots

Place the record in `config/models.py`:

```python
@dataclass(frozen=True)
class ConfigSnapshot:
    config: AppAIConfig
    sha256: bytes
    api_base_present: bool
```

All three fields are required. `sha256` is the 32-byte binary result of `hashlib.sha256(raw).digest()`, never hexadecimal text. In `__post_init__`, reject a non-`AppAIConfig` config with `ValueError("Snapshot config must be an AppAIConfig.")`, an incorrectly typed or non-32-byte digest with `ValueError("Snapshot digest must be a 32-byte SHA-256 value.")`, and a presence value whose exact type is not bool with `ValueError("Snapshot base presence must be a boolean.")`. The frozen record takes a deep copy of its configuration; consumers must not mutate that configuration in place. Make separate deep copies for editable drafts and legacy `_saved_configs` storage.

`api_base_present` is true if and only if the parsed base `ai` mapping contains the key, even if its stored value is empty or null. It does not mean that the normalized value differs from the manager placeholder. The reader's config and presence flag are derived from the same bytes whose hash is returned.

### 2.4 Capability records: `services/protocol_capability.py`

```python
class ProtocolSupportStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"

@dataclass(frozen=True)
class ProtocolSupport:
    status: ProtocolSupportStatus
    accepted: frozenset[str] = frozenset()
    detail: str = ""
```

Invariants: `accepted` is a subset of `ENDPOINT_VALUES`; `SUPPORTED` means equality with that set; `PARTIAL` means one or two members; `UNSUPPORTED` and `UNVERIFIABLE` both have an empty set, but only the former is a verified rejection of all three. Producers validate these invariants and never publish inconsistent records. All diagnostic text is passed through existing `launcher_gate.redact_diagnostics()` before being put in `detail`, cached, or displayed.

### 2.5 Gate result and coordinator ownership

```python
@dataclass(frozen=True)
class LLMGateResult:
    refused: bool = False
    no_op: bool = False
    message: str = ""
    detail: str = ""
```

`refused` and `no_op` cannot both be true. An allowed write has both false. This record does not authorize bypassing the checked writer.

Add these `MainWindow` stores without changing structured-document ownership:

| Store | Type / meaning |
| --- | --- |
| `_snapshots` | `dict[str, ConfigSnapshot]`, LLM saved snapshots only |
| `_load_failed` | `dict[str, bool]`; also the reload-required block after an LLM stale error |
| `_baseline_conflict` | `dict[str, tuple[str, ...]]`; empty tuple is clear; names follow §8.3 |
| `_protocol_probe_tokens` | `dict[str, int]`, monotonically increasing per app |
| `_protocol_probe_jobs` | `dict[tuple[str, int], ProtocolProbeJob]`; separate from launcher jobs |
| `_protocol_support` | `dict[str, ProtocolSupport]`, latest applicable UI result; not a substitute for a fresh keyed capability lookup at gate rule 7 |

For LLM apps, `_saved_configs[app_id]` equals a deep copy of `_snapshots[app_id].config`. Install or retain the configuration, digest, and presence flag together, in one GUI-thread operation. A refusal, failed read, failed write, or stale error must not advance any part of that triple.

### 2.6 Dependent-save payload

Choose paths, not bare configurations, for the design's allowed dependent result form:

```python
@dataclass(frozen=True)
class SaveResult:
    document: StructuredDoc
    transaction: TransactionReport
    validation: ValidationResult
    saved_dependents: dict[str, Path] = field(default_factory=dict)
```

Each value is the canonical rewritten configuration path for its key's application, included only after the shared transaction commits. `DependentMatch` retains its existing fields, including `meta`, captured document, bytes, digest, and `saved_config`. The latter remains useful for inspection and warnings; it is not sufficient to publish a new saved baseline after a rewrite.

## 3. Protocol and URL function contracts

### 3.1 Explicit-literal predicate

```python
def is_valid_endpoint(value: object) -> bool:
    return isinstance(value, str) and value in ENDPOINT_VALUES
```

Pure and total for any object. False for `None`, integers, booleans, collections, empty strings, `/v1/completions`, `/v1/other`, aliases, full URLs, and strings with padding.

### 3.2 Request URL composition

```python
def compose_request_url(app_id: str, api_base: str, endpoint: str | None) -> str:
    raw = api_base.strip()
    if endpoint is not None:
        return raw.rstrip("/") + endpoint
    if app_id == "ai-grammar":
        base = raw if raw.rstrip("/").endswith("/v1") else raw.rstrip("/") + "/v1"
        return base + "/chat/completions"
    return raw.rstrip("/") + "/v1/chat/completions"
```

This is display-only string composition: no network, YAML mutation, path normalization, or URL repair. Its endpoint precondition is `None` or a valid literal. The fallback legacy branch is textkit's rule; production callers show this line only for participating apps. Invalid raw endpoints do not call this function. Partially typed string bases are still composed as strings and do not trigger URL parsing here.

Exact examples, applicable to both participating apps in explicit mode:

| Base | Endpoint | Request URL |
| --- | --- | --- |
| `https://x` | `/v1/messages` | `https://x/v1/messages` |
| `https://x/` | `/v1/messages` | `https://x/v1/messages` |
| `https://x/gateway/` | `/v1/responses` | `https://x/gateway/v1/responses` |
| `https://x/v1` | `/v1/messages` | `https://x/v1/v1/messages` |
| `https://x/v1/` | `/v1/chat/completions` | `https://x/v1/v1/chat/completions` |

The doubled explicit path is displayed, not silently corrected; the gate refuses it.

| App | Legacy base | Request URL |
| --- | --- | --- |
| ai-grammar | `https://x` | `https://x/v1/chat/completions` |
| ai-grammar | `https://x/v1` | `https://x/v1/chat/completions` |
| ai-grammar | `https://x/v1/` | `https://x/v1//chat/completions` |
| textkit | `https://x` | `https://x/v1/chat/completions` |
| textkit | `https://x/v1` | `https://x/v1/v1/chat/completions` |
| textkit | `https://x/v1/` | `https://x/v1/v1/chat/completions` |

Preserving ai-grammar's trailing-slash quirk is required; correcting it would misrepresent the target.

### 3.3 Base/protocol conflict predicate

```python
def base_conflicts_with_endpoint(api_base: str, endpoint: str | None) -> bool:
    if endpoint is None:
        return False
    try:
        path = urlsplit(api_base.strip()).path
    except ValueError:
        return False
    return path.rstrip("/").endswith("/v1")
```

Pure, non-throwing for every string the base editor can contain. Inspect the path only, case-sensitively. A host `v1.example.com`, a query value `/v1`, or a fragment `/v1` does not conflict. `/v1`, `/v1/`, and `/gateway/v1///` paths conflict in explicit mode. `/v10` and `/V1` do not. `https://[` and `https://[::1` return false and recover correctly when completed. This predicate is not a general URL validator.

### 3.4 Effective omitted base

Use one shared pure helper in `config/protocols.py`, with type-only imports to avoid a models/protocols import cycle:

```python
def effective_api_base(app_id: str, draft: AppAIConfig, snapshot: ConfigSnapshot) -> str:
    if snapshot.api_base_present or draft.api_base != snapshot.config.api_base:
        return draft.api_base
    if app_id == "ai-grammar" and draft.endpoint is None:
        return "https://api.openai.com/v1"
    return "https://api.openai.com"
```

Inputs are canonical configurations. Both the view's Request URL and gate rule 4 use this helper. A pending edit to an originally omitted base uses the edited value immediately. Reverting that edit to its loaded placeholder reverts to omission semantics. A protocol-only change in an omitted-base ai-grammar file uses the explicit-mode root default, not the legacy default ending in `/v1`.

This helper does not change what the base widget stores, materialize a key, or alter the model-discovery base selection specified in §9. Only omission invokes target defaults; an explicitly present invalid base is not repaired by this feature.

## 4. YAML reader, renderer, and writer interfaces

### 4.1 Metadata-aware normalization

```python
def _config_from_document(doc: MutableMapping[str, Any], meta: AppMetadata) -> AppAIConfig
```

Pure; call `require_llm(meta)` and never read or write a file. A missing or null `ai` value is treated as an empty mapping for normalization; any other non-mapping `ai` value is a shape error, not a default configuration. A non-mapping document root is also a shape error. Direct helper calls raise `ValueError("Configuration root must be a mapping; save is disabled.")` or `ValueError("AI must be a mapping when present; save is disabled.")` for these two cases. File-aware callers check the same conditions before calling the helper and raise `ConfigShapeError(path, message, reason)` with that exact message: root reason `non-dict-root`, AI reason `load-error`. Other normalization failures remain load errors rather than being mislabeled as shape failures.

Keep the existing scalar-reading conventions before canonical normalization: base is `str(ai.get("api_base") or "http://127.0.0.1:3000")`, key is `str(ai.get("api_key") or "")`, and a falsey model value becomes `None`, otherwise `str(value)`. This does not authorize writing these defaults back.

Split classification is `meta.supports_split_models` **and** at least one `ai.ocr` / `ai.text` mapping being present. This retains the existing textkit interpretation, including provider-only mappings, but ai-grammar or yt2txt nested mappings cannot accidentally turn their editor into split mode. In split mode, read `ocr.model` and `text.model` and set the normalized base model to `None`; the actual base model in the document remains untouched unless a later explicit mode toggle removes it. In unified mode, read the base model and set both split model fields to `None`.

Endpoint normalization is based on key presence, not `get()` truthiness:

| Application ownership | On-disk `ai.endpoint` | `endpoint` | `endpoint_raw` |
| --- | --- | --- | --- |
| participating | absent | `None` | `None` |
| participating | any exact literal | same literal | `None` |
| participating | `null` | `None` | `"None"` |
| participating | `""` | `None` | `"''"` |
| participating | `"/v1/completions"` | `None` | `"'/v1/completions'"` |
| participating | integer `42` | `None` | `"42"` |
| participating | boolean `true` | `None` | `"True"` |
| participating | any other value | `None` | Python `repr(value)` |
| nonparticipating LLM app | any state | `None` | `None` |

Do not send an invalid disk value through Pydantic's endpoint literal field and thereby fail the entire read. Do not resolve `$ENV_VAR` keys during reading.

### 4.2 Snapshot and compatibility readers

```python
def read_app_config_snapshot(app_meta: AppMetadata) -> ConfigSnapshot
def read_app_config(app_meta: AppMetadata) -> AppAIConfig
```

`read_app_config_snapshot` is a non-creating read. It calls `require_llm`, obtains one regular-file byte snapshot through the existing `_snapshot` primitive, decodes UTF-8, parses using the existing ruamel round-trip settings, checks the root/AI shape, passes metadata to `_config_from_document`, and returns config, hash, and presence from those same bytes. Ignore the primitive's non-writable reason for a successful read: read-only configurations must still load and allow no-op saves. Missing bytes raise `ConfigLoadError(path, "Configuration file is missing.")`. Symlinks and non-regular leaves retain their existing typed load refusals; never open a FIFO.

An empty or comments-only document becomes an empty `CommentedMap`. An explicit scalar/list root, including an explicit YAML null document, is not silently changed into a mapping. If round-trip `load()` returns None, distinguish empty input from a null scalar by composing the same already-read text: no root node means empty; a scalar root node means a shape error. Do not use truthiness to classify roots or perform a second file read. Keep duplicate-key rejection. Wrap decoding, parsing, normalization, and deep-copy failures as `ConfigLoadError`; preserve existing `ConfigError` subclasses and include the real path. Never manufacture a successful default snapshot after an exception.

For compatibility, `read_app_config` retains the existing `ensure_config_exists(app_meta)` step, then returns a deep copy of `read_app_config_snapshot(app_meta).config`. Initial LLM loading in `MainWindow` likewise performs the existing ensure-from-example step once before its snapshot read. Reloads, reconciliation, stale handling, blast-radius inspection, and checked saves do **not** create missing files or copy examples. `ensure_config_exists` itself retains its existing public behavior; this feature adds no new create-from-example UI for LLM apps.

Every `_config_from_document` caller passes metadata: compatibility reader, snapshot reader, `find_affected_dependents`, and the dependent-render branch of `structured_config.commit`. There is no shape-based inference of endpoint ownership.

### 4.3 Pure rendering

The existing interface is unchanged:

```python
def render_app_config(
    meta: AppMetadata,
    doc: MutableMapping[str, Any],
    mutate: Callable[[MutableMapping[str, Any]], None],
) -> bytes
```

Require LLM metadata, deep-copy the input tree, invoke the mutator once on the copy, and serialize UTF-8 using `YAML(typ="rt")`, `preserve_quotes=True`, mapping indent 2, sequence indent 4, offset 2, and width 4096. The caller's tree and disk remain unchanged. Rendering does not create backups, hash files, probe capabilities, or commit bytes. No-op UI saves do not call it.

### 4.4 Diff application

```python
def _apply_ai_config(
    meta: AppMetadata,
    doc: MutableMapping[str, Any],
    new_config: AppAIConfig,
    baseline: AppAIConfig,
) -> None
```

This mutates only the supplied candidate tree. Both configs are canonical. Require LLM metadata. Refuse a participating draft with `endpoint_raw is not None` using `ValueError("Invalid ai.endpoint must be explicitly repaired before saving.")`, rather than silently treating it as an Auto repair. Defensively reject an invalid non-`None` endpoint, even for unchecked test callers, with `ValueError(f"Unsupported ai.endpoint value: {new_config.endpoint!r}.")`. Run these assertions before any direct-writer no-op return as well. The writer does not run the capability probe; the one production caller must pass the gate first.

Create `ai` lazily only when an actual insertion or intentional structural toggle requires it. A removal from an absent mapping does not create `ai: {}`. Existing managed-key order is retained; newly inserted keys follow the application order below and are appended at their mapping's end. Do not delete and reinsert unchanged keys.

| Field / action | Exact mutation condition and result |
| --- | --- |
| `api_base` | If different from baseline, set `ai.api_base` to the draft string. Otherwise do not assign it. No implicit slash removal or default insertion. |
| `api_key` | If different from baseline, set `ai.api_key` to the draft string. Otherwise do not assign it or resolve the reference. |
| `endpoint`, flag false | Never set or pop the document key, irrespective of an existing hand-written value. |
| `endpoint`, flag true | Only when endpoint differs **or** `baseline.endpoint_raw is not None`: draft `None` pops the key; a literal sets that exact string. No `null`, empty string, or `endpoint_raw` key is emitted. |
| unchanged unified mode | Change only the base `model` when its canonical value differs; `None` pops it. Do not remove nested mappings. |
| unchanged split mode | Change only differing `ocr.model` / `text.model` leaves; `None` pops the leaf. Preserve each mapping and all provider-only keys, including when its last model leaf is removed. |
| unified → split | Explicit destructive mode switch: pop the base `model`, ensure OCR and text mappings exist, and set/remove their model leaves from the draft. Existing provider keys in surviving split mappings remain. Empty mappings may represent intentionally selected split mode. |
| split → unified | Explicit destructive mode switch: pop whole `ocr` and `text` sections, including provider overrides, then set/remove the base `model` from the draft. |

For an ordinary save, process differing base, key, endpoint, then model leaves. A mode toggle applies its structural mutations even when an active new model value equals an inactive baseline `None`. No other save is allowed to perform the toggle's destructive cleanup. For metadata without split support, the view and reader supply unified configs; unrelated nested fields remain unmanaged and untouched.

### 4.5 Single LLM commit point

```python
def write_app_config(
    app_meta: AppMetadata,
    new_config: AppAIConfig,
    *,
    baseline: AppAIConfig,
    expected_sha256: bytes | None = None,
) -> bytes
```

`baseline` is required and keyword-only. The return value is the 32-byte SHA-256 of the exact installed candidate bytes, not of `model_dump()` and not of a separately rendered approximation. Update every existing test invocation and both current rendering branches to supply the baseline. No production LLM save may omit the expected digest.

#### Checked production branch: expected digest supplied

1. Require a 32-byte `bytes` digest. Snapshot the existing path without ensuring/copying a config. If missing, raise `StaleDocumentError(path, expected, None)`.
2. Hash the read bytes before parsing. A mismatch raises `StaleDocumentError(path, expected, actual)` before rendering or creating a backup. Thus an externally added endpoint survives an unrelated pending save.
3. Parse and normalize safely; use the original document tree, the passed baseline, and `_apply_ai_config` through `render_app_config` to seal candidate bytes entirely in memory.
4. Use the existing `Transaction` in order: `prepare([path], {path: expected})`, `backups()`, `stage({path: rendered})`, `replace_all()`. `prepare` must still recheck the loaded digest under the sidecar lock; do not replace the expected hash with a newly observed hash.
5. `replace_all()` returning is **the commit point**. Immediately record `installed = sha256(rendered).digest()`. On a clean context exit, return `installed`. There is no candidate validation subprocess for LLM saves and no silent stale retry.
6. **Post-commit cleanup failure.** `Transaction.__exit__` can raise from sidecar unlock/close *after* `replace_all()` installed the bytes. The writer must not report that as an ordinary save failure. It raises `CommittedWriteError(path, installed, report, cause)` (a `ConfigError`) carrying the digest of the bytes on disk and the transaction report. Cleanup never rewrites or removes the installed file. The coordinator treats this as *committed with recovery required* (§6.2 step 6).
7. **Primary-error preservation.** When the body is already raising (for example `TransactionError` whose report says `unknown`), a cleanup failure during unwinding must not replace it. `Transaction.__exit__` re-raises the primary error and exposes the cleanup failure as its `__cause__`/note. The primary report — restored versus unknown — stays authoritative.

Keep the existing transaction's canonical-path, symlink, regular-file, writeability, sorted-lock, mode, fsync, backup, temporary-file, rollback, and report behavior. Successful checked writes create one distinct `config.yaml.<UTC timestamp>.<pid>-<six hex>.bak`; the timestamp format is `%Y%m%dT%H%M%S%fZ`. The backup contains the exact pre-commit bytes and permission mode. Stage files use the existing same-directory private temporary naming. A `.lock` sidecar may remain; it is not a backup or a config mutation. Do not replace this path with the legacy fixed backup path.

#### Compatibility branch: expected digest omitted

Retain this branch for existing direct writer tests/callers, not the MainWindow LLM path. Preserve the existing `ensure_config_exists` behavior, fixed `config.yaml.bak` copy with `copy2`, same-directory `config.yaml.tmp.<pid>_<six hex>` candidate, flush/fsync, mode copying, atomic `os.replace`, and best-effort temporary cleanup. Both branches use the same diff mutator and return the installed bytes' digest. This optional argument is not permission for UI code to weaken stale protection.

#### No-op and errors

The GUI gate skips the writer for no-ops. Also avoid backup/replacement in direct writer calls when canonical configs are equal and there is no raw repair to perform: return the hash of the unchanged read bytes. In a checked direct call, perform the stale comparison first. Never mistake an uncleared invalid raw value for a no-op.

Pass through typed `ConfigError` subclasses. Translate unowned local I/O, Unicode, YAML, type, and value failures at the save seam into `ConfigError("Configuration save failed: <detail>")`, as existing structured saves do. Do not swallow a `StaleDocumentError`. On any exception raised **before the `replace_all()` commit point**, the coordinator retains its old snapshot; `CommittedWriteError` is the sole exception and installs the committed snapshot (§6.2 step 6), because the bytes are already on disk. A transaction rollback may report `unknown` file state, so do not promise that every transaction failure left disk unchanged. That state requires reload before another LLM save.

## 5. Capability probe protocol

### 5.1 Eligibility and public interfaces

```python
def probe_protocol_support(meta: AppMetadata, *, use_cache: bool = True) -> ProtocolSupport
def invalidate_protocol_support(app_id: str) -> None
def protocol_support_generation(app_id: str) -> int
```

`protocol_support_generation` returns the current integer generation under the cache mutex, or zero for an unseen id, without incrementing, probing, or updating a view. It is the explicit integration seam for capturing and checking generations; callers do not access the service's private dictionaries.

`probe_protocol_support` returns a result, not an exception, for interpreter-resolution, filesystem, spawn, import, protocol-format, and timeout failures. It performs no operation for metadata with `supports_protocol_selection=False`, returning `UNSUPPORTED` with empty acceptance and detail `Protocol selection is not available for this application.` If the flag is true but no program exists for its id, return `UNVERIFIABLE` with detail `No protocol probe is defined for <app_id>.` Never guess from fields or release strings.

Use `resolve_app_interpreter(meta.relative_path)` only; do not call the separate structured interpreter import-verification function. Preserve its lexical virtualenv interpreter path, including symlinks. Selection precedence remains `.venv/bin/activate`, `venv/bin/activate`, then `python` on PATH. A selected broken virtualenv does not fall back to a different environment.

For an uncached eligible invocation:

| Property | Exact value |
| --- | --- |
| executable / argv | `[str(interpreter), "-B", "-c", program, nonce]` |
| working directory | `meta.relative_path.resolve()`; ai-grammar/backend or textkit/backend |
| shell | `False` |
| environment | copy inherited environment, overriding `PYTHONDONTWRITEBYTECODE` with string `"1"` |
| nonce | fresh `secrets.token_hex(16)`, 32 lowercase hex characters, per subprocess |
| streams | capture stdout and stderr separately; UTF-8 with replacement decoding |
| timeout | `5.0` seconds for child execution/communication |
| accepted success | exit 0 **and** validated, matching final sentinel payload |

Use captured-process execution with timeout cleanup that kills and reaps the direct child, including the timeout path. Do not start the service, pass real API keys in argv, mutate `config.yaml`, create candidate files, open sockets, or invoke a loader that demands a real key. A source scan and process creation are outside the subprocess timeout; this is not a hard five-second bound on all filesystem work or descendant processes.

### 5.2 Normative ai-grammar child program

The following checks `_resolve_endpoint`, which is the loader's membership guard and validator, rather than constructing its loosely typed dataclass:

```python
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
```

A `RuntimeError` for an individual value is a verified rejection. Other unexpected exceptions terminate without a valid success result and are unverifiable. Import-time `SystemExit(0)` cannot produce this program's sentinel. No dataclass-field-presence shortcut is permitted.

### 5.3 Normative textkit child program

The loader's module-level guard and the model validator must both accept each value:

```python
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
```

The harmless fixed strings above are probe data, not a real provider request. A model that accepts Responses while `SUPPORTED_ENDPOINTS` rejects it must report Responses as rejected. Missing or structurally unusable symbols are an unverifiable interface, not evidence of zero protocol support. Exceptions from an otherwise available per-value validator count as rejection as in the approved design. A `SystemExit` or other `BaseException` does not get reclassified as a per-literal rejection.

Neither program tests an explicit `None`: the manager's serializer cannot emit that state. Neither program calls a service's full config loader or adapter network method.

### 5.4 Sentinel grammar and validation

The final nonempty stdout line must be:

```text
PROBE_RESULT:<the exact per-call nonce>:<JSON object>
```

Earlier non-sentinel import banners may be ignored. Require exactly one line with this call's matching sentinel prefix and require it to be the final nonempty line. Do not strip a leading prefix, accept a stale nonce, infer success from a substring, or accept bare JSON. An earlier matching sentinel plus another closing matching sentinel is malformed, not success.

The JSON object must have exactly two keys, `accepted` and `rejected`. Each value must be a list of strings, with no duplicates, containing only `ENDPOINT_VALUES`. The lists must be disjoint and their union must equal all three values. Reject missing values, unknown values, wrong types, duplicate JSON object keys, trailing non-whitespace data, overlapping lists, or additional object keys. Ordering of list members does not affect membership; the supplied child programs emit protocol-table order.

Exit 0 plus a valid partition maps as follows:

| Accepted set size | Status | Accepted field |
| --- | --- | --- |
| 3 | `SUPPORTED` | all three |
| 1 or 2 | `PARTIAL` | precisely the verified subset |
| 0 | `UNSUPPORTED` | empty |

Every nonzero exit, including 75, a timeout, a spawn failure, a missing/wrong/duplicate/malformed sentinel, and a failed source/interpreter scan maps to `UNVERIFIABLE`, **always with an empty accepted set**, even if stdout contains a plausible payload. There is no reuse of a previous supported result after such a failure.

For a successful partition, `detail` may contain redacted nonempty stderr; it does not change the status. For failure, construct a reason from §10.3 and append captured stdout/stderr in labelled sections when present, then call `redact_diagnostics` on the entire detail. Never display unredacted child diagnostics through another field or exception. Preserve useful failure context without treating module output as UI markup.

### 5.5 Cache fingerprint and overflow

The in-process cache key is exactly:

```python
(app_id, str(interpreter), interpreter.stat().st_mtime_ns, source_fingerprint(app_dir))
```

Use the interpreter's absolute lexical path in the key, not `Path.resolve()` on the executable. `app_dir` is the resolved launch directory. Source enumeration recursively visits regular `*.py` files, excluding directories named `__pycache__`, `.venv`, or `venv`, and any other directory identified as a virtualenv by its `pyvenv.cfg`. Do not follow directory symlinks. Include Python-file symlink target bytes only when the leaf resolves to a regular file. A failed required stat/read/enumeration is unverifiable and not cached.

The internal `source_fingerprint(app_dir: Path)` returns either `("full", digest_bytes)` or `("coarse", count, newest_file_mtime_ns, app_dir_mtime_ns)`; these tagged tuples are the fingerprint element of the key. For at most 200 source files, sort by relative POSIX path. Compute the full digest using SHA-256 over this unambiguous stream:

```text
for each file, in sorted order:
    UTF-8 relative path, NUL, ASCII hex SHA-256(file bytes), LF
```

Use the resulting 32-byte digest in the full tuple. Hash file **contents**, not just size and mtime; replacing source with equal-size bytes and restoring the old mtime must invalidate acceptance. Read no target configuration, credential, `.env`, or non-Python file contents for this key; virtualenv exclusion needs only the existence/type of `pyvenv.cfg`.

For **more than 200 files**, return the coarse tuple above, with `newest_file_mtime_ns` the maximum over the source set. In overflow mode, skip both cache lookup and cache insertion on every invocation, even if an older full entry exists for the app. A threshold of exactly 200 still uses full hashing and may cache. Coarse fingerprints are never authority for a cached `SUPPORTED` result.

`use_cache=False` bypasses both lookup and insertion, but still uses the interpreter resolver, source scan, nonce, timeout, and generation safeguards. A validly keyed `UNVERIFIABLE` result may be cached just like other results; restart invalidation or a changed key permits recovery. Failures before a complete key exists are not cached.

For an uncached result, recompute the key's interpreter/source identity before cache publication. If it changed while probing, return empty-accepted `UNVERIFIABLE` with the superseded detail in §10.3 and do not cache the answer. This does not claim atomicity with a later external checkout change.

### 5.6 Generations and probe-job interface

Maintain a process-local monotonically increasing integer generation per app, initially 0. Access the generation and cache dictionaries under a short mutex. Do not hold that mutex during scanning, subprocess execution, waiting, or a GUI call.

`invalidate_protocol_support(app_id)` increments the generation and removes all cache entries for that id, in the same critical section. No subprocess or widget is invoked by invalidation itself.

A public synchronous probe captures the generation before starting its work and delegates to this internal worker-facing interface:

```python
def _probe_protocol_support_at_generation(
    meta: AppMetadata, *, generation: int, use_cache: bool = True
) -> ProtocolSupport
```

It has the same result/error/side-effect contracts as the public probe, but uses the supplied captured generation rather than recapturing at worker start. If that generation is already old when a queued job starts, return a superseded unknown result without spawning. Check generation under the mutex before returning any cache hit as well as before inserting/returning an uncached answer. An obsolete call returns an unverifiable result with empty acceptance, not the old success.

Add to `services/config_jobs.py`:

```python
class ProtocolProbeJob(QRunnable):
    def __init__(self, meta: AppMetadata, token: int, generation: int) -> None: ...
    def run(self) -> None: ...
```

The job owns a deep metadata copy, its immutable token and generation, and its own `ConfigJobSignals`. It emits exactly one `probe_finished(app_id, ProtocolSupport)` terminal signal. Unexpected worker exceptions are converted to redacted unverifiable results. It never touches widgets or opens a dialog. The existing signal's object payload supports both launcher and protocol records; keep their coordinator slots and job maps distinct.

At startup, create one job per participating app after view construction. Add `_start_protocol_probe(self, app_id: str) -> None` to increment that app's token, capture `protocol_support_generation(app_id)`, own the `(app_id, token)` job, and start it on the existing thread pool. Bind those immutable values to a `Qt.ConnectionType.QueuedConnection` delivered in the MainWindow's GUI-thread context. Add `_on_protocol_probe_finished(self, app_id: str, token: int, generation: int, support: ProtocolSupport) -> None`: it removes only the matching `(app_id, token)` owned job and applies the result only when the app still exists, its protocol-selection flag is still true, the token is current, and `protocol_support_generation(app_id)` still matches. A stale completion must not pop a newer job or overwrite newer availability/details. A QObject-bound forwarding slot may carry the immutable connection context; an unverified worker-thread lambda is not sufficient.

On **every terminal per-service restart attempt** for a participating app, saved-restart or manual, success or failure, invalidate once and start one fresh token-checked job. Hook terminal completion, not command dispatch and not status polling. Terminal means exactly one of `QProcess.finished` or `errorOccurred(QProcess.ProcessError.FailedToStart)`: the existing supervisor connects only `finished`, so a missing or non-executable launcher currently produces no completion at all and would leave saved-restart pending state stuck and capability stale. Add an exactly-once completion bridge in `SupervisorManager` that emits the same terminal result from `FailedToStart`, qualified with the app-scoped origin when the attempt was app-scoped, clears the saved-restart pending state, and ignores a later `finished` for the same attempt. An immediate supervisor-busy refusal is also a completed attempt. Wrap both manual and saved dispatch with `_submitting_restart` so the existing unqualified `"restart"` immediate-failure callback can be attributed. Fully qualified `"restart <app_id>"` callbacks carry their own origin. Do not invalidate unrelated structured apps or on a mere save.

There is one effective `_request_saved_restart` definition; consolidate the currently shadowed duplicate rather than adding a hook to a definition Python never calls. Preserve its actual notice, pending-result, and restart-failure semantics. Re-probing never loads a config, clears a draft, or recomputes dirty state from defaults.

## 6. Save-gate and commit state machine

### 6.1 Gate interface and evaluation order

```python
def _evaluate_llm_gate(
    self, app_id: str, draft: AppAIConfig, saved: AppAIConfig | None
) -> LLMGateResult
```

Call only after checking that the application is managed and the payload matches its registered configuration kind. The gate reads its owned snapshot and flags, and may perform a keyed capability probe at rule 7. It writes no config, creates no backup, requests no restart, and advances no saved/draft baseline. Rule-7 support may update the capability presentation without changing the draft.

The exact execution order is **1, 1a, 2, 3, 4, 0, 5, 6, 7a, 7b/7c/7d**. Rule 0's number is historical; it is not an early return ahead of refusal guards.

| Rule | Condition | Decision / next step |
| --- | --- | --- |
| 1 | `_load_failed[app_id]`, missing snapshot, or no owned saved baseline | Refuse with `LOAD_REQUIRED`; do not dereference a missing snapshot or create a default baseline. |
| 1a | nonempty `_baseline_conflict[app_id]` | Refuse with `BASELINE_CONFLICT`; list fields in details; reload is required. |
| 2 | endpoint is non-`None` and `is_valid_endpoint` is false | Refuse with `INVALID_LITERAL`; boundary assertion covers forged models. |
| 3 | `draft.endpoint_raw is not None` | Refuse with `REPAIR_REQUIRED`; unrelated edits cannot implicitly repair an invalid disk value. |
| 4 | explicit draft endpoint and `base_conflicts_with_endpoint(effective_api_base(...), endpoint)` | Refuse with `BASE_PATH_CONFLICT`; include the composed exact URL in details, even if endpoint is unchanged. |
| 0 | canonical draft equals canonical saved config | Return `no_op=True`; skip capability checking, rendering, writing, and backups. Caller may still restart. |
| 5 | draft endpoint is `None` and saved endpoint is explicit | Allow the write immediately. Do not invoke capability checking. |
| 6 | draft endpoint equals saved endpoint | Allow the write immediately. Do not invoke capability checking. This includes invalid-to-Auto repair after raw evidence was explicitly cleared. |
| 7a | endpoint introduced/changed and metadata flag false | Refuse with `NOT_SELECTABLE`; do not probe. |
| 7b | selected literal belongs to freshly keyed `support.accepted` | Allow, including a `PARTIAL` result. |
| 7c | verified status `SUPPORTED`, `PARTIAL`, or `UNSUPPORTED`, but chosen literal absent from acceptance | Refuse with `PROTOCOL_REJECTED`, naming that literal. |
| 7d | `UNVERIFIABLE` | Refuse with `BUILD_UNVERIFIABLE` plus the redacted probe detail. |

Apply rules 1, 1a, 2, and 3 to the owned typed values before revalidating a canonical copy for rule 4 onward; no assertion is replaced by a silently repaired value. Other forged model-shape violations raise Pydantic `ValidationError` into the coordinator's existing local-save-error translation, rather than being interpreted as legacy or capability evidence. New/change means endpoint comparison against the saved snapshot, not a sticky UI edit flag. A user selecting away and back reaches unchanged behavior.

Removal never depends on successful capability verification, and preserving an existing explicit value does not require re-verification. Both still obey the preceding load/conflict/raw guards; rule 4 is false after actual removal. “Removal is always allowed” does not authorize overwriting an unreadable or stale file. A changed base with an unchanged explicit endpoint still hits rule 4.

### 6.2 `_on_save_requested`: the only production LLM writer call

The LLM branch shall do the following synchronously on the GUI thread:

1. Preserve existing unknown-kind and payload-kind refusal checks. Keep the submitted owned draft separate from the saved snapshot. Obtain the snapshot with `.get()` so initial load failure does not raise `KeyError`.
2. Run the ordered gate, passing the saved config or `None`. On refusal, show the corresponding plain-text message/detail, keep the draft and all saved snapshot parts, and do not call the writer, transaction, or restart dispatcher.
3. On `no_op`, call no renderer or writer. With `should_restart=False`, retain existing `Configuration saved.` status semantics for an already-saved form. With `True`, request a restart only. The loaded snapshot remains the same object/value triple; no synthetic new digest or presence bit is installed.
4. Otherwise use the canonical validated draft values for the write: before entering the writer, prepare `AppAIConfig.model_validate(draft.model_dump())` and all owned deep copies, after rule 2 has already asserted the literal boundary. No validation adds new URL/model/key rules. Call exactly `write_app_config(meta, draft, baseline=snap.config, expected_sha256=snap.sha256)` once with that canonical draft. A mocked writer test must observe those arguments through this coordinator method, not just through a gate-helper test.
5. After the writer returns, calculate presence as `snap.api_base_present or (draft.api_base != snap.config.api_base)`. Base edits always set the key; no operation in this feature removes it. Build a new snapshot from the prepared canonical draft, returned digest, and that updated presence flag. Install it together with saved/draft copies, clear resolved ordinary save errors, pass the **same snapshot** to `view.load_config`, update dirty and auth warnings, then optionally request restart. If display fails after the physical commit succeeded, retain the newly committed snapshot and owned candidate draft, set the load-failure block, show a reload error, and do not dispatch restart; do not pretend the write was rolled back.
6. `CommittedWriteError` means the candidate bytes **are installed**, but recovery is required. Build and install the new snapshot from the error's digest and the prepared canonical draft, set the reload-required block, show `Configuration saved, but the file must be reloaded before another save.` with the cause in the details panel, dispatch no restart, and clear the block only on a successful reload. Never describe this as a rollback.
7. Catch `StaleDocumentError` in the typed LLM path in §8.1, before any structured-document recovery branch. Failures raised **before the commit point** do not update saved state or dispatch restart; `CommittedWriteError` is handled by step 6 and does update the snapshot because the bytes are installed. A transaction report containing unknown file state disables saving until reload; retain the actual report rather than claiming rollback succeeded.

There is no LLM write from a preset, combo handler, `_on_config_changed`, probe result, `_request_saved_restart`, or generic failure handler. Structured saves continue through their existing worker and shared transaction. A checked LLM save may wait on a cold capability miss for the subprocess's five-second timeout; no new asynchronous save pipeline is introduced.

### 6.3 File and restart effects

| Outcome | Configuration bytes | Baseline / digest / presence | Pending draft | Restart |
| --- | --- | --- | --- | --- |
| gate refusal | unchanged | unchanged | retained | none |
| permitted no-op | no file operation | unchanged | already equal | only if requested |
| successful checked save | sealed candidate installed | advance together | becomes saved candidate | only if requested |
| stale refusal | external bytes preserved | unchanged | retained; saving blocked | none |
| pre-install failure | unchanged | unchanged | retained | none |
| transaction failure | actual report: restored or unknown | unchanged | retained; unknown requires reload | none |
| restart failure after save | successful saved bytes remain | successful saved snapshot remains | not made dirty again | display failure; re-probe |
| manual restart | no config write | unchanged | unchanged | requested, then re-probe |

## 7. Persistence rules and exact YAML examples

All YAML blocks in this section are UTF-8 with LF line endings and one final newline. Examples with quotes use the ruamel quote-preservation settings. New endpoint keys use plain scalar spelling; an existing quoted endpoint retains its quote style when replaced. Comments attached to a removed managed key may disappear with that key; unrelated comments, keys, ordering, quotes, provider overrides, and values must survive round-trip rendering.

### 7.1 Legacy unchanged: exact byte identity, not just YAML equality

Before and after either permitted no-op save action:

```yaml
# Service configuration
ai:
  api_base: "https://gateway.example.test"
  api_key: "$EXAMPLE_API_KEY"
  model: "model-a"
  temperature: 0.2
```

Do not add `endpoint`, `endpoint_raw`, absent fields, or a backup. Even unusual formatting that the renderer would normalize remains byte-identical because rendering is skipped.

### 7.2 Explicit protocol insertion and removal

Starting from §7.1, selecting Messages produces exactly:

```yaml
# Service configuration
ai:
  api_base: "https://gateway.example.test"
  api_key: "$EXAMPLE_API_KEY"
  model: "model-a"
  temperature: 0.2
  endpoint: /v1/messages
```

Selecting Responses from that saved state changes only the last scalar to `/v1/responses`. Selecting Auto from either explicit state returns exactly the §7.1 document. It must not produce `endpoint: null`, `endpoint:`, `endpoint: ""`, or a display-only raw field.

### 7.3 Invalid value repaired explicitly to Auto

Before:

```yaml
ai:
  api_base: "https://gateway.example.test"
  endpoint: "/v1/completions"
  model: "model-a"
```

After the user selects Auto and saves:

```yaml
ai:
  api_base: "https://gateway.example.test"
  model: "model-a"
```

The reader represented the original endpoint as `None` plus raw evidence. Therefore comparing only normalized endpoints would miss this required removal. `baseline.endpoint_raw is not None` forces it. The same removal applies to stored null, empty string, integer, and boolean values. An unrelated edit without an explicit protocol selection retains raw evidence and is refused before writing.

### 7.4 Omitted fields remain omitted

Before:

```yaml
# Defaults are intentional
ai:
  messages_default_max_tokens: 8192
```

After selecting Messages on a verified build:

```yaml
# Defaults are intentional
ai:
  messages_default_max_tokens: 8192
  endpoint: /v1/messages
```

No `api_base`, `api_key`, or model field is inserted. Before selection, ai-grammar's effective legacy base is `https://api.openai.com/v1`; textkit's is `https://api.openai.com`. Both preview `https://api.openai.com/v1/chat/completions`. After selection, both use effective base `https://api.openai.com` and preview `https://api.openai.com/v1/messages`. Presence remains false after this protocol-only save.

### 7.5 Provider-only task mappings and an inactive base model survive

Before a textkit protocol-only save:

```yaml
ai:
  api_base: "https://gateway.example.test"
  api_key: "$EXAMPLE_API_KEY"
  model: "non-default-base-model"
  messages_default_max_tokens: 6000
  temperature: 0.2
  endpoints:
    check: 0.1
  ocr:
    api_base: "https://vision.example.test"
    api_key_env: "VISION_KEY"
  text:
    api_key_env: "TEXT_KEY"
```

After selecting Messages:

```yaml
ai:
  api_base: "https://gateway.example.test"
  api_key: "$EXAMPLE_API_KEY"
  model: "non-default-base-model"
  messages_default_max_tokens: 6000
  temperature: 0.2
  endpoints:
    check: 0.1
  ocr:
    api_base: "https://vision.example.test"
    api_key_env: "VISION_KEY"
  text:
    api_key_env: "TEXT_KEY"
  endpoint: /v1/messages
```

The provider-only mappings classify the editor as split, but do not authorize deleting the document's base model or adding empty model overrides. Never emit nested `ocr.endpoint` / `text.endpoint`: textkit forbids those, and ai-grammar does not use those sections.

### 7.6 Deliberate split-to-unified toggle is the destructive exception

If the user explicitly turns off split mode in the §7.5 saved document and chooses `unified-model`, the result is:

```yaml
ai:
  api_base: "https://gateway.example.test"
  api_key: "$EXAMPLE_API_KEY"
  model: "unified-model"
  messages_default_max_tokens: 6000
  temperature: 0.2
  endpoints:
    check: 0.1
  endpoint: /v1/messages
```

The task provider sections are intentionally removed. Clearing the chosen unified model removes `model` instead of writing an empty string. The manager does not materialize textkit's default `gpt-4.1-mini` or ai-grammar's default `gpt-4o-mini`.

### 7.7 Unmanaged yt2txt endpoint survives

Before:

```yaml
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$EXAMPLE_API_KEY"
  endpoint: "/hand-written/value" # unmanaged by this editor
  model: "whisper-old"
```

After changing only its model:

```yaml
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$EXAMPLE_API_KEY"
  endpoint: "/hand-written/value" # unmanaged by this editor
  model: "whisper-new"
```

The endpoint line and its comment remain verbatim. There is no protocol row, raw-error state, capability probe, or capability-based refusal for that field.

### 7.8 Dependent URL rewrite

A selected chat2api listener change may replace only `ai.api_base` in a dependent candidate. It must preserve `ai.endpoint`, including a present invalid raw value or an unmanaged yt2txt value, and all other fields. This path uses `render_app_config` with its narrow base-only mutator, not `_apply_ai_config` with a reconstructed/default `AppAIConfig`. Capability gating is not a new condition on that existing base-only transaction. Subsequent editor saves still obey all LLM gate rules.

## 8. UI, reload, and dependent-rebase contracts

### 8.1 Load failures and typed stale recovery

`AppDetailView` adds a `reload_requested = pyqtSignal(str)` and a `Reload configuration` button in its existing error area, connected by MainWindow to `_reload_config(app_id)`. All error labels and the new hint/request labels use `Qt.PlainText`; details use `QPlainTextEdit.setPlainText`.

An initial read/display/deep-copy failure records `_load_failed=True`, shows `ConfigLoadError` information, offers reload, and disables both save buttons. No successful snapshot, saved config, or editable owned default is published. With no loaded baseline, disable the provider/model editing groups too, and ignore LLM `config_changed` emissions until a snapshot exists; never publish a default draft through that signal path. A failed reload preserves any previous owned snapshot and draft, but keeps the save block. The manual restart and logs remain usable.

An LLM `StaleDocumentError` is recognized by `meta.config_kind == "llm"` before the structured stale-dialog branch. Keep its old snapshot and draft, set the reload-required `_load_failed` block, disable saving, show `LLM_STALE`, and offer reload. Do not construct `StaleDocumentDialog`, inspect `.kind` on an `AppAIConfig`, render a structured diff, or retry with the observed external hash.

`_reload_config` for an LLM app first reads a new non-creating snapshot into temporary ownership:

| New read / old state | Action |
| --- | --- |
| read fails | retain old owned triple and draft; show failure; keep saving disabled |
| no previous snapshot | install new snapshot and draft, clear blocks, enable saving |
| same digest and no baseline conflict | retain current pending draft, install the coherent re-read baseline/presence, clear load/stale block |
| different digest, no unsaved draft | install new snapshot and a new matching draft, clear blocks |
| different digest with pending edits | ask `RELOAD_CONFIRM`; Cancel changes nothing; Discard installs the new snapshot and drops old draft |
| any baseline conflict, including equal digest | ask `RELOAD_CONFIRM`; successful Discard resets to the new snapshot and clears the conflict; Cancel retains the block |

The confirmation uses title `Reload configuration`, body in §10.2, buttons `Discard` and `Cancel`, and defaults to Cancel. Read before asking so a failed read cannot discard a draft. No reload writes a configuration or copies an example. Successful installation updates the view with the same `ConfigSnapshot`, clears relevant error/reload state, preserves capability status, updates dirty and auth warnings, and does not start a service.

### 8.2 View interfaces and owned protocol state

```python
def load_config(self, snapshot: ConfigSnapshot) -> None
def get_current_draft(self) -> AppAIConfig
def set_protocol_support(self, support: ProtocolSupport) -> None
def adopt_saved_baseline(
    self, snapshot: ConfigSnapshot, *, preserve_draft: bool
) -> tuple[str, ...]
def show_config_error(self, message: str, detail: str = "") -> None
```

`load_config` installs a deep baseline and presence flag, populates controls silently under `_is_loading`/signal blockers, selects stored protocol or its invalid placeholder, updates preset matching, auth hint and Request URL, and initializes `_loaded_endpoint`, `_loaded_endpoint_raw`, and `_protocol_edited=False`. It emits no `config_changed`; restore loading guards/blockers in `finally`, including on display failure. Pass snapshots at every LLM view call site, including tests; do not keep a separate lossy config-only load path.

`get_current_draft` returns a fresh canonical `AppAIConfig` from current widgets. For participating apps, it copies `_endpoint_raw` as well as the selected valid endpoint. For an invalid placeholder, endpoint is `None` but the raw evidence remains. Unrelated field/model changes never clear it. For nonparticipating apps it always supplies `endpoint=None, endpoint_raw=None`.

An actual user activation of Auto or a valid literal, including explicit pinned-preset application, clears `_endpoint_raw` and emits the normal dirty-change signal. Connect protocol activation as well as index change so an explicit Auto choice can repair an invalid value even if an implementation's display index would otherwise be unchanged. Programmatic loading, support refresh, and baseline adoption cannot trigger this repair action. Compute `_protocol_edited` from the current `(endpoint, endpoint_raw)` pair versus the loaded pair on every relevant edit; it is not sticky.

`set_protocol_support` changes item enablement, capability notice, and applicable diagnostic details only. It never changes the selected draft protocol, clears raw evidence, changes a model/base/key, or emits dirty signals. A pending probe is presented as the unverifiable availability state, with all four normal items selectable and no claim of verified support.

`show_config_error` remains plain-text. Capability notice/details must not overwrite a blocking load/stale/conflict error or remove its reload button. Keep capability notice under the protocol row. Details priority is recovery error, then current gate/local-save/transaction error, then the current non-supported probe's redacted detail. Ordinary saved/restart status text is not an error that hides the probe-detail fallback. Successful probe completion does not re-enable saves blocked by recovery flags.

### 8.3 Three-way managed-field rebase

`adopt_saved_baseline(snapshot, preserve_draft=False)` is equivalent to loading the snapshot and returns `()`.

With `preserve_draft=True`, capture `L` from the view's old baseline and `D` freshly from its current widgets **before** installing `C=snapshot.config`. Do not rely on dirty state or a draft copy captured when the structured save worker started. Merge logical fields in deterministic order:

```text
api_base, api_key, endpoint, is_split_model, model, ocr_model, text_model
```

The logical endpoint field is the pair `(endpoint, endpoint_raw)`; raw evidence participates in equality. Model mode and each model value first follow the same rule. Model mode/leaf dependency receives the conservative cross-mode conflict check below before canonical active-field normalization; normalization must never silently erase a pending user model value.

| Comparison | Merged draft field | Conflict? |
| --- | --- | --- |
| `D == L` | adopt `C` | no |
| `D != L` and `C == L` | retain `D` | no |
| `D != L`, `C != L`, `D == C` | retain agreed `C` | no |
| `D != L`, `C != L`, `D != C` | retain visible `D`, install `C` as saved baseline | yes |

For model mode/leaf dependency, let model leaves mean `model`, `ocr_model`, and `text_model`. If `C.is_split_model != L.is_split_model` and a leaf has `D != L` and `D != C`, or if `D.is_split_model != L.is_split_model` and a leaf has `C != L` and `C != D`, record `is_split_model` and those leaves as conflicts. Retain D's mode and its active pending values visibly; do not adopt a mode that hides/clears them. The saved baseline is still C, and the conflict block prevents serializing a hybrid candidate. This makes concurrent mode-versus-leaf edits recoverable without treating independent OCR and text leaf edits as an atomic-group conflict. In a nonconflicting merge, ordinary per-field adoption and canonical inactive-field clearing apply.

Install C's presence flag regardless of which draft fields remain pending. An unedited field adopts C in its widget silently, except for that explicit mode/leaf conflict presentation; no `config_changed` is emitted by this operation. Update `_loaded_endpoint` and `_loaded_endpoint_raw` to C, retain the merged draft's raw state, and recompute `_protocol_edited` against C. Return the tuple of conflicting field names in the order above, using `endpoint` for its logical pair. This return type explicitly resolves the coordinator notification seam.

MainWindow stores that tuple in `_baseline_conflict`, installs C and its digest/presence together, takes `view.get_current_draft()` as its new owned draft, and recomputes the dirty indicator. A genuine conflict displays `BASELINE_CONFLICT`, disables both save actions, and offers reload; rule 1a also protects direct save-slot calls. An existing conflict remains blocking until a confirmed successful reload. Returning a combo away and back before reconciliation is not a conflict when its pair equals L.

### 8.4 Reconciliation after dependent commit

```python
def _reconcile_dependent_views(self, saved_dependents: dict[str, Path]) -> None
```

For each selected rewritten app, validate that its result path is the registered config path after canonical parent resolution, then re-read with `read_app_config_snapshot(meta)`. Do not accept a bare config from `SaveResult`, reuse the pre-transaction digest, reuse an old presence flag, or call a creating compatibility reader.

Call `adopt_saved_baseline(new_snapshot, preserve_draft=True)` for an existing view baseline; all four field cases then work even when the whole tab was dirty. Install the new saved triple and merged current draft in the coordinator as in §8.3. With no prior view baseline, load the snapshot normally. If re-read/display fails, keep the last owned triple/draft, set the load-failure block, and offer reload; do not undo the already successful chat2api transaction or claim that the dependent was not saved.

Within `structured_config.commit`, the dependent branch still normalizes its sealed parsed candidate with `_config_from_document(parsed, match.meta)` to establish correct ownership; publish `match.meta.id -> canonical target Path` only after commit. `find_affected_dependents` likewise supplies its actual metadata. Existing non-regular-file, anchor/alias, stale-dialog-snapshot, exact-base matching, and sealed-byte guarantees remain intact.

### 8.5 Layout and availability tables

Create the labelled protocol row only when metadata's flag is true, between the existing preset row and `API Base URL:`. Normal combo texts and data are:

| Index | Text | Data |
| --- | --- | --- |
| 0 | `Auto — omit the key` | `None` |
| 1 | `OpenAI Chat Completions — /v1/chat/completions` | exact literal |
| 2 | `OpenAI Responses — /v1/responses` | exact literal |
| 3 | `Anthropic Messages — /v1/messages` | exact literal |

An invalid file adds a selected, non-editable error placeholder `Invalid: <repr>`; it is not a selectable fifth protocol and never emits its display text as a draft endpoint. The four normal choices remain available according to the table.

Let `A=support.accepted` and let `v` be the currently saved valid literal, if any:

| Capability | Stored Auto | Stored explicit v | Stored invalid |
| --- | --- | --- | --- |
| `SUPPORTED` | all four | all four | all four |
| `UNVERIFIABLE` | all four | all four | all four |
| `PARTIAL` | Auto + A | Auto + A + v | Auto + A |
| `UNSUPPORTED` | Auto only | Auto + v | Auto only |

Store original item labels separately; disabled items are greyed and render a trailing ` unavailable` suffix once, not repeatedly. Their user data remains the exact literal. The stored item exemption preserves an existing value; it does not allow a different rejected value through rule 7. A draft that becomes rejected after a probe update remains visibly selected but disabled; never silently change it to Auto. The user can always select Auto. The same rule handles a pinned preset that explicitly selects a currently disabled literal: the draft shows the requested protocol, but saving it still fails the gate.

### 8.6 UI state and action effects

| State | Hint / Request URL | Saves | Reload / editing |
| --- | --- | --- | --- |
| flag false | protocol row and protocol URL line not created | existing LLM actions | no protocol/preset access |
| valid Auto | legacy hint; exact target legacy URL | gate decides | normal editing |
| valid explicit | protocol auth hint; exact URL | gate decides; `/v1` conflict refuses | normal editing |
| explicit `/v1` conflict | Request URL and base error style red; exact doubled URL retained | button may be clicked but gate refuses | edit base or select Auto; no auto-repair |
| partial/unsupported | amber compatibility notice | unchanged/removal allowed; rejected changes refused | availability table applies |
| unverifiable/pending | amber unknown notice; probe detail when available | unchanged/removal allowed; new/change refused | all four normal choices usable |
| raw invalid | invalid combo styling; hint and URL show repair-unavailable text | refuses until explicit repair | Auto/allowed literal clears raw and marks dirty |
| load failure/stale | blocking error and reload button | both disabled; direct slot still refuses | current draft retained; logs/manual restart usable |
| rebase conflict | blocking error with named fields and reload button | both disabled; rule 1a refuses | conflicting widgets retained until reload |
| successful recovery | refreshed baseline/digest/presence | re-enabled unless another recovery block remains | capability status remains |

For LLM views, the common save-button enablement condition is: owned snapshot exists, no load/reload-required block, no baseline conflict, and no save-in-progress state. Capability status, invalid raw evidence, and explicit-base conflicts do not independently disable these buttons; their gate refusal provides the actionable message. Provider/model groups are disabled only for a no-baseline load failure or an in-progress save, not just a failed capability probe.

Protocol edits, pinned-preset changes, and raw repairs participate in existing `config_changed` dirty tracking. Empty model widgets canonicalize to `None`; unsupported metadata cannot expose a hidden split/protocol editing path. No new restart gate depends on capability success.

## 9. Presets and model discovery

### 9.1 Preset resolver and application

Append this record to `DEFAULT_PRESETS`, after the existing entries:

```python
ProviderPreset(
    id="anthropic_official",
    name="Official Anthropic API",
    api_base="https://api.anthropic.com",
    default_key_env_var="ANTHROPIC_API_KEY",
    endpoint="/v1/messages",
    docs_url="https://docs.anthropic.com",
    description="Claude models over the Anthropic Messages protocol",
)
```

Provide one resolver in `config/presets.py`:

```python
def resolve_preset(
    preset_id: str, *, presets: Sequence[ProviderPreset] | None = None
) -> ProviderPreset | None
```

It searches the supplied ordered sequence or `DEFAULT_PRESETS` when `None`, returns the first id match, and returns `None` for an unknown id. It performs no I/O or mutations. Population, matching, and selection use this resolver rather than ad hoc nested id-lookup loops. This feature does not add a custom-preset editor or change which pre-existing custom records are offered; their new optional field remains load-compatible.

Filter endpoint-bearing presets out entirely if the protocol row is absent or the metadata flag is false. Do not filter them merely because the installed build is partial/unsupported; the draft and gate express that limitation. Existing presets default to `endpoint=None`.

For a non-custom selected preset, batch updates under the loading guard: base becomes `preset.api_base`, key becomes `$<default_key_env_var>` when supplied (otherwise leave it alone), and a pinned endpoint explicitly selects that protocol and clears raw invalid evidence. An endpoint-free preset leaves both current endpoint and raw evidence unchanged. A `custom` selection or unknown id does not alter fields. Emit at most one `config_changed` for the final batch, and only if canonical draft values actually changed.

Connect both `currentIndexChanged` and `activated` to the same application path. Duplicate delivery must be idempotent and not create a second dirty event for the same resulting draft. Re-activation of the current index must still repair base/key/protocol fields changed since the previous activation.

Silent load-time matching uses normalized base with trailing slashes removed. A pinned preset additionally requires matching endpoint and no raw invalid evidence. An endpoint-free preset matches by base only. Use the first offered match in existing order; otherwise select the existing custom entry. Matching never applies a preset or clears raw evidence. Thus an Anthropic base with a saved Responses endpoint is not displayed as the Anthropic preset already selected.

Persisted `custom_presets` in `settings.json` that omit endpoint load as `None`. Invalid explicit custom values fail Pydantic literal validation; do not expand the accepted vocabulary to preserve them. Retain the application's existing settings-load failure policy.

### 9.2 Fetch interface and headers

```python
def fetch_models_sync(request: ModelFetchRequest) -> ModelFetchResponse
```

Keep all existing discovery behavior except protocol-aware header choice. Resolve `$ENV_VAR` with existing `resolve_api_key`; do not mutate the request or persisted reference. Keep `Accept: application/json` and `User-Agent: ai-manager/0.1.0`.

| Current request endpoint | Authentication headers |
| --- | --- |
| `None`, Chat Completions, Responses, or any other non-Messages transport hint | `Authorization: Bearer <resolved_key>` when nonempty; omit Authorization when empty, preserving existing behavior |
| `/v1/messages` | `x-api-key: <resolved_key>` and `anthropic-version: 2023-06-01`; no Authorization |

For Messages, send the version header even with an empty resolved key and send `x-api-key` as the empty string in that case; this follows the approved Messages header assignment. A missing key is not replaced by another auth scheme. The provider's existing HTTP error handling remains authoritative.

Keep base selection `request.api_base.rstrip("/")`, the empty-base check, `/v1/models` then `/models`, `httpx.Timeout(10.0, connect=5.0)`, redirects, fallback behavior, payload normalization, error strings, and response token/endpoint fields unchanged. In particular, do not switch discovery to `/messages`, `/responses`, or a provider-specific models path, and do not “fix” a supplied base ending in `/v1` in this feature.

`AppDetailView._on_fetch_clicked` takes one current draft, increments its fetch token, and constructs the request with that draft's base, key, endpoint, and the view's own app id. It does not use `_current_config.endpoint` or the saved snapshot's endpoint. This also preserves the current model-discovery behavior for an omitted base; only URL preview/gate defaults use §3.4. Fetching while raw evidence remains uses the draft's `None` endpoint and does not count as a protocol repair or authorize saving.

The existing coordinator owns the request until completion and routes a response to its origin, not the selected sidebar app. A view ignores a response whose token differs from its latest fetch token. Model-list updates must not clear endpoint/raw state or create a spurious model edit from an absent model.

## 10. User-visible copy and error taxonomy

### 10.1 Fixed protocol copy

| Use | Exact text |
| --- | --- |
| row label | `Upstream protocol` |
| Auto item | `Auto — omit the key` |
| explicit items | the four-item table in §8.5 |
| disabled suffix | ` unavailable` |
| Auto auth hint | `legacy Chat Completions - Authorization: Bearer` |
| OpenAI explicit hint | `Sends Authorization: Bearer` |
| Messages hint | `Sends x-api-key + anthropic-version: 2023-06-01` |
| ordinary URL | `Request URL: <composed URL>` |
| invalid display | `Invalid: <repr>` |
| raw repair message | `Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.` |
| invalid hint | `Unavailable — Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.` |
| invalid URL | `Request URL: unavailable — Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.` |
| partial/unsupported notice | `Installed build failed protocol compatibility checks. Update the service to enable protocol selection. Auto stays selectable so a saved protocol can be removed.` |
| unknown notice | `Protocol support could not be verified — validated by ai-manager only.` |
| recovery button | `Reload configuration` |

The compatibility notice means some or all protocols failed checks, not that `ai.endpoint` is absent. Do not use “has no ai.endpoint” for a verified partial result. The visual reference's state captions, sample version, model id, URLs, and fetched-model count illustrate states; dynamic data is rendered using the exact templates here. Retain existing provider/model group labels, base/key labels, fetch button, and save/restart button captions. No endpoint/API key/model data is rich text.

### 10.2 Gate and recovery messages

Names in this table are specification identifiers; they need not introduce a public enum:

| Identifier | Exact message / detail |
| --- | --- |
| `LOAD_REQUIRED` | `Reload the configuration before saving.` |
| `BASELINE_CONFLICT` | `Configuration changed while you were editing. Reload the configuration before saving.` Detail: `Conflicting fields: <comma-separated ordered field names>.` |
| `INVALID_LITERAL` | `Unsupported protocol value: <repr>. Pick one of the three supported protocols or Auto.` |
| `REPAIR_REQUIRED` | `Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.` Detail: `Stored ai.endpoint: <endpoint_raw>` |
| `BASE_PATH_CONFLICT` | `The protocol path already includes /v1. Enter the gateway prefix, e.g. https://api.openai.com.` Detail: `Request URL: <exact composed URL>` |
| `NOT_SELECTABLE` | `Protocol selection is not available for this application.` |
| `PROTOCOL_REJECTED` | `Installed build rejected protocol <literal>. Update the service or select Auto.` Detail: redacted probe detail, when nonempty |
| `BUILD_UNVERIFIABLE` | `Cannot verify this build; introducing or changing ai.endpoint is refused. Select Auto to remove the key, or restore the saved protocol.` Detail: redacted probe detail |
| `LLM_STALE` | `Configuration changed on disk; save refused. Reload the configuration before saving.` |
| `RELOAD_CONFIRM` | `Reload configuration and discard unsaved changes?` |
| successful save / permitted no-op | `Configuration saved.` |
| saved-restart dispatch | `Configuration saved. Restart requested.` |
| saved-restart failure | `Configuration saved, but service restart failed: <message>` |
| saved-restart success | existing `service restart succeeded` |

`<repr>`, `<literal>`, `<message>`, and similar angle-bracket forms in copy tables are substitution slots, not implementation decisions. Use Python repr for raw/boundary values, the exact literal for rejected protocols, and ordered internal field names for conflicts. All are substituted into plain text. No-op success text describes an already-saved form; it does not imply a backup was created.

### 10.3 Probe failure reasons

Build failure detail from these exact initial lines, then optional `stdout:\n...` and `stderr:\n...` sections, and redact the complete text:

| Failure | Initial detail line |
| --- | --- |
| resolver / scan / stat failure | `Protocol capability check could not be prepared: <exception>` |
| spawn failure | `Could not run protocol capability check: <exception>` |
| timeout | `Protocol capability check timed out after 5 seconds.` |
| exit other than 0, including 75 | `Protocol capability check exited <returncode>.` |
| exit 0 but missing/invalid sentinel or payload | `Protocol capability check did not report a valid result.` |
| old generation or changed interpreter/source identity | `Protocol capability check was superseded; retry after the restart or update.` |
| unexpected worker failure | `Protocol capability check failed: <exception>` |

Redaction uses the existing function, including truncating a Pydantic `input_value=` tail and replacing recognized secret key/value pairs with `***`. This is a diagnostic scrubber, not a sandbox or a proof that arbitrary target output can never contain an unlabelled secret. Do not put real configuration secrets into the child program to begin with.

### 10.4 Exceptions and ownership

| Category | Public representation | Owner / recovery | Write permitted? |
| --- | --- | --- | --- |
| invalid model/preset construction | Pydantic `ValidationError` | caller/settings policy | no invalid draft persisted |
| unsupported config kind | existing `UnknownConfigKindError` or metadata validator error | exhaustive dispatch | no |
| LLM YAML/UTF-8/shape/read/display failure | `ConfigLoadError` / `ConfigShapeError` / `SymlinkConfigError` | LLM load block + reload | no |
| gate refusal | `LLMGateResult(refused=True, ...)` | plain-text view, draft retained | no |
| capability operational failure | `ProtocolSupport(UNVERIFIABLE, frozenset(), redacted_detail)` | load notice; rule 7d on change | not for a new/changed protocol |
| capability verified rejection | `PARTIAL` or `UNSUPPORTED` record | literal-specific availability and rule 7c | accepted choices/removal/unchanged only |
| stale write | `StaleDocumentError`, retaining expected and actual binary digests | typed LLM branch; reload, never force | no overwrite |
| non-writable checked save | existing `ReadOnlyConfigError` | show error; no-op needs no writeability | no replacement |
| backup/stage/replace/rollback failure | `TransactionError(report)` | existing transaction report; unknown state requires reload | only actual report determines disk state |
| cleanup failure after `replace_all()` | `CommittedWriteError(path, digest, report, cause)` | install committed snapshot, reload-required block, no restart | bytes are installed; never reported as rollback |
| other local save failure | `ConfigError("Configuration save failed: ...")` | retain baseline/draft; no restart | no successful snapshot publication |
| restart fails after commit | existing supervisor completion | show failure, keep saved state, invalidate/re-probe | already-saved bytes remain |

Typed errors are not flattened into a default config or into a supported result. Structured adapter validation and recovery behavior remain unchanged except for the explicitly revised dependent payload.

Retain model-discovery messages verbatim: `API Base URL cannot be empty.`, `Invalid JSON received from <url>: <error>`, `HTTP 404 Not Found at <url>`, `HTTP 401 Unauthorized: Invalid or missing API key at <url>`, `HTTP <status> (<reason>) from <url>`, `Connection refused connecting to <url>`, `Request timed out connecting to <url>`, `Network error connecting to <url>: <error>`, and `Failed to fetch models from provider.` The view retains `Fetching models from provider...`, `✓ Fetched <count> models from <endpoint>`, and the existing warning prefix for errors.

## 11. Concrete test plan and red-phase falsifications

### 11.1 Rules for evidence

Use isolated `tmp_path` copies and synthetic importable application modules. Do not run installed upstream services or contact providers. Metadata factories for ai-grammar/textkit explicitly set `supports_protocol_selection=True`, the actual split-support value, an isolated backend launch directory, and `default_port=8000`; an id alone does not set the structural flag. Keep separate flag-false cases. Patch the interpreter resolver to a known test interpreter and use mocked HTTP transport. GUI tests run offscreen with the existing isolation fixture, supervisor autostart disabled, controlled workers, and `QMessageBox` confirmation responses injected so a modal cannot hang teardown.

Every new mechanism needs: a behavioral assertion, an observed failing run before the fix or a narrow regression mutant that demonstrably fails, and a passing run after restoration. An import error caused solely by a not-yet-created module is scaffolding failure, not the required red-phase proof. Mutation runs belong to isolated test copies during implementation, not to this specification-drafting task. Do not accept a test that still passes when its claimed mechanism is disabled.

The following test names and files are prescribed acceptance cases; parametrization may combine cases without dropping assertions.

### 11.2 Protocols and normalized models

`tests/test_protocols.py`:

- `test_explicit_vocabulary_is_exact`: all three accepted; `None`, blank, padded, aliases, full URL, booleans, integers, and collections false.
- `test_request_url_exact_legacy_matrix`: all six §3.2 legacy rows, including ai-grammar's double slash.
- `test_explicit_request_url_preserves_gateway_prefix`: both app ids × three protocols × root, slash, gateway, and `/v1` bases.
- `test_base_conflict_is_path_only_and_total`: legacy false; path `/v1`, `/v1/`, `/gateway/v1///` true; host/query/fragment lookalikes, `/v10`, `/V1` false; partial IPv6 bases never raise and completion recovers.
- `test_omitted_base_uses_mode_specific_target_default`: absent vs explicit placeholder, pending base edit vs reversion, Auto vs explicit for both apps.

`tests/test_models.py` and `tests/test_app_registry.py`:

- Literal-construction rejection on AppAIConfig and ProviderPreset, legacy defaults, transport-hint permissiveness, raw field survival, whitespace/blank model canonicalization, inactive-model normalization, strict fetch origin, and existing kind errors.
- Registry flags true only for ai-grammar/textkit and split flags unchanged.

Red falsifications: replace `is_valid_endpoint` with truthiness; normalize every legacy URL as textkit; let the conflict predicate search the whole URL; remove its `ValueError` catch; ignore the presence bit; remove literal typing; omit registry flags. Each corresponding test must fail on its specific value/URL/flag assertion, not a broad exception.

### 11.3 YAML round-trip and writer

Extend `tests/test_yaml_manager.py`:

- `test_endpoint_read_matrix_with_metadata`: every §4.1 endpoint row, including null/blank/non-string; two participating app metadata records plus yt2txt ownership.
- `test_snapshot_hashes_the_same_bytes_it_parses`: exact binary hash and actual base-key presence, including explicit placeholder and absent base; no second independent read can supply the hash.
- `test_protocol_only_save_preserves_provider_only_mappings_and_base_model`: exact §7.5 before/after bytes; assert no nested model/endpoint insertion and no base-model removal.
- `test_invalid_to_auto_removes_exact_key_bytes`: exact §7.3 result for invalid string, null, blank, integer, boolean; assert endpoint line gone, not merely normalized to None.
- `test_unmanaged_endpoint_survives_other_edits`: exact yt2txt endpoint/comment bytes; save succeeds without a probe.
- `test_diff_does_not_materialize_omitted_fields`: exact §7.4 result, including model removal rather than empty serialization when actually edited.
- `test_only_mode_toggle_removes_inactive_sections`: protocol/key/model-only edits preserve provider overrides; deliberate split-to-unified removes sections; deliberate unified-to-split removes base model and establishes split mappings; blank active models are removed.
- `test_checked_writer_returns_installed_bytes_digest_and_backup`: hash equals actual installed bytes, backup bytes/mode equal original, final mode preserved, no leaked stage temp.
- `test_checked_writer_stale_refuses_before_render`: external endpoint addition, render/backup/replace spies forbidden, typed expected/actual hashes asserted, external bytes/mode unchanged.
- `test_checked_writer_rechecks_under_transaction_lock`: alter bytes between initial read and prepare; transaction refuses, original expected digest never advanced.
- `test_legacy_writer_branch_still_uses_fixed_backup`: required baseline argument, diff-only changes, return digest, original fixed `.bak` semantics.
- `test_noop_writer_has_no_backup_or_replace`: checked and unchecked existing-file direct calls, read-only input and renderer-sensitive formatting; no backup/render/replace.
- `test_load_failures_never_become_successful_default_snapshot`: malformed YAML, duplicate keys, non-mapping root/AI, invalid UTF-8, missing file, symlink, FIFO; missing snapshot read never copies example; read-only regular file still snapshots.
- `test_render_remains_pure`: original tree and file bytes unchanged; mutator called once on a distinct tree.

Update every existing `write_app_config` and `_config_from_document` test call site with baseline/metadata. Preserve tests for old unrelated managed fields and permissions.

Red falsifications: unconditionally assign defaults; unconditionally pop task sections; write `endpoint=None`; omit the `baseline.endpoint_raw` force condition; drop metadata; return a hash of model JSON; ignore `expected_sha256`; call creating reader in snapshot/reconcile; render before no-op. Pin each with exact bytes, a forbidden-call spy, or the returned digest assertion. The invalid-to-Auto test must fail when only its raw-force condition is removed.

### 11.4 Probe execution and format

New `tests/test_protocol_capability.py`, using real child interpreters against synthetic files:

| Fixture | Required result / assertion |
| --- | --- |
| ai-grammar resolver accepts all | supported, exact full accepted set |
| ai-grammar resolver rejects Responses | partial, Chat + Messages accepted |
| ai-grammar resolver rejects every value | unsupported, empty set |
| textkit guard rejects Responses but validator accepts it | partial; Responses absent despite model acceptance |
| textkit guard accepts Messages but model rejects it | Messages rejected; accepted subset exactly verified |
| no `_resolve_endpoint`, no `SUPPORTED_ENDPOINTS`, no `AIConfig.model_validate`, or unusable interface type | unverifiable, empty acceptance |
| imported module exits 0 before checks | unverifiable; exit status alone insufficient |
| resolver import sleeps beyond timeout | unverifiable timeout; direct child killed/reaped |
| import writes a marker file | marker exists; documented import side effect, not falsely sandboxed |
| bytecode-eligible imports | argv has `-B`, env flag `1`; no `__pycache__` in the target tree |

Parent-parser tests inject exit/payload pairs: exit 75 and another nonzero code with otherwise valid payload; missing sentinel; wrong nonce; duplicate matching sentinel; non-final sentinel; malformed JSON; duplicate object keys; wrong keys/types; unknown/duplicate/overlapping/unaccounted literals; a valid empty-accepted partition. Assert every malformed/nonzero case is empty-accepted unknown, while a valid rejection is unsupported. Import banners before the final valid sentinel remain acceptable.

Assert spawn argv/cwd/env exactly, lexical selected virtualenv interpreter preserved, and no extra `verify_app_interpreter` subprocess. Capture stderr with a synthetic credential-bearing key/value and a Pydantic `input_value=` tail; assert only scrubbed text reaches `ProtocolSupport.detail`, cache, and view.

Red falsifications: use field presence only; skip textkit's membership check; accept exit 0 without sentinel; ignore nonce or partition completeness; map timeout to unsupported; retain old accepted values on failure; drop `-B` or env flag. Each must fail the corresponding status/set/argv/filesystem assertion.

### 11.5 Cache, overflow, generation, and token races

`tests/test_protocol_capability.py`:

- Identical full key avoids a second subprocess; `use_cache=False` causes another and does not overwrite a cached entry.
- Edit source contents with the usual mtime change, then replace source with different equal-size bytes and restore its original mtime; each must re-probe. A source mtime-only touch with identical contents intentionally remains a full-key hit. Change interpreter mtime and assert another miss.
- Excluded cache/virtualenv Python files do not change the full fingerprint; included files do. A required scan error returns unknown without caching.
- Exactly 200 files may cache; 201 files always execute again, even with a prior small-tree supported entry. Returning a coarse key cannot create a cache hit.
- Block an old-generation child, invalidate, complete a new-generation probe, then release the old child. Assert no old result inserted over or returned as supported after invalidation.
- Queue a job before invalidation but run it after; assert no child spawn. Change source identity during a running probe; assert no publication under the old fingerprint.

GUI/coordinator race tests:

- Use a real `QThreadPool` worker and a GUI-thread assertion in the completion slot; a manually invoked `run()` does not prove queued delivery. Reuse the existing launcher worker's thread-affinity regression pattern.
- Controlled completions in reverse order: an old token cannot change availability or remove the newer owned job.
- Restart advances generation, schedules one new probe, and old-generation completion cannot change view/details even when its token callback arrives late.
- Saved and manual restart completion, success and failure, plus immediate busy refusal, each invalidate once for the correct origin and preserve the complete draft. No invalidation on an ordinary save or unrelated status refresh.
- `FailedToStart` with no `finished` (missing or non-executable launcher): exactly one completion, one invalidation, one fresh probe, the failure shown, saved-restart pending state cleared, draft unchanged, and no double completion when a `finished` also arrives for the same attempt.

Red falsifications: hash only mtime/size; cache overflow; remove cache generation comparison; capture generation only when a queued job starts; remove GUI token/generation validation; invalidate on dispatch only; hook the shadowed restart method. Each requires a targeted count/result/draft assertion that becomes false.

### 11.6 UI availability and invalid state

Extend `tests/test_app_views.py`:

- Exact row placement, labels/data/order, non-editable combo, no row or endpoint-bearing preset for yt2txt.
- All 12 capability/stored-state cells in §8.5. Partial fixture accepts Chat + Messages: only Responses disabled unless it is the stored value. Disabled suffix does not accumulate on repeat refresh.
- Stored explicit protocol remains selectable under unsupported; stored invalid leaves Auto only under unsupported. All four normal items remain enabled for unknown.
- Invalid placeholder/hint/URL text; unrelated model/key/base edits retain raw evidence; explicit Auto or literal activation clears it and marks dirty; load/support changes do not.
- Request URL exact matrices, red `/v1`/`/v1/` state, partial IPv6 editing, omitted-base defaults and pending explicit base edit.
- Support update leaves an already selected but newly rejected draft intact, does not emit `config_changed`, and cannot clear a blocking reload state.
- Load/snapshot adoption and model-list refresh normalize blank inactive fields without dirtying an untouched form.

Red falsifications: disable all three literals on partial; enable all three on partial; omit stored-item exemption; initialize invalid raw as Auto with no evidence; clear raw during any edit; force unknown to disabled; silently reset rejected draft to Auto. Test item flags, current draft pair, signal counts, and copy, not just screenshot presence.

### 11.7 Real save-slot gate coverage

Add `tests/test_endpoint_main_window.py`, invoking `_on_save_requested` for every case. Patch the writer to fail if reached on a refusal/no-op and patch capability lookup to fail if reached on removal/unchanged/no-op cases.

| Case | Required assertion |
| --- | --- |
| initial failed load / missing snapshot | rule 1 refusal, no default save and no KeyError |
| baseline conflict | rule 1a refusal even if draft otherwise equals baseline |
| forged invalid literal | rule 2 refusal before Pydantic revalidation |
| unrelated edit with raw invalid state | rule 3 refusal, key preserved |
| explicit endpoint with conflicting base | rule 4 refusal, exact doubled URL in details |
| unchanged explicit endpoint, only base changed to `/v1/` | same rule 4 refusal; cannot bypass via rule 6 |
| normalized equality and all guards passed | no-op, no renderer/transaction/backup |
| removal on unsupported and unknown build | succeeds without any probe |
| unchanged endpoint on unsupported and unknown build | unrelated edit succeeds without any probe |
| introduced endpoint on app without flag | 7a refusal |
| partial accepts Messages | Messages write allowed, Responses change refused naming literal |
| unknown introduction/change | 7d refusal, redacted details present |
| success | writer called once with exact saved baseline and loaded digest; returned digest installed |
| old invalid raw → explicit Auto | not a no-op; key removal reaches writer |

Repeat no-op tests for both save buttons, a read-only file, omitted base/key/model, and formatting unlike the renderer. Assert no `.bak`, no temp, same bytes/mode, same snapshot, and only the requested restart effect. An unchanged form with load block, baseline conflict, raw evidence, or explicit doubled `/v1` must still refuse before no-op logic.

Test the `_on_save_requested` seam itself by substituting a gate that refuses and a writer spy: bypassing the gate must make the test fail. Test writer arguments and post-success ownership separately. A gate-helper-only suite is not sufficient.

### 11.8 Digest advancement, stale path, and reload

- Two consecutive successful different LLM saves without reload: second writer expected hash equals first installed hash; no false stale error.
- Originally absent base edited and saved: new snapshot presence is true; next preview/reload uses the explicit value. Protocol-only omitted-base save retains false presence.
- Any failure raised before the commit point (including pre-install, stale and ordinary transaction failures): old baseline/digest/presence retained and restart not called. A display failure after a successful writer return instead retains the new committed triple, blocks save until reload, and does not dispatch restart; assert the actual installed bytes and reported outcome.
- `CommittedWriteError` is the deliberate exception: the new committed triple is installed, saving stays blocked until reload, and the old snapshot is never presented as current.
- External edit adds `ai.endpoint`, followed by unrelated save: typed stale handling keeps the external endpoint and bytes, retains pending widgets, disables saves, exposes reload, and never constructs a structured stale dialog or reads `.kind` from the LLM config.
- Fault injection: make `Transaction.__exit__` raise after a successful `replace_all()`. Assert `CommittedWriteError` carries the digest of the bytes actually on disk, the new snapshot is installed, saving is blocked until reload, no restart is dispatched, and the file content equals the sealed candidate.
- Fault injection: make cleanup raise while unwinding a `TransactionError` whose report is `unknown`. Assert the primary `TransactionError` and its report survive (cleanup attached as cause), saving stays blocked, and the old snapshot remains.
- A `CommittedWriteError` followed by reload restores normal saving; a reload that fails leaves the block in place.
- Same-digest reload preserves pending edits; different-digest reload with edits requires confirmation; Cancel retains all old state; Discard installs the read snapshot; failed read never discards the draft. Baseline-conflict reload resets after confirmation even if digest equals the current committed baseline.
- Successful reload re-enables actions only when all recovery blocks have cleared. Probe completion alone cannot do so.

Red falsifications: keep old digest after success/dependent rewrite; always reuse old presence; fall through to structured stale recovery; replace expected hash with observed hash; default a failed read; discard before reading/confirmation; swallow a post-commit cleanup error as a plain failure; let cleanup replace a primary transaction error. Pin snapshot triples, exact external bytes, forbidden dialogs, restart-call counts, and the exception type/report identity.

### 11.9 Rebase and structured dependent regression

Extend `tests/test_blast_radius.py` and `tests/test_structured_main_window.py`:

- Saved dependent result is a canonical Path, not AppAIConfig; coordinator snapshot read receives correct metadata and installs its actual new digest/presence.
- For every logical managed field, exercise `D==L`, user-only change, agreeing both-change, and disagreeing both-change. Include unchanged-file/unedited control and endpoint raw-pair cases. Assert silent adopted widgets with zero `config_changed` emissions.
- Dependent base updated while user edits only model: base adopts C, model edit survives, subsequent LLM save must not restore old base and must not be falsely stale.
- Externally added protocol present in C with no user protocol edit: adopt it; later model save preserves it. User-edited endpoint with unchanged disk survives; agreeing changes clear dirty intent; disagreeing changes block and reload resolves.
- Turn combo away and back before reconciliation: no sticky edit conflict.
- Concurrent model-mode-versus-leaf edits in both directions, including an originally absent model leaf, produce the named cross-mode conflict and preserve pending visible values. Independent OCR/text leaf edits still merge without a group-level false conflict.
- A chat2api listener transaction rewrites only selected dependent bases and leaves literal/raw/unmanaged endpoint lines unchanged; unselected dependents remain byte-identical.
- Re-read failure after successful dependent transaction keeps old owned state but disables dependent saves; does not roll back the primary transaction or claim its save failed.
- Existing sealed-byte, stale dialog snapshot, FIFO/non-regular, and rollback tests continue to pass with updated result assertions.

Red falsifications: keep all old widgets for a dirty tab; merge against worker-start draft instead of current widgets; ignore raw pair; overwrite user-only edits; omit conflict flag; return bare configs; call creating reader; invoke full `_apply_ai_config` for a base-only dependent rewrite. Exact post-save bytes and second-save behavior must expose each mutant.

### 11.10 Presets and fetch propagation

`tests/test_presets.py`, `tests/test_app_views.py`, `tests/test_model_fetcher.py`:

- Exact Anthropic record and append order; old/custom records default endpoint to None; unsupported explicit custom endpoint fails validation.
- Shared resolver used for population/matching/application; unknown id no-op; endpoint-bearing presets absent without row.
- Base+endpoint match for pinned presets; base-only match otherwise; Anthropic base plus Responses does not match Anthropic.
- Activating Anthropic sets base, env reference, Messages, clears raw evidence, and emits one final dirty event. Re-activating the current index restores all its pinned fields. Endpoint-free preset does not clear raw or change protocol.
- Mock HTTP transport asserts base headers and auth for None/Chat/Responses/Messages, including empty resolved keys; never sends both Bearer and x-api-key.
- Preserve `/v1/models` to `/models` fallback, normalization, error text, timeouts, redirect flag, token, endpoint-used field, and origin routing.
- Full view → request → worker → transport test: saved endpoint is Chat, pending combo is Messages, click Fetch, run the captured worker, and assert Messages headers. Reverse-delivery/equal-token/different-app tests continue to route by origin.

Red falsifications: populate fetch endpoint from saved config; drop request field propagation; send Bearer for Messages; change discovery path; match pinned preset by base only; rely solely on index change; clear protocol for endpoint-free presets; offer Anthropic with no combo. Each test observes the final request or draft, not only a helper's output.

### 11.11 Implementation acceptance commands

After implementation, use the integration project's existing Python environment and installed test dependencies. From the integration root, run the focused suite and then the entire suite; do not start the desktop application or upstream services to obtain unit-test evidence:

```bash
AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART=1 QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
  python -B -m pytest -q tests/test_protocols.py tests/test_protocol_capability.py \
  tests/test_models.py tests/test_app_registry.py tests/test_yaml_manager.py \
  tests/test_presets.py tests/test_model_fetcher.py tests/test_app_views.py \
  tests/test_endpoint_main_window.py tests/test_blast_radius.py tests/test_structured_main_window.py

AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART=1 QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 \
  python -B -m pytest -q
```

New named test modules above are implementation deliverables. Preserve existing fixture/API tests while updating intentionally changed interfaces. Acceptance evidence records commands, exit statuses, test counts, and the failing assertions from targeted red-phase probes; no production file or upstream checkout is a test fixture.

## 12. Implementation surface, obligations, and documentation

### 12.1 File responsibilities

| File | Required responsibility |
| --- | --- |
| `config/protocols.py` | shared vocabulary, literal predicate, exact composition/conflict, omitted-base helper |
| `services/protocol_capability.py` | child programs, parser, interpreter/source key, cache and generations |
| `config/models.py` | endpoint/preset/request fields, canonical normalization, metadata flag, snapshot |
| `config/app_registry.py` | true flags on exactly two apps |
| `config/yaml_manager.py` | metadata-aware read, non-creating snapshot, diff-only checked/legacy writer, installed digest |
| `config/structured_models.py` | path-valued `SaveResult.saved_dependents` |
| `config/blast_radius.py` | pass metadata during dependent normalization; preserve inspection rules |
| `config/structured_config.py` | sealed base-only dependent render, metadata normalization, post-commit paths |
| `config/transaction.py` | preserve a propagating primary error over cleanup failures; expose the report and installed state |
| `services/supervisor.py` | exactly-once terminal restart completion, including `FailedToStart` without `finished` |
| `services/config_jobs.py` | generation/token-owning protocol QRunnable with queued terminal result |
| `ui/app_detail_view.py` | conditional row, raw state, hint/URL, availability, snapshot loading/rebase, reload, preset and fetch propagation |
| `ui/main_window.py` | coherent snapshots, one ordered LLM commit path, typed stale/reload, per-field reconciliation, restart-completion re-probe |
| `services/model_fetcher.py` | protocol-aware auth headers only; discovery behavior otherwise unchanged |
| `config/presets.py` | typed Anthropic record and shared id resolver |
| `README.md` | short application/protocol subsection described below |
| `tests/` | concrete acceptance and falsification coverage in §11 |

This is an implementation surface, not permission to make unrelated changes. Reuse existing typed errors, transaction, interpreter selection, redactor, worker signaling, and model-fetch ownership.

### 12.2 Design-obligation closure

| Design obligation | Exact resolution |
| --- | --- |
| 1. Writer threading | §4.4–4.5: required keyword baseline in both render branches, binary installed digest return, unchanged pure renderer, all calls migrated |
| 2. Reader metadata | §4.1–4.2 and §8.4: `_config_from_document(doc, meta)` at load, snapshot, blast, dependent commit; split/ownership depend on metadata |
| 3. Dependent snapshots | §2.6 / §8.4: canonical paths in SaveResult; non-creating snapshot re-read; coherent config/hash/presence install |
| 4. Typed stale path | §8.1: LLM-specific handling before structured dialogs; retained draft, blocked save, explicit reload |
| 5. Probe generation | §5.5–5.6: capture at job creation, mutex-protected increment/eviction, cache and GUI generation checks, restart-terminal recovery |
| 6. Preset vocabulary | §2.2 / §9.1: shared Literal union and one resolver for all three lookup sites |
| 7. Fetch propagation | §9.2 / §11.10: current draft into request/worker/transport, protocol auth only |

Also preserve all review-driven invariants: per-literal partial support, unknown fails closed, removal/unchanged before capability, invalid-to-Auto forced removal, no-op before rendering but after refusal guards, source-content invalidation, no bytecode writes, exact target composition, unmanaged key ownership, three-way rebase, and `api_base_present` through every installation path.

### 12.3 README content

Under Applications Managed, add one short subsection stating:

- The three exact literals and their names.
- Auto removes `ai.endpoint`; null and empty values are not legacy.
- OpenAI protocols use Bearer auth; Messages uses x-api-key and version `2023-06-01`.
- Explicit protocol paths already contain `/v1`; enter a gateway prefix, not a base ending in `/v1`.
- Verified historical baseline: textkit 2.1.4 or newer, ai-grammar verified at `6f8c42d`; installed capability checking, not version text, decides acceptance.
- Unsupported/partial builds can retain or remove stored values; unverifiable builds cannot receive a new/changed value.

No claim of general configuration validity, provider connectivity, sandboxing, or automatic base repair is permitted.

## 13. Risks and out of scope

1. **Imports execute target top-level code.** Programs themselves contain no file/network operation; imported modules may write files or open sockets. Bytecode suppression prevents `__pycache__`, not arbitrary side effects. The timeout bounds direct child execution, not all external descendant behavior or filesystem latency.
2. **Probe/loader drift.** The probe verifies known upstream interfaces, not the entire candidate config. Missing/changed interfaces fail unknown; a per-value rejection is not a general diagnosis. Dependencies or imports outside the enumerated source tree are not fully fingerprinted. Restart invalidation is the explicit recovery action.
3. **Concurrent external changes.** Source-key rechecks and generation checks prevent known stale publication. They cannot make probing, external checkout replacement, config editing, and a later service launch one atomic event. Loaded config digests prevent cooperative editor saves from overwriting intervening config bytes; existing sidecar locks do not compel unrelated writers to cooperate.
4. **Cold gate cost.** Save remains synchronous. A keyed cache hit avoids a child, but a cold miss can block the GUI for child timeout plus local scan/spawn/cleanup work. Overflow deliberately favors correctness over caching speed.
5. **No generic LLM service validator.** Invalid base URL, model, secret, unmanaged nested endpoint, token setting, or unrelated provider option can still fail the target at startup. The request preview is composition, not connectivity verification. Explicit malformed values are not silently repaired.
6. **Intentional destructive toggle.** Split/unified conversion retains its existing documented section-removal behavior. Protocol-only and other ordinary changes must never accidentally take that path.
7. **Transaction uncertainty.** Rollback may report unknown state. Do not advance an owned snapshot or promise restoration in that case; retain the report and require reload.
8. **Diagnostic limits.** Reuse the established scrubber and plain-text rendering, but do not claim to sanitize every arbitrary unlabelled secret emitted by imported code.

Out of scope: yt2txt protocol selection; changes to structured schemas or launcher gating; generic LLM candidate validation; editing `messages_default_max_tokens`; per-task provider editing or endpoint overrides; protocol-aware health checks or restart authorization; provider request/temperature behavior; general URL normalization; automatic upgrades; new custom-preset UI; background/asynchronous LLM saves; and any implementation or app execution during this document-only drafting task.

## 14. Resolved ambiguities

The following choices are normative and close the remaining specification-level questions:

1. **A01 — Explicit vocabulary versus legacy.** `None` is allowed in configuration memory but is false for `is_valid_endpoint`; disk legacy is absence only. The later design requirement for a shared preset Literal supersedes its earlier shorthand `Optional[str]`; fetch hints intentionally remain optional strings.
2. **A02 — Canonical values and split classification.** Strip base/key whitespace, turn blank model controls into None, and clear inactive model values for equality. Gate split classification by metadata while preserving textkit's existing mapping-based split interpretation; provider-only sections do not authorize deleting its inactive base model.
3. **A03 — Invalid raw ownership.** Carry raw evidence through every unrelated draft change; compare endpoint and raw as one rebase field. Only an explicit Auto/literal activation or pinned-preset action clears it, and baseline raw evidence forces a repair mutation even when both normalized endpoints are None.
4. **A04 — Read creation semantics.** Snapshot reads never create/copy missing configs. Preserve the old example-copy behavior only in the compatibility reader and initial LLM load; reload/reconciliation/checked save remain non-creating.
5. **A05 — Omitted base and presence advancement.** Use mode-specific upstream defaults only for an untouched omitted base; pending base edits use their value immediately. A committed base edit sets presence true, while a protocol-only omitted-base save leaves it false. The preview and gate share this computation.
6. **A06 — URL helper scope.** Preserve the exact ai-grammar legacy trailing-slash quirk and textkit concatenation. The conflict check inspects path only, catches partial-URL parsing failures, and never repairs the base; it applies even to unchanged explicit endpoints.
7. **A07 — Probe evidence and drift.** Use the concrete guard/validator programs, not field presence or a full real-config loader. Structurally missing/unusable probe interfaces are unknown. Require a final, single matching nonce sentinel and an exact, complete accepted/rejected partition; nonzero exits never prove rejection.
8. **A08 — Partial versus unsupported.** One or two verified literals means PARTIAL, even where early design test prose called a single rejected literal “unsupported.” Only zero accepted literals means UNSUPPORTED; UI and gate use the actual accepted subset.
9. **A09 — Cache encoding and overflow.** Full keys hash sorted paths and file bytes with explicit delimiters and stated exclusions. The design's “source mtime change” test means a source edit; a mtime-only touch intentionally stays cached under the mandated content-based key. Exactly 200 files may cache; more than 200 uses a specified coarse tuple but skips cache lookup and insertion entirely. Scan failures do not reuse old support.
10. **A10 — Generations, tokens, and restart timing.** Capture generation at job creation, check before queued work and before cache/UI publication, and recheck source identity on uncached completion. Invalidate/re-probe at each attributable terminal saved/manual restart attempt, including failure, not merely at dispatch; consolidate the shadowed restart helper.
11. **A11 — Gate order.** The execution sequence is 1, 1a, 2, 3, 4, 0, 5, 6, then 7. No-op cannot hide a refusal; removal/unchanged cannot be blocked by capability, but do not bypass load/conflict/stale protection or the explicit-base rule.
12. **A12 — No-op effects.** Both save buttons skip rendering/writing/backups on canonical equality. Save-and-Restart requests only restart, and existing saved-status wording is retained without claiming that bytes were newly written.
13. **A13 — Checked versus compatibility commit.** The required baseline reaches both writer branches. MainWindow always supplies its loaded digest and uses the existing timestamped-backup transaction; the optional unchecked branch retains the old fixed `.bak` behavior. Successful writes return the actual installed-byte hash. Failures raised before the commit point never advance the snapshot; `CommittedWriteError` installs the committed snapshot because the bytes are already on disk.
14. **A14 — Field diff and destructive exception.** Ordinary saves touch only changed leaves and never emit empty model strings or defaults. Only a real mode toggle removes inactive sections; deleting the last split model leaf retains its mapping, and selecting split mode may intentionally create empty task mappings.
15. **A15 — Dependent result form.** Choose canonical Paths in SaveResult, followed by metadata-aware non-creating snapshot reads. Publish new baseline, digest, and presence together; a failed post-commit reread blocks that dependent rather than undoing the primary save.
16. **A16 — Rebase notification and conflicts.** `adopt_saved_baseline` returns ordered conflicting field names. Merge current widgets per managed field, install C as baseline even on a conflict, retain conflicting user text, and block until confirmed reload. Concurrent mode-versus-model-leaf edits conservatively conflict instead of hiding/dropping pending values; independent model leaves still merge. No whole-tab dirty shortcut or sticky protocol-edit flag is allowed.
17. **A17 — Reload draft policy.** A same-digest reload without conflict preserves pending edits. A changed-digest reload with edits requires Discard/Cancel confirmation; any baseline conflict requires that reset even if its digest matches. Read failure or Cancel discards nothing, and LLM stale recovery never enters structured dialogs.
18. **A18 — Availability versus current selection.** Enable Auto plus verified literals plus a saved valid literal exemption; unknown enables all normal choices but not new-value saves. A now-rejected pending selection remains visible and is not silently reset. Invalid display state is not a fifth protocol.
19. **A19 — Preset semantics and activation.** One resolver backs all id lookup; endpoint-free presets leave protocol/raw untouched, pinned presets explicitly apply both. Filter pinned presets only when no protocol row exists. Programmatic pinned selection may display a rejected literal, but cannot bypass the gate. Both activation and index-change delivery are handled idempotently.
20. **A20 — Fetch propagation and empty keys.** Use one current draft through the request and worker. Preserve discovery URLs/errors/timeouts and Bearer omission for an empty key; Messages uses its version header and an empty x-api-key when resolution is empty, never Bearer. Omitted-base discovery remains existing behavior, distinct from preview defaults.
21. **A21 — Error/UI precedence and copy.** Pin gate, recovery, probe, unavailable, and dynamic copy templates; all render as plain text. Capability completion cannot erase a blocking error or re-enable blocked saves; initial failed-load controls cannot publish an owned fallback draft. Existing no-op/success/restart messages remain compatible. Unknown transaction state requires reload, and a post-commit display failure retains the successful installed snapshot, rather than claiming unchanged disk or rollback.
22. **A22 — Documentation and acceptance authority.** Release/commit references document the verified historical baseline, not a version-based capability shortcut. Behavioral tests through real coordinator seams and mechanism-specific red falsifications are required; an import failure or helper-only green test is not acceptance evidence.
