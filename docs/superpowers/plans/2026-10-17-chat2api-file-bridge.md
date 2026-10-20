# chat2api and file-bridge Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.

**Goal:** Manage all five supervised applications with format-specific editors, validation, recoverable configuration saves, and a chat2api launcher whose configured listener actually binds.

**Architecture:** Target A keeps the existing LLM adapter and adds an addressed structured-document layer, an advisory-lock transaction, service-validation workers, and a sibling structured Qt view. One pure editor model owns draft mutations; MainWindow owns dirty state, worker lifetimes, request origin, launcher gating, and dependent reconciliation. Target B changes only its launcher and acceptance test; it must be installed with or before Target A.

**Tech Stack:** Python, PyQt6>=6.5.0, pydantic>=2.0.0, ruamel.yaml>=0.18.0, httpx>=0.25.0; existing pytest/pytest-qt/respx tooling; Bash, POSIX flock, fsync, subprocesses and loopback sockets. No dependency or version change.

## Global Constraints

- Authority: `docs/superpowers/specs/2026-10-17-chat2api-file-bridge-design.md` revision 4, then `docs/superpowers/specs/2026-10-17-chat2api-file-bridge-spec.md`. The resolved decisions in spec §14 are normative.
- Target A canonical repository is `/data/home/guest/Development/ai/ai-manager`; implement its paths in the isolated Target A execution checkout. Target B canonical repository is `/data/home/guest/Development/ai/chat2api`; implement Task 13 in its separate execution checkout. Absolute canonical paths in Files blocks identify ownership, not permission to edit a primary checkout instead of an assigned worktree. All other tasks belong only to Target A. Never put a Target B change into a Target A commit.
- No file in `/data/home/guest/Development/ai/file-bridge` changes. No production Python file in Target B changes. Target B changes only `start.sh` and `tests/test_launcher.py`.
- Both targets form one atomic delivery unit. Target B is a hard prerequisite for Target A. Task commits below are execution instructions; writing this plan does not authorize merging, publishing or delivering either target.
- Use the five registered ids, in order: `ai-grammar`, `textkit`, `yt2txt`, `chat2api`, `file-bridge`. Only `free-tts` remains excluded. Dispatch every configuration operation exhaustively; unknown kinds raise `UnknownConfigKindError` even if metadata validation was bypassed.
- Preserve the three LLM formats, equality, split-model transitions and two-argument `write_app_config(meta, config) -> None` behavior, including its single-name `.bak`. Structured loads never auto-create a target. Explicit creation starts a draft and writes only after validation.
- Use ruamel `YAML(typ="rt")`, `preserve_quotes=True`, mapping indent 2, sequence indent 4, offset 2, width 4096. JSON uses `indent=2`, `ensure_ascii=False`, `allow_nan=False`, insertion order and one final LF. Preserve unknown values and relative order of untouched keys; do not serialize Pydantic models over original trees.
- Hashes are raw 32-byte SHA-256 digests. `None` means absent, distinct from an empty-file digest. Reject symlink leaves with `lstat` before resolving parents; preserve lexical venv interpreter paths. Non-writable mode bits forbid saves even under root. Existing modes survive replacement; explicit creation uses 0600.
- Backups use `<name>.<YYYYmmddTHHMMSSffffffZ>.<pid>-<hex6>.bak`, UTC `strftime("%Y%m%dT%H%M%S%fZ")`, `secrets.token_hex(3)`, `O_CREAT | O_EXCL`, collision retry, backup fsync and parent fsync. Sidecars are `<config>.lock`, remain on disk, and are locked in sorted canonical-path order across replace and rollback.
- Render all candidates purely, validate them, then stage exactly those sealed bytes. D7 changes exactly `doc["ai"]["api_base"]`; it never uses mutating `write_app_config` to render. Save has no force-overwrite path and never substitutes a newer hash for an older tree.
- Stages 1–2 always run. Stage 3 uses an adjacent hidden candidate, argv lists with `shell=False`, cwd the resolved application directory, inherited environment, and a 10-second timeout with kill/reap. Only unavailable interpreter/imports degrade validation; other rejection and timeout refuse the save. Never run startup_login or ensure_discovered in validation.
- R-HOST-LOOPBACK accepts exactly `127.0.0.1`, `::1`, or case-insensitive `localhost`, without stripping whitespace. Reject `0.0.0.0`, `::`, padded values, external addresses and `127.0.0.2`. R-HOST-CLASS uses one shared `urls_match`, strips at most ONE terminal slash, normalizes only loopback host spelling, and compares the remaining URL text exactly. Never use `rstrip("/")` for D7.
- The launcher gate NEVER starts the server and NEVER binds a socket. It runs `start.sh --print-listener`, which resolves config with the same `PY` and loader, prints host and port, and exits before any uvicorn import or bind. A launcher without the flag exits non-zero (fail-closed). Pending or failed gates disable only host/port and dependent rewriting; cache once per resolved app directory per MainWindow session. Do not add a sandbox, socket probe, port allocation, process-group signalling, or readiness polling.
- Bind ONE `PY` variable in Target B and use `"$PY"` for version, config read and final exec. Preserve activation precedence, script-directory cwd, fixed uvicorn flags and later CLI overrides. Copy the exact spec §10 script in Task 13.
- New UI text follows spec §9.4 literally. Pass dynamic text through `escape_mnemonic` only at mnemonic-aware sinks; plain labels/details use plain text. Logs and stderr are never interpreted as rich text. Secrets have unchanged flags; reveal alone cannot write anything.
- MainWindow, not a view, computes dirty state. Invalid raw text and duplicate rows remain dirty. Model fetches capture required `request.app_id`; per-view token equality alone cannot route responses. Save/probe workers touch no widgets and emit one terminal result through queued connections.
- A successful save updates baselines from sealed bytes only. Dirty dependent widgets/drafts survive a D7 baseline update. Never restart on validation/transaction failure, never restart dependents implicitly, and never roll back a committed configuration merely because restart fails.
- Tests use synthetic credentials and temporary workspaces; no live configs, settings, supervisor or production listeners are touched. Keep offscreen QPA setup before QApplication construction. Mandatory behavioral socket tests supplement argv inspection. No dependency installation or optional C probe is required.
- Document limits: advisory locks cannot exclude non-cooperating writers after hash check; replacement is not crash-atomic across files and has no recovery journal; save validation does not prove restart/login/discovery/port availability; B reads config twice; externally set `CHAT2API_CONFIG` is not discovered by the editor.
- File map: `config_errors.py` owns typed errors; `structured_models.py` owns records; `structured_schema.py` owns declarative inventories and schemas; `structured_config.py` owns parse/render/commit; `transaction.py` owns filesystem phases; `blast_radius.py` owns URL comparison and dependent snapshots; three service modules own interpreter/validation/probe; `config_jobs.py` owns Qt workers; `ui/structured_editor_model.py` owns pure row/draft state; `structured_config_view.py` owns declarative widgets; `config_dialogs.py` owns dialogs. The small pure editor-model file is the only additional decomposition beyond spec §3 and has no I/O or Qt dependency.
- Dependency schedule: Task 2 installs form inventories needed for raw-area normalization; Task 5 adds validation schemas. Task 7 installs only the probe worker. Task 9 completes commit orchestration and the save worker after validation and pure dependent rendering exist. Modification line ranges below refer to the inspected baseline; use the named symbols after earlier tasks shift line numbers.

## Task 1: Register five configuration kinds and protect legacy dispatch

**Implementer tier:** Advanced

**Files:**

- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/models.py:1-48` and `:74-79`.
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/config_errors.py`.
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/app_registry.py:6-43`.
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/yaml_manager.py:28-43` and `:80-82` (entry guards only).
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/app_detail_view.py:338-345` (required request origin).
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_app_registry.py:15-23`, `/data/home/guest/Development/ai/ai-manager/tests/test_models.py:1-51`, `/data/home/guest/Development/ai/ai-manager/tests/test_model_fetcher.py:23-65`.
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/tests/conftest.py:1-28` (append fixtures and isolation).
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_e2e_integration.py:1-27` (remove live-workspace access now; full view dispatch assertions arrive in Task 12).

**Interfaces:**

- Consumes: existing `AppAIConfig(BaseModel)` fields `api_base: str`, `api_key: str`, `model: str | None`, `is_split_model: bool`, `ocr_model: str | None`, `text_model: str | None`; existing `get_managed_apps(workspace_root: Path) -> dict[str, AppMetadata]`.
- Produces: `ConfigKind = Literal["llm", "chat2api", "file-bridge"]`; `AppMetadata.config_kind: ConfigKind = "llm"` with a before validator; `ModelFetchRequest(token: int, api_base: str, api_key: str, app_id: str)` with strict nonempty required app_id. Response fields stay unchanged.
- Produces: `require_llm(meta: AppMetadata) -> None`; `UnknownConfigKindError(kind: object)` and all concrete error constructors below; `five_app_workspace: Path` pytest fixture and autouse `isolate_manager` fixture.

- [ ] **Step 1: Write registry, request and dispatch tests.** Replace `test_managed_apps` and append the following tests to their named files. Keep the preset and existing normalized-model tests.

```python
# tests/test_app_registry.py
import pytest
from pydantic import ValidationError
from ai_manager.config.models import AppMetadata
from ai_manager.config.config_errors import ConfigError, UnknownConfigKindError
from ai_manager.config.yaml_manager import ensure_config_exists, read_app_config, write_app_config
from ai_manager.config.models import AppAIConfig


def test_managed_apps(tmp_path):
    apps = get_managed_apps(tmp_path)
    assert list(apps) == ["ai-grammar", "textkit", "yt2txt", "chat2api", "file-bridge"]
    assert [a.config_kind for a in apps.values()] == ["llm", "llm", "llm", "chat2api", "file-bridge"]
    assert "free-tts" not in apps
    assert apps["chat2api"].relative_path == tmp_path / "chat2api"
    assert apps["chat2api"].config_file_name == "config.json"
    assert apps["chat2api"].example_config_file_name == "config.example.json"
    assert apps["chat2api"].default_port == 8000
    assert apps["file-bridge"].default_port == 8964
    assert apps["textkit"].supports_split_models


@pytest.mark.parametrize("kind", [None, 1, "LLM", "file_bridge", "unknown"])
def test_bad_kind_fails_closed(tmp_path, kind):
    with pytest.raises(ValidationError, match="Unknown config_kind"):
        AppMetadata(id="x", display_name="x", relative_path=tmp_path, default_port=1, config_kind=kind)


def test_legacy_dispatch_does_not_materialize_structured_examples(five_app_workspace):
    apps = get_managed_apps(five_app_workspace)
    for app_id in ("chat2api", "file-bridge"):
        meta = apps[app_id]
        path = meta.relative_path / meta.config_file_name
        path.unlink()
        for call in (lambda: ensure_config_exists(meta), lambda: read_app_config(meta),
                     lambda: write_app_config(meta, AppAIConfig())):
            with pytest.raises(ConfigError):
                call()
        assert not path.exists()
    bad = apps["ai-grammar"].model_copy(update={"config_kind": "plugin-kind"})
    with pytest.raises(UnknownConfigKindError):
        read_app_config(bad)
```

```python
# append to tests/test_models.py
from pydantic import ValidationError
from ai_manager.config.models import ModelFetchRequest


def test_metadata_default_and_llm_equality(tmp_path):
    assert AppMetadata(id="x", display_name="x", relative_path=tmp_path, default_port=1).config_kind == "llm"
    cfg = AppAIConfig(model="original")
    assert cfg == cfg.model_copy(deep=True)
    assert cfg != cfg.model_copy(update={"model": "changed"})


@pytest.mark.parametrize("origin", [None, "", 7])
def test_fetch_origin_is_required_and_strict(origin):
    with pytest.raises(ValidationError):
        ModelFetchRequest(token=1, api_base="http://localhost", api_key="", app_id=origin)
    with pytest.raises(ValidationError):
        ModelFetchRequest(token=1, api_base="http://localhost", api_key="")
```

- [ ] **Step 2: Run the tests and observe the missing discriminator/error-module failure.**

```bash
PYTHONPATH=src pytest tests/test_app_registry.py tests/test_models.py -q
```

Expected: failure before implementation, mentioning missing config_errors or config_kind/origin behavior.

- [ ] **Step 3: Install the exact metadata/request definitions and errors.** Add `Literal` and `field_validator` to models.py imports; retain every other model definition. Replace AppMetadata and ModelFetchRequest with this code.

```python
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
        if type(value) is not str or value not in ("llm", "chat2api", "file-bridge"):
            raise ValueError(f"Unknown config_kind {value!r}; expected llm, chat2api, or file-bridge.")
        return value


class ModelFetchRequest(BaseModel):
    """Request payload sent to background model fetcher worker."""
    token: int
    api_base: str
    api_key: str
    app_id: str = Field(strict=True, min_length=1)
```

```python
# config/config_errors.py
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ai_manager.config.structured_models import FieldIssue, TransactionReport


class ConfigError(Exception):
    pass


class UnknownConfigKindError(ConfigError, ValueError):
    def __init__(self, kind: object) -> None:
        super().__init__(f"Unknown config_kind {kind!r}; expected llm, chat2api, or file-bridge.")
        self.kind = kind


class ConfigLoadError(ConfigError):
    def __init__(self, path: Path, detail: str, reason: str = "load-error") -> None:
        super().__init__(f"Cannot load configuration {path}: {detail}")
        self.path, self.detail, self.reason = path, detail, reason


class ConfigShapeError(ConfigLoadError):
    pass


class SymlinkConfigError(ConfigLoadError):
    def __init__(self, path: Path) -> None:
        super().__init__(path, "Configuration path is a symlink; editing is disabled.", "symlink")


class ReadOnlyConfigError(ConfigError):
    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(detail)
        self.path, self.detail = path, detail


class MissingExampleError(ConfigLoadError):
    pass


class ConfigValidationError(ConfigError):
    def __init__(self, issues: tuple[FieldIssue, ...]) -> None:
        super().__init__("Configuration has invalid fields; nothing was saved.")
        self.issues = issues


class ServiceValidationError(ConfigError):
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        super().__init__("Service validator rejected the configuration; nothing was saved.")
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class ServiceValidationTimeout(ConfigError):
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        super().__init__("Service validator timed out after 10 seconds; nothing was saved.")
        self.stdout, self.stderr = stdout, stderr


class InterpreterUnavailableError(ConfigError):
    pass


class StaleDocumentError(ConfigError):
    def __init__(self, path: Path, expected_sha256: bytes | None, actual_sha256: bytes | None) -> None:
        super().__init__("Configuration changed on disk; save refused.")
        self.path, self.expected_sha256, self.actual_sha256 = path, expected_sha256, actual_sha256


class TransactionError(ConfigError):
    def __init__(self, report: TransactionReport) -> None:
        super().__init__(report.error or "Configuration transaction failed.")
        self.report = report


def require_llm(meta) -> None:
    if meta.config_kind not in ("llm", "chat2api", "file-bridge"):
        raise UnknownConfigKindError(meta.config_kind)
    if meta.config_kind != "llm":
        raise ConfigError(f"{meta.id} requires its {meta.config_kind} configuration adapter.")
```

- [ ] **Step 4: Register both apps, guard legacy operations and migrate request constructors.** In get_managed_apps, add `config_kind="llm"` to each of the existing three constructors, retain insertion order and fields, and append the following two entries. Replace the registry function's description with `Return the five supervised applications in display order; free-tts remains excluded.` in this task. Import `require_llm` into yaml_manager and make it the first statement after the docstring in `ensure_config_exists`, `read_app_config`, and `write_app_config`.

```python
        "chat2api": AppMetadata(
            id="chat2api", display_name="chat2api", relative_path=workspace_root / "chat2api",
            config_file_name="config.json", example_config_file_name="config.example.json",
            default_port=8000, supports_split_models=False,
            description="Local OpenAI-compatible gateway for web AI providers", config_kind="chat2api",
        ),
        "file-bridge": AppMetadata(
            id="file-bridge", display_name="file-bridge", relative_path=workspace_root / "file-bridge",
            config_file_name="config.yaml", example_config_file_name="config.example.yaml",
            default_port=8964, supports_split_models=False,
            description="Local file bridge for saving text and completing paths", config_kind="file-bridge",
        ),
```

```python
# AppDetailView._on_fetch_clicked: replace only the request construction.
        req = ModelFetchRequest(
            token=self._fetch_token,
            api_base=self._base_url_edit.text().strip(),
            api_key=self._key_edit.text().strip(),
            app_id=self.app_meta.id,
        )

# tests/test_model_fetcher.py: replace the three existing request lines.
# Standard OpenAI test:
    req = ModelFetchRequest(token=1, api_base="http://localhost:3000", api_key="sk-test", app_id="ai-grammar")
# Fallback test:
    req = ModelFetchRequest(token=2, api_base="http://localhost:11434", api_key="", app_id="textkit")
# Unauthorized test:
    req = ModelFetchRequest(token=3, api_base="https://api.openai.com", api_key="sk-bad", app_id="yt2txt")
```

- [ ] **Step 5: Add the temporary five-app corpus and isolate window construction.** Append this code to conftest, keeping its existing QPA setup and mock_tray_available fixture. Isolation never intercepts service-validation/probe functions directly; dedicated boundary tests can still execute them. Task 12 implements `_start_launcher_probes`, which the isolation fixture detects at construction time.

```python
from pathlib import Path
import json
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import UserSettings

CHAT = '{"server":{"host":"127.0.0.1","port":8000,"auth_token_env":null},"models":{"echo-1":{"provider":"echo"}}}\n'
BRIDGE = '# Local save destination\nsave_root: "../storage" # keep relative to config parent\nmax_text_bytes: 1048576\nport: 8964\n'
LLM = {
    "ai-grammar": '''server:
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
''',
    "textkit": '''host: 127.0.0.1
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
''',
    "yt2txt": '''host: "127.0.0.1"
port: 8666
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$CHAT2API_TOKEN"
  model: "original-transcribe"
cache:
  enabled: true
''',
}


@pytest.fixture
def five_app_workspace(tmp_path):
    (tmp_path / "storage").mkdir()
    for app_id, meta in get_managed_apps(tmp_path).items():
        meta.relative_path.mkdir(parents=True)
        text = CHAT if app_id == "chat2api" else BRIDGE if app_id == "file-bridge" else LLM[app_id]
        (meta.relative_path / meta.config_file_name).write_text(text, encoding="utf-8")
        (meta.relative_path / meta.example_config_file_name).write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def isolate_manager(monkeypatch):
    from ai_manager.ui import main_window as mw
    monkeypatch.setattr(mw, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(mw, "save_user_settings", lambda settings: None)
    class IsolatedSupervisor(mw.SupervisorManager):
        def refresh_status(self):
            pass
        def start_supervisor(self):
            pass
        def stop_supervisor(self):
            pass
        def restart_service(self, app_id):
            pass
    monkeypatch.setattr(mw, "SupervisorManager", IsolatedSupervisor)
    if hasattr(mw.MainWindow, "_start_launcher_probes"):
        from ai_manager.config.structured_models import LauncherProbeResult
        def passed(window):
            for app_id, meta in window.apps.items():
                if meta.config_kind == "chat2api":
                    window._on_launcher_probe_finished(app_id, LauncherProbeResult(True))
        monkeypatch.setattr(mw.MainWindow, "_start_launcher_probes", passed)
```

Replace the live end-to-end test now with this independent temporary-config test. Task 12 will extend it to both view types.

```python
# tests/test_e2e_integration.py
import json
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.yaml_manager import read_app_config, _get_yaml_engine


def test_full_workspace_integration(five_app_workspace):
    apps = get_managed_apps(five_app_workspace)
    for meta in apps.values():
        path = meta.relative_path / meta.config_file_name
        if meta.config_kind == "llm":
            cfg = read_app_config(meta)
            assert cfg.api_base == "http://127.0.0.1:8000"
            assert cfg.api_key == "$CHAT2API_TOKEN"
        elif meta.config_kind == "chat2api":
            doc = json.loads(path.read_bytes())
            assert doc["server"]["auth_token_env"] is None
            assert "options" not in doc["models"]["echo-1"]
        elif meta.config_kind == "file-bridge":
            doc = _get_yaml_engine().load(path.read_text())
            assert doc["save_root"] == "../storage"
            assert doc["port"] == 8964
        else:
            raise AssertionError(meta.config_kind)
```

- [ ] **Step 6: Run registry, normalized-model, legacy YAML and fetch tests.**

```bash
PYTHONPATH=src pytest tests/test_app_registry.py tests/test_models.py tests/test_yaml_manager.py tests/test_model_fetcher.py tests/test_e2e_integration.py -q
```

Expected: PASS with no failures; existing HTTP payload, comment and split-transition assertions remain.

- [ ] **Step 7: Commit.**

```bash
git add src/ai_manager/config/models.py src/ai_manager/config/config_errors.py src/ai_manager/config/app_registry.py src/ai_manager/config/yaml_manager.py src/ai_manager/ui/app_detail_view.py tests/conftest.py tests/test_app_registry.py tests/test_models.py tests/test_model_fetcher.py tests/test_e2e_integration.py
git commit -m "feat(config): register structured application kinds and require fetch origins"
```

## Task 2: Load and render addressed structured documents without writes

**Implementer tier:** Advanced

**Files:**

- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_models.py`.
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_schema.py` (form inventories only in this task).
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_config.py` (load, example, parse, mutations, render; commit arrives in Task 9).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_structured_config.py`.

**Interfaces:**

- Consumes: Task 1 `UnknownConfigKindError(kind: object)`, `ConfigLoadError(path: Path, detail: str, reason: str = "load-error")`, `ConfigShapeError` with the same constructor, `SymlinkConfigError(path: Path)`, `MissingExampleError` with the load-error constructor, `ReadOnlyConfigError(path: Path, detail: str)`, `ConfigValidationError(issues: tuple[FieldIssue, ...])`, `StaleDocumentError(path: Path, expected_sha256: bytes | None, actual_sha256: bytes | None)`; existing `_get_yaml_engine() -> ruamel.yaml.YAML`.
- Produces: every record below; `load(kind: StructuredKind, path: Path) -> StructuredDoc`; `load_example(kind: StructuredKind, path: Path, example_path: Path) -> StructuredDoc`; `effective_mutations(doc: StructuredDoc) -> tuple[Mutation, ...]`; `render(kind: StructuredKind, doc: StructuredDoc) -> bytes`.
- Produces shared internal helpers: `_check_kind(kind: object) -> None`, `_snapshot(path: Path) -> tuple[Path, bytes | None, int | None, tuple[str, ...]]`, `_parse_bytes(kind: StructuredKind, path: Path, raw: bytes) -> tuple[MutableMapping[str, Any], tuple[str, ...]]`, `_candidate(doc: StructuredDoc) -> MutableMapping[str, Any]`, `_json_object(text: str) -> dict[str, Any]`. They perform no writes. Task 3 reuses snapshot safety; Task 9 reuses byte-buffer parsing.
- Produces: `FieldSpec`, `OptionSpec`, `SERVER_FIELDS`, `FILE_BRIDGE_FIELDS`, `COMMON_LOGIN_OPTIONS`, `PROVIDER_OPTIONS`, `SECRET_OPTION_KEYS` with exact values below. Inventory construction inserts no configuration defaults.

- [ ] **Step 1: Write load/fidelity and safety tests.** Use the following entire new test file. Tests compare subtree values/order in addition to the prescribed normalized bytes.

```python
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
```

- [ ] **Step 2: Run the new tests and confirm the missing structured module fails.**

```bash
PYTHONPATH=src pytest tests/test_structured_config.py -q
```

- [ ] **Step 3: Create the records exactly as follows.**

```python
# config/structured_models.py
from __future__ import annotations
import hashlib
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from ai_manager.config.models import AppAIConfig, AppMetadata

StructuredKind = Literal["chat2api", "file-bridge"]
KeyPath = tuple[str, ...]
ReadOnlyReason = Literal["symlink", "non-writable", "yaml-anchors-aliases", "non-dict-root", "load-error", "missing-config"]
FinalFileState = Literal["new", "restored", "unknown"]
TransactionPhase = Literal["prepare", "backups", "stage", "replace_all", "rollback", "complete"]


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
        if type(self.address) is not tuple or not self.address or any(type(k) is not str for k in self.address):
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

- [ ] **Step 4: Create the declarative form inventories.** Task 5 appends validation classes to this module; raw normalization can already consume these definitions today.

```python
# config/structured_schema.py
from __future__ import annotations
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
    FieldSpec("max_text_bytes", "Maximum text bytes", "integer", 0, 104_857_600, "0 = no limit"),
    FieldSpec("port", "Port", "integer", 1, 65535),
)
COMMON_LOGIN_OPTIONS = (
    OptionSpec("account", "secret"), OptionSpec("password", "secret"),
    OptionSpec("interactive_login", "boolean"), OptionSpec("browser_profile_dir", "text"),
)
PROVIDER_OPTIONS = {
    "echo": (OptionSpec("prefix", "text"),),
    "gemini_webapi": COMMON_LOGIN_OPTIONS + (
        OptionSpec("secure_1psid_env", "text"), OptionSpec("secure_1psidts_env", "text"),
        OptionSpec("timeout", "integer"), OptionSpec("gemini_model", "text"),
    ),
    "copilot_webapi": COMMON_LOGIN_OPTIONS + (
        OptionSpec("access_token", "secret"), OptionSpec("access_token_env", "text"),
        OptionSpec("timezone", "text"), OptionSpec("chat_timeout", "integer"), OptionSpec("copilot_mode", "text"),
    ),
    "browser": (
        OptionSpec("account", "secret"), OptionSpec("password", "secret"), OptionSpec("headless", "boolean"),
        OptionSpec("user_data_dir", "text"), OptionSpec("timeout", "integer"),
        OptionSpec("response_appear_timeout", "integer"), OptionSpec("gemini_model", "text"),
    ),
}
SECRET_OPTION_KEYS = frozenset({"account", "password", "access_token"})
```

- [ ] **Step 5: Implement parsing and filesystem snapshots.** No lock, temp, example copy, backup or replacement belongs in these functions.

```python
# config/structured_config.py
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
            return resolved, None, None, ()
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
        return StructuredDoc(kind, requested, resolved, {}, b"", None, False, None, ("missing-config",))
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
    return replace(target, doc=copy.deepcopy(example.doc), read_only_reasons=tuple(r for r in example.read_only_reasons if r == "yaml-anchors-aliases"), create_requested=True)
```

- [ ] **Step 6: Implement pure addressed rendering and raw-option normalization.** Append this code. Parent/child overlap is rejected; edited raw areas become per-key mutations without changing convenience/secret keys.

```python

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
```

- [ ] **Step 7: Run load/render and legacy tests.**

```bash
PYTHONPATH=src pytest tests/test_structured_config.py tests/test_yaml_manager.py tests/test_app_registry.py -q
```

Expected: PASS with no failures and no target writes from load/render.

- [ ] **Step 8: Commit.**

```bash
git add src/ai_manager/config/structured_models.py src/ai_manager/config/structured_schema.py src/ai_manager/config/structured_config.py tests/test_structured_config.py
git commit -m "feat(config): load and render addressed JSON and round-trip YAML drafts"
```

## Task 3: Lock snapshots, refuse stale writes and create exclusive backups

**Implementer tier:** Advanced

**Files:**

- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/transaction.py` (prepare/backups and resource ownership).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_transaction.py`.

**Interfaces:**

- Consumes: Task 2 `_snapshot(path: Path) -> tuple[Path, bytes | None, int | None, tuple[str, ...]]`, which rejects symlink/non-regular leaves and returns parent-resolved paths, exact bytes/mode, and read-only reasons; `TransactionReport(phase, files={}, backups={}, replaced=(), restore_failures={}, error=None, committed=False)` with states new/restored/unknown.
- Consumes: Task 1 `StaleDocumentError(path: Path, expected_sha256: bytes | None, actual_sha256: bytes | None)`, `ReadOnlyConfigError(path: Path, detail: str)`, `ConfigLoadError(path: Path, detail: str, reason: str = "load-error")`, `SymlinkConfigError(path: Path)`, `TransactionError(report: TransactionReport)`.
- Produces: `Transaction.__init__() -> None`, `__enter__() -> Transaction`, `__exit__(exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> bool`, `prepare(paths: list[Path], expected: dict[Path, bytes | None]) -> None`, `backups() -> None`, `original_mode(path: Path) -> int`. The last accessor returns captured mode or 0600, allowing the coordinator to build a sealed baseline without rereading disk.
- Produces internal `_paths: tuple[Path, ...]`, `_original: dict[Path, tuple[bytes | None, int | None]]`, `_backups: dict[Path, Path]`, `_temps: set[Path]`, `_state: str`, `_require(state: str) -> None`, `_fsync_dir(parent: Path) -> None`, `_verify_original(path: Path) -> bool`, `_report(phase, error: str) -> TransactionReport`. Task 4 extends this same class; no stage/replace stub is added now.

- [ ] **Step 1: Write stale, exclusive-backup, mode and sidecar tests.**

```python
# tests/test_transaction.py
import fcntl
import hashlib
import multiprocessing
import os
from pathlib import Path
import stat
import time
import pytest
from ai_manager.config import transaction as tm
from ai_manager.config.config_errors import StaleDocumentError, SymlinkConfigError, TransactionError


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest() if path.exists() else None


def files(tmp_path, count=2):
    paths = [tmp_path / f"{i}.yaml" for i in range(count)]
    for index, path in enumerate(paths):
        path.write_bytes(f"old-{index}\n".encode())
        path.chmod(0o640)
    return paths


@pytest.mark.parametrize("member", [0, 1])
def test_stale_member_leaves_all_bytes_and_no_artifacts(tmp_path, member):
    paths = files(tmp_path)
    expected = {p: digest(p) for p in paths}
    paths[member].write_bytes(b"hand edit\n")
    before = {p: p.read_bytes() for p in paths}
    with pytest.raises(StaleDocumentError) as err:
        with tm.Transaction() as tx:
            tx.prepare(list(reversed(paths)), expected)
    assert err.value.expected_sha256 == expected[paths[member]]
    assert err.value.actual_sha256 == digest(paths[member])
    assert {p: p.read_bytes() for p in paths} == before
    assert not list(tmp_path.glob("*.bak")) and not list(tmp_path.glob(".*.tmp"))
    for p in paths:
        with open(str(p) + ".lock", "r+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("race", ["deleted", "created", "empty"])
def test_none_digest_semantics(tmp_path, race):
    p = tmp_path / "config.json"
    if race == "deleted":
        p.write_bytes(b"old")
        expected = digest(p)
        p.unlink()
    else:
        expected = None
        p.write_bytes(b"" if race == "empty" else b"appeared")
    with pytest.raises(StaleDocumentError):
        with tm.Transaction() as tx:
            tx.prepare([p], {p: expected})
    assert p.exists() == (race != "deleted")


def test_symlink_swapped_after_load_is_rejected(tmp_path):
    p = files(tmp_path, 1)[0]
    old_hash = digest(p)
    target = tmp_path / "referent"
    target.write_bytes(b"untouched")
    p.unlink()
    p.symlink_to(target)
    with pytest.raises(SymlinkConfigError):
        with tm.Transaction() as tx:
            tx.prepare([p], {p: old_hash})
    assert p.is_symlink() and target.read_bytes() == b"untouched"


def test_backups_exclusive_collision_and_order(tmp_path, monkeypatch):
    paths = files(tmp_path)
    class Clock:
        @classmethod
        def now(cls, tz):
            from datetime import datetime, timezone
            return datetime(2026, 10, 17, 16, 7, 34, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(tm, "datetime", Clock)
    monkeypatch.setattr(tm.os, "getpid", lambda: 4321)
    nonces = iter(["a1b2c3", "a1b2c3", "d4e5f6", "a1b2c3", "d4e5f6", "abcdef"])
    monkeypatch.setattr(tm.secrets, "token_hex", lambda n: next(nonces))
    flags_seen, locks_seen = [], []
    original_open, original_flock = tm.os.open, tm.fcntl.flock
    def opened(path, flags, mode=0o777):
        flags_seen.append((str(path), flags))
        return original_open(path, flags, mode)
    def locked(fd, op):
        if op == fcntl.LOCK_EX:
            locks_seen.append(Path(os.readlink(f"/proc/self/fd/{fd}")))
        return original_flock(fd, op)
    monkeypatch.setattr(tm.os, "open", opened)
    monkeypatch.setattr(tm.fcntl, "flock", locked)
    with tm.Transaction() as tx:
        tx.prepare(list(reversed(paths)), {p: digest(p) for p in paths})
        tx.backups()
        first = tx._backups.copy()
        assert list(tx._paths) == sorted(paths, key=str)
        assert all(stat.S_IMODE(b.lstat().st_mode) == 0o640 for b in first.values())
    paths[0].write_bytes(b"next")
    with tm.Transaction() as tx:
        tx.prepare([paths[0]], {paths[0]: digest(paths[0])})
        tx.backups()
        second = tx._backups[paths[0]]
    assert second != first[paths[0]]
    assert first[paths[0]].read_bytes() == b"old-0\n" and second.read_bytes() == b"next"
    assert locks_seen[:2] == [Path(str(p) + ".lock") for p in sorted(paths, key=str)]
    assert all(flags & os.O_EXCL for name, flags in flags_seen if name.endswith(".bak"))
    assert all(flags & os.O_NOFOLLOW for name, flags in flags_seen if name.endswith(".lock"))
    assert first[paths[0]].name == "0.yaml.20261017T160734123456Z.4321-a1b2c3.bak"


def test_backup_failure_keeps_targets_and_completed_backup(tmp_path, monkeypatch):
    paths = files(tmp_path)
    old = {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths}
    original = tm.os.open
    def fail(path, flags, mode=0o777):
        if str(path).startswith(str(paths[1]) + ".") and str(path).endswith(".bak"):
            raise OSError("fixture backup failure")
        return original(path, flags, mode)
    monkeypatch.setattr(tm.os, "open", fail)
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare(paths, {p: digest(p) for p in paths})
            tx.backups()
    assert err.value.report.phase == "backups"
    assert set(err.value.report.files.values()) == {"restored"}
    assert len(err.value.report.backups) == 1
    assert {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths} == old


def test_sidecar_identity_survives_target_inode_replace(tmp_path):
    p = files(tmp_path, 1)[0]
    ctx = multiprocessing.get_context("fork")
    ready, acquired = ctx.Event(), ctx.Event()
    output = ctx.Queue()
    def reader():
        with open(str(p) + ".lock", "a+b") as lock:
            ready.set()
            fcntl.flock(lock, fcntl.LOCK_EX)
            output.put(p.read_bytes())
            acquired.set()
    child = None
    try:
        with tm.Transaction() as tx:
            tx.prepare([p], {p: digest(p)})
            child = ctx.Process(target=reader)
            child.start()
            assert ready.wait(2) and not acquired.wait(0.1)
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"new inode")
            os.replace(replacement, p)
            assert not acquired.wait(0.1)
        assert acquired.wait(2)
        assert output.get(timeout=2) == b"new inode"
        child.join(2)
        assert child.exitcode == 0 and Path(str(p) + ".lock").exists()
    finally:
        if child is not None and child.is_alive():
            child.terminate()
            child.join(2)
```

- [ ] **Step 2: Run the tests and see the missing transaction implementation fail.**

```bash
PYTHONPATH=src pytest tests/test_transaction.py -q
```

- [ ] **Step 3: Implement context ownership and prepare.**

```python
# config/transaction.py
from __future__ import annotations
import fcntl
import hashlib
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from ai_manager.config.config_errors import (
    ConfigLoadError, ReadOnlyConfigError, StaleDocumentError, SymlinkConfigError, TransactionError,
)
from ai_manager.config.structured_config import _snapshot
from ai_manager.config.structured_models import TransactionReport


def _canonical(path: Path) -> Path:
    requested = Path(os.path.abspath(path))
    try:
        for candidate in (requested, requested.parent.resolve() / requested.name):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise SymlinkConfigError(requested)
            if not stat.S_ISREG(info.st_mode):
                raise ConfigLoadError(requested, "Configuration path must be a regular file.")
        return requested.parent.resolve() / requested.name
    except (OSError, RuntimeError) as exc:
        raise ConfigLoadError(requested, str(exc)) from exc


class Transaction:
    def __init__(self) -> None:
        self._state = "initial"
        self._entered = False
        self._paths: tuple[Path, ...] = ()
        self._original: dict[Path, tuple[bytes | None, int | None]] = {}
        self._backups: dict[Path, Path] = {}
        self._locks: list[int] = []
        self._temps: set[Path] = set()

    def __enter__(self) -> Transaction:
        if self._entered or self._state != "initial":
            raise ValueError("A transaction context may be entered once.")
        self._entered = True
        return self

    def _release(self) -> None:
        while self._locks:
            fd = self._locks.pop()
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> bool:
        try:
            for path in tuple(self._temps):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # Only unconsumed private temps; no target-state assertion depends on deletion.
                    pass
        finally:
            self._release()
            self._entered = False
            self._state = "closed"
        return False

    def _require(self, state: str) -> None:
        if not self._entered or self._state != state:
            raise ValueError(f"Expected transaction state {state}; got {self._state}.")

    def _fsync_dir(self, parent: Path) -> None:
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def prepare(self, paths: list[Path], expected: dict[Path, bytes | None]) -> None:
        self._require("initial")
        if not paths or len(paths) != len(set(paths)) or set(paths) != set(expected):
            raise ValueError("Paths and expected hashes must have the same nonempty unique key set.")
        if any(value is not None and (type(value) is not bytes or len(value) != 32) for value in expected.values()):
            raise ValueError("Expected digests must be 32-byte SHA-256 values or None.")
        canonical = {p: _canonical(p) for p in paths}
        if len(set(canonical.values())) != len(paths):
            raise ValueError("Duplicate canonical configuration paths.")
        hashes = {canonical[p]: expected[p] for p in paths}
        self._paths = tuple(sorted(canonical.values(), key=str))
        try:
            for path in self._paths:
                lock = path.with_name(path.name + ".lock")
                fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
                self._locks.append(fd)
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX)
                        break
                    except InterruptedError:
                        continue
            for path in self._paths:
                resolved, raw, mode, reasons = _snapshot(path)
                if resolved != path:
                    raise ConfigLoadError(path, "Configuration parent changed during prepare.")
                if reasons or not os.access(path.parent, os.W_OK | os.X_OK):
                    raise ReadOnlyConfigError(path, "Configuration is not writable; editing is disabled.")
                actual = None if raw is None else hashlib.sha256(raw).digest()
                if actual != hashes[path]:
                    raise StaleDocumentError(path, hashes[path], actual)
                self._original[path] = (raw, mode)
            self._state = "prepared"
        except BaseException:
            self._release()
            self._state = "failed"
            raise

    def original_mode(self, path: Path) -> int:
        if path not in self._original:
            raise ValueError("Path was not prepared.")
        return self._original[path][1] if self._original[path][1] is not None else 0o600

    def _verify_original(self, path: Path) -> bool:
        try:
            resolved, raw, mode, reasons = _snapshot(path)
            return resolved == path and (raw, mode) == self._original[path]
        except Exception:
            return False

    def _report(self, phase, error: str) -> TransactionReport:
        return TransactionReport(phase, files={p: "restored" if self._verify_original(p) else "unknown" for p in self._paths}, backups=self._backups.copy(), error=error)

    def backups(self) -> None:
        self._require("prepared")
        active: Path | None = None
        try:
            for path in self._paths:
                raw, mode = self._original[path]
                if raw is None:
                    continue
                while True:
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    backup = path.with_name(f"{path.name}.{timestamp}.{os.getpid()}-{secrets.token_hex(3)}.bak")
                    try:
                        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
                        break
                    except FileExistsError:
                        continue
                active = backup
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fchmod(stream.fileno(), mode)
                    os.fsync(stream.fileno())
                self._fsync_dir(path.parent)
                self._backups[path] = backup
                active = None
            self._state = "backed-up"
        except OSError as exc:
            if active is not None:
                try:
                    active.unlink(missing_ok=True)
                except OSError:
                    pass
            self._state = "failed"
            raise TransactionError(self._report("backups", f"Could not create all backups; no configuration files were changed. {exc}")) from exc
```

- [ ] **Step 4: Run stale, lock and backup tests plus loader safety tests.**

```bash
PYTHONPATH=src pytest tests/test_transaction.py tests/test_structured_config.py -q
```

Expected: PASS with no failures. In the collision test the frozen first backup is never truncated, and another process acquires the same sidecar only after context exit.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/config/transaction.py tests/test_transaction.py
git commit -m "feat(config): lock snapshots and create exclusive durable backups"
```

## Task 4: Stage sealed bytes and recover handled replacement failures

**Implementer tier:** Advanced

**Files:**

- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/transaction.py:1-170` (Task 3 class, imports and appended phase methods).
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_transaction.py:1-190` (append phase/fault tests).

**Interfaces:**

- Consumes: Task 3 `Transaction.prepare(paths: list[Path], expected: dict[Path, bytes | None]) -> None`, `backups() -> None`, `original_mode(path: Path) -> int`, `_require(state: str) -> None`, `_fsync_dir(parent: Path) -> None`, `_verify_original(path: Path) -> bool`, `_report(phase, error: str) -> TransactionReport`; internal `_paths: tuple[Path, ...]`, `_original: dict[Path, tuple[bytes | None, int | None]]`, `_backups: dict[Path, Path]`, `_temps: set[Path]`, `_state: str`.
- Consumes: Task 2 `TransactionReport` fields `phase`, `files: dict[Path, Literal["new", "restored", "unknown"]]`, `backups`, `replaced`, `restore_failures`, `error`, `committed`; Task 1 `TransactionError(report: TransactionReport)`.
- Produces: `Transaction.stage(rendered: dict[Path, bytes]) -> None`, `replace_all() -> TransactionReport`, `rollback(report: TransactionReport) -> TransactionReport`. Stage never invokes any renderer or mutating writer. All terminal reports cover every participating path.

- [ ] **Step 1: Write successful and faulted phase tests.** Append to test_transaction.py.

```python
@pytest.mark.parametrize("dependent_count", [0, 1, 3])
def test_sealed_stage_and_sorted_replace(tmp_path, dependent_count, monkeypatch):
    paths = files(tmp_path, dependent_count + 1)
    old = {p: p.read_bytes() for p in paths}
    new = {p: b"new-" + p.name.encode() for p in paths}
    replacements = []
    original = tm.os.replace
    def spy(src, dst):
        replacements.append(Path(dst))
        return original(src, dst)
    monkeypatch.setattr(tm.os, "replace", spy)
    with tm.Transaction() as tx:
        tx.prepare(list(reversed(paths)), {p: digest(p) for p in paths})
        tx.backups()
        tx.stage(new)
        assert {p: p.read_bytes() for p in paths} == old
        assert all(t.parent == tmp_path and t.name.startswith(".") for t in tx._temps)
        report = tx.replace_all()
    assert replacements == sorted(paths, key=str)
    assert report.committed and report.phase == "complete"
    assert report.files == {p: "new" for p in paths}
    assert {p: p.read_bytes() for p in paths} == new
    assert all(stat.S_IMODE(p.lstat().st_mode) == 0o640 for p in paths)
    assert all(b.read_bytes() == old[p] for p, b in report.backups.items())
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("phase", ["stage", "replace", "parent-fsync", "restore"])
def test_fault_reports_real_bytes_modes_and_all_paths(tmp_path, monkeypatch, phase):
    paths = files(tmp_path, 3)
    old = {p: (p.read_bytes(), stat.S_IMODE(p.lstat().st_mode)) for p in paths}
    original_replace = tm.os.replace
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare(paths, {p: digest(p) for p in paths})
            tx.backups()
            replaced, restore_order = [], []
            original_temp, original_sync = tx._write_temp, tx._fsync_dir
            def temporary(path, raw, mode, label):
                if phase == "stage" and path == paths[1] and label == "stage":
                    raise OSError("fixture stage failure")
                return original_temp(path, raw, mode, label)
            def replace_file(src, dst):
                label = "restore" if "restore" in str(src) else "stage"
                dst = Path(dst)
                if label == "stage" and dst == paths[2] and phase in ("replace", "restore"):
                    raise OSError("fixture replace failure")
                if label == "restore":
                    restore_order.append(dst)
                    if phase == "restore" and dst == paths[1]:
                        raise OSError("fixture restore failure")
                result = original_replace(src, dst)
                if label == "stage":
                    replaced.append(dst)
                return result
            sync_failed = False
            def sync(parent):
                nonlocal sync_failed
                if phase == "parent-fsync" and replaced and not sync_failed:
                    sync_failed = True
                    raise OSError("fixture directory fsync failure")
                return original_sync(parent)
            monkeypatch.setattr(tx, "_write_temp", temporary)
            monkeypatch.setattr(tx, "_fsync_dir", sync)
            monkeypatch.setattr(tm.os, "replace", replace_file)
            tx.stage({p: b"new" for p in paths})
            tx.replace_all()
    report = err.value.report
    assert not report.committed and set(report.files) == set(paths)
    if phase == "stage":
        assert replaced == [] and report.phase == "stage"
    else:
        assert report.phase == "rollback"
        assert restore_order == list(reversed(replaced))
        if phase == "parent-fsync":
            assert replaced == [paths[0]]
    if phase == "restore":
        assert report.files[paths[1]] == "unknown"
        assert paths[1] in report.restore_failures
        assert p_original(paths[0]) == old[paths[0]] and p_original(paths[2]) == old[paths[2]]
    else:
        assert report.files == {p: "restored" for p in paths}
        assert {p: p_original(p) for p in paths} == old
    assert not list(tmp_path.glob(".*.tmp"))
    assert all(b.exists() for b in report.backups.values())


def p_original(path):
    return path.read_bytes(), stat.S_IMODE(path.lstat().st_mode)


def test_explicit_create_mode_and_rollback_to_absence(tmp_path, monkeypatch):
    created = tmp_path / "0.json"
    other = files(tmp_path, 1)[0]
    old = other.read_bytes()
    original = tm.os.replace
    def fail(src, dst):
        if Path(dst) == other and "stage" in str(src):
            raise OSError("fixture later replace failure")
        return original(src, dst)
    monkeypatch.setattr(tm.os, "replace", fail)
    with pytest.raises(TransactionError) as err:
        with tm.Transaction() as tx:
            tx.prepare([other, created], {created: None, other: digest(other)})
            tx.backups()
            tx.stage({created: b"{}\n", other: b"new"})
            assert tx.original_mode(created) == 0o600
            tx.replace_all()
    assert not created.exists() and other.read_bytes() == old
    assert err.value.report.files[created] == "restored"
    assert created not in err.value.report.backups
    monkeypatch.setattr(tm.os, "replace", original)
    with tm.Transaction() as tx:
        tx.prepare([created], {created: None})
        tx.backups()
        tx.stage({created: b"{}\n"})
        assert tx.replace_all().committed
    assert stat.S_IMODE(created.lstat().st_mode) == 0o600


def test_invalid_phase_and_key_sets_write_nothing(tmp_path):
    p = files(tmp_path, 1)[0]
    with tm.Transaction() as tx:
        with pytest.raises(ValueError):
            tx.stage({p: b"bad"})
        with pytest.raises(ValueError):
            tx.prepare([p], {})
        tx.prepare([p], {p: digest(p)})
        with pytest.raises(ValueError):
            tx.prepare([p], {p: digest(p)})
        tx.backups()
        with pytest.raises(ValueError):
            tx.stage({})
        assert p.read_bytes() == b"old-0\n"


def test_two_processes_reverse_input_order_finish_or_refuse_stale(tmp_path):
    paths = files(tmp_path)
    ctx = multiprocessing.get_context("fork")
    start, out = ctx.Event(), ctx.Queue()
    expected = {p: digest(p) for p in paths}
    def writer(order, value):
        start.wait(2)
        try:
            with tm.Transaction() as tx:
                tx.prepare(order, expected)
                tx.backups()
                tx.stage({p: value for p in order})
                tx.replace_all()
            out.put("saved")
        except StaleDocumentError:
            out.put("stale")
    children = [ctx.Process(target=writer, args=(paths, b"first")), ctx.Process(target=writer, args=(list(reversed(paths)), b"second"))]
    try:
        for child in children:
            child.start()
        start.set()
        for child in children:
            child.join(4)
            assert child.exitcode == 0
        assert sorted([out.get(timeout=1), out.get(timeout=1)]) == ["saved", "stale"]
        assert len({p.read_bytes() for p in paths}) == 1
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(2)
```

- [ ] **Step 2: Run the added tests and confirm missing stage/replace methods fail.**

```bash
PYTHONPATH=src pytest tests/test_transaction.py -q
```

- [ ] **Step 3: Add staging and replace/rollback methods.** Add `import tempfile` to transaction.py and append these methods inside Transaction.

```python
    def _write_temp(self, path: Path, raw: bytes, mode: int, label: str) -> Path:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.ai-manager-{label}-", suffix=".tmp", dir=path.parent)
        temp = Path(name)
        self._temps.add(temp)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
            return temp
        except BaseException:
            temp.unlink(missing_ok=True)
            self._temps.discard(temp)
            raise

    def stage(self, rendered: dict[Path, bytes]) -> None:
        self._require("backed-up")
        if set(rendered) != set(self._paths) or any(type(v) is not bytes for v in rendered.values()):
            raise ValueError("Stage requires exactly the prepared paths and sealed byte values.")
        self._staged: dict[Path, Path] = {}
        try:
            for path in self._paths:
                self._staged[path] = self._write_temp(path, rendered[path], self.original_mode(path), "stage")
            self._state = "staged"
        except OSError as exc:
            self._state = "failed"
            raise TransactionError(self._report("stage", f"Could not stage configuration files; no configuration files were changed. {exc}")) from exc

    def replace_all(self) -> TransactionReport:
        self._require("staged")
        self._state = "replacing"
        replaced: list[Path] = []
        report = TransactionReport("replace_all", backups=self._backups.copy())
        path = self._paths[0]
        try:
            for path in self._paths:
                os.replace(self._staged[path], path)
                replaced.append(path)
                report.replaced = tuple(replaced)
                self._temps.discard(self._staged[path])
                self._fsync_dir(path.parent)
                report.files[path] = "new"
            report.phase, report.committed = "complete", True
            self._state = "complete"
            return report
        except OSError as exc:
            report.error = f"Configuration save failed at {path}: {exc}"
            for untouched in self._paths:
                if untouched not in replaced:
                    report.files[untouched] = "restored" if self._verify_original(untouched) else "unknown"
            recovered = self.rollback(report)
            raise TransactionError(recovered) from exc

    def rollback(self, report: TransactionReport) -> TransactionReport:
        self._require("replacing")
        self._state = "rolling-back"
        report.phase, report.committed = "rollback", False
        for path in reversed(report.replaced):
            try:
                old, mode = self._original[path]
                if old is None:
                    path.unlink()
                    self._fsync_dir(path.parent)
                else:
                    backup = self._backups[path]
                    restored = backup.read_bytes()
                    if restored != old:
                        raise OSError("Backup no longer matches the prepared bytes.")
                    temp = self._write_temp(path, restored, mode, "restore")
                    os.replace(temp, path)
                    self._temps.discard(temp)
                    self._fsync_dir(path.parent)
                if not self._verify_original(path):
                    raise OSError("Restoration could not be verified.")
                report.files[path] = "restored"
            except Exception as exc:
                report.files[path] = "unknown"
                report.restore_failures[path] = str(exc)
        for path in self._paths:
            report.files.setdefault(path, "restored" if self._verify_original(path) else "unknown")
        self._state = "failed"
        return report
```

- [ ] **Step 4: Run every transaction test and verify actual disk bytes, modes and reports.**

```bash
PYTHONPATH=src pytest tests/test_transaction.py tests/test_structured_config.py -q
```

Expected: PASS with no failures, including backup/staging failures with zero target replacements, a post-replace fsync failure included in rollback, reverse recovery, and continued recovery after one restore fails.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/config/transaction.py tests/test_transaction.py
git commit -m "feat(config): stage sealed bytes and report recoverable multi-file saves"
```

## Task 5: Validate only written scalars and enforce both service schemas

**Implementer tier:** Standard

**Files:**

- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_schema.py:1-74` (imports, append schemas and public validation functions).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_structured_validation.py`.

**Interfaces:**

- Consumes: Task 2 `Mutation(address: tuple[str, ...], operation: Literal["set", "delete"], value: Any = None)` and `FieldIssue(address: tuple[str, ...], message: str)`; Task 1 `ConfigValidationError(issues: tuple[FieldIssue, ...])` and `UnknownConfigKindError(kind: object)`.
- Produces: `Port`, `TextLimit`, `ProviderName`, `ENV_NAME_RE`, `Chat2ApiServerSchema`, `Chat2ApiRouteSchema`, `Chat2ApiSchema`, `FileBridgeSchema` with the exact spec §2.3 fields/validators copied below.
- Produces: `validate_written_scalars(mutations: tuple[Mutation, ...]) -> None`; `validate_in_process(kind: StructuredKind, candidate: Mapping[str, Any], *, config_path: Path, app_dir: Path) -> None`. Both return None or raise ConfigValidationError with literal tuple addresses. Unknown kinds raise UnknownConfigKindError. The input tree is never modified or replaced with schema output.

- [ ] **Step 1: Write all scalar, shape, path and written-value tests.**

```python
# tests/test_structured_validation.py
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
    ss.validate_in_process(kind, doc, config_path=app_dir / ("config.json" if kind == "chat2api" else "config.yaml"), app_dir=app_dir)


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
            expected = "Host must be a non-empty string." if server[key] == "" else "Host must be a loopback address (127.0.0.1, localhost, or ::1). Binding a wildcard or external interface is not supported for this local service."
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
```

- [ ] **Step 2: Run the schema tests and confirm the absent validation functions fail.**

```bash
PYTHONPATH=src pytest tests/test_structured_validation.py -q
```

- [ ] **Step 3: Append the normative validation schemas.** Merge these imports at the top of structured_schema.py; retain the existing inventories.

```python
import copy
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError, ValidationInfo, field_validator, model_validator
from ai_manager.config.config_errors import ConfigValidationError, UnknownConfigKindError
from ai_manager.config.structured_models import FieldIssue, Mutation, StructuredKind

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
        raise ValueError("Host must be a loopback address (127.0.0.1, localhost, or ::1). Binding a wildcard or external interface is not supported for this local service.")

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

- [ ] **Step 4: Add written-only recursion and stable issue translation.**

```python
CONTROL_MESSAGE = "This value must not contain newline, carriage return, or NUL characters."


def validate_written_scalars(mutations: tuple[Mutation, ...]) -> None:
    issues = []
    def string(value, address):
        if isinstance(value, str) and any(c in value for c in ("\n", "\r", "\0")):
            issues.append(FieldIssue(address, CONTROL_MESSAGE))
    def visit(value, address):
        if isinstance(value, Mapping):
            for key, child in value.items():
                string(key, address + (str(key),))
                visit(child, address + (str(key),))
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, address + (str(index),))
        else:
            string(value, address)
    for mutation in mutations:
        if mutation.operation == "set":
            string(mutation.address[-1], mutation.address)
            visit(mutation.value, mutation.address)
    if issues:
        raise ConfigValidationError(tuple(issues))


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return copy.deepcopy(value)


def _issue(kind, error) -> FieldIssue:
    address = tuple(str(key) for key in error["loc"])
    raw = error["msg"]
    message = raw.removeprefix("Value error, ")
    key = address[-1] if address else "save_root"
    if key == "host" and error["type"] != "value_error":
        message = "Host must be a non-empty string."
    elif key == "port":
        message = "Port must be an integer from 1 to 65535."
    elif key == "auth_token_env":
        message = "Auth token environment variable must be null or a valid environment variable name."
    elif key == "provider":
        message = "Provider must be echo, gemini_webapi, copilot_webapi, or browser."
    elif key == "max_text_bytes":
        message = "Maximum text bytes must be an integer from 0 to 104857600."
    elif kind == "file-bridge" and error["type"] == "extra_forbidden":
        message = f"Unknown file-bridge configuration key: {key}"
    elif key == "save_root" and error["type"] != "value_error":
        message = "Save root must not be empty or whitespace-only."
    if kind == "file-bridge" and not address:
        address = ("save_root",)
    return FieldIssue(address, message)


def validate_in_process(kind: StructuredKind, candidate: Mapping[str, Any], *, config_path: Path, app_dir: Path) -> None:
    if kind not in ("chat2api", "file-bridge"):
        raise UnknownConfigKindError(kind)
    try:
        plain = _plain(candidate)
        if kind == "chat2api":
            Chat2ApiSchema.model_validate(plain)
        else:
            FileBridgeSchema.model_validate(plain, context={"config_path": config_path, "app_dir": app_dir})
    except ValidationError as exc:
        raise ConfigValidationError(tuple(_issue(kind, error) for error in exc.errors(include_input=False))) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        address = ("save_root",) if kind == "file-bridge" else ()
        raise ConfigValidationError((FieldIssue(address, str(exc)),)) from exc
```

- [ ] **Step 5: Run validation and structured-render tests.**

```bash
PYTHONPATH=src pytest tests/test_structured_validation.py tests/test_structured_config.py -q
```

Expected: PASS with the eight-valid/fifteen-invalid chat server partition, no insertion of absent fields, and no service imports.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/config/structured_schema.py tests/test_structured_validation.py
git commit -m "feat(config): validate written values and strict local-service schemas"
```

## Task 6: Resolve the launch interpreter and execute bounded service validation

**Implementer tier:** Advanced

**Files:**

- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/app_interpreter.py`.
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/service_validation.py`.
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_validator_orchestration.py`.

**Interfaces:**

- Consumes: Task 2 `StructuredKind = Literal["chat2api", "file-bridge"]`, `ValidationResult(scope: Literal["service", "manager-only"], notice: str, detail: str = "")`; Task 1 `InterpreterUnavailableError`, `ServiceValidationError(returncode: int, stdout: str, stderr: str)`, `ServiceValidationTimeout(stdout: str = "", stderr: str = "")`, `ConfigError`, `UnknownConfigKindError(kind: object)`.
- Produces: `resolve_app_interpreter(app_dir: Path) -> Path`, `verify_app_interpreter(kind: StructuredKind, app_dir: Path, interpreter: Path) -> None`; `validate_candidate(kind: StructuredKind, target_path: Path, app_dir: Path, rendered: bytes) -> ValidationResult`; exact constant programs `CHAT2API_VALIDATE_PROGRAM` and `FILE_BRIDGE_VALIDATE_PROGRAM`. Stage 3 does not perform or replace stages 1–2.

- [ ] **Step 1: Write the fake-interpreter harness and selection tests.**

```python
# tests/test_validator_orchestration.py
import json
import os
from pathlib import Path
import sys
import time
import pytest
from ai_manager.services import app_interpreter as ai
from ai_manager.services import service_validation as sv
from ai_manager.config.config_errors import InterpreterUnavailableError, ServiceValidationError, ServiceValidationTimeout

FAKE = '''import json, os, sys, time
from pathlib import Path
if len(sys.argv) == 3:
    if os.environ.get("MANAGER_TEST_IMPORT_SLEEP"):
        time.sleep(30)
    raise SystemExit(int(os.environ.get("MANAGER_TEST_IMPORT_EXIT", "0")))
candidate = Path(sys.argv[3])
Path(os.environ["MANAGER_TEST_RECORD"]).write_text(json.dumps({"pid":os.getpid(), "cwd":str(Path.cwd()), "argv":sys.argv[1:], "candidate":str(candidate), "bytes":candidate.read_text(encoding="utf-8"), "mode":candidate.stat().st_mode & 0o777, "environment":os.environ.get("MANAGER_TEST_SENTINEL")}), encoding="utf-8")
if os.environ.get("MANAGER_TEST_SLEEP"):
    time.sleep(30)
print(os.environ.get("MANAGER_TEST_STDOUT", ""), end="")
print(os.environ.get("MANAGER_TEST_STDERR", ""), end="", file=sys.stderr)
raise SystemExit(int(os.environ.get("MANAGER_TEST_VALIDATOR_EXIT", "0")))
'''


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


@pytest.fixture
def fake_interpreter(tmp_path, monkeypatch):
    app = tmp_path / "application"
    app.mkdir()
    record = tmp_path / "record.json"
    python = executable(app / ".venv" / "bin" / "python", FAKE)
    (python.parent / "activate").write_text("# synthetic activation\n")
    monkeypatch.setenv("MANAGER_TEST_RECORD", str(record))
    monkeypatch.setenv("MANAGER_TEST_SENTINEL", "inherited fixture")
    for name in ("MANAGER_TEST_IMPORT_EXIT", "MANAGER_TEST_VALIDATOR_EXIT", "MANAGER_TEST_IMPORT_SLEEP", "MANAGER_TEST_SLEEP", "MANAGER_TEST_STDOUT", "MANAGER_TEST_STDERR"):
        monkeypatch.delenv(name, raising=False)
    return app, record, python


@pytest.mark.parametrize("selection", ["both", "venv", "ambient", "directory-only"])
def test_activation_precedence_and_lexical_path(tmp_path, monkeypatch, selection):
    app = tmp_path / "app"
    app.mkdir()
    ambient = executable(tmp_path / "path" / "python", "raise SystemExit(0)\n")
    monkeypatch.setenv("PATH", str(ambient.parent) + os.pathsep + os.environ.get("PATH", ""))
    for env in (".venv", "venv"):
        folder = app / env / "bin"
        folder.mkdir(parents=True)
        (folder / "python").symlink_to(sys.executable)
        if selection == "both" or selection == "venv" and env == "venv":
            (folder / "activate").write_text("# fixture\n")
    selected = ai.resolve_app_interpreter(app)
    expected = app / ".venv/bin/python" if selection == "both" else app / "venv/bin/python" if selection == "venv" else ambient
    assert selected == expected.absolute()
    if selection in ("both", "venv"):
        assert selected.is_symlink() and selected != selected.resolve()


@pytest.mark.parametrize("failure", ["missing", "nonexec", "no-ambient"])
def test_selected_broken_interpreter_never_falls_back(tmp_path, monkeypatch, failure):
    app = tmp_path / "app"
    app.mkdir()
    if failure != "no-ambient":
        folder = app / ".venv/bin"
        folder.mkdir(parents=True)
        (folder / "activate").write_text("# fixture\n")
        if failure == "nonexec":
            (folder / "python").write_text("not executable")
    else:
        monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    with pytest.raises(InterpreterUnavailableError):
        ai.resolve_app_interpreter(app)
```

- [ ] **Step 2: Write outcome, adjacency and timeout tests.** Append these tests.

```python
@pytest.mark.parametrize("kind", ["chat2api", "file-bridge"])
def test_validator_success_argv_bytes_cwd_and_adjacent_cleanup(fake_interpreter, kind):
    app, record, selected = fake_interpreter
    target = app / ("config.json" if kind == "chat2api" else "config.yaml")
    raw = b'{"server":{"auth_token_env":null},"models":{}}\n' if kind == "chat2api" else b'save_root: "../storage"\n'
    result = sv.validate_candidate(kind, target, app, raw)
    data = json.loads(record.read_text())
    expected_program = sv.CHAT2API_VALIDATE_PROGRAM if kind == "chat2api" else sv.FILE_BRIDGE_VALIDATE_PROGRAM
    assert data["argv"] == ["-c", expected_program, data["candidate"]]
    candidate = Path(data["candidate"])
    assert candidate.parent == target.parent.resolve() and candidate.name.startswith(f".{target.name}.ai-manager-validate-")
    assert data["cwd"] == str(app.resolve()) and data["bytes"].encode() == raw
    assert data["mode"] == 0o600 and data["environment"] == "inherited fixture"
    assert not candidate.exists() and not target.exists()
    assert result.scope == "service"
    assert result.notice == f"configuration valid — validated by {kind} · ai-manager"


@pytest.mark.parametrize("exit_code,expected", [(1, "reject"), (75, "unavailable"), (-1, "reject")])
def test_validator_exit_is_not_import_probe_exit(fake_interpreter, monkeypatch, exit_code, expected):
    app, record, selected = fake_interpreter
    monkeypatch.setenv("MANAGER_TEST_VALIDATOR_EXIT", str(exit_code))
    monkeypatch.setenv("MANAGER_TEST_STDERR", "fixture schema error\n")
    monkeypatch.setenv("MANAGER_TEST_STDOUT", "fixture stdout\n")
    if expected == "reject":
        with pytest.raises(ServiceValidationError) as err:
            sv.validate_candidate("chat2api", app / "config.json", app, b"{}\n")
        assert err.value.stderr == "fixture schema error\n" and err.value.stdout == "fixture stdout\n"
        assert err.value.returncode == (255 if exit_code == -1 else exit_code)
    else:
        result = sv.validate_candidate("chat2api", app / "config.json", app, b"{}\n")
        assert result.scope == "manager-only" and "fixture schema error\n" in result.detail
        assert result.notice == "validated by ai-manager only — service validator unavailable"
    assert record.exists() and not Path(json.loads(record.read_text())["candidate"]).exists()


def test_import_failure_degrades_without_running_validator(fake_interpreter, monkeypatch):
    app, record, selected = fake_interpreter
    monkeypatch.setenv("MANAGER_TEST_IMPORT_EXIT", "1")
    result = sv.validate_candidate("chat2api", app / "config.json", app, b"{}")
    assert result.scope == "manager-only" and not record.exists()
    selected.unlink()
    assert sv.validate_candidate("chat2api", app / "config.json", app, b"{}").scope == "manager-only"


def test_timeout_kills_reaps_and_cleans(fake_interpreter, monkeypatch):
    app, record, selected = fake_interpreter
    children = []
    original = sv.subprocess.Popen
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(sv.subprocess, "Popen", spawn)
    monkeypatch.setattr(sv, "VALIDATOR_TIMEOUT_S", 0.15)
    monkeypatch.setenv("MANAGER_TEST_SLEEP", "1")
    with pytest.raises(ServiceValidationTimeout):
        sv.validate_candidate("chat2api", app / "config.json", app, b"{}")
    assert all(child.poll() is not None for child in children)
    data = json.loads(record.read_text())
    assert not Path(data["candidate"]).exists()
    monkeypatch.delenv("MANAGER_TEST_SLEEP")
    monkeypatch.setenv("MANAGER_TEST_IMPORT_SLEEP", "1")
    monkeypatch.setattr(ai, "IMPORT_TIMEOUT_S", 0.15)
    assert sv.validate_candidate("chat2api", app / "config.json", app, b"{}").scope == "manager-only"
    assert all(child.poll() is not None for child in children)


def test_symlinked_parent_uses_actual_candidate_location(fake_interpreter, tmp_path):
    app, record, selected = fake_interpreter
    link = tmp_path / "linked-parent"
    link.symlink_to(app, target_is_directory=True)
    sv.validate_candidate("file-bridge", link / "config.yaml", app, b'save_root: "../storage"\n')
    data = json.loads(record.read_text())
    assert Path(data["candidate"]).parent == app.resolve()
    assert (Path(data["candidate"]).parent / "../storage").resolve() == (app.parent / "storage").resolve()
```

- [ ] **Step 3: Run tests and confirm missing interpreter/validator modules fail.**

```bash
PYTHONPATH=src pytest tests/test_validator_orchestration.py -q
```

- [ ] **Step 4: Implement interpreter resolution and import probing.**

```python
# services/app_interpreter.py
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
from ai_manager.config.config_errors import InterpreterUnavailableError, UnknownConfigKindError
from ai_manager.config.structured_models import StructuredKind

IMPORT_TIMEOUT_S = 10.0


def resolve_app_interpreter(app_dir: Path) -> Path:
    directory = app_dir.resolve()
    selected = None
    for env in (".venv", "venv"):
        if (directory / env / "bin/activate").is_file():
            selected = directory / env / "bin/python"
            break
    if selected is None:
        ambient = shutil.which("python")
        if ambient is not None:
            selected = Path(os.path.abspath(ambient))
    if selected is None or not selected.is_file() or not os.access(selected, os.X_OK):
        raise InterpreterUnavailableError(f"Application interpreter is unavailable: {selected or 'python on PATH'}")
    return selected


def verify_app_interpreter(kind: StructuredKind, app_dir: Path, interpreter: Path) -> None:
    if kind == "chat2api":
        program = "import app, fastapi"
    elif kind == "file-bridge":
        program = "import main, fastapi"
    else:
        raise UnknownConfigKindError(kind)
    try:
        child = subprocess.Popen([str(interpreter), "-c", program], cwd=app_dir.resolve(), shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InterpreterUnavailableError(str(exc)) from exc
    try:
        stdout, stderr = child.communicate(timeout=IMPORT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        child.kill()
        stdout, stderr = child.communicate()
        raise InterpreterUnavailableError(f"Interpreter import probe timed out.\n{stdout}{stderr}") from exc
    if child.returncode != 0:
        raise InterpreterUnavailableError(f"Interpreter import probe exited {child.returncode}.\n{stdout}{stderr}")
```

- [ ] **Step 5: Implement exact validator programs, adjacent candidate lifetime and outcome classification.**

```python
# services/service_validation.py
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
from ai_manager.config.config_errors import ConfigError, InterpreterUnavailableError, ServiceValidationError, ServiceValidationTimeout, UnknownConfigKindError
from ai_manager.config.structured_models import StructuredKind, ValidationResult
from ai_manager.services.app_interpreter import resolve_app_interpreter, verify_app_interpreter

VALIDATOR_TIMEOUT_S = 10.0
DEGRADED_NOTICE = "validated by ai-manager only — service validator unavailable"
CHAT2API_VALIDATE_PROGRAM = '''import sys
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
'''
FILE_BRIDGE_VALIDATE_PROGRAM = '''import sys
from pathlib import Path
try:
    import main
except ImportError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(75)
cfg = main.load_config(Path(sys.argv[1]))
main._probe_save_root(cfg.save_root)
'''


def validate_candidate(kind: StructuredKind, target_path: Path, app_dir: Path, rendered: bytes) -> ValidationResult:
    if kind == "chat2api":
        program = CHAT2API_VALIDATE_PROGRAM
    elif kind == "file-bridge":
        program = FILE_BRIDGE_VALIDATE_PROGRAM
    else:
        raise UnknownConfigKindError(kind)
    try:
        interpreter = resolve_app_interpreter(app_dir)
        verify_app_interpreter(kind, app_dir, interpreter)
    except InterpreterUnavailableError as exc:
        return ValidationResult("manager-only", DEGRADED_NOTICE, str(exc))
    target = target_path.parent.resolve() / target_path.name
    candidate = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{target.name}.ai-manager-validate-", suffix=target.suffix, dir=target.parent)
        candidate = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        child = subprocess.Popen([str(interpreter), "-c", program, str(candidate)], cwd=app_dir.resolve(), shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = child.communicate(timeout=VALIDATOR_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            child.kill()
            stdout, stderr = child.communicate()
            raise ServiceValidationTimeout(stdout, stderr) from exc
        if child.returncode == 75:
            return ValidationResult("manager-only", DEGRADED_NOTICE, stdout + stderr)
        if child.returncode != 0:
            raise ServiceValidationError(child.returncode, stdout, stderr)
        return ValidationResult("service", f"configuration valid — validated by {kind} · ai-manager")
    except OSError as exc:
        raise ConfigError(f"Configuration save failed: {exc}") from exc
    finally:
        if candidate is not None:
            try:
                candidate.unlink()
            except OSError as exc:
                raise ConfigError(f"Configuration save failed: {exc}") from exc
```

- [ ] **Step 6: Add a real-Python program-contract test with isolated modules and dotenv data.** This executes the exact program constants with an actual interpreter, so fake exit codes cannot conceal login/discovery or auth-order mistakes.

```python
# append to tests/test_validator_orchestration.py
CONFIG_MODULE = '''import json, os
from pathlib import Path
from types import SimpleNamespace
def load_config(path):
    dotenv = Path(".env")
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    data = json.loads(Path(path).read_text())
    def validate_auth():
        name = data.get("server", {}).get("auth_token_env", "CHAT2API_TOKEN")
        if name is not None and not os.environ.get(name):
            raise RuntimeError("fixture auth variable is missing or empty")
    return SimpleNamespace(validate_auth=validate_auth, data=data)
'''
REGISTRY_MODULE = '''class Registry:
    def __init__(self, cfg):
        if cfg.data.get("reject_registry"):
            raise RuntimeError("fixture registry runtime failure")
def startup_login():
    raise AssertionError("network login must never run")
def ensure_discovered():
    raise AssertionError("discovery must never run")
'''


@pytest.mark.parametrize("auth,env_value,dotenv,valid", [("FIXTURE_TOKEN", None, False, False), ("FIXTURE_TOKEN", "", False, False), ("FIXTURE_TOKEN", None, True, True), (None, None, False, True)])
def test_real_program_auth_and_no_runtime_calls(tmp_path, monkeypatch, auth, env_value, dotenv, valid):
    app = tmp_path / "isolated-app"
    package = app / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (app / "fastapi.py").write_text("")
    (package / "config.py").write_text(CONFIG_MODULE)
    (package / "registry.py").write_text(REGISTRY_MODULE)
    selected = app / "venv/bin/python"
    selected.parent.mkdir(parents=True)
    selected.symlink_to(sys.executable)
    (selected.parent / "activate").write_text("# conventional fixture\n")
    monkeypatch.delenv("FIXTURE_TOKEN", raising=False)
    if env_value is not None:
        monkeypatch.setenv("FIXTURE_TOKEN", env_value)
    if dotenv:
        (app / ".env").write_text("FIXTURE_TOKEN=fixture-bearer-value\n")
    data = {"server": {"auth_token_env": auth}, "models": {"echo-1": {"provider": "echo"}}}
    raw = json.dumps(data).encode()
    if valid:
        assert sv.validate_candidate("chat2api", app / "config.json", app, raw).scope == "service"
        data["reject_registry"] = True
        with pytest.raises(ServiceValidationError) as err:
            sv.validate_candidate("chat2api", app / "config.json", app, json.dumps(data).encode())
        assert "fixture registry runtime failure" in err.value.stderr
    else:
        with pytest.raises(ServiceValidationError) as err:
            sv.validate_candidate("chat2api", app / "config.json", app, raw)
        assert "fixture auth variable is missing or empty" in err.value.stderr
    assert not list(app.glob(".*.ai-manager-validate-*"))
```

- [ ] **Step 7: Run orchestration plus unconditional schema tests.**

```bash
PYTHONPATH=src pytest tests/test_validator_orchestration.py tests/test_structured_validation.py -q
```

Expected: PASS with exact stderr preservation, import versus validator timeout classification, no fallback from a selected broken venv, and no target writes.

- [ ] **Step 8: Commit.**

```bash
git add src/ai_manager/services/app_interpreter.py src/ai_manager/services/service_validation.py tests/test_validator_orchestration.py
git commit -m "feat(validation): run service checks with the selected app interpreter"
```

## Task 7: Prove launcher capability and provide the gate worker

**Implementer tier:** Advanced

**Files:**

- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/launcher_gate.py`.
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/config_jobs.py` (signals and LauncherProbeJob only; Task 9 adds StructuredSaveJob).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_launcher_gate.py`.

**Interfaces:**

- Consumes: Task 1 `AppMetadata` including `id: str`, `relative_path: Path`; Task 2 `LauncherProbeResult(passed: bool, detail: str = "", stdout: str = "", stderr: str = "", returncode: int | None = None)`.
- Produces: `probe_launcher(app_dir: Path, *, timeout_s: float = 10.0) -> LauncherProbeResult` (uncached, no widgets, no sockets); `ConfigJobSignals(QObject)` with `save_finished(str, object)`, `save_failed(str, object)`, `probe_finished(str, object)` signals; `LauncherProbeJob(QRunnable).__init__(meta: AppMetadata)` and `.run() -> None`, exposing `.signals: ConfigJobSignals` and emitting exactly one terminal probe result.

### Step 1: Write the capability-gate tests

```python
# tests/test_launcher_gate.py
import json
import os
from pathlib import Path

import pytest

from ai_manager.services.launcher_gate import probe_launcher


def _write_launcher(directory: Path, body: str) -> Path:
    """Create an executable fake start.sh in *directory*."""
    script = directory / "start.sh"
    script.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def test_print_listener_success(tmp_path):
    _write_launcher(tmp_path, 'printf "127.0.0.1\\n8123\\n"\n')
    result = probe_launcher(tmp_path)
    assert result.passed is True
    assert result.returncode == 0


def test_exactly_two_lines_are_required(tmp_path):
    _write_launcher(tmp_path, 'printf "127.0.0.1\\n"\n')
    assert probe_launcher(tmp_path).passed is False


def test_rejects_non_loopback_or_bad_port(tmp_path):
    for body in (
        'printf "0.0.0.0\\n8000\\n"\n',
        'printf "127.0.0.1\\n0\\n"\n',
        'printf "127.0.0.1\\n65536\\n"\n',
        'printf "127.0.0.1\\nnotanint\\n"\n',
    ):
        directory = tmp_path / body[:8].replace("/", "_").replace(".", "_")
        directory.mkdir()
        _write_launcher(directory, body)
        result = probe_launcher(directory)
        assert result.passed is False, body


def test_legacy_launcher_without_the_flag_fails_closed(tmp_path):
    _write_launcher(tmp_path, 'echo "No such option" >&2\nexit 2\n')
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert result.returncode == 2


def test_timeout_is_a_failure(tmp_path):
    _write_launcher(tmp_path, 'sleep 30\n')
    result = probe_launcher(tmp_path, timeout_s=0.5)
    assert result.passed is False


def test_missing_launcher_is_a_failure(tmp_path):
    assert probe_launcher(tmp_path).passed is False


def test_gate_never_binds_a_socket(tmp_path):
    """The gate must pass a real launcher without opening any listener."""
    _write_launcher(tmp_path, 'printf "127.0.0.1\\n8123\\n"\n')
    probe_launcher(tmp_path)
    # No port was requested, allocated, or bound by the gate: the fake launcher
    # only printed. Assert the gate never called socket bind by construction.
    source = Path("src/ai_manager/services/launcher_gate.py").read_text()
    assert "socket" not in source
    assert "bind(" not in source
```

### Step 2: Implement the capability gate

```python
# src/ai_manager/services/launcher_gate.py
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ai_manager.config.structured_models import LauncherProbeResult

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
FLAG = "--print-listener"


def _parse(stdout: str) -> tuple[str, int] | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        return None
    host, raw_port = lines
    if host.lower() not in LOOPBACK:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return host, port


def probe_launcher(app_dir: Path, *, timeout_s: float = 10.0) -> LauncherProbeResult:
    """Ask the launcher what it would bind, without binding anything.

    Runs ``start.sh --print-listener``. That flag resolves the config with the
    same interpreter and loader as the serving path, prints host and port, and
    exits before any uvicorn import or socket bind. A launcher without the flag
    exits non-zero, which is treated as "capability absent".
    """
    launcher = Path(app_dir) / "start.sh"
    if not launcher.is_file():
        return LauncherProbeResult(passed=False, detail=f"No launcher at {launcher}")
    try:
        completed = subprocess.run(
            [str(launcher), FLAG],
            cwd=str(app_dir),
            env=None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return LauncherProbeResult(passed=False, detail="Launcher capability check timed out.")
    except OSError as exc:
        return LauncherProbeResult(passed=False, detail=f"Could not run the launcher: {exc}")
    parsed = _parse(completed.stdout) if completed.returncode == 0 else None
    if parsed is None:
        detail = (completed.stderr or completed.stdout or "").strip()
        return LauncherProbeResult(
            passed=False,
            detail=detail or "Launcher did not report a valid listener.",
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
    return LauncherProbeResult(
        passed=True,
        detail=f"Launcher honors configuration: {parsed[0]}:{parsed[1]}",
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )
```

### Step 3: Implement the Qt worker shell

```python
# src/ai_manager/services/config_jobs.py
from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ai_manager.config.models import AppMetadata
from ai_manager.services.launcher_gate import probe_launcher


class ConfigJobSignals(QObject):
    save_finished = pyqtSignal(str, object)
    save_failed = pyqtSignal(str, object)
    probe_finished = pyqtSignal(str, object)


class LauncherProbeJob(QRunnable):
    """Runs the capability gate off the GUI thread and emits one result."""

    def __init__(self, meta: AppMetadata) -> None:
        super().__init__()
        self.meta = meta
        self.signals = ConfigJobSignals()

    def run(self) -> None:  # pragma: no cover - exercised via direct call
        try:
            result = probe_launcher(self.meta.relative_path)
        except Exception as exc:  # never let a worker die silently
            result = type("R", (), {"passed": False, "detail": str(exc)})()
        self.signals.probe_finished.emit(self.meta.id, result)
```

- [ ] **Step 4: Run the gate tests until they pass.**
- [ ] **Step 5: Run the full suite; confirm no regression.**
- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/services/launcher_gate.py src/ai_manager/services/config_jobs.py tests/test_launcher_gate.py
git commit -m "feat(launcher): gate listener editing on a stateless capability check"
```

## Task 8: Render dependent YAML purely and detect exact listener matches

**Implementer tier:** Advanced

**Files:**

- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/yaml_manager.py:1-9`, `:43-77`, `:80-153` (imports, extract normalization, pure rendering and both writer paths).
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/blast_radius.py`.
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_yaml_manager.py:1-120` (retain tests, append).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_blast_radius.py`.

**Interfaces:**

- Consumes: Task 1 `require_llm(meta) -> None`, `ConfigLoadError(path, detail, reason="load-error")`, `StaleDocumentError(path, expected_sha256, actual_sha256)`; Task 2 `StructuredDoc`, `DependentMatch(meta, path, doc, raw_bytes, raw_sha256, saved_config, old_api_base, new_api_base, auth_warning=None)`, `Mutation(address, operation, value=None)`, `structured_config._snapshot(path) -> tuple[Path, bytes | None, int | None, tuple[str, ...]]`, `_candidate(doc: StructuredDoc) -> MutableMapping`; Tasks 3–4 `Transaction` context with `.prepare(paths, expected)`, `.backups()`, `.stage(rendered)`, `.replace_all() -> TransactionReport`.
- Produces: `render_app_config(meta: AppMetadata, doc: MutableMapping[str, Any], mutate: Callable[[MutableMapping[str, Any]], None]) -> bytes`; `_render_document(doc) -> bytes`; `_apply_ai_config(meta, doc, new_config: AppAIConfig) -> None`; `_config_from_document(doc) -> AppAIConfig`; `write_app_config(meta, new_config, expected_sha256: bytes | None = None) -> None` with unchanged two-arg behavior.
- Produces: `normalize_loopback_url(url: str) -> str | None`; `urls_match(a: str, b: str) -> bool`; `endpoint(doc: StructuredDoc) -> tuple[str, int, str]` (effective host, port, URL); `find_affected_dependents(apps: Mapping[str, AppMetadata], before: StructuredDoc, after: StructuredDoc) -> tuple[DependentMatch, ...]`; `auth_mismatch_warning(dependent: AppAIConfig, auth_token_env: str | None) -> str | None` returning the catalog template with `{app_id}` still literal so callers can substitute an id without reconstructing its text.

- [ ] **Step 1: Write URL, snapshot, pure-render, auth and failure tests.**

```python
# tests/test_blast_radius.py
import copy
from dataclasses import replace
import hashlib
import pytest
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.blast_radius import auth_mismatch_warning, endpoint, find_affected_dependents, normalize_loopback_url, urls_match
from ai_manager.config.config_errors import ConfigLoadError
from ai_manager.config.models import AppAIConfig
from ai_manager.config.structured_config import load
from ai_manager.config.structured_models import Mutation
from ai_manager.config.yaml_manager import render_app_config

BASE = "http://127.0.0.1:8000"


@pytest.mark.parametrize("url,match", [(BASE, True), (BASE + "/", True), ("http://localhost:8000", True), ("http://[::1]:8000", True), ("http://LOCALHOST:8000", True), (BASE + "/v1", False), ("http://127.0.0.1:8001", False), ("https://127.0.0.1:8000", False), (BASE + "/?x=1", False), ("http://0.0.0.0:8000", False), (BASE + "///", False), ("http://user:pw@127.0.0.1:8000", False)])
def test_normative_url_matrix(url, match):
    assert urls_match(BASE, url) is match
    assert urls_match(url, BASE) is match


def test_normalization_changes_host_only():
    assert normalize_loopback_url("HTTP://u:p@LOCALHOST:08000/v1/?x=1#f") == "HTTP://u:p@127.0.0.1:08000/v1/?x=1#f"
    assert not urls_match("HTTP://localhost:8000", BASE)
    assert normalize_loopback_url("http://127.0.0.2:8000") is None
    assert normalize_loopback_url("not a URL") is None


def drafts(workspace):
    apps = get_managed_apps(workspace)
    before = load("chat2api", apps["chat2api"].relative_path / "config.json")
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    return apps, before, after


def test_three_snapshots_and_only_exact_api_base_changes(five_app_workspace, monkeypatch):
    apps, before, after = drafts(five_app_workspace)
    monkeypatch.setattr("ai_manager.config.yaml_manager.write_app_config", lambda *a, **k: pytest.fail("D7 cannot call a writer"))
    matches = find_affected_dependents(apps, before, after)
    assert [m.meta.id for m in matches] == ["ai-grammar", "textkit", "yt2txt"]
    for match in matches:
        assert match.raw_bytes == match.path.read_bytes()
        assert match.raw_sha256 == hashlib.sha256(match.raw_bytes).digest()
        original = copy.deepcopy(match.doc)
        def update(tree):
            tree["ai"]["api_base"] = match.new_api_base
        rendered = render_app_config(match.meta, match.doc, update)
        assert rendered == match.raw_bytes.replace(b"http://127.0.0.1:8000", b"http://127.0.0.1:8123")
        assert match.doc == original and match.path.read_bytes() == match.raw_bytes
        assert match.saved_config.api_base == BASE
    assert matches[1].saved_config.is_split_model
    assert endpoint(replace(before, mutations=(Mutation(("server", "host"), "set", "::1"),)))[2] == "http://[::1]:8000"


def test_unchanged_listener_reads_nothing_and_external_base_excluded(five_app_workspace, monkeypatch):
    apps, before, after = drafts(five_app_workspace)
    with monkeypatch.context() as patch:
        patch.setattr("ai_manager.config.blast_radius._snapshot", lambda path: pytest.fail("auth-only edit must not inspect disk"))
        assert find_affected_dependents(apps, before, replace(before, mutations=(Mutation(("server", "auth_token_env"), "set", "OTHER_TOKEN"),))) == ()
    path = apps["textkit"].relative_path / "config.yaml"
    path.write_bytes(path.read_bytes().replace(BASE.encode(), b"https://api.example.invalid"))
    assert [m.meta.id for m in find_affected_dependents(apps, before, after)] == ["ai-grammar", "yt2txt"]


@pytest.mark.parametrize("failure", ["missing", "anchor", "readonly", "malformed", "symlink"])
def test_uninspectable_dependent_refuses_without_example_creation(five_app_workspace, failure):
    apps, before, after = drafts(five_app_workspace)
    path = apps["textkit"].relative_path / "config.yaml"
    if failure == "missing":
        path.unlink()
    elif failure == "anchor":
        path.write_text("ai: &a {api_base: 'http://127.0.0.1:8000'}\nother: *a\n")
    elif failure == "readonly":
        path.chmod(0o444)
    elif failure == "malformed":
        path.write_text("ai: [broken\n")
    else:
        path.unlink()
        path.symlink_to("config.example.yaml")
    with pytest.raises(ConfigLoadError, match="Cannot inspect dependent configuration"):
        find_affected_dependents(apps, before, after)
    if failure == "missing":
        assert not path.exists()


@pytest.mark.parametrize("key,auth,warn", [("$OTHER_TOKEN", "CHAT2API_TOKEN", True), (" $OTHER_TOKEN ", "CHAT2API_TOKEN", True), ("$CHAT2API_TOKEN", "CHAT2API_TOKEN", False), ("literal", "CHAT2API_TOKEN", False), ("", "CHAT2API_TOKEN", False), ("$OTHER_TOKEN", None, False)])
def test_auth_warnings(key, auth, warn):
    message = auth_mismatch_warning(AppAIConfig(api_key=key), auth)
    assert (message is not None) is warn
    if warn:
        assert message.format(app_id="ai-grammar") == "ai-grammar uses $OTHER_TOKEN, but chat2api auth_token_env is 'CHAT2API_TOKEN'; requests may fail with HTTP 401."
```

```python
# append to tests/test_yaml_manager.py
import hashlib
from ai_manager.config.config_errors import StaleDocumentError
from ai_manager.config.yaml_manager import render_app_config


def test_pure_renderer_and_checked_writer(five_app_workspace, monkeypatch):
    meta = get_managed_apps(five_app_workspace)["ai-grammar"]
    path = meta.relative_path / "config.yaml"
    original = path.read_bytes()
    doc = _get_yaml_engine().load(original.decode())
    def update(tree):
        tree["ai"]["api_base"] = "http://127.0.0.1:8123"
    rendered = render_app_config(meta, doc, update)
    assert rendered == original.replace(b":8000", b":8123")
    assert path.read_bytes() == original and doc["ai"]["api_base"].endswith(":8000")
    cfg = read_app_config(meta).model_copy(update={"model": "checked"})
    digest = hashlib.sha256(original).digest()
    path.write_bytes(original + b"# hand edit\n")
    with pytest.raises(StaleDocumentError):
        write_app_config(meta, cfg, digest)
    assert path.read_bytes() == original + b"# hand edit\n"
    path.unlink()
    with pytest.raises(StaleDocumentError):
        write_app_config(meta, cfg, digest)
    assert not path.exists()
    path.write_bytes(original)
    assert write_app_config(meta, cfg, digest) is None
    assert read_app_config(meta).model == "checked"
    assert list(path.parent.glob("config.yaml.*.bak")) and not (path.parent / "config.yaml.bak").exists()
    assert write_app_config(meta, cfg) is None
    assert (path.parent / "config.yaml.bak").exists()
```

- [ ] **Step 2: Run and observe missing pure-render/blast interfaces.**

```bash
PYTHONPATH=src pytest tests/test_blast_radius.py tests/test_yaml_manager.py -q
```

- [ ] **Step 3: Extract the current normalization and install pure rendering without changing legacy effects.** Add copy/io, Callable/MutableMapping and Any imports. Move the existing `read_app_config` block starting `ai_section = doc.get("ai") or {}` through both AppAIConfig returns into `_config_from_document(doc) -> AppAIConfig` without changing its expressions. Replace the moved block with `return _config_from_document(doc)`. This is the exact replacement writer/rendering code:

```python
def _render_document(doc: MutableMapping[str, Any]) -> bytes:
    stream = io.StringIO()
    _get_yaml_engine().dump(doc, stream)
    return stream.getvalue().encode("utf-8")


def render_app_config(meta: AppMetadata, doc: MutableMapping[str, Any], mutate: Callable[[MutableMapping[str, Any]], None]) -> bytes:
    require_llm(meta)
    candidate = copy.deepcopy(doc)
    mutate(candidate)
    return _render_document(candidate)


def _apply_ai_config(meta: AppMetadata, doc: MutableMapping[str, Any], new_config: AppAIConfig) -> None:
    if "ai" not in doc or not isinstance(doc["ai"], dict):
        doc["ai"] = CommentedMap()
    ai_sec = doc["ai"]
    ai_sec["api_base"] = new_config.api_base
    ai_sec["api_key"] = new_config.api_key
    if new_config.is_split_model and meta.supports_split_models:
        ai_sec.pop("model", None)
        if not isinstance(ai_sec.get("ocr"), dict):
            ai_sec["ocr"] = CommentedMap()
        if not isinstance(ai_sec.get("text"), dict):
            ai_sec["text"] = CommentedMap()
        ai_sec["ocr"]["model"] = new_config.ocr_model or ""
        ai_sec["text"]["model"] = new_config.text_model or ""
    else:
        ai_sec.pop("ocr", None)
        ai_sec.pop("text", None)
        ai_sec["model"] = new_config.model or ""


def write_app_config(app_meta: AppMetadata, new_config: AppAIConfig, expected_sha256: bytes | None = None) -> None:
    require_llm(app_meta)
    if expected_sha256 is not None:
        from ai_manager.config.structured_config import _snapshot
        from ai_manager.config.config_errors import StaleDocumentError
        from ai_manager.config.transaction import Transaction
        cfg_path, raw, mode, reasons = _snapshot(get_config_path(app_meta))
        if raw is None:
            raise StaleDocumentError(cfg_path, expected_sha256, None)
        doc = _get_yaml_engine().load(raw.decode("utf-8"))
        if doc is None:
            doc = CommentedMap()
        rendered = render_app_config(app_meta, doc, lambda tree: _apply_ai_config(app_meta, tree, new_config))
        with Transaction() as tx:
            tx.prepare([cfg_path], {cfg_path: expected_sha256})
            tx.backups()
            tx.stage({cfg_path: rendered})
            tx.replace_all()
        return
    cfg_path = ensure_config_exists(app_meta)
    doc = _get_yaml_engine().load(cfg_path.read_text(encoding="utf-8"))
    if doc is None:
        doc = CommentedMap()
    rendered = render_app_config(app_meta, doc, lambda tree: _apply_ai_config(app_meta, tree, new_config))
    backup_path = cfg_path.with_name(f"{cfg_path.name}.bak")
    shutil.copy2(cfg_path, backup_path)
    temp_path = cfg_path.with_name(f"{cfg_path.name}.tmp.{os.getpid()}_{uuid.uuid4().hex[:6]}")
    try:
        with open(temp_path, "wb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        if cfg_path.exists():
            os.chmod(temp_path, stat.S_IMODE(cfg_path.stat().st_mode))
        os.replace(temp_path, cfg_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: Implement the one shared URL comparator and captured dependent inspection.**

```python
# config/blast_radius.py
from __future__ import annotations
from collections.abc import Mapping
import io
import re
from urllib.parse import urlsplit
from ruamel.yaml.tokens import AliasToken, AnchorToken
from ai_manager.config.config_errors import ConfigError, ConfigLoadError, ConfigValidationError, FieldIssue
from ai_manager.config.models import AppAIConfig, AppMetadata
from ai_manager.config.structured_config import _candidate, _snapshot
from ai_manager.config.structured_models import DependentMatch, StructuredDoc
from ai_manager.config.structured_schema import Chat2ApiServerSchema
from ai_manager.config.yaml_manager import _config_from_document, _get_yaml_engine
from ai_manager.utils.env_resolver import is_env_var_reference
import hashlib

URL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)([^/?#]+)(.*)$", re.DOTALL)


def normalize_loopback_url(url: str) -> str | None:
    match = URL_RE.fullmatch(url)
    if match is None:
        return None
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        return None
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        return None
    scheme, authority, rest = match.groups()
    userinfo, marker, host_port = authority.rpartition("@")
    prefix = userinfo + marker if marker else ""
    if not marker:
        host_port = authority
    if host_port.startswith("["):
        end = host_port.find("]")
        if end == -1 or host_port[1:end] != "::1":
            return None
        suffix = host_port[end + 1:]
    else:
        host, separator, port = host_port.partition(":")
        if host.lower() not in ("127.0.0.1", "localhost"):
            return None
        suffix = separator + port
    if suffix and re.fullmatch(r":[0-9]+", suffix) is None:
        return None
    return scheme + prefix + "127.0.0.1" + suffix + rest


def urls_match(a: str, b: str) -> bool:
    left = normalize_loopback_url(a[:-1] if a.endswith("/") else a)
    right = normalize_loopback_url(b[:-1] if b.endswith("/") else b)
    return left is not None and right is not None and left == right


def endpoint(doc: StructuredDoc) -> tuple[str, int, str]:
    server = Chat2ApiServerSchema.model_validate(_candidate(doc).get("server", {}))
    host = f"[{server.host}]" if server.host == "::1" else server.host
    return server.host, server.port, f"http://{host}:{server.port}"


def auth_mismatch_warning(dependent: AppAIConfig, auth_token_env: str | None) -> str | None:
    if auth_token_env is None or not is_env_var_reference(dependent.api_key):
        return None
    dependent_env = dependent.api_key.strip()[1:]
    if dependent_env == auth_token_env:
        return None
    return f"{{app_id}} uses ${dependent_env}, but chat2api auth_token_env is {auth_token_env!r}; requests may fail with HTTP 401."


def find_affected_dependents(apps: Mapping[str, AppMetadata], before: StructuredDoc, after: StructuredDoc) -> tuple[DependentMatch, ...]:
    old_host, old_port, old_url = endpoint(before)
    new_host, new_port, new_url = endpoint(after)
    if (old_host, old_port) == (new_host, new_port):
        return ()
    auth = Chat2ApiServerSchema.model_validate(_candidate(after).get("server", {})).auth_token_env
    matches = []
    for app_id, meta in apps.items():
        if app_id not in ("ai-grammar", "textkit", "yt2txt") or meta.config_kind != "llm":
            continue
        path = meta.relative_path / meta.config_file_name
        try:
            canonical, raw, mode, reasons = _snapshot(path)
            if raw is None:
                raise ValueError("Configuration file is missing.")
            if reasons:
                raise ValueError("Configuration is not writable; editing is disabled.")
            text = raw.decode("utf-8")
            if any(isinstance(token, (AnchorToken, AliasToken)) for token in _get_yaml_engine().scan(io.StringIO(text))):
                raise ValueError("YAML anchors or aliases are present; editing is disabled to preserve linked values.")
            engine = _get_yaml_engine()
            engine.allow_duplicate_keys = False
            tree = engine.load(text)
            if not isinstance(tree, dict) or not isinstance(tree.get("ai"), dict) or not isinstance(tree["ai"].get("api_base"), str):
                raise ValueError("Expected a mapping with a string ai.api_base.")
            old_base = tree["ai"]["api_base"]
            if urls_match(old_base, old_url):
                saved = _config_from_document(tree)
                warning = auth_mismatch_warning(saved, auth)
                matches.append(DependentMatch(meta, canonical, tree, raw, hashlib.sha256(raw).digest(), saved, old_base, new_url, warning.format(app_id=app_id) if warning else None))
        except Exception as exc:
            # The entire operation is inspection: never treat an unreadable file as a nonmatch.
            message = f"Cannot inspect dependent configuration {path}: {exc}"
            error = ConfigLoadError(path, str(exc))
            error.args = (message,)
            raise error from exc
    return tuple(matches)
```

In the imports above, `FieldIssue` comes from `structured_models`, not `config_errors`; omit the two unused names `ConfigValidationError` and `FieldIssue` rather than importing an invalid re-export. This keeps the dependency direction `blast_radius -> structured_config` and `structured_config.commit -> local import of blast_radius/yaml_manager`, avoiding a top-level cycle.

- [ ] **Step 5: Run pure rendering, URL, and legacy regression tests.**

```bash
PYTHONPATH=src pytest tests/test_blast_radius.py tests/test_yaml_manager.py tests/test_structured_config.py -q
```

Expected: PASS; initial `.bak` tests and split transitions retain their existing expectations, no D7 render writes, exact URL negative rows remain negative.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/config/yaml_manager.py src/ai_manager/config/blast_radius.py tests/test_yaml_manager.py tests/test_blast_radius.py
git commit -m "feat(config): capture dependent snapshots and render API-base-only updates"
```

## Task 9: Coordinate validation and commit, then expose the save worker

**Implementer tier:** Advanced

**Files:**

- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/structured_config.py:1-240` (imports and append commit/baseline helper after render).
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/services/config_jobs.py:1-40` (imports and append StructuredSaveJob).
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_structured_config.py:1-200`, `/data/home/guest/Development/ai/ai-manager/tests/test_blast_radius.py:1-140` (append coordinator tests).
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_validator_orchestration.py:1-220` (append worker ownership tests).

**Interfaces:**

- Consumes: Task 2 `load(kind, path) -> StructuredDoc`, `_parse_bytes(kind, path, raw)`, `effective_mutations(doc) -> tuple[Mutation, ...]`, `render(kind, doc) -> bytes`; Task 5 `validate_written_scalars(mutations) -> None`, `validate_in_process(kind, candidate, *, config_path, app_dir) -> None`; Task 6 `validate_candidate(kind, target_path, app_dir, rendered) -> ValidationResult`; Tasks 3–4 `Transaction.prepare(paths, expected)`, `.backups()`, `.stage(rendered)`, `.replace_all() -> TransactionReport`; Task 8 `render_app_config(meta, doc, mutate) -> bytes`, `_config_from_document(doc) -> AppAIConfig`.
- Consumes: `StructuredDoc` fields kind/path/resolved_path/doc/raw_bytes/raw_sha256/existed/mode/read_only_reasons/mutations/raw_option_edits/input_issues/create_requested; `DependentMatch` fields meta/path/doc/raw_bytes/raw_sha256/saved_config/old_api_base/new_api_base/auth_warning; `SaveResult(document: StructuredDoc, transaction: TransactionReport, validation: ValidationResult, saved_dependents: dict[str, AppAIConfig] = {})`.
- Produces: `commit(kind: StructuredKind, path: Path, doc: StructuredDoc, expected_sha256: bytes | None, *, dependents: tuple[DependentMatch, ...] = ()) -> SaveResult`; `StructuredSaveJob(QRunnable).__init__(meta: AppMetadata, draft: StructuredDoc, dependents: tuple[DependentMatch, ...] = ())`, `.signals: ConfigJobSignals`, `.run() -> None` emitting exactly one save_finished or save_failed.

- [ ] **Step 1: Write coordinator tests with real filesystem transactions and stub service validation.**

```python
# append to tests/test_structured_config.py
from ai_manager.config import structured_config as sc
from ai_manager.config.structured_models import ValidationResult
from ai_manager.config.config_errors import ConfigValidationError, StaleDocumentError


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
```

```python
# append to tests/test_blast_radius.py
from ai_manager.config import structured_config as sc
from ai_manager.config.structured_models import ValidationResult
from ai_manager.config.config_errors import StaleDocumentError


@pytest.mark.parametrize("selected", [(), ("textkit",), ("ai-grammar", "textkit", "yt2txt")])
def test_commit_selected_members_only(five_app_workspace, monkeypatch, selected):
    import ai_manager.services.service_validation as service
    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    apps, before, after = drafts(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    originals = {m.meta.id: m.raw_bytes for m in matches}
    result = sc.commit("chat2api", before.path, after, before.raw_sha256, dependents=tuple(m for m in matches if m.meta.id in selected))
    assert len(result.transaction.files) == 1 + len(selected)
    assert set(result.saved_dependents) == set(selected)
    for match in matches:
        actual = match.path.read_bytes()
        expected = originals[match.meta.id].replace(b":8000", b":8123") if match.meta.id in selected else originals[match.meta.id]
        assert actual == expected
    assert result.document.doc["server"]["port"] == 8123


def test_dialog_snapshot_stale_refuses_every_member(five_app_workspace, monkeypatch):
    import ai_manager.services.service_validation as service
    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    apps, before, after = drafts(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    matches[1].path.write_bytes(matches[1].raw_bytes + b"# later hand edit\n")
    snapshots = {m.path: m.path.read_bytes() for m in matches}
    with pytest.raises(StaleDocumentError):
        sc.commit("chat2api", before.path, after, before.raw_sha256, dependents=matches)
    assert before.path.read_bytes() == before.raw_bytes
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())
```

- [ ] **Step 2: Confirm commit/save-job interfaces are absent.**

```bash
PYTHONPATH=src pytest tests/test_structured_config.py tests/test_blast_radius.py -q
```

- [ ] **Step 3: Append the coordinator, using local imports to keep parse/render usable without cycles.** Add hashlib and `dataclasses.replace` imports if not already present.

```python

def commit(kind: StructuredKind, path: Path, doc: StructuredDoc, expected_sha256: bytes | None, *, dependents: tuple[DependentMatch, ...] = ()) -> SaveResult:
    from ai_manager.config.config_errors import ConfigError
    from ai_manager.config.structured_models import SaveResult
    from ai_manager.config.structured_schema import validate_in_process, validate_written_scalars
    from ai_manager.config.transaction import Transaction
    from ai_manager.config.yaml_manager import _config_from_document, _get_yaml_engine, render_app_config
    from ai_manager.services.service_validation import validate_candidate
    _check_kind(kind)
    requested = Path(os.path.abspath(path))
    canonical = requested.parent.resolve() / requested.name
    if kind != doc.kind or requested != doc.path or canonical != doc.resolved_path or expected_sha256 != doc.raw_sha256:
        raise ConfigValidationError((FieldIssue((), "Save must use the loaded document's kind, path, and digest."),))
    primary = render(kind, doc)
    sealed = {canonical: primary}
    expected = {canonical: expected_sha256}
    dependent_baselines = {}
    scalar_mutations = list(effective_mutations(doc))
    for match in dependents:
        require_llm(match.meta)
        target = match.path.parent.resolve() / match.path.name
        if target in sealed or match.raw_sha256 != hashlib.sha256(match.raw_bytes).digest():
            raise ConfigValidationError((FieldIssue((), "Dependent snapshots must be unique and retain their captured digest."),))
        def update(tree, value=match.new_api_base):
            tree["ai"]["api_base"] = value
        raw = render_app_config(match.meta, match.doc, update)
        parsed = _get_yaml_engine().load(raw.decode("utf-8"))
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ai"), dict):
            raise ConfigValidationError((FieldIssue(("ai",), "Dependent AI configuration must be a mapping."),))
        sealed[target] = raw
        expected[target] = match.raw_sha256
        scalar_mutations.append(Mutation(("ai", "api_base"), "set", match.new_api_base))
        dependent_baselines[match.meta.id] = _config_from_document(parsed)
    validate_written_scalars(tuple(scalar_mutations))
    parsed_primary, parse_reasons = _parse_bytes(kind, canonical, primary)
    validate_in_process(kind, parsed_primary, config_path=canonical, app_dir=canonical.parent)
    validation = validate_candidate(kind, canonical, canonical.parent, primary)
    with Transaction() as tx:
        tx.prepare(list(sealed), expected)
        tx.backups()
        tx.stage(sealed)
        report = tx.replace_all()
    baseline = StructuredDoc(kind=kind, path=requested, resolved_path=canonical, doc=parsed_primary, raw_bytes=primary, raw_sha256=hashlib.sha256(primary).digest(), existed=True, mode=doc.mode if doc.existed else 0o600)
    return SaveResult(baseline, report, validation, dependent_baselines)
```

Import `DependentMatch`, `SaveResult` and `require_llm` at module scope for annotations and guarded dispatch, keeping service/transaction imports local as shown. Wrap local render/parse `OSError`/Unicode/ruamel errors into `ConfigError("Configuration save failed: ...")` if any owning helper does not already translate them; preserve existing ConfigError subclasses. This boundary never retries with newer bytes or changes a supplied expected hash.

- [ ] **Step 4: Add the owned-snapshot save worker and its tests.**

```python
# append to services/config_jobs.py; add imports copy and the named records/errors
class StructuredSaveJob(QRunnable):
    def __init__(self, meta: AppMetadata, draft: StructuredDoc, dependents: tuple[DependentMatch, ...] = ()) -> None:
        super().__init__()
        self.meta = meta.model_copy(deep=True)
        self.draft = copy.deepcopy(draft)
        self.dependents = copy.deepcopy(dependents)
        self.signals = ConfigJobSignals()

    def run(self) -> None:
        from ai_manager.config.config_errors import ConfigError
        from ai_manager.config.structured_config import commit
        try:
            result = commit(self.meta.config_kind, self.draft.path, self.draft, self.draft.raw_sha256, dependents=self.dependents)
        except ConfigError as exc:
            self.signals.save_failed.emit(self.meta.id, exc)
        except Exception as exc:
            self.signals.save_failed.emit(self.meta.id, ConfigError(f"Configuration save failed: {exc}"))
        else:
            self.signals.save_finished.emit(self.meta.id, result)
```

```python
# append to tests/test_validator_orchestration.py
from ai_manager.services.config_jobs import StructuredSaveJob
from ai_manager.config import structured_config as sc
from ai_manager.config.config_errors import ConfigError


def test_save_worker_owns_snapshot_and_emits_exactly_once(five_app_workspace, monkeypatch, qtbot):
    meta = get_managed_apps(five_app_workspace)["chat2api"]
    draft = sc.load("chat2api", meta.relative_path / "config.json")
    job = StructuredSaveJob(meta, draft)
    draft.doc["later-widget-edit"] = True
    results, failures = [], []
    job.signals.save_finished.connect(lambda app_id, result: results.append((app_id, result)))
    job.signals.save_failed.connect(lambda app_id, error: failures.append((app_id, error)))
    def fail(kind, path, owned, expected, **kwargs):
        assert "later-widget-edit" not in owned.doc
        raise ValueError("fixture invariant failure")
    monkeypatch.setattr(sc, "commit", fail)
    job.run()
    assert results == [] and len(failures) == 1 and failures[0][0] == "chat2api"
    assert isinstance(failures[0][1], ConfigError) and str(failures[0][1]) == "Configuration save failed: fixture invariant failure"
```

Add `from ai_manager.config.app_registry import get_managed_apps` to that test module's imports. Use the existing QObject signal object and never import a widget into config_jobs.

- [ ] **Step 5: Run coordinator, transaction, validation and worker tests.**

```bash
PYTHONPATH=src pytest tests/test_structured_config.py tests/test_blast_radius.py tests/test_transaction.py tests/test_structured_validation.py tests/test_validator_orchestration.py -q
```

Expected: PASS; primary and selected dependents are sealed before target mutation, return baselines are from those bytes, and no validation failure reaches prepare.

- [ ] **Step 6: Commit.**

```bash
git add src/ai_manager/config/structured_config.py src/ai_manager/services/config_jobs.py tests/test_structured_config.py tests/test_blast_radius.py tests/test_validator_orchestration.py
git commit -m "feat(config): commit validated sealed candidates through one transaction"
```

## Task 10: Keep structured row and mutation state in one pure editor model

**Implementer tier:** Advanced

**Files:**

- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/structured_editor_model.py`.
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_structured_editor_model.py`.

**Interfaces:**

- Consumes: Task 2 `StructuredDoc`, `Mutation(address, operation, value=None)`, `FieldIssue(address, message)`, `structured_config._apply(tree, mutation) -> None`, `effective_mutations(doc) -> tuple[Mutation, ...]`; Task 2 declarative `PROVIDER_OPTIONS: dict[str, tuple[OptionSpec, ...]]` and `SECRET_OPTION_KEYS: frozenset[str]`.
- Produces: `ModelRow(id: int, original_name: str | None, name: str, route: dict, raw_text: str | None = None)`; `StructuredEditorModel(config: StructuredDoc)` with `.baseline: StructuredDoc`, `.rows: list[ModelRow]`, `.tree: dict`, `.row(row_id) -> ModelRow`, `.add_model(name="", provider="") -> int`, `.remove_model(row_id) -> None`, `.rename_model(row_id, name) -> None`, `.set_field(address, *, present: bool, value=None) -> None`, `.set_option(row_id, key, *, present: bool, value=None) -> None`, `.set_provider(row_id, provider) -> None`, `.set_raw_options(row_id, text) -> None`, `.raw_options(row_id) -> dict`, `.draft() -> StructuredDoc`. This model has no Qt, filesystem or dirty/sidebar logic.

- [ ] **Step 1: Write literal-address, coalescing, duplicate-row and raw-preservation tests.**

```python
# tests/test_structured_editor_model.py
import json
import pytest
from ai_manager.config.structured_config import load, effective_mutations, render
from ai_manager.config.config_errors import ConfigValidationError
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
    assert {(m.address, m.operation) for m in mutations} == {(("models", "echo-1"), "delete"), (("models", "gemini.fast/v2"), "set")}
    state.rename_model(new, "qwen&co/7b")
    tree = json.loads(render("chat2api", state.draft()))
    assert list(tree["models"]) == ["qwen&co/7b"]
    assert tree["models"]["qwen&co/7b"] == {"provider": "echo", "options": {"prefix": "hello"}}


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
    assert effective_mutations(state.draft())[0].address == ("models", "echo-1", "options", "opaque.key/path")
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
    assert after["options"] == {"account": "synthetic-account", "password": "synthetic-password", "future": {"keep": [1, "雪"]}, "headless": False}
    assert state.raw_options(row) == {"future": {"keep": [1, "雪"]}}
    state.set_provider(row, "echo")
    assert "account" not in state.raw_options(row) and "password" not in state.raw_options(row)
    assert "headless" in state.raw_options(row)
    state.set_raw_options(row, '{"password":"raw collision"}')
    with pytest.raises(ConfigValidationError) as err:
        render("chat2api", state.draft())
    assert err.value.issues[0].message == "Edit known or secret options in their fields, not in raw options."
```

- [ ] **Step 2: Run and observe missing model.**

```bash
PYTHONPATH=src pytest tests/test_structured_editor_model.py -q
```

- [ ] **Step 3: Implement owned rows and derive minimal mutations against the loaded tree.**

```python
# ui/structured_editor_model.py
from __future__ import annotations
import copy
from dataclasses import dataclass, replace
from ai_manager.config.config_errors import ConfigValidationError
from ai_manager.config.structured_config import _apply, effective_mutations
from ai_manager.config.structured_models import FieldIssue, Mutation, StructuredDoc
from ai_manager.config.structured_schema import PROVIDER_OPTIONS, SECRET_OPTION_KEYS


def _equal(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return type(left) is type(right) and left == right


def _diff(before, after, prefix):
    result = []
    for key in before:
        if key not in after:
            result.append(Mutation(prefix + (key,), "delete"))
    for key, value in after.items():
        if key not in before or not _equal(before[key], value):
            result.append(Mutation(prefix + (key,), "set", copy.deepcopy(value)))
    return result


@dataclass
class ModelRow:
    id: int
    original_name: str | None
    name: str
    route: dict
    raw_text: str | None = None


class StructuredEditorModel:
    def __init__(self, config: StructuredDoc):
        self.baseline = copy.deepcopy(config)
        self.tree = copy.deepcopy(config.doc)
        for mutation in config.mutations:
            _apply(self.tree, mutation)
        self.rows = [ModelRow(index, name, name, copy.deepcopy(route), config.raw_option_edits.get(name)) for index, (name, route) in enumerate(self.tree.get("models", {}).items())] if config.kind == "chat2api" else []
        self._next_id = len(self.rows)

    def row(self, row_id):
        return next(row for row in self.rows if row.id == row_id)

    def add_model(self, name="", provider=""):
        row = ModelRow(self._next_id, None, name, {"provider": provider})
        self._next_id += 1
        self.rows.append(row)
        return row.id

    def remove_model(self, row_id):
        self.rows = [row for row in self.rows if row.id != row_id]

    def rename_model(self, row_id, name):
        self.row(row_id).name = name

    def set_field(self, address, *, present, value=None):
        _apply(self.tree, Mutation(address, "set" if present else "delete", value if present else None))

    def set_option(self, row_id, key, *, present, value=None):
        row = self.row(row_id)
        options = row.route.setdefault("options", {})
        if present:
            options[key] = copy.deepcopy(value)
        else:
            options.pop(key, None)
            original = self.baseline.doc.get("models", {}).get(row.original_name, {})
            if not options and "options" not in original:
                row.route.pop("options", None)

    def set_provider(self, row_id, provider):
        row = self.row(row_id)
        if row.raw_text is not None:
            try:
                draft = self.draft()
                for mutation in effective_mutations(draft):
                    if mutation.address[:2] == ("models", row.name) and len(mutation.address) > 2:
                        box = {"route": copy.deepcopy(row.route)}
                        _apply(box, Mutation(("route",) + mutation.address[2:], mutation.operation, mutation.value))
                        row.route = box["route"]
                    elif mutation.address == ("models", row.name) and mutation.operation == "set":
                        row.route = copy.deepcopy(mutation.value)
                row.raw_text = None
            except ConfigValidationError:
                pass
        row.route["provider"] = provider

    def set_raw_options(self, row_id, text):
        self.row(row_id).raw_text = text

    def raw_options(self, row_id):
        row = self.row(row_id)
        protected = {o.key for o in PROVIDER_OPTIONS.get(row.route.get("provider"), ())} | SECRET_OPTION_KEYS
        return copy.deepcopy({k: v for k, v in row.route.get("options", {}).items() if k not in protected})

    def draft(self):
        mutations, issues, raw_edits = [], [], {}
        if self.baseline.kind == "file-bridge":
            mutations.extend(_diff(self.baseline.doc, self.tree, ()))
        else:
            old_server = self.baseline.doc.get("server", {})
            new_server = self.tree.get("server", {})
            mutations.extend(_diff(old_server, new_server, ("server",)))
            old_models = self.baseline.doc.get("models", {})
            originals = {row.original_name for row in self.rows if row.original_name is not None}
            for name in old_models:
                if name not in originals:
                    mutations.append(Mutation(("models", name), "delete"))
            seen = set()
            for row in self.rows:
                if not row.name:
                    issues.append(FieldIssue(("models", row.name), "Model names must be non-empty strings."))
                    continue
                if row.name in seen:
                    issues.append(FieldIssue(("models", row.name), "Model names must be unique."))
                    continue
                seen.add(row.name)
                address = ("models", row.name)
                if row.original_name is None or row.name != row.original_name:
                    if row.original_name is not None:
                        mutations.append(Mutation(("models", row.original_name), "delete"))
                    mutations.append(Mutation(address, "set", copy.deepcopy(row.route)))
                else:
                    original = old_models[row.name]
                    mutations.extend(_diff({k: v for k, v in original.items() if k != "options"}, {k: v for k, v in row.route.items() if k != "options"}, address))
                    mutations.extend(_diff(original.get("options", {}), row.route.get("options", {}), address + ("options",)))
                if row.raw_text is not None:
                    raw_edits[row.name] = row.raw_text
        return replace(self.baseline, mutations=tuple(mutations), raw_option_edits=raw_edits, input_issues=tuple(issues))
```

Before returning `draft`, coalesce model rename collisions against *all* row names (including rows encountered later), so renaming `echo-1` onto a preexisting later row cannot generate overlapping parent set/delete addresses. A duplicate remains a row with `input_issues`; no rendering is attempted until names are unique. The tests above pin refusal; append this exact later-row case:

```python
def test_rename_to_later_existing_row_retains_both(five_app_workspace):
    state = model(five_app_workspace)
    second = state.add_model("second", "echo")
    state.rename_model(state.rows[0].id, "second")
    assert len(state.rows) == 2 and state.draft().input_issues[0].message == "Model names must be unique."
    state.rename_model(second, "third")
    assert not state.draft().input_issues
    assert list(json.loads(render("chat2api", state.draft()))["models"]) == ["second", "third"]
```

- [ ] **Step 4: Run pure editor and render tests.**

```bash
PYTHONPATH=src pytest tests/test_structured_editor_model.py tests/test_structured_config.py -q
```

Expected: PASS; every renderable mutation set has no parent/child overlap, absence is preserved, and no duplicate row is lost in a dictionary.

- [ ] **Step 5: Commit.**

```bash
git add src/ai_manager/ui/structured_editor_model.py tests/test_structured_editor_model.py
git commit -m "feat(ui): retain structured draft rows and derive addressed mutations"
```

## Task 11: Build declarative structured views and concrete review dialogs

**Implementer tier:** Advanced

**Files:**

- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/structured_config_view.py`.
- Create (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/config_dialogs.py`.
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/app_detail_view.py:38-41`, `:50-52`, `:137-141`, `:211-223`, `:229-267` (adapter signals, saved-baseline adoption, error details, saving controls).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_structured_view.py`.

**Interfaces:**

- Consumes: Task 10 `StructuredEditorModel(config)` with `.baseline`, `.rows: list[ModelRow(id, original_name, name, route, raw_text)]`, `.tree`, `.row(id)`, `.draft() -> StructuredDoc`, `.add_model(name="", provider="") -> int`, `.remove_model(id)`, `.rename_model(id, name)`, `.set_field(address, *, present, value=None)`, `.set_option(id, key, *, present, value=None)`, `.set_provider(id, provider)`, `.set_raw_options(id, text)`, `.raw_options(id) -> dict`.
- Consumes: Task 2 `render(kind, doc) -> bytes`, `effective_mutations(doc) -> tuple[Mutation, ...]`, `load_example(kind, path, example_path) -> StructuredDoc`; inventories `SERVER_FIELDS`, `FILE_BRIDGE_FIELDS`, `PROVIDER_OPTIONS`, `SECRET_OPTION_KEYS`; `FieldSpec(key, label, control, minimum=None, maximum=None, annotation="")`; `OptionSpec(key, control)`.
- Produces: `StructuredConfigView(QWidget)` common adapter exactly as spec §8.1: four signals `save_requested(str, object, bool)`, `restart_requested(str)`, `config_changed(str, object)`, `fetch_models_requested(ModelFetchRequest)` (never emitted); constructor `(app_meta: AppMetadata, parent=None)`; `load_config(config: StructuredDoc)`, `get_current_draft() -> StructuredDoc`, `adopt_saved_baseline(config: StructuredDoc, *, preserve_draft: bool)`, `show_load_error(message, reason="load-error")`, `show_config_error(message, detail="")`, `show_field_issues(issues: tuple[FieldIssue, ...])`, `set_validation_result(result: ValidationResult)`, `show_auth_warnings(warnings: tuple[str, ...])`, `set_launcher_gate(result: LauncherProbeResult | None)`, `set_save_in_progress(saving: bool)`, `update_service_status(status: ServiceStatus)`, `log_view: LogViewWidget` property.
- Produces: `AppDetailView.adopt_saved_baseline(config: AppAIConfig, *, preserve_draft: bool)`, `.show_config_error(message: str, detail: str = "")`, `.set_save_in_progress(saving: bool)`; both AppDetailView payload signals become object while its existing fetch/config behavior stays compatible.
- Produces: `ReviewChangesDialog(before: bytes, after: bytes, path: Path, parent=None)`; `BlastRadiusDialog(matches: tuple[DependentMatch, ...], parent=None).selected_app_ids() -> tuple[str, ...]`; `StaleDocumentDialog(path: Path, parent=None).choice() -> Literal["reload", "diff", "cancel"]`; `TransactionReportDialog(report: TransactionReport, parent=None)`. Dialogs never write files.

- [ ] **Step 1: Write widget and dialog tests.**

```python
# tests/test_structured_view.py
import json
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QLineEdit, QPlainTextEdit, QPushButton, QTabWidget
import pytest
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.structured_config import load, render, effective_mutations
from ai_manager.config.structured_models import LauncherProbeResult, ValidationResult
from ai_manager.config.models import ServiceRunState, ServiceStatus
from ai_manager.ui.structured_config_view import StructuredConfigView
from ai_manager.ui.config_dialogs import ReviewChangesDialog, BlastRadiusDialog, StaleDocumentDialog


def make_view(qtbot, workspace, app_id="chat2api"):
    meta = get_managed_apps(workspace)[app_id]
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    changes, saves, fetches = [], [], []
    view.config_changed.connect(lambda *args: changes.append(args))
    view.save_requested.connect(lambda *args: saves.append(args))
    view.fetch_models_requested.connect(lambda *args: fetches.append(args))
    view.load_config(load(meta.config_kind, meta.relative_path / meta.config_file_name))
    return view, changes, saves, fetches


def test_kind_forms_tabs_status_and_saved_port(qtbot, five_app_workspace):
    for app_id, group in (("chat2api", "Server"), ("file-bridge", "Save Location && Server")):
        view, changed, saves, fetches = make_view(qtbot, five_app_workspace, app_id)
        assert group in [g.title() for g in view.findChildren(QGroupBox)]
        assert [view._tabs.tabText(i) for i in range(2)] == ["Configuration", "Logs"]
        assert view.log_view.service_id == app_id
        assert changed == saves == fetches == []
        if app_id == "file-bridge":
            assert set(view._fields) == {("save_root",), ("max_text_bytes",), ("port",)}
            assert not hasattr(view, "_table") and not hasattr(view, "_fetch_btn")
        view.update_service_status(ServiceStatus(service_id=app_id, state=ServiceRunState.RUNNING, pid=104, log_path="/tmp/fixture.log"))
        view.update_service_status(ServiceStatus(service_id=app_id, state=ServiceRunState.STOPPED))
        assert str(view.log_view._reader.path) == "/tmp/fixture.log" and changed == []


def test_gate_restricts_only_listener_and_typing_preserves_absent_options(qtbot, five_app_workspace):
    view, changed, saves, fetches = make_view(qtbot, five_app_workspace)
    assert view._gate_label.text() == "Checking whether launcher honors config…"
    assert not view._fields[("server", "port")].isEnabled()
    assert view._fields[("server", "auth_token_env")].isEnabled()
    view.set_launcher_gate(LauncherProbeResult(False, "fixture failure", stderr="fixture stderr\n"))
    assert view._gate_label.text() == "launcher does not honor config — install Target B first"
    assert view._table.isEnabled() and view._save_only_btn.isEnabled()
    view.set_launcher_gate(LauncherProbeResult(True))
    port = view._fields[("server", "port")]
    port.edit.setText("8123")
    assert len(changed) == 1 and "Port 8000" in view._title_label.text()
    assert "options" not in json.loads(render("chat2api", view.get_current_draft()))["models"]["echo-1"]
    view._emit_save(False)
    view._emit_save(True)
    assert [args[2] for args in saves] == [False, True] and fetches == []


def test_row_edit_invalid_raw_secret_flags_and_provider_warning(qtbot, five_app_workspace):
    view, changed, saves, fetches = make_view(qtbot, five_app_workspace)
    view._add_model()
    new_id = view._model.rows[-1].id
    assert view.get_current_draft().input_issues
    view._table.item(view._table.rowCount() - 1, 0).setText("new-echo")
    combo = view._table.cellWidget(view._table.rowCount() - 1, 1)
    combo.setCurrentText("echo")
    view._expand_model(new_id)
    prefix = view._option_fields[("models", "new-echo", "options", "prefix")]
    prefix.present.setChecked(True)
    prefix.edit.setText("hello")
    view._on_raw_options_changed(new_id, "{broken")
    assert view.get_current_draft().raw_option_edits["new-echo"] == "{broken"
    view._on_raw_options_changed(new_id, '{"future":{"keep":[1,"雪"]}}')
    view._on_provider_changed(new_id, "browser")
    assert view._provider_warning.text() == "Provider changed. Existing options were kept and may not apply to the new provider."
    account = view._option_fields[("models", "new-echo", "options", "account")]
    account.present.setChecked(True)
    account.edit.setText("synthetic-account")
    committed_draft = view.get_current_draft()
    count = len(changed)
    account.reveal.setChecked(True)
    account.reveal.setChecked(False)
    assert len(changed) == count and view.get_current_draft() == committed_draft
    assert account.changed
    view._remove_model(view._model.rows[0].id)
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert list(tree["models"]) == ["new-echo"]
    assert tree["models"]["new-echo"]["options"]["account"] == "synthetic-account"
    assert tree["models"]["new-echo"]["options"]["future"] == {"keep": [1, "雪"]}
    assert saves == fetches == []


def test_load_secret_reveal_no_change_and_exact_plain_error_details(qtbot, five_app_workspace):
    path = five_app_workspace / "chat2api/config.json"
    data = json.loads(path.read_bytes())
    data["models"]["echo-1"]["options"] = {"account": "synthetic-account", "password": "synthetic-password"}
    path.write_text(json.dumps(data))
    view, changed, saves, fetches = make_view(qtbot, five_app_workspace)
    row = view._model.rows[0].id
    view._expand_model(row)
    field = view._option_fields[("models", "echo-1", "options", "password")]
    assert field.edit.echoMode() == QLineEdit.EchoMode.Password and not field.changed
    field.reveal.setChecked(True)
    field.reveal.setChecked(False)
    assert not field.changed and effective_mutations(view.get_current_draft()) == () and changed == []
    field.edit.setText("")
    assert effective_mutations(view.get_current_draft())[0].value == ""
    draft = view.get_current_draft()
    stderr = '<tag>synthetic & literal stderr</tag>\n'
    view.show_config_error("Service validator rejected the configuration; nothing was saved.", stderr)
    assert view._details.toPlainText() == stderr and view.get_current_draft() == draft
    assert saves == fetches == []


def test_review_stale_and_blast_dialogs_are_read_only(qtbot, five_app_workspace):
    from ai_manager.config.blast_radius import find_affected_dependents
    from dataclasses import replace
    from ai_manager.config.structured_models import Mutation
    view, changed, saves, fetches = make_view(qtbot, five_app_workspace)
    before = view.get_current_draft()
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    original = before.path.read_bytes()
    dialog = ReviewChangesDialog(before.raw_bytes, render("chat2api", after), before.path)
    qtbot.addWidget(dialog)
    diff = dialog.findChild(QPlainTextEdit).toPlainText()
    assert '-    "port": 8000' in diff and '+    "port": 8123' in diff
    matches = find_affected_dependents(get_managed_apps(five_app_workspace), before, after)
    blast = BlastRadiusDialog(matches)
    qtbot.addWidget(blast)
    assert blast.selected_app_ids() == ()
    blast._checks["textkit"].setChecked(True)
    assert blast.selected_app_ids() == ("textkit",)
    stale = StaleDocumentDialog(before.path)
    qtbot.addWidget(stale)
    assert stale.choice() == "cancel"
    assert {b.text() for b in stale.findChildren(QPushButton)} == {"Reload", "Show diff", "Cancel"}
    assert before.path.read_bytes() == original and changed == saves == fetches == []
```

- [ ] **Step 2: Confirm the new view/dialog imports fail.**

```bash
PYTHONPATH=src pytest tests/test_structured_view.py -q
```

- [ ] **Step 3: Implement dialogs with plain-text details and opt-in selection.**

```python
# ui/config_dialogs.py
from __future__ import annotations
import difflib
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout
from ai_manager.config.structured_models import DependentMatch, TransactionReport
from ai_manager.ui.mnemonic import escape_mnemonic


def _label(text, parent):
    label = QLabel(parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setWordWrap(True)
    return label


class ReviewChangesDialog(QDialog):
    def __init__(self, before: bytes, after: bytes, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Changes")
        self.resize(850, 550)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(str(path), self))
        detail = QPlainTextEdit(self)
        detail.setReadOnly(True)
        detail.setPlainText("".join(difflib.unified_diff(before.decode("utf-8", errors="replace").splitlines(keepends=True), after.decode("utf-8", errors="replace").splitlines(keepends=True), fromfile="saved", tofile="draft")))
        layout.addWidget(detail)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class BlastRadiusDialog(QDialog):
    def __init__(self, matches: tuple[DependentMatch, ...], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update dependent API base URLs?")
        self._checks = {}
        self._primary_only = False
        layout = QVBoxLayout(self)
        old_url, new_url = matches[0].old_api_base, matches[0].new_api_base
        layout.addWidget(_label(f"Changing chat2api from {old_url} to {new_url} affects these apps. Only checked apps will have ai.api_base updated.", self))
        for match in matches:
            checkbox = QCheckBox(escape_mnemonic(f"{match.meta.display_name}: {match.old_api_base} → {match.new_api_base}"), self)
            checkbox.setChecked(False)
            self._checks[match.meta.id] = checkbox
            layout.addWidget(checkbox)
            if match.auth_warning:
                layout.addWidget(_label(match.auth_warning, self))
        actions = QHBoxLayout()
        selected = QPushButton("Save with Selected Updates", self)
        selected.clicked.connect(self.accept)
        alone = QPushButton("Save chat2api Only", self)
        alone.clicked.connect(self._save_alone)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        for button in (selected, alone, cancel):
            actions.addWidget(button)
        layout.addLayout(actions)

    def _save_alone(self):
        self._primary_only = True
        self.accept()

    def selected_app_ids(self) -> tuple[str, ...]:
        return () if self._primary_only else tuple(app_id for app_id, checkbox in self._checks.items() if checkbox.isChecked())


class StaleDocumentDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Changed")
        self._choice = "cancel"
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Configuration changed on disk; save refused.", self))
        layout.addWidget(_label(str(path), self))
        layout.addWidget(_label("Reload discards this app's unsaved draft.", self))
        actions = QHBoxLayout()
        for text, choice in (("Reload", "reload"), ("Show diff", "diff"), ("Cancel", "cancel")):
            button = QPushButton(text, self)
            button.clicked.connect(lambda checked=False, value=choice: self._choose(value))
            actions.addWidget(button)
        layout.addLayout(actions)

    def _choose(self, choice):
        self._choice = choice
        self.accept()

    def choice(self):
        return self._choice


class TransactionReportDialog(QDialog):
    def __init__(self, report: TransactionReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Save Failed")
        layout = QVBoxLayout(self)
        if report.restore_failures:
            summary = "Save failed and some files could not be restored. Review every path below before restarting services."
        else:
            summary = {"backups": "Could not create all backups; no configuration files were changed.", "stage": "Could not stage configuration files; no configuration files were changed."}.get(report.phase, "Save failed; configuration files were restored from backups.")
        layout.addWidget(_label(summary, self))
        details = QPlainTextEdit(self)
        details.setReadOnly(True)
        lines = [f"{path}: {state}" for path, state in report.files.items()]
        lines += [f"Backup {path}: {backup}" for path, backup in report.backups.items()]
        lines += [f"{path}: {reason}" for path, reason in report.restore_failures.items()]
        if report.error:
            lines.append(report.error)
        if report.restore_failures:
            lines.append("Reload affected files after resolving the reported recovery failures.")
        details.setPlainText("\n".join(lines))
        layout.addWidget(details)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        layout.addWidget(close)
```

- [ ] **Step 4: Add the reusable explicit-presence control to structured_config_view.py.** Use QLineEdit for integers so invalid loaded values cannot be clamped. The private `changed` flag records value edits; reveal never touches it.

```python
# ui/structured_config_view.py
from __future__ import annotations
import copy
import json
import re
from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget
from ai_manager.config.config_errors import ConfigError, ConfigValidationError, MissingExampleError, UnknownConfigKindError
from ai_manager.config.models import ModelFetchRequest, ServiceStatus
from ai_manager.config.structured_config import effective_mutations, load_example, render
from ai_manager.config.structured_models import FieldIssue, LauncherProbeResult, StructuredDoc, ValidationResult
from ai_manager.config.structured_schema import FILE_BRIDGE_FIELDS, PROVIDER_OPTIONS, SECRET_OPTION_KEYS, SERVER_FIELDS
from ai_manager.services.supervisor import default_log_path
from ai_manager.ui.config_dialogs import ReviewChangesDialog, _label
from ai_manager.ui.mnemonic import escape_mnemonic
from ai_manager.ui.structured_editor_model import StructuredEditorModel
from ai_manager.ui.widgets.log_view import LogViewWidget
from ai_manager.ui.widgets.status_badge import StatusBadge


class PresenceControl(QWidget):
    written = pyqtSignal(bool, object)

    def __init__(self, control, present, value, *, default=None, parent=None):
        super().__init__(parent)
        self.control, self.changed, self._loading = control, False, True
        self._value = copy.deepcopy(value if present else default)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.present = QCheckBox("Present", self)
        self.present.setChecked(present)
        layout.addWidget(self.present)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Absent")
        self.null = None
        if control == "nullable-text":
            self.null = QCheckBox("Authentication disabled", self)
            self.null.setChecked(present and value is None)
            layout.addWidget(self.null)
            self.null.toggled.connect(self._write)
        expected = str if control in ("text", "directory", "nullable-text", "secret") else int if control == "integer" else bool
        self._raw_type = self._value is not None and (type(self._value) is not expected if expected in (int, bool) else not isinstance(self._value, expected))
        text = "" if self._value is None else json.dumps(self._value, ensure_ascii=False) if self._raw_type else str(self._value).lower() if type(self._value) is bool else str(self._value)
        self.edit.setText(text)
        if control == "secret":
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.edit, 1)
        self.reveal = QCheckBox("Reveal", self)
        self.reveal.setVisible(control == "secret")
        self.reveal.toggled.connect(lambda visible: self.edit.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        layout.addWidget(self.reveal)
        if control == "directory":
            pick = QPushButton("Choose Directory", self)
            pick.clicked.connect(self._pick)
            layout.addWidget(pick)
        self.present.toggled.connect(self._write)
        self.edit.textChanged.connect(self._write)
        self._loading = False
        self._enabled_value()

    def _pick(self):
        directory = QFileDialog.getExistingDirectory(self, "Save root", self.edit.text())
        if directory:
            self.present.blockSignals(True)
            self.present.setChecked(True)
            self.present.blockSignals(False)
            self.edit.setText(directory)

    def _enabled_value(self):
        self.edit.setEnabled(self.present.isChecked() and not (self.null is not None and self.null.isChecked()))
        if self.null is not None:
            self.null.setEnabled(self.present.isChecked())

    def _write(self, *args):
        self._enabled_value()
        if self._loading:
            return
        self.changed = True
        text = self.edit.text()
        value = text
        if self.null is not None and self.null.isChecked():
            value = None
        elif self._raw_type:
            try:
                value = json.loads(text)
            except ValueError:
                value = text
        elif self.control == "integer" and re.fullmatch(r"[+-]?[0-9]+", text):
            value = int(text)
        elif self.control == "boolean" and text in ("true", "false"):
            value = text == "true"
        self.written.emit(self.present.isChecked(), value)
```

- [ ] **Step 5: Add the grouped view and delegate edits to the pure model.**

```python
class StructuredConfigView(QWidget):
    save_requested = pyqtSignal(str, object, bool)
    restart_requested = pyqtSignal(str)
    config_changed = pyqtSignal(str, object)
    fetch_models_requested = pyqtSignal(ModelFetchRequest)

    def __init__(self, app_meta, parent=None):
        super().__init__(parent)
        if app_meta.config_kind not in ("chat2api", "file-bridge"):
            raise UnknownConfigKindError(app_meta.config_kind)
        self.app_meta = app_meta
        self._model, self._baseline = None, None
        self._known_log_path, self._gate = None, None
        self._saving, self._load_failed = False, False
        self._fields, self._option_fields = {}, {}
        self._row_issue_widgets = {}
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self._title_label = _label(f"{app_meta.display_name} (Port {app_meta.default_port})", self)
        self._status_badge = StatusBadge(self)
        self._restart_btn = QPushButton("Restart Service Only", self)
        self._restart_btn.clicked.connect(lambda: self.restart_requested.emit(self.app_meta.id))
        header.addWidget(self._title_label, 1)
        header.addWidget(self._status_badge)
        header.addWidget(self._restart_btn)
        layout.addLayout(header)
        target = Path(app_meta.relative_path / app_meta.config_file_name).absolute()
        path_text = f"Editing {target}"
        if app_meta.config_kind == "chat2api":
            path_text += ". If CHAT2API_CONFIG is set externally for the supervised service, ai-manager edits a different file."
        layout.addWidget(_label(path_text, self))
        self._validation_label = _label("Not validated since load.", self)
        self._notice_label = _label("", self)
        self._gate_label = _label("", self)
        self._auth_label = _label("", self)
        for label in (self._validation_label, self._notice_label, self._gate_label, self._auth_label):
            layout.addWidget(label)
        self._details_toggle = QToolButton(self)
        self._details_toggle.setText("Validator details")
        self._details_toggle.setCheckable(True)
        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.hide()
        self._details_toggle.toggled.connect(self._details.setVisible)
        layout.addWidget(self._details_toggle)
        layout.addWidget(self._details)
        self._tabs = QTabWidget(self)
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        self._form = QWidget(scroll)
        self._form_layout = QVBoxLayout(self._form)
        scroll.setWidget(self._form)
        page_layout.addWidget(scroll, 1)
        footer = QFrame(page)
        footer.setObjectName("footerActionBar")
        actions = QHBoxLayout(footer)
        self._dirty_label = _label("", self)
        self._create_btn = QPushButton("Create from Example", self)
        self._create_btn.clicked.connect(self._create_from_example)
        self._review_btn = QPushButton("Review Changes", self)
        self._review_btn.clicked.connect(self._review_changes)
        self._save_only_btn = QPushButton("Save Config Only", self)
        self._save_only_btn.clicked.connect(lambda: self._emit_save(False))
        self._save_restart_btn = QPushButton("Save and Restart", self)
        self._save_restart_btn.clicked.connect(lambda: self._emit_save(True))
        for widget in (self._dirty_label, self._create_btn, self._review_btn, self._save_only_btn, self._save_restart_btn):
            actions.addWidget(widget)
        page_layout.addWidget(footer)
        self._log_view_widget = LogViewWidget(app_meta.id, self)
        self._tabs.addTab(page, "Configuration")
        self._tabs.addTab(self._log_view_widget, "Logs")
        layout.addWidget(self._tabs, 1)
        self.set_launcher_gate(None)
        self._controls()

    @property
    def log_view(self):
        return self._log_view_widget

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def load_config(self, config):
        self._baseline = copy.deepcopy(config)
        self._model = StructuredEditorModel(config)
        self._load_failed = False
        self._fields, self._option_fields = {}, {}
        self._row_issue_widgets = {}
        self._details.clear()
        self._clear(self._form_layout)
        chat = self.app_meta.config_kind == "chat2api"
        fields = SERVER_FIELDS if chat else FILE_BRIDGE_FIELDS
        group = QGroupBox(escape_mnemonic("Server" if chat else "Save Location & Server"), self._form)
        form = QFormLayout(group)
        values = self._model.tree.get("server", {}) if chat else self._model.tree
        defaults = {"host": "127.0.0.1", "port": 8000, "auth_token_env": "CHAT2API_TOKEN"} if chat else {"save_root": "~", "max_text_bytes": 1048576, "port": 8964}
        for spec in fields:
            address = ("server", spec.key) if chat else (spec.key,)
            field = PresenceControl(spec.control, spec.key in values, values.get(spec.key), default=defaults[spec.key], parent=group)
            field.setToolTip(spec.annotation)
            field.written.connect(lambda present, value, at=address: self._on_field_changed(at, present, value))
            self._fields[address] = field
            form.addRow(_label(spec.label + (f" ({spec.annotation})" if spec.annotation else ""), group), field)
        self._form_layout.addWidget(group)
        if chat:
            models = QGroupBox("Models", self._form)
            box = QVBoxLayout(models)
            self._table = QTableWidget(0, 4, models)
            self._table.setHorizontalHeaderLabels(["Name", "Provider", "Options", "Secrets"])
            self._table.cellChanged.connect(self._name_changed)
            box.addWidget(self._table)
            add = QPushButton("Add Model", models)
            add.clicked.connect(self._add_model)
            box.addWidget(add)
            self._provider_warning = _label("", models)
            box.addWidget(self._provider_warning)
            self._options_box = QWidget(models)
            self._options_layout = QVBoxLayout(self._options_box)
            box.addWidget(self._options_box)
            self._form_layout.addWidget(models)
            self._populate_rows()
        self._form_layout.addStretch(1)
        port = values.get("port", defaults["port"]) if config.existed else self.app_meta.default_port
        if type(port) is not int or not 1 <= port <= 65535:
            port = self.app_meta.default_port
            self.show_field_issues((FieldIssue(("server", "port") if chat else ("port",), "Port must be an integer from 1 to 65535."),))
        self._title_label.setText(f"{self.app_meta.display_name} (Port {port})")
        self._validation_label.setText("Not validated since load.")
        reasons = {"missing-config": "Configuration file is missing. Choose Create from Example to start a draft.", "non-writable": "Configuration is not writable; editing is disabled.", "yaml-anchors-aliases": "YAML anchors or aliases are present; editing is disabled to preserve linked values."}
        self._notice_label.setText(reasons.get(config.read_only_reasons[0], "") if config.read_only_reasons else "")
        if "yaml-anchors-aliases" in config.read_only_reasons:
            self._details.setPlainText(config.raw_bytes.decode("utf-8", errors="replace"))
        self._controls()

    def _populate_rows(self):
        self._row_issue_widgets = {}
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._model.rows))
        for index, row in enumerate(self._model.rows):
            name = QTableWidgetItem(row.name)
            name.setData(Qt.ItemDataRole.UserRole, row.id)
            self._table.setItem(index, 0, name)
            providers = QComboBox(self._table)
            providers.addItem("")
            providers.addItems(list(PROVIDER_OPTIONS))
            if row.route.get("provider") not in PROVIDER_OPTIONS and row.route.get("provider"):
                providers.addItem(str(row.route["provider"]))
            providers.setCurrentText(row.route.get("provider", ""))
            providers.currentTextChanged.connect(lambda value, uid=row.id: self._on_provider_changed(uid, value))
            self._table.setCellWidget(index, 1, providers)
            expand = QToolButton(self._table)
            expand.setText("Options")
            expand.clicked.connect(lambda checked=False, uid=row.id: self._expand_model(uid))
            self._table.setCellWidget(index, 2, expand)
            self._row_issue_widgets[("models", row.name)] = expand
            self._row_issue_widgets[("models", row.name, "provider")] = providers
            count = len(SECRET_OPTION_KEYS.intersection(row.route.get("options", {})))
            self._table.setCellWidget(index, 3, _label(f"{count} present", self._table))
        self._table.blockSignals(False)

    def _name_changed(self, row, column):
        if column == 0:
            item = self._table.item(row, 0)
            self._model.rename_model(item.data(Qt.ItemDataRole.UserRole), item.text())
            self._on_changed()

    def _add_model(self, checked=False):
        uid = self._model.add_model()
        self._populate_rows()
        self._expand_model(uid)
        self._on_changed()

    def _remove_model(self, row_id):
        self._model.remove_model(row_id)
        self._populate_rows()
        self._clear(self._options_layout)
        self._option_fields = {}
        self._on_changed()

    def _expand_model(self, row_id):
        self._row_issue_widgets = {key: widget for key, widget in self._row_issue_widgets.items() if not (len(key) == 3 and key[-1] == "options")}
        self._clear(self._options_layout)
        self._option_fields = {}
        row = self._model.row(row_id)
        panel = QWidget(self._options_box)
        form = QFormLayout(panel)
        specs = list(PROVIDER_OPTIONS.get(row.route.get("provider"), ()))
        known = {spec.key for spec in specs}
        from ai_manager.config.structured_schema import OptionSpec
        specs += [OptionSpec(key, "secret") for key in row.route.get("options", {}) if key in SECRET_OPTION_KEYS and key not in known]
        for spec in specs:
            options = row.route.get("options", {})
            field = PresenceControl(spec.control, spec.key in options, options.get(spec.key), parent=panel)
            field.written.connect(lambda present, value, uid=row_id, key=spec.key: self._option_changed(uid, key, present, value))
            address = ("models", row.name, "options", spec.key)
            self._option_fields[address] = field
            form.addRow(_label(spec.key, panel), field)
        raw_toggle = QToolButton(panel)
        raw_toggle.setText("Raw options")
        raw_toggle.setCheckable(True)
        raw = QPlainTextEdit(panel)
        self._row_issue_widgets[("models", row.name, "options")] = raw
        raw.setPlainText(row.raw_text if row.raw_text is not None else json.dumps(self._model.raw_options(row_id), indent=2, ensure_ascii=False))
        raw.hide()
        raw_toggle.toggled.connect(raw.setVisible)
        raw.textChanged.connect(lambda uid=row_id, edit=raw: self._on_raw_options_changed(uid, edit.toPlainText()))
        form.addRow(raw_toggle)
        form.addRow(raw)
        remove = QPushButton("Remove Model", panel)
        remove.clicked.connect(lambda checked=False, uid=row_id: self._remove_model(uid))
        form.addRow(remove)
        self._options_layout.addWidget(panel)

    def _on_provider_changed(self, row_id, provider):
        self._model.set_provider(row_id, provider)
        self._provider_warning.setText("Provider changed. Existing options were kept and may not apply to the new provider.")
        self._expand_model(row_id)
        self._on_changed()

    def _option_changed(self, row_id, key, present, value):
        self._model.set_option(row_id, key, present=present, value=value)
        self._on_changed()

    def _on_raw_options_changed(self, row_id, text):
        self._model.set_raw_options(row_id, text)
        self._on_changed()

    def _on_field_changed(self, address, present, value):
        self._model.set_field(address, present=present, value=value)
        self._on_changed()

    def _on_changed(self):
        draft = self.get_current_draft()
        try:
            effective_mutations(draft)
            self.show_field_issues(())
        except ConfigValidationError as exc:
            self.show_field_issues(exc.issues)
        self.config_changed.emit(self.app_meta.id, draft)

    def get_current_draft(self):
        if self._model is None:
            raise ConfigError("Create a draft from the example before saving.")
        return self._model.draft()

    def adopt_saved_baseline(self, config, *, preserve_draft):
        if preserve_draft:
            self._baseline = copy.deepcopy(config)
        else:
            self.load_config(config)

    def _emit_save(self, restart):
        if not self._saving:
            self.save_requested.emit(self.app_meta.id, self.get_current_draft(), restart)

    def _review_changes(self):
        try:
            draft = self.get_current_draft()
            ReviewChangesDialog(self._baseline.raw_bytes, render(draft.kind, draft), draft.path, self).exec()
        except ConfigError as exc:
            self.show_config_error(str(exc))

    def _create_from_example(self):
        try:
            path = self.app_meta.relative_path / self.app_meta.config_file_name
            draft = load_example(self.app_meta.config_kind, path, self.app_meta.relative_path / self.app_meta.example_config_file_name)
            self.load_config(draft)
        except ConfigError as exc:
            self.show_config_error(exc.detail if isinstance(exc, MissingExampleError) else str(exc))
        else:
            self.config_changed.emit(self.app_meta.id, draft)

    def show_load_error(self, message, reason="load-error"):
        self._load_failed = True
        self.show_config_error(message)
        self._controls()

    def show_config_error(self, message, detail=""):
        self._notice_label.setText(message)
        self._details.setPlainText(detail)

    def show_field_issues(self, issues):
        fields = {**self._row_issue_widgets, **self._fields, **self._option_fields}
        for field in fields.values():
            field.setStyleSheet("")
        for issue in issues:
            field = fields.get(issue.address)
            if field is None:
                prefixes = [prefix for prefix in fields if issue.address[:len(prefix)] == prefix]
                if prefixes:
                    field = fields[max(prefixes, key=len)]
            if field is not None:
                field.setStyleSheet("border: 1px solid #ef4444;")
                field.setToolTip(issue.message)
                if isinstance(field, QPlainTextEdit):
                    field.show()
        self._notice_label.setText("\n".join(dict.fromkeys(issue.message for issue in issues)))

    def set_validation_result(self, result):
        self._validation_label.setText(result.notice)
        self._details.setPlainText(result.detail)

    def show_auth_warnings(self, warnings):
        self._auth_label.setText("\n".join(warnings))

    def set_launcher_gate(self, result):
        self._gate = result
        if self.app_meta.config_kind == "chat2api":
            self._gate_label.setText("Checking whether launcher honors config…" if result is None else "launcher honors config — host/port editable" if result.passed else "launcher does not honor config — install Target B first")
            if result is not None and not result.passed:
                self._details.setPlainText(result.detail + ("\n" if result.detail and result.stderr else "") + result.stderr)
        self._controls()

    def set_save_in_progress(self, saving):
        self._saving = saving
        if saving:
            self._notice_label.setText("Saving configuration…")
        self._controls()

    def _controls(self):
        initialized = self._model is not None and not self._load_failed
        doc = self._model.baseline if self._model else None
        writable = initialized and not doc.read_only_reasons and (doc.existed or doc.create_requested)
        self._form.setEnabled(bool(writable and not self._saving))
        for widget in (self._save_only_btn, self._save_restart_btn, self._review_btn):
            widget.setEnabled(bool(writable and not self._saving))
        self._create_btn.setVisible(bool(doc and not doc.existed and not doc.create_requested))
        self._create_btn.setEnabled(not self._saving)
        if self.app_meta.config_kind == "chat2api":
            for key in ("host", "port"):
                if ("server", key) in self._fields:
                    self._fields[("server", key)].setEnabled(bool(writable and not self._saving and self._gate is not None and self._gate.passed))

    def update_service_status(self, status):
        if status.log_path:
            self._known_log_path = str(status.log_path)
        self._log_view_widget.set_log_path(self._known_log_path or str(default_log_path(self.app_meta.id)))
        self._log_view_widget.set_service_state(status.state)
        self._status_badge.set_status(status.state, status.pid)
```

For `adopt_saved_baseline(..., preserve_draft=True)`, retain widgets but rebase their current mutations onto the new StructuredDoc before a later save; the current feature calls this path only on LLM dependents, so add no disk read. Row expansion and reveal never call `_on_changed`. The prescribed `_row_issue_widgets` mapping and longest-prefix lookup highlight a row's options control when collapsed and its raw editor when expanded; show the raw editor for a raw-options error.

- [ ] **Step 6: Add the LLM common adapter.** Change its two payload signals to object. Add `QPlainTextEdit` and Qt imports, and a plain-text `_config_error_label`/read-only `_config_error_details` below its existing header. Retain references `_provider_group`, `_model_group` when those existing groups are created so saving can disable editing without disabling Logs/restart. Add:

```python
    def adopt_saved_baseline(self, config: AppAIConfig, *, preserve_draft: bool) -> None:
        self._current_config = config.model_copy(deep=True)
        if not preserve_draft:
            self.load_config(config)

    def show_config_error(self, message: str, detail: str = "") -> None:
        self._config_error_label.setText(message)
        self._config_error_details.setPlainText(detail)
        self._config_error_details.setVisible(bool(detail))

    def set_save_in_progress(self, saving: bool) -> None:
        self._provider_group.setEnabled(not saving)
        self._model_group.setEnabled(not saving)
        self._save_only_btn.setEnabled(not saving)
        self._save_restart_btn.setEnabled(not saving)
```

Construct those details explicitly after `main_layout.addWidget(header_frame)`:

```python
        self._config_error_label = QLabel(self)
        self._config_error_label.setTextFormat(Qt.TextFormat.PlainText)
        self._config_error_details = QPlainTextEdit(self)
        self._config_error_details.setReadOnly(True)
        self._config_error_details.hide()
        main_layout.addWidget(self._config_error_label)
        main_layout.addWidget(self._config_error_details)
```

- [ ] **Step 7: Run widget, pure model, mnemonic and legacy view tests.**

```bash
PYTHONPATH=src pytest tests/test_structured_view.py tests/test_structured_editor_model.py tests/test_app_views.py tests/test_mnemonic.py -q
```

Expected: new standalone structured tests and existing LLM-only assertions pass; MainWindow-specific mnemonic/setup tests may require Task 12's discriminator migration and must pass in that task before integration. Do not remove an assertion to hide an intermediate MainWindow failure.

- [ ] **Step 8: Commit.**

```bash
git add src/ai_manager/ui/structured_config_view.py src/ai_manager/ui/structured_editor_model.py src/ai_manager/ui/config_dialogs.py src/ai_manager/ui/app_detail_view.py tests/test_structured_view.py
git commit -m "feat(ui): add structured forms, masked options and recovery dialogs"
```

## Task 12: Coordinate five views, queued jobs, reconciliation and restart outcomes

**Implementer tier:** Advanced

**Files:**

- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/main_window.py:1-44`, `:84-87`, `:124-126`, `:187-266`, `:307-309`, `:399-405` (imports, state, dispatch/load/save/fetch/completion helpers, dirty and restart outcome).
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/ui/app_sidebar.py:20-22`, `:43-50` (saved-port cache).
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/src/ai_manager/config/presets.py:16` (CHAT2API_TOKEN correction).
- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_structured_main_window.py`.
- Modify/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_app_views.py:1-200`, `/data/home/guest/Development/ai/ai-manager/tests/test_main_window.py:1-128`, `/data/home/guest/Development/ai/ai-manager/tests/test_main_window_tray.py:1-400`, `/data/home/guest/Development/ai/ai-manager/tests/test_mnemonic.py:200-272`, `/data/home/guest/Development/ai/ai-manager/tests/test_supervisor.py:1-160`, `/data/home/guest/Development/ai/ai-manager/tests/test_e2e_integration.py:1-30` (extend regression tests; never delete lifecycle assertions).
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/README.md:1-180` (supported apps, controls, delivery prerequisite and limits).

**Interfaces:**

- Consumes: both Task 11 QWidget adapters with `save_requested(str, object, bool)`, `restart_requested(str)`, `config_changed(str, object)`, `fetch_models_requested(ModelFetchRequest)`, `load_config(object)`, `get_current_draft()`, `adopt_saved_baseline(config, *, preserve_draft: bool)`, `show_config_error(message, detail="")`, `set_save_in_progress(saving)`, `update_service_status(status)`, `.log_view`. Structured-only calls: `show_load_error(message, reason="load-error")`, `show_field_issues(issues)`, `set_launcher_gate(result | None)`, `set_validation_result(result)`, `show_auth_warnings(tuple[str, ...])`. LLM-only call: `on_model_fetch_response(response)`.
- Consumes: `StructuredSaveJob(meta, draft, dependents=())` and `LauncherProbeJob(meta)` QRunnables, owned `.signals.save_finished(str, object)`, `.save_failed(str, object)`, `.probe_finished(str, object)`; `ModelFetchWorker(request).signals.finished(ModelFetchResponse)`; `QThreadPool.start(worker)`; common dialogs from Task 11.
- Consumes: `structured_config.load(kind, path) -> StructuredDoc`, `render(kind, doc) -> bytes`, `_candidate(doc) -> mapping`; `blast_radius.find_affected_dependents(apps, before, after) -> tuple[DependentMatch, ...]`, `auth_mismatch_warning(config, auth_env) -> str | None`, `endpoint(doc) -> tuple[str, int, str]`, `urls_match(a, b) -> bool`; `validate_in_process(kind, candidate, *, config_path, app_dir) -> None`.
- Consumes: `SaveResult(document, transaction, validation, saved_dependents)`; typed ConfigError subclasses; `SupervisorManager.restart_service(app_id)` emits `action_completed(action: str, success: bool, message: str)` where action is `restart {app_id}` or immediate busy failure `restart`.
- Produces: all MainWindow methods in spec §8.6, plus `_start_launcher_probes`, `_update_configured_port`, `_check_payload`, `_set_dirty_indicator`, `_request_saved_restart`; session-only `_launcher_gate_cache: dict[Path, LauncherProbeResult | None]`, `_probe_jobs: dict[Path, LauncherProbeJob]`, `_save_jobs: dict[str, StructuredSaveJob]`, `_model_workers: dict[int, ModelFetchWorker]`, `_pending_restarts: dict[str, bool]`, `_save_restart_pending: set[str]`.
- Produces: `AppSidebar.update_configured_port(app_id: str, port: int | None)` with strict int/range checks and cached saved port unaffected by dirty/status repaint. No view computes its own dirty state.

- [ ] **Step 1: Write integration tests with controlled worker completion.**

```python
# tests/test_structured_main_window.py
import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PyQt6.QtCore import QThread, Qt
from PyQt6.QtWidgets import QDialog, QMessageBox
from ai_manager.config.config_errors import ConfigError, ConfigValidationError, ServiceValidationError, ServiceValidationTimeout, StaleDocumentError, TransactionError, UnknownConfigKindError
from ai_manager.config.models import AppAIConfig, ModelFetchRequest, ModelFetchResponse, ServiceRunState, ServiceStatus, SupervisorStatus
from ai_manager.config.structured_config import load, render
from ai_manager.config.structured_models import FieldIssue, LauncherProbeResult, Mutation, SaveResult, TransactionReport, ValidationResult
from ai_manager.ui import main_window as mw
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.structured_config_view import StructuredConfigView


@pytest.fixture
def window(qtbot, five_app_workspace, monkeypatch):
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a: None)
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a: None)
    monkeypatch.setattr(mw.BlastRadiusDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mw.BlastRadiusDialog, "selected_app_ids", lambda self: ())
    result = mw.MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(result)
    result.thread_pool = MagicMock()
    result.supervisor_manager.restart_service = MagicMock()
    return result


def port_draft(window, port=8123):
    doc = window._saved_configs["chat2api"]
    return replace(doc, mutations=(Mutation(("server", "port"), "set", port),))


def run_save(qtbot, window, monkeypatch, app_id="chat2api", draft=None, restart=False):
    import ai_manager.services.service_validation as validation
    monkeypatch.setattr(validation, "validate_candidate", lambda *a: ValidationResult("manager-only", "validated by ai-manager only — service validator unavailable"))
    draft = draft or window._draft_configs[app_id]
    window._on_config_changed(app_id, draft)
    window._on_save_requested(app_id, draft, restart)
    job = window._save_jobs[app_id]
    job.run()
    qtbot.waitUntil(lambda: app_id not in window._save_jobs)


def test_five_views_saved_ports_dirty_revert_and_kind_refusal(window):
    assert len(window.views) == 5 and not window.has_unsaved_changes()
    assert all(isinstance(window.views[a], AppDetailView) for a in ("ai-grammar", "textkit", "yt2txt"))
    assert all(isinstance(window.views[a], StructuredConfigView) for a in ("chat2api", "file-bridge"))
    window._on_config_changed("chat2api", port_draft(window))
    assert window._is_dirty("chat2api") and window.has_unsaved_changes()
    assert window.sidebar._configured_ports["chat2api"] == 8000
    assert "Port 8000" in window.views["chat2api"]._title_label.text()
    window._on_config_changed("chat2api", replace(window._saved_configs["chat2api"], mutations=()))
    assert not window.has_unsaved_changes()
    window._on_save_requested("chat2api", AppAIConfig(), False)
    assert not window._save_jobs
    assert window.views["chat2api"]._notice_label.text() == "Configuration draft does not match this app's config kind; save refused."
    with pytest.raises(ValueError):
        window.sidebar.update_configured_port("chat2api", True)
    with pytest.raises(ValueError):
        window.sidebar.update_configured_port("chat2api", 65536)
    with pytest.raises(KeyError):
        window.sidebar.update_configured_port("unknown", None)


@pytest.mark.parametrize("gate", [None, LauncherProbeResult(False, "old launcher")])
def test_gate_refuses_forged_listener_draft_but_allows_auth_save(window, gate):
    window._launcher_gate_cache[window.apps["chat2api"].relative_path.resolve()] = gate
    window.views["chat2api"].set_launcher_gate(gate)
    window._on_save_requested("chat2api", port_draft(window), True)
    assert not window._save_jobs and not window._pending_restarts
    assert window.views["chat2api"]._notice_label.text() == "Launcher has not passed the configuration probe; host/port changes cannot be saved."
    auth = replace(window._saved_configs["chat2api"], mutations=(Mutation(("server", "auth_token_env"), "set", "OTHER_TOKEN"),))
    window._on_save_requested("chat2api", auth, False)
    assert "chat2api" in window._save_jobs
    assert not window.views["chat2api"]._save_only_btn.isEnabled()
    assert window.views["chat2api"]._restart_btn.isEnabled()
    first = window._save_jobs["chat2api"]
    window._on_save_requested("chat2api", auth, True)
    assert window._save_jobs["chat2api"] is first and window._pending_restarts["chat2api"] is False
    window._on_structured_save_failed("chat2api", ConfigError("fixture failure"))


def test_commit_then_restart_failure_keeps_sealed_state(qtbot, window, monkeypatch):
    run_save(qtbot, window, monkeypatch, draft=port_draft(window), restart=True)
    assert not window.has_unsaved_changes() and window.sidebar._configured_ports["chat2api"] == 8123
    assert window._saved_configs["chat2api"].doc["server"]["port"] == 8123
    assert not window._pending_restarts
    assert window.views["chat2api"]._validation_label.text() == "validated by ai-manager only — service validator unavailable"
    window.supervisor_manager.restart_service.assert_called_once_with("chat2api")
    path = window._saved_configs["chat2api"].path
    sealed = path.read_bytes()
    window._on_supervisor_action("restart chat2api", False, "port busy")
    assert window.views["chat2api"]._notice_label.text() == "Configuration saved, but service restart failed: port busy"
    assert path.read_bytes() == sealed and not window._is_dirty("chat2api")


@pytest.mark.parametrize("error", [
    ConfigValidationError((FieldIssue(("server", "port"), "Port must be an integer from 1 to 65535."),)),
    ServiceValidationError(3, "fixture stdout\n", '<exact & stderr>\n'),
    ServiceValidationTimeout("fixture stdout\n", "timeout stderr\n"),
    TransactionError(TransactionReport(phase="stage", files={Path("/tmp/fixture-config"): "restored"}, error="injected stage failure")),
])
def test_save_failure_retains_dirty_draft_and_never_restarts(window, monkeypatch, error):
    monkeypatch.setattr(mw.TransactionReportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    before = window._saved_configs["chat2api"].raw_bytes
    window._on_save_requested("chat2api", draft, True)
    window._on_structured_save_failed("chat2api", error)
    assert window._draft_configs["chat2api"] == draft and window._is_dirty("chat2api")
    assert window._saved_configs["chat2api"].path.read_bytes() == before
    assert not window._pending_restarts and not window._save_jobs
    assert window.views["chat2api"]._save_only_btn.isEnabled()
    if isinstance(error, (ServiceValidationError, ServiceValidationTimeout)):
        assert window.views["chat2api"]._details.toPlainText() == error.stderr
    window.supervisor_manager.restart_service.assert_not_called()


def test_selected_dependents_reconcile_current_dirty_widgets(qtbot, window, monkeypatch):
    monkeypatch.setattr(mw.BlastRadiusDialog, "selected_app_ids", lambda self: ("textkit", "ai-grammar"))
    original_yt = window._saved_configs["yt2txt"].model_copy(deep=True)
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    window._on_save_requested("chat2api", draft, False)
    # Edit after worker creation: reconciliation must inspect the current draft.
    grammar = window.views["ai-grammar"]
    grammar._model_combo.setEditText("unsaved-user-model")
    retained = window._draft_configs["ai-grammar"].model_copy(deep=True)
    import ai_manager.services.service_validation as validation
    monkeypatch.setattr(validation, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    window._save_jobs["chat2api"].run()
    qtbot.waitUntil(lambda: not window._save_jobs)
    assert window._saved_configs["textkit"].api_base == "http://127.0.0.1:8123"
    assert window._draft_configs["textkit"] == window._saved_configs["textkit"] and not window._is_dirty("textkit")
    assert window._saved_configs["ai-grammar"].api_base == "http://127.0.0.1:8123"
    assert window._draft_configs["ai-grammar"] == retained and grammar.get_current_draft() == retained
    assert grammar._current_config == window._saved_configs["ai-grammar"] and window._is_dirty("ai-grammar")
    assert window._saved_configs["yt2txt"] == original_yt and not window._is_dirty("chat2api")
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("choice", ["cancel", "diff", "reload"])
def test_stale_actions_do_not_force_overwrite(window, monkeypatch, choice):
    viewed = []
    monkeypatch.setattr(mw.StaleDocumentDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mw.StaleDocumentDialog, "choice", lambda self: choice)
    monkeypatch.setattr(mw.ReviewChangesDialog, "exec", lambda self: viewed.append(True) or QDialog.DialogCode.Accepted)
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    window._on_save_requested("chat2api", draft, False)
    path = draft.path
    changed = json.loads(path.read_bytes())
    changed["server"]["port"] = 8222
    path.write_text(json.dumps(changed))
    raw = path.read_bytes()
    window._on_structured_save_failed("chat2api", StaleDocumentError(path, draft.raw_sha256, hashlib.sha256(raw).digest()))
    assert path.read_bytes() == raw and not window._save_jobs
    assert bool(viewed) is (choice == "diff")
    if choice == "reload":
        assert window._saved_configs["chat2api"].doc["server"]["port"] == 8222 and not window._is_dirty("chat2api")
    else:
        assert window._draft_configs["chat2api"] == draft and window._is_dirty("chat2api")


def test_missing_explicit_create_invalid_raw_and_failed_reload_protect_draft(window, monkeypatch):
    path = window.apps["chat2api"].relative_path / "config.json"
    path.unlink()
    window._reload_config("chat2api")
    view = window.views["chat2api"]
    assert not window.has_unsaved_changes() and not view._save_only_btn.isEnabled()
    assert "chat2api" not in window.sidebar._configured_ports
    view._create_from_example()
    assert not path.exists() and window._is_dirty("chat2api")
    row = view._model.rows[0].id
    view._on_raw_options_changed(row, "{broken")
    retained = copy.deepcopy(window._draft_configs["chat2api"])
    path.write_text("[]")
    window._reload_config("chat2api")
    assert window._draft_configs["chat2api"] == retained and window.has_unsaved_changes()
    assert not view._save_only_btn.isEnabled()
    assert view._model.row(row).raw_text == "{broken"


def test_fetch_origin_survives_equal_tokens_navigation_and_non_llm_origin(window, monkeypatch):
    workers = []
    class ControlledWorker:
        def __init__(self, request):
            self.request = request
            from ai_manager.services.model_fetcher import ModelFetchSignals
            self.signals = ModelFetchSignals()
            workers.append(self)
    monkeypatch.setattr(mw, "ModelFetchWorker", ControlledWorker)
    for app_id in ("ai-grammar", "textkit"):
        window.views[app_id].on_model_fetch_response = MagicMock()
        window._on_fetch_models(ModelFetchRequest(token=1, api_base="http://fixture", api_key="", app_id=app_id))
    window.sidebar.select_app("file-bridge")
    response = ModelFetchResponse(token=1, success=True, models=["fixture-model"])
    window._on_models_fetched("ai-grammar", response)
    window.views["ai-grammar"].on_model_fetch_response.assert_called_once_with(response)
    window.views["textkit"].on_model_fetch_response.assert_not_called()
    with pytest.raises(ConfigError):
        window._on_fetch_models(ModelFetchRequest(token=1, api_base="http://fixture", api_key="", app_id="missing"))
    with pytest.raises(ConfigError):
        window._on_fetch_models(ModelFetchRequest(token=1, api_base="http://fixture", api_key="", app_id="file-bridge"))
    window._on_models_fetched("file-bridge", response)
    window._on_models_fetched("removed", response)


def test_probe_once_per_resolved_directory_and_completion_keeps_other_controls(window, monkeypatch):
    # Call the production method explicitly because the autouse fixture substitutes startup.
    from ai_manager.services.config_jobs import LauncherProbeJob
    path = window.apps["chat2api"].relative_path.resolve()
    window._launcher_gate_cache.clear()
    window._probe_jobs.clear()
    # Task 1's isolate_manager stores the production function before replacing it:
    # see fixture amendment in Step 2 below.
    window._production_start_launcher_probes()
    window._production_start_launcher_probes()
    assert len(window._probe_jobs) == 1
    assert window.views["chat2api"]._fields[("server", "port")].isEnabled() is False
    window._on_launcher_probe_finished("chat2api", LauncherProbeResult(False, "fixture failure", stderr="exact probe error\n"))
    assert path in window._launcher_gate_cache and not window._probe_jobs
    assert window.views["chat2api"]._fields[("server", "auth_token_env")].isEnabled()
    assert window.views["chat2api"]._details.toPlainText() == "fixture failure\nexact probe error\n"
    window._production_start_launcher_probes()
    assert not window._probe_jobs
```

- [ ] **Step 2: Make the test harness preserve and expose the production probe starter.** In the existing `isolate_manager` fixture, before its `monkeypatch.setattr(..., "_start_launcher_probes", passed)` add:

```python
        monkeypatch.setattr(mw.MainWindow, "_production_start_launcher_probes", mw.MainWindow._start_launcher_probes, raising=False)
```

The test intentionally calls the preserved method, never a live process. The Task 1 fixture patches only MainWindow's supervisor subclass, so standalone supervisor tests retain their production methods. Add `/data/home/guest/Development/ai/ai-manager/tests/conftest.py:1-120` to this task's modification allowlist.

- [ ] **Step 3: Run and observe dispatcher/worker-state failures.**

```bash
PYTHONPATH=src pytest tests/test_structured_main_window.py -q
```

- [ ] **Step 4: Install imports and state, and choose the widget by an exhaustive kind branch.**

```python
# main_window.py imports
import copy
from dataclasses import replace
from functools import partial
from typing import Any
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QDialog
from ai_manager.config.config_errors import ConfigError, ConfigLoadError, ConfigValidationError, ReadOnlyConfigError, ServiceValidationError, ServiceValidationTimeout, StaleDocumentError, TransactionError, UnknownConfigKindError
from ai_manager.config.structured_config import _candidate, load as load_structured, render
from ai_manager.config.structured_models import LauncherProbeResult, SaveResult, StructuredDoc
from ai_manager.config.structured_schema import validate_in_process
from ai_manager.config.blast_radius import auth_mismatch_warning, endpoint, find_affected_dependents, urls_match
from ai_manager.services.config_jobs import LauncherProbeJob, StructuredSaveJob
from ai_manager.ui.config_dialogs import BlastRadiusDialog, ReviewChangesDialog, StaleDocumentDialog, TransactionReportDialog
from ai_manager.ui.structured_config_view import StructuredConfigView
```

Replace only the two saved/draft annotations and extend the existing state block:

```python
        self._saved_configs: dict[str, Any] = {}
        self._draft_configs: dict[str, Any] = {}
        self._launcher_gate_cache: dict[Path, LauncherProbeResult | None] = {}
        self._probe_jobs: dict[Path, LauncherProbeJob] = {}
        self._save_jobs: dict[str, StructuredSaveJob] = {}
        self._model_workers: dict[int, ModelFetchWorker] = {}
        self._pending_restarts: dict[str, bool] = {}
        self._save_restart_pending: set[str] = set()
        self._submitting_restart: str | None = None
```

After `_load_all_configs()` call `_start_launcher_probes()`. In `_init_ui` replace `self.views`' annotation by `dict[str, AppDetailView | StructuredConfigView]`; replace only the `view = AppDetailView(...)` statement in its existing loop:

```python
            if meta.config_kind == "llm":
                view = AppDetailView(meta, self.stack)
            elif meta.config_kind in ("chat2api", "file-bridge"):
                view = StructuredConfigView(meta, self.stack)
            else:
                raise UnknownConfigKindError(meta.config_kind)
```

- [ ] **Step 5: Replace load/change/dirty helpers and install the saved-port sidebar.**

```python
    def _load_all_configs(self) -> None:
        for app_id in self.apps:
            self._load_config(app_id)
        self._update_auth_warnings()

    def _load_config(self, app_id: str) -> None:
        meta, view = self.apps[app_id], self.views[app_id]
        if meta.config_kind == "llm":
            try:
                config = read_app_config(meta)
            except Exception:
                config = AppAIConfig()
        elif meta.config_kind in ("chat2api", "file-bridge"):
            try:
                config = load_structured(meta.config_kind, meta.relative_path / meta.config_file_name)
            except ConfigLoadError as exc:
                view.show_load_error(exc.detail if exc.reason in ("non-dict-root", "symlink") else str(exc), exc.reason)
                self.sidebar.update_configured_port(app_id, None)
                # A failed reload retains the previous owned draft and dirty state.
                self._set_dirty_indicator(app_id)
                return
        else:
            raise UnknownConfigKindError(meta.config_kind)
        self._saved_configs[app_id] = copy.deepcopy(config)
        self._draft_configs[app_id] = copy.deepcopy(config)
        view.load_config(config)
        self._update_configured_port(app_id, config)
        self._set_dirty_indicator(app_id)

    def _reload_config(self, app_id: str) -> None:
        self._load_config(app_id)
        self._update_auth_warnings()

    def _update_configured_port(self, app_id: str, config) -> None:
        kind = self.apps[app_id].config_kind
        if kind == "llm":
            return
        if kind not in ("chat2api", "file-bridge"):
            raise UnknownConfigKindError(kind)
        if not config.existed:
            self.sidebar.update_configured_port(app_id, None)
            return
        values = config.doc.get("server", {}) if kind == "chat2api" else config.doc
        port = values.get("port", self.apps[app_id].default_port)
        self.sidebar.update_configured_port(app_id, port if type(port) is int and 1 <= port <= 65535 else None)

    def _is_dirty(self, app_id: str) -> bool:
        saved, draft = self._saved_configs.get(app_id), self._draft_configs.get(app_id)
        kind = self.apps[app_id].config_kind
        if kind == "llm":
            return draft is not None and draft != saved
        if kind not in ("chat2api", "file-bridge"):
            raise UnknownConfigKindError(kind)
        if draft is None:
            return False
        if draft.create_requested:
            return True
        if not draft.existed:
            return False
        if draft.input_issues or draft.raw_option_edits:
            try:
                return render(kind, saved) != render(kind, draft)
            except ConfigError:
                return True
        if draft.read_only_reasons and not draft.mutations:
            return False
        try:
            return render(kind, replace(saved, mutations=(), raw_option_edits={}, input_issues=())) != render(kind, draft)
        except ConfigError:
            return bool(draft.mutations) or saved is None

    def _set_dirty_indicator(self, app_id: str) -> None:
        dirty = self._is_dirty(app_id)
        self.sidebar.set_dirty(app_id, dirty)
        view = self.views.get(app_id)
        if view is not None:
            view._dirty_label.setText("Unsaved changes" if dirty else "")

    def _check_payload(self, app_id: str, config: object) -> None:
        meta = self.apps[app_id]
        if meta.config_kind == "llm":
            valid = isinstance(config, AppAIConfig)
        elif meta.config_kind in ("chat2api", "file-bridge"):
            valid = isinstance(config, StructuredDoc) and config.kind == meta.config_kind
        else:
            raise UnknownConfigKindError(meta.config_kind)
        if not valid:
            raise ConfigError("Configuration draft does not match this app's config kind; save refused.")

    def _on_config_changed(self, app_id: str, new_draft: object) -> None:
        try:
            self._check_payload(app_id, new_draft)
        except ConfigError as exc:
            self.views[app_id].show_config_error(str(exc))
            return
        self._draft_configs[app_id] = copy.deepcopy(new_draft)
        self._set_dirty_indicator(app_id)
        self._update_auth_warnings()

    def has_unsaved_changes(self) -> bool:
        return any(self._is_dirty(app_id) for app_id in self.apps)
```

In `AppSidebar.__init__`, initialize `_configured_ports: dict[str, int] = {}` before `_init_items`. Change its port line and add:

```python
        port = self._configured_ports.get(app_id, meta.default_port)
        item.setText(f"{title}\n   Port {port}")

    def update_configured_port(self, app_id: str, port: int | None) -> None:
        if app_id not in self.apps:
            raise KeyError(app_id)
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ValueError("Configured port must be an integer from 1 to 65535.")
        if port is None:
            self._configured_ports.pop(app_id, None)
        else:
            self._configured_ports[app_id] = port
        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == app_id:
                self._update_item_text(item, app_id)
                break
```

- [ ] **Step 6: Replace save coordination and add completion/error/reconciliation slots.**

```python
    def _on_save_requested(self, app_id: str, config: object, should_restart: bool) -> None:
        if app_id in self._save_jobs:
            return
        meta, view = self.apps[app_id], self.views[app_id]
        try:
            self._check_payload(app_id, config)
            if meta.config_kind == "llm":
                write_app_config(meta, config)
                self._saved_configs[app_id] = config.model_copy(deep=True)
                self._draft_configs[app_id] = config.model_copy(deep=True)
                view.adopt_saved_baseline(config, preserve_draft=False)
                self._set_dirty_indicator(app_id)
                self._update_auth_warnings()
                if should_restart:
                    self._request_saved_restart(app_id)
                else:
                    view.show_config_error("Configuration saved.")
                return
            if meta.config_kind not in ("chat2api", "file-bridge"):
                raise UnknownConfigKindError(meta.config_kind)
            if not config.existed and not config.create_requested:
                raise ConfigError("Create a draft from the example before saving.")
            selected = ()
            if meta.config_kind == "chat2api":
                previous = self._saved_configs.get(app_id)
                def listener(document):
                    server = _candidate(document).get("server", {})
                    return tuple((type(server.get(key, default)), server.get(key, default)) for key, default in (("host", "127.0.0.1"), ("port", 8000)))
                changed = previous is not None and listener(previous) != listener(config)
                gate = self._launcher_gate_cache.get(meta.relative_path.resolve())
                if changed and (gate is None or not gate.passed):
                    raise ReadOnlyConfigError(config.path, "Launcher has not passed the configuration probe; host/port changes cannot be saved.")
                if changed:
                    # Chat2api schema is pure; diagnose malformed listener values before constructing URLs/dialogs.
                    validate_in_process("chat2api", _candidate(config), config_path=config.resolved_path, app_dir=meta.relative_path)
                    matches = find_affected_dependents(self.apps, previous, config)
                    if matches:
                        dialog = BlastRadiusDialog(matches, self)
                        if dialog.exec() != QDialog.DialogCode.Accepted:
                            return
                        selected_ids = set(dialog.selected_app_ids())
                        selected = tuple(match for match in matches if match.meta.id in selected_ids)
            job = StructuredSaveJob(meta, config, selected)
            self._save_jobs[app_id] = job
            self._pending_restarts[app_id] = bool(should_restart)
            view.set_save_in_progress(True)
            job.signals.save_finished.connect(self._on_structured_saved, Qt.ConnectionType.QueuedConnection)
            job.signals.save_failed.connect(self._on_structured_save_failed, Qt.ConnectionType.QueuedConnection)
            self.thread_pool.start(job)
        except ConfigError as exc:
            self._on_structured_save_failed(app_id, exc)
        except Exception as exc:
            self._on_structured_save_failed(app_id, ConfigError(f"Configuration save failed: {exc}"))

    @pyqtSlot(str, object)
    def _on_structured_saved(self, app_id: str, result: SaveResult) -> None:
        should_restart = self._pending_restarts.pop(app_id, False)
        self._save_jobs.pop(app_id, None)
        self._saved_configs[app_id] = copy.deepcopy(result.document)
        self._draft_configs[app_id] = copy.deepcopy(result.document)
        view = self.views[app_id]
        view.adopt_saved_baseline(result.document, preserve_draft=False)
        view.set_validation_result(result.validation)
        view.set_save_in_progress(False)
        self._update_configured_port(app_id, result.document)
        self._set_dirty_indicator(app_id)
        self._reconcile_dependent_views(result.saved_dependents)
        self._update_auth_warnings()
        if should_restart:
            self._request_saved_restart(app_id)
        else:
            view.show_config_error("Configuration saved.")

    @pyqtSlot(str, object)
    def _on_structured_save_failed(self, app_id: str, error: ConfigError) -> None:
        self._pending_restarts.pop(app_id, None)
        self._save_jobs.pop(app_id, None)
        view = self.views[app_id]
        view.set_save_in_progress(False)
        self._set_dirty_indicator(app_id)
        if isinstance(error, ConfigValidationError) and isinstance(view, StructuredConfigView):
            view.show_config_error(str(error))
            view.show_field_issues(error.issues)
        elif isinstance(error, (ServiceValidationError, ServiceValidationTimeout)):
            view.show_config_error(str(error), error.stderr)
        elif isinstance(error, StaleDocumentError):
            view.show_config_error(str(error))
            dialog = StaleDocumentDialog(error.path, self)
            dialog.exec()
            if dialog.choice() == "reload":
                self._reload_config(app_id)
            elif dialog.choice() == "diff":
                try:
                    current = error.path.read_bytes()
                    draft = self._draft_configs[app_id]
                    ReviewChangesDialog(current, render(draft.kind, draft), error.path, self).exec()
                except (OSError, ConfigError) as exc:
                    view.show_config_error(str(error), str(exc))
        elif isinstance(error, TransactionError):
            view.show_config_error(str(error))
            TransactionReportDialog(error.report, self).exec()
        else:
            view.show_config_error(str(error))

    def _reconcile_dependent_views(self, saved_dependents: dict[str, AppAIConfig]) -> None:
        for app_id, baseline in saved_dependents.items():
            dirty = self._is_dirty(app_id)
            self._saved_configs[app_id] = baseline.model_copy(deep=True)
            if not dirty:
                self._draft_configs[app_id] = baseline.model_copy(deep=True)
            self.views[app_id].adopt_saved_baseline(baseline, preserve_draft=dirty)
            self._set_dirty_indicator(app_id)

    def _request_saved_restart(self, app_id: str) -> None:
        self.views[app_id].show_config_error("Configuration saved. Restart requested.")
        self._save_restart_pending.add(app_id)
        self._submitting_restart = app_id
        try:
            self.supervisor_manager.restart_service(app_id)
        finally:
            self._submitting_restart = None

    def _on_supervisor_action(self, action: str, success: bool, msg: str) -> None:
        app_id = action[len("restart "):] if action.startswith("restart ") else self._submitting_restart if action == "restart" else None
        if app_id in self._save_restart_pending:
            self._save_restart_pending.remove(app_id)
            self.views[app_id].show_config_error("service restart succeeded" if success else f"Configuration saved, but service restart failed: {msg}")
        elif not success:
            QMessageBox.warning(self, "Supervisor Action Failed", f"Action: {action}\n{msg}")
```

`show_config_error("Configuration saved.")` must not clear the validation details set by `set_validation_result`; adjust the view's message helper to preserve validator details when detail is omitted, and explicitly clear stale details when loading a different config. Change its signature to `detail: str | None = None` (compatible with the adapter's optional argument) and call `_details.setPlainText(detail)` only when `detail is not None`. The exact stderr supplied on failures always replaces it.

- [ ] **Step 7: Cache probe results and bind model fetch completion to its origin on the GUI thread.**

```python
    def _start_launcher_probes(self) -> None:
        for app_id, meta in self.apps.items():
            if meta.config_kind == "llm" or meta.config_kind == "file-bridge":
                continue
            if meta.config_kind != "chat2api":
                raise UnknownConfigKindError(meta.config_kind)
            key = meta.relative_path.resolve()
            if key in self._launcher_gate_cache:
                self.views[app_id].set_launcher_gate(self._launcher_gate_cache[key])
                continue
            self._launcher_gate_cache[key] = None
            job = LauncherProbeJob(meta)
            self._probe_jobs[key] = job
            self.views[app_id].set_launcher_gate(None)
            job.signals.probe_finished.connect(self._on_launcher_probe_finished, Qt.ConnectionType.QueuedConnection)
            self.thread_pool.start(job)

    @pyqtSlot(str, object)
    def _on_launcher_probe_finished(self, app_id: str, result: LauncherProbeResult) -> None:
        if app_id not in self.apps or self.apps[app_id].config_kind != "chat2api":
            return
        key = self.apps[app_id].relative_path.resolve()
        self._launcher_gate_cache[key] = result
        self._probe_jobs.pop(key, None)
        for other_id, meta in self.apps.items():
            if meta.config_kind == "chat2api" and meta.relative_path.resolve() == key:
                self.views[other_id].set_launcher_gate(result)

    def _update_auth_warnings(self) -> None:
        for app_id, meta in self.apps.items():
            if meta.config_kind not in ("llm", "chat2api", "file-bridge"):
                raise UnknownConfigKindError(meta.config_kind)
            if meta.config_kind != "chat2api":
                continue
            warnings = []
            current = self._draft_configs.get(app_id)
            if isinstance(current, StructuredDoc) and (current.existed or current.create_requested):
                try:
                    tree = _candidate(current)
                    auth = tree.get("server", {}).get("auth_token_env", "CHAT2API_TOKEN")
                    _, _, url = endpoint(current)
                    for other_id, other_meta in self.apps.items():
                        config = self._draft_configs.get(other_id)
                        if other_meta.config_kind == "llm" and isinstance(config, AppAIConfig) and urls_match(config.api_base, url):
                            warning = auth_mismatch_warning(config, auth)
                            if warning:
                                warnings.append(warning.format(app_id=other_id))
                except (ConfigError, ValueError):
                    pass
            self.views[app_id].show_auth_warnings(tuple(warnings))

    def _on_fetch_models(self, request: ModelFetchRequest) -> None:
        meta = self.apps.get(request.app_id)
        if meta is None:
            raise ConfigError("Model fetch origin is not a managed app.")
        if meta.config_kind not in ("llm", "chat2api", "file-bridge"):
            raise UnknownConfigKindError(meta.config_kind)
        if meta.config_kind != "llm":
            raise ConfigError("Model fetching is available only for LLM configurations.")
        worker = ModelFetchWorker(request)
        key = id(worker)
        self._model_workers[key] = worker
        worker.signals.finished.connect(partial(self._finish_model_worker, request.app_id, key), Qt.ConnectionType.QueuedConnection)
        self.thread_pool.start(worker)

    def _finish_model_worker(self, app_id: str, key: int, response: ModelFetchResponse) -> None:
        self._model_workers.pop(key, None)
        self._on_models_fetched(app_id, response)

    def _on_models_fetched(self, app_id: str, response: ModelFetchResponse) -> None:
        meta, view = self.apps.get(app_id), self.views.get(app_id)
        if meta is None or view is None:
            return
        if meta.config_kind == "llm":
            view.on_model_fetch_response(response)
        elif meta.config_kind in ("chat2api", "file-bridge"):
            return
        else:
            raise UnknownConfigKindError(meta.config_kind)
```

Keep `_on_restart_requested` as a direct supervisor call; it writes no config and clears no dirty state. Correct `CHAT2API_API_KEY` to `CHAT2API_TOKEN` in the preset.

- [ ] **Step 8: Migrate the existing window fixtures and add behavioral regressions.** Keep every existing test/assertion while replacing its three-app setup with `five_app_workspace`.

In `tests/test_main_window.py`, replace `make_test_window` by this complete helper. Change the three existing test signatures from `(qtbot, tmp_path)` to `(qtbot, five_app_workspace)` and their helper/workspace arguments accordingly. In `test_main_window_init_and_navigation`, replace only the fixture-copy block and constructor/addWidget lines by `window = MainWindow(workspace_root=five_app_workspace)` followed by `qtbot.addWidget(window)`; retain all its existing navigation/theme/dirty assertions.

```python
def make_test_window(qtbot, five_app_workspace):
    window = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    window.sidebar.update_status = MagicMock()
    for view in window.views.values():
        view.update_service_status = MagicMock()
    return window
```

In `tests/test_main_window_tray.py`, replace its `window` fixture and `_dirty_draft` helper with these complete definitions. Existing tray/close/settings tests then exercise both LLM and structured dirty state.

```python
@pytest.fixture
def window(qtbot, five_app_workspace, monkeypatch):
    monkeypatch.setattr(main_window_module, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(main_window_module, "save_user_settings", lambda settings: None)
    win = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(win)
    return win


def _dirty_draft(window: MainWindow) -> None:
    window.views["ai-grammar"]._model_combo.setEditText("tray-test-model")
    window.views["chat2api"]._fields[("server", "port")].edit.setText("8123")
```

In `tests/test_mnemonic.py`, change the existing main-window sweep signature to `(qtbot, five_app_workspace, monkeypatch)`, remove its local fixture-copy block, and construct `MainWindow(workspace_root=five_app_workspace)`; retain its settings stubs and all sweep/menu/title assertions. The separate dynamic LLM chip test stays LLM-only. Append the following tests to the indicated files.

```python
# append to tests/test_structured_main_window.py
from threading import Event
from PyQt6.QtCore import QThreadPool, QTimer


def test_actual_worker_completion_is_queued_and_gui_remains_responsive(qtbot, window, monkeypatch):
    from ai_manager.config import structured_config as sc
    entered, release = Event(), Event()
    observed = []
    def blocked_commit(*args, **kwargs):
        observed.append(("worker", QThread.currentThread()))
        entered.set()
        assert release.wait(5), "test did not release worker"
        raise ServiceValidationError(3, "", "queued stderr\n")
    monkeypatch.setattr(sc, "commit", blocked_commit)
    view = window.views["chat2api"]
    original = view.show_config_error
    def checked_message(message, detail=None):
        observed.append(("gui", QThread.currentThread()))
        assert QThread.currentThread() is window.thread()
        return original(message, detail)
    monkeypatch.setattr(view, "show_config_error", checked_message)
    pool = QThreadPool(window)
    window.thread_pool = pool
    window._on_config_changed("chat2api", port_draft(window))
    try:
        window._on_save_requested("chat2api", port_draft(window), True)
        qtbot.waitUntil(entered.is_set)
        ticks = []
        QTimer.singleShot(0, lambda: (view._tabs.setCurrentIndex(1), ticks.append(True)))
        qtbot.waitUntil(lambda: bool(ticks))
        assert "chat2api" in window._save_jobs and not view._save_only_btn.isEnabled()
        release.set()
        qtbot.waitUntil(lambda: not window._save_jobs)
        assert any(role == "worker" and thread is not window.thread() for role, thread in observed)
        assert any(role == "gui" for role, thread in observed)
        assert view._details.toPlainText() == "queued stderr\n"
        window.supervisor_manager.restart_service.assert_not_called()
    finally:
        release.set()
        assert pool.waitForDone(5000)


def test_fetch_reverse_delivery_equal_tokens_and_late_token(qtbot, window, monkeypatch):
    from ai_manager.services.model_fetcher import ModelFetchSignals
    workers = []
    class ControlledWorker:
        def __init__(self, request):
            self.request, self.signals = request, ModelFetchSignals()
            workers.append(self)
    monkeypatch.setattr(mw, "ModelFetchWorker", ControlledWorker)
    grammar, textkit = window.views["ai-grammar"], window.views["textkit"]
    grammar._on_fetch_clicked()
    textkit._on_fetch_clicked()
    window.sidebar.select_app("chat2api")
    assert workers[0].request.app_id == "ai-grammar" and workers[1].request.app_id == "textkit"
    assert workers[0].request.token == workers[1].request.token == 1
    workers[1].signals.finished.emit(ModelFetchResponse(token=1, success=True, models=["textkit-only"]))
    workers[0].signals.finished.emit(ModelFetchResponse(token=1, success=True, models=["grammar-only"]))
    qtbot.waitUntil(lambda: not window._model_workers)
    assert "grammar-only" in grammar._available_models and "grammar-only" not in textkit._available_models
    assert "textkit-only" in textkit._available_models and "textkit-only" not in grammar._available_models
    grammar._on_fetch_clicked()
    window._on_models_fetched("ai-grammar", ModelFetchResponse(token=1, success=True, models=["stale-model"]))
    assert "stale-model" not in grammar._available_models
    workers[-1].signals.finished.emit(ModelFetchResponse(token=2, success=True, models=["fresh-model"]))
    qtbot.waitUntil(lambda: not window._model_workers)
    assert "fresh-model" in grammar._available_models


@pytest.mark.parametrize("app_id,key,value", [("chat2api", ("server", "port"), 8123), ("file-bridge", ("port",), 8970)])
def test_port_cache_survives_status_dirty_redraw_and_unreadable_reload(qtbot, window, monkeypatch, app_id, key, value):
    saved = window._saved_configs[app_id]
    run_save(qtbot, window, monkeypatch, app_id=app_id, draft=replace(saved, mutations=(Mutation(key, "set", value),)))
    window.sidebar.select_app(app_id)
    window.sidebar.set_dirty(app_id, True)
    window.sidebar.update_status(app_id, ServiceStatus(service_id=app_id, state=ServiceRunState.RUNNING, pid=1))
    assert f"Port {value}" in window.sidebar._list_widget.currentItem().text()
    assert f"Port {value}" in window.views[app_id]._title_label.text()
    assert window.apps[app_id].default_port == (8000 if app_id == "chat2api" else 8964)
    window._saved_configs[app_id].path.write_bytes(b"[]\n")
    window._reload_config(app_id)
    assert app_id not in window.sidebar._configured_ports
    assert f"Port {window.apps[app_id].default_port}" in window.sidebar._list_widget.currentItem().text()


def test_auth_warning_uses_current_dependent_draft_without_key_write(window):
    draft = replace(window._saved_configs["chat2api"], mutations=(Mutation(("server", "auth_token_env"), "set", "CHAT2API_TOKEN"),))
    window._on_config_changed("chat2api", draft)
    dependent = window._draft_configs["ai-grammar"].model_copy(update={"api_key": "$OTHER_TOKEN"})
    window._on_config_changed("ai-grammar", dependent)
    expected = "ai-grammar uses $OTHER_TOKEN, but chat2api auth_token_env is 'CHAT2API_TOKEN'; requests may fail with HTTP 401."
    assert expected in window.views["chat2api"]._auth_label.text()
    assert b'api_key: "$CHAT2API_TOKEN"' in (window.apps["ai-grammar"].relative_path / "config.yaml").read_bytes()
    disabled = replace(draft, mutations=(Mutation(("server", "auth_token_env"), "set", None),))
    window._on_config_changed("chat2api", disabled)
    assert not window.views["chat2api"]._auth_label.text()


def test_blast_cancel_prevents_worker_and_target_changes(window, monkeypatch):
    monkeypatch.setattr(mw.BlastRadiusDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    original = draft.path.read_bytes()
    window._on_save_requested("chat2api", draft, True)
    assert not window._save_jobs and not window._pending_restarts
    assert draft.path.read_bytes() == original and window._is_dirty("chat2api")
    window.supervisor_manager.restart_service.assert_not_called()
```

The fetch tests inspect the existing LLM view's `_available_models` list and its actual per-view token rejection. Do not replace these with mocked receiver call counts.

```python
# append to tests/test_app_views.py

def test_sidebar_saved_port_strictness_and_llm_baseline_adoption(qtbot, tmp_path):
    import pytest
    apps = get_managed_apps(tmp_path)
    sidebar = AppSidebar(apps)
    qtbot.addWidget(sidebar)
    assert sidebar._list_widget.count() == 5
    sidebar.update_configured_port("chat2api", 8123)
    sidebar.select_app("chat2api")
    sidebar.set_dirty("chat2api", True)
    assert "Port 8123" in sidebar._list_widget.currentItem().text()
    sidebar.update_configured_port("chat2api", None)
    assert "Port 8000" in sidebar._list_widget.currentItem().text()
    view = AppDetailView(apps["ai-grammar"])
    qtbot.addWidget(view)
    old = AppAIConfig(api_base="http://127.0.0.1:8000", model="original")
    new = old.model_copy(update={"api_base": "http://127.0.0.1:8123"})
    view.load_config(old)
    view._model_combo.setEditText("draft-only")
    draft = view.get_current_draft()
    changed = []
    view.config_changed.connect(lambda *args: changed.append(args))
    view.adopt_saved_baseline(new, preserve_draft=True)
    assert view.get_current_draft() == draft and view._current_config == new and not changed
    view.adopt_saved_baseline(new, preserve_draft=False)
    assert view.get_current_draft() == new and not changed
```

```python
# append to tests/test_supervisor.py

def test_five_service_status_and_hyphenated_restart(qtbot, tmp_path):
    from unittest.mock import MagicMock
    from PyQt6.QtCore import QProcess
    from ai_manager.services.supervisor import SupervisorManager, parse_supervisor_status
    from ai_manager.config.models import ServiceRunState
    text = """[2026-10-17 16:07:34] supervisor running: 34491
ai-grammar   running  pid=101 log=/tmp/logs/ai-grammar.log
textkit      running  pid=102 log=/tmp/logs/textkit.log
yt2txt       stopped  pid=- log=/tmp/logs/yt2txt.log
chat2api     running  pid=104 log=/tmp/logs/chat2api.log
file-bridge  running  pid=105 log=/tmp/logs/file-bridge.log
"""
    status = parse_supervisor_status(text)
    assert len(status.services) == 5 and status.services["yt2txt"].pid is None
    assert status.services["file-bridge"].state == ServiceRunState.RUNNING
    assert status.services["file-bridge"].pid == 105 and status.services["file-bridge"].log_path == "/tmp/logs/file-bridge.log"
    manager = SupervisorManager(tmp_path)
    manager._action_process = MagicMock()
    manager._action_process.state.return_value = QProcess.ProcessState.NotRunning
    manager.restart_service("file-bridge")
    manager._action_process.start.assert_called_once_with(manager.executable, ["restart", "file-bridge"])
```

The supervisor test imports the original service class, while the isolated MainWindow fixture patches only its module's subclass. The test's fake QProcess therefore verifies the real restart method without invoking a supervisor.

```python
# append to tests/test_mnemonic.py

def test_structured_views_and_blast_names_escape_only_mnemonic_sinks(qtbot, five_app_workspace):
    import json
    from dataclasses import replace
    from ai_manager.config.app_registry import get_managed_apps
    from ai_manager.config.structured_config import load
    from ai_manager.config.structured_models import Mutation
    from ai_manager.config.blast_radius import find_affected_dependents
    from ai_manager.ui.structured_config_view import StructuredConfigView
    from ai_manager.ui.config_dialogs import BlastRadiusDialog
    apps = get_managed_apps(five_app_workspace)
    path = apps["chat2api"].relative_path / "config.json"
    tree = json.loads(path.read_bytes())
    tree["models"]["qwen&co/7b"] = tree["models"].pop("echo-1")
    path.write_text(json.dumps(tree))
    before = load("chat2api", path)
    for app_id in ("chat2api", "file-bridge"):
        view = StructuredConfigView(apps[app_id])
        qtbot.addWidget(view)
        view.load_config(load(apps[app_id].config_kind, apps[app_id].relative_path / apps[app_id].config_file_name))
        assert find_unescaped_ampersand_sinks(view) == []
        if app_id == "chat2api":
            assert view._model.rows[0].name == "qwen&co/7b"
        else:
            view._fields[("save_root",)].edit.setText("../A&B")
            assert view.get_current_draft().mutations[0].value == "../A&B"
    apps["textkit"] = apps["textkit"].model_copy(update={"display_name": "Text & Toolkit"})
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    dialog = BlastRadiusDialog(find_affected_dependents(apps, before, after))
    qtbot.addWidget(dialog)
    assert "Text && Toolkit" in dialog._checks["textkit"].text()
    assert find_unescaped_ampersand_sinks(dialog) == []
```

```python
# append to tests/test_main_window_tray.py

def test_structured_dirty_quit_cancel_keeps_raw_draft(qtbot, five_app_workspace, monkeypatch):
    from ai_manager.ui import main_window as mw
    window = mw.MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    view = window.views["chat2api"]
    view._on_raw_options_changed(view._model.rows[0].id, "{broken")
    exited = []
    monkeypatch.setattr(window, "_exit_application", lambda: exited.append(True))
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a: mw.QMessageBox.StandardButton.Cancel)
    window.handle_quit()
    assert not exited and window.has_unsaved_changes()
    assert view.get_current_draft().raw_option_edits == {"echo-1": "{broken"}
```

Extend existing `test_e2e_integration.py` by appending:

```python

def test_five_widget_dispatch(qtbot, five_app_workspace):
    from ai_manager.ui.main_window import MainWindow
    from ai_manager.ui.app_detail_view import AppDetailView
    from ai_manager.ui.structured_config_view import StructuredConfigView
    window = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    assert list(window.views) == ["ai-grammar", "textkit", "yt2txt", "chat2api", "file-bridge"]
    assert all(isinstance(window.views[a], AppDetailView) for a in ("ai-grammar", "textkit", "yt2txt"))
    assert all(isinstance(window.views[a], StructuredConfigView) for a in ("chat2api", "file-bridge"))
    assert window.sidebar.current_app_id() == "ai-grammar" and not window.has_unsaved_changes()
```

- [ ] **Step 9: Update user documentation.** Replace the supported-app description by a five-row table (`ai-grammar`/8766, `textkit`/8765, `yt2txt`/8666, `chat2api`/8000 JSON, `file-bridge`/8964 YAML), and insert the following section before existing development instructions. Preserve the existing installation/tray/theme documentation. Use four backticks for this embedded Markdown so its headings never truncate this task in the controller.

````markdown
### Structured configuration

chat2api exposes Server and Models; file-bridge exposes Save Location & Server. Create from Example starts an unsaved draft when a structured config is missing. Review Changes shows the local saved-to-draft diff. Save Config Only validates and writes; Save and Restart requests a supervisor restart only after the save commits. A restart failure keeps the saved configuration and is reported separately.

Install the chat2api launcher update with or before this ai-manager version. Each manager session checks the launcher with a temporary echo-only config and disabled auth. Until that check passes, chat2api host/port and dependent URL updates stay disabled. Models/options/auth, status, logs and restart remain available. The probe is cleaned up and never changes the real config.

When chat2api host/port changes, only explicitly checked matching LLM apps receive a new ai.api_base. Their API keys, models and other data are preserved. Dirty drafts in those apps stay visible after the saved baseline changes. The chat2api_local preset now uses $CHAT2API_TOKEN; existing keys are never migrated automatically.

chat2api host accepts only 127.0.0.1, localhost or ::1. The editor edits app_dir/config.json; it does not discover an externally set CHAT2API_CONFIG. CLI listener overrides may differ from the configured port shown by the manager. file-bridge stays on IPv4 loopback; 0 maximum text bytes means no configured limit while its transport cap still applies. A save root must already exist outside the file-bridge application directory.

Validation always checks the manager schema. When the target interpreter/imports are unavailable, the inline result says "validated by ai-manager only — service validator unavailable". Validation does not establish restart success, free ports, provider credentials, login or discovery.

Structured saves refuse stale files and keep timestamped exclusive backups and existing mode bits (new files use 0600). Sidecar locks coordinate participating writers. Unlocked editors/readers can still race or observe a partial multi-file replacement. Recovery covers handled failures; there is no crash-recovery journal or multi-file crash atomicity. The launcher reads config once for listener flags and again during startup, so an intervening edit can disagree with the listener. Symlinks, non-writable files, and YAML anchors/aliases cannot be edited here.
````

- [ ] **Step 10: Run the whole Target A suite and inspect the scope.**

```bash
PYTHONPATH=src pytest tests/
git diff --check
git diff --stat
```

Expected: PASS with no failures; all five apps' kind dispatch, saved ports, lifecycle behavior, token ownership, transaction refusal/recovery, and dirty-draft retention pass. This task does not edit service/model-fetcher production code. Do not commit Target B or C files.

- [ ] **Step 11: Commit Target A only.**

```bash
git add src/ai_manager/ui/main_window.py src/ai_manager/ui/app_sidebar.py src/ai_manager/ui/structured_config_view.py src/ai_manager/config/presets.py tests/conftest.py tests/test_structured_main_window.py tests/test_app_views.py tests/test_main_window.py tests/test_main_window_tray.py tests/test_mnemonic.py tests/test_supervisor.py tests/test_e2e_integration.py README.md
git commit -m "feat(ui): coordinate structured saves, dependents and listener gates"
```

## Task 13: Fix and behaviorally verify the Target B launcher in its own checkout

**Implementer tier:** Advanced

**Files:**

- Modify (Target B only): `/data/home/guest/Development/ai/chat2api/start.sh:1-34` (complete script replacement; retain executable bit).
- Create/Test (Target B only): `/data/home/guest/Development/ai/chat2api/tests/test_launcher.py`.

**Interfaces:**

- Consumes: real chat2api `app.config.load_config(path: str | None = None) -> Config` with `.server.host: str`, `.server.port: int`, dotenv and CHAT2API_CONFIG handling; `app.__version__`; `uvicorn app.main:app`'s existing Click parser; no production Python changes.
- Produces: configured `--host`/`--port` before existing fixed uvicorn flags and final `"$@"`; one lexical `PY` selection used for banner/config/final exec; every config-read failure exits before uvicorn.
- Produces: the `--print-listener` capability flag. When it is the first argument, the launcher prints the resolved host and port on two lines and exits 0 **before** importing or starting uvicorn, binding no socket. This is the flag ai-manager's Task 7 gate invokes. It must be placed after HOST/PORT resolution and before the final `exec`.
- Produces: mandatory real-app socket/HTTP acceptance plus interpreter spy tests, isolated app/config/env fixtures, bounded process-group cleanup and reaping. Work only in the assigned isolated **Target B** execution checkout; all commands in this task run there. If the controller's A task ledger requires a commit reference, report the B commit and repo explicitly; never manufacture an A commit or copy B files into A to satisfy the ledger.

- [ ] **Step 1: Add the actual-launcher tests, using only temporary copies and synthetic echo/null configs.**

```python
# tests/test_launcher.py
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import pytest

REPO = Path(__file__).resolve().parents[1]


def free_port(*excluded):
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in (8000, *excluded):
            return port


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_closed(port):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and listening(port):
        time.sleep(0.02)
    assert not listening(port)


def config(path, port):
    path.write_text(json.dumps({"server": {"host": "127.0.0.1", "port": port, "auth_token_env": None}, "models": {"echo-probe": {"provider": "echo"}}}), encoding="utf-8")


SPY = r'''import json, os, sys, time
from pathlib import Path
program = sys.argv[2] if len(sys.argv) > 2 else ""
with open(os.environ["LAUNCHER_TEST_RECORD"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"python": str(Path(sys.argv[0]).absolute()), "args": sys.argv[1:], "cwd": str(Path.cwd())}) + "\n")
if "from app.config import load_config" in program:
    if os.environ.get("LAUNCHER_TEST_FREEZE_READ"):
        time.sleep(60)
    if os.environ.get("LAUNCHER_TEST_FAIL_READ"):
        raise SystemExit(42)
os.execv(os.environ["LAUNCHER_TEST_REAL_PYTHON"], [os.environ["LAUNCHER_TEST_REAL_PYTHON"], *sys.argv[1:]])
'''


def interpreter(directory, activate):
    directory.mkdir(parents=True)
    python = directory / "python"
    python.write_text(f"#!{sys.executable}\n" + SPY, encoding="utf-8")
    python.chmod(0o755)
    if activate:
        (directory / "activate").write_text('export PATH="' + str(directory) + ':$PATH"\n', encoding="utf-8")
    return python


@pytest.fixture
def application(tmp_path):
    root = tmp_path / "temporary app"
    root.mkdir()
    for directory in ("app", "providers"):
        shutil.copytree(REPO / directory, root / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(REPO / "start.sh", root / "start.sh")
    (root / "start.sh").chmod((root / "start.sh").stat().st_mode | 0o100)
    # Never copy .env, config.json, venvs, cache files or stored credentials.
    (root / ".env").write_text("", encoding="utf-8")
    outside = tmp_path / "caller cwd"
    outside.mkdir()
    home = tmp_path / "synthetic home"
    home.mkdir()
    env = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8"}
    env.update(HOME=str(home), PYTHONNOUSERSITE="1", LAUNCHER_TEST_REAL_PYTHON=sys.executable, LAUNCHER_TEST_RECORD=str(tmp_path / "interpreter.jsonl"))
    return root, outside, env


def choose(application, mode):
    root, outside, env = application
    ambient = interpreter(root / "ambient-bin", False)
    env["PATH"] = str(ambient.parent) + os.pathsep + env["PATH"]
    chosen = ambient
    if mode in (".venv", "both"):
        chosen = interpreter(root / ".venv/bin", True)
    if mode in ("venv", "both"):
        alternate = interpreter(root / "venv/bin", True)
        if mode == "venv":
            chosen = alternate
    if mode == "unactivated":
        interpreter(root / ".venv/bin", False)
    return chosen


def records(env):
    path = Path(env["LAUNCHER_TEST_RECORD"])
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@contextlib.contextmanager
def running(application, *args):
    root, outside, env = application
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen([str(root / "start.sh"), *args], cwd=outside, env=env, stdout=out, stderr=err, start_new_session=True)
        try:
            yield child, out, err
        finally:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=2)
            assert child.poll() is not None


def wait_ready(child, err, port, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            err.seek(0)
            pytest.fail(f"launcher exited {child.returncode}: {err.read().decode('utf-8', errors='replace')}")
        if listening(port):
            with urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1) as response:
                body = json.load(response)
                assert response.status == 200
                assert "echo-probe" in [item["id"] for item in body["data"]]
            assert child.poll() is None
            return
        time.sleep(0.03)
    raise TimeoutError("launcher did not bind the configured port")


def assert_spy(env, chosen, root):
    invocations = records(env)
    assert len(invocations) == 3
    assert all(call["python"] == str(chosen) and call["cwd"] == str(root) for call in invocations)
    assert invocations[0]["args"][0] == invocations[1]["args"][0] == "-c"
    assert "from app import __version__" in invocations[0]["args"][1]
    assert "from app.config import load_config" in invocations[1]["args"][1]
    assert invocations[2]["args"][:3] == ["-m", "uvicorn", "app.main:app"]
    return invocations[2]["args"]


@pytest.mark.parametrize("mode", [".venv", "venv", "both", "ambient", "unactivated"])
def test_configured_socket_and_exact_interpreter(application, mode, record_property):
    root, outside, env = application
    chosen = choose(application, mode)
    port = free_port()
    config(root / "config.json", port)
    default_was_closed = not listening(8000)
    record_property("default_port_negative_inapplicable", not default_was_closed)
    with running(application) as (child, out, err):
        wait_ready(child, err, port)
        if default_was_closed:
            assert not listening(8000)
        args = assert_spy(env, chosen, root)
        assert args[3:7] == ["--host", "127.0.0.1", "--port", str(port)]
        assert args[7:] == ["--timeout-graceful-shutdown", "5", "--log-level", "info"]
    wait_closed(port)


@pytest.mark.parametrize("override", ["absolute", "relative", "default"])
def test_config_path_uses_script_directory(application, override):
    root, outside, env = application
    choose(application, ".venv")
    port = free_port()
    path = root / ("config.json" if override == "default" else "relative-probe.json")
    config(path, port)
    if override != "default":
        env["CHAT2API_CONFIG"] = str(path) if override == "absolute" else path.name
    with running(application) as (child, out, err):
        wait_ready(child, err, port)
        assert outside != root
    wait_closed(port)


def test_later_cli_listener_and_log_flags_win(application):
    root, outside, env = application
    chosen = choose(application, "venv")
    configured, overridden = free_port(), free_port()
    while overridden == configured:
        overridden = free_port(configured)
    config(root / "config.json", configured)
    with running(application, "--host", "127.0.0.1", "--port", str(overridden), "--log-level", "debug") as (child, out, err):
        wait_ready(child, err, overridden)
        assert not listening(configured)
        args = assert_spy(env, chosen, root)
        assert args[-6:] == ["--host", "127.0.0.1", "--port", str(overridden), "--log-level", "debug"]
    wait_closed(overridden)
    wait_closed(configured)


@pytest.mark.parametrize("failure", ["missing", "empty-override", "malformed", "invalid-port", "interpreter-read"])
def test_config_read_errors_exit_before_uvicorn(application, failure):
    root, outside, env = application
    choose(application, ".venv")
    port = free_port()
    path = root / "config.json"
    config(path, port)
    if failure == "missing":
        env["CHAT2API_CONFIG"] = str(root / "missing.json")
    elif failure == "empty-override":
        env["CHAT2API_CONFIG"] = ""
    elif failure == "malformed":
        path.write_text('{"server":', encoding="utf-8")
    elif failure == "invalid-port":
        path.write_text('{"server":{"port":"invalid"},"models":{}}', encoding="utf-8")
    else:
        env["LAUNCHER_TEST_FAIL_READ"] = "1"
    default_was_closed = not listening(8000)
    with running(application) as (child, out, err):
        assert child.wait(timeout=10) != 0
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace")
        if failure in ("missing", "empty-override"):
            assert "FileNotFoundError" in stderr
        elif failure == "malformed":
            assert "JSONDecodeError" in stderr
        elif failure == "invalid-port":
            assert "port" in stderr
        else:
            assert child.returncode == 42
        assert not any(call["args"][:2] == ["-m", "uvicorn"] for call in records(env))
        assert not listening(port)
        if default_was_closed:
            assert not listening(8000)
    wait_closed(port)


def test_timeout_and_assertion_cleanup_reap_owned_group(application):
    root, outside, env = application
    choose(application, ".venv")
    port = free_port()
    config(root / "config.json", port)
    env["LAUNCHER_TEST_FREEZE_READ"] = "1"
    with pytest.raises(TimeoutError):
        with running(application) as (child, out, err):
            wait_ready(child, err, port, timeout=0.3)
    assert child.poll() is not None
    env.pop("LAUNCHER_TEST_FREEZE_READ")
    with pytest.raises(AssertionError, match="test-owned failure"):
        with running(application) as (child, out, err):
            wait_ready(child, err, port)
            raise AssertionError("test-owned failure")
    assert child.poll() is not None
    wait_closed(port)
```

- [ ] **Step 2: Run against the original launcher and observe the configured-port failure.**

```bash
python -m pytest tests/test_launcher.py -q -x
```

Expected: the original launcher fails the real configured-socket test (it may bind 8000 or fail early if 8000 is occupied). Its process group is still terminated and reaped. Do not run `./start.sh` in the live repository to obtain this evidence; the test copies the script and real app modules to a temporary directory.

- [ ] **Step 3: Replace start.sh with the exact approved script.**

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

- [ ] **Step 4: Run launcher acceptance and the full existing B suite.**

```bash
bash -n start.sh
python -m pytest tests/test_launcher.py -q
python -m pytest
git diff --check
git diff --name-only
```

Expected: PASS with no failures; only `start.sh` and the added `tests/test_launcher.py` differ from the inspected Target B base. If the selected checkout has no activated test environment, invoke its existing conventional venv interpreter for `-m pytest`; do not change dependencies, source modules, or the script's interpreter rules. The socket/HTTP cases are mandatory, never silently skipped. The negative assertion for 8000 is conditional only on preexisting occupancy, recorded separately by the test.

- [ ] **Step 5: Commit Target B only.**

```bash
git add start.sh tests/test_launcher.py
git commit -m "fix(launcher): honor configured host and port with one interpreter"
```

Record `git rev-parse HEAD` with the absolute Target B execution checkout path in the task report. Keep B separate from A; no merge/publish/delivery occurs in this task.

## Task 14: Verify the real cross-target gate and close the acceptance record

**Implementer tier:** Advanced

**Files:**

- Create/Test (Target A): `/data/home/guest/Development/ai/ai-manager/tests/test_launcher_gate_integration.py`.
- Modify (Target A): `/data/home/guest/Development/ai/ai-manager/README.md:1-220` (cross-target test command).

**Interfaces:**

- Consumes: A `services.launcher_gate.probe_launcher(app_dir: Path, *, timeout_s: float = 10.0) -> LauncherProbeResult`; A `services.app_interpreter.resolve_app_interpreter(app_dir: Path) -> Path`; Task 13's recorded B checkout containing `app/`, `providers/`, fixed executable `start.sh` and no changed production Python. Source B modules are read/copied only.
- Consumes: existing B conventional venv at its canonical repo, or explicit `CHAT2API_TEST_PYTHON` naming a usable existing interpreter. New environment variable `CHAT2API_LAUNCHER_CHECKOUT` selects the reviewed B execution checkout for acceptance; no live configuration or dotenv is copied. No dependencies are installed.
- Produces: real fixed-launcher pass and original-launcher fail evidence with owned process groups reaped, plus a clean A/B/C scope record. This task changes only A tests/docs; B's commit remains separate. Passing acceptance is the prerequisite to any later joint delivery decision.

- [ ] **Step 1: Write the integration gate fixture and test.**

```python
# tests/test_launcher_gate_integration.py
import os
from pathlib import Path
import shutil
import pytest
from ai_manager.services import launcher_gate
from ai_manager.services.app_interpreter import resolve_app_interpreter

CANONICAL_B = Path("/data/home/guest/Development/ai/chat2api")
BASELINE_LAUNCHER = '''#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
elif [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi
echo "chat2api $(python -c 'from app import __version__; print(__version__)' 2>/dev/null || echo '?')"
echo "Starting (host/port from config.json) ..."
exec python -m uvicorn app.main:app \\
    --timeout-graceful-shutdown 5 \\
    --log-level info \\
    "$@"
'''


@pytest.fixture
def actual_chat2api(tmp_path, monkeypatch):
    source = Path(os.environ.get("CHAT2API_LAUNCHER_CHECKOUT", str(CANONICAL_B)))
    selected = os.environ.get("CHAT2API_TEST_PYTHON")
    if selected is None:
        for candidate in (CANONICAL_B / ".venv/bin/python", CANONICAL_B / "venv/bin/python"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                selected = str(candidate)
                break
    assert selected is not None, "Provide CHAT2API_TEST_PYTHON with the existing chat2api test environment."
    selected = os.path.abspath(selected)  # preserve lexical venv entrypoint, not .resolve()
    assert source.is_dir() and (source / "start.sh").is_file(), "Set CHAT2API_LAUNCHER_CHECKOUT to the reviewed Target B execution checkout."
    root = tmp_path / "copied chat2api"
    root.mkdir()
    for directory in ("app", "providers"):
        shutil.copytree(source / directory, root / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(source / "start.sh", root / "start.sh")
    (root / ".env").write_text("", encoding="utf-8")
    # A sentinel real config must never be read/changed by the echo probe.
    (root / "config.json").write_bytes(b"sentinel config: probe must override this\n")
    interpreter = root / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(selected)
    (interpreter.parent / "activate").write_text('export PATH="' + str(interpreter.parent) + ':$PATH"\n', encoding="utf-8")
    assert resolve_app_interpreter(root) == interpreter
    children = []
    real_popen = launcher_gate.subprocess.Popen
    def capture(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(launcher_gate.subprocess, "Popen", capture)
    return root, children


@pytest.mark.parametrize("fixed", [True, False])
def test_real_launcher_gate_and_cleanup(actual_chat2api, fixed):
    root, children = actual_chat2api
    if not fixed:
        (root / "start.sh").write_text(BASELINE_LAUNCHER, encoding="utf-8")
    (root / "start.sh").chmod(0o755)
    before = (root / "config.json").read_bytes()
    result = launcher_gate.probe_launcher(root)
    assert result.passed is fixed, result.detail + "\n" + result.stderr
    assert children and all(child.poll() is not None for child in children)
    assert all(child.wait(timeout=1) is not None for child in children)
    assert (root / "config.json").read_bytes() == before
    assert not list(root.glob("*.bak")) and not list(root.glob("*.lock"))
```

The baseline body above omits comments only and retains the old launcher behavior. Do not use the installed old launcher against its real config. In the fixture capture only Popen, leaving no ProcessLookupError assertion that could accidentally identify another service by port.

- [ ] **Step 2: Run this integration check with Task 13's B checkout selected.** Bind the actual task-reported checkout and existing test interpreter in the runner environment; never substitute an unreviewed primary `start.sh` for the reviewed B commit.

```bash
PYTHONPATH=src pytest tests/test_launcher_gate_integration.py -q
```

Expected: fixed passes, old fails, both clean up; no skipped acceptance. Interpreter import absence is a failed setup here, not permission to mark a manager-only save as real-launcher evidence.

- [ ] **Step 3: Add the precise cross-target test command to README's development section.**

````markdown
The launcher integration tests need the reviewed chat2api checkout and its existing test interpreter. Set CHAT2API_LAUNCHER_CHECKOUT to that checkout and CHAT2API_TEST_PYTHON to its usable conventional venv entrypoint when it differs from the canonical installation. Then run the full manager suite:

```bash
PYTHONPATH=src pytest tests/
```

Run the launcher and existing service tests separately from the chat2api checkout with its test interpreter. Both repositories must pass before delivery; file-bridge is a read-only reference.
````

- [ ] **Step 4: Run final acceptance and inspect exact ownership.**

```bash
PYTHONPATH=src pytest tests/
git diff --check
git status --short
```

From the assigned B checkout rerun `bash -n start.sh`, its actual test-environment interpreter with `-m pytest tests/test_launcher.py -q`, and `-m pytest`. Read `git -C /data/home/guest/Development/ai/file-bridge status --short` and compare to the captured pre-execution status; do not clean or alter it. Inspect B's `git diff <inspected-base> --name-only` and require exactly `start.sh` plus `tests/test_launcher.py`. A's feature range contains only the A files listed across these tasks plus this plan/spec/design documentation; no production service sources or dependency/version files change.

- [ ] **Step 5: Commit the Target A acceptance files only.**

```bash
git add tests/test_launcher_gate_integration.py README.md
git commit -m "test(launcher): verify real cross-target gate and cleanup"
```

The completion report records A and B checkout paths, commit SHAs, commands/results, the gate pass/fail pair, and any conditional 8000-negative applicability. It must distinguish successful saves from successful supervisor restart and state that merge/publication/delivery remains a separate decision.
