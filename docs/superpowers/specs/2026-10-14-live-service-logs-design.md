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
   never polls, and the in-view text is capped.

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
│ ● Live   [⏸ Pause]  [☑ Follow]  [Open log file] [Copy] [Clear]      │
│ 2026-10-14 11:56:12 INFO  grammar check ok                   1 204  │
│ 2026-10-14 11:57:02 ERROR upstream timeout                          │
│ 2026-10-14 11:57:03 INFO  retrying once                             │
└────────────────────────────────────────────────────────────────────┘
```

The user selected this option over window-level tabs (duplicate navigation state,
must reconcile with unsaved drafts) and a docked bottom panel (permanently halves
the configuration area).

## 3. Architecture & Components

Four small units, each independently testable. The Qt layer depends on the reader;
the reader depends on nothing but the standard library.

### 3.1 `LogTailReader` — `src/ai_manager/services/log_tailer.py` (new, pure Python)

Incremental, rotation-tolerant reader for one append-only log file.

```python
@dataclass(frozen=True)
class LogReadBatch:
    lines: List[str]              # complete lines, newline-stripped, in order
    reset: Optional[str] = None   # None | "created" | "truncated" | "rotated" | "missing"


class LogTailReader:
    def __init__(self, *, initial_bytes: int = 65_536, max_line_bytes: int = 16_384) -> None: ...

    @property
    def path(self) -> Optional[Path]: ...

    def set_path(self, path: Optional[Union[str, Path]]) -> bool:
        """Point the reader at a log file; True when the target actually changed.
        Changing the target resets offset, device/inode identity and any partial line."""

    def read_new_lines(self) -> LogReadBatch:
        """Return everything appended since the previous call."""
```

Contract:

| Situation | Behaviour |
| --- | --- |
| `path is None` | `LogReadBatch([], None)` |
| First successful read of a target | seek to `max(0, size - initial_bytes)`; when starting mid-file, drop the first partial line; `reset="created"` |
| `size` unchanged since last read | `LogReadBatch([], None)` — the common case, one `stat` only |
| `size < offset` (truncated in place) | offset := 0, re-read from start, `reset="truncated"` |
| `st_ino`/`st_dev` changed (rotated) | offset := 0, re-read from 0, `reset="rotated"` |
| File missing, previously present | `reset="missing"` once, then `([], None)` until it returns |
| File (re)appears | normal initial read, `reset="created"` |
| No trailing `\n` | bytes after the last `\n` are buffered as a partial line; emitted only once a `\n` arrives |
| Bytes > `max_line_bytes` with no `\n` | emit the decoded prefix plus `" …[line truncated]"`, then discard bytes until the next `\n` |
| Undecodable bytes | decoded per line with `errors="replace"`; never raises |

The reader holds no Qt imports and no line cap; bounding is the view's job
(`QPlainTextEdit.setMaximumBlockCount`). Line cap in the reader would double-count
and make `reset` semantics ambiguous.

### 3.2 `LogViewWidget` — `src/ai_manager/ui/widgets/log_view.py` (new)

```python
class LogViewWidget(QWidget):
    LOG_POLL_INTERVAL_MS = 1000
    MAX_LINES = 5000

    def __init__(self, service_id: str, parent: Optional[QWidget] = None) -> None: ...

    def set_log_path(self, path: Optional[str]) -> None        # forwards to reader; NO reset of view
    def set_service_state(self, state: ServiceRunState) -> None  # status chip only
    def set_paused(self, paused: bool) -> None
    def set_follow(self, follow: bool) -> None
    def clear_view(self) -> None        # clears text only; read offset untouched
    def poll_once(self) -> None         # public seam used by tests and the QTimer
    @property
    def is_polling(self) -> bool        # True while the QTimer is active
```

Contents and behaviour:

- `QPlainTextEdit` (object name `logView`), read-only, no wrap,
  `setMaximumBlockCount(MAX_LINES)`, fixed-width font from
  `QFontDatabase.systemFont(FixedFont)` so tests are font-independent.
- Toolbar row: status chip (`● Live`, `○ Stopped`, `◌ Unknown`, `⚠ Log file not found`),
  `⏸ Pause` / `▶ Resume` toggle, `☑ Follow` checkbox (checked), `Open log file`,
  `Copy`, `Clear`, and a right-aligned counter (`"1 204 lines"`, `"5 000 lines (capped)"`).
- `poll_once()` appends the batch from `LogTailReader`; `reset` values render one
  plain-text marker line (`------ log rotated ------`, `------ log truncated ------`,
  `------ log file missing ------`, `------ log file created ------`). Content is
  always appended as **plain text** — log output is untrusted and never parsed as HTML.
- Follow semantics: auto-scroll happens only when Follow is checked; unchecking
  Follow lets the user scroll freely without being yanked to the bottom.
- Pause semantics: Pause stops consuming bytes (the timer keeps running and the
  offset is untouched), so resuming shows exactly the output produced while paused.
- Timer lifecycle: started in `showEvent`, stopped in `hideEvent`. Inside a
  `QTabWidget` this means only the visible tab polls; the default tab
  (`Configuration`) never reads a log file at all.
- Missing/unreadable file: the reader reports it; the view shows the placeholder
  text and switches the chip to `⚠ Log file not found` (path is quoted in the
  placeholder). Errors are surfaced once per state change, not per poll.
- `Open log file` uses `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`;
  `Copy` copies the selection, or all text when nothing is selected.

### 3.3 Tab integration — `src/ai_manager/ui/app_detail_view.py` (modified)

- Wrap the existing `QScrollArea` **and** the footer action bar into a
  `Configuration` page; add a `Logs` page holding one `LogViewWidget`.
- New `QTabWidget` sits below the header frame and fills the rest of the view;
  the footer's Save buttons live inside the Configuration page because they act on
  the config draft, not on logs.
- `update_service_status(status)` keeps updating the `StatusBadge` and additionally
  forwards `status.log_path or default_log_path(app_id)` and `status.state` to the
  log view.
- Public addition for the window layer and tests: a `log_view` property exposing
  the page's `LogViewWidget`.
- Tab change is inert with respect to config state: `config_changed` is never
  emitted by tab switching, so dirty/asterisk behaviour in the sidebar is unchanged.

### 3.4 Fallback path — `src/ai_manager/services/supervisor.py` (modified)

```python
def default_log_path(service_id: str) -> Path:
    """~/.cache/ai-backends/logs/<service_id>.log — used only when supervisor status omits log_path."""
```

Used when `log_path` is absent (supervisor stopped, or service not yet reported).

### 3.5 Main window — `src/ai_manager/ui/main_window.py` (modified)

No structural change: `_on_supervisor_status` already calls
`view.update_service_status(s_stat)` for every reported service. One addition —
services absent from the status payload (supervisor stopped) are forwarded as
`ServiceRunState.UNKNOWN`, which the existing `StatusBadge` already renders as
`Unknown`, so a stopped supervisor cannot leave a stale `Running` badge in either
the header or the log chip.

### 3.6 Theme — `src/ai_manager/ui/theme.py` (modified)

Add to both `DARK_QSS` and `LIGHT_QSS`:

- `QTabWidget::pane` (border/background matching `QGroupBox`),
- `QTabBar::tab`, `:hover`, `:selected` (selected tab tinted with the existing
  `#93c5fd` accent on dark / `#2563eb` on light, consistent with the toolbar),
- `QPlainTextEdit#logView` (dark `#121217` on `#d4d4d8`; light `#ffffff` on `#1e293b`,
  monospace family, matching selection colors),
- `QLabel#logStatusChip` and `QLabel#logLineCounter` muted-text styles.

No other widget styles change, so existing screenshots and tests stay valid.

## 4. Data Flow

```text
QTimer (1000 ms, only while Logs tab visible)
        │
        ▼
LogViewWidget.poll_once()
        │
        ▼
LogTailReader.read_new_lines()  ──stat──►  ~/.cache/ai-backends/logs/<id>.log
        │  LogReadBatch(lines, reset)
        ▼
QPlainTextEdit.appendPlainText(line)          (cap 5 000 blocks)
        │
        └─ if follow: move cursor to end

SupervisorManager.refresh_status() ──poll_interval_ms (4 s, unchanged)──►
  MainWindow._on_supervisor_status → AppDetailView.update_service_status
    → StatusBadge (unchanged) + LogViewWidget.set_service_state/set_log_path
```

The two timers are intentionally independent: status polling stays at the user's
`poll_interval_ms`, while log reading is a cheap local `stat` plus an incremental
read at 1 s.

## 5. Error Handling

| Failure | User-visible behaviour |
| --- | --- |
| Log path unknown and fallback file missing | Placeholder `Log file not found: <path>` + chip `⚠ Log file not found`; retried on the next poll, so starting the service recovers automatically |
| Permission denied | Same placeholder with `Permission denied` as the reason; chip warning |
| Supervisor stopped | Chip `◌ Unknown`; last known path is still tailed if the file exists, since post-mortem output matters most |
| Rotation / truncation | Marker line in the view, reader restarts from byte 0, no crash, no duplicated tail |
| Gigantic file | Initial read bounded by `initial_bytes` (64 KiB) |
| Line longer than 16 KiB | Emitted truncated with `…[line truncated]`, remaining bytes skipped to the next newline |
| Non-UTF-8 output | Replaced characters, never an exception |

## 6. Test Strategy

All tests run headless (`QT_QPA_PLATFORM=offscreen`, existing `conftest.py`) and
never invoke `ai-backends`; log files are created under `tmp_path`.

- **`tests/test_log_tailer.py` (new, pure unit).** Missing path → empty batch;
  `set_path` change detection; initial read of only the last `initial_bytes` with
  the first partial line dropped; append → only new lines; unchanged size → empty
  batch; in-place truncation → `reset="truncated"` and full re-read; inode change
  (replace file) → `reset="rotated"`; partial trailing line held until `\n`; over-long
  line truncated once and remainder skipped; invalid UTF-8 replaced without raising;
  missing → reappearing file emits `reset="created"`.
- **`tests/test_log_view.py` (new, Qt offscreen).** `poll_once` renders appended
  lines; `MAX_LINES` cap enforced through `maximumBlockCount`; Pause stops
  consumption and Resume delivers the backlog; Follow toggling changes auto-scroll
  without losing lines; `clear_view` empties the view and the next poll does not
  resurrect old output; marker lines rendered for rotation; missing-file
  placeholder and chip text; `set_log_path` toggles between two files without
  cross-contamination; timer is not active while hidden and is active after
  `show()`.
- **`tests/test_app_views.py` (extended).** Each `AppDetailView` exposes exactly the
  `Configuration` and `Logs` tabs, `Configuration` is the default page, and
  toggling the split-model checkbox on the config page still yields the same draft
  (dirty state unaffected by the new tab).
- **`tests/test_main_window.py` (extended).** A supervisor status routed through
  `_on_supervisor_status` reaches the per-app log view (`log_view` path + chip),
  and a status payload without the app marks it `Unknown` rather than stale-running.
- **`tests/test_widgets.py` (extended).** Theme test asserts tab and `logView` QSS
  exist in both `DARK_QSS` and `LIGHT_QSS`.

## 7. Compatibility & Risks

- **No persisted state changes.** No new settings, no `settings.json` keys, no
  config-file changes; the feature is read-only with respect to every external file.
- **Log format is opaque.** Nothing parses log lines, so format changes in the
  backends cannot break the view.
- **Risk: 1 s polling cost.** Mitigated by `stat`-first reads, `showEvent`/`hideEvent`
  gating, and the 64 KiB initial bound. A hidden tab performs zero syscalls.
- **Risk: unbounded memory.** Bounded by `setMaximumBlockCount(5 000)` at roughly
  ≤ 5 000 × 16 KiB in the pathological case, and by the 16 KiB line cap in practice.
- **Risk: `QDesktopServices` unavailable in headless CI.** The handler is a no-op
  guard: if `openUrl` returns `False`, the view shows a tooltip with the raw path
  instead of failing.
- **Reversibility:** the feature adds one widget, one reader, one tab page and QSS;
  removing the tab requires deleting the two new files and reverting three small
  hunks.
