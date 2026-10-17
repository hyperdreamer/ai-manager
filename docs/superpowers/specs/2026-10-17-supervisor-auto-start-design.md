# Design Document: Supervisor Auto-Start on Launch

## 1. Background & Goals

`ai-manager` administers the external `ai-backends` shell supervisor, which keeps
five local AI backends alive (`ai-grammar`, `textkit`, `yt2txt`, `chat2api`,
`file-bridge`). Today the GUI only *observes* the supervisor: `MainWindow` polls
`ai-backends status` every `poll_interval_ms` and renders the result, but nothing
ever starts the supervisor. A user who launches `ai-manager` and sees
"Stopped / Inactive" must click **Start Supervisor** by hand.

This feature makes launching `ai-manager` perform **one automatic startup attempt**,
and only when `ai-backends status` explicitly reports that the supervisor is not
running.

### Goals

1. On launch, if the probe exits normally with status 0 **and** explicitly prints
   `supervisor not running`, start the supervisor exactly once.
2. If the probe reports the supervisor running, or reports anything unrecognised,
   or fails in any way: no automatic action at all.
3. Exactly one automatic attempt per process, ever — not per poll tick, not per
   entry-point call, not per window.
4. An automatic attempt is cancelled the moment the user expresses intent: manual
   **Start Supervisor**, manual **Stop Supervisor**, or application quit.
   A Stop pressed during the first probe must stay stopped forever.
5. Automatic failures are silent. Only explicit user actions may raise the
   existing "Supervisor Action Failed" dialog.
6. No new user-visible UI, no new persisted setting.
7. Automated tests must never start, stop, or restart real backends.

### Non-Goals (explicitly out of scope)

- Auto-restart after the supervisor dies while the GUI is running, and any
  "keep alive" guarantee. The outcome of the single attempt is observed through
  the ordinary status poll, not awaited.
- Changing `ai-backends` semantics. Note what `start` really does:
  `start_all_fresh()` in `/home/henry/Development/ai/ai-backends:251` TERMs the
  previous supervisor, kills every backend by PID file **and** by project-path
  scan, and starts all services fresh. It never re-adopts running backends.
- A settings toggle, CLI flag, or tray entry.
- Atomic "start only if stopped" semantics. A status observation followed by a
  `start` cannot exclude an external controller starting the supervisor between
  those two operations; only a supervisor-side atomic operation could. The guard
  here is a best-effort check made immediately before the decision, which is the
  strongest guarantee available to the GUI without changing `ai-backends`.

## 2. Approved Behaviour

Launch sequence, unchanged until the last step:

```text
MainWindow.__init__
  ├─ build UI, load configs, apply theme
  ├─ start poll timer (settings.poll_interval_ms, default 4000)
  └─ supervisor_manager.start_if_not_running()   ← was refresh_status()
```

Decision table for the single automatic attempt:

| Probe outcome | Automatic start? |
| --- | --- |
| exit 0, output matches `supervisor running: <pid>` | no |
| exit 0, output matches `supervisor not running` | **yes, once** |
| exit 0, output unrecognised (empty, usage text, garbage) | no |
| non-zero exit status (e.g. bash usage error) | no |
| could not spawn (`errorOccurred` / `FailedToStart`: missing or non-executable script) | no |
| attempt already claimed in this process | no |
| autostart disabled by environment | no (and no probe is issued) |
| user pressed Start/Stop or quit while the probe was in flight | no |

Neither the exit code nor "not running" is inferred from `is_running`:
`parse_supervisor_status` defaults to `is_running=False` for *any* unrecognised
output, so `is_running == False` is not evidence that the script reported a
stopped supervisor. Authorisation therefore requires the positive regex match
`SUPERVISOR_NOT_RUNNING_RE`, a normal exit, and status 0 together.

### User-visible surface

No new widget, label, dialog, menu item, or tray action. The only consequence of
a successful attempt is that the existing "Supervisor:" label and the per-service
badges move from "Stopped / Inactive" to "Running (PID …)" when the next poll —
or the automatic follow-up refresh — observes the new supervisor. While an
attempt is pending or has failed, the window shows exactly what it shows today.

The one UI-adjacent edit is a cleanup: `MainWindow._on_supervisor_btn_clicked`
(`main_window.py:287-291`) has an if/else whose two branches both call
`start_supervisor()`. It collapses to one call. No behaviour change, no new text.

## 3. Architecture

### 3.1 Components

`SupervisorManager` (`src/ai_manager/services/supervisor.py`) owns every
`ai-backends` invocation. Additions:

```python
AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"
_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})

class SupervisorManager(QObject):
    # Process-wide: exactly one automatic attempt per application process,
    # regardless of how many windows/managers exist.
    _autostart_claimed: ClassVar[bool] = False

    def __init__(...):
        ...
        self._autostart_pending: bool = False   # this manager's probe is armed

    @staticmethod
    def autostart_disabled() -> bool: ...
    def start_if_not_running(self) -> bool: ...   # returns True iff a probe was issued
    def cancel_pending_autostart(self) -> None: ...
    def start_supervisor(self) -> None: ...       # unchanged public behaviour
    def stop_supervisor(self) -> None: ...        # unchanged public behaviour
    def _spawn_supervisor(self, command: str, *, silent: bool) -> bool: ...
```

`MainWindow` (`src/ai_manager/ui/main_window.py`):

- `__init__` final call becomes `start_if_not_running()`;
- `_exit_application()` calls `cancel_pending_autostart()` before quitting;
- `_on_supervisor_btn_clicked` loses its duplicated branch.

### 3.2 Flow

```text
start_if_not_running() -> bool
  if autostart_disabled():            return False      # no probe, no claim
  if self._autostart_pending:         return False      # this manager already armed
  if SupervisorManager._autostart_claimed: return False # another manager claimed
  SupervisorManager._autostart_claimed = True           # claim BEFORE probing
  self._autostart_pending = True
  self.refresh_status()
  return True

_on_status_finished(exit_code: int, exit_status)
  output = buffer.decode(...)
  status = parse_supervisor_status(output)
  authorized = (
      self._autostart_pending
      and exit_code == 0
      and exit_status == QProcess.ExitStatus.NormalExit
      and SUPERVISOR_NOT_RUNNING_RE.search(output) is not None
  )
  self._autostart_pending = False          # consume before any side effect
  self.status_updated.emit(status)         # unchanged: emit parsed status first
  if authorized and self._spawn_supervisor("start", silent=True):
      self.refresh_status()                # one ordinary follow-up probe

_on_status_error(error)
  self._autostart_pending = False          # a failed probe never authorises
  self.status_updated.emit(SupervisorStatus(is_running=False, supervisor_pid=None, services={}))

start_supervisor()   # manual (toolbar + tray "Start All Services")
  self.cancel_pending_autostart()
  if self._spawn_supervisor("start", silent=False):
      self.refresh_status()

stop_supervisor()    # manual (toolbar + tray "Stop All Services")
  self.cancel_pending_autostart()
  if self._spawn_supervisor("stop", silent=False):
      self.refresh_status()

cancel_pending_autostart()
  self._autostart_pending = False          # the process-wide claim is NOT returned:
                                           # one attempt per process, not one per cancel
```

### 3.3 Why each rule is load-bearing

**Claim before probing, and never release it.** `_autostart_claimed` is a
process-wide class attribute set at entry, before the asynchronous probe runs.
This makes the attempt once-per-process even if a second `MainWindow` is
constructed (the app allows it; `main.py` builds one, tests build many). Two
managers that each observed "not running" would otherwise both launch `start`,
and `ai-backends start` tears down every backend — a real disruption, not a
no-op. The claim is deliberately *not* released by `cancel_pending_autostart`,
by a failed probe, or by a failed spawn: "one automatic attempt per process" is
the promise, and a retry loop is exactly what this feature must not become.

**Two separate pieces of state.** `_autostart_claimed` answers "has this process
used its attempt?"; `_autostart_pending` answers "is *my* probe still armed?".
Conflating them into one flag (an earlier draft did) made an early manual Stop
convert into a start: `stop_supervisor()` calls `refresh_status()`, which is
ignored while the first probe is still in flight, so the probe's own
`supervisor not running` result would arrive holding an armed latch. Cancel at
entry to Stop and Start removes that ordering hazard.

**Cancellation is one-way.** `cancel_pending_autostart()` only ever clears
`_autostart_pending`. No status result, poll tick, or repeated
`start_if_not_running()` call can re-arm it, because re-arming requires
`_autostart_claimed` to still be false.

**Manual actions keep their exact old contract.** `start_supervisor()` and
`stop_supervisor()` keep their `action_completed` emissions (names
`start_supervisor` / `stop_supervisor`, messages "Supervisor started." /
"Supervisor stopped.") and their trailing refresh, so the toolbar, tray and
existing tests are unaffected. They now additionally cancel a pending automatic
attempt, which is the only behavioural change on those paths.

**Automatic failures are silent.** `_spawn_supervisor(..., silent=True)` does not
emit `action_completed` on exception, so `MainWindow._on_supervisor_action`
never opens the modal **Supervisor Action Failed** dialog for something the user
did not ask for. The failure is observable through the normal poll: the label
stays "Stopped / Inactive". Manual paths pass `silent=False` and keep the dialog.

**Follow-up probe is a local result, not a stored flag.** The spawn helper returns
`bool`; the follow-up `refresh_status()` is issued only when it returned `True`,
after `status_updated` has been emitted for the probe that authorised the start.
The follow-up is an ordinary refresh: `_autostart_pending` is already `False`
and `_autostart_claimed` is already `True`, so it can never start anything again.
(An earlier draft stored `_start_again_after_status` with no consumer, which was
unimplementable as written.)

### 3.4 Quit vs. hide

`closeEvent` (`main_window.py:400`) hides to tray when `close_to_tray` is enabled
and only accepts the close when `_force_quit` was set by `handle_quit` /
`_exit_application`. Therefore:

- **Hiding to tray keeps the pending attempt armed.** The application is still
  running and still supervising; a launch-equivalent attempt that is already in
  flight should complete. Nothing new is needed for this path.
- **Quitting cancels it.** `_exit_application()` calls
  `cancel_pending_autostart()` before `app.quit()`, so a late status result
  during shutdown cannot spawn a supervisor the user just quit from. Because the
  claim is not released, this also means quitting during the first probe consumes
  the process's one attempt — correct, since the process is ending.
- A spawned supervisor outlives the GUI (`start_new_session=True`), exactly as
  today when the user clicks Start and then quits.

## 4. Error Handling

| Failure | Behaviour |
| --- | --- |
| `ai-backends` missing or not executable | `QProcess` reports `errorOccurred` and (verified on Qt 6 / PyQt6 6.x) **no** `finished`; latch cleared, `SupervisorStatus(is_running=False, services={})` emitted, window usable, no start, no dialog |
| `ai-backends` exists but exits non-zero (e.g. bash usage error) | `finished(3, NormalExit)`; the explicit-`not running` match fails, so no start. Verified: Qt reports `NormalExit` with the real exit code, so the code must be checked, not just the exit status enum |
| Probe output unrecognised (empty / usage text / garbage) with exit 0 | no start (no `supervisor not running` match) |
| Spawn of `start` raises `OSError` during an automatic attempt | swallowed; no `action_completed`, no dialog; label stays stopped |
| Spawn of `start` raises during a manual action | unchanged: `action_completed("start_supervisor", False, msg)` → existing warning dialog |
| Probe hangs | `refresh_status` returns early while the process is running, so no overlapping probes; the automatic attempt stays pending until the process reports finished or errors. Quit or a manual action cancels it |
| Application quits during the probe | `_exit_application` cancels; a late `finished` finds `_autostart_pending` false |
| Two windows | second manager's `start_if_not_running()` returns `False`; only one attempt per process |

Startup never blocks: the probe is an async `QProcess` and the spawn is
`subprocess.Popen` with `start_new_session=True`, so the window paints
immediately and `main.py` reaches `window.show()` without waiting.

## 5. Test-Safety Hazard

`tests/test_main_window.py`, `test_main_window_tray.py`, `test_mnemonic.py` build
`MainWindow` against temp workspaces, and `tests/test_e2e_integration.py` builds
one against the **live** workspace (`find_ai_workspace_root()`).
`SupervisorManager` resolves its executable through
`find_ai_backends_executable`, which falls back to a PATH lookup — on this
machine that is the real `/home/bin/ai-backends`. Without a guard, running
`pytest` would make those tests tear down and restart the developer's five live
backends.

Mitigation (both layers required):

1. `start_if_not_running()` returns `False` immediately when
   `AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART` normalises to one of `1`, `true`,
   `yes`, `on` (case-insensitive, surrounding whitespace stripped). Unset or any
   other value means enabled. This is also the documented opt-out for packagers.
   The check is at entry only: flipping the variable while a probe is in flight
   does not cancel the already-armed attempt (cancellation is the job of
   `cancel_pending_autostart`).
2. `tests/conftest.py` gains a **function-scoped autouse** fixture that sets that
   variable with `monkeypatch.setenv`. Function scope is required: the built-in
   `monkeypatch` fixture is function-scoped, so a session-scoped fixture using it
   is a scope error. Living in `conftest.py` means it also applies when a single
   module is run directly (`pytest tests/test_main_window.py`).
3. `tests/test_supervisor_autostart.py` opts back in per test with
   `monkeypatch.delenv(AUTOSTART_DISABLE_ENV, raising=False)`, and always patches
   subprocess launch before enabling autostart.

Scope of the guard, stated precisely: it prevents **destructive** commands
(`start` / `stop`). It does not prevent the pre-existing poll timer from running
`ai-backends status`, which is read-only; the keyword-safety evidence for tests
is therefore "no `start`/`stop` argv was ever passed to `subprocess.Popen`",
asserted by a recorder, not by the environment variable alone.

## 6. Test Strategy (TDD; written first, red before implementation)

New file `tests/test_supervisor_autostart.py`. Shared fixture:

- `manager` — `SupervisorManager(workspace_root=tmp_path)`, with
  `subprocess.Popen` monkeypatched to a recorder returning `MagicMock`
  (`popens: list[list[str]]`), and with
  `SupervisorManager._autostart_claimed` reset to `False` (it is process-wide
  state; pytest reuses the process).
- `deliver(manager, output, code=0, status=QProcess.ExitStatus.NormalExit)` —
  writes `output` into `manager._status_output_buffer` and calls
  `manager._on_status_finished(code, status)`. Tests go through the **public
  entry point plus the real completion callback**, never by poking the latch.

| # | Test | Falsifiable because |
| --- | --- | --- |
| 1 | `test_autostart_starts_once_when_status_reports_stopped` — `start_if_not_running()` then `deliver(SAMPLE_STOPPED_OUTPUT)`; assert exactly one `Popen` with `[exe, "start"]` and `start_new_session=True` | unchanged code spawns nothing |
| 2 | `test_autostart_does_not_start_when_status_reports_running` — assert zero `Popen` **and** that the attempt was issued (`start_if_not_running()` returned `True`, one probe recorded) | pairs the zero-spawn assertion with evidence the mechanism ran |
| 3 | `test_autostart_is_one_shot_across_repeated_entry_calls` — call `start_if_not_running()` twice, then deliver stopped once; re-deliver stopped; assert one `Popen` and that the second entry call returned `False` | a per-call re-arm spawns twice |
| 4 | `test_manual_stop_during_first_probe_never_converts_into_a_start` — `start_if_not_running()`, then `stop_supervisor()`, then deliver the in-flight `SAMPLE_STOPPED_OUTPUT`; assert argv is exactly `[[exe, "stop"]]`, i.e. `stop → start` never happens | the earlier single-flag draft produces `["stop", "start"]` |
| 5 | `test_manual_start_during_first_probe_never_double_starts` — `start_if_not_running()`, `start_supervisor()`, deliver stopped; assert exactly one `start` argv | an uncancelled latch produces two |
| 6 | `test_probe_failure_does_not_start_and_survives_a_later_status` — armed, `_on_status_error(...)`, then deliver `SAMPLE_STOPPED_OUTPUT`; assert zero `Popen` | clears the latch *and* proves later results cannot re-arm |
| 7 | `test_unrecognised_output_never_starts` — deliver `"usage: ...\n"` with code 0; and deliver `""` with code 0; assert zero `Popen` | `is_running == False` alone would start |
| 8 | `test_nonzero_exit_never_starts` — deliver `SAMPLE_STOPPED_OUTPUT` with `code=3`; assert zero `Popen` | guards the verified `NormalExit` + real-code case |
| 9 | `test_abnormal_exit_status_never_starts` — deliver stopped with `QProcess.ExitStatus.CrashExit`; assert zero `Popen` | exit-status enum is honoured separately |
| 10 | `test_autostart_disabled_by_environment` — for each of `1/true/TRUE/yes/on/ spaced `: no probe at all (probe recorder empty) and no start after a later stopped delivery; then, in the same test, clear the env var, reset the claim, and assert the enabled path starts — so a no-op implementation fails | positive control in the same test |
| 11 | `test_second_manager_does_not_start_again` — manager A claims and is delivered stopped (one `Popen`); a second `SupervisorManager` on the same `tmp_path` is armed and delivered stopped; assert still one `Popen` | per-window claims spawn twice |
| 12 | `test_automatic_spawn_failure_is_silent` — armed, deliver stopped, make `Popen` raise `OSError`; assert `action_completed` never emitted (use a list collector) and no exception escapes | silent=True is the only way to pass |
| 13 | `test_manual_spawn_failure_still_reports` — `start_supervisor()` with `Popen` raising; assert `action_completed` emitted with `("start_supervisor", False, …)` | preserves the existing dialog contract |
| 14 | `test_followup_probe_requested_only_after_successful_automatic_start` — patch `refresh_status` with a counter; armed + stopped delivery → 2 (initial + follow-up); armed + failed spawn → 0 after the initial; armed + running delivery → 1 | pins the local-result design and its `silent` interaction |

`tests/test_main_window_autostart.py` (or an addition to `test_main_window.py`):

| # | Test | Note |
| --- | --- | --- |
| 15 | `test_main_window_requests_one_attempt_and_does_not_only_refresh` — patch `SupervisorManager.start_if_not_running` (class method) with a spy **before** constructing `MainWindow` against the tray-fixture workspace; assert called once, and that `refresh_status` was not called directly by the constructor | spying before construction is possible: the constructor resolves the attribute at call time |
| 16 | `test_quit_cancels_pending_autostart` — construct the window with the attempt armed (spy returns `True` without probing), call `_exit_application()`, assert `_autostart_pending is False` and that a subsequent stopped delivery spawns nothing | quit-vs-hide contract |
| 17 | `test_hiding_to_tray_keeps_pending_autostart` — same setup, `close()` with `close_to_tray` enabled, assert the window is hidden and `_autostart_pending is True` | the opposite contract |

`tests/conftest.py` addition: the function-scoped autouse env guard (§5.2).

Existing tests must keep passing unchanged, in particular
`tests/test_supervisor.py::test_stop_supervisor_runs_stop_command` (argv
`[exe, "stop"]`, `start_new_session=True`, `action_completed` with
`("stop_supervisor", True, …)`, and the trailing `refresh_status`).

Note on red-phase honesty: a test that fails only because
`start_if_not_running` does not yet exist proves nothing about behaviour. Tests
1-14 are written so that, with the method present but the latch/authorisation
logic absent or naive, they still fail — tests 4, 6, 7, 8, 11, 12, 14 in
particular were each checked against the naive implementation.

## 7. Verification

1. `pytest` full suite green, with a `Popen` recorder asserting no `start`/`stop`
   argv reached subprocess during ordinary window tests.
2. Manual, supervisor running: note PIDs from `ai-backends status`, launch
   `./start.sh`; PIDs unchanged, no restart.
3. Manual, supervisor stopped: `ai-backends stop`, launch `./start.sh`; within a
   few seconds the label reads "Running (PID …)" and `ai-backends status` shows
   running backends.
4. Manual, manual-stop race: `ai-backends stop`, launch, and click **Stop
   Supervisor** immediately; the supervisor must not come back.
5. Manual, missing script: launch with `PATH` stripped of `ai-backends` and no
   workspace copy; window opens, label shows stopped, **no dialog**.
