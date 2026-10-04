# Technical Specification: AI Manager (PyQt6 Desktop Configuration Tool)

**Document**: `2026-10-04-ai-manager-spec.md`  
**Status**: Draft / Complete Specification  
**Design Reference**: `2026-10-04-ai-manager-design.md`  
**Target Package**: `ai_manager`  
**Python Runtime**: Python >= 3.10  
**Target Framework**: PyQt6 >= 6.5.0  

---

## 1. Overview & Scope

The `ai-manager` application is a native PyQt6 desktop administration dashboard designed to centralize and automate AI provider configuration, model discovery, and service lifecycle management across local backend applications in `/data/home/guest/Development/ai`:
1. `ai-grammar` (Default port: 8766) — Check, polish, and translate text.
2. `textkit` (Default port: 8765) — OCR and text transformations (supports unified `ai.model` or split `ai.ocr.model` & `ai.text.model`).
3. `yt2txt` (Default port: 8666) — Media and YouTube audio transcription via `/v1/audio/transcriptions`.

The tool runs alongside the `ai-backends` process supervisor, providing:
- Asynchronous discovery of available models from OpenAI-compatible endpoints (`/v1/models` and fallback `/models`).
- Round-trip YAML reading/updating preserving comments, blank lines, and structure via `ruamel.yaml`.
- Real-time supervisor process monitoring and backend restart triggers without blocking the UI.
- In-memory dirty-state management preventing accidental data loss when switching tabs or closing.
- Light and Dark UI themes with dynamic runtime switching.

---

## 2. Data Models and Classes

All models are strongly typed using Pydantic v2 or standard dataclasses where PyQt signal compatibility is preferred.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class ServiceRunState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class ProviderPreset(BaseModel):
    """Preconfigured AI provider template."""
    id: str = Field(..., description="Unique provider key, e.g., 'oneapi'")
    name: str = Field(..., description="Human-readable label, e.g., 'Local One-API / New-API'")
    api_base: str = Field(..., description="Base URL, e.g., 'http://localhost:3000'")
    default_key_env: Optional[str] = Field(None, description="Suggested env var name, e.g., '$ONEAPI_API_KEY'")
    docs_url: Optional[str] = Field(None, description="Documentation or web console link")
    description: str = Field("", description="Usage instructions or notes")


class AppAIConfig(BaseModel):
    """Represents the in-memory or persisted AI configuration for an app."""
    app_id: str
    config_path: Path
    api_base: str = ""
    api_key: str = ""
    
    # Textkit multi-model handling
    is_split_model: bool = False
    model: str = ""                # Used when is_split_model is False
    ocr_model: str = ""            # Used when is_split_model is True (textkit only)
    text_model: str = ""           # Used when is_split_model is True (textkit only)
    
    # Raw comment/node references retained by ruamel.yaml
    raw_roundtrip_doc: Optional[Any] = Field(None, exclude=True)


class AppMetadata(BaseModel):
    """Static registration metadata for supported backends."""
    app_id: str
    name: str
    port: int
    working_dir: Path
    config_rel_path: Path
    supports_split_models: bool = False
    model_type: Literal["llm", "transcription", "multimodal"] = "llm"


class ServiceStatus(BaseModel):
    """Runtime process status parsed from ai-backends."""
    name: str
    state: ServiceRunState = ServiceRunState.UNKNOWN
    pid: Optional[int] = None
    logfile: Optional[Path] = None


class SupervisorStatus(BaseModel):
    """Global supervisor daemon status."""
    is_running: bool = False
    supervisor_pid: Optional[int] = None
    services: Dict[str, ServiceStatus] = Field(default_factory=dict)
    timestamp: str = ""


class ModelFetchRequest(BaseModel):
    """Request payload sent to background model fetcher worker."""
    token: int
    api_base: str
    api_key: str


class ModelFetchResponse(BaseModel):
    """Result emitted by background model fetcher worker."""
    token: int
    success: bool
    models: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    endpoint_used: Optional[str] = None


class UserSettings(BaseModel):
    """Global user settings persisted in ~/.config/ai-manager/settings.json."""
    theme: ThemeMode = ThemeMode.DARK
    poll_interval_ms: int = 4000
    custom_presets: List[ProviderPreset] = Field(default_factory=list)
```

---

## 3. Configuration Management & YAML Protocol

### 3.1 YAML Engine Rules (`ruamel.yaml`)
To ensure zero corruption of comments, indentation, commented-out provider examples, and formatting:
1. Always instantiate:
   ```python
   from ruamel.yaml import YAML
   yaml = YAML(typ="rt")
   yaml.preserve_quotes = True
   yaml.indent(mapping=2, sequence=4, offset=2)
   yaml.width = 4096  # Prevent premature line wrap
   ```
2. Modifying values MUST be done in-place on existing mapping nodes rather than replacing dicts. This preserves AST line/column attachment for comments.
3. Reading `api_key`: If the raw text starts with `$`, store the exact string in the data model (e.g. `$TENCENTTOKENHUB_API_KEY`). For previewing or making model requests, resolve via `os.environ.get(var_name[1:], "")`.
4. Fallback creation: If `config.yaml` is missing, verify if `config.example.yaml` exists in the same backend folder. If so, copy it over prior to parsing.

### 3.2 App-Specific YAML Rules

#### `ai-grammar` (`ai-grammar/backend/config.yaml`)
- Keys located under top-level `ai:` block:
  - `ai.api_base`: string
  - `ai.api_key`: string (quoted or unquoted)
  - `ai.model`: string
- Example mutation:
  ```python
  doc['ai']['api_base'] = new_base
  doc['ai']['api_key'] = new_key
  doc['ai']['model'] = new_model
  ```

#### `textkit` (`textkit/backend/config.yaml`)
- `textkit` can have either unified `ai.model` OR split `ai.ocr.model` & `ai.text.model`.
- **Case 1: Switching to Split Models**:
  - If `ai.ocr` or `ai.text` does not exist as a map, initialize them:
    ```python
    if 'model' in doc['ai']:
        del doc['ai']['model']
    if 'ocr' not in doc['ai']:
        doc['ai']['ocr'] = {}
    if 'text' not in doc['ai']:
        doc['ai']['text'] = {}
    doc['ai']['ocr']['model'] = ocr_model_name
    doc['ai']['text']['model'] = text_model_name
    ```
- **Case 2: Switching to Unified Model**:
  - Remove `ocr` and `text` subkeys if present, or assign `model`:
    ```python
    if 'ocr' in doc['ai']:
        del doc['ai']['ocr']
    if 'text' in doc['ai']:
        del doc['ai']['text']
    doc['ai']['model'] = unified_model_name
    ```

#### `yt2txt` (`yt2txt/backend/config.yaml`)
- Keys located under top-level `ai:` block:
  - `ai.api_base`: string
  - `ai.api_key`: string
  - `ai.model`: string (typically `gpt-4o-transcribe` or compatible audio model)

### 3.3 Atomic File Writing & Backup Protocol
When saving modifications:
1. Target path: `dest_path = app_config.config_path`
2. Create backup:
   - Timestamp format: `config.yaml.bak` (or `config.yaml.bak.<YYYYmmdd_HHMMSS>`)
   - `shutil.copy2(dest_path, backup_path)`
3. Write to temporary file in the **same directory** to guarantee same filesystem mount for atomic renaming:
   - Temp path: `dest_path.with_name(f"{dest_path.name}.tmp.{os.getpid()}_{uuid.uuid4().hex[:6]}")`
   - Open temp file, execute `yaml.dump(doc, temp_file)`.
   - Flush and `os.fsync(temp_file.fileno())`.
4. Replace atomically:
   - `os.replace(temp_path, dest_path)`
5. Permissions: Retain original file mode (`stat.st_mode`).

---

## 4. Background Model Fetching Protocol

Fetching models over HTTP cannot block the PyQt main GUI thread. The background worker uses `httpx` within a `QRunnable` or `QThread`.

### 4.1 Request & Race-Condition Prevention (Generation Token)
- The controller maintains an integer generation counter: `self._fetch_generation: int = 0`.
- Every time the user clicks "Fetch Available Models" or changes presets/apps:
  ```python
  self._fetch_generation += 1
  token = self._fetch_generation
  worker = ModelFetchWorker(token=token, api_base=base, api_key=key)
  ```
- When a worker emits `finished(token, response)`:
  - Check: `if response.token != self._fetch_generation: return  # Stale, discard silently`.

### 4.2 Endpoint Sequence & Timeout Bounds
1. Resolve API key:
   - If `api_key.startswith("$")`: `resolved_key = os.environ.get(api_key[1:], "")`
   - Else: `resolved_key = api_key`
2. Headers:
   ```python
   headers = {
       "Accept": "application/json",
       "User-Agent": "ai-manager/1.0",
   }
   if resolved_key:
       headers["Authorization"] = f"Bearer {resolved_key}"
   ```
3. HTTP Client bounds:
   - Connect timeout: `5.0` seconds
   - Read timeout: `10.0` seconds
   - Follow redirects: `True`
4. Request sequence:
   - **Step 1**: Target URL = `{api_base.rstrip('/')}/v1/models`
   - **Step 2**: If Step 1 returns HTTP 404 or path error, attempt fallback to `{api_base.rstrip('/')}/models`
   - If both fail, produce a normalized human-readable error (e.g., `HTTP 401 Unauthorized - Check API Key`, `Connection Refused at {api_base}`, `Timeout after 10s`).

### 4.3 Response Normalization
OpenAI-compatible gateways return varying response schemas. The normalizer handles:
1. Standard OpenAI dictionary:
   ```json
   {"data": [{"id": "gpt-4o"}, {"id": "claude-3-5-sonnet"}]}
   ```
   Extracted: `["claude-3-5-sonnet", "gpt-4o"]` (sorted alphabetically).
2. Simple string array:
   ```json
   {"data": ["model-a", "model-b"]}
   ```
3. Direct array root:
   ```json
   [{"id": "model-a"}, {"id": "model-b"}]
   ```
4. Ollama / custom gateway structure:
   ```json
   {"models": [{"name": "llama3:latest"}, {"name": "mistral"}]}
   ```
5. Deduplicate and sort all returned IDs case-insensitively.

---

## 5. `ai-backends` Supervisor Integration

The tool supervises services using the bash command `/data/home/guest/Development/ai/ai-backends`.

### 5.1 CLI Status Parsing
Running `ai-backends status` outputs structured lines:
```text
[2026-10-04 11:47:44] supervisor running: 34491
ai-grammar   running  pid=2333046 log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
textkit      running  pid=2336549 log=/home/henry/.cache/ai-backends/logs/textkit.log
yt2txt       running  pid=42973 log=/home/henry/.cache/ai-backends/logs/yt2txt.log
chat2api     running  pid=42974 log=/home/henry/.cache/ai-backends/logs/chat2api.log
file-bridge  running  pid=42975 log=/home/henry/.cache/ai-backends/logs/file-bridge.log
```
Or when supervisor is dead:
```text
[2026-10-04 11:47:44] supervisor not running
ai-grammar   stopped  pid=- log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
...
```

#### Parsing Regular Expressions
```python
import re

SUPERVISOR_RUNNING_RE = re.compile(
    r"^\[.*?\]\s+supervisor running:\s+(?P<pid>\d+)", re.MULTILINE
)
SUPERVISOR_NOT_RUNNING_RE = re.compile(
    r"^\[.*?\]\s+supervisor not running", re.MULTILINE
)
SERVICE_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z0-9_\-]+)\s+(?P<state>running|stopped)\s+pid=(?P<pid>\d+|-)\s+log=(?P<log>\S+)",
    re.MULTILINE,
)
```

### 5.2 Status Polling & Asynchronous Command Execution
1. Polling:
   - A `QTimer` triggers every 4000ms.
   - Runs `ai-backends status` non-blockingly via `QProcess`.
   - On completion, emits `supervisor_status_updated(SupervisorStatus)`.
2. Service Restart:
   - Executing "Restart": runs `ai-backends restart <app_name>`.
   - When triggered, UI sets the app state immediately to `ServiceRunState.TRANSITIONING`.
   - Does not freeze the UI; emits `restart_completed(app_name, success, message)`.
3. Supervisor-Dead Detection & Recovery:
   - If `supervisor.is_running` is `False`:
     - The top toolbar displays a prominent warning indicator: `"Supervisor Inactive"`.
     - Action button switches to `"Start Supervisor"`.
     - Clicking "Start Supervisor" runs `ai-backends start` in a detached background process or offers a terminal launch command.
     - Individual "Restart" buttons display a tooltip warning: *"Supervisor is stopped; restarting requires the supervisor watchdog or manual ./start.sh."*

---

## 6. PyQt6 UI Architecture & State Management

### 6.1 Widget Hierarchy

```
MainWindow (QMainWindow)
│
├── TopToolBar (QToolBar)
│   ├── QLabel ("Supervisor: ")
│   ├── SupervisorStatusBadge (QWidget: dot + text "Running (PID 34491)")
│   ├── QToolButton ("Start/Restart Supervisor")
│   ├── QSeparator
│   ├── QToolButton ("Refresh (F5)")
│   ├── QWidget (Expanding spacer)
│   └── QToolButton ("Theme Toggle: 🌙 / ☀️")
│
└── CentralWidget (QWidget: QHBoxLayout)
    └── QSplitter (Qt.Orientation.Horizontal)
        ├── AppSidebar (QListWidget or custom QFrame list)
        │   ├── AppSidebarItem ("ai-grammar", port 8766, model chip, dirty indicator "*")
        │   ├── AppSidebarItem ("textkit", port 8765, model chip, dirty indicator "*")
        │   ├── AppSidebarItem ("yt2txt", port 8666, model chip, dirty indicator "*")
        │   └── ProvidersCatalogItem ("⚙️ Provider Presets")
        │
        └── ContentArea (QStackedWidget)
            ├── AppDetailView (for selected app)
            │   ├── AppHeaderBar
            │   │   ├── QLabel (App Title + Port)
            │   │   ├── StatusBadge (Running / Stopped / Transitioning)
            │   │   └── QPushButton ("Restart Service Only")
            │   │
            │   ├── MissingConfigBanner (QFrame, hidden by default, shown if config.yaml missing)
            │   │   ├── QLabel ("config.yaml missing. config.example.yaml available.")
            │   │   └── QPushButton ("Create config.yaml from example")
            │   │
            │   ├── QScrollArea
            │   │   └── FormLayoutContainer
            │   │       ├── ProviderGroupBox ("AI Provider Configuration")
            │   │       │   ├── QComboBox (Preset dropdown: One-API, chat2api, TokenHub, OpenAI, Custom)
            │   │       │   ├── QLineEdit (Base URL)
            │   │       │   ├── APIKeyInputWidget (QLineEdit masked + Eye toggle button)
            │   │       │   └── QPushButton ("🔄 Fetch Available Models") + QProgressBar (indeterminate)
            │   │       │
            │   │       ├── ModelGroupBox ("Model Configuration")
            │   │       │   ├── (If textkit) QCheckBox ("Split OCR and Text models")
            │   │       │   ├── [Single Model Mode]:
            │   │       │   │   ├── ModelComboBox (Editable, filterable)
            │   │       │   │   └── ModelChipsScrollArea (FlowLayout of clickable QToolButtons)
            │   │       │   └── [Split Model Mode - textkit only]:
            │   │       │       ├── QLabel ("OCR Model:") + ModelComboBox + Chips
            │   │       │       └── QLabel ("Text Model:") + ModelComboBox + Chips
            │   │       │
            │   │       └── AdvancedSettingsGroupBox (Collapsible, timeouts preview)
            │   │
            │   └── FooterActionBar (QFrame)
            │       ├── DirtyNoticeLabel ("⚠️ Unsaved changes pending")
            │       ├── QWidget (Expanding spacer)
            │       ├── QPushButton ("Discard Changes")
            │       ├── QPushButton ("Save Config Only")
            │       └── QPushButton ("Save & Restart App" - Primary Styled)
            │
            └── ProvidersCatalogView (for presets management)
                ├── QListWidget (Registered Presets)
                └── PresetEditForm (Name, Base URL, Default Env Key, Docs URL)
```

### 6.2 In-Memory Dirty Tracking
To allow seamless navigation between applications without accidental loss of entered keys/models:
1. State Store:
   ```python
   class StateManager:
       # app_id -> original AppAIConfig loaded from disk
       _saved_configs: Dict[str, AppAIConfig] = {}
       # app_id -> draft AppAIConfig with user edits
       _draft_configs: Dict[str, AppAIConfig] = {}
       
       def is_dirty(self, app_id: str) -> bool:
           if app_id not in self._draft_configs:
               return False
           return self._draft_configs[app_id] != self._saved_configs[app_id]
           
       def has_any_dirty(self) -> bool:
           return any(self.is_dirty(app_id) for app_id in self._saved_configs)
   ```
2. UI Feedback:
   - Sidebar item displays an asterisk `*` badge when `is_dirty(app_id) == True`.
   - Footer bar shows "⚠️ Unsaved changes pending" and enables "Discard" and "Save" buttons.
3. Window Close Interception:
   - Override `closeEvent(event: QCloseEvent)`:
   - If `has_any_dirty()`:
     - Prompt standard `QMessageBox`: *"You have unsaved changes in [app names]. Discard and quit?"*
     - If rejected: `event.ignore()`, else `event.accept()`.

### 6.3 Light & Dark QSS Theme Specifications

Themes are applied at the `QApplication` level via `.setStyleSheet()`.

#### Dark Theme (`dark.qss`)
```css
QMainWindow, QWidget#centralWidget {
    background-color: #1e1e24;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

/* Sidebar */
QListWidget#sidebarList {
    background-color: #18181c;
    border: none;
    border-right: 1px solid #2d2d34;
    padding: 8px 4px;
}
QListWidget#sidebarList::item {
    border-radius: 6px;
    padding: 10px 12px;
    margin: 2px 4px;
    color: #b0b0b8;
}
QListWidget#sidebarList::item:selected {
    background-color: #2b2d3a;
    color: #ffffff;
    font-weight: 600;
}
QListWidget#sidebarList::item:hover:!selected {
    background-color: #222228;
}

/* Group Boxes & Containers */
QGroupBox {
    background-color: #24242c;
    border: 1px solid #32323c;
    border-radius: 8px;
    margin-top: 24px;
    padding: 16px;
    font-weight: 600;
    color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}

/* Inputs */
QLineEdit, QComboBox {
    background-color: #18181c;
    border: 1px solid #3a3a46;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f0f0f0;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #4f80ff;
}

/* Buttons */
QPushButton {
    background-color: #2e303e;
    color: #e0e0e0;
    border: 1px solid #3e4052;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #383a4c;
}
QPushButton:pressed {
    background-color: #282a36;
}
QPushButton#primaryActionBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}
QPushButton#primaryActionBtn:hover {
    background-color: #1d4ed8;
}

/* Status Badges */
QLabel#statusBadgeRunning {
    color: #10b981;
    font-weight: 600;
}
QLabel#statusBadgeStopped {
    color: #9ca3af;
}
QLabel#statusBadgeTransitioning {
    color: #f59e0b;
}

/* Model Chips */
QToolButton#modelChip {
    background-color: #282a36;
    border: 1px solid #44475a;
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 11px;
    color: #c0c4d0;
}
QToolButton#modelChip:hover {
    background-color: #3b3e52;
    border-color: #6272a4;
    color: #ffffff;
}
```

#### Light Theme (`light.qss`)
```css
QMainWindow, QWidget#centralWidget {
    background-color: #f8fafc;
    color: #1e293b;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

/* Sidebar */
QListWidget#sidebarList {
    background-color: #ffffff;
    border: none;
    border-right: 1px solid #e2e8f0;
    padding: 8px 4px;
}
QListWidget#sidebarList::item {
    border-radius: 6px;
    padding: 10px 12px;
    margin: 2px 4px;
    color: #64748b;
}
QListWidget#sidebarList::item:selected {
    background-color: #eff6ff;
    color: #1d4ed8;
    font-weight: 600;
}
QListWidget#sidebarList::item:hover:!selected {
    background-color: #f1f5f9;
}

/* Group Boxes & Containers */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 24px;
    padding: 16px;
    font-weight: 600;
    color: #0f172a;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}

/* Inputs */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 10px;
    color: #0f172a;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}

/* Buttons */
QPushButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background-color: #f1f5f9;
}
QPushButton#primaryActionBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}
QPushButton#primaryActionBtn:hover {
    background-color: #1d4ed8;
}

/* Status Badges */
QLabel#statusBadgeRunning {
    color: #059669;
    font-weight: 600;
}
QLabel#statusBadgeStopped {
    color: #64748b;
}
QLabel#statusBadgeTransitioning {
    color: #d97706;
}

/* Model Chips */
QToolButton#modelChip {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 11px;
    color: #475569;
}
QToolButton#modelChip:hover {
    background-color: #e2e8f0;
    border-color: #94a3b8;
    color: #0f172a;
}
```

---

## 7. Error Handling & Boundary Conditions

1. **Permission / File Access Errors**:
   - If a YAML file is read-only or permission is denied, wrap save operation in a `try...except OSError as e:` block.
   - Display a non-modal warning notification banner in the UI with exact OS error message.
2. **Malformed Existing YAML**:
   - If parsing an existing `config.yaml` fails with `ruamel.yaml.YAMLError`, do NOT overwrite the file.
   - Show an error dialog detailing line and column, disable the "Save" button to prevent destroying corrupted files, and offer an option to restore from `config.yaml.bak` or `config.example.yaml`.
3. **Network Timeouts & Non-JSON Endpoints**:
   - When hitting `/v1/models` on a non-OpenAI endpoint (e.g. an HTML 404 page or standard web server), catch `httpx.HTTPError` and `json.JSONDecodeError`.
   - Provide clean error message in the UI: *"Received invalid JSON from {api_base}/v1/models (Status {status_code})"*.
4. **Environment Variable Expansion**:
   - When displaying an API key defined as `$VAR_NAME`:
     - Show the text `$VAR_NAME` in the input field.
     - Add a small label next to it indicating whether the env var is currently set in the environment: `✓ Resolved (len: 48)` or `⚠️ $VAR_NAME is unset in environment`.

---

## 8. Test Fixtures and Verification Suite

### 8.1 Test Matrix
1. `tests/test_yaml_manager.py`:
   - Round-trip fidelity test: Read real fixture with commented-out models, change `model` to `test-model`, serialize, re-read. Assert comments and surrounding whitespace are character-identical outside the changed value.
   - Split-to-unified transition test on `textkit`: Verify switching from `ai.ocr.model` & `ai.text.model` to `ai.model` cleanly removes sub-dictionaries and vice-versa.
   - Atomic replacement failure test: Simulate write permission error during `os.replace`; assert original file and `.bak` file remain untouched.
2. `tests/test_model_fetcher.py`:
   - Mock HTTP server with `respx`:
     - Response A: Standard OpenAI `{"data": [{"id": "gpt-4"}]}`.
     - Response B: Fallback endpoint `{"models": [{"name": "ollama-model"}]}`.
     - Response C: 404 on `/v1/models` followed by 200 on `/models`.
     - Response D: Generation token race: fire token 1 (sleep 100ms), fire token 2 (immediate), assert only token 2 updates state.
3. `tests/test_supervisor.py`:
   - Test CLI parser on sample output strings from `ai-backends status`.
   - Test supervisor dead / alive status extraction.
4. `tests/test_ui_state.py`:
   - Using `pytest-qt` (`qtbot`):
     - Load MainWindow, select `ai-grammar`.
     - Modify model name in text field.
     - Assert sidebar shows dirty indicator `*`.
     - Switch to `textkit`. Assert `ai-grammar` edits preserved in in-memory draft.

### 8.2 Fixtures Directory Structure
```
tests/fixtures/
├── ai_grammar_config.yaml          # Sample config with rich comments & alternative providers
├── textkit_unified_config.yaml     # Textkit config using ai.model
├── textkit_split_config.yaml       # Textkit config using ai.ocr.model + ai.text.model
└── yt2txt_config.yaml              # Yt2txt config with $OPENAI_API_KEY
```

---

## 9. Launch & Execution Environment

### 9.1 `start.sh` Wrapper
A shell script in `ai-manager/start.sh` handles environment initialization and execution:
```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"

if command -v conda &>/dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate daily || true
fi

export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH:-}"
exec python -m ai_manager.main "$@"
```

### 9.2 Package Metadata (`pyproject.toml`)
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-manager"
version = "0.1.0"
description = "Desktop administration tool for local AI backends"
authors = [{ name = "Henry", email = "henry@local" }]
dependencies = [
    "PyQt6>=6.5.0",
    "pydantic>=2.0.0",
    "ruamel.yaml>=0.18.0",
    "httpx>=0.25.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-qt>=4.2.0",
    "respx>=0.20.0",
]

[project.scripts]
ai-manager = "ai_manager.main:main"
```
