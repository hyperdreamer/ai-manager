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

1. On launch, if the probe exits normally with code 0 **and** explicitly prints
   `supervisor not running` (and does not also print a running header), start the
   supervisor exactly once.
2. If the probe reports the supervisor running, reports anything unrecognised or
   contradictory, or fails in any way: no automatic action at all.
3. At most one automatic attempt per **process**, whether or not it succeeds.
4. Manual intent wins: a manual **Start** or **Stop** from any window, in any
   window, cancels the pending automatic attempt process-wide. Stop must stay
   stopped.
5. Automatic failures are silent. Only explicit user actions may raise the
   existing "Supervisor Action Failed" dialog.
6. No new user-visible UI, no new persisted setting.
7. Automated tests must never start, stop, or restart real backends.

### Non-Goals (explicitly out of scope)

- Auto-restart after the supervisor dies while the GUI is running, and any
  "keep alive" guarantee. The single attempt's outcome is observed by the ordinary
  status poll, not awaited.
- Changing `ai-backends` semantics. `start` is a teardown: `start_all_fresh()`
  (`/home/henry/Development/ai/ai-backends:251`) TERMs the previous supervisor,
  kills every backend by PID file **and** by project-path scan, and starts all
  services fresh. It never re-adopts running backends.
- A settings toggle, CLI flag, or tray entry.
- Atomicity of "start only if stopped". A status observation followed by `start`
  cannot exclude an external controller starting the supervisor in between; only a
  supervisor-side atomic operation could. The GUI's guarantee is a best-effort
  check made immediately before the decision.

## 2. Approved Behaviour

Launch sequence, unchanged until the last step:

```text
MainWindow.__init__
  ├─ build UI, load configs, apply theme
  ├─ start poll timer (settings.poll_interval_ms, default 4000)
  ├─ connect QApplication.instance().aboutToQuit -> supervisor_manager.cancel_pending_autostart
  └─ supervisor_manager.start_if_not_running()   ← was refresh_status()
```

Decision table for the single automatic attempt:

| Probe outcome | Automatic start? |
| --- | --- |
| exit 0, output has `supervisor running: <pid>` only | no |
| exit 0, output has `supervisor not running` only | **yes, once** |
| exit 0, output has both headers (contradictory) | no (running wins) |
| exit 0, output unrecognised (empty / usage / garbage) | no |
| non-zero exit code (e.g. bash usage error) | no |
| abnormal exit status (`CrashExit`) | no |
| could not spawn (`FailedToStart`; missing or non-executable script) | no |
| attempt already claimed in this process | no |
| a status probe is already in flight | no (and nothing is claimed) |
| autostart disabled by environment | no (and no probe is issued) |

`is_running` is never used as authorisation: `parse_supervisor_status`
(`supervisor.py:41`) yields `is_running=False` for *any* unrecognised output, so
"false" is not evidence the script said stopped. Authorisation requires the
positive match `SUPERVISOR_NOT_RUNNING_RE`, **no** `SUPERVISOR_RUNNING_RE` match,
exit code 0, and `NormalExit`, together.

### User-visible surface

No new widget, label, dialog, menu item, or tray action. A successful attempt
shows up only through today's rendering: the "Supervisor:" label and the
per-service badges move to "Running (PID …)" when the follow-up refresh or the
next poll observes the new supervisor. While an attempt is pending or failed, the
window shows exactly what it shows today.

One UI-adjacent cleanup: `MainWindow._on_supervisor_btn_clicked`
(`main_window.py:287-291`) has an if/else whose branches both call
`start_supervisor()`; it collapses to one call. No behaviour change, no new text.

## 3. Architecture

### 3.1 Components

`SupervisorManager` (`src/ai_manager/services/supervisor.py`) owns every
`ai-backends` invocation:

```python
AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"
_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})

class SupervisorManager(QObject):
    # Process-wide autostart state. Written only as
    # `SupervisorManager._autostart_pending`, never through `self`, so no
    # instance attribute can shadow it.
    _autostart_pending: ClassVar[bool] = False

    @staticmethod
    def autostart_disabled() -> bool: ...
    def start_if_not_running(self) -> bool: ...
    def cancel_pending_autostart(self) -> None: ...
    def start_supervisor(self) -> None: ...   # public manual entry, unchanged
    def stop_supervisor(self) -> None: ...    # public manual entry, unchanged
    def _spawn_supervisor(self, command: str, *, silent: bool) -> bool: ...
```

`MainWindow` (`src/ai_manager/ui/main_window.py`): the `__init__` final call, the
`aboutToQuit` connection, cancellation inside `_exit_application`, and the
collapsed button branch.

### 3.2 Flow

```text
start_if_not_running() -> bool
  if autostart_disabled():                   return False   # no probe, nothing claimed
  if SupervisorManager._autostart_pending:   return False   # pending or already consumed
  if self._status_process.state() != NotRunning: return False  # no probe would be issued
  SupervisorManager._autostart_pending = True               # claim before probing
  self.refresh_status()                                     # guaranteed to start a process
  return True

_on_status_finished(exit_code: int, exit_status: QProcess.ExitStatus)
  output = self._status_output_buffer.decode("utf-8", errors="replace")
  status = parse_supervisor_status(output)
  authorized = (
      SupervisorManager._autostart_pending
      and exit_code == 0
      and exit_status == QProcess.ExitStatus.NormalExit
      and SUPERVISOR_NOT_RUNNING_RE.search(output) is not None
      and SUPERVISOR_RUNNING_RE.search(output) is None
  )
  SupervisorManager._autostart_pending = False              # consume, always
  started = authorized and self._spawn_supervisor("start", silent=True)
  self.status_updated.emit(status)                          # after any spawn decision
  if started:
      self.refresh_status()

_on_status_error(error)
  SupervisorManager._autostart_pending = False              # failed probe never authorises
  self.status_updated.emit(SupervisorStatus(is_running=False, supervisor_pid=None, services={}))

start_supervisor()      # toolbar + tray "Start All Services"
  self.cancel_pending_autostart()
  if self._spawn_supervisor("start", silent=False):
      self.refresh_status()

stop_supervisor()       # toolbar + tray "Stop All Services"
  self.cancel_pending_autostart()
  if self._spawn_supervisor("stop", silent=False):
      self.refresh_status()

cancel_pending_autostart()
  SupervisorManager._autostart_pending = False              # process-wide; never re-armed
```

`_spawn_supervisor(command, *, silent)` is the existing body of
`start_supervisor`/`stop_supervisor` factored once:

```
try:
    subprocess.Popen([self.executable, command], start_new_session=True)
except Exception as e:
    if not silent:
        self.action_completed.emit(
            "start_supervisor" if command == "start" else "stop_supervisor", False,
            f"Failed to {'start' if command == 'start' else 'stop'} supervisor: {e}")
    return False
if not silent:
    self.action_completed.emit(
        "start_supervisor" if command == "start" else "stop_supervisor", True,
        f"Supervisor {'started' if command == 'start' else 'stopped'}.")
return True
```

Its argv, kwargs, signal names and messages are byte-identical to today's
`start_supervisor`/`stop_supervisor`, so `tests/test_supervisor.py` keeps passing.

### 3.3 Why each rule is load-bearing

**One process-wide flag, deliberately not per manager.** The app is a tray
application that can hold more than one window (tests construct many).
A per-manager flag let window A start while the user pressed Stop in window B, and
allowed two managers to both launch `start` — which would tear down every backend
twice. A single class attribute answers both: "has this process used its attempt?"
and "is an attempt still armed?". Both are the same question once the claim is
taken, so a second conflation trap is avoided by *not* having two fields.

**Claim before probing; consume on every terminal path.** Claiming inside
`start_if_not_running` (not in the completion callback) makes a second window's
call return `False` while the first probe is still in flight. Consuming in
`_on_status_finished` *and* `_on_status_error` *and* `start_if_not_running`'s
busy-guard means no status result, poll tick, or repeated entry call can ever
authorise a second attempt. A failed attempt is not retried: retrying is exactly
the loop this feature must not become.

**Busy-probe guard before claiming.** `refresh_status()` is a no-op while
`_status_process` is `Starting`/`Running` (`supervisor.py:100`). Without the guard,
a pre-existing probe would make `start_if_not_running()` return `True` while no
new process was issued, and the in-flight probe's *own* result — possibly
`not running` from before the user's Stop — would be treated as authorisation.
The guard makes the return value mean what it says: a probe was actually issued.

**Spawn before emit.** `status_updated` is a Qt signal whose receivers run
synchronously inside the emit. Emitting first and spawning afterwards let a
receiver that calls `stop_supervisor()` (or any status handler that cancels) be
overridden by the cached authorisation. Composing the decision, clearing the flag,
and spawning *before* the emit removes the re-entrancy window with no token
machinery. The emitted status is the probe that authorised the spawn — stale by one
step, which is exactly what it is today, and the follow-up refresh corrects it.

**Manual actions keep their exact old contract.** Same argv, same kwargs, same
`action_completed` names/messages, same trailing refresh; the only addition is the
cancellation. Existing tray and toolbar behaviour and `tests/test_supervisor.py`
are untouched.

**Automatic failures are silent.** `silent=True` suppresses `action_completed`, so
`_on_supervisor_action` (`main_window.py:293`) never opens the modal
**Supervisor Action Failed** dialog for something the user did not request. That
signal is the only path to that dialog — status completion, status errors, and the
follow-up refresh all emit `status_updated` instead — and the automatic path never
touches `_action_process`. Failures stay observable: the label reads
"Stopped / Inactive" and the next poll re-renders reality.

**Follow-up refresh is a local result.** `_spawn_supervisor` returns `bool`; the
follow-up `refresh_status()` happens only on `True`. The flag is already clear, so
that refresh and every later poll can never authorise anything.

### 3.4 Quit vs. hide

`closeEvent` (`main_window.py:400`) has two accept paths: the `_force_quit` branch
(accept and return) and the ordinary non-tray branch, which accepts and then calls
`_exit_application()` (`main_window.py:435`). It *ignores* the close and hides to
tray when `close_to_tray` is enabled. Two question dialogs — `handle_quit`'s and
`closeEvent`'s unsaved-changes prompt — run nested event loops.

Specified behaviour:

- **Hide to tray keeps the attempt armed.** The process is still supervising; an
  in-flight attempt should complete.
- **Quitting does not.** Cancellation is hooked in two places so no shutdown path
  is missed: `_exit_application()` (which both accept paths reach) and
  `QApplication.instance().aboutToQuit`, which also covers a direct
  `app.quit()`/`QApplication.quit()` from anywhere while visible, hidden, or
  minimised.
- **Confirmation dialogs do not cancel.** While a quit prompt is open the process
  is still running and still supervising, so completing a pending start is
  correct; if the user then cancels the quit, the app simply continues with a
  supervisor it would have started anyway. If they confirm, the exit path cancels
  anything still pending. This is stated explicitly because "cancel as early as
  possible" and "don't cancel on a decision you might revoke" are both defensible;
  this design picks the second.
- A spawned supervisor outlives the GUI (`start_new_session=True`), exactly as
  today when the user clicks Start and then quits.

## 4. Error Handling

| Failure | Behaviour |
| --- | --- |
| `ai-backends` missing / not executable | verified on Qt 6/PyQt6 6.11: `errorOccurred(FailedToStart)` and **no** `finished`; flag cleared, `SupervisorStatus(is_running=False, services={})` emitted, window usable, no start, no dialog |
| exits non-zero (bash usage error) | verified: `finished(3, NormalExit)`; the code check rejects it, so no start |
| abnormal exit (`CrashExit`) | `finished(_, CrashExit)`; exit-status check rejects it |
| output empty / usage text / garbage with exit 0 | no `supervisor not running` match; no start |
| both headers present | contradictory; `SUPERVISOR_RUNNING_RE` match vetoes; no start |
| `Popen` raises during automatic attempt | swallowed, returns `False`, no `action_completed`, no dialog, label stays stopped |
| `Popen` raises during manual action | unchanged: `action_completed(..., False, msg)` → existing dialog |
| probe hangs | no overlapping probes (`refresh_status` early-returns); the attempt stays pending until it reports finished/error; manual Start/Stop or quit cancels it |
| quit during probe | cancelled by `_exit_application` / `aboutToQuit`; a late `finished` sees the flag clear |
| two windows | second manager's `start_if_not_running()` returns `False`; one attempt per process |
| probe buffering | the existing same-thread `readyReadStandardOutput` wiring accumulates all output before `finished` (checked at 64 B, 64 KiB and 1 MiB); no tail is lost |

Startup never blocks: async `QProcess` probe, `Popen` spawn, so the window paints
before `main.py` calls `window.show()`.

## 5. Test-Safety Hazard

`tests/test_main_window.py`, `test_main_window_tray.py`, `test_mnemonic.py` build
`MainWindow` against temp workspaces; `tests/test_e2e_integration.py` builds one
against the **live** workspace. `SupervisorManager` resolves its executable via
`find_ai_backends_executable`, whose last resort is the hardcoded
`/home/bin/ai-backends` (`supervisor.py:34`) — the real script on this machine.
Unguarded, `pytest` would tear down and restart the developer's live backends.

Mitigation (both layers required):

1. `start_if_not_running()` returns `False` before any claim or probe when
   `AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART` normalises to `1`, `true`, `yes`, or
   `on` (case-insensitive, stripped). Unset or any other value means enabled. The
   check happens at entry only — flipping the variable mid-probe does not cancel an
   already-armed attempt; that is `cancel_pending_autostart`'s job.
2. `tests/conftest.py` gains a **function-scoped autouse** fixture that sets that
   variable via `monkeypatch.setenv`. Function scope is required because
   `monkeypatch` is function-scoped. Living in `conftest.py` makes it apply to
   single-module runs (`pytest tests/test_main_window.py`) too.

Precise scope of the guard: it prevents **destructive** commands (`start`/`stop`).
It does not stop the pre-existing poll timer from running read-only
`ai-backends status`. The safety evidence for ordinary tests is therefore
"no `start`/`stop` argv ever reached `subprocess.Popen`", asserted with a
recorder — not the environment variable alone.

## 6. Test Strategy (TDD; written first, red before implementation)

Two new files plus a shared fixture.

**`tests/conftest.py`** (added):

- autouse function-scoped `_disable_supervisor_autostart` (env var, §5.2);
- `autostart_env` — opt-in, `monkeypatch.delenv(...)`, and it **restores process
  state with `monkeypatch`**: `monkeypatch.setattr(SupervisorManager,
  "_autostart_pending", False)`. Because the flag is process-wide, every test that
  touches it must get it reset *and restored*, and must cancel any outstanding
  probe before the launch patches are undone.

**`tests/test_supervisor_autostart.py`** — fixtures:

- `recorder` — `subprocess.Popen` patched to append argv and return `MagicMock`;
  optionally raises (`raise_oserror`);
- `probes` — `QProcess.start` records how many processes were really launched
  (distinct from `refresh_status` requests, which is what test 14 counts);
- `manager` — `SupervisorManager(workspace_root=tmp_path)` with both patches;
- `deliver(manager, output, code=0, status=NormalExit)` — fills
  `_status_output_buffer`, calls `_on_status_finished(code, status)`. Every test
  goes through the **public entry point plus the real completion callback**.

| # | Test | Falsifiable because |
| --- | --- | --- |
| 1 | `starts_once_when_status_reports_stopped` | unchanged code spawns nothing; asserts `[exe, "start"]` + `start_new_session=True` |
| 2 | `does_not_start_when_running` | zero spawn **and** entry returned `True` with one probe issued |
| 3 | `is_one_shot_across_repeated_entry_calls` — call entry twice before delivery, once **after** consumption, deliver stopped twice; assert one spawn | a per-call re-arm spawns 2-3 times |
| 4 | `manual_stop_during_first_probe_never_converts_into_a_start` — entry, `stop_supervisor()`, then deliver the in-flight stopped output; argv must be exactly `[[exe, "stop"]]` | the single-flag draft yields `stop → start` |
| 5 | `manual_start_during_first_probe_never_double_starts` | two spawns without cancellation |
| 6 | `probe_failure_does_not_start_and_a_later_status_cannot_rearm` — armed, `_on_status_error`, then deliver stopped | fails if the flag is left armed |
| 7 | `unrecognised_output_never_starts` — three independently armed cases: `""`, `"usage: …"`, and a mixed running+stopped header | `is_running == False` alone starts |
| 8 | `nonzero_exit_never_starts` — stopped output with `code=3` | guards the verified `NormalExit` + real-code case |
| 9 | `abnormal_exit_status_never_starts` — `CrashExit` | exit-status enum honoured separately |
| 10 | `disabled_by_environment` — for `1`/`true`/`TRUE`/` yes ` and friendlies: no probe, flag untouched (`False`); then, in the **same test without resetting the flag**, delete the env var and assert the enabled path starts | a mutant claiming *before* the env check leaves the flag `True` and fails the first half; a no-op implementation fails the second |
| 11 | `second_manager_never_starts_again` — both managers' entry points called and asserted `True`/`False` **before** either delivery; then deliver stopped to both; one spawn, one probe | a mutant that claims only at completion passes a sequential version; this one does not |
| 12 | `automatic_spawn_failure_is_silent` — armed, stopped delivery, `Popen` raises; collector sees no `action_completed` and nothing escapes | only `silent=True` passes |
| 13 | `manual_spawn_failure_still_reports` — `start_supervisor()` with `Popen` raising; `("start_supervisor", False, …)` emitted | preserves the dialog contract |
| 14 | `followup_probe_requested_only_after_a_successful_automatic_start` — counts `refresh_status` calls, **uniform totals**: success **2** (initial + follow-up), failed spawn **1**, running **1** | pins the local-result design and its `silent` interaction |
| 15 | `cancel_is_process_wide_across_managers` — manager A armed (in-flight probe), `manager_b.stop_supervisor()`, then A's stopped delivery; A spawns nothing | per-instance cancellation lets A start |
| 16 | `busy_probe_is_not_claimed` — force `_status_process` into a running state, call entry: returns `False`, flag stays `False`, no new `QProcess.start` | without the guard the flag is claimed retroactively |
| 17 | `status_receiver_that_stops_cannot_be_overridden` — arm, connect a `status_updated` receiver that calls `stop_supervisor()`, deliver stopped; argv must be `[[exe, "stop"]]` only | spawn-after-emit produces `start` then `stop` |

**`tests/test_main_window_autostart.py`** — must *arm for real*: patch
`subprocess.Popen` and `refresh_status` per test, keep the env var deleted, and
patch `SupervisorManager.start_if_not_running` **before** construction only for
test 18.

| # | Test | Note |
| --- | --- | --- |
| 18 | `constructor_requests_one_attempt` — class-method spy installed before construction (attribute lookup happens at call time, so this works); asserts called once and that the constructor did not call `refresh_status` directly | pins the wiring |
| 19 | `quit_cancels_pending_autostart` — arm through the **real** entry method (never a bare spy, which would not set the flag), assert the flag is armed, call `_exit_application()`, assert `False` and that a later stopped delivery spawns nothing | quit-vs-hide |
| 20 | `hiding_to_tray_keeps_pending_autostart` — same setup, `close()` with `close_to_tray` enabled; window hidden, flag still armed | the opposite contract |
| 21 | `cancel_in_the_unsaved_changes_prompt_keeps_the_attempt` — arm, force `has_unsaved_changes()` true and answer Cancel; the attempt is still armed (§3.4 decision) | documents the chosen semantics |

Existing tests must keep passing unchanged, especially
`tests/test_supervisor.py::test_stop_supervisor_runs_stop_command`
(argv `[exe, "stop"]`, `start_new_session=True`,
`action_completed("stop_supervisor", True, …)`, trailing `refresh_status`).

Red-phase honesty: a test failing only because `start_if_not_running` does not
exist proves nothing. Tests 13, 15, 16, 17 were each reasoned against a naive
implementation (per-instance flag, claim-at-completion, no busy guard,
spawn-after-emit) and fail against it.

## 7. Verification

1. `pytest` full suite green, with the `Popen` recorder proving no `start`/`stop`
   argv during ordinary window tests.
2. Executable resolution: assert `find_ai_backends_executable` returns the
   workspace copy when present, so the `/home/bin/ai-backends` hardcoded fallback
   (`supervisor.py:34`) does not silently make tests depend on the host.
3. Manual, running: note PIDs from `ai-backends status`, launch `./start.sh`;
   PIDs unchanged, no restart.
4. Manual, stopped: `ai-backends stop`, launch; within a few seconds the label
   reads "Running (PID …)" and `ai-backends status` shows running backends.
5. Manual, stop race: `ai-backends stop`, launch, click **Stop Supervisor**
   immediately; the supervisor must not come back.
6. Manual, missing script: temporarily set `AI_WORKSPACE_ROOT` to a directory with
   no `ai-backends` **and** shadow PATH, because the hardcoded `/home/bin` fallback
   is otherwise used; window opens, label stopped, **no dialog**.
