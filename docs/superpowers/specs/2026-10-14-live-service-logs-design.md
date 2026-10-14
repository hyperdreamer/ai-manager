# Design Document: Live Service Log Tabs

## 1. Background & Goals

`ai-manager` supervises three backends (`ai-grammar`, `textkit`, `yt2txt`) through
the external `ai-backends` supervisor and already knows where each service writes
its log: `ai-backends status` prints a `log=<path>` column that
`parse_supervisor_status` stores in `ServiceStatus.log_path`. Today the GUI never
shows that content, so diagnosing a failing backend means leaving the app for a
terminal and running `tail -f` by hand.

This feature adds a **Logs tab to each service's detail view** so a user can watch
a service's output live in the same place they restart and configure it.

### Goals

1. A second tab, `Logs`, beside the existing configuration form in every
   `AppDetailView`; the header (title, status badge, *Restart Service Only*)
   remains visible above the tab bar.
2. The tab shows the tail of the service's log file, refreshing about once per
   second while visible, with **Follow** (auto-scroll, on by default) and
   **Pause** controls.
3. No new subprocesses: log data is read directly from the path the supervisor
   already reports, with a deterministic fallback path.
4. Bounded cost: opening a tab never reads a whole log file, an idle/hidden tab
   never polls, and every single poll has a hard byte budget.

### Non-Goals (explicitly out of scope)

- Aggregated multi-service log view, floating log window, or log tab outside the
  detail view (Option B/C mockups were rejected).
- `tail -f` subprocesses, remote logs, or journald/`systemd` sources.
- Log rotation management, retention policy, or deletion.
- Level filtering, syntax coloring, regex search, or timestamp rewriting.
- Writing to log files, or any change to `ai-backends` itself.

## 2. Approved UI (Option A)

```text
┌────────────────────────────────────────────────────────────────────┐
│ ai-grammar (Port 8766)                ● Running (PID 107255)       │
│ Grammar checking, polishing, and…           [Restart Service Only] │
│ ┌─[ Configuration ]─┬───── Logs ─────┐                             │
│ │ AI Provider Settings               │  ← QTabWidget, page 0 active │
│ │   Preset / API Base URL / API Key  │                             │
│ │ Model Configuration                │                             │
│ │ [Save Config Only] [Save & Restart]│                             │
│ └────────────────────────────────────┴─────────────────────────────┘
```

Logs page (page 1), same window chrome:

```text
┌────────────────────────────────────────────────────────────────────┐
│ ● Live      [⏸ Pause]  [☑ Follow]  [Open log file] [Copy] [Clear]   │
│ service running · 1 204 lines                                       │
│ 2026-10-14 11:56:12 INFO  grammar check ok                          │
│ 2026-10-14 11:57:02 ERROR upstream timeout                          │
│ 2026-10-14 11:57:03 INFO  retrying once                             │
└────────────────────────────────────────────────────────────────────┘
```

The user selected this option over window-level tabs (duplicate navigation state,
must reconcile with unsaved drafts) and a docked bottom panel (permanently halves
the configuration area).

**Two independent state displays (resolves review finding 5).** The header
`StatusBadge` keeps showing service run state exactly as today. Inside the log
page, the left chip reports **file health only** and the muted line below reports
**service state only**:

| Chip (file health) | Meaning |
| --- | --- |
| `● Live` | file readable and being consumed |
| `⏸ Paused` | consumption paused by the user; file still readable |
| `⚠ Log file not found` | path resolved but the file does not exist |
| `⚠ Log unreadable: <reason>` | e.g. permission denied |
| `◌ No log path` | no path resolved yet and the fallback is unavailable |

| Muted line (service state) | Meaning |
| --- | --- |
| `service running` | `ServiceRunState.RUNNING` |
| `service stopped` | `ServiceRunState.STOPPED` |
| `service restarting` | `ServiceRunState.TRANSITIONING` |
| `service unknown` | `ServiceRunState.UNKNOWN` (incl. supervisor inactive) |

Precedence is structural, not a priority list: file health owns the chip, service
state owns the muted line, so a supervisor status update can never erase a
missing-file warning and vice versa. `● Live` and `⏸ Paused` assert *successful
consumption*: a stat-only check can never promote the chip to `● Live` by itself,
and a probe cannot clear an error that a read actually discovered (finding 14).

## 3. Architecture & Components

Four small units, each independently testable. The Qt layer depends on the reader;
the reader depends on nothing but the standard library.

### 3.1 `LogTailReader` — `src/ai_manager/services/log_tailer.py` (new, pure Python)

Incremental, rotation-tolerant reader for one append-only log file.

```python
class LogFileStatus(str, Enum):
    UNSET = "unset"        # no path configured
    OK = "ok"
    MISSING = "missing"    # path configured, file does not exist
    UNREADABLE = "unreadable"  # exists but stat/open/read failed

class FilePresence(str, Enum):
    UNSET = "unset"            # no path configured
    MISSING = "missing"        # stat says ENOENT/ENOTDIR
    PRESENT = "present"        # stat succeeded; readability NOT asserted
    UNAVAILABLE = "unavailable"  # stat failed for another reason (e.g. EACCES on a parent)

@dataclass(frozen=True)
class LogReadBatch:
    lines: List[str]                    # complete lines, newline-stripped, in order
    status: LogFileStatus = LogFileStatus.OK
    reset: Optional[str] = None         # None | "created" | "truncated" | "rotated"
    error: Optional[str] = None         # human-readable reason when status != OK
    more_pending: bool = False          # budget exhausted; call again to continue


class LogTailReader:
    def __init__(self, *, initial_bytes: int = 65_536,
                 max_batch_bytes: int = 262_144,
                 max_line_bytes: int = 16_384) -> None: ...

    @property
    def path(self) -> Optional[Path]: ...

    def set_path(self, path: Optional[Union[str, Path]]) -> bool:
        """Point the reader at a log file; True when the target actually changed.
        Accepts str or Path (normalized with os.fspath). Changing the target resets
        offset, device/inode identity, partial line and error state."""

    def probe_health(self) -> Tuple[FilePresence, Optional[str]]:
        """stat-only presence check used while paused. Never reads, never advances
        the offset, never mutates state, and never claims readability."""

    def read_new_lines(self) -> LogReadBatch:
        """Return up to max_batch_bytes of newly appended content."""
```

Every call reports `status` for the current poll, so the view never has to guess
whether a missing file is new, persistent, or recovered. `reset` is only ever set
when `status is OK`.

Contract:

| Situation | Behaviour |
| --- | --- |
| `path is None` | `LogReadBatch([], LogFileStatus.UNSET)` |
| Path configured, file absent | `LogReadBatch([], MISSING, error=<path>)`; repeats on every poll until it appears |
| Path configured, `probe_health()` says `MISSING` | metadata-only confirmation; readable by the view even while paused |
| Path configured, `probe_health()` says `PRESENT` | presence only — **not** proof of readability, because `stat` succeeds on an unreadable file |
| Path configured, `probe_health()` says `UNAVAILABLE` | e.g. a parent directory denies search; treat as unreadable metadata |
| File exists, open/read fails | `LogReadBatch([], UNREADABLE, error=<oserror reason>)`; the offset is kept so a transient failure cannot duplicate output |
| A previously `UNREADABLE`/`MISSING` file becomes readable again | `status=OK`; reading resumes from the retained offset, and `reset` stays `None` unless the file was genuinely new or reappeared |
| First successful read of a target | seek to `max(0, size - initial_bytes)`; when starting mid-file, drop the first partial line; `status=OK, reset="created"` |
| `size == offset` and `mtime_ns` unchanged | `([], OK)` — the common case, one `stat` only |
| `size == offset` but `mtime_ns` changed | Rewritten in place at equal size: reset via the initial-read rule (trailing `initial_bytes` window), `reset="truncated"` |
| `size < offset` | Truncated: reset to `max(0, size - initial_bytes)` via the initial-read rule, `reset="truncated"` |
| `st_ino`/`st_dev` changed (rotated) | Same as truncation but `reset="rotated"` |
| File missing, previously OK | `MISSING` (with `error`) for the first time and on every subsequent poll while absent |
| File (re)appears | Normal initial read, `reset="created"` |
| No trailing `\n` | Bytes after the last `\n` are buffered as a partial line; emitted only once a `\n` arrives |
| Bytes > `max_line_bytes` with no `\n` | Emit the decoded prefix plus `" …[line truncated]"`, then discard bytes until the next `\n` |
| Bytes > `max_batch_bytes` available | `lines` filled up to the budget, `more_pending=True`; the caller drains with further calls |
| Undecodable bytes | Decoded per line with `errors="replace"`; never raises |

**Bounding (resolves review finding 4).** Every code path — initial read,
rotation reset, truncation reset, and a large backlog accumulated while paused —
uses the same two bounds: at most `max_batch_bytes` bytes are read per call, and a
reset never re-reads more than the trailing `initial_bytes`. There is no path that
reads a whole log file. `more_pending` lets the view drain without a single huge
batch.

**Test seam.** Files are opened through a module-level `_open_file(path)` helper so
tests can wrap the handle and record every `read(n)` call; byte bounds are asserted
against those records instead of being inferred from returned lines (resolves
review finding 13).

**Stated limitation (no quantitative bound).** A truncate-and-regrow that completes
inside one poll interval and ends past the previous offset is indistinguishable from
an append without content comparison. It is detected when either the size shrinks
below the offset or `mtime_ns` changes at equal size (the `copytruncate` cases this
design targets). The reader has no clock and performs no content comparison, so the
undetected case may duplicate a suffix of the rewritten content of unspecified
length; the requirement is only that it can never crash, corrupt reader state, or
mis-state file health. This limitation is documented rather than engineered around
(YAGNI), and the detected cases are covered by explicit tests. The specification's
R20 is the normative wording.

The reader holds no Qt imports and no line cap; bounding the *view* is
`QPlainTextEdit.setMaximumBlockCount`.

### 3.2 `LogViewWidget` — `src/ai_manager/ui/widgets/log_view.py` (new)

```python
class LogViewWidget(QWidget):
    LOG_POLL_INTERVAL_MS = 1000
    MAX_LINES = 5000
    MAX_READS_PER_TICK = 4          # ≤ 1 MiB consumed per tick

    def __init__(self, service_id: str, parent: Optional[QWidget] = None) -> None: ...

    def set_log_path(self, path: Optional[Union[str, Path]]) -> None
    def set_service_state(self, state: ServiceRunState) -> None
    def set_paused(self, paused: bool) -> None
    def set_follow(self, follow: bool) -> None
    def clear_view(self) -> None    # clears text only; read offset untouched
    def poll_once(self) -> None     # public seam used by tests and the QTimer
    @property
    def is_polling(self) -> bool    # True while the QTimer is active
```

Contents and behaviour:

- `QPlainTextEdit` (object name `logView`), read-only, no wrap,
  `setMaximumBlockCount(MAX_LINES)`, fixed-width font from
  `QFontDatabase.systemFont(FixedFont)` so tests are font-independent.
- Toolbar row: file-health chip, `⏸ Pause` / `▶ Resume` toggle, `☑ Follow`
  checkbox (checked), `Open log file`, `Copy`, `Clear`; second muted line with the
  service state and the line counter (`"1 204 lines"`, `"5 000 lines (capped)"`).
- `poll_once()` first calls `reader.probe_health()` on **every** tick, including
  while paused, so presence changes are always current; then, unless paused, it
  performs at most `MAX_READS_PER_TICK` reader calls, appending each batch.
  `more_pending` is consumed on the next call within the same tick, so a resumed
  backlog drains at ≤ 1 MiB per second and the UI thread never blocks on a giant
  read. Pause therefore gates content only, never presence (resolves review
  finding 11).
- `reset` values render one plain-text marker line (`------ log rotated ------`,
  `------ log truncated ------`, `------ log file created ------`). Content is
  always **plain text** — log output is untrusted and is never parsed as HTML.
- **File-health rendering (resolves findings 1, 12 and 14).** Read batches are the
  **authoritative** source of readability, because only an actual open/read can
  distinguish `OK` from `UNREADABLE`; `probe_health()` contributes presence only.
  The chip is a pure function of (presence, paused, last read-observed status):

  | Presence | Paused | Last read status | Chip |
  | --- | --- | --- | --- |
  | `UNSET` | any | – | `◌ No log path` |
  | `MISSING` | any | – | `⚠ Log file not found` |
  | `UNAVAILABLE` | any | – | `⚠ Log unreadable: <reason>` |
  | `PRESENT` | yes | `UNREADABLE` | `⚠ Log unreadable: <reason>` (retained) |
  | `PRESENT` | yes | anything else | `⏸ Paused` |
  | `PRESENT` | no | batch `OK` | `● Live` |
  | `PRESENT` | no | batch `UNREADABLE` | `⚠ Log unreadable: <reason>` |

  A read-observed `UNREADABLE` clears only on a successful read of the same file
  identity, or on a successful read after the identity changes (a replaced file is a
  fresh subject), so a
  paused `PRESENT` probe can never mask a real read error. On a chip change the view
  renders exactly one placeholder line for `MISSING`, `UNREADABLE` or `UNSET`
  (`Log file not found: <path>`, `Cannot read log file: <reason>`, `No log file
  resolved yet`), replacing a previous placeholder rather than stacking a new one.
  A return to `OK` always removes the placeholder; a `------ log file created
  ------` marker is rendered **only** when a batch carries `reset="created"`, so a
  transient error clearing without a file change resumes output from the retained
  offset with no misleading marker. Because presence is probed on every tick, a
  service that starts writing later recovers with no user action. Errors are
  surfaced once per transition, not once per poll.
- **Path changes (resolves finding 6).** `set_log_path()` is deliberately
  **history-preserving**: existing lines stay in the view, and the reader is reset to
  the new target, so the next poll renders `------ log file changed: <path> ------`
  followed by the new file's tail. History is never silently wiped on a status
  refresh (which may legitimately re-report the fallback path), and the marker keeps
  the concatenation truthful. `clear_view()` remains the explicit way to wipe text.
- Follow semantics: auto-scroll happens only when Follow is checked; unchecking
  Follow lets the user scroll freely without being yanked to the bottom.
- Pause semantics: Pause stops consuming bytes (the timer keeps running and the
  offset is untouched), so resuming shows exactly the output produced while paused,
  drained under the per-tick budget.
- Timer lifecycle: started in `showEvent`, stopped in `hideEvent`. Inside a
  `QTabWidget` this means only the visible tab polls; the default `Configuration`
  tab never reads a log file at all.
- `Open log file` uses `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`; when
  that returns `False` the chip tooltip carries the raw path instead of failing.
  `Copy` copies the selection, or all text when nothing is selected.

### 3.3 Tab integration — `src/ai_manager/ui/app_detail_view.py` (modified)

- Wrap the existing `QScrollArea` **and** the footer action bar into a
  `Configuration` page; add a `Logs` page holding one `LogViewWidget`.
- New `QTabWidget` sits below the header frame and fills the rest of the view;
  the footer's Save buttons live inside the Configuration page because they act on
  the config draft, not on logs.
- New `log_view` property exposing the page's widget for the window layer and tests.
- **Path resolution with memory (resolves finding 3).** `AppDetailView` holds
  `_known_log_path: Optional[str]`. In `update_service_status(status)`:
  1. if `status.log_path` is non-empty, set `_known_log_path = status.log_path`;
  2. pass `_known_log_path if _known_log_path else str(default_log_path(app_id))`
     to `log_view.set_log_path(...)`;
  3. pass `status.state` to `log_view.set_service_state(...)`;
  4. keep updating the header `StatusBadge` exactly as today.
  A later status without `log_path` therefore **cannot** downgrade an explicit path
  to the fallback; the fallback is used only before any path has ever been reported.
- Tab switching is inert with respect to config state: `config_changed` is never
  emitted by tab switching, so dirty/asterisk behaviour in the sidebar is unchanged.

### 3.4 Fallback path — `src/ai_manager/services/supervisor.py` (modified)

```python
def default_log_path(service_id: str) -> Path:
    """~/.cache/ai-backends/logs/<service_id>.log — used only when no log_path was ever reported."""
```

`SERVICE_LINE_RE` already requires `log=<path>`, so a hypothetical row without a
log column does not match and the service is simply absent from
`status.services`; the absent-service path below supplies the fallback and this
design leaves the existing regex untouched (resolves finding 2).

### 3.5 Main window — `src/ai_manager/ui/main_window.py` (modified)

`_on_supervisor_status` gains one normalization step before touching widgets
(resolves findings 2, 7 and 10):

- when `status.is_running` is `True`, a managed app absent from `status.services`
  receives `ServiceStatus(service_id=app_id, state=ServiceRunState.UNKNOWN)`;
- when `status.is_running` is `False`, **every** managed app receives that
  synthetic `UNKNOWN`, because a stopped supervisor's service rows (which
  `parse_supervisor_status` can still emit from residual output) are not
  authoritative;
- reported rows are echoed unchanged only while the supervisor is running.

The resulting status is forwarded **to both the sidebar and the detail view**.
`StatusBadge` already renders `UNKNOWN` as `Unknown`, so a stopped supervisor can no
longer leave stale `Running` — or misleading `Stopped` — badges in the sidebar, the
header, or the log tab's service line.

### 3.6 Theme — `src/ai_manager/ui/theme.py` (modified)

Add to both `DARK_QSS` and `LIGHT_QSS`:

- `QTabWidget::pane` (border/background matching `QGroupBox`),
- `QTabBar::tab`, `:hover`, `:selected` (selected tab tinted with the existing
  `#93c5fd` accent on dark / `#2563eb` on light, consistent with the toolbar),
- `QPlainTextEdit#logView` (dark `#121217` on `#d4d4d8`; light `#ffffff` on `#1e293b`,
  monospace family, matching selection colors),
- `QLabel#logStatusChip`, `QLabel#logServiceState` and `QLabel#logLineCounter`
  muted-text styles.

## 4. Data Flow

```text
QTimer (1000 ms, only while Logs tab visible)
        │
        ▼
LogViewWidget.poll_once()   ── probe_health() every tick (presence only) ──┐
        │                   ── unless paused: up to 4 × read_new_lines() │
        │                          LogTailReader  ──stat/seek/read──►   │  <log file>
        │  LogReadBatch(lines, status, reset, error, more_pending) ◄────┘
        ▼
QPlainTextEdit.appendPlainText(line)          (cap 5 000 blocks)
        │
        ├─ status change → chip + single placeholder line
        ├─ reset → one plain-text marker line
        └─ if follow: move cursor to end

SupervisorManager.refresh_status() ──poll_interval_ms (4 s, unchanged)──►
  MainWindow._on_supervisor_status → normalize, then for every managed app:
    is_running ? (reported row, else synthetic UNKNOWN) : synthetic UNKNOWN
    sidebar.update_status(status) + AppDetailView.update_service_status(status)
      → StatusBadge (unchanged) + LogViewWidget.set_service_state/set_log_path
```

The two timers are intentionally independent: status polling stays at the user's
`poll_interval_ms`, while log reading is a cheap local `stat` plus a bounded
incremental read at 1 s.

## 5. Error Handling

| Failure | User-visible behaviour |
| --- | --- |
| Log path unknown and fallback file missing | Chip `⚠ Log file not found`, one placeholder line naming the path; re-checked every poll, so creating the file recovers automatically |
| Permission denied / read error | Chip `⚠ Log unreadable: <reason>`, one placeholder line; repeated attempts do not spam the view |
| Supervisor stopped (`is_running=False`) | Every service's muted line reads `service unknown` regardless of residual reported rows; the last known path is **retained** (never downgraded to the fallback) and still tailed if the file exists, because post-mortem output matters most |
| File health changes while paused | Presence is probed every tick, so `⚠ Log file not found` can appear while paused; a read-discovered `⚠ Log unreadable` is retained until a successful read, because `stat` cannot prove readability |
| Rotation / truncation / equal-size rewrite | Marker line in the view, reader restarts under the `initial_bytes` bound, no crash, no unbounded read |
| Gigantic file | Initial and reset reads bounded by 64 KiB; each poll bounded by 256 KiB |
| Backlog while paused | Drained at ≤ 1 MiB/s across ticks (`MAX_READS_PER_TICK`) |
| Line longer than 16 KiB | Emitted truncated with ` …[line truncated]`, remaining bytes skipped to the next newline |
| Non-UTF-8 output | Replaced characters, never an exception |

## 6. Test Strategy

All tests run headless (`QT_QPA_PLATFORM=offscreen`, existing `conftest.py`) and
never invoke `ai-backends`; log files are created under `tmp_path`.

- **`tests/test_log_tailer.py` (new, pure unit).** `UNSET` for no path; `MISSING`
  with an error reason for an absent file and `reset="created"` when it appears;
  `UNREADABLE` for a chmod-000 file (skipped when running as root); `set_path`
  change detection and str/`Path` acceptance; initial read of only the last
  `initial_bytes` with the first partial line dropped; append → only new lines;
  unchanged size+mtime → empty batch; in-place truncation → `reset="truncated"`
  with a bounded re-read; equal-size rewrite (new content, same length, newer
  mtime) → `reset="truncated"`; inode change → `reset="rotated"`; partial trailing
  line held until `\n`; over-long line truncated once and remainder skipped;
  invalid UTF-8 replaced without raising; a > `max_batch_bytes` append returns
  `more_pending=True` and drains across repeated calls without loss or duplication;
  `probe_health()` never advances the offset (an append made while probing is still
  delivered by the next read) and reports `MISSING`/`PRESENT`/`UNAVAILABLE`
  presence transitions without claiming readability; a transient `UNREADABLE` that
  clears resumes from the retained offset with `reset=None`.
- **`tests/test_log_view.py` (new, Qt offscreen).** `poll_once` renders appended
  lines; `MAX_LINES` cap enforced through `maximumBlockCount`; Pause stops
  consumption and Resume delivers the backlog; Follow toggling changes auto-scroll
  without losing lines; `clear_view` empties the view and the next poll does not
  resurrect old output; marker lines for rotation; file-health chip transitions
  (`OK`→`MISSING`→`OK`) render exactly one placeholder at a time; while paused, a
  deleted file still flips the chip to `⚠ Log file not found` and Resume then
  delivers the backlog; a chmod-000 file (skipped as root) sets
  `⚠ Log unreadable`, is paused, is made readable again, and the chip stays
  `⚠ Log unreadable` across paused ticks until a successful read clears it; path
  switch keeps history and adds the `log file changed`
  marker without mixing the two files' offset state; service-state line and chip
  evolve independently (a status update cannot clear a missing-file warning).
- **`tests/test_app_views.py` (extended).** Each `AppDetailView` exposes exactly the
  `Configuration` and `Logs` tabs with `Configuration` default; toggling the
  split-model checkbox still yields the same draft (dirty state unaffected);
  `update_service_status` remembers an explicit `log_path` and does not replace it
  with the fallback on a later status lacking one.
- **`tests/test_main_window.py` (extended).** A supervisor status routed through
  `_on_supervisor_status` reaches the per-app log view; a status payload that omits
  an app while the supervisor runs sends synthetic `UNKNOWN` to **both** the sidebar
  and the detail view; a payload with `is_running=False` that still carries service
  rows sends `UNKNOWN` for every managed app.
- **I/O bounds (resolves finding 13).** Tests monkeypatch the reader's `_open_file`
  seam to record every `read(n)` size and assert `max(sizes) <= max_batch_bytes` for
  initial reads, rotation/truncation resets and backlog drains; and monkeypatch
  `view._reader.read_new_lines` to assert the call count per `poll_once()` never
  exceeds `MAX_READS_PER_TICK`.
- **Visibility (resolves finding 8).** Polling gating is tested in a real
  hierarchy, not a bare `show()`/`hide()`: build a `QTabWidget` whose second page is
  the log view, assert `is_polling` is `False` on the Configuration page and `True`
  after `setCurrentIndex(1)`, then `False` again after switching back; repeat for a
  `QStackedWidget` standing in for `MainWindow.stack`.
- **`tests/test_widgets.py` (extended).** Theme test asserts tab, pane, `logView`,
  and log-status-label QSS exist in both `DARK_QSS` and `LIGHT_QSS`.

## 7. Compatibility & Risks

- **No persisted state changes.** No new settings, no `settings.json` keys, no
  config-file changes; the feature is read-only with respect to every external file.
- **Log format is opaque.** Nothing parses log lines, so format changes in the
  backends cannot break the view.
- **Layout change is acknowledged (resolves finding 9).** The detail view gains a
  tab bar and the footer moves inside the Configuration page, so *rendered*
  screenshots of the detail view change; what stays valid is the QSS contract — the
  new rules are additive and the existing style assertions in `tests/test_widgets.py`
  are unaffected. `docs/superpowers/specs/mockups/` screenshots that show the old
  detail view are historical and are not regenerated by this work.
- **Risk: 1 s polling cost.** Mitigated by `stat`-first reads, `showEvent`/`hideEvent`
  gating, and the 256 KiB per-poll bound. A hidden tab performs zero syscalls.
- **Risk: unbounded memory.** Bounded by `setMaximumBlockCount(5 000)` and the
  16 KiB per-line cap; the pathological upper bound is ≤ 5 000 × 16 KiB.
- **Risk: `QDesktopServices` unavailable in headless CI.** Guarded by the
  `openUrl` return value; the tooltip carries the path instead.
- **Reversibility:** the feature adds one reader, one widget, one tab page and
  additive QSS; removing it means deleting the two new files and reverting three
  small hunks.

## 8. Design Review Resolutions

| # | Finding (attempt 2) | Resolution |
| --- | --- | --- |
| 1 | Blocker: `LogReadBatch` cannot report missing/unreadable/error reasons | Added `LogFileStatus`, `status`, `error`, `more_pending`; §3.1 contract table + §3.2 single-placeholder transition rule + §5 |
| 2 | Major: UNKNOWN forwarding, mandatory `log=` column, `Path` vs `str` | §3.5 forwards synthetic UNKNOWN to all managed apps incl. sidebar; §3.4 documents the untouched regex path; `set_path`/`set_log_path` accept `Union[str, Path]` |
| 3 | Major: fallback replaced a known custom path | §3.3 `_known_log_path` memory; fallback only before any path was reported |
| 4 | Major: unbounded reset/backlog/paused reads; copytruncate | §3.1 `max_batch_bytes` on every path, bounded resets, equal-size mtime detection, explicit limitation without a time bound; §3.2 `MAX_READS_PER_TICK` |
| 5 | Major: chip conflated file health and service state | §2 two separate displays with structural precedence; chip/state tables |
| 6 | Major: `set_log_path` vs "no cross-contamination" test | §3.2 history-preserving with `log file changed` marker; test reworded in §6 |
| 7 | Minor: sidebar stale Running for absent services | §3.5 synthetic UNKNOWN to both sidebar and detail view; §6 test |
| 8 | Minor: show/hide test does not prove tab gating | §6 real `QTabWidget`/`QStackedWidget` visibility test |
| 9 | Minor: screenshot compatibility claim | §7 narrowed to the QSS contract; layout change acknowledged |
| 10 | Blocker (attempt 3): inactive supervisor could still render reported `stopped` rows | §3.5 normalization: `is_running=False` forces synthetic `UNKNOWN` for every managed app; §5 table updated; §6 test |
| 11 | Major (attempt 3): paused view cannot detect file-health changes | §3.1 `probe_status()` stat-only API; §3.2 probe runs every tick, pause gates content only; §6 tests |
| 12 | Major (attempt 3): transient `UNREADABLE` clearing wrongly implied a `created` marker | §3.1 recovery keeps the offset with `reset=None`; §3.2 marker only on `reset="created"`; §6 test |
| 13 | Major (attempt 3): tests could not prove the I/O bounds | §3.1 `_open_file` instrumentation seam; §6 test asserts per-call byte maxima and per-tick call counts |
| 14 | Major (attempt 5): `stat`-only probe cannot prove readability and could clear a real read error while paused | §3.1 `FilePresence` metadata enum replaces probe-status claims; §3.2 read batches are authoritative with an explicit chip truth table; §6 chmod-000 retention test |
