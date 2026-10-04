# Design Document: AI Manager (PyQt6 Desktop Configuration Tool)

**Date**: 2026-10-04  
**Status**: Approved (Refined Post-Review)  
**Topic**: `ai-manager`  
**Repository**: `hyperdreamer/ai-manager` (Public, GitHub)  
**Location**: `/data/home/guest/Development/ai/ai-manager`

---

## 1. Background & Objectives
In `/data/home/guest/Development/ai`, several backend services rely on large language models (LLMs) or transcription models:
- `ai-grammar` (port 8766): checks, polishes, and translates text using an OpenAI-compatible endpoint.
- `textkit` (port 8765): handles OCR and text operations using configurable models (either unified `ai.model` or split `ai.ocr.model` & `ai.text.model`).
- `yt2txt` (port 8666): transcribes YouTube/media audio via an audio transcription API (`ai.model`).
- Excluded applications: `free-tts` (does not rely on an LLM), `file-bridge` (local file server).
- Provider gateways: `chat2api` (local proxy/provider at `http://localhost:8000`).

Currently, switching models or AI providers requires manual editing of YAML configuration files across directories and manually executing `ai-backends restart <service>`.

**Objectives**:
1. Build a desktop GUI application using **PyQt6** (`ai-manager`).
2. Discover, fetch, and display available models dynamically from configured AI providers via OpenAI-compatible `/v1/models` and `/models` endpoints.
3. Allow manual model entry or selection from fetched models.
4. Support clean, editable provider presets (e.g. Local One-API, chat2api, Tencent TokenHub, OpenAI).
5. Update application configuration files atomically and safely with strict comment and structure preservation (`ruamel.yaml`).
6. Provide one-click service restart actions via `ai-backends restart <service>` commands (run asynchronously via `QProcess` or worker threads, with supervisor daemon state awareness).
7. Support modern **Light** and **Dark** themes with dynamic runtime switching and persisted preference.
8. Provide real-time status indicators with periodic polling (`QTimer`) and unsaved dirty-state protection across app tabs.

---

## 2. User Interface Design

### 2.1 Selected Architecture: Master-Detail Split View (Option C)
- **Top Toolbar**:
  - Global supervisor status indicator: checks `ai-backends status` (Running / Stopped, supervisor PID).
  - Theme toggle: switch between Light Mode and Dark Mode.
  - Refresh button: re-checks service PIDs and logs immediately.
  - Supervisor control button: "Start Supervisor" if stopped, or "Restart Supervisor" if running.
- **Left Sidebar**:
  - List of managed target applications: `ai-grammar`, `textkit`, `yt2txt`.
  - Real-time status dot: Green (running) / Gray (stopped) / Yellow (transitioning).
  - Subtitle on each item showing port, currently assigned active model, and an unsaved dirty badge (`*`) if edits are pending.
  - Providers Catalog item: manages custom provider presets and default keys.
- **Right Content Area (Application Details)**:
  - Header with app name, running status badge, port, and relative configuration path.
  - Quick action: "Restart Service Only".
  - Missing config banner (if `config.yaml` is absent but `config.example.yaml` exists, offer "Create from Example").
  - **AI Provider Box**:
    - Preset selector dropdown (One-API, chat2api, Tencent TokenHub, OpenAI, Custom).
    - API Base URL input.
    - API Key input (masked by default, with an eye toggle 👁️ to reveal, supporting `$ENV_VAR` references displayed cleanly).
    - "🔄 Fetch Available Models" button (with loading spinner/indicator and error callout).
  - **Model Selection Box**:
    - Editable combo box (type-to-filter / custom model entry).
    - Quick pick tag chips showing available models returned by provider.
    - Multi-model toggle for `textkit`: allows configuring a single unified model or split OCR / Text models.
  - **Footer Action Bar**:
    - Dirty state notification ("Unsaved changes").
    - "Discard Changes" button.
    - "Save Config Only" button (updates YAML).
    - "Save & Restart App" button (updates YAML, executes `ai-backends restart <app>`).

### 2.2 Theme Switching
- Theme selection persisted in `~/.config/ai-manager/settings.json`.
- QSS stylesheets engineered for crisp contrast and consistent styling in both Light and Dark themes.

### 2.3 Navigation & Dirty State Protection
- When switching between applications in the left sidebar with unsaved modifications:
  - The UI caches unsaved drafts per application in memory.
  - A subtle `*` indicator is shown on the sidebar item.
  - If the user attempts to close the window or reload, an explicit prompt confirms discarding unsaved changes.

---

## 3. System Architecture & Modules

```
ai-manager/
├── src/
│   └── ai_manager/
│       ├── __init__.py
│       ├── main.py                   # PyQt6 entrypoint & CLI argument handling
│       ├── config/
│       │   ├── app_registry.py       # Metadata & path discovery for ai-grammar, textkit, yt2txt
│       │   ├── yaml_manager.py       # Round-trip YAML reader/writer using ruamel.yaml
│       │   └── presets.py            # Provider presets (URLs, docs, default paths)
│       ├── services/
│       │   ├── supervisor.py         # Asynchronous process runner for `ai-backends` CLI
│       │   └── model_fetcher.py      # Background worker fetching /v1/models (httpx) with cancellation
│       ├── ui/
│       │   ├── main_window.py        # Main application window with QTimer polling
│       │   ├── app_sidebar.py        # Left sidebar with status dots and dirty indicators
│       │   ├── app_detail_view.py    # Right detail view with provider & model controls
│       │   ├── theme.py              # Light / Dark theme definitions
│       │   └── widgets/
│       │       ├── model_combo.py    # Editable filterable combo box
│       │       └── status_badge.py   # Status indicator badge
│       └── utils/
│           ├── env_resolver.py       # $ENV_VAR resolution without leaking keys
│           └── path_locator.py       # Robust discovery of ai workspace root
├── tests/
│   ├── test_app_registry.py
│   ├── test_yaml_manager.py
│   ├── test_model_fetcher.py
│   └── test_supervisor.py
├── pyproject.toml
├── start.sh
└── README.md
```

---

## 4. Component Details & Protocols

### 4.1 YAML Configuration Manager (`yaml_manager.py`)
- **Preservation Engine**: Uses `ruamel.yaml` with `typ="rt"` (round-trip) to preserve comments, indentation, key order, and commented-out alternative blocks.
- **Target Files**:
  - `ai-grammar/backend/config.yaml`: reads/writes `ai.api_base`, `ai.api_key`, `ai.model`.
  - `textkit/backend/config.yaml`: handles both unified `ai.model` and split `ai.ocr.model` / `ai.text.model`.
  - `yt2txt/backend/config.yaml`: reads/writes `ai.api_base`, `ai.api_key`, `ai.model`.
- **Safety**:
  - Automatically creates a timestamped backup copy (`config.yaml.bak`) prior to writing.
  - Writes to a temporary file (`config.yaml.tmp.<pid>`) and executes an atomic replacement (`os.replace`).
  - Missing file handling: if `config.yaml` is missing, copies from `config.example.yaml` upon user confirmation.

### 4.2 Model Discovery Worker (`model_fetcher.py`)
- Runs asynchronously using `QThread` or `QThreadPool`.
- **Generation / Cancellation Token**: Each fetch request is tagged with an incremental integer token. If the user triggers another fetch or switches applications, prior in-flight results are discarded to prevent race conditions.
- **Endpoint Protocol**:
  - Tries `GET {api_base}/v1/models`. If 404 or path error, falls back to `GET {api_base}/models`.
  - Header: `Authorization: Bearer {resolved_api_key}` (if key is set).
  - Timeout: 5s connection timeout, 10s read timeout.
- **Response Parsing**:
  - Normalizes OpenAI-compatible responses:
    - `{"data": [{"id": "model-1"}, ...]}`
    - `{"data": ["model-1", ...]}`
    - `{"models": [{"name": "model-1"}, ...]}`
  - Emits Qt signals: `models_fetched(token: int, models: list[str])`, `fetch_failed(token: int, error_msg: str)`.

### 4.3 Service Supervisor Integration (`supervisor.py`)
- **Asynchronous Execution**:
  - All executions of `ai-backends` (`status`, `restart`, `start`, `stop`) run via `QProcess` or background threads to prevent UI freezes.
- **Supervisor State Invariants**:
  - `status`: parses output of `ai-backends status` into structured status:
    - Supervisor running state (pid or inactive).
    - Per-backend state: `running` (with PID and log path) or `stopped`.
  - If supervisor is **not running** and the user requests a restart:
    - The UI informs the user and offers to start `ai-backends start` (in supervisor mode) or execute the backend's local `start.sh`.
- **Periodic Status Polling**:
  - A `QTimer` triggers a background status refresh every 4 seconds so external changes (crashes, restarts) reflect live in the UI.

---

## 5. Testing & Verification Plan
1. **Unit Tests**:
   - `test_yaml_manager`: verifies reading existing configs, modifying values, writing atomically with `ruamel.yaml`, and ensuring comments and commented-out blocks are 100% preserved.
   - `test_model_fetcher`: verifies parsing of standard and non-standard `/v1/models` responses, fallback endpoints, authentication headers, generation token cancellation, and network timeout handling.
   - `test_supervisor`: verifies parsing of `ai-backends status` CLI output, handling of dead/stale PIDs, and asynchronous command dispatching.
2. **Integration & UI Tests**:
   - Off-screen PyQt6 tests using `pytest-qt` to verify widget creation, theme switching, model combobox population, unsaved dirty state preservation, and signal dispatch.
   - Verification of the executable `start.sh` script under the conda environment (`daily`).
