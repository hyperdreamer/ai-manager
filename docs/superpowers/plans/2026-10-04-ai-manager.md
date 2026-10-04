# AI Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ai-manager`, a desktop PyQt6 administration GUI for configuring AI providers, discovering models dynamically via `/v1/models`, atomically modifying YAML configurations with comment preservation (`ruamel.yaml`), controlling service restarts via `ai-backends`, and providing Light/Dark themes.

**Architecture:** Python package under `src/ai_manager` with modular domains: `config` (data models, YAML round-trip parser, app registry, presets), `services` (non-blocking model discovery with generation tokens, async `ai-backends` supervisor runner), `ui` (PyQt6 master-detail window, sidebar with status/dirty indicators, detail view, Light/Dark QSS styling), and `utils` (environment resolution and workspace path discovery).

**Tech Stack:** Python 3.14 (conda `daily`), PyQt6, ruamel.yaml, httpx, pydantic, pytest, pytest-qt.

## Global Constraints

- Python 3.10+ compatibility (primary runtime is Python 3.14 in conda `daily` environment).
- All YAML mutations must preserve comments, formatting, and commented-out blocks using `ruamel.yaml(typ="rt")`.
- Configuration writes must be atomic: write to a temporary file in the same directory, flush and `fsync`, and replace with `os.replace`.
- Network model fetches and supervisor subprocesses must never block the PyQt6 UI thread.
- Exclude `free-tts` and `file-bridge` from managed consumer applications; target `ai-grammar`, `textkit`, and `yt2txt`.
- Every task's requirements implicitly include this section.

## Task 1: Project Scaffolding and Core Data Models

**Implementer tier:** Standard

**Files:**

- Create: `pyproject.toml`
- Create: `src/ai_manager/__init__.py`
- Create: `src/ai_manager/config/models.py`
- Create: `src/ai_manager/utils/env_resolver.py`
- Create: `src/ai_manager/utils/path_locator.py`
- Create: `tests/test_models.py`
- Create: `tests/test_env_resolver.py`

**Interfaces:**

- Produces: `ThemeMode`, `ServiceRunState`, `AppAIConfig`, `AppMetadata`, `ProviderPreset`, `ServiceStatus`, `SupervisorStatus`, `ModelFetchRequest`, `ModelFetchResponse`, `UserSettings` in `src/ai_manager/config/models.py`.
- Produces: `resolve_api_key(value: str) -> str`, `is_env_var_reference(value: str) -> bool` in `src/ai_manager/utils/env_resolver.py`.
- Produces: `find_ai_workspace_root(start_dir: Optional[Path] = None) -> Path` in `src/ai_manager/utils/path_locator.py`.

- [ ] **Step 1: Write the failing tests for models and utilities**

Create `tests/test_models.py` and `tests/test_env_resolver.py` testing Pydantic validation, serialization, environment variable resolution (both `$ENV_VAR` expansion and plaintext keys), and path locator finding the parent workspace.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_models.py tests/test_env_resolver.py`
Expected: FAIL, imports missing.

- [ ] **Step 3: Write the minimal implementation**

Implement `pyproject.toml`, package roots, `src/ai_manager/config/models.py`, `src/ai_manager/utils/env_resolver.py`, and `src/ai_manager/utils/path_locator.py`.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_models.py tests/test_env_resolver.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat(core): scaffold project and core data models"
```

## Task 2: Provider Presets and Application Registry

**Implementer tier:** Standard

**Files:**

- Create: `src/ai_manager/config/presets.py`
- Create: `src/ai_manager/config/app_registry.py`
- Create: `tests/test_app_registry.py`

**Interfaces:**

- Consumes: Models from Task 1.
- Produces: `DEFAULT_PRESETS: List[ProviderPreset]` in `src/ai_manager/config/presets.py`.
- Produces: `get_managed_apps(workspace_root: Path) -> Dict[str, AppMetadata]` in `src/ai_manager/config/app_registry.py` registering `ai-grammar`, `textkit`, and `yt2txt`.

- [ ] **Step 1: Write the failing tests for registry and presets**

Create `tests/test_app_registry.py` verifying that `get_managed_apps` discovers the exact paths to `ai-grammar`, `textkit`, and `yt2txt`, excludes `free-tts` and `file-bridge`, and validates the default presets (One-API, chat2api, Tencent TokenHub, OpenAI).

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_app_registry.py`
Expected: FAIL, module not found.

- [ ] **Step 3: Write the minimal implementation**

Implement presets and app registry with relative path discovery.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_app_registry.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/config/presets.py src/ai_manager/config/app_registry.py tests/test_app_registry.py
git commit -m "feat(config): implement provider presets and target app registry"
```

## Task 3: Round-Trip YAML Configuration Manager

**Implementer tier:** Frontier

**Files:**

- Create: `src/ai_manager/config/yaml_manager.py`
- Create: `tests/fixtures/ai_grammar_config.yaml`
- Create: `tests/fixtures/textkit_unified_config.yaml`
- Create: `tests/fixtures/textkit_split_config.yaml`
- Create: `tests/fixtures/yt2txt_config.yaml`
- Create: `tests/test_yaml_manager.py`

**Interfaces:**

- Consumes: Models and AppMetadata from Tasks 1 & 2.
- Produces: `read_app_config(app_meta: AppMetadata) -> AppAIConfig`, `write_app_config(app_meta: AppMetadata, new_config: AppAIConfig) -> None` in `src/ai_manager/config/yaml_manager.py`.

- [ ] **Step 1: Write the failing tests with realistic YAML fixtures**

Create tests in `tests/test_yaml_manager.py` verifying:
1. `read_app_config` parses `ai-grammar`, `textkit` (both unified and split), and `yt2txt`.
2. `write_app_config` writes atomically via temp files with `.bak` creation.
3. Round-trip preservation: inline comments and commented-out model lines remain intact.
4. Switching `textkit` between unified model and split OCR/Text models.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_yaml_manager.py`
Expected: FAIL, `yaml_manager` does not exist.

- [ ] **Step 3: Write the minimal implementation**

Implement `yaml_manager.py` using `ruamel.yaml(typ="rt")` with atomic `os.replace` and `.bak` backups.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_yaml_manager.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/config/yaml_manager.py tests/
git commit -m "feat(yaml): round-trip yaml manager with comment preservation"
```

## Task 4: Background Model Discovery Worker

**Implementer tier:** Frontier

**Files:**

- Create: `src/ai_manager/services/model_fetcher.py`
- Create: `tests/test_model_fetcher.py`

**Interfaces:**

- Consumes: `ModelFetchRequest`, `ModelFetchResponse` from Task 1.
- Produces: `fetch_models_sync(request: ModelFetchRequest) -> ModelFetchResponse`, `ModelFetchWorker(QRunnable)` with signals `signals.finished(ModelFetchResponse)`.

- [ ] **Step 1: Write the failing tests for model fetching and normalization**

Create `tests/test_model_fetcher.py` using `respx` or mock HTTP endpoints:
1. Standard OpenAI dictionary `{"data": [{"id": "model-1"}]}`.
2. Direct list `{"data": ["model-1"]}` and fallback endpoint `/models` when `/v1/models` gives 404.
3. Network error / timeout handling with descriptive error messages.
4. Generation token propagation for race prevention.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_model_fetcher.py`
Expected: FAIL, module missing.

- [ ] **Step 3: Write the minimal implementation**

Implement `model_fetcher.py` using `httpx` with 5s connect / 10s read timeouts, token tracking, and Qt signals.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_model_fetcher.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/services/model_fetcher.py tests/test_model_fetcher.py
git commit -m "feat(services): implement background model discovery worker"
```

## Task 5: Asynchronous ai-backends Supervisor Integration

**Implementer tier:** Frontier

**Files:**

- Create: `src/ai_manager/services/supervisor.py`
- Create: `tests/test_supervisor.py`

**Interfaces:**

- Consumes: `SupervisorStatus`, `ServiceStatus`, `ServiceRunState` from Task 1.
- Produces: `parse_supervisor_status(output: str) -> SupervisorStatus`, `SupervisorManager(QObject)` with methods `refresh_status()`, `restart_service(service_name: str)`, `start_supervisor()` emitting Qt signals.

- [ ] **Step 1: Write the failing tests for supervisor output parsing and dispatch**

Create `tests/test_supervisor.py`:
1. Parse live `ai-backends status` output (running supervisor + running/stopped service lines).
2. Parse supervisor dead output (`supervisor not running`).
3. Verify restart and start command formulation.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_supervisor.py`
Expected: FAIL, module missing.

- [ ] **Step 3: Write the minimal implementation**

Implement `supervisor.py` with regex parsing and asynchronous `QProcess` dispatching.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_supervisor.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/services/supervisor.py tests/test_supervisor.py
git commit -m "feat(services): implement asynchronous ai-backends supervisor controller"
```

## Task 6: Theme Stylesheets and Custom UI Widgets

**Implementer tier:** Standard

**Files:**

- Create: `src/ai_manager/ui/theme.py`
- Create: `src/ai_manager/ui/widgets/status_badge.py`
- Create: `src/ai_manager/ui/widgets/model_combo.py`
- Create: `src/ai_manager/ui/widgets/api_key_input.py`
- Create: `tests/test_widgets.py`

**Interfaces:**

- Produces: `get_stylesheet(theme: ThemeMode) -> str` in `src/ai_manager/ui/theme.py`.
- Produces: `StatusBadge(QWidget)`, `ModelComboBox(QComboBox)`, `ApiKeyInputWidget(QWidget)` in `src/ai_manager/ui/widgets/`.

- [ ] **Step 1: Write the failing tests for custom widgets and themes**

Create `tests/test_widgets.py` using `pytest-qt` / `QApplication`:
1. Theme QSS strings are non-empty and syntactically valid for both Light and Dark modes.
2. `StatusBadge` sets text and CSS IDs according to `ServiceRunState`.
3. `ApiKeyInputWidget` toggles password echo mode on eye click.
4. `ModelComboBox` supports editable text and item selection.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_widgets.py`
Expected: FAIL, widgets missing.

- [ ] **Step 3: Write the minimal implementation**

Implement stylesheets in `theme.py` and custom widgets in `src/ai_manager/ui/widgets/`.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_widgets.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/ui/theme.py src/ai_manager/ui/widgets/ tests/test_widgets.py
git commit -m "feat(ui): implement Light/Dark theme stylesheets and custom widgets"
```

## Task 7: App Sidebar and Detail View

**Implementer tier:** Frontier

**Files:**

- Create: `src/ai_manager/ui/app_sidebar.py`
- Create: `src/ai_manager/ui/app_detail_view.py`
- Create: `tests/test_app_views.py`

**Interfaces:**

- Consumes: Custom widgets from Task 6, Models from Task 1.
- Produces: `AppSidebar(QWidget)` emitting `app_selected(str)` and displaying dirty asterisks `*`.
- Produces: `AppDetailView(QWidget)` managing provider presets, API key, model selection, live fetch triggering, and save/restart actions.

- [ ] **Step 1: Write the failing tests for sidebar and detail view**

Create `tests/test_app_views.py` using `pytest-qt`:
1. `AppSidebar` renders items for `ai-grammar`, `textkit`, and `yt2txt`, and updates dirty asterisks.
2. `AppDetailView` populates fields from an `AppAIConfig`, fires fetch signals, handles single vs split model toggling for `textkit`, and emits save/restart signals.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_app_views.py`
Expected: FAIL, views missing.

- [ ] **Step 3: Write the minimal implementation**

Implement `app_sidebar.py` and `app_detail_view.py`.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_app_views.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/ui/app_sidebar.py src/ai_manager/ui/app_detail_view.py tests/test_app_views.py
git commit -m "feat(ui): implement application sidebar and detail view"
```

## Task 8: Main Window Integration, State Management, and Supervisor Polling

**Implementer tier:** Frontier

**Files:**

- Create: `src/ai_manager/ui/main_window.py`
- Create: `src/ai_manager/main.py`
- Create: `tests/test_main_window.py`

**Interfaces:**

- Consumes: All UI views, services, and configuration managers.
- Produces: `MainWindow(QMainWindow)` with top toolbar, split layout, 4s `QTimer` polling, dirty draft caching, and close event confirmation.
- Produces: `main()` CLI entrypoint in `src/ai_manager/main.py`.

- [ ] **Step 1: Write the failing tests for MainWindow and StateManager**

Create `tests/test_main_window.py` using `pytest-qt`:
1. Master-detail navigation switches views without losing dirty draft edits.
2. Supervisor status signals update top toolbar badge and sidebar dots.
3. Save and restart action dispatches YAML write and supervisor restart command.
4. Theme toggle switches application stylesheet and saves preference.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `pytest tests/test_main_window.py`
Expected: FAIL, MainWindow missing.

- [ ] **Step 3: Write the minimal implementation**

Implement `main_window.py` and `src/ai_manager/main.py`.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `pytest tests/test_main_window.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ai_manager/ui/main_window.py src/ai_manager/main.py tests/test_main_window.py
git commit -m "feat(app): wire main window, state management, and supervisor polling"
```

## Task 9: Packaging, Start Script, and End-to-End Test Suite Verification

**Implementer tier:** Standard

**Files:**

- Create: `start.sh`
- Create: `README.md`
- Create: `tests/test_e2e_integration.py`

**Interfaces:**

- Consumes: Complete `ai_manager` package.
- Produces: Executable `start.sh` wrapper, documentation, and full test suite passing with `pytest`.

- [ ] **Step 1: Write end-to-end integration test**

Create `tests/test_e2e_integration.py` simulating full lifecycle: discovering sibling applications in `/data/home/guest/Development/ai`, loading real configs, running model normalization, and validating theme transitions.

- [ ] **Step 2: Run end-to-end test and confirm it fails**

Run: `pytest tests/test_e2e_integration.py`
Expected: FAIL, `start.sh` or integrations missing.

- [ ] **Step 3: Implement start.sh and README**

Create `start.sh` with `chmod +x` ensuring conda environment loading, and write complete `README.md`.

- [ ] **Step 4: Run complete test suite and confirm it passes**

Run: `pytest tests/`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add start.sh README.md tests/test_e2e_integration.py
git commit -m "feat(release): add start.sh, documentation, and e2e integration tests"
```
