# Specification: Live Service Log Tabs

## 1. Background & Goals

`ai-manager` already receives each backend's reported log path from `ai-backends status`, but the GUI does not expose the file contents. This specification adds a per-service `Logs` tab beside the existing configuration form so diagnosis does not require a separate terminal.

**Goals**

1. Add a `Logs` tab to every `AppDetailView` while keeping the existing header, status badge, and `Restart Service Only` action visible.
2. Tail the resolved service log about once per second while the Logs page is visible, with Follow enabled by default and an explicit Pause control.
3. Read directly from the supervisor-reported path, using a deterministic fallback only before any explicit path has been reported; do not spawn a subprocess.
4. Bound all I/O and UI memory: initial/reset reads use `initial_bytes`, each reader call uses `max_batch_bytes`, each tick uses `MAX_READS_PER_TICK`, and the text widget caps blocks at `MAX_LINES`.

**Non-goals**

- Aggregated multi-service views, floating log windows, or window-level log tabs.
- `tail -f` subprocesses, remote logs, journald, or `systemd` log sources.
- Rotation retention or deletion management.
- Level filtering, syntax coloring, regex search, timestamp rewriting, or log parsing.
- Writing to log files or modifying `ai-backends`.

The feature is read-only with respect to external log files and preserves the existing configuration-draft workflow.

## 2. Approved UI

Each service detail view keeps its existing header (service title, port, status badge, description, and `Restart Service Only`) above a `QTabWidget`. The tabs are exactly:

- `Configuration`: the existing configuration `QScrollArea` and footer action bar.
- `Logs`: one `LogViewWidget` for the selected service.

The Logs page contains a file-health chip, Pause/Resume toggle, checked-by-default Follow checkbox, `Open log file`, `Copy`, and `Clear` controls. A muted second line shows service state and the current line count. Log output is displayed as untrusted plain text in a read-only, non-wrapping fixed-width editor.

File health and service run state are independent displays. The chip owns file health:

| Chip | Meaning |
| --- | --- |
| `● Live` | An actual read succeeded and consumption is not paused. |
| `⏸ Paused` | Consumption is paused and the file is present; no read error is currently retained. |
| `⚠ Log file not found` | The resolved path is absent. |
| `⚠ Log unreadable: <reason>` | A stat/open/read operation reported an unavailable or unreadable file. |
| `◌ No log path` | No path is resolved. |

The muted service-state line maps `RUNNING` to `service running`, `STOPPED` to `service stopped`, `TRANSITIONING` to `service restarting`, and `UNKNOWN` to `service unknown`. Supervisor status normalization supplies `UNKNOWN` whenever the supervisor is inactive or a managed app is absent from an active supervisor response. A status update cannot erase a file-health warning, and a file-health update cannot change the service-state line.

## 3. Architecture & Components

The implementation has four components: a pure-Python incremental reader in `src/ai_manager/services/log_tailer.py`; a Qt log page in `src/ai_manager/ui/widgets/log_view.py`; integration and path memory in `AppDetailView` plus a deterministic fallback in `supervisor.py`; and per-app status normalization in `MainWindow`. The dark and light themes receive additive selectors for tabs, the log editor, and log-status labels. The reader is independent of Qt, the view consumes the reader's bounded batches, and the detail/window layers supply the resolved path and service state.


### 3.1 `LogTailReader` API

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

`LogTailReader` is pure Python and owns all incremental-file state for one resolved path: byte offset, device/inode identity, size, `mtime_ns`, a trailing partial line, and the last read-observed error. It imports no Qt code. `set_path()` normalizes non-`None` values through `os.fspath`; changing the normalized target resets all file identity, offset, partial-line, and error state and returns `True`. Repeating the same target returns `False` and preserves state.

The implementation performs a metadata check before reading. It opens files only through the module-level `_open_file(path)` helper, which is a test seam for wrapping handles and recording every `read(n)` request. Bytes are consumed incrementally, complete newline-terminated records are emitted without the newline, and decoding uses UTF-8 with `errors="replace"`. Every `LogReadBatch` reports the status observed for that call; `reset` is populated only when the batch status is `OK`.

**Behavioural rules**

| Rule | Required behaviour | Test case |
| --- | --- | --- |
| R1 | With no path configured, `read_new_lines()` returns `LogReadBatch([], UNSET)` and `probe_health()` returns `(UNSET, None)`. | `tests/test_log_tailer.py::LT-01` |
| R2 | A configured absent path returns `MISSING` with a human-readable path/error on every read until the file appears; the reader does not invent `OK`. | `tests/test_log_tailer.py::LT-02` |
| R3 | `probe_health()` is stat-only: it reports `MISSING`, `PRESENT`, or `UNAVAILABLE`, never claims readability, never opens/reads, never advances the offset, and does not mutate reader state. | `tests/test_log_tailer.py::LT-03` |
| R4 | An open/read failure returns `UNREADABLE` with the operating-system reason, retains the offset and partial state, and does not emit a `created` reset when a transient error later clears; recovery resumes from the retained offset with `reset=None`. | `tests/test_log_tailer.py::LT-04` |
| R5 | The first successful read of a target starts at `max(0, size - initial_bytes)`, drops a leading partial line when starting mid-file, and returns `OK` with `reset="created"`; the initial read is bounded. | `tests/test_log_tailer.py::LT-05` |
| R6 | Each call consumes at most `max_batch_bytes`; if complete or partial input remains after the budget, it returns `more_pending=True` and later calls continue in order without loss or duplication. | `tests/test_log_tailer.py::LT-06` |
| R7 | Bytes skipped while dropping a leading partial line or discarding the remainder of an over-long line count against the same per-call byte budget; skipped bytes cannot be read for free. | `tests/test_log_tailer.py::LT-07` |
| R8 | When size and `mtime_ns` are unchanged at the current offset, the call performs no content read and returns an empty `OK` batch. | `tests/test_log_tailer.py::LT-08` |
| R9 | An equal-size rewrite with a newer `mtime_ns` is treated as an in-place truncation: reset to the initial-read window, emit `reset="truncated"`, and never read more than the reset and batch bounds. | `tests/test_log_tailer.py::LT-09` |
| R10 | When `size < offset`, the file is treated as truncated: clear the partial state, seek to `max(0, size - initial_bytes)`, and emit `reset="truncated"` on the successful bounded read. | `tests/test_log_tailer.py::LT-10` |
| R11 | A change to `st_dev` or `st_ino` is treated as rotation: start the bounded initial window for the replacement identity and emit `reset="rotated"`. | `tests/test_log_tailer.py::LT-11` |
| R12 | A file that was missing and then appears is read as a fresh target, with `reset="created"`; subsequent unchanged polls do not repeat the marker. | `tests/test_log_tailer.py::LT-12` |
| R13 | Bytes after the last newline are retained as a partial line and are emitted exactly once only after a later read supplies its terminating newline. | `tests/test_log_tailer.py::LT-13` |
| R14 | Once a line exceeds `max_line_bytes`, emit only its decoded prefix plus the literal ` …[line truncated]` marker (U+2026, byte-matching the approved design), then discard through the next newline; the discarded bytes remain budgeted and no duplicate truncated line is produced. | `tests/test_log_tailer.py::LT-14` |
| R15 | Invalid UTF-8 is decoded with replacement characters per emitted line and never raises an exception. | `tests/test_log_tailer.py::LT-15` |
| R16 | Initial, truncation, rotation, and backlog paths all use the same bounds: `initial_bytes` is the **total** reset window, re-read from the end of the file and drained across successive calls each bounded by `max_batch_bytes` with `more_pending=True` until drained (with the default `65 536 <= 262 144` the window completes in one call); no individual `read(n)` exceeds `max_batch_bytes`. | `tests/test_log_tailer.py::LT-16` |
| R17 | Appends after a successful read emit only newly completed lines in order; an append larger than one budget is drained by repeated calls, with the offset advanced only for bytes actually consumed. This no-duplication guarantee covers appends and detected resets; the single documented exception is R20. | `tests/test_log_tailer.py::LT-17` |
| R18 | A read batch with `status != OK` contains no reset marker; a successful unchanged recovery has `reset=None`, while `created`, `truncated`, and `rotated` are reserved for their corresponding identity/window events. | `tests/test_log_tailer.py::LT-18` |
| R19 | `set_path()` accepts both `str` and `Path`, reports whether the normalized target changed, and on a change resets offset, identity, partial bytes, pending discard state, and error state before the next read. | `tests/test_log_tailer.py::LT-19` |
| R20 | A truncate-and-regrow completed between polls can be indistinguishable from an append when the final size is past the old offset. The reader has no clock and performs no content comparison, so it cannot bound how much of the rewritten content a duplicate suffix may contain; the requirement is only that this case cannot crash, corrupt reader state, or mis-state file health, and that the size-shrink and equal-size-`mtime_ns` cases remain detected as `truncated`. | `tests/test_log_tailer.py::LT-20` |

`more_pending` is the only mechanism for draining a large backlog; there is no whole-file read. The reader has no line-count cap because the view enforces the UI cap with `QPlainTextEdit.setMaximumBlockCount`.



### 3.2 `LogViewWidget` API

```python
class LogViewWidget(QWidget):
    LOG_POLL_INTERVAL_MS = 1000
    MAX_LINES = 5000
    MAX_READS_PER_TICK = 4          # <= 1 MiB consumed per tick

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

`LogViewWidget` is a `QWidget` whose reader is created for one `service_id` and stored as `self._reader` (a `LogTailReader`). Tests substitute `self._reader` to count calls and to exercise batches; the attribute is part of the required internal contract, in the same way existing tests rely on `_split_chk` and `_list_widget`. It contains a read-only `QPlainTextEdit` named `logView`, with line wrapping disabled, `setMaximumBlockCount(MAX_LINES)`, and a fixed-width font obtained from `QFontDatabase.systemFont(QFontDatabase.FixedFont)`. The widget does not parse or interpret log text as HTML.

The toolbar contains the file-health chip, a Pause/Resume toggle, a checked-by-default Follow checkbox, `Open log file`, `Copy`, and `Clear`. The muted line below contains the service-state text and a counter such as `1 204 lines` or `5 000 lines (capped)`. `set_service_state()` updates only the service-state display. `set_paused()` updates only consumption and the chip's pause dimension. `set_follow()` changes only auto-scroll behavior. `clear_view()` removes displayed text without resetting the reader offset, path, identity, or pending input.

**Polling and lifecycle**

`poll_once()` first calls `reader.probe_health()` on every tick, including when paused. The probe updates only the current presence and metadata reason. If the widget is not paused, it then calls `read_new_lines()` at most `MAX_READS_PER_TICK` times, continuing within that same tick while the previous batch has `more_pending=True`. Batch status and error are the authoritative read-observed readability state. A paused widget makes no reader calls that consume bytes, so the offset is unchanged; the timer continues to probe presence. A resumed widget drains the retained backlog under the per-tick limit.

Each emitted line is appended with `appendPlainText()` as plain text. Follow moves the cursor to the end only when checked; an unchecked Follow state never moves the user's viewport. The widget starts its one-second `QTimer` in `showEvent()` and stops it in `hideEvent()`. `is_polling` is true exactly while that timer is active. Because the Logs widget is a page in a `QTabWidget`, only the visible Logs page polls; the default Configuration page performs no log syscalls.

**Chip truth table**

The chip is a pure function of the latest probed `FilePresence`, the pause flag, and the last read-observed status. A stat-only `PRESENT` result never promotes the chip to `Live`, and a probe cannot clear an actual read error.

| Presence | Paused | Last read status | Chip |
| --- | --- | --- | --- |
| `UNSET` | either | any | `◌ No log path` |
| `MISSING` | either | any | `⚠ Log file not found` |
| `UNAVAILABLE` | either | any | `⚠ Log unreadable: <reason>` |
| `PRESENT` | yes | `UNREADABLE` | `⚠ Log unreadable: <reason>`; retain the read error |
| `PRESENT` | yes | anything other than `UNREADABLE` | `⏸ Paused` |
| `PRESENT` | no | `OK` | `● Live` |
| `PRESENT` | no | `UNREADABLE` | `⚠ Log unreadable: <reason>` |

A read-observed `UNREADABLE` clears only after a successful read of the same file identity or after a successful read of a replacement identity. A successful recovery from a transient error uses `reset=None`; it never creates a misleading file-created marker. `MISSING` and `UNAVAILABLE` always win over the retained read status while those presence results are current. The service-state line is updated independently and cannot affect this table.

When the derived chip state changes, exactly one placeholder line is maintained for a non-OK health state. Replacing a placeholder removes the previous placeholder instead of stacking another one. The exact placeholder formats are:

| Health state | Placeholder |
| --- | --- |
| `UNSET` | `No log file resolved yet` |
| `MISSING` | `Log file not found: <path>` |
| `UNAVAILABLE` or read-observed `UNREADABLE` | `Cannot read log file: <reason>` |

A return to an OK-derived chip removes the placeholder. Errors are surfaced once per transition, not once per poll. Presence is rechecked every tick, so a file created while paused is reflected immediately; its content is consumed only after Resume.

**Marker formats**

Reset markers are plain-text lines and are rendered only for a successful `LogReadBatch` carrying the matching reset value:

| Batch/reset or event | Exact marker line |
| --- | --- |
| `reset="rotated"` | `------ log rotated ------` |
| `reset="truncated"` | `------ log truncated ------` |
| `reset="created"` | `------ log file created ------` |
| `set_log_path()` changes the normalized target | `------ log file changed: <path> ------` |

`set_log_path()` preserves existing displayed history, resets the reader to the new target, and causes the path-change marker to be inserted before the new target's output on the next poll. A repeated report of the same path does not add a marker or clear history. `clear_view()` is the only explicit text wipe.

`Open log file` calls `QDesktopServices.openUrl(QUrl.fromLocalFile(path))`. With no resolved path (`UNSET`), the button and `Copy` are disabled and their tooltip states that no log file is resolved yet, so `None` is never passed to `QUrl.fromLocalFile`. If Qt reports failure for a resolved path, the raw path is placed in the chip tooltip so the failure remains actionable in headless or desktop environments. `Copy` copies the current selection, or all text when there is no selection.


### 3.3 `AppDetailView` API

```python
class AppDetailView(QWidget):
    def __init__(self, app_meta: AppMetadata, parent: Optional[QWidget] = None) -> None: ...

    @property
    def log_view(self) -> LogViewWidget: ...

    def update_service_status(self, status: ServiceStatus) -> None: ...
```

`app_id` is `self.app_meta.id` throughout (the constructor signature is unchanged from
today's code; only the widget tree inside it changes).

The existing configuration `QScrollArea` and footer action bar are wrapped together in a page titled `Configuration`. A second page titled `Logs` contains one `LogViewWidget(self.app_meta.id)`. A `QTabWidget` sits below the unchanged header frame and fills the remaining view. `Configuration` is index 0 and selected by default; its Save buttons remain inside that page because they operate on the configuration draft.

`AppDetailView.log_view` returns the Logs page widget for the window layer and tests. The view stores `_known_log_path: Optional[str]`, initially `None`, as path memory independent of the current supervisor payload.

`update_service_status(status)` applies this exact order:

1. If `status.log_path` is non-empty, assign its normalized string value to `_known_log_path`.
2. Resolve `path = _known_log_path` when it exists; otherwise resolve `str(default_log_path(self.app_meta.id))`.
3. Call `log_view.set_log_path(path)`.
4. Call `log_view.set_service_state(status.state)`.
5. Update the existing header `StatusBadge` exactly as before.

A later status with no `log_path` cannot replace an explicit remembered path with the fallback. The fallback is used only before any explicit path has ever been reported. Status refreshes that repeat the same path do not clear log history because `LogViewWidget.set_log_path()` is history-preserving. Switching between `Configuration` and `Logs` never emits `config_changed`, so dirty-state and sidebar asterisk behavior remain unchanged.

### 3.4 Fallback Path

Add this helper to `src/ai_manager/services/supervisor.py`:

```python
def default_log_path(service_id: str) -> Path:
    """Return ~/.cache/ai-backends/logs/<service_id>.log.

    Used only when no log_path has ever been reported for this service.
    """
```

`SERVICE_LINE_RE` already requires `log=<path>`. Leave that regex unchanged. If a service row is absent from the parsed status, `MainWindow` supplies the synthetic `UNKNOWN` status and `AppDetailView` uses this fallback only if `_known_log_path` is still unset.

### 3.5 Main Window

Before updating widgets, `_on_supervisor_status` normalizes one status for every managed application:

- If `status.is_running` is `False`, every managed app receives `ServiceStatus(service_id=app_id, state=ServiceRunState.UNKNOWN)`, regardless of residual rows in `status.services`.
- If `status.is_running` is `True`, a reported service row is forwarded unchanged. A managed app absent from `status.services` receives `ServiceStatus(service_id=app_id, state=ServiceRunState.UNKNOWN)`.

Forward each resulting status to both `sidebar.update_status(status)` and the corresponding detail view's `update_service_status(status)`. Thus a stopped supervisor cannot leave a stale Running badge or misrepresent residual Stopped rows as authoritative, and the log tab's service-state line receives the same normalized state.

### 3.6 Theme

Add the following rules to both `DARK_QSS` and `LIGHT_QSS`; the additions are additive and leave existing selectors intact:

| Selector | Required styling |
| --- | --- |
| `QTabWidget::pane` | Border and background consistent with `QGroupBox`. |
| `QTabBar::tab` | Tab surface, text, padding, and border consistent with the existing toolbar and theme. |
| `QTabBar::tab:hover` | Theme-consistent hover feedback. |
| `QTabBar::tab:selected` | Selected tab uses the existing accent: `#93c5fd` in dark theme and `#2563eb` in light theme. |
| `QPlainTextEdit#logView` | Monospace family, readable contrast, and matching selection colors; dark theme uses `#121217` background and `#d4d4d8` text, light theme uses `#ffffff` background and `#1e293b` text. |
| `QLabel#logStatusChip` | Muted-text treatment suitable for file-health status. |
| `QLabel#logServiceState` | Muted service-state text. |
| `QLabel#logLineCounter` | Muted line-count text. |

No existing theme selectors or assertions are removed.

## 4. Data Flow

The log timer runs every `LOG_POLL_INTERVAL_MS` (1000 ms) only while the Logs tab is visible. Each tick probes presence, then performs up to four bounded reads unless paused. The supervisor's existing status timer remains independent and keeps its configured poll interval.

```text
Visible Logs page -> poll_once -> probe_health (presence only, every tick)
                              -> if not paused: <= 4 read_new_lines calls
                              -> append plain text, update file chip/placeholder,
                                 render reset marker, follow if enabled

Supervisor status -> MainWindow normalization -> sidebar + AppDetailView
                                              -> remembered/fallback path + service state
```

The detail header's `StatusBadge` remains governed by service run state. The Logs chip remains governed by file presence, pause state, and actual read status; neither flow overrides the other's display.

## 5. Error Handling

| Condition | User-visible behavior |
| --- | --- |
| No path resolved | Chip shows `◌ No log path`; exactly one `No log file resolved yet` placeholder is maintained. |
| Resolved file missing | Chip shows `⚠ Log file not found`; exactly one placeholder names the path, and subsequent probes detect creation. |
| Parent/path metadata unavailable | Presence is `UNAVAILABLE`; the chip and one placeholder report the OS reason. |
| Open/read denied or failed | Batch reports `UNREADABLE`; the chip shows the reason and one placeholder. Repeated polls do not spam lines. |
| Read error clears without identity change | The next successful read clears the placeholder/error with `reset=None`; no created marker is rendered and reading resumes at the retained offset. |
| Supervisor inactive | Every managed app's service state is `UNKNOWN`, even if residual service rows exist; the last explicit log path remains remembered and can still be tailed. |
| File changes while paused | Presence is reprobed and can change the chip/placeholder; content reads remain paused and the offset is unchanged. |
| Rotation or truncation | A bounded reset emits the matching plain-text marker and resumes from no more than the initial window. |
| Large file or paused backlog | Each reader call is capped at 262144 bytes, each reset starts within the trailing 65536 bytes, and no tick exceeds four reads. |
| Over-long line | Emit the bounded decoded prefix followed by ` …[line truncated]` (U+2026); skip to newline under the same byte budget. |
| Invalid UTF-8 | Replace undecodable bytes; do not raise. |

All file output remains plain text. The widget caps displayed blocks at 5000, and path/status errors are surfaced once per state transition.

## 6. Test Strategy

**Test environment and fixtures**

Run Qt tests headlessly with the existing `QT_QPA_PLATFORM=offscreen` fixture. Tests create log files under `tmp_path` and never invoke `ai-backends`. Byte-level fixtures control exact newline, partial-line, invalid-UTF-8, truncation, rewrite, and rotation cases. Tests that require chmod mode `000` are skipped when running as root because root can still read those files.

| File | Required test matrix |
| --- | --- |
| `tests/test_log_tailer.py` | Pure unit coverage for R1-R20: unset and missing paths; path change and `str`/`Path` acceptance; initial tail window with first partial line dropped; append-only delivery; unchanged size/mtime no-op; equal-size rewrite with newer mtime; size-below-offset truncation; device/inode rotation; missing-to-created transition; partial trailing line buffering; long-line truncation with the exact ` …[line truncated]` marker and skip-to-newline; invalid UTF-8 replacement; oversized backlog draining without loss/duplication; probe transitions and proof probe does not advance offset; transient unreadable recovery at retained offset; skipped-byte budgeting; and exact I/O bounds (including a case with `initial_bytes > max_batch_bytes` that drains across calls). Instrument `_open_file` and assert every `read(n)` is no larger than `max_batch_bytes`; cover initial reads, reset reads, and drains. Skip chmod-000 readability assertions as root. |
| `tests/test_log_view.py` | `poll_once()` appends output; `maximumBlockCount` enforces `MAX_LINES`; Pause prevents consumption and Resume drains backlog; Follow changes auto-scroll without dropping lines; Clear empties the view without resetting offset or resurrecting old output; rotation/truncation/created/path-change markers have exact formats; health transitions maintain exactly one placeholder; missing-file changes are observed while paused; read-observed unreadability remains through paused `PRESENT` probes until a successful read; path changes preserve history and isolate reader offsets; service-state and file-chip displays evolve independently. Monkeypatch `view._reader.read_new_lines` and assert no tick exceeds `MAX_READS_PER_TICK`. Build a real `QTabWidget` hierarchy and verify polling is off on Configuration, on for the selected Logs page, and off after switching back. Repeat visibility gating under a `QStackedWidget` representing the MainWindow stack. |
| `tests/test_app_views.py` | Each detail view has exactly `Configuration` and `Logs` pages, with Configuration selected by default; the configuration `QScrollArea` and footer remain together; tab switching emits no `config_changed`; split-model checkbox changes preserve draft behavior; explicit `log_path` is remembered and never downgraded to `default_log_path` by a later status with no path. |
| `tests/test_main_window.py` | Status reaches the matching per-app log view; when an active supervisor omits a managed app, synthetic `UNKNOWN` reaches both sidebar and detail view; when `is_running=False`, every managed app receives `UNKNOWN` even if the payload has service rows; reported rows are forwarded unchanged only while active. |
| `tests/test_widgets.py` | Both `DARK_QSS` and `LIGHT_QSS` contain the required tab pane/tab states, `QPlainTextEdit#logView`, and all three log-label selectors. |

The byte instrumentation is the acceptance proof for the read bounds; returned line counts alone are not a substitute. Visibility checks use actual Qt container visibility propagation rather than directly calling `show()`/`hide()` on an unattached widget.

## 7. Compatibility & Risks

**Compatibility**

- No persisted settings or configuration-format changes: no new `settings.json` keys, no config-file changes, and no writes to external logs.
- The log format remains opaque; backend line-format changes do not affect rendering.
- The detail layout gains a tab bar and moves the footer into the Configuration page. Existing screenshot output changes; the preserved compatibility contract is that QSS additions are additive and existing style assertions continue to hold. Historical mockup screenshots are not regenerated.
- Supervisor status polling retains its existing configured interval; only the visible log page uses the new one-second timer.

**Risks and bounds**

- Polling cost is limited by visible-tab timer gating, one metadata probe, and at most 1 MiB read per tick.
- Display memory is limited by 5000 text blocks and a 16 KiB line cap; the worst-case displayed log content is bounded by those limits.
- `QDesktopServices.openUrl()` can fail in headless or unsupported desktop environments; the raw path remains available as the chip tooltip.
- A truncate-and-regrow beyond the old offset between polls may be indistinguishable from append and may duplicate a suffix of the rewritten content; the reader has no clock, so no quantitative bound is claimed (R20). Size shrink and equal-size rewrite with changed `mtime_ns` are detected.
- The change is reversible by removing the two new implementation modules and reverting the listed integration/test changes; no external data migration is required.

**Files created/modified**

- Created: `src/ai_manager/services/log_tailer.py`; `src/ai_manager/ui/widgets/log_view.py`; `tests/test_log_tailer.py`; `tests/test_log_view.py`; `docs/superpowers/specs/2026-10-14-live-service-logs-spec.md`.
- Modified: `src/ai_manager/ui/app_detail_view.py`; `src/ai_manager/services/supervisor.py`; `src/ai_manager/ui/main_window.py`; `src/ai_manager/ui/theme.py`; `tests/test_app_views.py`; `tests/test_main_window.py`; `tests/test_widgets.py`.

## 8. Design Review Resolutions

| Finding | Specification decision and location |
| --- | --- |
| Missing/unreadable/error could not be represented | `LogFileStatus`, `FilePresence`, `LogReadBatch.error`, and `more_pending` are normative in §3.1; the chip and placeholder transitions are normative in §3.2 and §5. |
| UNKNOWN forwarding and path type ambiguity | §3.5 normalizes every managed app and forwards to both widgets; §3.4 leaves the mandatory `log=` parser unchanged; reader/widget path APIs accept `str` or `Path`. |
| Fallback could replace a custom path | §3.3 retains `_known_log_path` and uses `default_log_path()` only before an explicit path has ever been reported. |
| Reset, backlog, and paused reads could be unbounded | §3.1 applies `initial_bytes` and `max_batch_bytes` to every read path; §3.2 applies `MAX_READS_PER_TICK`; §7 records the bounded residual truncate-and-regrow limitation. |
| File health and service state were conflated | §2 and §3.2 make them independent displays with a structural chip truth table and service-state mapping. |
| Path changes could mix histories | §3.2 preserves existing text, resets the reader, and inserts `------ log file changed: <path> ------`; `clear_view()` is explicit. |
| Sidebar could retain stale Running state | §3.5 sends synthetic `UNKNOWN` to both sidebar and detail view for absent active rows. |
| Visibility tests could be vacuous | §6 requires real `QTabWidget` and `QStackedWidget` visibility gating tests. |
| Screenshot compatibility was overstated | §7 acknowledges the tab/footer layout change and limits compatibility claims to additive QSS and existing style assertions. |
| Inactive supervisor rows could look authoritative | §3.5 forces `UNKNOWN` for every managed app when `is_running=False`, even if residual rows are present. |
| Paused view could miss file-health changes | §3.2 and §4 probe on every active timer tick while pause gates only content reads. |
| Transient unreadable recovery could imply creation | §3.1 and §3.2 require retained offset, `reset=None`, and no created marker for same-identity recovery. |
| Tests could not prove byte bounds | §3.1 defines `_open_file(path)` instrumentation and §6 asserts every `read(n)` plus per-tick call count. |
| Stat-only probe could clear a real read error | §3.2 treats read batches as authoritative for readability; a `PRESENT` probe while paused cannot clear retained `UNREADABLE`. |
| Truncated-line marker differed from the design; R20 claimed an unenforceable time bound; reset-window draining was ambiguous; `_reader` seam was undocumented; undefined `Open` behaviour with no path | §3.1 R14/R16/R17/R20 rewritten, §3.2 documents `_reader` and disables `Open`/`Copy` while `UNSET`, §5 and §6 synchronized. |

The specification makes no persisted-state or external configuration change; all decisions above are implementation and test contracts for this read-only UI feature.
