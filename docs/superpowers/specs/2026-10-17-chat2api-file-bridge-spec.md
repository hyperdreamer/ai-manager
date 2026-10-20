# chat2api and file-bridge management — technical specification

Date: 2026-10-17. Authority: [approved revision-4 design](2026-10-17-chat2api-file-bridge-design.md).

This document specifies implementation of that design. The design takes precedence if a conflict is found. §14 records decisions that were open during drafting and are now resolved by explicit user decision; they are normative, not pending. This specification does not implement or deliver either target.

## 1. Source baseline and scope

Repository abbreviations in source citations are rooted as follows. A citation such as `A/src/ai_manager/config/models.py:36` means the named file and line in the inspected baseline, not a proposed line number.

```text
A = /data/home/guest/Development/ai/ai-manager
A implementation checkout = /data/home/henry-arch/.local/state/pi/project-manager/worktrees/6f027a5a576a8d21/pm-run-20261017-160734-18a296e5/integration
B = /data/home/guest/Development/ai/chat2api
C = /data/home/guest/Development/ai/file-bridge

Inspected git revisions:
A primary: b220669
A implementation checkout: a6fc46b (includes the approved design)
B: c40e3c6
C: 6ac6325
```

Existing behavior relied upon by this specification:

| Evidence | Consequence |
| --- | --- |
| `A/src/ai_manager/config/models.py:36`, `A/src/ai_manager/config/app_registry.py:6` | Metadata currently has no kind discriminator and the registry has three entries. Add explicit kind dispatch. |
| `A/src/ai_manager/config/yaml_manager.py:12` | Reuse the round-trip engine: `typ="rt"`, preserved quotes, mapping indent 2, sequence indent 4, offset 2, width 4096. |
| `A/src/ai_manager/config/yaml_manager.py:28`, `A/tests/test_yaml_manager.py:49` | LLM loading can copy an example; the existing two-argument writer produces `config.yaml.bak`. Preserve that compatibility path. |
| `A/src/ai_manager/config/yaml_manager.py:80` | The writer assigns API base, API key, and model fields and immediately backs up/replaces. It cannot stage D7 updates. |
| `A/src/ai_manager/ui/main_window.py:206`, `A/src/ai_manager/ui/main_window.py:221` | Loading currently defaults errors to `AppAIConfig`; dirty state compares normalized LLM models. New kinds need explicit load errors and their own comparator. |
| `A/src/ai_manager/ui/app_detail_view.py:40`, `A/src/ai_manager/ui/app_detail_view.py:266` | Preserve the four signal names and `get_current_draft`. |
| `A/src/ai_manager/ui/main_window.py:258`, `A/src/ai_manager/ui/app_detail_view.py:338` | Responses currently follow selection, with tokens allocated per view. Capture request origin; tokens alone are insufficient. |
| `A/src/ai_manager/ui/app_detail_view.py:277`, `A/src/ai_manager/services/supervisor.py:159` | Both kinds need the reported-log-path memory and fallback log-path behavior. |
| `A/src/ai_manager/ui/app_sidebar.py:43` | Sidebar currently always uses the metadata port. Introduce a separate configured-port cache. |
| `A/src/ai_manager/config/presets.py:16` | Correct `CHAT2API_API_KEY` to `CHAT2API_TOKEN`. |
| `B/start.sh:15`, `B/start.sh:18`, `B/start.sh:29` | Preserve script-directory cwd, activation precedence, and uvicorn flags; add config-derived listener flags. |
| `B/app/config.py:28`, `B/app/config.py:80` | Service defaults are host `127.0.0.1`, port 8000, auth env `CHAT2API_TOKEN`; loader loads dotenv, honors `CHAT2API_CONFIG`, and coerces non-object roots. The editor must reject that last shape. |
| `B/app/config.py:64`, `B/app/main.py:82` | Auth validation is a startup configuration check; login and discovery follow it and are outside save validation. |
| `B/app/registry.py:31`, `B/app/registry.py:86` | Registry defines four provider names and rejects unknown providers. |
| `B/config.example.json:40` | Shipped model routes can omit `options`. Preserve absence. |
| `C/main.py:34`, `C/main.py:161` | Defaults are `~`, 8964, 1,048,576 bytes; reject unknown keys, bool/string integers, and limits above 104,857,600 bytes. Relative roots use config-parent resolution. |
| `C/main.py:104`, `C/main.py:132` | Service YAML rejects duplicate keys and non-mapping roots; comment-only input is a special empty mapping. |
| `C/main.py:484`, `C/main.py:1063` | Root must exist outside the application directory and be readable/writable; the configured port controls an IPv4 loopback socket. |
| `A/pyproject.toml:10`, `A/tests/conftest.py:6`, `B/pyproject.toml:23`, `C/requirements-dev.txt:6` | Existing dependencies cover rendering and automated tests; C has a pytest harness and remains a reference only. |

Target A implements management, editors, validation, transaction support, tests, and documentation. Target B changes only production file `start.sh`; `tests/test_launcher.py` is the acceptance test expressly required by design §9. No production Python file in B changes. No file in C changes. Target B is a prerequisite for delivering A; both remain one delivery unit with separate repository decisions.

## 2. Types, schemas, and invariants

All Python below is normative. Ellipses occur only in interface declarations, never in field definitions or validation rules. Dataclasses are internal records: except for the explicit `__post_init__` methods, their validation is performed by the owning operation described below. Do not serialize a Pydantic schema back over the loaded tree; schemas validate a candidate, while the original tree plus addressed mutations determine its bytes.

### 2.1 Existing metadata and fetch request

Replace these two class definitions in `A/src/ai_manager/config/models.py`; retain the other models and their current fields. Add the listed imports and alias.

```python
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator

ConfigKind = Literal["llm", "chat2api", "file-bridge"]


class AppMetadata(BaseModel):
    """Metadata describing a managed target application."""
    id: str
    display_name: str
    relative_path: Path
    config_file_name: str = "config.yaml"
    example_config_file_name: str = "config.example.yaml"
    default_port: int
    supports_split_models: bool = False
    description: str = ""
    config_kind: ConfigKind = "llm"

    @field_validator("config_kind", mode="before")
    @classmethod
    def validate_config_kind(cls, value: object) -> object:
        if type(value) is not str or value not in (
            "llm", "chat2api", "file-bridge"
        ):
            raise ValueError(
                f"Unknown config_kind {value!r}; expected llm, chat2api, or file-bridge."
            )
        return value


class ModelFetchRequest(BaseModel):
    """Request payload sent to background model fetcher worker."""
    token: int
    api_base: str
    api_key: str
    app_id: str = Field(strict=True, min_length=1)
```

`config_kind` omission means `llm` for old construction sites. Unknown values, `None`, numbers, and misspellings produce Pydantic `ValidationError` containing the validator message. `app_id` is required: no default to current selection and no normalization of an empty name. Existing request field coercion is unchanged. `ModelFetchResponse` remains unchanged (`A/src/ai_manager/config/models.py:81`); routing captures `request.app_id` in MainWindow.

Every runtime dispatcher must also use an exhaustive branch with a final `UnknownConfigKindError`, protecting against bypasses such as `model_construct` and bad plugin/test objects.

### 2.2 Shared structured records

Create `A/src/ai_manager/config/structured_models.py` with these definitions. `JsonValue` is deliberately represented by `Any`: free-form provider options retain JSON types, nesting, insertion order, and unknown keys. Load/render reject non-JSON values at their format boundary.

```python
from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ai_manager.config.models import AppAIConfig, AppMetadata

StructuredKind = Literal["chat2api", "file-bridge"]
KeyPath = tuple[str, ...]
ReadOnlyReason = Literal[
    "symlink", "non-writable", "yaml-anchors-aliases",
    "non-dict-root", "load-error", "missing-config",
]
FinalFileState = Literal["new", "restored", "unknown"]
TransactionPhase = Literal[
    "prepare", "backups", "stage", "replace_all", "rollback", "complete"
]


@dataclass(frozen=True)
class FieldIssue:
    address: KeyPath
    message: str


@dataclass(frozen=True)
class Mutation:
    address: KeyPath
    operation: Literal["set", "delete"]
    value: Any = None

    def __post_init__(self) -> None:
        if (
            type(self.address) is not tuple or not self.address
            or any(type(k) is not str for k in self.address)
        ):
            raise ValueError("A mutation address must be a non-empty tuple of string keys.")
        if self.operation not in ("set", "delete"):
            raise ValueError("Mutation operation must be set or delete.")
        if self.operation == "delete" and self.value is not None:
            raise ValueError("A delete mutation cannot carry a value.")


@dataclass(frozen=True)
class StructuredDoc:
    kind: StructuredKind
    path: Path
    resolved_path: Path
    doc: MutableMapping[str, Any]
    raw_bytes: bytes
    raw_sha256: bytes | None
    existed: bool
    mode: int | None
    read_only_reasons: tuple[ReadOnlyReason, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    raw_option_edits: dict[str, str] = field(default_factory=dict)
    input_issues: tuple[FieldIssue, ...] = ()
    create_requested: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ("chat2api", "file-bridge"):
            raise ValueError("StructuredDoc kind must be chat2api or file-bridge.")
        if not isinstance(self.doc, MutableMapping):
            raise ValueError("StructuredDoc.doc must be a mapping.")
        if self.existed:
            if self.raw_sha256 != hashlib.sha256(self.raw_bytes).digest():
                raise ValueError("raw_sha256 must hash raw_bytes.")
            if self.mode is None:
                raise ValueError("An existing document must retain its mode.")
        elif self.raw_bytes != b"" or self.raw_sha256 is not None or self.mode is not None:
            raise ValueError("An absent document has no bytes, digest, or mode.")


@dataclass(frozen=True)
class ValidationResult:
    scope: Literal["service", "manager-only"]
    notice: str
    detail: str = ""


@dataclass
class TransactionReport:
    phase: TransactionPhase
    files: dict[Path, FinalFileState] = field(default_factory=dict)
    backups: dict[Path, Path] = field(default_factory=dict)
    replaced: tuple[Path, ...] = ()
    restore_failures: dict[Path, str] = field(default_factory=dict)
    error: str | None = None
    committed: bool = False


@dataclass(frozen=True)
class SaveResult:
    document: StructuredDoc
    transaction: TransactionReport
    validation: ValidationResult
    saved_dependents: dict[str, AppAIConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class DependentMatch:
    meta: AppMetadata
    path: Path
    doc: MutableMapping[str, Any]
    raw_bytes: bytes
    raw_sha256: bytes
    saved_config: AppAIConfig
    old_api_base: str
    new_api_base: str
    auth_warning: str | None = None


@dataclass(frozen=True)
class LauncherProbeResult:
    passed: bool
    detail: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
```

Additional invariants enforced by public operations:

- Hashes are raw 32-byte SHA-256 digests, not UTF-8 hex strings. Display with `.hex()` only in diagnostics. `None` means path absent, distinct from the digest of an empty file.
- `path` is the absolute requested path; `resolved_path` resolves the parent directory and retains the leaf name after rejecting a symlink leaf. Candidate files, locks, backups, and replacement use `resolved_path`. Do not resolve a leaf symlink before `lstat`.
- `doc` is the load-time tree, including ruamel metadata. A view never mutates it in place. Draft creation and render use deep copies, including nested options. Frozen dataclasses do not make their nested dictionaries immutable; ownership enforces this rule.
- `mode` is `stat.S_IMODE(lstat_result.st_mode)`. Mode preservation covers these bits, not ownership, ACLs, or extended attributes.
- A missing document initially has `doc={}`, `existed=False`, `create_requested=False`, and `("missing-config",)` reasons. Explicit Create from Example replaces its tree with a parsed example, sets `create_requested=True`, and clears that reason. The target still has no bytes/hash/mode until committed.
- Launcher-gate state belongs to the view/session cache, never `read_only_reasons`: a failed/pending gate restricts only host/port and dependent rewriting, while the document's other fields remain renderable/saveable.
- `raw_option_edits` maps model name to the current raw-area JSON text. It contains only edited raw areas; untouched areas are read from `doc`. Invalid text is retained so dirty/close protection does not discard it.
- `input_issues` holds invalid widget input before it can become a valid mapping, including duplicate row names. Valid drafts have an empty tuple. Save fails if this tuple is nonempty.
- `TransactionReport.files` covers every participating target on a returned report. `new` means the new staged bytes reached that path and directory fsync succeeded. `restored` means the pre-transaction state is verified, including a target never replaced or an originally absent target restored to absence. `unknown` means replacement/restoration/durability could not be established. `committed=True` requires every file to be `new` and no failures.
- `DependentMatch` records bytes/hash from one read of an existing dependent, not a fresh hash paired with an old parsed tree. It is immutable by ownership, like `StructuredDoc`.

`saved_dependents` contains only selected and successfully committed D7 dependents, keyed by app id, derived from the sealed bytes that reached disk. It is empty for a one-file save. A failed transaction returns no `SaveResult` and therefore cannot update a saved dependent baseline.

### 2.3 Per-kind validation schemas

Create `A/src/ai_manager/config/structured_schema.py`. These schemas validate the whole candidate after applying mutations. Validation defaults describe effective service defaults; omitted keys are not inserted into serialized output.

```python
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationInfo,
    field_validator, model_validator,
)

Port = Annotated[StrictInt, Field(ge=1, le=65535)]
TextLimit = Annotated[StrictInt, Field(ge=0, le=104_857_600)]
ProviderName = Literal["echo", "gemini_webapi", "copilot_webapi", "browser"]
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Chat2ApiServerSchema(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    host: StrictStr = Field(default="127.0.0.1", min_length=1)
    port: Port = 8000
    auth_token_env: StrictStr | None = "CHAT2API_TOKEN"

    @field_validator("host")
    @classmethod
    def validate_loopback_host(cls, value: str) -> str:
        """R-HOST-LOOPBACK: exact loopback spelling, no stripping."""
        if value in ("127.0.0.1", "::1"):
            return value
        if value.lower() == "localhost":
            return value
        raise ValueError(
            "Host must be a loopback address (127.0.0.1, localhost, or ::1). "
            "Binding a wildcard or external interface is not supported for "
            "this local service."
        )

    @field_validator("auth_token_env")
    @classmethod
    def validate_auth_name(cls, value: str | None) -> str | None:
        if value is not None and ENV_NAME_RE.fullmatch(value) is None:
            raise ValueError("Auth token environment variable must be null or a valid environment variable name.")
        return value


class Chat2ApiRouteSchema(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    provider: ProviderName
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options", mode="before")
    @classmethod
    def validate_options_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("Model options must be a mapping when present.")
        return value


class Chat2ApiSchema(BaseModel):
    model_config = ConfigDict(extra="allow", validate_default=True)
    # Validate a raw mapping default through the same shape guard as explicit input.
    server: Chat2ApiServerSchema = Field(default_factory=dict)
    models: dict[str, Chat2ApiRouteSchema] = Field(default_factory=dict)

    @field_validator("server", mode="before")
    @classmethod
    def validate_server_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("Server must be a mapping when present.")
        return value

    @field_validator("models", mode="before")
    @classmethod
    def validate_models_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("Models must be a mapping.")
        for name, route in value.items():
            if type(name) is not str or name == "":
                raise ValueError("Model names must be non-empty strings.")
            if not isinstance(route, dict):
                raise ValueError(f"Model {name!r} must be a mapping.")
        return value


class FileBridgeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)
    save_root: StrictStr = "~"
    max_text_bytes: TextLimit = 1_048_576
    port: Port = 8964

    @field_validator("save_root")
    @classmethod
    def validate_root_text(cls, value: str) -> str:
        if not value or value.isspace():
            raise ValueError("Save root must not be empty or whitespace-only.")
        return value

    @model_validator(mode="after")
    def validate_root_directory(self, info: ValidationInfo) -> FileBridgeSchema:
        context = info.context or {}
        if "config_path" not in context or "app_dir" not in context:
            raise ValueError("File-bridge validation requires config_path and app_dir.")
        try:
            config_path = Path(context["config_path"])
            app_dir = Path(context["app_dir"]).resolve()
            root = Path(self.save_root).expanduser()
            if not root.is_absolute():
                root = config_path.parent / root
            root = root.resolve()
            if root == app_dir or app_dir in root.parents:
                raise ValueError("Save root must not be inside the application directory.")
            root_stat = root.stat()
            if not stat.S_ISDIR(root_stat.st_mode):
                raise ValueError("Save root is not a directory.")
            if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
                raise ValueError("Save root must be readable and writable.")
            with os.scandir(root) as entries:
                next(entries, None)
            with tempfile.TemporaryFile(dir=root):
                pass
        except FileNotFoundError as exc:
            raise ValueError("Save root does not exist.") from exc
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Save root cannot be used: {exc}") from exc
        return self
```

Pass a plain deep-copy candidate to Pydantic; retain the original ruamel tree for rendering. `FileBridgeSchema.model_validate(candidate, context={"config_path": target_resolved_path, "app_dir": meta.relative_path})` is mandatory. Convert its model-level path issue to address `("save_root",)` for UI marking. Catch path `ValueError` from expansion/resolution at the validation boundary as a field issue too; it must not escape the save worker as an internal error.

Port and text-limit checks reject booleans, numeric strings, and floats. Host/model names are nonempty without silent trimming; this schema does not impose DNS syntax, reachability, or credential checks. Duplicate names are detected before a table is collapsed into a dictionary, and duplicate JSON keys are rejected at load; a dictionary alone cannot prove that input names were unique.

For C, unknown top-level keys are preserved by the renderer but fail schema validation. This follows `C/main.py:169`; preserving a value is not a promise the service accepts it. For B, unknown top-level, server, route, and option data remain in the tree even though the service's Pydantic models may ignore them.

### 2.4 Declarative form schema

In `structured_schema.py`, define the following form records and inventories. They select widgets; they do not insert option defaults or close the free-form options mapping.

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    control: Literal["text", "integer", "nullable-text", "directory"]
    minimum: int | None = None
    maximum: int | None = None
    annotation: str = ""


@dataclass(frozen=True)
class OptionSpec:
    key: str
    control: Literal["text", "integer", "boolean", "secret"]


SERVER_FIELDS = (
    FieldSpec("host", "Host", "text"),
    FieldSpec("port", "Port", "integer", 1, 65535),
    FieldSpec("auth_token_env", "Auth token env var", "nullable-text"),
)
FILE_BRIDGE_FIELDS = (
    FieldSpec("save_root", "Save root", "directory"),
    FieldSpec("max_text_bytes", "Maximum text bytes", "integer", 0, 104_857_600,
              "0 = no limit"),
    FieldSpec("port", "Port", "integer", 1, 65535),
)
COMMON_LOGIN_OPTIONS = (
    OptionSpec("account", "secret"),
    OptionSpec("password", "secret"),
    OptionSpec("interactive_login", "boolean"),
    OptionSpec("browser_profile_dir", "text"),
)
PROVIDER_OPTIONS = {
    "echo": (OptionSpec("prefix", "text"),),
    "gemini_webapi": COMMON_LOGIN_OPTIONS + (
        OptionSpec("secure_1psid_env", "text"),
        OptionSpec("secure_1psidts_env", "text"),
        OptionSpec("timeout", "integer"),
        OptionSpec("gemini_model", "text"),
    ),
    "copilot_webapi": COMMON_LOGIN_OPTIONS + (
        OptionSpec("access_token", "secret"),
        OptionSpec("access_token_env", "text"),
        OptionSpec("timezone", "text"),
        OptionSpec("chat_timeout", "integer"),
        OptionSpec("copilot_mode", "text"),
    ),
    "browser": (
        OptionSpec("account", "secret"),
        OptionSpec("password", "secret"),
        OptionSpec("headless", "boolean"),
        OptionSpec("user_data_dir", "text"),
        OptionSpec("timeout", "integer"),
        OptionSpec("response_appear_timeout", "integer"),
        OptionSpec("gemini_model", "text"),
    ),
}
SECRET_OPTION_KEYS = frozenset({"account", "password", "access_token"})
```

Inventory evidence: `B/providers/echo.py:37`; `B/app/startup_login.py:88`; `B/app/startup_login.py:190`; `B/providers/gemini_webapi.py:493`; `B/providers/gemini_webapi.py:698`; `B/providers/gemini_webapi.py:726`; `B/providers/copilot_webapi.py:349`; `B/providers/copilot_webapi.py:464`; `B/providers/copilot_webapi.py:538`; `B/providers/copilot_webapi.py:703`; `B/providers/browser_gemini.py:953`; `B/providers/browser_gemini.py:1024`.

Any key not in a provider's inventory remains in its collapsed raw area. Browser URL/selector overrides are examples (`B/providers/browser_gemini.py:470`). Existing values with a type different from a convenience widget's type are shown as raw JSON until explicitly edited; never coerce them on load. Secrets are masked even if a provider switch makes them raw; present secret keys have their own masked editors and are omitted from the raw-area text. A provider switch preserves the complete options tree and only changes the inventory classification.

Absent optional fields show a non-dirty effective default or an `Absent` placeholder. Optional option controls have an explicit presence toggle; toggling it off addresses deletion. Auth has three states: absent, explicit null (`Authentication disabled`), or a named variable. Null and absent must not collapse into each other.

### 2.5 Exceptions

Create `A/src/ai_manager/config/config_errors.py` with these exact public exception types. Preserve chained causes for diagnostics. Error messages below are UI templates, not instructions to dump credentials into logs.

```python
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_manager.config.structured_models import FieldIssue, TransactionReport


class ConfigError(Exception):
    pass


class UnknownConfigKindError(ConfigError, ValueError):
    def __init__(self, kind: object) -> None:
        super().__init__(
            f"Unknown config_kind {kind!r}; expected llm, chat2api, or file-bridge."
        )
        self.kind = kind


class ConfigLoadError(ConfigError):
    def __init__(self, path: Path, detail: str, reason: str = "load-error") -> None:
        super().__init__(f"Cannot load configuration {path}: {detail}")
        self.path = path
        self.detail = detail
        self.reason = reason


class ConfigShapeError(ConfigLoadError):
    pass


class SymlinkConfigError(ConfigLoadError):
    def __init__(self, path: Path) -> None:
        super().__init__(path, "Configuration path is a symlink; editing is disabled.", "symlink")


class ReadOnlyConfigError(ConfigError):
    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.detail = detail


class MissingExampleError(ConfigLoadError):
    pass


class ConfigValidationError(ConfigError):
    def __init__(self, issues: tuple[FieldIssue, ...]) -> None:
        super().__init__("Configuration has invalid fields; nothing was saved.")
        self.issues = issues


class ServiceValidationError(ConfigError):
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        super().__init__("Service validator rejected the configuration; nothing was saved.")
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ServiceValidationTimeout(ConfigError):
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        super().__init__("Service validator timed out after 10 seconds; nothing was saved.")
        self.stdout = stdout
        self.stderr = stderr


class InterpreterUnavailableError(ConfigError):
    pass


class StaleDocumentError(ConfigError):
    def __init__(
        self, path: Path, expected_sha256: bytes | None,
        actual_sha256: bytes | None,
    ) -> None:
        super().__init__("Configuration changed on disk; save refused.")
        self.path = path
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256


class TransactionError(ConfigError):
    def __init__(self, report: TransactionReport) -> None:
        super().__init__(report.error or "Configuration transaction failed.")
        self.report = report
```

No special exception means “force.” `FileNotFoundError` while reading an intentionally missing new-kind target becomes a missing `StructuredDoc`, not a load-error dialog. Errors reading an example become `MissingExampleError`. Other filesystem errors at load become `ConfigLoadError`. Pydantic `ValidationError`, JSON parse errors in edited raw options, and control-character failures become `ConfigValidationError` before reaching MainWindow.

## 3. Module and file layout

Paths below identify delivery files at their canonical repository locations; A changes are implemented in its integration worktree. No dependency or version change is required.

### 3.1 New production files and their public interfaces

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_models.py`** — all records in §2.2. No I/O.

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/config_errors.py`** — exceptions in §2.5. No I/O.

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_schema.py`** — schemas, form records, and inventories in §2.3–2.4, plus:

```python
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from ai_manager.config.structured_models import Mutation, StructuredKind


def validate_written_scalars(mutations: tuple[Mutation, ...]) -> None: ...

def validate_in_process(
    kind: StructuredKind, candidate: Mapping[str, Any], *,
    config_path: Path, app_dir: Path,
) -> None: ...
```

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_config.py`** — parse, addressed render, explicit example initialization, and save orchestration:

```python
from pathlib import Path
from ai_manager.config.structured_models import (
    DependentMatch, Mutation, SaveResult, StructuredDoc, StructuredKind,
)


def load(kind: StructuredKind, path: Path) -> StructuredDoc: ...

def load_example(
    kind: StructuredKind, path: Path, example_path: Path,
) -> StructuredDoc: ...

def effective_mutations(doc: StructuredDoc) -> tuple[Mutation, ...]: ...

def render(kind: StructuredKind, doc: StructuredDoc) -> bytes: ...

def commit(
    kind: StructuredKind, path: Path, doc: StructuredDoc,
    expected_sha256: bytes | None, *,
    dependents: tuple[DependentMatch, ...] = (),
) -> SaveResult: ...
```

`load` and `load_example` read only. `render` and `effective_mutations` perform no filesystem operation. `commit` owns validation and one transaction, including when no dependents are selected. It returns a new load baseline from the exact successfully written bytes, rather than clearing flags on a stale input object. App directory for these default config locations is the target's parent (§14 covers overridden service paths).

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/transaction.py`** — sidecar locks, backups, staging, replace, rollback:

```python
from __future__ import annotations
from pathlib import Path
from types import TracebackType
from ai_manager.config.structured_models import TransactionReport


class Transaction:
    def __init__(self) -> None: ...
    def __enter__(self) -> Transaction: ...
    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, tb: TracebackType | None,
    ) -> bool: ...
    def prepare(
        self, paths: list[Path], expected: dict[Path, bytes | None],
    ) -> None: ...
    def backups(self) -> None: ...
    def stage(self, rendered: dict[Path, bytes]) -> None: ...
    def replace_all(self) -> TransactionReport: ...
    def rollback(self, report: TransactionReport) -> TransactionReport: ...
```

The `None` digest extension supports an explicitly created missing target. Context exit always cleans temps and closes/unlocks descriptors; it returns `False`. No target mutation occurs before `replace_all`. A failure during replacement invokes rollback before propagation as `TransactionError`.

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/blast_radius.py`** — snapshots of the three LLM dependents and exact API-base mutation:

```python
from collections.abc import Mapping
from ai_manager.config.models import AppAIConfig, AppMetadata
from ai_manager.config.structured_models import DependentMatch, StructuredDoc


def find_affected_dependents(
    apps: Mapping[str, AppMetadata], before: StructuredDoc,
    after: StructuredDoc,
) -> tuple[DependentMatch, ...]: ...

def auth_mismatch_warning(
    dependent: AppAIConfig, auth_token_env: str | None,
) -> str | None: ...
```

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/app_interpreter.py`** — interpreter selection and import probe:

```python
from pathlib import Path
from ai_manager.config.structured_models import StructuredKind


def resolve_app_interpreter(app_dir: Path) -> Path: ...

def verify_app_interpreter(
    kind: StructuredKind, app_dir: Path, interpreter: Path,
) -> None: ...
```

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/service_validation.py`** — adjacent candidate, stage 3, timeout/reaping:

```python
from pathlib import Path
from ai_manager.config.structured_models import StructuredKind, ValidationResult


def validate_candidate(
    kind: StructuredKind, target_path: Path, app_dir: Path, rendered: bytes,
) -> ValidationResult: ...
```

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/launcher_gate.py`** — session gate and behavioral subprocess probe:

```python
from pathlib import Path
from ai_manager.config.structured_models import LauncherProbeResult


def probe_launcher(app_dir: Path, *, timeout_s: float = 10.0) -> LauncherProbeResult: ...
```

MainWindow caches the result per resolved chat2api app directory for its lifetime. `probe_launcher` itself is uncached so subprocess tests can exercise each case.

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/config_jobs.py`** — Qt worker ownership, with object results as the concrete records/exceptions above:

```python
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from ai_manager.config.models import AppMetadata
from ai_manager.config.structured_models import DependentMatch, StructuredDoc


class ConfigJobSignals(QObject):
    save_finished = pyqtSignal(str, object)  # app_id, SaveResult
    save_failed = pyqtSignal(str, object)    # app_id, ConfigError
    probe_finished = pyqtSignal(str, object) # app_id, LauncherProbeResult


class StructuredSaveJob(QRunnable):
    def __init__(
        self, meta: AppMetadata, draft: StructuredDoc,
        dependents: tuple[DependentMatch, ...] = (),
    ) -> None: ...
    def run(self) -> None: ...


class LauncherProbeJob(QRunnable):
    def __init__(self, meta: AppMetadata) -> None: ...
    def run(self) -> None: ...
```

Each job exposes `signals: ConfigJobSignals`. `run` emits exactly one terminal signal. MainWindow retains jobs until terminal handling and uses queued Qt delivery into MainWindow slots. Workers never touch widgets or display dialogs. Save jobs receive owned snapshots; the GUI cannot mutate their nested trees.

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/structured_config_view.py`** — generic declarative form for the two structured kinds, with methods/signals in §8. Models-table helpers are private methods `_add_model`, `_remove_model`, `_expand_model`, `_on_provider_changed`, `_on_raw_options_changed`, `_on_field_changed`, `_emit_save`, `_review_changes`, and `_create_from_example`. All edits build addressed mutations against the loaded tree.

**`/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/config_dialogs.py`** — dialog results, not disk writes:

```python
from pathlib import Path
from typing import Literal
from PyQt6.QtWidgets import QDialog, QWidget
from ai_manager.config.structured_models import DependentMatch, TransactionReport


class ReviewChangesDialog(QDialog):
    def __init__(
        self, before: bytes, after: bytes, path: Path,
        parent: QWidget | None = None,
    ) -> None: ...


class BlastRadiusDialog(QDialog):
    def __init__(
        self, matches: tuple[DependentMatch, ...],
        parent: QWidget | None = None,
    ) -> None: ...
    def selected_app_ids(self) -> tuple[str, ...]: ...


class StaleDocumentDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None: ...
    def choice(self) -> Literal["reload", "diff", "cancel"]: ...


class TransactionReportDialog(QDialog):
    def __init__(
        self, report: TransactionReport, parent: QWidget | None = None,
    ) -> None: ...
```

Review Changes displays an on-demand unified textual diff. Its inputs are bytes from the saved baseline and addressed candidate, decoded as UTF-8 for these formats. Stale diff compares the captured draft to newly read disk bytes without adopting a new hash. A failed reread displays the load error and retains the draft.

### 3.2 Modified production/documentation files

| Full path | Exact affected symbols or content |
| --- | --- |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/models.py` | `AppMetadata`, `AppMetadata.validate_config_kind`, `ModelFetchRequest`, `ConfigKind` (§2.1). |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/app_registry.py` | `get_managed_apps`: five entries and corrected docstring (§4). |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/presets.py` | Only `DEFAULT_PRESETS` entry `chat2api_local.default_key_env_var`. |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/yaml_manager.py` | Add `render_app_config`, `_render_document`, `_apply_ai_config`; change `write_app_config` to reuse pure rendering and accept optional `expected_sha256`; add kind guards to `read_app_config`, `write_app_config`, `render_app_config`, `ensure_config_exists`. Leave engine settings and legacy two-argument behavior intact. |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/main_window.py` | Change `__init__`, `_init_ui`, `_load_all_configs`, `_on_config_changed`, `_on_save_requested`, `_on_fetch_models`, `_on_models_fetched`, `_on_supervisor_action`, `has_unsaved_changes`; add `_load_config`, `_is_dirty`, `_reload_config`, `_on_structured_saved`, `_on_structured_save_failed`, `_on_launcher_probe_finished`, `_reconcile_dependent_views`, `_update_auth_warnings`. Existing status forwarding, tray and log lifecycle remain applicable. |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/app_detail_view.py` | Change two signal payload declarations to `object`; `_on_fetch_clicked` supplies app id; add `adopt_saved_baseline`, `show_config_error`, `set_save_in_progress` for the common adapter. Keep `get_current_draft` and current form semantics. |
| `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/app_sidebar.py` | Change `__init__`, `_update_item_text`; add `update_configured_port`. |
| `/data/home/guest/Development/ai/ai-manager/README.md` | List five apps, only free-tts excluded; JSON/round-trip YAML fidelity, structured missing-config action, validation scope, stale refusal, unique transaction backups, launcher gate and two-target delivery. Correct current exclusion at `README.md:21`. |
| `/data/home/guest/Development/ai/chat2api/start.sh` | Entire final body is §10. |

Pure YAML interfaces:

```python
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any
from ai_manager.config.models import AppAIConfig, AppMetadata


def render_app_config(
    meta: AppMetadata, doc: MutableMapping[str, Any],
    mutate: Callable[[MutableMapping[str, Any]], None],
) -> bytes: ...

def _render_document(doc: MutableMapping[str, Any]) -> bytes: ...

def _apply_ai_config(
    meta: AppMetadata, doc: MutableMapping[str, Any], new_config: AppAIConfig,
) -> None: ...

def write_app_config(
    app_meta: AppMetadata, new_config: AppAIConfig,
    expected_sha256: bytes | None = None,
) -> None: ...
```

`render_app_config` deep-copies the supplied already-parsed document, applies the callback once, and dumps to `StringIO` with the existing engine. It performs no read, example creation, backup, temp creation, chmod, or replace. The callback is the complete mutation authority. D7 uses exactly `doc["ai"]["api_base"] = new_url`; it never calls `_apply_ai_config`.

`write_app_config(meta, config)` retains example creation, `.bak`, model-transition behavior, return value `None`, and existing error propagation. `_apply_ai_config` contains the current assignments/deletions from `yaml_manager.py:94`. The optional non-None digest invokes the sidecar/hash/unique-backup transaction around the same rendered result. In that checked branch, read only an already-existing target and do not call `ensure_config_exists`; a missing/deleted target is stale and must remain absent. `None` on this legacy API means the legacy unchecked path; it is not the missing-file sentinel of `Transaction.prepare`.

`services/model_fetcher.py` and `services/supervisor.py` need no production change: request origin travels through the connection context, while the supervisor parser and restart method already accept hyphenated arbitrary service names (`A/src/ai_manager/services/supervisor.py:15`, `:119`). Extend their tests.

### 3.3 Test files

New test files (each uses the fixture corpus and assertions in §11–12):

```text
/data/home/guest/Development/ai/ai-manager/tests/test_structured_config.py
/data/home/guest/Development/ai/ai-manager/tests/test_structured_validation.py
/data/home/guest/Development/ai/ai-manager/tests/test_validator_orchestration.py
/data/home/guest/Development/ai/ai-manager/tests/test_transaction.py
/data/home/guest/Development/ai/ai-manager/tests/test_blast_radius.py
/data/home/guest/Development/ai/ai-manager/tests/test_structured_view.py
/data/home/guest/Development/ai/ai-manager/tests/test_sidebar_port.py
/data/home/guest/Development/ai/ai-manager/tests/test_preset_auth.py
/data/home/guest/Development/ai/ai-manager/tests/test_launcher_gate.py
/data/home/guest/Development/ai/ai-manager/tests/test_fetch_routing.py
/data/home/guest/Development/ai/chat2api/tests/test_launcher.py
```

Modified existing test files:

```text
/data/home/guest/Development/ai/ai-manager/tests/conftest.py
/data/home/guest/Development/ai/ai-manager/tests/test_app_registry.py
/data/home/guest/Development/ai/ai-manager/tests/test_e2e_integration.py
/data/home/guest/Development/ai/ai-manager/tests/test_app_views.py
/data/home/guest/Development/ai/ai-manager/tests/test_mnemonic.py
/data/home/guest/Development/ai/ai-manager/tests/test_models.py
/data/home/guest/Development/ai/ai-manager/tests/test_yaml_manager.py
/data/home/guest/Development/ai/ai-manager/tests/test_main_window.py
/data/home/guest/Development/ai/ai-manager/tests/test_main_window_tray.py
/data/home/guest/Development/ai/ai-manager/tests/test_model_fetcher.py
/data/home/guest/Development/ai/ai-manager/tests/test_supervisor.py
```

Define new fixture literals in `tests/conftest.py` or their owning tests, using §11 verbatim. No additional fixture files are required, and the four existing YAML fixtures remain usable for legacy assertions.

## 4. Registry and dispatch

Keep the existing three entries in their current insertion order, explicitly set their kind to `llm`, and append these entries:

```python
{
"chat2api": AppMetadata(
    id="chat2api",
    display_name="chat2api",
    relative_path=workspace_root / "chat2api",
    config_file_name="config.json",
    example_config_file_name="config.example.json",
    default_port=8000,
    supports_split_models=False,
    description="Local OpenAI-compatible gateway for web AI providers",
    config_kind="chat2api",
),
"file-bridge": AppMetadata(
    id="file-bridge",
    display_name="file-bridge",
    relative_path=workspace_root / "file-bridge",
    config_file_name="config.yaml",
    example_config_file_name="config.example.yaml",
    default_port=8964,
    supports_split_models=False,
    description="Local file bridge for saving text and completing paths",
    config_kind="file-bridge",
),
}
```

Required dispatch:

| Surface | llm | chat2api/file-bridge |
| --- | --- | --- |
| View creation | `AppDetailView` | `StructuredConfigView` |
| Read | `read_app_config` | `structured_config.load` |
| Missing target | Existing `ensure_config_exists` | Missing document, no write; explicit action only |
| Draft | `AppAIConfig` | `StructuredDoc` with mutations and raw edits |
| Render for transaction | `render_app_config` | `structured_config.render` |
| Validation | Existing behavior | §7 stages 1–3 |
| Save | Existing `write_app_config` | `structured_config.commit` |
| Dirty | `AppAIConfig.__eq__` | §9 rendered comparison |

Every row raises on unknown kinds. Structured failures must never fall back to `AppAIConfig()`. Legacy load fallback remains confined to the LLM branch. `ensure_config_exists` must refuse non-LLM metadata before any copy.

## 5. Load, mutation addresses, rendering, and commit

### 5.1 Load

1. Validate kind. Make the requested path absolute without dereferencing its leaf.
2. `lstat()` the leaf. A symlink, including a dangling symlink, raises `SymlinkConfigError`. A non-regular existing file raises `ConfigLoadError`.
3. Resolve the parent and join the unchanged leaf name to obtain `resolved_path`. Recheck the leaf with `lstat` at that location.
4. If absent, return the missing record in §2.2. Do not read/copy the example and do not create a lock.
5. Read bytes once, calculate `hashlib.sha256(raw_bytes).digest()`, and retain mode. Decode as UTF-8; malformed encoding is a load error.
6. JSON: parse with an `object_pairs_hook` that constructs insertion-ordered dictionaries and refuses duplicate keys, reporting the offending key. Reject NaN/Infinity via `parse_constant`. Reject a non-dict root with reason `non-dict-root`; do not imitate the service's coercion.
7. YAML: use `_get_yaml_engine()`, with duplicate keys refused. Scan tokens for `AnchorToken` or `AliasToken` using the YAML scanner, not a search for `&` or `*` in text. Parse into the round-trip tree. A comment/whitespace-only file becomes an empty round-trip mapping; explicit null, list, scalar, and other non-mapping roots are load errors. An anchor/alias document stays viewable with reason `yaml-anchors-aliases`; no dump/save is permitted.
8. Chat2api route-shape checks run at load: `models` absent is valid; present `models` must be dict; every entry must be dict; present `options` must be dict. Present `server` must be dict. An error names the offending address. Do not validate credentials, service imports, or endpoint availability at load.
9. Writability check: a file with no write mode bits (`mode & 0o222 == 0`) is non-writable even when a test runs as root; also require `os.access(path, os.W_OK)`. Require write/search access to the parent for eventual replacement. Failed checks add `non-writable`. Readability failure remains a load error.
10. Return a record with an empty mutation list and no input issues. Fill controls with signals suppressed. Set sidebar configured port only if the effective port is a strict integer in range; otherwise retain metadata default and display the field issue.

`load_example` first confirms the target remains absent, loads the example using the same parser/shape checks, and returns an absent-target draft with the example tree and `create_requested=True`. If a target has appeared, raise `StaleDocumentError(path, None, actual_digest)`. Example file mode/read-only status is not the destination mode. Save still runs all validation. The file-bridge example's root need not exist; the user must fix it before save (`C/config.example.yaml:5`).

### 5.2 Mutation address rules

Addresses are tuples of literal keys. A model named `gemini.fast/v2` is one component, never split on dots or slashes:

```python
Mutation(("server", "port"), "set", 8123)
Mutation(("models", "gemini.fast/v2", "options", "headless"), "set", False)
Mutation(("models", "echo-1"), "delete")
Mutation(("models", "renamed"), "set", {"provider": "echo"})
Mutation(("server", "auth_token_env"), "set", None)  # explicit null
Mutation(("server", "auth_token_env"), "delete")     # use service default
```

- Existing-key assignment keeps its position. A new key appends in its parent. Deletion removes only that addressed key. Rename is deletion of the old model and insertion of the whole original route at the new name; untouched model keys keep relative order.
- An absent intermediate mapping is created only to reach an explicitly addressed descendant; no defaults are filled alongside it. An existing non-mapping intermediate value is a shape error, not silently replaced.
- The view coalesces multiple edits to the same address into the latest edit. If the user restores the loaded value/presence, remove the mutation. Deleting a key already absent is a no-op.
- No parent/descendant overlapping mutations are passed to the renderer. For an added/renamed route, later child edits update the value of its parent `set` mutation; a model removal eliminates its child edits. Reject any residual overlap as `ConfigValidationError`.
- Every deletion, null, option addition, and removal is explicit. Merely expanding a row, revealing a secret, changing tabs, or reading an effective default adds no address.
- A secret editor has a private `changed` flag initially false. On save, `changed=False` contributes no mutation, regardless of widget text. A reveal toggle changes echo mode only. Explicit edit, including clearing to an empty string, contributes a set; explicit remove contributes delete. There is no special bullet-string sentinel written to disk.
- Raw area shows only non-secret keys outside the convenience inventory, as a JSON object. When edited, parse with duplicate-key rejection. Compare it with that area's original keys and produce per-key set/delete mutations. Preserve known and secret option keys; an attempted raw collision with one is a field error. Reclassify after a provider switch without rewriting values.

### 5.3 Render

1. Verify kind matches `doc.kind`; reject any `input_issues`.
2. Obtain `effective_mutations`: normalize widget edits and edited raw areas as above. Invalid raw JSON is a field issue; retain its draft text.
3. Reject a read-only document (including YAML anchors/aliases). A missing uninitialized document is also refused.
4. Deep-copy `doc.doc`, apply each non-overlapping mutation in user edit order, and run route/root shape checks on the result. Do not inspect untouched strings for control characters here.
5. JSON: `json.dumps(candidate, indent=2, ensure_ascii=False, allow_nan=False) + "\n"`, UTF-8 encoded, no `sort_keys`. `_comments` is ordinary data. Numeric/string values and unknown subtrees retain their types/values. Whitespace and Unicode escaping can normalize.
6. YAML: dump the round-trip copy to `StringIO` with `_get_yaml_engine()`, encode UTF-8, and retain its final newline. Preserve comments, quoting and relative order of untouched keys. An addressed value's quote spelling need not remain identical.
7. Return bytes. Do not update hashes, clear edits, touch a target, or create backups. No-op render can normalize JSON whitespace, so initial dirty comparison uses `render(saved_snapshot)` rather than `saved_snapshot.raw_bytes`.

### 5.4 Commit coordinator

1. Verify path/kind match the document and `expected_sha256 == doc.raw_sha256`. A caller cannot change the expected digest to bypass stale detection.
2. Require a passed launcher gate for addressed chat2api host/port edits at the MainWindow boundary. Other chat2api fields remain saveable after a failed gate. Recheck that the submitted mutation set did not bypass the disabled controls.
3. Render the primary candidate and selected dependent candidates entirely in memory. Dependent callbacks modify only `ai.api_base`. Any render failure leaves targets unchanged.
4. Run validation stages 1, 2, 3 (§7) for the primary bytes. Dependent YAML gets parse/mapping checks and stage-1 rejection on its newly written API-base string; existing LLM validation behavior is otherwise unchanged. Seal those bytes in a private mapping; do not rerender between validation and replace.
5. `with Transaction() as tx`: prepare all paths against their captured digests, create all backups, stage the already-rendered/validated bytes, then replace all. Thus the ordered validation pipeline precedes target commit; `stage` writes exactly those validated bytes.
6. Build the returned `StructuredDoc` from the sealed primary bytes and known mode, with no edits/issues; do not adopt any later unobserved external bytes as its hash. Return `SaveResult` with validation scope and report.
7. MainWindow adopts baselines/ports only on committed success, reconciles dependent drafts (§8.4), and optionally sends the primary app's restart command. Never restart on validation/transaction failure; never restart dependents implicitly.

### 5.5 Blast-radius selection algorithm

1. Materialize deep-copy before/after chat2api mappings by applying the effective addressed mutations, without modifying the saved tree. Obtain effective host/port with the schema defaults. If that pair is equal, return no matches without reading dependent files or showing a rewrite dialog. The launcher gate must have passed before any changed listener is submitted.
2. Construct the ordinary old/new endpoint as `http://{host}:{port}`. A literal IPv6 address uses brackets (`http://[::1]:8000`). Do not DNS-resolve names. Wildcard hosts cannot occur: R-HOST-LOOPBACK (§7.4) rejects `0.0.0.0` and `::` at save time, so this branch never has to translate a wildcard to loopback.
3. Iterate only metadata with ids `ai-grammar`, `textkit`, `yt2txt` and kind `llm`, in registry order. Read each existing config's bytes once, hash those bytes, parse that same byte buffer with the round-trip YAML engine, and require a mapping root, a mapping `ai`, and a string `ai.api_base`. Do not call `ensure_config_exists`, `read_app_config`, or any mutating writer here. Reject symlink leaves and apply the same regular-file/writability rules as structured load. YAML anchors/aliases make a dependent ineligible for an automatic addressed rewrite; report that reason rather than changing an aliased node.
4. Compare using the **single shared comparator** `urls_match` (§7.4): strip **at most one** trailing `/` from each side, then `normalize_loopback_url` both and require exact equality. Do not use `rstrip("/")`, which would strip repeated slashes and turn `http://127.0.0.1:8000///` into a match. Repeated trailing slashes are a deliberate **negative** case. Nonmatches do not participate. For a match, record the exact tree/bytes/hash and old base, with `new_api_base=new_url`. Derive `saved_config` from this tree using the existing LLM normalized-field rules without rereading the file. A named auth mismatch supplies `DependentMatch.auth_warning`.
5. An unreadable/missing/malformed/ineligible dependent raises `ConfigLoadError` with the dependent-inspection message. MainWindow retains the primary draft, shows that error, and refuses the attempted combined save; it never silently counts an uninspected dependent as unaffected or materializes its example. Successful detection with zero matches skips the dialog and saves the primary alone.
6. With matches, show `BlastRadiusDialog`. All rewrite checkboxes start unchecked, making selection explicitly opt-in. `Save with Selected Updates` uses just the checked ids; zero checked is a one-file transaction. `Save chat2api Only` selects none. Cancel performs no validation or write. Selection returns ids, not editable copies of API keys/models.
7. For each selected match, call `render_app_config` on its captured tree with the single callback `doc["ai"]["api_base"] = match.new_api_base`. Keep the captured digest. Assemble rendered and expected mappings keyed by the normalized resolved target paths, including the primary. Their exact key sets must agree. A later hand edit, including after the dialog, is caught by transaction prepare; do not recapture a newer digest while retaining an old tree.
8. Auth warnings do not mutate keys or select a checkbox. Parse the dependent's normalized key with the same `$NAME` syntax as `A/src/ai_manager/utils/env_resolver.py`; compare only its extracted named variable with the effective non-null server auth name. Refresh chat2api's inline warning list on initial load, relevant draft changes, and committed saves using already-loaded dependent baselines, without reading files for an auth-only change. Display the same matching-dependent warning in the blast dialog. A literal key, empty key, disabled auth, or equal name yields no such warning. An invalid auth draft receives a field error before a save instead.

## 6. Transaction protocol

### 6.1 Paths, locks, and prepare

1. Normalize each target exactly as §5.1 does. Reject symlink/non-regular leaves again. Map each to its parent-resolved absolute path, reject duplicates, require exact matching key sets in `paths` and `expected`, and require digest values of length 32 or `None`.
2. Sort by `str(path)` in Python's lexicographic string ordering; store that tuple for all later phases. All callers, including single-file commits, use that ordering. Do not sort by app selection, descriptor, inode, or backup name.
3. For each sorted target, open sidecar `target.with_name(target.name + ".lock")` with `os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW`, mode `0o600`. The sidecar's parent is the config parent. A lock-file symlink or open failure aborts. Do not unlink a sidecar on release; unlinking would let another process lock a different inode under the same name.
4. Acquire `fcntl.flock(fd, fcntl.LOCK_EX)` in that same order. Retry an interrupted acquire. This is blocking advisory locking in a worker, not the GUI thread; it creates no permission to ignore other writers. The UI reports the saving state while waiting.
5. Once *all* locks are held, `lstat`/read every target, recheck writable/regular status, capture pre-transaction bytes/mode/existence, and compute current digest. Missing path yields `None`.
6. Compare every actual digest to expected. Any mismatch raises `StaleDocumentError` for the first sorted mismatch. No backups or staged files have been created and no target has been written. Release all acquired locks in reverse order even after partial acquisition failure.
7. A read/permission/type error is not equivalent to a hash mismatch. Raise the appropriate load/read-only error. Only advance to backups after all files pass.

Locking the config inode itself is forbidden: replace changes that inode. Holding sidecars stabilizes lock identity across replace. The guarantee is no lost update observable at this hash check. A non-cooperating writer can still write between the hash check and replace. A symlink/type race from an uncooperative process is also outside this pathname/advisory-lock guarantee; rechecks narrow it without claiming inode-level exclusion.

### 6.2 Backups

For each existing target, use its exact prepare bytes and mode. For an absent creation target, record no backup and remember original absence.

```text
<name>.<YYYYmmddTHHMMSSffffffZ>.<pid>-<hex6>.bak
Example: config.json.20261017T160734123456Z.4321-a1b2c3.bak
Timestamp: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
Nonce: secrets.token_hex(3)
```

1. Create in the config parent with `os.open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0o600)`.
2. On `FileExistsError`, draw a fresh nonce and retry exclusive creation. Never truncate or reuse an existing backup; even a patched/frozen clock cannot overwrite it.
3. Write all bytes, handling short writes via a file object's complete write/flush semantics; apply original mode with `fchmod`, flush and `fsync` the backup descriptor, then fsync its parent directory.
4. On any failure, close descriptors, remove only an incomplete backup created by this attempt, and abort before staging/replacement. Successfully completed backups from earlier targets remain recovery artifacts. Report every prepared target as `restored` after verifying its original state, report any unverifiable path as `unknown`, include the backups-phase error, and release all locks.
5. Do not update the legacy single-name `.bak` as part of this transaction. No backup retention/deletion policy is introduced.

### 6.3 Stage

1. Require the rendered mapping to have exactly the prepared target set. Every value is the sealed validated bytes from §5.4; no writer callback is called here.
2. In sorted target order, use `tempfile.mkstemp(prefix=f".{name}.ai-manager-stage-", suffix=".tmp", dir=parent)`; only hidden sibling temps are created.
3. Write bytes, flush, apply the existing target's mode, fsync. For an explicitly created missing structured config, use mode `0o600` because it may contain credentials. No target is replaced here.
4. If any stage operation fails, remove all stage temps, keep complete backups, and release locks. Every target must still be byte-for-byte and mode-for-mode equal to its prepare state. The failure report covers every prepared path using the same verified `restored`/`unknown` rule as a backup failure. No call to `write_app_config` is allowed in any staging callback.

### 6.4 Replace and rollback

1. For each sorted target, `os.replace(staged_path, target)`, then immediately record it as replaced, then fsync its parent directory. If the directory fsync fails after replace, that target is still in the rollback list.
2. Success requires every replace and directory fsync. Return `phase="complete"`, `committed=True`, all `files[path]="new"`, and the complete backup mapping.
3. On first failure, stop replacements. Set the report error to the failing path/operation. Mark all never-replaced targets `restored` after checking original bytes/existence. Call `rollback` while all locks remain held.
4. For each replaced target in reverse replacement order, restore by writing backup bytes into a *new* hidden sibling restore temp, applying original mode, fsyncing it, replacing the target, and fsyncing the parent. Keep the backup itself. For an originally absent target, unlink the newly created target and fsync the parent.
5. Verify restored bytes/digest (or absence) before recording `restored`. Continue attempting every other restoration even if one fails. Record every failed path in `restore_failures`, set its state to `unknown`, and retain backup/staged evidence that may aid recovery. Do not claim a failed restore has old or new contents.
6. Return a rollback report with `committed=False`; the caller raises `TransactionError(report)` chained from the original error. `phase="rollback"` identifies this path; `restore_failures` distinguishes complete recovery from unresolved state.
7. On every terminal path, remove unconsumed stage/restore temps when safe, unlock in reverse order, and close descriptors. Do not delete a complete backup or a sidecar. Cleanup errors that affect a target's known final state belong in the report.

This is in-process coordinated replacement with recovery, not an atomic multi-path filesystem primitive. Readers ignoring sidecars may see an intermediate mixture. A crash/power loss between replacements is not automatically recovered on next startup; there is no journal. Backups survive for manual recovery. Reported guarantees concern handled failures in the running process.

## 7. Validation and interpreter execution

### 7.1 Stages 1–4

Stages are ordered and fail fast. A blocked stage never sends a restart command.

**Stage 1 — scalar values being written.** Traverse only effective `set` mutations, recursively descending any addressed object/list; inspect newly written string mapping keys as well as string values. This includes added/renamed model names, host, auth name, all edited known/raw option values, save-root text/components, and D7 API-base text. Reject any occurrence of newline (`U+000A`), carriage return (`U+000D`), or NUL (`U+0000`). A delete writes no scalar. Do not scan an untouched subtree; an existing multiline string cannot block an unrelated edit. Unicode and tabs are not rejected by this rule. Numeric/bool/null values proceed to schema checks.

Exact field message:

```text
This value must not contain newline, carriage return, or NUL characters.
```

**Stage 2 — in-process candidate rules.** Parse rendered bytes as the proper format, retaining duplicate-key/root/route checks, and validate with §2.3:

```text
chat2api:
- root: mapping; server when present: mapping
- models when present: mapping; every name: non-empty string and unique
- every route: mapping; provider required and one of four inventory names
- options absent: valid; options present: mapping
- host: strict string, length >= 1, and **loopback-only** — one of
  `127.0.0.1`, `localhost`, `::1` (case-insensitive for `localhost`);
  effective default 127.0.0.1. Wildcard (`0.0.0.0`, `::`) and any other value
  are rejected by rule R-HOST-LOOPBACK (§7), not coerced.
- port: strict int, excluding bool, 1..65535; effective default 8000
- auth_token_env: absent/default CHAT2API_TOKEN, explicit null, or ASCII env name
- extra data: allowed/preserved; provider options remain open

file-bridge:
- root: mapping; duplicate keys forbidden
- only save_root, max_text_bytes, port are accepted keys
- save_root: strict nonempty, non-whitespace-only string; effective default ~
- expanduser then relative-to-config-parent resolution then resolve
- resolved root exists and is a directory
- root is neither app_dir nor below resolved app_dir
- root readable/searchable/writable; scandir and TemporaryFile probe succeed
- port: strict int, excluding bool, 1..65535; effective default 8964
- max_text_bytes: strict int, excluding bool, 0..104857600 inclusive
- effective default max_text_bytes: 1048576; 0 disables decoded-text limit only
```

The service has an additional transport cap irrespective of that setting (`C/main.py:44`); the editor's `0 = no limit` annotation refers to `max_text_bytes`, not a promise to remove transport limits.

Pydantic error locations map to literal-key tuples, preserving model names as one component. Display a concise field message without printing Pydantic's input-value dump, since that may contain passwords. Full service stderr is handled separately below.

**Stage 3 — best-effort service configuration checks.** Resolve and import-probe the interpreter (§7.2). If unavailable, return manager-only scope with the exact degraded notice; in-process validation is still mandatory. Otherwise:

1. Create a hidden candidate using `mkstemp(prefix=f".{target.name}.ai-manager-validate-", suffix=target.suffix, dir=target.parent)` where `target` is the resolved target path. Write precisely the rendered bytes, flush/fsync, and keep candidate mode `0o600`.
2. Run the appropriate command below as an argv list (`shell=False`), cwd the resolved app directory, environment inherited from ai-manager, candidate passed through `sys.argv[1]`. Do not interpolate config contents into Python code or a shell.
3. Apply a 10-second wall timeout to each validator subprocess. Capture stdout and stderr; use `communicate(timeout=10)`, then kill and communicate/reap on timeout. Timeout is a refused validation, not “validator unavailable.” No network/login/discovery method is called.
4. Exit 0 means configuration passed the service's checks. Exit 75 means an import required to run the validator was unavailable, so return the degraded result. Every other exit, including a signal exit, raises `ServiceValidationError` with exact decoded stdout/stderr. Timeout raises `ServiceValidationTimeout`.
5. Always remove the hidden candidate after the child has exited/reaped, including import failures and timeouts. Candidate creation/write/unlink failure is a local save/validation I/O error, not a reason to silently skip validation.

Exact subprocess Python programs (constant strings; argv is `[str(py), "-c", PROGRAM, str(candidate)]`):

```python
# CHAT2API_VALIDATE_PROGRAM
import sys
try:
    from app.config import load_config
    from app.registry import Registry
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
try:
    cfg = load_config(sys.argv[1])
    Registry(cfg)
    cfg.validate_auth()
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
```

```python
# FILE_BRIDGE_VALIDATE_PROGRAM
import sys
from pathlib import Path
try:
    import main
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
cfg = main.load_config(Path(sys.argv[1]))
main._probe_save_root(cfg.save_root)
```

No wrapper catches `RuntimeError`, Pydantic validation failures, or arbitrary exceptions as unavailable. In particular, `cfg.validate_auth()` rejecting an unset/empty named variable blocks saving; explicit null passes. B's `load_config` loads `.env` itself (`B/app/config.py:82`). Login/discovery and provider credential validation are never invoked. Import-time missing dependencies can degrade validation; a runtime provider error from Registry remains a validator rejection with stderr.

**Stage 4 — commit.** Run §6 only after successful stages 1–2 and either passed or explicitly degraded stage 3. The bytes checked in stage 3 are the bytes staged for replace. Save success means `configuration valid` at the indicated scope, not restart success.

### 7.2 Interpreter selection contract

For B, both launcher and manager use activation-file precedence, not merely directory existence:

1. If `<app_dir>/.venv/bin/activate` is a file, select absolute `<app_dir>/.venv/bin/python`.
2. Else if `<app_dir>/venv/bin/activate` is a file, select absolute `<app_dir>/venv/bin/python`.
3. Else use `shutil.which("python")` from the manager environment's PATH, matching shell `command -v python` before local activation. Do not substitute `sys.executable`, `python3`, or a guessed `.venv`.
4. A selected interpreter that is missing/non-executable is unavailable; do not silently fall through to a different environment. The launcher likewise fails with that selected path.
5. Preserve the lexical interpreter path; do not `.resolve()` a virtualenv `python` symlink to its base interpreter, since that can change virtualenv selection. Resolve the app directory, not the executable leaf.

The launcher sources the chosen activation file to preserve its existing environment effects, then binds its explicit interpreter path to `PY`. Both config read and uvicorn use `"$PY"`. With no activation, `PY` is the ambient command lookup. Conventional venv activation effects are preserved; arbitrary custom activation scripts that intentionally select a different interpreter are not an additional supported branch.

The manager uses the selected interpreter without sourcing shell code and verifies it with a subprocess import probe, cwd app directory, timeout 10 seconds:

```python
# chat2api probe
import app, fastapi
```

```python
# file-bridge probe
import main, fastapi
```

A probe spawn error, nonzero exit, or timeout raises internal `InterpreterUnavailableError`, converted by `validate_candidate` to `ValidationResult("manager-only", degraded_notice, detail)`. Both probes are reaped. For C this is the validator search prescribed by the approved design; C's actual launcher currently mandates `.venv/bin/python` (`C/start.sh:6`), so using an ambient/venv validator is best-effort evidence rather than a guarantee of C launcher readiness.

Manager and supervisor processes may inherit different PATH/environment values. Import probing establishes usability in the manager's environment; it does not prove that future supervisor startup uses identical ambient state.

### 7.3 Behavioral launcher gate (capability-flag design)

> **Amendment, approved by the user as design-pivot question 15.** Revision 4 of this
> section specified a probe that launched `start.sh` and socket-tested the bound port.
> Adversarial review proved that approach cannot be isolated in-process: the launcher
> needs its `app/` tree, and any symlink to it exposes the real `config.json` and `.env`
> to the child, including non-Python children that carry no audit hook. A `bytes` path
> also bypasses a `str` deny-list, and `os.open(..., dir_fd=...)` resolves relative to a
> directory descriptor rather than the checked path. The probe was therefore both a
> credential-leak and a port-collision risk. It is replaced by a capability flag on the
> launcher itself.

#### 7.3.1 The `--print-listener` capability

Target B's `start.sh` accepts `--print-listener`. When present, it:

1. resolves the config exactly as the serving path does (same `PY`, same `load_config`,
   same cwd);
2. prints the resolved host and port on separate lines to **stdout**;
3. exits `0` **before** any uvicorn import, bind, or serve.

It **reads the installed configuration** — and, through the service loader, its
`.env` — exactly as a real start would; that is what makes the answer truthful. It
never *prints* secrets, binds no socket, and starts no server. Failure diagnostics are
redacted (`redact_diagnostics`) before they are stored or displayed, because the
service's pydantic errors can quote option values verbatim.
A launcher predating this flag exits non-zero on the unknown argument, which the gate
treats as "capability absent".

#### 7.3.2 Gate algorithm

`probe_launcher(app_dir) -> LauncherProbeResult` runs, in the app directory:

```python
subprocess.run([str(app_dir / "start.sh"), "--print-listener"],
               cwd=str(app_dir), env=os.environ.copy(),
               capture_output=True, text=True, timeout=10, shell=False)
```

- exit `0`, **at least two** non-empty stdout lines, the **last two** being host then
  port, host in the R-HOST-LOOPBACK set, port an int in 1..65535 -> `passed=True`.
  (The real launcher prints a version banner first, so earlier lines are ignored; this
  was established by cross-target acceptance.)
- exit non-zero, timeout, fewer than two lines, or an out-of-range value ->
  `passed=False` with the captured stderr as `detail`.
- The child is `start.sh` only; it is awaited and reaped by `subprocess.run`. No process
  group is created, no PID is signalled, and nothing survives the call.

Because nothing binds, the gate may run at any time, on any port state, including while
the real service is live on 8000. There is no port allocation, no readiness polling, and
no SIGTERM/SIGKILL escalation.

#### 7.3.3 What the gate proves, and what it does not

Proves: the installed launcher advertises the capability and reports the same listener
ai-manager derives from the same config. This is enough to make the editor's host/port
fields truthful.

Does not prove: that a subsequent restart actually binds successfully (port-in-use,
missing dependencies, and login/discovery remain runtime concerns), and does not detect a
supervisor-level `--host`/`--port` override that supersedes config. The end-to-end
proof that the launcher really binds and serves a non-default port lives in Target B's
own acceptance test (`tests/test_launcher.py`), not in the GUI gate.

#### 7.3.4 Caching and UI effect

Run once per resolved application directory per `MainWindow` session and cache the
terminal result. While pending, and on failure, chat2api's `host`/`port` fields and the
blast-radius rewrite stay read-only; models, auth, logs, status, and restart remain
available. A failed gate is not retried automatically in the same session; restarting
ai-manager after installing Target B starts a new check.

### 7.4 R-HOST-LOOPBACK and R-HOST-CLASS

**R-HOST-LOOPBACK** (stage 2, chat2api): `server.host` must be a strict string
that is **exactly** one of `127.0.0.1`, `localhost`, or `::1`, compared
case-insensitively for `localhost` only. Surrounding whitespace is **not**
stripped and is therefore rejected: a host of `" localhost "` would be written
verbatim, forwarded to uvicorn verbatim, and produce an unusable
`http:// localhost :8000` endpoint. The accepted value must equal the canonical
form character for character. Rejection message:

```text
Host must be a loopback address (127.0.0.1, localhost, or ::1). Binding a
wildcard or external interface is not supported for this local service.
```

Rationale: chat2api is a loopback-only service. A wildcard bind (`0.0.0.0`,
`::`) has no single connectable client URL, so a blast-radius rewrite would have
to guess. Rejecting it makes the rewrite correct by construction. This rule is
an ai-manager editor rule only; it does not modify chat2api, which still accepts
any host in its own loader.

**R-HOST-CLASS** (blast-radius matching): compare two URLs by **normalizing the
host spelling only**, and by comparing everything else as exact text.

```python
LOOPBACK_CANONICAL = "127.0.0.1"

def normalize_loopback_url(url: str) -> str | None:
    """Return `url` with its loopback host spelling normalized to 127.0.0.1.

    Only the host component is replaced. Scheme, userinfo, port, path, query,
    and fragment are preserved byte-for-byte. Returns None when the URL is
    unparseable or its host is not one of the three loopback spellings.
    """

def urls_match(a: str, b: str) -> bool:
    """Exact string equality after normalize_loopback_url on both sides."""
```

The whole-URL comparison is what makes path suffixes significant:

| `api_base` | matches `http://127.0.0.1:8000`? |
| --- | --- |
| `http://127.0.0.1:8000` | yes |
| `http://127.0.0.1:8000/` | yes (single trailing `/` stripped from both before comparison) |
| `http://localhost:8000` | yes (host class) |
| `http://[::1]:8000` | yes (host class) |
| `http://LOCALHOST:8000` | yes (`localhost` compared case-insensitively) |
| `http://127.0.0.1:8000/v1` | **no** (path preserved) |
| `http://127.0.0.1:8001` | **no** (port differs) |
| `https://127.0.0.1:8000` | **no** (scheme differs) |
| `http://127.0.0.1:8000/?x=1` | **no** (query preserved) |
| `http://0.0.0.0:8000` | **no** (not loopback; cannot be saved anyway) |
| `http://127.0.0.1:8000///` | **no** (only one trailing `/` is stripped) |
| `http://user:pw@127.0.0.1:8000` | **no** (userinfo preserved, so not equal) |

The trailing-slash rule is: strip **at most one** trailing `/` from each raw
string before normalization; do not strip repeatedly and do not strip a path
that is exactly `/` into an empty string when a query or fragment follows.

When a match is rewritten, the dependent's `api_base` receives exactly
`new_url` — the primary's newly saved base URL — rather than a reconstructed
URL. This is the single rewrite rule and it is consistent with §5.5 step 4:
the dependent's endpoint becomes identical to the primary's, which is what
"points at chat2api" means. Because host normalization is comparison-only and
never applied on write, a user who typed `localhost` keeps `localhost` in
the chat2api file and dependents are rewritten to that saved spelling.

Credentials, queries, and paths in a dependent that do not match are left
entirely alone; they are never partially rewritten.

### 7.5 Non-default `CHAT2API_CONFIG` (recorded limitation)

The editor targets `<app_dir>/config.json`, matching the registry's
`config_file_name`. The supervisor invokes `./start.sh` with no override, so in
the managed path this is the file the service reads.

The launcher does honor an externally set `CHAT2API_CONFIG`. ai-manager does
**not** discover it, and this specification makes no attempt to. Consequences,
stated in the UI header for chat2api:

```text
Editing <absolute path to app_dir/config.json>. If CHAT2API_CONFIG is set
externally for the supervised service, ai-manager edits a different file.
```

This is a documented limitation, not a defect: the managed configuration has a
single writer (ai-manager) and a single reader (`start.sh` with no override).

### 7.6 Validation guarantee boundary

Validation guarantees that the written file is accepted by the service's
configuration loader **when the stage-3 validator runs**, and that it satisfies
ai-manager's schema rules in all cases. It does **not** guarantee that a restart
succeeds: port-in-use, missing dependencies, absent provider credentials, and
runtime login/discovery failures are outside its scope and are reported by the
supervisor's restart outcome, never inferred from a successful save.

The gate proves that the installed launcher advertises the `--print-listener` capability and reports the same listener ai-manager derives from the same config. It does **not** prove runtime provider/login success, freedom from port conflicts, or that a restart will bind. Those remain Target B's acceptance-test concern (§7.3.3).

## 8. Qt adapter and orchestration contracts

### 8.1 Concrete common adapter

Both widgets are siblings deriving from QWidget. MainWindow stores their union and config dictionaries containing `Any`:

```python
from typing import Any
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget
from ai_manager.config.models import AppAIConfig, AppMetadata, ModelFetchRequest, ServiceStatus
from ai_manager.config.structured_models import (
    FieldIssue, LauncherProbeResult, StructuredDoc, ValidationResult,
)
from ai_manager.ui.widgets.log_view import LogViewWidget

# Declare on BOTH AppDetailView and StructuredConfigView:
save_requested = pyqtSignal(str, object, bool)
restart_requested = pyqtSignal(str)
config_changed = pyqtSignal(str, object)
fetch_models_requested = pyqtSignal(ModelFetchRequest)

# MainWindow storage:
_saved_configs: dict[str, Any]
_draft_configs: dict[str, Any]
views: dict[str, AppDetailView | StructuredConfigView]

# AppDetailView public adapter additions:
def adopt_saved_baseline(self, config: AppAIConfig, *, preserve_draft: bool) -> None: ...
def show_config_error(self, message: str, detail: str = "") -> None: ...
def set_save_in_progress(self, saving: bool) -> None: ...

# StructuredConfigView public surface:
class StructuredConfigView(QWidget):
    def __init__(self, app_meta: AppMetadata, parent: QWidget | None = None) -> None: ...
    def load_config(self, config: StructuredDoc) -> None: ...
    def get_current_draft(self) -> StructuredDoc: ...
    def adopt_saved_baseline(self, config: StructuredDoc, *, preserve_draft: bool) -> None: ...
    def show_load_error(self, message: str, reason: str = "load-error") -> None: ...
    def show_config_error(self, message: str, detail: str = "") -> None: ...
    def show_field_issues(self, issues: tuple[FieldIssue, ...]) -> None: ...
    def set_validation_result(self, result: ValidationResult) -> None: ...
    def show_auth_warnings(self, warnings: tuple[str, ...]) -> None: ...
    def set_launcher_gate(self, result: LauncherProbeResult | None) -> None: ...
    def set_save_in_progress(self, saving: bool) -> None: ...
    def update_service_status(self, status: ServiceStatus) -> None: ...
    @property
    def log_view(self) -> LogViewWidget: ...
```

`None` gate result means pending. Structured view never emits `fetch_models_requested`; it has no fetch controls. It does not require `set_available_models` or `on_model_fetch_response`. MainWindow calls those LLM-only methods only in the LLM branch. Dirty state remains a MainWindow computation; there is no `set_dirty` adapter method.

`adopt_saved_baseline(..., preserve_draft=False)` replaces loaded state and widgets with signals suppressed. With `preserve_draft=True` it updates only the saved baseline and retains current widget values/draft. For the LLM view `_current_config` becomes the new saved config, but controls are not repopulated.

### 8.2 Signal/event behavior

| Event | Emission and MainWindow action |
| --- | --- |
| Successful load/reload | No save/config-change/fetch emission. MainWindow installs baseline and owned draft, clears dirty, updates configured port. |
| Structured load failure | View emits none of the four signals. `show_load_error` disables save/config editing, retains header/logs/restart, displays exact error, and leaves no fabricated saved config. |
| Field edit | Emit `config_changed(app_id: str, draft: object)` once per logical edit; MainWindow stores the typed draft and recomputes dirty. Invalid input also remains represented in the draft. |
| Save click | Emit `save_requested(app_id, draft, should_restart)` once. MainWindow validates kind/type, resolves blast dialog if applicable, then starts the appropriate save operation. |
| Stale save result | No additional view signal. MainWindow retains draft/dirty, re-enables editing, displays StaleDocumentDialog. Reload discards draft and calls `_reload_config`; Show diff reads current disk only; Cancel retains draft. |
| Manager rule failure | No additional view signal. MainWindow calls `show_field_issues`, keeps draft/dirty and marks relevant fields; save is re-enabled after completion. |
| Service validator rejection/timeout | No additional view signal. MainWindow calls `show_config_error` with credential-safe stderr (field location and message preserved, input values redacted) in expandable panel, keeps draft/dirty, and does not restart. |
| Service validator unavailable | Save continues; the returned validation result is displayed inline and persists after successful save. |
| Successful save | MainWindow installs saved baseline, clears primary dirty, updates ports, and reconciles selected dependents. Only then may it send restart. Loading committed widgets emits no edit signals. |
| Restart click | Emit `restart_requested(app_id)`; MainWindow calls `SupervisorManager.restart_service(app_id)`. No config write or dirty clear. |
| Logs/status/reveal/row expansion | No config-change/save signal. Status forwards to StatusBadge and LogViewWidget with existing reported-path fallback behavior. |

MainWindow `_on_save_requested` accepts `object`; it rejects a payload whose type disagrees with metadata rather than coercing a structured object to LLM config. During a primary save, disable that view's editing/save controls and reject a second save for that app. Keep its restart-after-save boolean in `_pending_restarts: dict[str, bool]`; clear it on any failure. Other views may retain edits; reconciliation uses their current drafts at completion.

### 8.3 Form behavior

Chat2api page contains Server and Models groups, with table columns Name, Provider, Options, Secrets. Add creates an unsaved row requiring a unique nonempty name and a provider; no default model is saved silently. Remove addresses only that route. Expanded row uses `PROVIDER_OPTIONS` plus collapsed raw options. Changing provider displays the provider-switch warning and retains all options. Review Changes does not write. Save Config Only and Save and Restart emit the same draft with different boolean flags.

File-bridge page contains only `Save Location & Server`: directory text/picker, max bytes, port. No host, auth, model table, provider preset, or fetch control. A directory picker changes only the `save_root` draft text; it creates no directory. Integer widgets support the full specified ranges, explicit invalid input marking, and no silent clamping of existing invalid values.

Common page structure retains Configuration/Logs tabs, service status/PID, restart button, editing-path label, validation label, and footer actions. New dynamic text in mnemonic-aware Qt widgets passes through `escape_mnemonic` (`A/src/ai_manager/ui/app_detail_view.py:310`); ordinary labels without buddies remain literal (`A/tests/test_mnemonic.py:128`). Use plain-text labels/details for filenames and stderr.

### 8.4 Dependent draft reconciliation

After a committed D7 rewrite, parse each dependent's sealed new bytes into the new normalized `AppAIConfig` baseline. Do not reread an unrelated later hand edit and silently adopt its hash.

1. Capture whether its current draft is dirty against its previous saved baseline using LLM equality.
2. Update `_saved_configs[app_id]` to the new baseline.
3. If it was clean, update draft and widgets to the new baseline; dirty is false.
4. If it was dirty, leave `_draft_configs[app_id]` and every widget value unchanged; call `adopt_saved_baseline(..., preserve_draft=True)`. Recompute dirty against the new saved baseline; unrelated edits remain and the old draft API base may now differ from disk.
5. Clear only primary chat2api mutations. Unchecked dependents and nonmatching apps receive no disk or baseline change.

### 8.5 Model fetch identity

`AppDetailView._on_fetch_clicked` constructs:

```python
request = ModelFetchRequest(
    token=self._fetch_token,
    api_base=self._base_url_edit.text().strip(),
    api_key=self._key_edit.text().strip(),
    app_id=self.app_meta.id,
)
```

MainWindow connects each worker's finished signal to a queued receiver that binds `request.app_id` at worker creation, then invokes:

```python
def _on_models_fetched(self, app_id: str, response: ModelFetchResponse) -> None: ...
```

Do not read `sidebar.current_app_id()` when completing a request. Verify the originating view still exists and is LLM, then call its `on_model_fetch_response(response)`; its existing token check discards stale responses (`A/src/ai_manager/ui/app_detail_view.py:324`). A removed/non-LLM origin is ignored. An unknown request id is rejected before dispatch. Selection changes never change ownership of a response.

### 8.6 MainWindow and sidebar signatures

These methods are added/changed in the existing classes, retaining the constructor parameters documented by their current callers. The methods below run on the GUI thread; save/probe completion slots receive worker results through queued connections.

```python
from typing import Any
from pathlib import Path
from PyQt6.QtWidgets import QWidget
from ai_manager.config.models import AppAIConfig, ModelFetchRequest, ModelFetchResponse
from ai_manager.config.structured_models import LauncherProbeResult, SaveResult
from ai_manager.config.config_errors import ConfigError

# MainWindow methods:
def __init__(
    self, workspace_root: Path | None = None, parent: QWidget | None = None,
    start_minimized_override: bool = False,
) -> None: ...
def _init_ui(self) -> None: ...
def _load_all_configs(self) -> None: ...
def _load_config(self, app_id: str) -> None: ...
def _reload_config(self, app_id: str) -> None: ...
def _is_dirty(self, app_id: str) -> bool: ...
def _on_config_changed(self, app_id: str, new_draft: object) -> None: ...
def _on_save_requested(
    self, app_id: str, config: object, should_restart: bool,
) -> None: ...
def _on_structured_saved(self, app_id: str, result: SaveResult) -> None: ...
def _on_structured_save_failed(self, app_id: str, error: ConfigError) -> None: ...
def _on_launcher_probe_finished(
    self, app_id: str, result: LauncherProbeResult,
) -> None: ...
def _reconcile_dependent_views(
    self, saved_dependents: dict[str, AppAIConfig],
) -> None: ...
def _update_auth_warnings(self) -> None: ...
def _on_fetch_models(self, request: ModelFetchRequest) -> None: ...
def _on_models_fetched(self, app_id: str, response: ModelFetchResponse) -> None: ...
def _on_supervisor_action(self, action: str, success: bool, msg: str) -> None: ...
def has_unsaved_changes(self) -> bool: ...

# AppSidebar method:
def update_configured_port(self, app_id: str, port: int | None) -> None: ...
```

`AppSidebar._configured_ports: dict[str, int]` is initialized empty. `update_configured_port` requires a known app id; a non-None port must have `type(port) is int` and be in 1..65535, otherwise raise `ValueError`. None removes its cache entry. `_update_item_text` chooses `_configured_ports.get(app_id, meta.default_port)` so dirty/status redraws retain the saved port. Call this method on successful structured load/save and with None on missing/unreadable load; do not call it for draft edits. The structured header uses the same saved-effective-port rule.

A `SaveResult` must expose dependent committed baselines without an unverified reread. The coordinator builds `saved_dependents` by parsing the sealed dependent bytes and attaches them to `SaveResult` as specified in §2.2. `_on_structured_saved` passes that mapping to `_reconcile_dependent_views`.

## 9. State machines and user-visible strings

### 9.1 Dirty and load states

| Kind/state | Baseline/draft and dirty rule |
| --- | --- |
| LLM loaded | Saved and draft are independent `AppAIConfig` copies; compare with equality exactly as existing model semantics. |
| Structured loaded | Compare `render(kind, saved_without_edits)` to `render(kind, current_draft)`. Normalized JSON formatting alone is clean. |
| Structured invalid input/raw JSON | Treat as dirty because no equal valid candidate render exists; retain all raw text and issues. Never discard a draft merely because render raises. |
| Missing before explicit creation | No writable draft; dirty false. Both save buttons disabled. |
| Explicit example creation | `create_requested=True`; dirty true even if there are no mutations relative to the example tree. Save validates and requires the target to remain absent. |
| Load error | No new baseline; dirty false on initial load. A failed reload does not clear a previously retained draft. |
| Read-only document | Render for editing is unavailable. Initial state is clean; save disabled; show parsed values and reason. |
| Save rejected/rolled back | Baseline, draft and dirty stay unchanged. |
| Save committed | Primary baseline/draft become the sealed committed snapshot; dirty false. Dependent reconciliation follows §8.4. |

`MainWindow.has_unsaved_changes` delegates to `_is_dirty` for every app and includes explicit-create/invalid drafts. It must not use truthiness of a draft as a proxy for existence. Closing/tray behavior uses this same result, retaining existing lifecycle semantics (`A/src/ai_manager/ui/main_window.py:372`, `:400`).

### 9.2 Save transitions

```text
loaded/dirty -> pre-save dialog (only host/port change with matches)
pre-save dialog -> cancel -> dirty, no I/O
pre-save dialog -> save alone / selected rewrites -> validating
loaded/dirty -> validating (no dialog needed)
validating -> invalid -> dirty + field/stderr error
validating -> manager-only notice -> preparing
validating -> service valid -> preparing
preparing -> stale/read-only/I/O error -> dirty + refusal
preparing -> backups -> staging -> replacing -> committed
backups/staging -> failure -> dirty; all targets unchanged
replacing -> failure -> rolling back -> dirty + report
rolling back -> restore failure -> dirty + unknown-state report
committed -> optional restart requested -> supervisor result
restart failure -> committed configuration retained + restart error
```

No transition bypasses a stale digest. Stale dialog offers only Reload, Show diff, Cancel. No force action, hidden override flag, retry with a newly substituted hash, or automatic rollback after restart failure exists.

### 9.3 Read-only reasons

| Reason | Scope and exit condition |
| --- | --- |
| Symlink | Entire config load rejected, including dangling link. Remove/reconfigure the link externally and reload. |
| Non-writable file/parent | Entire parsed config displayed read-only. Correct permissions and reload. Writable parent alone does not override non-writable mode bits. |
| YAML anchor or alias | Entire parsed YAML config displayed read-only, with original text available in error/diff details. Remove those constructs externally and reload. Quoted `"a&b*"` is ordinary text. |
| Launcher pending/failed | Only chat2api host/port and dependent rewrite disabled. Other fields may save. Success unlocks fields; failed cached gate requires a new manager session after B is installed. |
| Non-dict root | Load error and save disabled. Do not show an empty default form as if loaded successfully. |
| Missing structured config | Empty sections and explicit Create from Example. No automatic materialization. |

### 9.4 Exact UI text catalog

Use these literal strings, including punctuation/case. Braces denote runtime substitutions; paths are displayed as plain text. Native service stderr is shown unchanged in the expandable details panel, decoded with `errors="replace"`; the UI never substitutes the generic message for those details.

| State/control | Exact text |
| --- | --- |
| Gate pending | `Checking whether launcher honors config…` |
| Gate passed | `launcher honors config — host/port editable` |
| Gate failed | `launcher does not honor config — install Target B first` |
| Degraded validation | `validated by ai-manager only — service validator unavailable` |
| Chat2api validated | `configuration valid — validated by chat2api · ai-manager` |
| File-bridge validated | `configuration valid — validated by file-bridge · ai-manager` |
| Not yet validated | `Not validated since load.` |
| Missing target | `Configuration file is missing. Choose Create from Example to start a draft.` |
| Create action | `Create from Example` |
| Example missing/unreadable | `Cannot create draft from example: {path}` |
| Non-object root | `Configuration root must be a mapping; save is disabled.` |
| Models shape | `Models must be a mapping; save is disabled.` |
| Entry shape | `Model {name!r} must be a mapping; save is disabled.` |
| Options shape | `Options for model {name!r} must be a mapping when present; save is disabled.` |
| Server shape | `Server must be a mapping when present; save is disabled.` |
| Duplicate key | `Duplicate configuration key {key!r}; save is disabled.` |
| General parse/read error | `Cannot load configuration {path}: {detail}` |
| Symlink | `Configuration path is a symlink; editing is disabled.` |
| Non-writable | `Configuration is not writable; editing is disabled.` |
| YAML anchors/aliases | `YAML anchors or aliases are present; editing is disabled to preserve linked values.` |
| Missing/uninitialized save attempt | `Create a draft from the example before saving.` |
| Invalid input summary | `Configuration has invalid fields; nothing was saved.` |
| Duplicate model row | `Model names must be unique.` |
| Empty model row | `Model names must be non-empty strings.` |
| Raw options parse | `Raw options must be a JSON object with unique keys.` |
| Raw known/secret collision | `Edit known or secret options in their fields, not in raw options.` |
| Control-character error | `This value must not contain newline, carriage return, or NUL characters.` |
| Service rejection | `Service validator rejected the configuration; nothing was saved.` |
| Validator timeout | `Service validator timed out after 10 seconds; nothing was saved.` |
| Validator details toggle | `Validator details` |
| Saving/waiting | `Saving configuration…` |
| Stale summary/title | `Configuration changed on disk; save refused.` / `Configuration Changed` |
| Stale choices | `Reload` / `Show diff` / `Cancel` |
| Reload consequence | `Reload discards this app's unsaved draft.` |
| Backup failure | `Could not create all backups; no configuration files were changed.` |
| Stage failure | `Could not stage configuration files; no configuration files were changed.` |
| Replacement recovered | `Save failed; configuration files were restored from backups.` |
| Restore failure | `Save failed and some files could not be restored. Review every path below before restarting services.` |
| Report row | `{path}: {state}` |
| Unknown-state action | `Reload affected files after resolving the reported recovery failures.` |
| Draft dirty | `Unsaved changes` |
| Review control/title | `Review Changes` |
| Editing path | `Editing {path}` |
| Save only / save+restart | `Save Config Only` / `Save and Restart` |
| Save success | `Configuration saved.` |
| Restart pending | `Configuration saved. Restart requested.` |
| Supervisor restart success | `service restart succeeded` |
| Restart failure | `Configuration saved, but service restart failed: {detail}` |
| Provider switch warning | `Provider changed. Existing options were kept and may not apply to the new provider.` |
| Blast title | `Update dependent API base URLs?` |
| Blast body | `Changing chat2api from {old_url} to {new_url} affects these apps. Only checked apps will have ai.api_base updated.` |
| Blast checkbox | `{display_name}: {old_url} → {new_url}` |
| Blast buttons | `Save with Selected Updates` / `Save chat2api Only` / `Cancel` |
| Dependent unreadable | `Cannot inspect dependent configuration {path}: {detail}` |
| Auth mismatch | `{app_id} uses ${dependent_env}, but chat2api auth_token_env is {server_env!r}; requests may fail with HTTP 401.` |
| Full unknown kind | `Unknown config_kind {kind!r}; expected llm, chat2api, or file-bridge.` |
| Bad draft type | `Configuration draft does not match this app's config kind; save refused.` |
| Host/port gate bypass | `Launcher has not passed the configuration probe; host/port changes cannot be saved.` |
| General transaction I/O | `Configuration save failed: {detail}` |
| Non-initialized valid labels | `Authentication disabled` / `Absent` |

For field-specific strict type/bound errors, use these messages instead of unstable Pydantic wording:

```text
Host must be a non-empty string.
Port must be an integer from 1 to 65535.
Provider must be echo, gemini_webapi, copilot_webapi, or browser.
Auth token environment variable must be null or a valid environment variable name.
Maximum text bytes must be an integer from 0 to 104857600.
Save root must not be empty or whitespace-only.
Save root does not exist.
Save root is not a directory.
Save root must not be inside the application directory.
Save root must be readable and writable.
Unknown file-bridge configuration key: {key}
```

Internal unexpected I/O/path failures append their OS detail to the general load/save template. Do not invent a degraded success for an unknown error. The supervisor success label means the supervisor command reported success (`A/src/ai_manager/services/supervisor.py:148`); a config save does not establish listener health.

### 9.5 Exception ownership

| Exception/source | Raised by | Caught by / outcome |
| --- | --- | --- |
| Pydantic `ValidationError` on metadata/request | Metadata/request construction | Registry/caller boundary; fail closed, unknown-kind text; no widget for an invalid registry entry. |
| `UnknownConfigKindError` | Every dispatch boundary | MainWindow/job error path; display error, no fallback/no write. |
| `ConfigLoadError` / `ConfigShapeError` / `SymlinkConfigError` | Structured loader and prepare path checks | MainWindow load/reload or save-failure slot; save disabled for load errors, retained draft for save errors. |
| `MissingExampleError` | Explicit example action | Structured view; show example-path error, emit no save/config-change event. |
| `ReadOnlyConfigError` | Render/commit/prepare or bypassed gate | Save worker then MainWindow; refuse, preserve draft and reason. |
| `ConfigValidationError` | Mutation normalization/stage 1/schema boundary | Save worker then MainWindow; mark fields, no target writes. |
| `InterpreterUnavailableError` | Interpreter resolution/import probe | `validate_candidate` only; convert to manager-only result with detail. |
| `ServiceValidationError` | Stage-3 nonzero exit other than unavailable code | Save worker then MainWindow; credential-safe stderr (field location and message preserved, input values redacted) panel; no commit/restart. |
| `ServiceValidationTimeout` | Stage-3 deadline | Save worker then MainWindow; refusal, child killed/reaped. |
| `StaleDocumentError` | Explicit create race or transaction prepare | MainWindow; stale choices only, no baseline update until explicit Reload. |
| `TransactionError` | Backup/stage/replace/rollback filesystem failure | MainWindow; use report phase/state text and all file rows; no restart. |
| `OSError`, `UnicodeError`, JSON/ruamel parser errors | OS/parsers | Owning load/validate/transaction operation translates as above, preserving cause; no raw worker exception disappears. |
| Internal `ValueError` on invalid operation/order | Programmer invariant violation | Worker wraps with general save failure; tests assert invalid call ordering; never retry as a different kind. |
| Probe spawn/exit/timeout/cleanup fault | Behavioral launcher probe | Convert to failed `LauncherProbeResult`, queued to MainWindow; host/port stay gated. |
| Supervisor action failure | QProcess/action callback | MainWindow restart message; saved file is retained and dirty stays cleared after a successful save. |

## 10. Exact Target B launcher

Replace `/data/home/guest/Development/ai/chat2api/start.sh` with this body. Preserve executable mode. It selects `PY` once and uses it for the version read, the service loader call, and uvicorn. `LISTENER` assignment propagates config-read failure through `set -e`; process substitution/read pipelines must not replace it because they can hide a child failure.

```bash
#!/usr/bin/env bash
set -euo pipefail

# chat2api — start the local OpenAI-compatible API server.
# Usage:
#   ./start.sh
#   ./start.sh --log-level debug
#   CHAT2API_CONFIG=prod.json ./start.sh

cd -- "$(dirname -- "$0")"

if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    PY="$PWD/.venv/bin/python"
elif [ -f venv/bin/activate ]; then
    source venv/bin/activate
    PY="$PWD/venv/bin/python"
else
    PY="$(command -v python)"
fi

echo "chat2api $(
    "$PY" -c 'from app import __version__; print(__version__)' 2>/dev/null || echo '?'
)"

LISTENER="$("$PY" -c '
from app.config import load_config
cfg = load_config()
print(cfg.server.host)
print(cfg.server.port)
')"
HOST="${LISTENER%$'\n'*}"
PORT="${LISTENER##*$'\n'}"

echo "Starting (host/port from config.json) ..."

exec "$PY" -m uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --timeout-graceful-shutdown 5 \
    --log-level info \
    "$@"
```

Path resolution is the loader's own: `load_config()` calls `load_dotenv()`, then uses the environment's `CHAT2API_CONFIG` value if the key is present, otherwise `config.json` (`B/app/config.py:80`). Because cwd is the script directory, a relative override and the default resolve there, regardless of caller cwd. An explicitly empty override follows the service loader too: opening the empty path fails; the script must not silently replace it with the default.

The Python call prints host and port on separate lines; the shell separates at the last newline. Command substitution removes the trailing newline, and quoting preserves the host as one argument. The loader supplies defaults/coercion; the launcher must not add a separate parser, pydantic schema, integer coercion, or auth check. Invalid JSON, invalid service schema, missing/unreadable config, unusable interpreter, or missing imports exit nonzero before uvicorn exec. Missing auth variables can still fail during uvicorn lifespan, matching service behavior.

`--host` and `--port` precede the fixed flags and final `"$@"`; later user-provided host/port/log flags win under the installed uvicorn/click parser. The real subprocess test must prove this rather than relying only on text/argv inspection. The version banner retains the existing `?` fallback on import failure; config loading still fails normally afterward.

Known double-read limitation: this loader call determines uvicorn arguments, then `B/app/main.py:82` loads config again during lifespan. An edit in that interval can produce different listener/config values. This feature does not change B's startup API or remove that race.

## 11. Literal fixture corpus

All fixtures are synthetic and contain no live credentials. All text blocks below end with one LF. Use a temporary root `W`; create directories explicitly. Placeholder expansion rules are exact: `${W}` becomes the absolute temporary root; `${P}`/`${Q}` become distinct allocated free TCP ports; no other shell interpolation occurs. Write with Python UTF-8 APIs, not a shell heredoc that expands secrets. For tests asserting serialization, use the exact before/after spelling shown.

### F-C: ordinary chat2api and explicit-auth-null echo probe

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8000,
    "auth_token_env": null
  },
  "models": {
    "echo-1": {
      "provider": "echo"
    }
  }
}
```

F-C lives at `W/chat2api/config.json`, with identical `config.example.json` unless overridden. For subprocess probes, replace only `8000` with `${P}` and model name `echo-1` with `echo-probe`; resulting literal structure is §7.3. Null disables auth even when the test environment lacks `CHAT2API_TOKEN`.

### F-F: file-bridge

Create `W/storage` outside `W/file-bridge` and make it readable/writable. Write this at `W/file-bridge/config.yaml` and as its example:

```yaml
# Local save destination
save_root: "../storage" # keep relative to config parent
max_text_bytes: 1048576
port: 8964
```

### F-L: dependent LLM configs

`W/ai-grammar/backend/config.yaml`:

```yaml
server:
  host: 127.0.0.1
  port: 8766
# Keep debug and commented choices
debug: false
ai:
  api_base: "http://127.0.0.1:8000" # bridge endpoint
  api_key: "$CHAT2API_TOKEN"
  model: "original-grammar"
  #model: alternate-grammar
  timeout:
    connect: 10
    read: 300
cache:
  enabled: true
```

`W/textkit/backend/config.yaml`:

```yaml
host: 127.0.0.1
port: 8765
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$CHAT2API_TOKEN"
  ocr:
    model: "original-ocr"
  text:
    model: "original-text"
  timeout:
    read: 1200
```

`W/yt2txt/backend/config.yaml`:

```yaml
host: "127.0.0.1"
port: 8666
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$CHAT2API_TOKEN"
  model: "original-transcribe"
cache:
  enabled: true
```

Copy each to its corresponding `config.example.yaml` for missing-LLM tests. `five_app_workspace` creates F-C, F-F, F-L and storage; it does not create service processes. Fixture setup stubs supervisor methods/QProcess, settings load/save, launcher probe outcomes, and stage-3 execution unless a test explicitly exercises those boundaries. Preserve offscreen QPA setup before QApplication construction (`A/tests/conftest.py:6`). Never let a MainWindow test invoke live services or write the user's settings.

### F-J: JSON fidelity before/after

Before (`W/chat2api/config.json`):

```json
{
  "_comments": {
    "keep": "ordinary data",
    "nested": [1, {"x": true}]
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8000,
    "auth_token_env": null,
    "future": {"keep": "yes"}
  },
  "models": {
    "gemini.fast/v2": {
      "provider": "gemini_webapi",
      "options": {
        "account": "fixture@example.invalid",
        "password": "fixture-password",
        "future": {"keep": [1, "雪"]},
        "headless": true
      },
      "route_extra": 17
    },
    "echo-1": {
      "provider": "echo"
    }
  },
  "tail": ["untouched", {"a": 1, "b": 2}]
}
```

After only `Mutation(("server", "port"), "set", 8123)`:

```json
{
  "_comments": {
    "keep": "ordinary data",
    "nested": [
      1,
      {
        "x": true
      }
    ]
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8123,
    "auth_token_env": null,
    "future": {
      "keep": "yes"
    }
  },
  "models": {
    "gemini.fast/v2": {
      "provider": "gemini_webapi",
      "options": {
        "account": "fixture@example.invalid",
        "password": "fixture-password",
        "future": {
          "keep": [
            1,
            "雪"
          ]
        },
        "headless": true
      },
      "route_extra": 17
    },
    "echo-1": {
      "provider": "echo"
    }
  },
  "tail": [
    "untouched",
    {
      "a": 1,
      "b": 2
    }
  ]
}
```

Assert exact after bytes for this renderer contract and parsed subtree equality/order separately. Unknown data is not stripped by schema construction. The fixture's unknown `headless` key for gemini stays raw, because the provider inventory is open.

### F-Y: YAML fidelity before/after

Before:

```yaml
# Bridge configuration
save_root: '../storage' # preserve destination spelling
max_text_bytes: 1048576 # keep limit
# Selected listener
port: 8964
# end
```

After only `Mutation(("port",), "set", 8970)`:

```yaml
# Bridge configuration
save_root: '../storage' # preserve destination spelling
max_text_bytes: 1048576 # keep limit
# Selected listener
port: 8970
# end
```

Assert quoted root, all comments, parsed untouched scalar values and relative order. No test may infer JSON fidelity from byte-range equality of an unrelated input's whitespace.

### F-A: anchored YAML (read-only)

```yaml
save_root: &root "../storage"
max_text_bytes: &limit 1048576
port: 8964
extra_alias: *limit
```

This deliberately contains an unknown key as well: loading remains viewable/read-only before any stage-2 save attempt. Test the anchor/alias reason independently of the service's unknown-key rejection. A separate no-anchor literal must stay editable:

```yaml
save_root: "../storage&star*"
max_text_bytes: 1048576
port: 8964
```

Create that directory for validation tests; a scanner must not flag its quoted punctuation.

### F-BAD: load-shape corpus

Each JSON block is a complete separate file:

```json
[]
```

```json
{"server": {"auth_token_env": null}, "models": []}
```

```json
{"server": {"auth_token_env": null}, "models": {"x": 1}}
```

```json
{"server": {"auth_token_env": null}, "models": {"x": {"provider": "echo", "options": null}}}
```

```json
{"server": {"auth_token_env": null}, "models": {"x": {"provider": "echo", "options": []}}}
```

```json
{"server": [], "models": {}}
```

```json
{"models": {"same": {"provider": "echo"}, "same": {"provider": "browser"}}}
```

YAML separate files:

```yaml
- not
- a mapping
```

```yaml
null
```

```yaml
port: 8964
port: 8970
```

Also use malformed JSON bytes `b'{"server":'`, malformed YAML bytes `b'save_root: [unterminated\n'`, and invalid UTF-8 `b'\xff'`. These are byte fixtures, not valid JSON/YAML blocks.

### F-V: scalar validation cases

Use F-C with the following complete `server` objects, keeping its models unchanged. Each row's JSON is literal fixture data:

```json
[
  {"host": "127.0.0.1", "port": true, "auth_token_env": null},
  {"host": "127.0.0.1", "port": "8000", "auth_token_env": null},
  {"host": "127.0.0.1", "port": 8000.0, "auth_token_env": null},
  {"host": "127.0.0.1", "port": 0, "auth_token_env": null},
  {"host": "127.0.0.1", "port": 65536, "auth_token_env": null},
  {"host": "127.0.0.1", "port": 1, "auth_token_env": null},
  {"host": "127.0.0.1", "port": 65535, "auth_token_env": null},
  {"host": "", "port": 8000, "auth_token_env": null},
  {"host": "127.0.0.1", "port": 8000, "auth_token_env": ""},
  {"host": "127.0.0.1", "port": 8000, "auth_token_env": "BAD-NAME"},
  {"host": "127.0.0.1", "port": 8000, "auth_token_env": "9BAD"},
  {"host": "127.0.0.1", "port": 8000, "auth_token_env": "_TOKEN_9"},
  {"host": "127.0.0.1", "port": 8000, "auth_token_env": null},
  {"host": "127.0.0.1", "port": 8000},
  {"host": "localhost", "port": 8000, "auth_token_env": null},
  {"host": "LOCALHOST", "port": 8000, "auth_token_env": null},
  {"host": "::1", "port": 8000, "auth_token_env": null},
  {"host": "0.0.0.0", "port": 8000, "auth_token_env": null},
  {"host": "::", "port": 8000, "auth_token_env": null},
  {"host": "192.0.2.5", "port": 8000, "auth_token_env": null},
  {"host": " localhost ", "port": 8000, "auth_token_env": null},
  {"host": "localhost\n", "port": 8000, "auth_token_env": null},
  {"host": "127.0.0.2", "port": 8000, "auth_token_env": null}
]
```

The 23 rows above partition as follows. **Valid (8):** rows 6, 7, 12, 13, 14, 15, 16, 17 — ports 1 and 65535; `_TOKEN_9`; explicit `null`; defaulted auth; `localhost`; `LOCALHOST`; `::1`. **Invalid (15):** rows 1–5, 8–11, and 18–23. Rows 18–23 are the loopback rule: `0.0.0.0`, `::`, `192.0.2.5`, `" localhost "`, `"localhost\n"`, and `127.0.0.2` all fail R-HOST-LOOPBACK. Named/default auth success in service validation additionally requires the corresponding environment variable or `.env` value.

For F-F replace exactly one scalar with the YAML literal selected below. These are replacement scalar literals, not strings passed through a coercing parser:

```yaml
# port invalid: true | "8964" | 8964.0 | 0 | 65536
# port valid: 1 | 65535
# max_text_bytes invalid: true | "1" | 1.0 | -1 | 104857601
# max_text_bytes valid: 0 | 1048576 | 104857600
```

For a name/provider corpus, use these complete model maps as the F-C `models` value:

```json
[
  {"": {"provider": "echo"}},
  {"x": {"provider": "unknown"}},
  {"x": {}},
  {"x": {"provider": "echo"}},
  {"x": {"provider": "gemini_webapi", "options": {}}},
  {"x": {"provider": "copilot_webapi", "options": {"future": [1, null]}}},
  {"x": {"provider": "browser", "options": {"url": "https://example.invalid"}}}
]
```

First three fail; last four pass in-process with options absence preserved. Duplicate table rows are supplied as two UI rows both named `same`, not as a Python dict that already lost the duplicate.

### F-AUTH: service auth and mismatch

```json
{
  "server": {"host": "127.0.0.1", "port": 8000, "auth_token_env": "FIXTURE_TOKEN"},
  "models": {"echo-1": {"provider": "echo"}}
}
```

For dotenv success create a temporary B-like app fixture whose `.env` contains this synthetic literal:

```dotenv
FIXTURE_TOKEN=fixture-bearer-value
```

For mismatch replace only F-L's API key with the following YAML scalar:

```yaml
api_key: "$OTHER_TOKEN"
```

The warning fixture uses server name `CHAT2API_TOKEN`, not the F-AUTH fixture name. Literal API keys and empty keys do not name an environment variable and do not trigger this specific warning.

## 12. Required automated tests and precise assertions

Test identifiers below are required scenarios; names may combine parameterized cases, but no listed assertion may be omitted. F-C/F-F/F-L and variants are the literal data for every scenario that does not explicitly provide another fixture. Patch only the stated scalar/tree or OS failure, retaining all other fixture bytes.

### 12.1 `tests/test_structured_config.py`

| Scenario/setup | Required assertions |
| --- | --- |
| Load F-C/F-F | Kind, requested/resolved paths, raw bytes and `sha256(raw).digest()` match; existed true; no edits/issues; effective defaults are not injected into parsed tree. |
| Missing F-C target, example present | `load` returns absent record; neither load nor view construction creates a target, backup or lock. Explicit example action creates a dirty draft only. Commit creates mode 0600 after validation; if target appears first, stale refusal preserves it. |
| F-J port edit | Bytes equal F-J after; `_comments`, `tail`, every option/secret/route-extra untouched subtree compare equal; root key order and untouched nested key order compare equal. `options` remains absent on echo. |
| Literal-key address | Edit F-J key `gemini.fast/v2` headless only. Assert only that option changes, and no accidental `gemini`/`fast` nested mapping appears. |
| Delete/rename | Remove echo and rename `gemini.fast/v2`; untouched siblings keep relative order; renamed route has all original unknown data/secrets. No unwanted options defaults appear. |
| F-Y port edit | Exact after content; all comments/quote spelling retained; root key order `save_root,max_text_bytes,port`. |
| F-A | Parsed tree viewable; anchor/alias reason present; render/commit refused; raw bytes unchanged. Quoted-punctuation fixture does not acquire that reason. |
| F-BAD | Each wrong shape/duplicate/non-UTF8 raises typed load/shape error with addressed message; no default empty config; no target/backup writes. |
| Symlink and dangling symlink | Create leaf link before load, spy on `Path.lstat`; both raise SymlinkConfigError before target resolution/read; link and referent unchanged. Also change a loaded regular file to a symlink before prepare and assert refusal. |
| Non-writable | chmod F-C 0444 with writable parent; load read-only; save refused; inode/bytes/mode unchanged, including root-run test behavior. Restore fixture mode in test cleanup. |
| Mode preservation | chmod F-C 0640, save port edit, `stat.S_IMODE(path.lstat().st_mode)==0o640`; backup mode same. Repeat on rollback path in transaction tests. |
| Exclusive/colliding backups | Freeze UTC timestamp and PID; patch nonce sequence to `a1b2c3,a1b2c3,d4e5f6`; save twice. Assert distinct names, first backup bytes never truncated, O_EXCL was present, collision was retried and each backup contains the appropriate prior exact bytes. |
| No-op fidelity/dirty | Load compact `{"models":{}}\n`; normalized render differs from raw, but saved-vs-draft render equality is true and GUI starts clean. |
| Secret untouched vs changed | Change only port in F-J with password editor untouched/revealed. Password bytes as a parsed value remain original; explicit empty edit writes `""`; explicit remove deletes only addressed secret. |

### 12.2 `tests/test_structured_validation.py`

1. Run every F-V scalar and provider case through stage 2. Assert pass/fail partition specified there, exact field address/message, and strict rejection of bool/string/float integers for both kinds. Assert boundary inclusion at ports 1/65535 and max bytes 0/104857600.
2. Run all F-BAD mapping/options cases through loader and schema as applicable. Missing options succeeds and is still absent after unrelated render. Nonmapping options/entry/models never becomes a default empty model map.
3. For root-path rules use these YAML scalar variants in F-F:

```yaml
# Each line is an independent save_root replacement value:
save_root: ""
save_root: "   "
save_root: null
save_root: 42
save_root: "../does-not-exist"
save_root: "../plain-file"
save_root: "."
save_root: "./nested"
save_root: "../storage"
save_root: "../资料"
```

Create `W/plain-file` as a regular file, `W/file-bridge/nested` as a directory, and `W/资料` as writable. First eight fail; final two pass. Assert resolved relative root equals config-parent resolution and both app directory itself and descendants are excluded. Patch `expanduser` to the temporary test home for a separate literal `save_root: "~"` case; no real HOME writes. For an external unreadable/unwritable directory, use OS permissions when meaningful and patch `os.access`/TemporaryFile to fail deterministically otherwise; assert refusal and no target write.
4. Stage 1: submit `set` mutations containing each of `"bad\nvalue"`, `"bad\rvalue"`, `"bad\u0000value"` separately in host, model name, option value, auth name and save root. Assert stage-1 field issue and that stage 2/service validator were not called. Recurse into addressed raw-option objects/lists. Literal fixture:

```json
{"models": {"echo-1": {"provider": "echo", "options": {"future": "already\nodd"}}}, "server": {"auth_token_env": null}}
```

An unrelated port mutation does not trigger stage-1 inspection of the untouched odd string. Unicode `"雪"`, `"资料"`, and an edited option `"a\tb"` pass stage 1; later per-field schema rules still apply.
5. Add unknown YAML key using literal `unexpected: true` to F-F. Assert schema refuses with the exact unknown-key message, renderer still preserves the key, and no service process is needed to detect it.
6. F-AUTH: in-process validates both named and null auth; only stage 3 checks the variable's presence. Assert no unconditional guarantee is inferred from stage-2 success.

### 12.3 `tests/test_validator_orchestration.py`

Use an executable fake interpreter at the path selected by each fixture. Its harness records cwd, argv, candidate bytes/path, and environment; it returns success for the import-probe code and the configured result for the validation code. Do not make “exit 1” accidentally fail the import probe and thereby test only degradation.

Representative fake executable body; generate the initial `MANAGER_TEST_*` values in its environment, not by editing a live environment file:

```python
#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

program = sys.argv[2] if len(sys.argv) > 2 else ""
if len(sys.argv) == 3:
    raise SystemExit(int(os.environ.get("MANAGER_TEST_IMPORT_EXIT", "0")))
record = {
    "cwd": str(Path.cwd()),
    "argv": sys.argv[1:],
    "candidate": str(Path(sys.argv[3])),
    "bytes": Path(sys.argv[3]).read_text(encoding="utf-8"),
}
Path(os.environ["MANAGER_TEST_RECORD"]).write_text(json.dumps(record), encoding="utf-8")
print(os.environ.get("MANAGER_TEST_STDERR", ""), file=sys.stderr)
raise SystemExit(int(os.environ.get("MANAGER_TEST_VALIDATOR_EXIT", "0")))
```

The fake's shebang interpreter is resolved independently of the candidate `python` under test; ensure PATH provides `python3`. A separate timeout fake blocks until killed, with the parent harness recording/reaping its PID.

| Setup | Required assertions |
| --- | --- |
| F-C/F-F, import 0, validator 0 | Scope `service`; correct kind notice; command/cwd exact; candidate bytes equal rendered; hidden candidate parent equals target resolved parent; candidate removed afterward. |
| Validator 1, stderr `fixture schema error\n` | ServiceValidationError returncode 1 and credential-safe stderr (field location and message preserved, input values redacted); no commit, no degraded notice. |
| Missing interpreter or import exit 1 | Manager-only exact notice; validator not invoked; in-process validation still ran; invalid port still blocks. |
| Validator import unavailable exit 75 | Manager-only exact notice with captured detail, child reaped and candidate removed. |
| Validator timeout | ServiceValidationTimeout; kill/reap called; candidate cleaned; no commit. Import timeout instead means interpreter unavailable. |
| Both `.venv` and `venv` activation files | Pick `.venv/bin/python` only; do not resolve its symlink to a base interpreter. |
| Only `venv/bin/activate` plus executable | Pick `venv/bin/python`; compare with launcher spy evidence from Target B tests. |
| No activation file, PATH python | Pick ambient fixture python; same launcher spy path. A `.venv` directory without activation does not win. |
| Selected activation with missing/nonexec python | Unavailable, no fallback to ambient. |
| Symlinked config parent | Candidate created beside the actual config directory after parent resolution, not `/tmp` or the lexical parent elsewhere. |
| Relative F-F root | Fake inspects location; optional real C interpreter calls `load_config` and `_probe_save_root` against an adjacent candidate, resolving `../storage` correctly. Deterministic fake case is mandatory even if optional real probe is skipped. |
| Chat validation code | Assert calls load_config, Registry, validate_auth; instrument fake modules so startup_login/ensure_discovered throw if called, and prove neither executes. |
| Real auth contract with temporary modules/dotenv fixture | F-AUTH with absent/empty variable rejects; with `.env` fixture value passes; explicit null passes without a token. Never rely on the developer's `.env`. |

### 12.4 `tests/test_transaction.py`

Use F-C plus F-L, recording exact initial bytes and modes. Stage new bytes with only port/API-base mutations. Spy at the transaction's OS boundary rather than monkeypatching unrelated `Path` operations globally.

| Scenario/setup | Required assertions |
| --- | --- |
| 0, 1, 3 checked dependents | Exactly 1, 2, 4 targets; all hashes checked, every existing file backed up, stage creates only temps, sorted replace order, report every file `new`, committed true, locks closed. |
| Stale any member | Hand-edit one target after snapshot but before prepare. Raise StaleDocumentError with old/current digests; no backups/stage/replace; all target bytes including hand edit unchanged; locks released. Test primary and a dependent separately. |
| Deleted/created race | Existing target deleted or absent explicit-create target created before prepare gives digest mismatch with None semantics; no overwrite. Empty-file digest is distinct from None. |
| Lock ordering | Pass reverse/random path order; assert opens/flocks, hash checks, replaces use sorted canonical path order. Two worker processes request `[a,b]` and `[b,a]`; both finish without deadlock and leave valid sequential results when expected hashes are refreshed by the second process, or second refuses stale safely. |
| Sidecar identity | Another cooperating process blocks on the sidecar through primary `os.replace`, acquires only after release, and rereads the new target inode; sidecar pathname remains after both exit. |
| Backup failure on later target | Inject write/fsync/O_EXCL-open error after one complete backup. Zero replaces; all targets byte/mode-identical; complete earlier backup survives; no leaked locks. |
| Render failure on dependent | Raise before tx prepare; no writer/replace calls and every target byte-identical. This specifically prevents use of `write_app_config` as a renderer. |
| Stage failure on later target | Inject temp write/fsync failure; zero target replaces; all target bytes/modes unchanged; all stage temps removed and completed backups retained. |
| Replace failure on second/last target | Inject once, then allow restoration; already-replaced paths restored in reverse order; all final bytes/modes original; report all paths restored, committed false. |
| Parent fsync failure after replace | Already-replaced target is included in rollback; report cannot claim untouched merely because fsync raised. |
| Restore failure | Replace first two, fail third, then fail restoring one replaced path. Continue restoring the others; failed path state unknown, named in restore_failures; other paths restored; every participating path has report row; no restart. |
| Explicit creation rollback | Primary originally absent, later replacement fails; rollback removes newly created target and fsyncs parent; state restored means absence, no fabricated backup. |
| Invalid phase/dictionary keys | Repeated/out-of-order method calls and extra/missing rendered/expected keys fail before target write; context cleanup still releases descriptors. |

A staging-purity assertion must compare actual target bytes on disk, not merely mock call counts. A rollback test must compare originals and report states, not just observe that a restore function was called.

### 12.5 `tests/test_blast_radius.py`

Start with F-C/F-L. Change chat2api port 8000 to 8123; the expected dependent after image for ai-grammar is the same F-L text with only this line changed:

```yaml
  api_base: "http://127.0.0.1:8123" # bridge endpoint
```

Required cases:

1. All three matching bases: detection returns exactly ai-grammar, textkit, yt2txt in registry order; unrelated apps excluded. Compare snapshots to original file bytes/hashes.
2. Host/port unchanged, options/auth changed: no blast dialog, no dependent inspection/rewrite transaction members.
3. Change textkit's scalar to literal `api_base: "https://api.example.invalid"`; detect only ai-grammar and yt2txt. Do not match mere substring occurrences in comments or timeout/raw values.
4. Check only textkit: all checkboxes initially unchecked; transaction contains chat2api+textkit after explicitly checking it; other dependent bytes unchanged. Check all: four-file transaction. Choose Save chat2api Only: one-file transaction. Cancel: no render/validation/transaction call.
5. Assert every dependent's API key, model/split models, timeouts, cache, comments, scalar quote styles, root/nested order and values remain unchanged. Spy that `write_app_config` is never called. Compare pure renderer output before/after all subtrees other than `("ai","api_base")`.
6. Unreadable/missing/anchored dependent: detection raises with the exact inspection message, the combined save is refused with draft retained, and it does not auto-create from an example. No silently fabricated default AppAIConfig participates.
7. Dirty dependent: set grammar draft model `unsaved-model` before rewrite; after success its disk model remains `original-grammar`, saved baseline base becomes 8123, widget/draft model stays unsaved-model and draft base remains its old value; dirty stays true. Clean dependent instead reloads base 8123 and stays clean.
8. Stale dependent after dialog: hash refusal is all-or-nothing; neither primary nor any checked dependent changes.
9. Auth mismatch using F-AUTH/F-L variant: warning only for a named `$OTHER_TOKEN` versus named server auth; literal/empty key or disabled auth does not produce this specific warning. Warning does not edit keys or block an otherwise approved save.
10. URL matching uses rule R-HOST-CLASS (§7.4): strip **at most one** trailing
    `/` from each side, then `normalize_loopback_url` both sides and require
    exact equality. This table is normative and was executed during design
    against `http://127.0.0.1:8000`; every row must pass:

    | `api_base` | matches base? |
    | --- | --- |
    | `http://127.0.0.1:8000` | yes |
    | `http://127.0.0.1:8000/` | yes |
    | `http://localhost:8000` | yes |
    | `http://[::1]:8000` | yes |
    | `http://LOCALHOST:8000` | yes |
    | `http://127.0.0.1:8000/v1` | **no** |
    | `http://127.0.0.1:8001` | **no** |
    | `https://127.0.0.1:8000` | **no** |
    | `http://127.0.0.1:8000/?x=1` | **no** |
    | `http://0.0.0.0:8000` | **no** |
    | `http://127.0.0.1:8000///` | **no** |
    | `http://user:pw@127.0.0.1:8000` | **no** |

    Host normalization is comparison-only and is **never** applied on write;
    the dependent receives exactly `new_url`.

### 12.6 `tests/test_structured_view.py`

Use `qtbot` and deterministic stub stage-3/gate outcomes. No live launcher is needed in widget tests.

- F-C chat2api creates Server+Models groups and both tabs; F-F creates exactly its three fields, no chat/LLM controls. Log view service id equals metadata id.
- Add row `new-echo`/echo, expand it, set prefix `hello`, remove echo-1: emitted draft has only the explicit new-route/removal mutations; no action saves automatically. Duplicate/empty row names remain dirty with field errors; no dictionary collapse loses them.
- Load F-J: absent options on echo stays absent after port edit; reveal account/password never emits config_changed or changes their flags. Explicit secret edit/removal changes only its address, and provider switch preserves all unknown/secret keys with warning.
- Raw unknown object edit to literal `{"future":{"keep":[1,"雪"]},"headless":false}` changes only that raw key; raw invalid literal `{broken` remains in draft and counts dirty, with correct message; known/secret collision is refused.
- Review Changes for F-J shows `8000` removed and `8123` added in unified diff, includes unchanged surrounding keys, does not write, and does not mark a clean view dirty. Account/password visibility follows existing draft data in the local diff; no diff is logged or persisted.
- Read-only F-A/F-BAD/symlink/0444/missing cases show exact catalog messages, disabled saves, and no load-time config/save signals. Gate failure disables only host/port and rewrite; models/auth remain editable. Gate pending has its own text.
- Stale save/validator rejection leaves get_current_draft unchanged; emits no second save/config_changed/fetch signal. Error detail preserves the credential-safe service stderr (field location and message kept, input values redacted). Reload choice discards, Cancel preserves, Show diff does not change baseline/hash.
- Header configured port is 8000/8964 on load and committed value after save, not the unsaved edited value. Status update changes badge and log state with no config signal; reported log path survives a later status without path, falling back only before any report.
- MainWindow owns dirty computation; switching tabs, selection, row expansion, reveal, and validation label updates cannot set/clear a sidebar dirty flag independently.

### 12.7 `tests/test_sidebar_port.py`

F-C/F-F initial ports, then committed JSON port 8123 and YAML port 8970. Assert item and structured header show saved configured value, metadata defaults remain 8000/8964, and status/dirty updates do not reset the configured cache. Unsaved draft port has no sidebar effect. Delete/corrupt config and explicitly reload: fall back to default when unreadable. Invalid scalar `port: "8964"` likewise cannot be displayed as a validated configured port. LLM entries keep their existing metadata-port behavior in this feature.

### 12.8 `tests/test_preset_auth.py`

Locate preset by id, assert default env name exactly CHAT2API_TOKEN; selecting preset in LLM view emits `$CHAT2API_TOKEN`. Use mismatch literals in §11: exact warning includes app id, `$OTHER_TOKEN`, server env repr and HTTP 401; matching names, plaintext API key, empty key and explicit auth null do not emit that warning. The preset change must not rewrite any existing config during load.

### 12.9 `tests/test_launcher_gate.py`

1. Inject failed LauncherProbeResult with stderr: host/port disabled, inline failed text, no D7 action; edit models and save with valid auth config still allowed. Submit a forged host mutation and assert refusal before disk write.
2. Inject success: host/port enabled, passed text, D7 detection enabled. Pending result has disabled fields and pending text.
3. Construct/select/reload the chat view several times: exactly one probe per resolved app-dir/session; new MainWindow session probes again.
4. Exercise actual `probe_launcher` against the real B launcher using the §7.3
   echo/null fixture: the fixed launcher passes and reports the configured listener;
   the pre-fix baseline (`c40e3c6:start.sh`) fails closed. **Neither case binds a
   socket** — see §7.3.3 and the amendment note. The live-bind readiness proof lives
   in B's own `tests/test_launcher.py`, not here. Never run the old launcher against
   the live B config.
5. **(Superseded by the §7.3 amendment.)** The historical harness asserted early-exit
   behaviour against a readiness deadline and pipe-buffer back-pressure. Under the
   capability-flag design the gate spawns nothing but `start.sh --print-listener`, so
   those cases are covered instead by the unit tests for non-zero exit, timeout, and
   captured-stderr propagation.
6. **(Superseded by the §7.3 amendment.)** Readiness polling and process-group
   escalation no longer exist on this path; `subprocess.run` awaits and reaps the single
   child. The timeout case is asserted directly.

### 12.10 `tests/test_fetch_routing.py`

F-L and a fake worker whose terminal signal is controlled by the test. Start grammar request token 1, switch to textkit, deliver response token 1 with literal payload:

```json
{"data": [{"id": "grammar-only"}]}
```

Assert grammar receives/installs `grammar-only`, textkit does not, request app_id is ai-grammar. Also run simultaneous grammar/textkit token 1 requests with payloads `{"data":[{"id":"g"}]}` and `{"data":[{"id":"t"}]}` and deliver in reverse order; each origin gets only its models. A second grammar request token 2 makes late token 1 stale only for grammar. Select chat2api/file-bridge before response and prove neither receives an LLM response or emits fetch itself.

### 12.11 Extend `tests/test_supervisor.py`

Use this complete status literal:

```text
[2026-10-17 16:07:34] supervisor running: 34491
ai-grammar   running  pid=101 log=/tmp/logs/ai-grammar.log
textkit      running  pid=102 log=/tmp/logs/textkit.log
yt2txt       stopped  pid=- log=/tmp/logs/yt2txt.log
chat2api     running  pid=104 log=/tmp/logs/chat2api.log
file-bridge  running  pid=105 log=/tmp/logs/file-bridge.log
```

Assert five statuses; file-bridge id/state/pid/log exact; stopped service pid None. Stub QProcess, invoke `restart_service("file-bridge")`, assert executable and argv `["restart","file-bridge"]` and normal action completion/refresh. No parser special case by kind. Preserve existing stopped-supervisor and default-log-path tests (`A/tests/test_supervisor.py:36`, `:73`).

### 12.12 Target B `tests/test_launcher.py`

Tests run a temporary app copy of real `app/` and `providers/` plus the actual repository `start.sh`, with the installed test environment exposed as the chosen conventional venv or ambient interpreter. Use copied/synthetic dotenv state, never the live config/credentials. Use absolute symlinks for interpreter executables but retain the venv entrypoint path; build genuine temporary venv activation scripts or a minimal activation script that prepends its `bin` directory. Config files are F-C echo/null fixtures with allocated ports.

Required real-launcher subprocess cases:

1. Absolute CHAT2API_CONFIG, configured `${P}` != 8000: invoke real start.sh and poll using §7.3's child-exit/readiness/reap algorithm. Assert TCP connection to `${P}` succeeds while child lives. Additional GET `/v1/models` yields 200 and an echo model id, proving startup rather than only argv construction. If 8000 was unbound immediately before spawn, assert it remains unbound; if already occupied, record that only this negative assertion is inapplicable, not that the configured-port test passed by default.
2. Override: config `${P}`, invoke `start.sh --port ${Q}` with distinct free ports; `${Q}` binds and serves echo, `${P}` stays unbound. Also override `--host 127.0.0.1` and `--log-level debug`; verify successful parser acceptance. Do not pass a config-changing option that bypasses the fixture.
3. Relative CHAT2API_CONFIG: place `relative-probe.json` in temporary app dir, invoke launcher from a different cwd with override `relative-probe.json`; configured port binds. Repeat absolute override. No override: fixture `config.json` in script dir binds. This proves `cd` resolution, not caller-cwd behavior.
4. Missing config path: child exits nonzero before readiness deadline; no configured/default listener is created; captured stderr identifies FileNotFoundError/path. Invalid JSON literal `{"server":` and invalid service port literal `{"server":{"port":"invalid"},"models":{}}` both exit nonzero before uvicorn. Empty CHAT2API_CONFIG also fails following loader semantics. Negative old-default checks are conditional on preflight availability.
5. Only `venv/`: no `.venv/bin/activate`, create `venv/bin/activate` and instrument `venv/bin/python` forwarding to the real test interpreter while recording its lexical argv path for every invocation. Assert version/config read/uvicorn all use that path, and A resolver selects that same lexical path. Repeat no virtualenv with fixture ambient `python` on PATH. Also assert `.venv` takes precedence when both activation files exist.
6. Interpreter/config-read failure: instrument selected python to exit 42 on the config-read program; assert no `-m uvicorn` invocation. A directory named `.venv` without activate must not override ambient python.
7. For each success, early exit, timeout, assertion failure, and override path, a `try/finally` terminates the process group, escalates after 2 seconds if needed, and waits for the child. Assert `poll()`/`wait()` confirm reaping and the test-owned port is closed afterward. Never kill by matching a port or service name.

The behavioral cases are mandatory automated acceptance. Fast argv/interpreter-spy cases supplement them; they cannot replace socket readiness against the real app.

### 12.13 Existing-suite migration inventory

Every file named in approved design §9 is accounted for here. These source citations describe the inspected files, which differ slightly from the design's historical line references.

| Existing file and source evidence | Fixture/setup and required assertions after change |
| --- | --- |
| `test_app_registry.py:15` | Temporary workspace path, no files required. Exact id set five; kinds llm/llm/llm/chat2api/file-bridge; correct filenames/paths/ports; only free-tts excluded. Invalid metadata kind fails with clear error; omitted kind defaults llm. |
| `test_e2e_integration.py:10` | Replace unsafe live-workspace registry loop with five_app_workspace F-C/F-F/F-L and stub external execution/settings. Branch by kind: AppAIConfig model/base for each LLM, chat server/models including absent options, file-bridge root/limit/port. MainWindow creates five correct widget types and initial selection grammar. No silently defaulted AppAIConfig passes a structured assertion. |
| `test_app_views.py:11`, `:39` | Existing LLM/sidebar fixtures remain; construct AppDetailView only for llm kinds. Assert five sidebar entries and add sibling structured cases using F-C/F-F; preserve tabs/log path/split-model assertions. |
| `test_mnemonic.py:210`, `:248` | Use five_app_workspace and stub probes; sweep both new structured views and BlastRadiusDialog. Add model name `qwen&co/7b` and root `../A&B`; escape only mnemonic-aware sinks, preserve raw model/path in draft. Existing chip test remains llm-only. |
| `test_models.py:12` | Preserve current display/serialization tests; add equal AppAIConfig copy vs changed model comparisons and structured render-equality/invalid-draft contracts using F-C/F-J. Add required app_id validation and unknown kind failure. Existing file does not currently pin all these equality cases; add them. |
| `test_yaml_manager.py:26`, `:49`, `:78` | Keep current four fixture YAML files and their exact existing read/split/comment assertions. Two-arg writer still returns None and creates single-name `.bak`. New pure renderer uses synthetic F-L, changes only base, touches no filesystem. Optional expected digest stale path refuses with unchanged target; matching digest uses transaction behavior. |
| `test_main_window.py:14`, `:42` | Use five_app_workspace; assert three LLM/two structured views, per-kind dirty, navigation preserves drafts, five-app status normalization, successful structured port update and failed validation no restart. |
| `test_main_window_tray.py:21` | Extend fixture to five apps, retain settings isolation/stub external work. Dirty a structured field as well as existing grammar test; close-to-tray preserves draft; explicit quit prompts; committed save clears only its own dirty state. Preserve all existing settings/start-minimized tests. |
| `test_model_fetcher.py:23`, `:51`, `:65` | Add app_id ai-grammar/textkit/yt2txt to existing requests. Retain respx payloads: OpenAI ids gemini-flash-high/gpt-5.6-terra/deepseek-flash, Ollama names llama3:latest/qwen2.5:32b, 401 error JSON. Assert HTTP results/token semantics unchanged; origin routing separately tested in §12.10. |
| `tests/conftest.py:6` | Preserve offscreen setup and tray fixture. Add fixture corpus/workspace and reusable stubs; never mutate user configs/settings or start a production service as a side effect of construction. |

Verification commands for implementers, from the appropriate delivery checkout:

```bash
# Target A
PYTHONPATH=src pytest tests/

# Target B, using its selected environment with declared dev dependencies
python -m pytest tests/test_launcher.py
python -m pytest
bash -n start.sh
```

No C source/test changes or C dependency installation is part of delivery. An optional existing-C-venv validation probe must be reported separately from the deterministic mandatory tests.

## 13. Migration and operational limits

1. Existing three LLM config formats, examples, normalized equality, model transitions and two-argument writer semantics remain compatible. The new metadata default means old metadata construction sites continue to represent llm. Requests constructed by internal callers/tests now must supply app_id. There is no settings schema migration.
2. First run lists all five apps. Existing structured files are read without creation or normalization writes. A missing new-kind file shows empty sections and Create from Example; it remains absent until explicit save passes validation. Existing LLM missing-file example copy remains unchanged. Launcher capability check runs once per session by invoking `start.sh --print-listener` against the installed configuration (synthetic echo/null configs belong to the acceptance tests in B, not to this runtime check); it binds nothing and its diagnostics are redacted.
3. First successful structured save normalizes JSON to indent 2 plus LF, or uses the YAML round-trip engine. Untouched parsed values/order survive; byte formatting across a JSON file need not. Complete original bytes remain in timestamped exclusive backups. Existing mode bits are retained; a new file uses 0600.
4. `chat2api_local` now selects `$CHAT2API_TOKEN`. Existing saved `$CHAT2API_API_KEY` values are not silently migrated. A differing named auth variable gets the mismatch warning; the user chooses any credential/key change.
5. If B is never updated, the behavioral gate fails and chat2api host/port plus D7 rewrite stay read-only. Models/options/auth remain editable and validated; logs/status/restart remain available. There is no version-string or manual override bypass. A cannot be declared delivered independently of B under the approved two-target gate.
6. Stage-3 degradation permits saves validated by ai-manager only. A save cannot prove restart readiness, provider credentials/login, discovery, dependency installation, port availability, supervisor environment equivalence, or remote model behavior. Named auth-env availability is checked only when service validation actually runs.
7. Save and Restart saves first; supervisor failure does not roll back a valid config. The UI retains the saved baseline and reports the restart failure. The sidebar port is the effective configured value, not proof of a current live listener, especially before restart or with a failing launcher gate.
8. Sidecar locks coordinate participating writers. Hand editors that ignore them can still race after the observed hash check. A multi-file transaction can be seen partially by unlocked readers and can be interrupted by process/power failure; backups and explicit failure reports are the recovery mechanism, without an automatic journal.
9. B still reads config twice at startup. A concurrent edit between listener extraction and lifespan loading can disagree with the bound listener. A later CLI `--host`/`--port` override also intentionally supersedes config; the GUI's configured port does not claim to discover such supervisor command overrides.
10. file-bridge remains IPv4-loopback-only (`C/main.py:45`); its editor exposes no host. `max_text_bytes=0` leaves the hard transport cap in force. Save-root validation creates and immediately closes a temporary probe file, not user data or a directory.

## 14. Resolved Decisions

Both questions raised during specification drafting were resolved by explicit
user decision and are now normative requirements, not open items.

1. **Wildcard listener hosts and dependent URLs → resolved: reject wildcards.**
   Rule R-HOST-LOOPBACK (§7.4) restricts `server.host` to `127.0.0.1`,
   `localhost`, or `::1`. Rule R-HOST-CLASS (§7.4) treats those three spellings
   as one equivalence class for blast-radius matching, so an alias change is
   detected and dependent URLs are rewritten with the primary's saved spelling.
   No wildcard-to-loopback translation exists because no wildcard value can be
   saved.
2. **Non-default `CHAT2API_CONFIG` and GUI target identity → resolved: documented
   limitation.** The editor edits `<app_dir>/config.json` only. An externally
   set `CHAT2API_CONFIG` is not discovered, and the UI header states this
   explicitly (§7.5). No claim is made that editing the registry default edits
   an overridden service config.
