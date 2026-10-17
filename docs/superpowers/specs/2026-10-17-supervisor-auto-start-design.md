# Design Document: Supervisor Auto-Start on Launch

## 1. Background & Goals

`ai-manager` administers the external `ai-backends` shell supervisor, which keeps
five local AI backends alive (`ai-grammar`, `textkit`, `yt2txt`, `chat2api`,
`file-bridge`). Today the GUI only *observes* the supervisor: `MainWindow` polls
`ai-backends status` every `poll_interval_ms` and renders the result. Launching the
app never starts the supervisor automatically, so a user who opens `ai-manager` and
sees "Stopped / Inactive" must click **Start Supervisor** by hand.

This feature adds **one automatic startup attempt at launch**, taken only when
`ai-backends status` explicitly reports that the supervisor is not running.

### Goals

1. At launch, when the probe exits normally with code 0 and its output contains
   `supervisor not running` and does **not** contain `supervisor running: <pid>`,
   start the supervisor once.
2. Any other probe outcome — running, unrecognised, contradictory, non-zero exit,
   abnormal exit, spawn failure — causes no automatic action.
3. At most one automatic attempt per process, permanently, regardless of windows,
   cancellations, failures, or later entry-point calls.
4. Manual intent wins over a pending automatic start, from any window. After a
   manual **Stop** the supervisor stays stopped.
5. The guarantee is bounded, and the bound is exactly this: **a manual Stop issued
   before the automatic spawn is attempted always wins**; a Stop issued after the
   detached `start` has been launched cannot cancel it. `ai-backends start` is an
   independent process (`start_all_fresh()`,
   `/home/henry/Development/ai/ai-backends:251`) and `Popen` returns once that
   process has been executed, not once the script has finished killing and starting
   services. Two detached `Popen` calls provide no ordering between the script's
   internal steps, so a later Stop can run before `start_all_fresh` publishes its
   PID file and the end state may be *running*. This design does not claim
   otherwise; a guaranteed stopped end state would need readiness/serialization
   support inside `ai-backends`, which is out of scope. The window is narrow (launch,
   let the probe finish, press Stop within the few seconds `start_all_fresh` needs),
   and the follow-up poll shows the real state either way.
6. Automatic failures are silent; only explicit user actions may raise the existing
   "Supervisor Action Failed" dialog.
7. No new user-visible UI and no new persisted setting.
8. Automated tests never start, stop, or restart real backends.

### Non-Goals (explicitly out of scope)

- Auto-restart after the supervisor dies while the GUI runs; no keep-alive.
- Awaiting the outcome of the attempt. It is observed through the ordinary poll.
- Changing `ai-backends`. In particular, `start` is destructive:
  `start_all_fresh()` TERMs any existing supervisor, kills every backend by PID file
  **and** project-path scan, and starts all services fresh. It never re-adopts
  running backends, which is why an automatic attempt must never fire against a
  running supervisor.
- A settings toggle, CLI flag, or tray entry.
- Atomic "start iff stopped". A status observation followed by `start` cannot
  exclude an external controller starting the supervisor in between; only a
  supervisor-side atomic operation could.

## 2. Approved Behaviour

Launch sequence, unchanged except the last two steps:

```text
MainWindow.__init__
  ├─ build UI, load configs, apply theme
  ├─ start poll timer (settings.poll_interval_ms, default 4000)
  ├─ connect QApplication.instance().aboutToQuit -> supervisor_manager.cancel_pending_autostart
  └─ supervisor_manager.start_if_not_running()   ← was refresh_status()
```

Decision table for the attempt:

| Probe outcome | Automatic start? |
| --- | --- |
| exit 0, `supervisor running: <pid>` only | no |
| exit 0, `supervisor not running` only | **yes, once** |
| exit 0, both headers (contradictory) | no (running wins) |
| exit 0, output unrecognised (empty / usage / garbage) | no |
| non-zero exit code (e.g. bash usage error) | no |
| abnormal exit status (`CrashExit`) | no |
| could not spawn (`FailedToStart`: missing or non-executable) | no |
| attempt already consumed in this process | no |
| this manager's status process was busy | no (nothing consumed) |
| autostart disabled by environment | no (no probe issued, nothing consumed) |
| manual Start/Stop/quit observed before the spawn | no |

`is_running` is never used as authorisation: `parse_supervisor_status`
(`supervisor.py:41`) yields `is_running=False` for *any* unrecognised output. The
positive tests are `SUPERVISOR_NOT_RUNNING_RE` present, `SUPERVISOR_RUNNING_RE`
absent, exit code 0, and `NormalExit`.

### User-visible surface

No new widget, label, dialog, menu item, or tray action. A successful attempt
appears only through today's rendering: the "Supervisor:" label and the per-service
badges move to "Running (PID …)" when the follow-up refresh or the next poll sees
the new supervisor. While the attempt is pending or failed, the window shows
exactly what it shows today.

One UI-adjacent cleanup: `MainWindow._on_supervisor_btn_clicked`
(`main_window.py:287-291`) has an if/else whose branches both call
`start_supervisor()`; it collapses to a single call. No behaviour change.

## 3. Architecture

### 3.1 Components

All supervisor state and every `ai-backends` invocation live in
`SupervisorManager` (`src/ai_manager/services/supervisor.py`). Three monotone
process-wide values plus one per-manager value:

```python
AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"
_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})

class SupervisorManager(QObject):
    # Process-wide, monotone. Written only as SupervisorManager.<name>, never
    # through `self`, so no instance attribute can shadow them.
    _autostart_consumed: ClassVar[bool] = False   # False -> True, never back
    _autostart_cancel_epoch: ClassVar[int] = 0    # ++ on every manual Start/Stop
    _autostart_owner: ClassVar[Optional["SupervisorManager"]] = None

    # Per-manager: the epoch stamped on the probe that claimed the attempt.
    self._autostart_epoch: Optional[int] = None

    @staticmethod
    def autostart_disabled() -> bool: ...
    def start_if_not_running(self) -> bool: ...
    def cancel_pending_autostart(self) -> None: ...
    def start_supervisor(self) -> None: ...
    def stop_supervisor(self) -> None: ...
    def _spawn_supervisor(self, command: str, *, silent: bool) -> bool: ...
```

`MainWindow` (`src/ai_manager/ui/main_window.py`): the `__init__` final call, the
`aboutToQuit` connection, cancellation in `_exit_application`, and the collapsed
button branch.

### 3.2 Flow

```text
start_if_not_running() -> bool
  if autostart_disabled():                            return False
  if SupervisorManager._autostart_consumed:           return False
  if SupervisorManager._autostart_owner is not None:  return False
  if self._status_process.state() != NotRunning:      return False   # nothing would be launched
  SupervisorManager._autostart_consumed = True                      # consume at claim time
  SupervisorManager._autostart_owner = self
  self._autostart_epoch = SupervisorManager._autostart_cancel_epoch
  self.refresh_status()                                             # a probe really starts
  return True

_on_status_finished(exit_code: int, exit_status: QProcess.ExitStatus)
  output = self._status_output_buffer.decode("utf-8", errors="replace")
  status = parse_supervisor_status(output)

  # Locals, so releasing the claim below cannot invalidate the comparison.
  claim_epoch = self._autostart_epoch
  claimed_here = (SupervisorManager._autostart_owner is self
                  and claim_epoch is not None
                  and claim_epoch == SupervisorManager._autostart_cancel_epoch)
  if claimed_here:
      self._release_autostart_claim()               # before any side effect
  self.status_updated.emit(status)                  # ordinary rendering, unchanged
  if not claimed_here:
      return
  if not (exit_code == 0
          and exit_status == QProcess.ExitStatus.NormalExit
          and SUPERVISOR_NOT_RUNNING_RE.search(output) is not None
          and SUPERVISOR_RUNNING_RE.search(output) is None):
      return
  if claim_epoch != SupervisorManager._autostart_cancel_epoch:
      return                                        # cancelled while we emitted
  if self._spawn_supervisor("start", silent=True):
      self.refresh_status()                         # ordinary follow-up probe

_on_status_error(error)
  claim_epoch = self._autostart_epoch
  if (SupervisorManager._autostart_owner is self
          and claim_epoch is not None
          and claim_epoch == SupervisorManager._autostart_cancel_epoch):
      self._release_autostart_claim()
  self.status_updated.emit(SupervisorStatus(is_running=False, supervisor_pid=None, services={}))

_release_autostart_claim()
  SupervisorManager._autostart_owner = None
  self._autostart_epoch = None

start_supervisor()          # toolbar + tray "Start All Services"
  self.cancel_pending_autostart()
  if self._spawn_supervisor("start", silent=False):
      self.refresh_status()

stop_supervisor()           # toolbar + tray "Stop All Services"
  self.cancel_pending_autostart()
  if self._spawn_supervisor("stop", silent=False):
      self.refresh_status()

cancel_pending_autostart()
  SupervisorManager._autostart_cancel_epoch += 1     # monotone; invalidates any claim
  SupervisorManager._autostart_owner = None          # never restores _autostart_consumed
```

`_spawn_supervisor(command, *, silent) -> bool` is today's spawn body, factored
once, with argv `[self.executable, command]`, `start_new_session=True`, and the
existing `action_completed` names/messages for `silent=False`:

```
command == "start"  -> action "start_supervisor",
                       ok   "Supervisor started.",
                       fail "Failed to start supervisor: {e}"
command == "stop"   -> action "stop_supervisor",
                       ok   "Supervisor stopped.",
                       fail "Failed to stop supervisor: {e}"
```

These strings, the argv, and the kwargs are byte-identical to the current
implementation (`supervisor.py:128-145`), so `tests/test_supervisor.py` passes
unchanged.

### 3.3 Why this shape (and what the three previous drafts got wrong)

Three earlier drafts shared one defect and were rejected for it: they used a
*mutable boolean* to mean both "armed" and "consumed". Every review round then
found another interleaving — a second window re-arming it, a second manager's poll
consuming it, a manual Stop converting into a start, a synchronous signal receiver
outranking a cached authorisation. The fix is structural, not another patch:

**`_autostart_consumed` is monotone.** It is set at claim time and never cleared.
False means "this process has not used its attempt"; True means "it is spent", and
no entry call, cancellation, failure, or new window can return it to False.
Cancelling therefore cannot make the attempt eligible again.

**The claim is owned, not global-only.** `_autostart_owner` identifies the manager
whose probe claimed the attempt, and only that manager's terminal callback may act
on it. Another manager's poll — running or failing — cannot consume the claim,
cannot suppress the attempt, and cannot authorise a spawn from a probe it did not
send.

**Cancellation is a monotone epoch, not a flag.** `cancel_pending_autostart()`
increments `_autostart_cancel_epoch`; the claiming manager remembers the epoch at
claim time and compares before spawning. Any manual Start/Stop from any window,
and any quit, therefore invalidates a pending attempt process-wide, and the
comparison survives nested event loops. The comparison uses a **local copy**
captured before `_release_autostart_claim()` runs: release clears
`self._autostart_epoch`, so comparing the field afterwards would always compare
`None` against the live epoch and silently disable the automatic start entirely.

**Authorisation is re-derived, never cached across the emit.** `status_updated` is
a Qt signal whose receivers run synchronously. An earlier draft computed
`authorized`, cleared the flag, emitted, and then spawned from the cached boolean —
so a receiver that called `stop_supervisor()` still got an automatic start
(`start` then `stop`). This draft releases the claim, emits, and only then
re-checks the epoch: a receiver that cancels makes the epoch stale and the spawn is
skipped. Emitting before spawning also means the emitted status never post-dates
the spawn, so rendering is not shown a "stopped" state derived from a probe that
has already been acted upon.

**Busy probe is rejected before claiming.** `refresh_status()` is a no-op while
`_status_process` is `Starting`/`Running` (`supervisor.py:100`). Checking state
first means a `True` return really means "a probe was launched" and prevents an
already-in-flight poll's result from being treated as authorisation.

**Manual paths keep their exact old contract.** Same argv, kwargs, signal
names/messages, and trailing refresh; the only addition is cancellation, which
invalidates a *pending* automatic attempt and never touches manual behaviour. The
tray's "Start All Services" and "Stop All Services" therefore behave exactly as
before.

**Automatic failures stay silent.** `silent=True` suppresses `action_completed`,
the only route to the modal **Supervisor Action Failed** dialog
(`main_window.py:293`); status completion, status errors, and the follow-up refresh
all emit `status_updated` instead, and the automatic path never touches
`_action_process`. Failure remains observable: the label reads "Stopped / Inactive"
and the next poll re-renders reality.

**Follow-up refresh is a local result.** `_spawn_supervisor` returns `bool`; the
follow-up probe is requested only on `True`, after the claim is already spent, so it
cannot authorise anything.

### 3.4 Quit vs. hide

`closeEvent` (`main_window.py:400`) accepts on the `_force_quit` branch, ignores and
hides to tray when `close_to_tray` is enabled, and otherwise accepts and calls
`_exit_application()` (`main_window.py:435`). Both unsaved-changes prompts
(`handle_quit`, `closeEvent`) run nested event loops.

- **Hide to tray keeps a pending attempt alive.** The process is still supervising.
- **Quitting cancels.** Cancellation is hooked in `_exit_application()` (reached by
  both accept paths) *and* `QApplication.instance().aboutToQuit`, which also covers
  a direct `app.quit()` from anywhere. A late probe result finds a stale epoch and
  does nothing.
- **Confirmation prompts do not cancel.** While a quit prompt is open the process is
  still running and still supervising, so completing a pending start is correct; if
  the user cancels the quit, the app continues with a supervisor it would have
  started anyway. If they confirm, the exit path cancels whatever is still pending
  and stops any spawn that has not happened yet.
- A spawned supervisor outlives the GUI (`start_new_session=True`), exactly as it
  does today when the user clicks Start and then quits.

## 4. Error Handling

| Failure | Behaviour |
| --- | --- |
| `ai-backends` missing / not executable | verified on Qt 6 / PyQt6 6.11: `errorOccurred(FailedToStart)` and **no** `finished`; claim released, `SupervisorStatus(is_running=False, services={})` emitted, no start, no dialog |
| exits non-zero (bash usage error) | verified: `finished(3, NormalExit)`; the code check rejects it |
| abnormal exit (`CrashExit`) | exit-status check rejects it |
| empty / usage / garbage output, exit 0 | no positive `not running` match; no start |
| both headers present | contradictory; the `running` match vetoes |
| `Popen` raises during an automatic attempt | swallowed, returns `False`, no `action_completed`, no dialog |
| `Popen` raises during a manual action | unchanged: `action_completed(..., False, msg)` → existing dialog |
| probe hangs | no overlapping probes; the claim stays owned until it reports finished or error; manual Start/Stop or quit invalidates it via the epoch |
| quit during probe | cancelled via `_exit_application` / `aboutToQuit`; late result finds a stale epoch |
| two windows | second manager's entry returns `False` (`owner is not None`), and its polls cannot consume or authorise the first manager's claim |
| probe buffering | existing same-thread `readyReadStandardOutput` wiring accumulates all output before `finished` (checked at 64 B, 64 KiB, 1 MiB) |
| manual Stop after the detached start was launched | cannot cancel it; the Stop command runs after and leaves the supervisor stopped — the bounded guarantee of Goal 5 |

Startup does not block the event loop: the probe is async `QProcess`, the spawn is
`Popen`, so `main.py` proceeds to `window.show()` without waiting for the supervisor
to come up.

## 5. Test-Safety Hazard

`tests/test_main_window.py`, `test_main_window_tray.py`, `test_mnemonic.py` build
`MainWindow` against temp workspaces; `tests/test_e2e_integration.py` builds one
against the **live** workspace. `find_ai_backends_executable`'s last resort is the
hardcoded `/home/bin/ai-backends` (`supervisor.py:34`) — the real script here.
Unguarded, `pytest` would tear down and restart the developer's live backends.

Mitigation (both layers required):

1. `start_if_not_running()` returns `False` before any claim or probe when
   `AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART` normalises to `1`, `true`, `yes`, or
   `on` (case-insensitive, stripped). Unset or any other value means enabled. The
   check is at entry only: flipping it mid-probe does not cancel an armed attempt —
   that is `cancel_pending_autostart`'s job.
2. `tests/conftest.py` gains a **function-scoped autouse** fixture that sets that
   variable with `monkeypatch.setenv`. Function scope is required (`monkeypatch` is
   function-scoped) and `conftest.py` placement makes it apply to single-module runs
   too.

Scope, stated precisely: the guard prevents **destructive** commands
(`start`/`stop`). It does not stop the pre-existing poll timer from running
read-only `ai-backends status`. Ordinary-test safety is therefore evidenced by
"no `start`/`stop` argv reached `subprocess.Popen`" from a recorder, not by the
environment variable alone.

## 6. Test Strategy (TDD; written first, red before implementation)

Two new test files plus shared fixtures in `tests/conftest.py`.

**`tests/conftest.py`** additions:

- autouse function-scoped `_disable_supervisor_autostart` (env var, §5.2);
- `autostart_env` opt-in fixture that `monkeypatch.delenv(...)`s the variable and
  resets process state **with restoration**:
  `monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)`,
  `... "_autostart_owner", None)`, `... "_autostart_cancel_epoch", 0)`.
  Because these are process-wide, each test must both reset and restore them, and
  must cancel/await outstanding probes before its patches are undone.

**`tests/test_supervisor_autostart.py`** fixtures:

- `recorder` — `subprocess.Popen` patched to append argv and return `MagicMock`,
  optionally raising `OSError`;
- `fake_status_process` — a stub exposing `state()` and `start()`, so
  `refresh_status()` and the busy guard can be exercised **with explicit state
  transitions**: `start()` → `Starting`, then the fixture sets `NotRunning` before
  the test delivers output. This is required because `deliver()` calls
  `_on_status_finished` directly and does not move the real `QProcess` (an earlier
  draft missed this: test 3's post-consumption entry would be rejected as busy);
- `manager` — `SupervisorManager(workspace_root=tmp_path)` wired to the above;
- `deliver(manager, output, code=0, status=QProcess.ExitStatus.NormalExit)` — sets
  the fake process to `NotRunning`, fills `_status_output_buffer`, calls
  `_on_status_finished(code, status)`.

**A positive `arm()` helper is mandatory in tests.** Three review rounds found
negative-path tests that passed against an `start_if_not_running()` implemented as
`return False`. Every test that asserts "no spawn happened" therefore arms through
the helper, which asserts the arm actually took effect:

```python
def arm(manager, probes):
    """Claim the attempt and prove a probe was really launched."""
    assert manager.start_if_not_running() is True
    assert probes.count == 1                      # a QProcess.start really happened
    assert SupervisorManager._autostart_owner is manager
    assert manager._autostart_epoch == SupervisorManager._autostart_cancel_epoch
    return manager._autostart_epoch
```

A no-op implementation fails `arm()` immediately, and tests 16 and 17 pair their
negative expectation with a non-busy positive control in the same test.

| # | Test | Falsifiable because |
| --- | --- | --- |
| 1 | `starts_once_when_status_reports_stopped` | unchanged code spawns nothing; asserts `[exe, "start"]` + `start_new_session=True` |
| 2 | `does_not_start_when_running` | zero spawn **and** entry returned `True` with one probe launched |
| 3 | `is_one_shot_across_repeated_entry_calls` — entry twice before delivery, once **after** consumption, deliver stopped twice | a re-arming guard spawns 2-3 times; the fake process must be `NotRunning` so the post-consumption call is not masked by the busy guard |
| 4 | `manual_stop_during_first_probe_never_converts_into_a_start` — `arm()`, `stop_supervisor()`, then deliver the in-flight stopped output; argv exactly `[[exe, "stop"]]` | a claim that ignores cancellation yields `stop → start` |
| 5 | `manual_start_during_first_probe_never_double_starts` — `arm()`, `start_supervisor()`, deliver stopped; exactly one `start` argv | an invalidating cancel yields one `start` |
| 6 | `probe_failure_does_not_start_and_a_later_status_cannot_rearm` — `arm()`, `_on_status_error`, deliver stopped; zero spawns | fails if the claim survives the error |
| 7 | `unrecognised_output_never_starts` — three independently armed cases: `""`, `"usage: …"`, mixed running+stopped headers | `is_running == False` alone would start |
| 8 | `nonzero_exit_never_starts` — stopped output with `code=3` | guards the verified `NormalExit` + real-code case |
| 9 | `abnormal_exit_status_never_starts` — `CrashExit` | exit-status enum honoured separately |
| 10 | `disabled_by_environment` — for `1`/`true`/`TRUE`/` yes `: no probe, `_autostart_consumed` stays `False`; then, in the same test **without resetting state**, delete the env var and assert the enabled path starts | a mutant claiming before the env check leaves `consumed=True`; a no-op implementation fails the second half |
| 11 | `second_manager_never_starts_again` — both entries called and asserted `True`/`False` **before** either delivery; deliver stopped to both; one spawn | a mutant claiming only at completion passes a sequential version |
| 12 | `automatic_spawn_failure_is_silent` — `arm()`, then deliver stopped, then assert `Popen` **was actually attempted once** and raised (so the call was reached), no `action_completed` emitted, nothing escapes | only `silent=True` passes; the "attempted once" assertion prevents a never-reached vacuous pass |
| 13 | `manual_spawn_failure_still_reports` | preserves the dialog contract |
| 14 | `followup_probe_requested_only_after_a_successful_automatic_start` — counts refresh requests with uniform totals: success **2**, failed spawn **1**, running **1** | pins the local-result design |
| 15 | `cancel_is_process_wide_across_managers` — `arm(A)` (probe in flight), `manager_b.stop_supervisor()`, then A's stopped delivery; A spawns nothing | per-instance cancellation lets A start |
| 16 | `busy_probe_is_not_claimed` — fake process `Running`; entry returns `False` and `_autostart_consumed` stays `False`; then, in the same test, flip the fake to `NotRunning` and assert the entry **does** arm via `arm()` | the paired positive control makes a no-op implementation fail |
| 17 | `another_managers_poll_cannot_consume_or_authorise_the_claim` — start B's ordinary poll and let it error, then `arm(A)` while B's poll is still in flight, deliver B's stopped result, and assert B spawned nothing **and** `arm(A)`'s claim is still live and A starts on delivery | a single global flag lets B consume A's claim |
| 18 | `status_receiver_that_stops_wins` — `arm()`, connect a `status_updated` receiver that calls `stop_supervisor()`, deliver stopped; argv is `[[exe, "stop"]]` only | cached authorisation across the emit yields `start` then `stop` |

**`tests/test_main_window_autostart.py`** — must arm *for real* (patch
`subprocess.Popen` and the status process, keep the env var deleted).

| # | Test | Note |
| --- | --- | --- |
| 19 | `constructor_requests_one_attempt` — class-method spy on `start_if_not_running` installed before construction (attribute lookup happens at call time); asserts one call and that the constructor did not call `refresh_status` directly | pins the wiring |
| 20 | `quit_cancels_pending_autostart` — arm through the real entry method, assert the claim is live, call `_exit_application()`, assert the claim is dead and a later stopped delivery spawns nothing | quit-vs-hide |
| 21 | `hiding_to_tray_keeps_pending_autostart` — same setup, `close()` with `close_to_tray`; window hidden, claim still live | the opposite contract |
| 22 | `cancel_in_the_unsaved_changes_prompt_keeps_the_attempt` — arm, force `has_unsaved_changes()`, answer Cancel; claim still live (§3.4) | documents the chosen semantics |

Existing tests must keep passing unchanged, especially
`tests/test_supervisor.py::test_stop_supervisor_runs_stop_command` (argv
`[exe, "stop"]`, `start_new_session=True`, `action_completed("stop_supervisor",
True, …)`, trailing refresh).

Red-phase honesty: a test failing only because `start_if_not_running` does not
exist proves nothing. Tests 4, 6, 10, 11, 15, 16, 17, 18 were each reasoned against
the naive implementation it targets (shared flag, claim-at-completion, no busy
guard, cached authorisation) and fail against it.

## 7. Verification

1. `pytest` green, with the `Popen` recorder proving no `start`/`stop` argv during
   ordinary window tests.
2. Executable resolution: assert `find_ai_backends_executable` prefers the workspace
   copy when present, so tests do not silently depend on `/home/bin/ai-backends`
   (`supervisor.py:34`).
3. Manual, running: note PIDs from `ai-backends status`, launch `./start.sh`; PIDs
   unchanged, no restart.
4. Manual, stopped: `ai-backends stop`, launch; within a few seconds the label reads
   "Running (PID …)" and `ai-backends status` shows running backends.
5. Manual, stop race (pre-spawn): `ai-backends stop`, launch, click **Stop
   Supervisor** immediately; the supervisor must not come back.
6. Manual, missing script: point `AI_WORKSPACE_ROOT` at a directory with no
   `ai-backends` **and** shadow `PATH`, since the hardcoded `/home/bin` fallback is
   otherwise used; window opens, label stopped, **no dialog**.
