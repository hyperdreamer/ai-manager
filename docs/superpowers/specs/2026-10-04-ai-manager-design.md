# Design Document: AI Manager (PyQt6 Desktop Configuration Tool)

**Date**: 2026-10-04  
**Status**: Approved (Collaborative Design Phase)  
**Topic**: `ai-manager`  
**Repository**: `hyperdreamer/ai-manager` (Public, GitHub)  
**Location**: `/data/home/guest/Development/ai/ai-manager`

---

## 1. Background & Objectives
In `/data/home/guest/Development/ai`, several backend services rely on large language models (LLMs) or transcription models:
- `ai-grammar` (port 8766): checks, polishes, and translates text using an OpenAI-compatible endpoint.
- `textkit` (port 8765): handles OCR and text operations using configurable models.
- `yt2txt` (port 8666): transcribes YouTube/media audio via an audio transcription API.
- Excluded applications: `free-tts` (does not rely on an LLM), `file-bridge` (local file server).
- Provider gateways: `chat2api` (local proxy/provider at `http://localhost:8000`).

Currently, switching models or AI providers requires manual editing of YAML configuration files across directories and manually executing `ai-backends restart <service>`.

**Objectives**:
1. Build a desktop GUI application using **PyQt6** (`ai-manager`).
2. Discover, fetch, and display available models dynamically from configured AI providers via OpenAI-compatible `/v1/models` endpoints.
3. Allow manual model entry or selection from fetched models.
4. Support clean, editable provider presets (e.g. Local One-API, chat2api, Tencent TokenHub, OpenAI).
5. Update application configuration files atomically and safely.
6. Provide one-click service restart actions via `ai-backends restart <service>` commands.
7. Support modern **Light** and **Dark** themes with dynamic runtime switching and persisted preference.

---

## 2. User Interface Design

### 2.1 Selected Architecture: Master-Detail Split View (Option C)
- **Top Toolbar**:
  - Global supervisor status indicator: checks `ai-backends status` (Running / Stopped).
  - Theme toggle: switch between Light Mode and Dark Mode.
  - Refresh button: re-checks service PIDs and logs.
  - Restart Supervisor button: restarts the `ai-backends` supervisor daemon.
- **Left Sidebar**:
  - List of managed target applications: `ai-grammar`, `textkit`, `yt2txt`.
  - Real-time status dot: Green (running) / Gray (stopped).
  - Subtitle on each item showing port and currently assigned active model.
  - Providers Catalog item: manages custom provider presets and default keys.
- **Right Content Area (Application Details)**:
  - Header with app name, running status badge, port, and configuration path.
  - Quick action: "Restart Service Only".
  - **AI Provider Box**:
    - Preset selector dropdown (One-API, chat2api, Tencent TokenHub, OpenAI, Custom).
    - API Base URL input.
    - API Key input (masked by default, supports `$ENV_VAR` references).
    - "🔄 Fetch Available Models" button.
  - **Model Selection Box**:
    - Editable combo box (type-to-filter / custom model entry).
    - Quick pick tag chips showing available models returned by provider.
    - Multi-model support where needed (e.g., `textkit` OCR vs. Text model).
  - **Footer Action Bar**:
    - "Save Config Only" button (updates YAML).
    - "Save & Restart App" button (updates YAML, executes `ai-backends restart <app>`).

### 2.2 Theme Switching
- Theme selection persisted in `~/.config/ai-manager/settings.json`.
- QSS stylesheets engineered for crisp contrast in both Light and Dark themes.

---

## 3. System Architecture & Modules

```
ai-manager/
├── src/
│   └── ai_manager/
│       ├── __init__.py
│       ├── main.py                   # PyQt6 entrypoint & CLI argument handling
│       ├── config/
│       │   ├── app_registry.py       # Metadata for ai-grammar, textkit, yt2txt
│       │   ├── yaml_manager.py       # Safe round-trip YAML reader/writer
│       │   └── presets.py            # Provider presets (URLs, docs, default paths)
│       ├── services/
│       │   ├── supervisor.py         # Subprocess integration with `ai-backends`
│       │   └── model_fetcher.py      # Background worker fetching /v1/models (httpx)
│       ├── ui/
│       │   ├── main_window.py        # Main application window
│       │   ├── app_sidebar.py        # Left sidebar with status dots
│       │   ├── app_detail_view.py    # Right detail view
│       │   ├── theme.py              # Light / Dark theme definitions
│       │   └── widgets/
│       │       ├── model_combo.py    # Editable filterable combo box
│       │       └── status_badge.py   # Status indicator badge
│       └── utils/
│           └── env_resolver.py       # $ENV_VAR resolution without leaking keys
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
- Target files:
  - `ai-grammar/backend/config.yaml`: reads/writes `ai.api_base`, `ai.api_key`, `ai.model`.
  - `textkit/backend/config.yaml`: reads/writes `ai.api_base`, `ai.api_key`, `ai.model` (or `ai.ocr.model` / `ai.text.model`).
  - `yt2txt/backend/config.yaml`: reads/writes `ai.api_base`, `ai.api_key`, `ai.model`.
- Safety:
  - Creates timestamped/backup copies before mutation (`config.yaml.bak`).
  - Writes to a temporary file in the same directory (`config.yaml.tmp.<pid>`) and performs an atomic rename (`os.replace`) to prevent file corruption.
  - Preserves unchanged top-level keys (`server`, `timeout`, `cache`, etc.).

### 4.2 Model Discovery Worker (`model_fetcher.py`)
- Runs in a background `QThread` via `QThreadPool` or `QRunnable`.
- Endpoint protocol:
  - Requests `GET {api_base}/v1/models` (or `GET {api_base}/models`).
  - Header: `Authorization: Bearer {resolved_api_key}`.
  - Timeout: 5s connect, 10s read.
- Response handling:
  - Extracts model IDs from `{"data": [{"id": "model-name"}, ...]}`.
  - Emits Qt signals: `models_fetched(list[str])`, `fetch_failed(str)`.
  - Never blocks the UI event loop.

### 4.3 Service Supervisor Integration (`supervisor.py`)
- Executes `/home/bin/ai-backends status` via `subprocess.run`:
  - Parses lines like `ai-grammar   running  pid=14230 log=...`.
  - Returns dictionary of `{service_name: {"state": "running"|"stopped", "pid": int|None}}`.
- Executes `/home/bin/ai-backends restart <service>` when requested:
  - Emits completion signal and triggers status refresh.

---

## 5. Testing & Verification Plan
1. **Unit Tests**:
   - `test_yaml_manager`: verifies reading existing configs, modifying values, writing atomically, and ensuring non-targeted fields are preserved.
   - `test_model_fetcher`: verifies parsing of standard `/v1/models` responses, fallback endpoints, authentication headers, and network timeout handling.
   - `test_supervisor`: verifies parsing of `ai-backends status` CLI output and command execution formatting.
2. **Integration & UI Tests**:
   - Off-screen PyQt6 tests using `QTest` / `pytest-qt` to verify widget creation, theme switching, model combobox population, and signal dispatch.
   - Verification of the executable `start.sh` script under the user's conda environment.
