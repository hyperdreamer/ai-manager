# Technical Specification: Supervisor Auto-Start on Launch

Status: derived from `docs/superpowers/specs/2026-10-17-supervisor-auto-start-design.md`
(design gate: PASS after 5 frontier review rounds).

## 1. Scope

Implements the design's Goal 1-8. Two files change in production code; two test
files and `tests/conftest.py` are added/changed. No UI, no settings, no
`ai-backends` changes.

### Files touched

| File | Change |
| --- | --- |
| `src/ai_manager/services/supervisor.py` | autostart state, entry point, cancellation, factored spawn helper |
| `src/ai_manager/ui/main_window.py` | one constructor call, one `aboutToQuit` connection, cancellation in `_exit_application`, collapsed button branch |
| `tests/conftest.py` | autouse env guard + opt-in autostart fixture |
| `tests/test_supervisor_autostart.py` | new, tests 1-18 |
| `tests/test_main_window_autostart.py` | new, tests 19-25 |

## 2. Module `ai_manager.services.supervisor`

### 2.1 Module constants

```python
AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"
_AUTOSTART_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})
```

### 2.2 Class-level state on `SupervisorManager`

```python
from typing import ClassVar, Optional

class SupervisorManager(QObject):
    _autostart_consumed: ClassVar[bool] = False
    _autostart_cancel_epoch: ClassVar[int] = 0
    _autostart_owner: ClassVar[Optional["SupervisorManager"]] = None
```

Contract:

| Name | Type | Monotone? | Meaning |
| --- | --- | --- | --- |
| `_autostart_consumed` | `bool` | yes (`False -> True` only) | the single process-wide automatic attempt has been claimed |
| `_autostart_cancel_epoch` | `int` | yes (increments) | incremented by every manual Start/Stop/quit cancellation |
| `_autostart_owner` | `Optional[SupervisorManager]` | no | the manager whose probe owns the claim; `None` when no live claim |
| `self._autostart_epoch` | `Optional[int]` | no | per-instance snapshot of the cancel epoch taken at claim time |

All three class attributes are read and written as
`SupervisorManager.<name>`, never via `self`, so no instance attribute can shadow
them.

### 2.3 `__init__` additions

`__init__` must initialise `self._autostart_epoch: Optional[int] = None` in
addition to today's attributes. Everything else is unchanged.

### 2.4 `autostart_disabled() -> bool` (staticmethod)

```python
@staticmethod
def autostart_disabled() -> bool:
    raw = os.environ.get(AUTOSTART_DISABLE_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in _AUTOSTART_DISABLED_VALUES
```

- Absent, empty string, or any other value -> `False` (enabled).
- Case-insensitive; surrounding whitespace stripped (`" yes "` disables).
- `os` must be imported (it is not imported today).

### 2.5 `start_if_not_running() -> bool`

Return value contract: **`True` if and only if this call claimed the attempt and
launched a new `ai-backends status` process.** Every early return is `False`.

```python
def start_if_not_running(self) -> bool:
    if self.autostart_disabled():
        return False
    if SupervisorManager._autostart_consumed:
        return False
    if SupervisorManager._autostart_owner is not None:
        return False
    if self._status_process.state() != QProcess.ProcessState.NotRunning:
        return False
    SupervisorManager._autostart_consumed = True
    SupervisorManager._autostart_owner = self
    self._autostart_epoch = SupervisorManager._autostart_cancel_epoch
    self.refresh_status()
    return True
```

Order of the guards is normative: disabled -> consumed -> owned -> busy. The busy
guard must precede the claim so that `True` implies a probe really started.

### 2.6 `cancel_pending_autostart() -> None`

```python
def cancel_pending_autostart(self) -> None:
    SupervisorManager._autostart_cancel_epoch += 1
    SupervisorManager._autostart_owner = None
```

Must not touch `_autostart_consumed`. Safe to call at any time, including before
any claim and repeatedly.

### 2.7 `_release_autostart_claim() -> None` (internal)

```python
def _release_autostart_claim(self) -> None:
    SupervisorManager._autostart_owner = None
    self._autostart_epoch = None
```

### 2.8 `_on_status_finished(exit_code: int, exit_status) -> None`

Replaces the current body. Required ordering, all four steps:

```python
def _on_status_finished(self, exit_code: int, exit_status) -> None:
    output = self._status_output_buffer.decode("utf-8", errors="replace")
    status = parse_supervisor_status(output)

    claim_epoch = self._autostart_epoch
    claimed_here = (
        SupervisorManager._autostart_owner is self
        and claim_epoch is not None
        and claim_epoch == SupervisorManager._autostart_cancel_epoch
    )
    if claimed_here:
        self._release_autostart_claim()

    self.status_updated.emit(status)

    if not claimed_here:
        return
    authorized = (
        exit_code == 0
        and exit_status == QProcess.ExitStatus.NormalExit
        and SUPERVISOR_NOT_RUNNING_RE.search(output) is not None
        and SUPERVISOR_RUNNING_RE.search(output) is None
    )
    if not authorized:
        return
    if claim_epoch != SupervisorManager._autostart_cancel_epoch:
        return
    if self._spawn_supervisor("start", silent=True):
        self.refresh_status()
```

Normative details:

- `claim_epoch` must be a **local variable** compared after release.
  Comparing `self._autostart_epoch` after `_release_autostart_claim()` would
  always compare `None` and disable the feature.
- `status_updated.emit(status)` keeps its current position in the sense that it
  always fires exactly once per finished probe; the autostart decision is taken
  around it as shown.
- The epoch re-check after the emit is required: Qt receivers run synchronously
  and may cancel.
- `exit_status` is compared to `QProcess.ExitStatus.NormalExit`; never to `0`.

### 2.9 `_on_status_error(error) -> None`

```python
def _on_status_error(self, error) -> None:
    claim_epoch = self._autostart_epoch
    if (
        SupervisorManager._autostart_owner is self
        and claim_epoch is not None
        and claim_epoch == SupervisorManager._autostart_cancel_epoch
    ):
        self._release_autostart_claim()
    status = SupervisorStatus(is_running=False, supervisor_pid=None, services={})
    self.status_updated.emit(status)
```

### 2.10 `_spawn_supervisor(command: str, *, silent: bool) -> bool`

Single implementation of the current `start_supervisor` / `stop_supervisor` spawn
bodies. Byte-compatible with today's messages (see
`supervisor.py:128-145`).

```python
_ACTIONS = {
    "start": ("start_supervisor", "Supervisor started.", "Failed to start supervisor: {}"),
    "stop": ("stop_supervisor", "Supervisor stopped.", "Failed to stop supervisor: {}"),
}

def _spawn_supervisor(self, command: str, *, silent: bool) -> bool:
    action, ok_message, fail_template = self._ACTIONS[command]
    try:
        subprocess.Popen([self.executable, command], start_new_session=True)
    except Exception as e:                      # matches today's breadth
        if not silent:
            self.action_completed.emit(action, False, fail_template.format(e))
        return False
    if not silent:
        self.action_completed.emit(action, True, ok_message)
    return True
```

`command` is restricted to `"start"`/`"stop"`; an unknown value raises
`KeyError`, which is acceptable for an internal helper.

### 2.11 `start_supervisor()` / `stop_supervisor()`

Public behaviour preserved exactly, plus cancellation first:

```python
def start_supervisor(self) -> None:
    self.cancel_pending_autostart()
    if self._spawn_supervisor("start", silent=False):
        self.refresh_status()

def stop_supervisor(self) -> None:
    self.cancel_pending_autostart()
    if self._spawn_supervisor("stop", silent=False):
        self.refresh_status()
```

Observable equivalence with today for every existing consumer:
argv `[exe, command]`, `start_new_session=True`,
`action_completed("start_supervisor"|"stop_supervisor", True, "Supervisor started."|"Supervisor stopped.")`
on success, the `Failed to …` message on exception, and the trailing
`refresh_status()` on success only.

Note: today the trailing `refresh_status()` runs unconditionally after a
successful `Popen`; it still does. On exception, today it does not run either.

## 3. Module `ai_manager.ui.main_window`

### 3.1 Constructor

Replace the final `self.supervisor_manager.refresh_status()` with:

```python
app = QApplication.instance()
if app is not None:
    app.aboutToQuit.connect(self.supervisor_manager.cancel_pending_autostart)
self.supervisor_manager.start_if_not_running()
```

`QApplication` is already imported. The connection is optional-defensive
(`app is not None`) so headless tests that construct a window without a
`QApplication` cannot crash.

### 3.2 `_exit_application`

Add cancellation before quitting:

```python
def _exit_application(self) -> None:
    self.supervisor_manager.cancel_pending_autostart()
    self._force_quit = True
    app = QApplication.instance()
    if app is not None:
        app.quit()
```

### 3.3 `_on_supervisor_btn_clicked`

Collapse the duplicated branch:

```python
def _on_supervisor_btn_clicked(self) -> None:
    self.supervisor_manager.start_supervisor()
```

The button's label switching by status is unchanged.

### 3.4 Untouched

`_on_supervisor_status`, `_on_supervisor_action`, `closeEvent`, `handle_quit`,
the poll timer, the tray wiring. In particular `_on_supervisor_action` keeps
warning only on `success is False`.

## 4. Test infrastructure

### 4.1 `tests/conftest.py` additions

```python
from ai_manager.services.supervisor import AUTOSTART_DISABLE_ENV, SupervisorManager

@pytest.fixture(autouse=True)
def _disable_supervisor_autostart(monkeypatch):
    monkeypatch.setenv(AUTOSTART_DISABLE_ENV, "1")

@pytest.fixture
def autostart_enabled(monkeypatch):
    """Opt in, with process-wide state reset AND restored by monkeypatch."""
    monkeypatch.delenv(AUTOSTART_DISABLE_ENV, raising=False)
    monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)
    monkeypatch.setattr(SupervisorManager, "_autostart_cancel_epoch", 0)
    monkeypatch.setattr(SupervisorManager, "_autostart_owner", None)
    yield
```

Both fixtures are function-scoped. Order matters: `autostart_enabled` depends on
the autouse fixture having set the variable, then deletes it.

### 4.2 `tests/test_supervisor_autostart.py` fixtures

```python
class FakeStatusProcess:
    """Mirror of the QProcess surface SupervisorManager uses."""

    def __init__(self):
        self._state = QProcess.ProcessState.NotRunning
        self.starts: list[list[str]] = []

    def state(self):
        return self._state

    def start(self, program, args):
        self.starts.append([program, *args])
        self._state = QProcess.ProcessState.Running

    def finish(self):
        self._state = QProcess.ProcessState.NotRunning


@pytest.fixture
def probes():
    return FakeStatusProcess()


@pytest.fixture
def manager(qtbot, tmp_path, autostart_enabled, probes, monkeypatch):
    popens: list[list[str]] = []
    def fake_popen(argv, **kwargs):
        popens.append(list(argv))
        popens_kwargs.append(dict(kwargs))
        return MagicMock()
    popens_kwargs: list[dict] = []
    monkeypatch.setattr("ai_manager.services.supervisor.subprocess.Popen", fake_popen)
    m = SupervisorManager(workspace_root=tmp_path)
    qtbot.addWidget  # not applicable; SupervisorManager is a QObject
    qapp = QApplication.instance()   # ensure the QObject lives under a live app
    m._status_process = probes       # replace the real QProcess with the fake
    m.popens = popens
    m.popens_kwargs = popens_kwargs
    return m
```

`deliver()` helper:

```python
def deliver(manager, output, code=0, status=QProcess.ExitStatus.NormalExit):
    manager._status_process.finish()          # explicit state transition
    manager._status_output_buffer.clear()
    manager._status_output_buffer.extend(output.encode("utf-8"))
    manager._on_status_finished(code, status)
```

`arm()` helper (mandatory for every negative-path test):

```python
def arm(manager):
    assert manager.start_if_not_running() is True
    assert len(manager._status_process.starts) == 1
    assert SupervisorManager._autostart_owner is manager
    assert manager._autostart_epoch == SupervisorManager._autostart_cancel_epoch
    return manager._autostart_epoch
```

Reuse `SAMPLE_RUNNING_OUTPUT` / `SAMPLE_STOPPED_OUTPUT` by importing them from
`tests.test_supervisor`, or duplicate them in the new module (duplication is
preferred: importing between test modules couples them).

### 4.3 `tests/test_main_window_autostart.py` fixtures

Copy the workspace/settings fixture approach from `tests/test_main_window_tray.py`
(temp workspace with three fixture configs, `load_user_settings` /
`save_user_settings` monkeypatched), then add `autostart_enabled`, the
`fake_popen`, and a fake status process. Tests here must arm **for real** through
`start_if_not_running()` except test 19, which spies on the entry point.

## 5. Test cases (normative)

Numbering matches design §6. Each row's assertion is mandatory.

### `tests/test_supervisor_autostart.py`

| # | Name | Assertions |
| --- | --- | --- |
| 1 | `starts_once_when_status_reports_stopped` | `arm()`; `deliver(SAMPLE_STOPPED_OUTPUT)`; `manager.popens == [[exe, "start"]]`; `popens_kwargs[0]["start_new_session"] is True` |
| 2 | `does_not_start_when_running` | `arm()`; `deliver(SAMPLE_RUNNING_OUTPUT)`; `manager.popens == []` |
| 3 | `is_one_shot_across_repeated_entry_calls` | `arm()`; `start_if_not_running() is False`; `deliver(stopped)` -> 1 popen; `deliver(stopped)` after a second `start_if_not_running() is False` -> still 1 |
| 4 | `manual_stop_during_first_probe_never_converts_into_a_start` | `arm()`; `stop_supervisor()`; `deliver(stopped)`; `popens == [[exe, "stop"]]` |
| 5 | `manual_start_during_first_probe_never_double_starts` | `arm()`; `start_supervisor()`; `deliver(stopped)`; exactly one `start` argv |
| 6 | `probe_failure_does_not_start_and_a_later_status_cannot_rearm` | `arm()`; `_on_status_error(QProcess.ProcessError.FailedToStart)`; `deliver(stopped)`; `popens == []` |
| 7 | `unrecognised_output_never_starts` | three independent cases in one test with `autostart_enabled` state reset between them via `monkeypatch`-style re-arming: `""`, `"usage: ai-backends [start|status]\n"`, and `SAMPLE_RUNNING_OUTPUT + SAMPLE_STOPPED_OUTPUT`; each: `arm()`, deliver, assert `popens == []` |
| 8 | `nonzero_exit_never_starts` | `arm()`; `deliver(stopped, code=3)`; `popens == []` |
| 9 | `abnormal_exit_status_never_starts` | `arm()`; `deliver(stopped, status=QProcess.ExitStatus.CrashExit)`; `popens == []` |
| 10 | `disabled_by_environment` | for `"1"`, `"true"`, `"TRUE"`, `" yes "`: `monkeypatch.setenv`, fresh manager, `start_if_not_running() is False`, `probes.starts == []`, `_autostart_consumed is False`; then without resetting those flags `monkeypatch.delenv(...)`, `start_if_not_running() is True` and `deliver(stopped)` yields one `start` |
| 11 | `second_manager_never_starts_again` | `arm(a)`; `b.start_if_not_running() is False`; `deliver(a, stopped)` -> 1 popen; `deliver(b, stopped)` -> still 1 |
| 12 | `automatic_spawn_failure_is_silent` | `arm()`; make `Popen` raise `OSError("nope")`; collect `action_completed` into a list; `deliver(stopped)`; `len(popens) == 1` (the attempt was reached); `collected == []` |
| 13 | `manual_spawn_failure_still_reports` | `Popen` raises; `start_supervisor()`; `collected == [("start_supervisor", False, "Failed to start supervisor: nope")]` |
| 14 | `followup_probe_requested_only_after_a_successful_automatic_start` | count `refresh_status` calls: success case total **2**, spawn-failure case total **1**, running case total **1** |
| 15 | `cancel_is_process_wide_across_managers` | `arm(a)`; `b.stop_supervisor()`; `deliver(a, stopped)`; `a.popens == [[exe, "stop"]]` (b's stop only) |
| 16 | `busy_probe_is_not_claimed` | force `probes._state = Running`; `start_if_not_running() is False`; `_autostart_consumed is False`; then `probes.finish()` and `arm(manager)` succeeds |
| 17 | `another_managers_poll_cannot_consume_or_authorise_the_claim` | put B's poll in flight and leave it; `arm(a)`; `deliver(b, stopped)`; `b.popens == []`; then `deliver(a, stopped)` -> exactly one `start` |
| 18 | `status_receiver_that_stops_wins` | `arm()`; connect a `status_updated` receiver calling `manager.stop_supervisor()`; `deliver(stopped)`; `popens == [[exe, "stop"]]` |

### `tests/test_main_window_autostart.py`

| # | Name | Assertions |
| --- | --- | --- |
| 19 | `constructor_requests_one_attempt` | monkeypatch `SupervisorManager.start_if_not_running` with a counting spy returning `True` **before** constructing; assert one call; assert the constructor never called `refresh_status` directly (spy on it, assert 0 calls from the constructor path) |
| 20 | `quit_cancels_pending_autostart` | build window with autostart enabled and fakes; `arm(window.supervisor_manager)`; `window._exit_application()`; claim is dead (`_autostart_owner is None`); `deliver(stopped)` spawns nothing |
| 21 | `hiding_to_tray_keeps_pending_autostart` | same setup, `settings.close_to_tray = True`, `window.close()`; `window.isHidden()` is True; claim still live |
| 22 | `cancel_in_the_unsaved_changes_prompt_keeps_the_attempt` | `arm()`; force `has_unsaved_changes()` True; monkeypatch `QMessageBox.question` to return `Cancel`; `window.handle_quit()`; claim still live |
| 23 | `direct_app_quit_cancels_via_about_to_quit` | `arm()`; `QApplication.instance().quit()`; then simulate the `aboutToQuit` emission (`app.aboutToQuit.emit()` or `processEvents()` after `quit()`), assert claim dead |
| 24 | `close_event_unsaved_prompt_path_keeps_the_attempt_until_confirmed` | `close_to_tray=False`; `has_unsaved_changes()` True; `QMessageBox.question` -> `Cancel`: window not closed, claim live; then `Discard`: claim dead |
| 25 | `manual_start_from_another_window_cancels_pending_attempt` | `arm(a)`; `b.start_supervisor()`; `deliver(a, stopped)`; `a.popens` contains no `start` |

## 6. Preservation requirements

- `tests/test_supervisor.py::test_stop_supervisor_runs_stop_command` must pass
  unchanged (argv, kwargs, action name, message, trailing refresh).
- `tests/test_widgets.py`, `test_main_window.py`, `test_main_window_tray.py`,
  `test_mnemonic.py`, `test_e2e_integration.py` must pass unchanged; none of them
  may spawn a real `ai-backends` (the autouse guard).
- Public API unchanged: `refresh_status`, `restart_service`,
  `start_supervisor`, `stop_supervisor`, `parse_supervisor_status`,
  `find_ai_backends_executable`, `default_log_path`, and both signals.

## 7. Acceptance

1. `pytest` green (whole suite) in the project's `daily` env with
   `QT_QPA_PLATFORM=offscreen` (set by `conftest.py`).
2. `grep -c "ai-backends start"` style manual check: the recorder assertion in the
   suite proves no real spawn during ordinary window tests.
3. Manual checks 3-6 of design §7.
4. No new dependency; `os` and `typing.ClassVar` are stdlib.
