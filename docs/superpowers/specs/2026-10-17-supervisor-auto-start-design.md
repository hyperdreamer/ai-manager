# Design Document: Supervisor Auto-Start on Launch

## 1. Background & Goals

`ai-manager` administers the external `ai-backends` shell supervisor, which keeps
five local AI backends (`ai-grammar`, `textkit`, `yt2txt`, `chat2api`,
`file-bridge`) alive. Today the GUI only *observes* the supervisor: `MainWindow`
polls `ai-backends status` every `poll_interval_ms` and renders the result, but
nothing ever starts the supervisor. A user who launches `ai-manager` and sees
"Stopped / Inactive" must click **Start Supervisor** by hand.

This feature makes launching `ai-manager` guarantee that the supervisor is
running, without ever disrupting a supervisor that is already healthy.

### Goals

1. On launch, if `ai-backends status` reports `supervisor not running`, start the
   supervisor exactly once.
2. If the supervisor is already running, do nothing at all — no subprocess, no
   service disruption.
3. The behaviour is one-shot per process: the periodic status poll must never
   re-trigger it, so clicking **Stop Supervisor** leaves the supervisor stopped.
4. Failures (missing `ai-backends`, non-executable, spawn error) stay silent at
   startup and never block the window from appearing.
5. No new user-visible UI, no new persisted setting.
6. Test runs must never start, stop, or restart real backends.

### Non-Goals (explicitly out of scope)

- Auto-restart after the supervisor dies while the GUI is running.
- Auto-start on every poll, or a "keep alive" guarantee.
- Changing the semantics of `ai-backends start` (it is a full
  teardown-and-restart: `start_all_fresh()` in `/home/henry/Development/ai/ai-backends`
  TERMs the old supervisor, kills every backend by PID file and project-path scan,
  and starts all services fresh). This design never calls it on a running
  supervisor.
- A settings toggle, CLI flag, or tray entry for this behaviour.
- Changes to the toolbar buttons beyond removing a duplicated branch.

## 2. Approved Behaviour

Launch sequence, unchanged until the last step:

```text
MainWindow.__init__
  ├─ build UI, load configs, apply theme
  ├─ start poll timer (settings.poll_interval_ms, default 4000)
  └─ supervisor_manager.start_if_not_running()   ← was refresh_status()
```

`start_if_not_running()` behaves as follows:

| Probe result (`ai-backends status`) | Action |
| --- | --- |
| `supervisor running: <pid>` | nothing |
| `supervisor not running` | `/usr/bin/env python` detached `ai-backends start` once |
| probe could not run (missing executable, crash) | nothing |
| behaviour already consumed (latch clear) | nothing |

No new widget, label, dialog, menu item, or tray action is added. The only
user-visible consequence is that the existing "Supervisor:" label and the
per-service status badges change from "Stopped / Inactive" to
"Running (PID …)" a few seconds after launch, as today's poll already does.

The one UI-adjacent edit is a cleanup: `MainWindow._on_supervisor_btn_clicked`
currently contains an if/else whose two branches both call
`start_supervisor()`. The design collapses it to a single call. No behaviour
change, no new text.

## 3. Architecture

### 3.1 Components

`SupervisorManager` (`src/ai_manager/services/supervisor.py`) — owns all
`ai-backends` invocations. Gains two members:

```python
AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"

def __init__(...):
    ...
    self._autostart_pending: bool = False
    self._start_again_after_status: bool = False

def start_if_not_running(self) -> None:
    """Probe once, and start the supervisor only if it is not running."""

def _spawn_start(self) -> None:      # existing body of start_supervisor
def start_supervisor(self) -> None:  # public button/tray entry point, unchanged
```

`MainWindow` (`src/ai_manager/ui/main_window.py`) — one line changes; it calls
`start_if_not_running()` where it currently calls `refresh_status()`.

### 3.2 Flow

```text
start_if_not_running()
  if env AUTOSTART_DISABLE_ENV is "1"/"true"/"yes" → return
  if self._autostart_pending → return          # idempotent
  self._autostart_pending = True
  self.refresh_status()                        # async QProcess probe

_on_status_finished(exit_code, status)
  armed = self._autostart_pending
  self._autostart_pending = False              # consume: one shot, always
  started_for_autostart = armed and not status.is_running
  if started_for_autostart:
      self._spawn_start()                      # NOT start_supervisor()
  self.status_updated.emit(status)             # unchanged ordering otherwise
  if started_for_autostart:
      self._start_again_after_status = True

_on_action... (no action process involved)

_on_status_error(error)
  self._autostart_pending = False              # a failed probe never auto-starts
  self.status_updated.emit(stopped)            # unchanged
```

Why `_spawn_start()` and not `start_supervisor()`: `start_supervisor()` ends by
calling `refresh_status()` itself. Re-arming the latch on that internal refresh
would mean "not running" is still true (the detached supervisor needs a moment to
write its PID file), and the poll would start the supervisor again in a loop.
`_spawn_start()` shares the exact same spawn code plus the same
`action_completed` signal, so a genuine spawn failure still surfaces through the
existing warning dialog, but it does not schedule another probe.

A second probe is still desirable after a successful spawn so the UI reflects the
new supervisor quickly rather than waiting for the next tick. That is what
`_start_again_after_status` exists for: `status_updated` is emitted first (so
listeners observe a real, fully parsed status for that probe, matching today's
contract), and only then a single follow-up `refresh_status()` is issued. The
follow-up probe is a plain refresh — the latch is already clear, so the poll and
this refresh can never start anything.

### 3.3 Latch semantics (the load-bearing rule)

`_autostart_pending` is cleared in **every** terminal path of the probe:
`_on_status_finished`, `_on_status_error`, and the entry guard of
`start_if_not_running`. There is no path that leaves it armed across a poll
tick, therefore:

- the 4 s poll timer can never auto-start;
- pressing **Stop Supervisor** stays stopped (its own `refresh_status()`, and
  every later poll, sees a clear latch);
- two windows in the same process each own their own manager, so each probes
  once. Two concurrent starts are harmless: `ai-backends start` is idempotent in
  the sense that the second invocation TERMs the first supervisor and re-adopts
  the same backends, and this is bounded to once per window per process launch.

## 4. Error Handling

| Failure | Behaviour |
| --- | --- |
| `ai-backends` not on PATH and not in the workspace | `QProcess` fails to start → `errorOccurred` → latch cleared, `SupervisorStatus(is_running=False, services={})` emitted, window usable, status shows "Stopped / Inactive" |
| `ai-backends` present but exits non-zero | `_on_status_finished` runs; `parse_supervisor_status` finds no `supervisor running:` line, so `is_running` is `False` and a start is attempted once. If the spawn itself then fails, the existing `action_completed(..., False, ...)` warning dialog is shown — this is the pre-existing behaviour for the toolbar button and is not new user-facing surface |
| Probe never finishes (hung script) | `_autostart_pending` stays armed until the QProcess reports finished or errors; nothing polls it into a loop because `refresh_status` returns early while a probe is in flight |
| App closed before the first probe completes | `QProcess` is a child of the manager, so Qt destroys it; the detached `ai-backends` (if already spawned) is `start_new_session=True` and survives the GUI, as today |

Startup never blocks: the probe and the spawn are both non-blocking
(`QProcess` / `subprocess.Popen`), so the window paints immediately.

## 5. Test-Safety Hazard

`tests/test_main_window.py`, `test_main_window_tray.py`, `test_mnemonic.py`, and
`test_e2e_integration.py` construct a real `MainWindow` against temp workspaces.
`SupervisorManager` resolves its executable via `find_ai_backends_executable`,
which falls back to a PATH lookup, so on this machine those tests would run a real
`ai-backends start` — tearing down and restarting the developer's five live
backends during `pytest`.

Mitigation (defence in depth, both required):

1. `start_if_not_running()` returns immediately when the environment variable
   `AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART` is `1`, `true`, or `yes`
   (case-insensitive). An explicit opt-out that also serves packagers.
2. `tests/conftest.py` gets an autouse, session-scoped fixture that sets that
   variable via `monkeypatch.setenv` before any test builds a `MainWindow`.
   Because it lives in `conftest.py` it applies even when a single test module is
   run directly (`pytest tests/test_main_window.py`), which a plain `os.environ`
   assignment in one module would not.
3. `tests/test_supervisor_autostart.py` opts back in with
   `monkeypatch.delenv(AUTOSTART_DISABLE_ENV, raising=False)` and asserts the
   enabled path.

The autouse fixture must not carry `autouse=True` on a `session`-scoped fixture
that needs `monkeypatch` (function-scoped). It is therefore a function-scoped
autouse fixture that calls `monkeypatch.setenv`; that is cheap and guarantees
isolation even if a test clears the environment.

## 6. Test Strategy (TDD; written first, red before implementation)

New file `tests/test_supervisor_autostart.py`, each test built on a
`SupervisorManager(workspace_root=tmp_path)` whose `subprocess.Popen` is patched
to record argv and to return a `MagicMock` (`refresh_status` is patched to a
recorder where a test cares about probe scheduling):

1. `test_start_if_not_running_starts_when_status_reports_stopped` — feed
   `SAMPLE_STOPPED_OUTPUT` through `_on_status_finished`; expect exactly one
   `Popen` with `[executable, "start"]` and `start_new_session=True`.
2. `test_start_if_not_running_does_nothing_when_already_running` — feed
   `SAMPLE_RUNNING_OUTPUT`; expect zero `Popen`.
3. `test_autostart_is_one_shot_after_a_stopped_probe` — after case 1, feed
   `SAMPLE_STOPPED_OUTPUT` again (simulating a later poll tick after the user
   pressed Stop); expect the `Popen` count to stay at one.
4. `test_autostart_skips_when_probe_fails` — call `_on_status_error(...)` with
   the latch armed; expect zero `Popen`.
5. `test_autostart_can_be_disabled_by_environment` — set the env var to `1`;
   `start_if_not_running()` must not even probe (`refresh_status` recorder stays
   empty) and a later stopped status must not start anything.
6. `test_autostart_ignores_stale_armed_flag_when_disabled_mid_flight` — arm,
   then delete the env var? (negated case: armed once, env var set afterwards
   still allows the already-armed start; documents that the check is at entry).
7. `test_main_window_autostarts_instead_of_only_refreshing` — build a
   `MainWindow` with `main_window_module` settings patched (mirroring the tray
   fixture), spy on `supervisor_manager.start_if_not_running` **before** the
   constructor runs is not possible, so instead assert the manager was asked:
   patch `SupervisorManager.start_if_not_running` with a counter class attribute
   and assert it is `1` after construction and that `refresh_status` was not
   called directly by the window.

Existing tests must keep passing unchanged: `tests/test_supervisor.py` asserts
the `stop` argv contract, which is untouched.

## 7. Verification

- `pytest` (whole suite) green, with the autouse guard proving no real
  `ai-backends` invocation happens (a `Popen` recorder or the env guard).
- Manual: with the supervisor running, launch → no restart (PIDs unchanged).
  With it stopped (`ai-backends stop`), launch → supervisor comes up within a
  few seconds and the toolbar label flips to "Running (PID …)".
