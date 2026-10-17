# Supervisor Auto-Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.

**Goal:** Make launching `ai-manager` perform exactly one automatic `ai-backends start`, and only when the status probe positively reports that the supervisor is not running — without ever disrupting a running supervisor, without overriding manual intent, and without letting tests touch live backends.

**Architecture:** `SupervisorManager` gains two monotone process-wide class attributes (`_autostart_consumed`, `_autostart_cancel_epoch`) plus one per-manager epoch snapshot. The entry point claims the attempt before probing; the status completion callback captures the epoch, clears the instance field, emits status, then authorises a single silent spawn only if the epoch is still current and the probe output positively reports "not running". `MainWindow` calls the entry point instead of a plain refresh and cancels on quit. Test safety is two autouse `conftest.py` fixtures: an environment guard plus an inert status-process wrapper and a destructive-spawn recorder.

**Tech Stack:** Python 3.10+, PyQt6 (`QProcess`, `QTimer`, `QApplication.aboutToQuit`), pytest, pytest-qt. No new dependencies.

## Global Constraints
- Python 3.10+ and PyQt6; no new third-party dependencies.
- Strict TDD: the failing test exists and has been observed red before the matching implementation line is written.
- Tests run with exactly: `source /home/bin/yesconda && conda activate daily && AI_WORKSPACE_ROOT=/home/henry/Development/ai PYTHONPATH=src python -m pytest tests/ -q`.
- Qt tests run headless; `tests/conftest.py` already sets `QT_QPA_PLATFORM=offscreen`.
- All paths in tasks are repository-relative.
- Authoritative documents: `docs/superpowers/specs/2026-10-17-supervisor-auto-start-spec.md` (rev6) and `docs/superpowers/specs/2026-10-17-supervisor-auto-start-design.md`. Where they disagree, the spec wins.
- Never invoke a real `ai-backends` command in any test. Every process-wide attribute is read and written as `SupervisorManager.<name>`, never through `self`.
- Do not modify `pyproject.toml`, `start.sh`, or `ai-backends`.

## Task 1: Add Test Safety Fixtures and Shared Doubles
**Implementer tier:** Standard
### Files:
- Create: `tests/__init__.py`
- Create: `tests/helpers.py`
- Modify: `tests/conftest.py`

### Interfaces:
- `tests/__init__.py` is an empty file; it exists so `from tests.helpers import ...` collects deterministically.
- `tests/helpers.py` produces exactly:
```python
class FakeStatusProcess:
    def __init__(self) -> None:
        self._state: QProcess.ProcessState = QProcess.ProcessState.NotRunning
        self.starts: list[list[str]] = []
    def state(self) -> QProcess.ProcessState: ...
    def start(self, program: str, args: list[str] | None = None) -> None: ...
    def finish(self) -> None: ...

def install_fake_status_process(original_init): ...
```
- `FakeStatusProcess.start` appends `[program, *(args or [])]` to `starts` and sets `_state` to `Running`; `finish()` sets `_state` to `NotRunning`. It must never spawn anything.
- `install_fake_status_process(original_init)` returns a wrapper `wrapped(self, *args, **kwargs)` that calls `original_init(self, *args, **kwargs)` and then sets `self._status_process = FakeStatusProcess()`, returning `None`.
- `tests/conftest.py` gains four fixtures, all function-scoped:

```python
@pytest.fixture(autouse=True)
def _disable_supervisor_autostart(monkeypatch): ...      # setenv(AUTOSTART_DISABLE_ENV, "1")

@pytest.fixture(autouse=True)
def _no_destructive_supervisor_commands(monkeypatch): ... # records/stubs start|stop, asserts empty at teardown

@pytest.fixture(autouse=True)
def _no_real_status_probe(monkeypatch): ...              # patches SupervisorManager.__init__ with install_fake_status_process

@pytest.fixture
def autostart_enabled(monkeypatch): ...                   # delenv + reset both class attributes + yield
```

- `_no_destructive_supervisor_commands` wraps `subprocess.Popen`: if `list(argv)[1]` is `"start"` or `"stop"` it appends to a list and returns `MagicMock()`; otherwise it delegates to the real `Popen`. After `yield` it asserts the list is empty.

### Checklist:
- [ ] Write `tests/__init__.py` (empty) and `tests/helpers.py` first.
- [ ] Add the four fixtures to `tests/conftest.py` without disturbing `mock_tray_available` or the `QT_QPA_PLATFORM` line.
- [ ] Confirm the safety net actually covers existing suites by running them unchanged:
```bash
source /home/bin/yesconda && conda activate daily && AI_WORKSPACE_ROOT=/home/henry/Development/ai PYTHONPATH=src python -m pytest tests/test_main_window.py tests/test_main_window_tray.py tests/test_mnemonic.py tests/test_supervisor.py -q
```
- [ ] All of those must still pass with the new autouse fixtures active. If any fails, fix the fixture — never weaken the guard.
- [ ] Prove the guard bites: temporarily add a throwaway test that calls `subprocess.Popen(["/bin/true", "start"])`, confirm it fails at teardown, then delete it.

### Commit Instructions:
- [ ] Stage only `tests/__init__.py`, `tests/helpers.py`, `tests/conftest.py`.
- [ ] Commit with message `test: add supervisor autostart safety fixtures and shared doubles`.

## Task 2: Add Autostart State, Guards, and Lifetime Tests
**Implementer tier:** Advanced
### Files:
- Modify: `src/ai_manager/services/supervisor.py`
- Create: `tests/test_supervisor_autostart.py`

### Interfaces:
- Module constants:
```python
AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"
_AUTOSTART_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})
```
- Class attributes on `SupervisorManager` (class-owned, never shadowed):
```python
_autostart_consumed: ClassVar[bool] = False
_autostart_cancel_epoch: ClassVar[int] = 0
_ACTIONS: ClassVar[dict] = {
    "start": ("start_supervisor", "Supervisor started.", "Failed to start supervisor: {}"),
    "stop": ("stop_supervisor", "Supervisor stopped.", "Failed to stop supervisor: {}"),
}
```
- `__init__` additionally sets `self._autostart_epoch: Optional[int] = None`.
- New/changed methods, exactly these signatures:
```python
@staticmethod
def autostart_disabled() -> bool: ...
def start_if_not_running(self) -> bool: ...
def cancel_pending_autostart(self) -> None: ...
def claim_is_live(self) -> bool: ...
def _spawn_supervisor(self, command: str, *, silent: bool) -> bool: ...
def start_supervisor(self) -> None: ...      # unchanged contract + cancel first
def stop_supervisor(self) -> None: ...       # unchanged contract + cancel first
def _on_status_finished(self, exit_code: int, exit_status) -> None: ...
def _on_status_error(self, error) -> None: ...
```
- Semantics are normative and defined in spec §2.4-§2.10. In particular: guard order in `start_if_not_running` is disabled -> consumed -> busy; the callback clears `self._autostart_epoch` **before** `status_updated.emit(status)`; the epoch guard is the single `claim_epoch != SupervisorManager._autostart_cancel_epoch` comparison, with no `is None` clause; `authorized` requires exit code 0, `NormalExit`, a `SUPERVISOR_NOT_RUNNING_RE` match, and no `SUPERVISOR_RUNNING_RE` match; the automatic spawn passes `silent=True`; the follow-up `refresh_status()` runs only when the spawn returned `True`.
- `_spawn_supervisor` must emit exactly the pre-existing names/messages for `silent=False` so `tests/test_supervisor.py::test_stop_supervisor_runs_stop_command` keeps passing unchanged.

### Checklist:
- [ ] Write `tests/test_supervisor_autostart.py` first with the `probes`, `manager`, `deliver()`, and `arm()` helpers from spec §4.2, and the 19 supervisor-level cases from spec §5 (tests 1-18 and 26, plus 27).
- [ ] `arm()` must assert `start_if_not_running() is True`, exactly one `_status_process.starts` entry, and `manager.claim_is_live() is True`. Every negative-path test calls `arm()`.
- [ ] Run the red suite and confirm the failures are behavioural, not import errors:
```bash
source /home/bin/yesconda && conda activate daily PYTHONPATH=src python -m pytest tests/test_supervisor_autostart.py -q
```
- [ ] Implement the constants, class attributes, `__init__` addition, `autostart_disabled`, `start_if_not_running`, `cancel_pending_autostart`, `claim_is_live`, `_spawn_supervisor`, and rewrite the two callbacks per spec §2.8/§2.9.
- [ ] Rewrite `start_supervisor`/`stop_supervisor` as `cancel_pending_autostart()` followed by `_spawn_supervisor(..., silent=False)` and the trailing refresh on success only.
- [ ] Re-run the focused suite and confirm all cases pass.
- [ ] Verify preservation explicitly:
```bash
source /home/bin/yesconda && conda activate daily PYTHONPATH=src python -m pytest tests/test_supervisor.py -q
```
- [ ] Confirm `tests/test_supervisor.py::test_stop_supervisor_runs_stop_command` passes **without** editing it.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/services/supervisor.py` and `tests/test_supervisor_autostart.py`.
- [ ] Commit with message `feat(supervisor): add one-shot autostart probe and cancellation state`.

## Task 3: Wire MainWindow to Autostart and Quit Cancellation
**Implementer tier:** Standard
### Files:
- Modify: `src/ai_manager/ui/main_window.py`
- Create: `tests/test_main_window_autostart.py`

### Interfaces:
- `MainWindow.__init__` replaces its final `self.supervisor_manager.refresh_status()` with:
```python
app = QApplication.instance()
if app is not None:
    app.aboutToQuit.connect(self.supervisor_manager.cancel_pending_autostart)
self.supervisor_manager.start_if_not_running()
```
- `_exit_application` calls `self.supervisor_manager.cancel_pending_autostart()` before setting `_force_quit` and quitting.
- `_on_supervisor_btn_clicked` collapses to a single `self.supervisor_manager.start_supervisor()` call.
- Window tests must install the fake status process **before** the constructor's probe: patch `SupervisorManager.__init__` with `install_fake_status_process` (already autouse in `conftest.py`) and assert the constructor's claim with `assert_constructor_claim(window, probes)` from spec §4.3. They must not call `arm()` after construction.

### Checklist:
- [ ] Write `tests/test_main_window_autostart.py` first, copying the temp-workspace and settings-isolation fixture style from `tests/test_main_window_tray.py`, and the 7 window-level cases from spec §5 (tests 19-25).
- [ ] Case 23 runs `app.quit()` inside an isolated subprocess with a real event loop, a `QTimer.singleShot(0, app.quit)` and a watchdog; the child must `del os.environ[AUTOSTART_DISABLE_ENV]` first or the case passes vacuously.
- [ ] Case 21 requests the existing `mock_tray_available` fixture and shows the window before closing it.
- [ ] Run the red suite:
```bash
source /home/bin/yesconda && conda activate daily PYTHONPATH=src python -m pytest tests/test_main_window_autostart.py -q
```
- [ ] Apply the three edits to `main_window.py` exactly as listed in Interfaces. Change nothing else in `_on_supervisor_status`, `_on_supervisor_action`, `closeEvent`, or `handle_quit`.
- [ ] Re-run the focused suite and confirm all cases pass.
- [ ] Confirm no regressions in the neighbouring window suites:
```bash
source /home/bin/yesconda && conda activate daily AI_WORKSPACE_ROOT=/home/henry/Development/ai PYTHONPATH=src python -m pytest tests/test_main_window.py tests/test_main_window_tray.py tests/test_mnemonic.py -q
```

### Commit Instructions:
- [ ] Stage only `src/ai_manager/ui/main_window.py` and `tests/test_main_window_autostart.py`.
- [ ] Commit with message `feat(ui): auto-start the supervisor once on launch and cancel it on quit`.

## Task 4: Full-Suite Verification and Mutation Audit
**Implementer tier:** Advanced
### Files:
- Modify: `tests/test_supervisor_autostart.py` (only if a mutation escapes)
- Modify: `src/ai_manager/services/supervisor.py` (only to fix a surfaced defect)
- Modify: `src/ai_manager/ui/main_window.py` (only to fix a surfaced defect)

### Interfaces:
- No new public interfaces. This task proves the delivered behaviour rather than adding to it.

### Checklist:
- [ ] Run the complete required suite with the external workspace supplied:
```bash
source /home/bin/yesconda && conda activate daily AI_WORKSPACE_ROOT=/home/henry/Development/ai PYTHONPATH=src python -m pytest tests/ -q
```
- [ ] Confirm zero failures. `tests/test_e2e_integration.py::test_full_workspace_integration` requires `AI_WORKSPACE_ROOT`; without it, it fails for an unrelated reason and that difference must be stated explicitly in the task report rather than papered over.
- [ ] Run the mutation audit, restoring the source after each probe, and require every row to produce at least one failing test:
  - entry `_autostart_consumed` guard removed
  - entry busy guard removed
  - callback epoch guard removed
  - `authorized` exit-code check removed
  - `authorized` `NormalExit` check removed
  - `authorized` not-running regex removed
  - `authorized` running-regex veto removed
  - automatic `silent=True` changed to `False`
  - `cancel_pending_autostart` stops clearing the instance epoch
  - callback clear moved to after `status_updated.emit`
  - `_on_status_error` stops clearing the instance epoch
  - follow-up `refresh_status()` removed after a successful spawn
- [ ] Record the mutation table in the task report: mutation, catching test name, pass/fail.
- [ ] Prove the safety net with the suite running under an audit wrapper that raises if any real `ai-backends` `start`, `stop`, or `status` reaches `Popen` or `QProcess.start`; report zero launches.
- [ ] Confirm `git status --porcelain` shows only the four intended production/test files plus the new ones from Tasks 1-3.

### Commit Instructions:
- [ ] If the audit required no changes, make no commit and report "verification only".
- [ ] If a fix was needed, stage only the touched files and commit with message `fix(supervisor): close mutation <name> surfaced by the audit`.
