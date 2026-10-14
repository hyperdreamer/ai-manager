# Live Service Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.

**Goal:** Add bounded, read-only per-service log tailing and visible Logs tabs while preserving configuration workflows, service status semantics, and headless testability.

**Architecture:** A pure-Python `LogTailReader` owns incremental file identity, offsets, partial lines, bounded byte reads, and health state. A Qt `LogViewWidget` consumes bounded batches only while its Logs page is visible, while `AppDetailView` remembers explicit supervisor paths and keeps log health independent from service state. `MainWindow`, the supervisor fallback helper, and additive theme selectors complete the integration.

**Tech Stack:** Python 3.10+, PyQt6, pydantic models, pytest, pytest-qt, standard-library filesystem and URL APIs.

## Global Constraints
- Python 3.10+ and PyQt6; no new third-party dependencies (only PyQt6, pydantic, ruamel.yaml, httpx, pytest, pytest-qt).
- Strict TDD: write the failing test first, then the minimal implementation.
- Tests run with exactly: `source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/ -q` (conda env `daily` holds PyQt6 and pytest-qt).
- Qt tests must run headless; tests/conftest.py already sets QT_QPA_PLATFORM=offscreen.
- All paths in tasks are repository-relative. Do not modify tests/conftest.py, pyproject.toml, or any docs file.
- Log content is untrusted: append plain text only, never HTML.

## Task 1: Implement LogTailReader and Its Unit Tests
**Implementer tier:** Advanced
### Files:
- Create: `src/ai_manager/services/log_tailer.py`
- Create: `tests/test_log_tailer.py`

### Interfaces:
- Produce these public types in `src/ai_manager/services/log_tailer.py`:
```python
class LogFileStatus(str, Enum):
    UNSET = "unset"
    OK = "ok"
    MISSING = "missing"
    UNREADABLE = "unreadable"

class FilePresence(str, Enum):
    UNSET = "unset"
    MISSING = "missing"
    PRESENT = "present"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class LogReadBatch:
    lines: List[str]
    status: LogFileStatus = LogFileStatus.OK
    reset: Optional[str] = None
    error: Optional[str] = None
    more_pending: bool = False

def _open_file(path: Path) -> BinaryIO: ...

class LogTailReader:
    def __init__(self, *, initial_bytes: int = 65536,
                 max_batch_bytes: int = 262144,
                 max_line_bytes: int = 16384) -> None: ...
    @property
    def path(self) -> Optional[Path]: ...
    def set_path(self, path: Optional[Union[str, Path]]) -> bool: ...
    def probe_health(self) -> Tuple[FilePresence, Optional[str]]: ...
    def read_new_lines(self) -> LogReadBatch: ...
```
- `set_path()` normalizes non-`None` values through `os.fspath`, stores a `Path`, returns `True` only when the normalized target changes, and on change resets byte offset, device/inode identity, size, `mtime_ns`, partial-line bytes, over-long-line discard state, pending reset state, and retained read error.
- `probe_health()` is stat-only and returns `(UNSET, None)`, `(MISSING, reason)`, `(PRESENT, None)`, or `(UNAVAILABLE, reason)` without opening, reading, advancing offset, or mutating reader state.
- `read_new_lines()` owns one target's offset, `(st_dev, st_ino)` identity, size, `mtime_ns`, partial line, over-long-line discard state, and last read-observed error. It returns newline-stripped UTF-8-with-replacement lines and imports no Qt.
- `_open_file(path)` is the only file-open seam. Open the path in binary mode through this helper; tests replace it with a wrapper whose `read(n)` records every request and delegates to the real handle.

### Checklist:
- [ ] Write the failing pure-unit suite before implementation. Use `tmp_path` files and this recording seam:
```python
class RecordingHandle:
    def __init__(self, raw, reads):
        self._raw, self._reads = raw, reads
    def __enter__(self):
        self._raw.__enter__(); return self
    def __exit__(self, *args):
        return self._raw.__exit__(*args)
    def __getattr__(self, name):
        return getattr(self._raw, name)
    def read(self, size=-1):
        self._reads.append(size); return self._raw.read(size)
```
  Patch `ai_manager.services.log_tailer._open_file` and assert every recorded request is no larger than `max_batch_bytes`.
- [ ] Add LT-01 through LT-04: unset path returns `LogReadBatch([], UNSET)` and `(UNSET, None)` from `probe_health`; an absent path repeatedly returns `MISSING` with a human-readable reason; stat-only probing never opens, reads, advances offset, or mutates state; and an open/read `PermissionError` returns `UNREADABLE` while retaining offset and partial state so same-identity recovery resumes with `reset=None`.
- [ ] Add LT-05 through LT-08: initial reads start at `max(0, size - initial_bytes)`, drop a leading partial line and return `reset="created"`; every call is capped at `max_batch_bytes` and drains `more_pending` in order; skipped leading-partial and over-long-line bytes consume the same budget; and unchanged size plus `mtime_ns` performs no content read and returns an empty `OK` batch.
- [ ] Add LT-09 through LT-12: equal-size rewrite with newer `mtime_ns` is a bounded `truncated` reset; size below offset is a bounded `truncated` reset that clears partial state; changed device/inode is a bounded `rotated` reset; and missing-to-created emits `created` once without repeating it on unchanged polls.
- [ ] Add LT-13 through LT-16: trailing partial lines emit exactly once after a later newline; an over-long line emits the exact prefix plus literal ` …[line truncated]` and discards through the newline under budget; invalid UTF-8 uses replacement characters; and initial/truncation/rotation/backlog paths use a total `initial_bytes` reset window drained across calls, with no `read(n)` above `max_batch_bytes`.
- [ ] Add LT-17 through LT-20: large appends drain without duplication and advance only for consumed bytes; non-`OK` batches never carry reset markers and same-identity recovery has `reset=None`; `set_path(str|Path)` returns accurate changed/repeated booleans and clears all state on change; and truncate-regrow between polls cannot crash, corrupt state, or mis-state health while size-shrink and equal-size-newer-`mtime_ns` remain detected.
- [ ] Use byte fixtures for exact newline, partial, invalid-UTF-8, rewrite, rotation, and over-long-line cases; skip chmod-`000` readability assertions when `os.geteuid() == 0`.
- [ ] Run the red focused suite after writing tests and before implementation:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/test_log_tailer.py -q
```
- [ ] Implement the minimal pure reader: stat before content reads; classify ENOENT/ENOTDIR as `MISSING`, other stat failures as `UNREADABLE` on read or `UNAVAILABLE` on probe; retain offset/partial/discard state on transient read failures; clear a pending `created` marker when recovery is same identity; and only put `created`, `truncated`, or `rotated` on successful `OK` batches.
- [ ] Implement a remaining-byte counter for every call. For reset events seek to `max(0, size - initial_bytes)` and limit the reset window to `initial_bytes`; request `read(min(remaining, max_batch_bytes))`; count bytes skipped while dropping a leading partial or discarding an over-long line; set `more_pending` while reset/backlog input remains; and never read a whole file at once.
- [ ] Implement line buffering and decoding with UTF-8 `errors="replace"`; retain bytes after the last newline; emit the over-long marker once when the first byte beyond `max_line_bytes` is seen; and discard the rest through the next newline under the same budget.
- [ ] Implement transition order: no path; missing/unavailable stat; new/reappeared target (`created`); identity change (`rotated`); size shrink or equal-size newer `mtime_ns` (`truncated`); unchanged metadata no-op; normal append/backlog. Reset transitions update identity/metadata and clear partial/discard state.
- [ ] Re-run the exact focused command and confirm LT-01 through LT-20 pass, including read instrumentation and root-only skips.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/services/log_tailer.py` and `tests/test_log_tailer.py`.
- [ ] Commit with message `feat(logs): add bounded incremental log tail reader`.


## Task 2: Add supervisor.default_log_path and Its Test
**Implementer tier:** Fast
### Files:
- Modify: `src/ai_manager/services/supervisor.py:156-156` (append the helper at end of file; leave `SERVICE_LINE_RE` and all existing supervisor behavior unchanged)
- Modify: `tests/test_supervisor.py:1-69` (append the helper test)

### Interfaces:
- Produce this module-level function in `src/ai_manager/services/supervisor.py`:
```python
def default_log_path(service_id: str) -> Path:
    """Return ~/.cache/ai-backends/logs/<service_id>.log.

    Used only when no log_path has ever been reported for this service.
    """
```
- The function must return `Path.home() / ".cache" / "ai-backends" / "logs" / f"{service_id}.log"` and must not create directories, access the filesystem, spawn `ai-backends`, or normalize/alter the supplied service ID.
- Consume the existing `Path` import from `pathlib`; no new dependency or parser change is permitted.

### Checklist:
- [ ] Write the failing test first in `tests/test_supervisor.py`:
```python
def test_default_log_path_uses_cache_logs_directory(monkeypatch, tmp_path):
    from ai_manager.services.supervisor import default_log_path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert default_log_path("textkit") == (
        tmp_path / ".cache" / "ai-backends" / "logs" / "textkit.log"
    )
```
  Add `from pathlib import Path` to the test imports if needed.
- [ ] Run the focused red test and confirm it fails because `default_log_path` is not yet defined:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/test_supervisor.py -q
```
- [ ] Append `default_log_path()` after the existing `SupervisorManager` implementation, using exactly `Path.home() / ".cache" / "ai-backends" / "logs" / f"{service_id}.log"`.
- [ ] Add an assertion that the helper does not create the returned parent directory (`assert not result.parent.exists()`), and retain the existing parser and `stop_supervisor` tests unchanged.
- [ ] Re-run the exact focused command and confirm all tests in `tests/test_supervisor.py` pass.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/services/supervisor.py` and `tests/test_supervisor.py`.
- [ ] Commit with message `feat(supervisor): add deterministic default log path`.


## Task 3: Add Log Theme QSS and Tests
**Implementer tier:** Fast
### Files:
- Modify: `src/ai_manager/ui/theme.py:3-290` (append the required selectors inside `DARK_QSS` without removing existing rules)
- Modify: `src/ai_manager/ui/theme.py:292-580` (append the required selectors inside `LIGHT_QSS` without removing existing rules)
- Modify: `tests/test_widgets.py:1-43` (extend the stylesheet test with required log selectors)

### Interfaces:
- Preserve the existing `DARK_QSS`, `LIGHT_QSS`, and `get_stylesheet(theme: ThemeMode) -> str` interfaces.
- Add these selectors to both stylesheet strings:
```css
QTabWidget::pane { ... }
QTabBar::tab { ... }
QTabBar::tab:hover { ... }
QTabBar::tab:selected { ... }
QPlainTextEdit#logView { ... }
QLabel#logStatusChip { ... }
QLabel#logServiceState { ... }
QLabel#logLineCounter { ... }
```
- Dark `QPlainTextEdit#logView` must use `background-color: #121217`, `color: #d4d4d8`, a fixed-width/monospace family, and explicit selection colors. Light must use `background-color: #ffffff`, `color: #1e293b`, a fixed-width/monospace family, and explicit selection colors.
- `QTabBar::tab:selected` must use `#93c5fd` in `DARK_QSS` and `#2563eb` in `LIGHT_QSS`; pane border/background must match each theme's existing `QGroupBox`, tab surface/text/padding/border must match the toolbar, and hover must provide theme-consistent feedback. The three labels must have muted text treatment.

### Checklist:
- [ ] Write the failing stylesheet assertions first:
```python
def test_log_theme_selectors_are_present():
    required = [
        "QTabWidget::pane", "QTabBar::tab", "QTabBar::tab:hover",
        "QTabBar::tab:selected", "QPlainTextEdit#logView",
        "QLabel#logStatusChip", "QLabel#logServiceState", "QLabel#logLineCounter",
    ]
    dark_css = get_stylesheet(ThemeMode.DARK)
    light_css = get_stylesheet(ThemeMode.LIGHT)
    for selector in required:
        assert selector in dark_css
        assert selector in light_css
    assert "background-color: #121217" in dark_css
    assert "color: #d4d4d8" in dark_css
    assert "background-color: #ffffff" in light_css
    assert "color: #1e293b" in light_css
    assert "#93c5fd" in dark_css
    assert "#2563eb" in light_css
```
  Keep the existing dark/light background assertions and widget tests unchanged.
- [ ] Run the exact focused command before implementation and confirm the new selector test fails:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/test_widgets.py -q
```
- [ ] Add only additive QSS rules. Use theme-matching values equivalent to: dark pane `background-color: #20202a; border: 1px solid #2e2e3d`, dark tabs `#262633`/`#e2e8f0` with `#363647` border and `#323244` hover; light pane `#f8fafc`/`#e2e8f0`, light tabs `#ffffff`/`#334155` with `#cbd5e1` border and `#f1f5f9` hover. Include padding and selected-tab accent explicitly.
- [ ] Add fixed-width families such as `"DejaVu Sans Mono", "Liberation Mono", monospace` to each log editor rule, set readable selection background/foreground, and use muted colors consistent with the existing `#94a3b8` dark and `#64748b` light labels.
- [ ] Re-run the exact focused command and confirm all stylesheet and existing widget tests pass; verify no existing selector or assertion was removed.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/ui/theme.py` and `tests/test_widgets.py`.
- [ ] Commit with message `feat(ui): style service log tabs for dark and light themes`.


## Task 4: Normalize Per-App Supervisor Status in MainWindow
**Implementer tier:** Standard
### Files:
- Modify: `src/ai_manager/ui/main_window.py:264-280` (replace only the per-app forwarding loop inside `_on_supervisor_status`)
- Modify: `tests/test_main_window.py:1-37` (add normalization tests and test helpers)

### Interfaces:
- Consume the existing models exactly:
```python
class SupervisorStatus(BaseModel):
    is_running: bool = False
    supervisor_pid: Optional[int] = None
    services: Dict[str, ServiceStatus] = Field(default_factory=dict)

class ServiceStatus(BaseModel):
    service_id: str
    state: ServiceRunState = ServiceRunState.UNKNOWN
    pid: Optional[int] = None
    log_path: Optional[str] = None
```
- Preserve `MainWindow._on_supervisor_status(status: SupervisorStatus) -> None` and its existing global supervisor label/action updates.
- For each `app_id` in `self.apps`, derive exactly one `normalized_status`: when `status.is_running` is `True`, use `status.services[app_id]` unchanged if present, otherwise `ServiceStatus(service_id=app_id, state=ServiceRunState.UNKNOWN)`; when `status.is_running` is `False`, always use `ServiceStatus(service_id=app_id, state=ServiceRunState.UNKNOWN)` even if a residual row exists.
- Forward every derived status to the existing sidebar interface `self.sidebar.update_status(app_id, normalized_status)` and to `self.views[app_id].update_service_status(normalized_status)` when the view exists. Do not mutate `status.services`, rewrite a reported active row, or skip managed apps.

### Checklist:
- [ ] Write failing tests before changing `MainWindow`. Add a fixture helper that creates the three existing managed-app directories/config files using the current fixture files, constructs `MainWindow(workspace_root=tmp_path)`, registers it with `qtbot`, replaces `window.sidebar.update_status` and each view's `update_service_status` with `MagicMock`, and returns the window.
- [ ] Add this active-supervisor test:
```python
def test_status_normalization_forwards_reported_and_missing_apps(qtbot, tmp_path):
    window = make_test_window(qtbot, tmp_path)
    reported = ServiceStatus(
        service_id="ai-grammar", state=ServiceRunState.RUNNING,
        pid=123, log_path="/tmp/grammar.log",
    )
    window._on_supervisor_status(
        SupervisorStatus(is_running=True, supervisor_pid=9,
                         services={"ai-grammar": reported})
    )
    assert window.sidebar.update_status.call_count == len(window.apps)
    for app_id in window.apps:
        forwarded = window.sidebar.update_status.call_args_list[
            list(window.apps).index(app_id)
        ].args[1]
        assert forwarded.service_id == app_id
        if app_id == "ai-grammar":
            assert forwarded is reported
        else:
            assert forwarded.state == ServiceRunState.UNKNOWN
            assert forwarded.log_path is None
            assert window.views[app_id].update_service_status.call_args.args[0] is forwarded
```
- [ ] Add this inactive-supervisor test to prove residual rows cannot remain authoritative:
```python
def test_inactive_supervisor_sends_unknown_to_every_managed_app(qtbot, tmp_path):
    window = make_test_window(qtbot, tmp_path)
    residual = ServiceStatus(
        service_id="ai-grammar", state=ServiceRunState.STOPPED,
        pid=None, log_path="/tmp/grammar.log",
    )
    window._on_supervisor_status(
        SupervisorStatus(is_running=False, services={"ai-grammar": residual})
    )
    for app_id in window.apps:
        forwarded = next(
            call.args[1] for call in window.sidebar.update_status.call_args_list
            if call.args[0] == app_id
        )
        assert forwarded == ServiceStatus(
            service_id=app_id, state=ServiceRunState.UNKNOWN
        )
        assert window.views[app_id].update_service_status.call_args.args[0] == forwarded
```
- [ ] Run the exact focused command before implementation and confirm the normalization assertions fail against the current loop, which only visits reported rows:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/test_main_window.py -q
```
- [ ] Replace only the loop with `for app_id in self.apps:` and the active/inactive derivation above, then forward the same object to sidebar and detail view. Keep existing supervisor label text, style, and action-button behavior intact.
- [ ] Re-run the exact focused command and confirm the existing navigation/draft test plus both normalization tests pass; assert every managed app receives one sidebar and one detail update.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/ui/main_window.py` and `tests/test_main_window.py`.
- [ ] Commit with message `fix(ui): normalize per-app supervisor status updates`.


## Task 5: Implement LogViewWidget and Its Qt Tests
**Implementer tier:** Standard
### Files:
- Create: `src/ai_manager/ui/widgets/log_view.py`
- Create: `tests/test_log_view.py`

### Interfaces:
- Consume Task 1's reader API exactly:
```python
LogTailReader(initial_bytes=65536, max_batch_bytes=262144, max_line_bytes=16384)
set_path(str | Path | None) -> bool
probe_health() -> tuple[FilePresence, str | None]
read_new_lines() -> LogReadBatch
```
  where `LogFileStatus` has `UNSET`, `OK`, `MISSING`, and `UNREADABLE`; `FilePresence` has `UNSET`, `MISSING`, `PRESENT`, and `UNAVAILABLE`; and `LogReadBatch(lines, status, reset, error, more_pending)` contains newline-stripped strings, an optional `created`/`truncated`/`rotated` reset, an optional reason, and a `more_pending` boolean.
- Produce this Qt API in `src/ai_manager/ui/widgets/log_view.py`:
```python
class LogViewWidget(QWidget):
    LOG_POLL_INTERVAL_MS = 1000
    MAX_LINES = 5000
    MAX_READS_PER_TICK = 4

    def __init__(self, service_id: str, parent: Optional[QWidget] = None) -> None: ...
    def set_log_path(self, path: Optional[Union[str, Path]]) -> None: ...
    def set_service_state(self, state: ServiceRunState) -> None: ...
    def set_paused(self, paused: bool) -> None: ...
    def set_follow(self, follow: bool) -> None: ...
    def clear_view(self) -> None: ...
    def poll_once(self) -> None: ...
    @property
    def is_polling(self) -> bool: ...
```
- Construct `self._reader` as a `LogTailReader(initial_bytes=65536, max_batch_bytes=262144, max_line_bytes=16384)` and keep it replaceable by tests. `self._reader` is a required internal seam; `set_log_path()` calls its `set_path()` and `poll_once()` calls its `probe_health()` and `read_new_lines()`.
- Expose a read-only, non-wrapping `QPlainTextEdit` as `self.logView` with object name `logView`, `setMaximumBlockCount(MAX_LINES)`, and a fixed-width font from `QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)`. All log output must use `appendPlainText()` or equivalent plain-text insertion; never call `setHtml()` or interpret log text as markup.
- Maintain named labels `self._health_chip` (`objectName="logStatusChip"`), `self._service_state_label` (`objectName="logServiceState"`), and `self._line_counter` (`objectName="logLineCounter"`), plus toolbar controls for Pause/Resume, checked-by-default Follow, Open log file, Copy, and Clear. The `QTimer` is stored as `self._poll_timer`.
- `set_service_state()` changes only the muted service-state line: `RUNNING -> "service running"`, `STOPPED -> "service stopped"`, `TRANSITIONING -> "service restarting"`, `UNKNOWN -> "service unknown"`. `set_paused()` changes only the consume/pause flag, button text, and derived chip; it never consumes bytes. `set_follow()` changes only auto-scroll. `clear_view()` clears displayed text and placeholder bookkeeping but never calls `set_path()` or resets reader offset, identity, partial bytes, pending discard, or error state.

### Checklist:
- [ ] Write `tests/test_log_view.py` before implementation with a replaceable reader seam:
```python
class StubReader:
    def __init__(self):
        self.path = None
        self.presence = (FilePresence.UNSET, None)
        self.batches = deque()
        self.set_path_calls = []
        self.probe_calls = 0
        self.read_calls = 0
    def set_path(self, path):
        normalized = None if path is None else Path(os.fspath(path))
        changed = normalized != self.path
        self.path = normalized
        self.set_path_calls.append(normalized)
        return changed
    def probe_health(self):
        self.probe_calls += 1
        return self.presence
    def read_new_lines(self):
        self.read_calls += 1
        return self.batches.popleft() if self.batches else LogReadBatch([])
```
  Assign `view._reader = stub` after constructing the widget, and use `qtbot.addWidget(view)` for every test.
- [ ] Add `test_poll_once_appends_plain_text_and_updates_counter`: queue `LogReadBatch(["<b>untrusted</b>", "& raw"])`, call `poll_once()`, and assert `view.logView.toPlainText()` contains the literal strings, never rendered HTML, and the line counter reports `2 lines`.
- [ ] Add `test_maximum_block_count_caps_display`: queue more than `LogViewWidget.MAX_LINES` complete lines, poll once, assert `logView.maximumBlockCount() == MAX_LINES`, `document().blockCount() <= MAX_LINES`, and the counter ends with `"lines (capped)"` at the cap.
- [ ] Add `test_pause_prevents_consumption_and_resume_drains`: set a present path, set paused, poll repeatedly, assert `probe_calls` increases while `read_calls == 0`; unset pause, queue a batch, poll, and assert the batch is consumed and rendered.
- [ ] Add `test_follow_controls_only_viewport`: append enough lines to make a scrollbar, disable Follow and record the scrollbar/cursor position, append more lines and assert the prior viewport is not forced to the end; enable Follow, append again, and assert the cursor/viewport reaches the document end without dropping lines.
- [ ] Add `test_clear_view_does_not_reset_reader`: poll a first batch, record the stub's read count and path, call `clear_view()`, assert the editor is empty and the reader path/read count are unchanged, then poll with no new batch and assert old output does not reappear; queue a genuinely new batch and assert only that new output renders.
- [ ] Add `test_reset_markers_are_exact_and_precede_lines`: parameterize `created`, `truncated`, and `rotated` with their exact marker lines `------ log file created ------`, `------ log truncated ------`, and `------ log rotated ------`; assert each marker precedes its batch lines. Change from `a.log` to `b.log`, poll, and assert `------ log file changed: <path> ------` precedes the new target output while the old displayed history remains.
- [ ] Add `test_health_placeholders_are_single_and_transition_only`: drive `MISSING`, repeated `MISSING`, `UNAVAILABLE`, repeated unreadable batches, and recovery; assert exact placeholders `No log file resolved yet`, `Log file not found: <path>`, and `Cannot read log file: <reason>`, each appears at most once, repeated polls do not append duplicates, and an OK-derived state removes the placeholder.
- [ ] Add `test_missing_file_is_observed_while_paused`: set a resolved path and pause, return `MISSING` from `probe_health()` across a poll, then return `PRESENT` without queueing content; assert the chip changes immediately, `read_calls` stays zero, and no content appears until resume.
- [ ] Add `test_read_error_survives_paused_present_probe`: return a present probe plus an `UNREADABLE` batch with `error="permission denied"`, pause, return a present probe, and assert the chip remains `⚠ Log unreadable: permission denied` and placeholder remains; resume with a successful empty batch and assert the warning/placeholder clears with no created marker.
- [ ] Add `test_path_changes_preserve_history_and_isolate_offsets`: render path A, change to path B, assert history remains and exactly one path-change marker appears on the next poll; repeat the same B path and assert no second marker; verify stub `set_path()` was called once for each normalized change and queued B batches cannot emit A output.
- [ ] Add `test_service_state_and_file_health_are_independent`: set each `ServiceRunState` and assert exact service text; separately drive missing, paused-present, live, and unreadable health states and assert service text does not change and state updates do not clear the chip warning.
- [ ] Add `test_open_copy_and_clear_controls`: with no path, assert Open and Copy are disabled and their tooltip says no log file is resolved; with a path, monkeypatch `QDesktopServices.openUrl` and `QUrl.fromLocalFile`, click Open and assert the raw path is passed; click Copy with and without a selection and assert the clipboard receives selected/all plain text; click Clear and assert only the editor text is wiped.
- [ ] Add `test_poll_once_never_exceeds_read_budget`: queue batches with `more_pending=True`, call one `poll_once()`, assert `read_calls <= MAX_READS_PER_TICK`, and assert the next tick continues rather than dropping pending data. Also assert `probe_calls` increments on every tick.
- [ ] Add `test_visibility_gates_timer_in_real_qt_containers`: create a real `QTabWidget` with a Configuration page and a Logs page containing the widget, show the tab host, assert polling is off on Configuration, select Logs and assert `is_polling` becomes true, switch back and assert it becomes false. Repeat with a `QStackedWidget` containing two real pages representing the MainWindow stack; do not call `show()`/`hide()` directly on an unattached log widget.
- [ ] Run the exact focused red suite before implementation:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/test_log_view.py -q
```
- [ ] Implement the widget layout and lifecycle. Create the toolbar and status line, construct the editor and timer, set Follow checked by default, connect controls, start the timer in `showEvent()` and stop it in `hideEvent()`, and make `is_polling` return `self._poll_timer.isActive()` exactly.
- [ ] Implement `poll_once()` in this order: call `probe_health()` on every tick; store only current presence/reason; if not paused, call `read_new_lines()` at most `MAX_READS_PER_TICK` times and continue only while `more_pending`; treat each batch's status/error as authoritative read health; render a pending path marker, reset marker, and plain lines in order; then update the chip, placeholder, and line counter. A paused tick must never call `read_new_lines()`.
- [ ] Implement the health truth table without conflation: `UNSET -> ◌ No log path`, `MISSING -> ⚠ Log file not found`, `UNAVAILABLE -> ⚠ Log unreadable: <reason>`; present+paused+retained unreadable stays `⚠ Log unreadable: <reason>`, present+paused otherwise is `⏸ Paused`, present+active+successful read is `● Live`, and present+active+retained unreadable is the warning. A stat-only `PRESENT` probe must not promote to Live or clear a retained read error; missing/unavailable presence wins while current.
- [ ] Implement health transition bookkeeping so exactly one placeholder is maintained for a non-OK state, replacing/removing the prior placeholder instead of stacking it; surface errors only when the derived health key changes; remove the placeholder on an OK-derived state. Use the exact placeholder text from the tests and keep path/reason text plain.
- [ ] Implement marker and path behavior: `set_log_path()` preserves editor history, calls reader `set_path()`, queues one `------ log file changed: <normalized path> ------` marker for the next poll only when the normalized target changes, and disables Open/Copy only for `None`; render reset markers only for successful batches carrying the matching reset, with path-change marker before new-target output. Repeated reports of the same path must not clear history or add markers.
- [ ] Implement control behavior: Open calls `QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))` only for a resolved path and puts the raw path in the chip tooltip if Qt returns `False`; Copy copies the selected text or all `toPlainText()` when no selection; Clear removes displayed text without changing reader state; Follow moves the cursor to end only when enabled; and line count uses the capped editor block count, showing `N lines` or `5000 lines (capped)`.
- [ ] Re-run the exact focused command and confirm all focused Qt tests pass, including actual QTabWidget/QStackedWidget visibility transitions and the `MAX_READS_PER_TICK` assertion.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/ui/widgets/log_view.py` and `tests/test_log_view.py`.
- [ ] Commit with message `feat(ui): add bounded live service log view`.


## Task 6: Add Configuration and Logs Tabs to AppDetailView
**Implementer tier:** Standard
### Files:
- Modify: `src/ai_manager/ui/app_detail_view.py:1-342` (imports, constructor state, `_init_ui` page layout, `update_service_status`, and the `log_view` property; preserve all configuration field/draft methods)
- Modify: `tests/test_app_views.py:1-63` (extend detail-view coverage with tabs, path memory, and status tests)

### Interfaces:
- Consume Task 2's exact helper:
```python
def default_log_path(service_id: str) -> Path:
    """Return ~/.cache/ai-backends/logs/<service_id>.log.

    Used only when no log_path has ever been reported for this service.
    """
```
- Consume Task 5's exact widget API:
```python
class LogViewWidget(QWidget):
    LOG_POLL_INTERVAL_MS = 1000
    MAX_LINES = 5000
    MAX_READS_PER_TICK = 4
    def __init__(self, service_id: str, parent: Optional[QWidget] = None) -> None: ...
    def set_log_path(self, path: Optional[Union[str, Path]]) -> None: ...
    def set_service_state(self, state: ServiceRunState) -> None: ...
    def set_paused(self, paused: bool) -> None: ...
    def set_follow(self, follow: bool) -> None: ...
    def clear_view(self) -> None: ...
    def poll_once(self) -> None: ...
    @property
    def is_polling(self) -> bool: ...
```
- Produce and preserve this `AppDetailView` API:
```python
class AppDetailView(QWidget):
    def __init__(self, app_meta: AppMetadata, parent: Optional[QWidget] = None) -> None: ...
    @property
    def log_view(self) -> LogViewWidget: ...
    def update_service_status(self, status: ServiceStatus) -> None: ...
```
- Add `self._known_log_path: Optional[str]`, initialized to `None`, independent of the current supervisor payload. `app_id` is always `self.app_meta.id`.
- `update_service_status(status)` must execute this exact order and semantics:
  1. If `status.log_path` is non-empty, assign its normalized string value to `_known_log_path`; an empty string or `None` never overwrites a remembered explicit path.
  2. Resolve `path = _known_log_path` when it is not `None`; otherwise resolve `str(default_log_path(self.app_meta.id))`.
  3. Call `log_view.set_log_path(path)`.
  4. Call `log_view.set_service_state(status.state)`.
  5. Call the existing `_status_badge.set_status(status.state, status.pid)` exactly as before.
  A later status with no path therefore cannot downgrade an explicit path to the fallback; the fallback is used only before any explicit path has ever been reported.
- The widget tree must keep the unchanged header (title, port, description, status badge, and `Restart Service Only`) above one `QTabWidget` filling the remaining view. Tabs must be exactly `Configuration` at index 0 and `Logs` at index 1, with Configuration selected by default. The Configuration page contains the existing `QScrollArea` and footer action bar together; the Logs page contains exactly one `LogViewWidget(self.app_meta.id)`. Tab switching must not emit `config_changed`.

### Checklist:
- [ ] Write the failing tests before modifying `AppDetailView`. Add imports for `QFrame`, `QScrollArea`, `QTabWidget`, `SupervisorStatus` only as needed and use the existing `get_managed_apps(Path("/tmp"))` fixture pattern.
- [ ] Add this exact tab-structure test:
```python
def test_app_detail_has_configuration_and_logs_tabs(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(detail)
    tabs = detail.findChild(QTabWidget)
    assert tabs is not None
    assert tabs.count() == 2
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Configuration", "Logs"
    ]
    assert tabs.currentIndex() == 0
    config_page = tabs.widget(0)
    assert config_page.findChild(QScrollArea) is not None
    assert config_page.findChild(QFrame, "footerActionBar") is not None
    assert detail.log_view is tabs.widget(1)
    assert detail.log_view.service_id == "textkit"
```
  Require `LogViewWidget` to retain `service_id` as a public read-only attribute or equivalent testable value.
- [ ] Add this tab-signal and draft regression test:
```python
def test_tab_switching_does_not_emit_config_changed_and_split_draft_survives(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(detail)
    changed = []
    detail.config_changed.connect(lambda *args: changed.append(args))
    tabs = detail.findChild(QTabWidget)
    tabs.setCurrentIndex(1)
    tabs.setCurrentIndex(0)
    assert changed == []
    detail._split_chk.setChecked(True)
    detail._ocr_combo.setEditText("qwen-ocr")
    detail._text_combo.setEditText("deepseek-text")
    draft = detail.get_current_draft()
    assert draft.is_split_model is True
    assert draft.ocr_model == "qwen-ocr"
    assert draft.text_model == "deepseek-text"
```
- [ ] Add this fallback and explicit-path memory test:
```python
def test_explicit_log_path_is_remembered_over_fallback(monkeypatch, qtbot, tmp_path):
    apps = get_managed_apps(tmp_path)
    detail = AppDetailView(apps["textkit"])
    qtbot.addWidget(detail)
    fallback = tmp_path / "fallback.log"
    explicit = tmp_path / "reported.log"
    monkeypatch.setattr(
        "ai_manager.ui.app_detail_view.default_log_path",
        lambda service_id: fallback,
    )
    detail.update_service_status(
        ServiceStatus(service_id="textkit", state=ServiceRunState.UNKNOWN)
    )
    assert detail._known_log_path is None
    assert detail.log_view._reader.path == fallback
    detail.update_service_status(
        ServiceStatus(
            service_id="textkit", state=ServiceRunState.RUNNING,
            pid=42, log_path=str(explicit),
        )
    )
    assert detail._known_log_path == str(explicit)
    assert detail.log_view._reader.path == explicit
    detail.update_service_status(
        ServiceStatus(service_id="textkit", state=ServiceRunState.STOPPED)
    )
    assert detail._known_log_path == str(explicit)
    assert detail.log_view._reader.path == explicit
```
- [ ] Add this status-order/independence test:
```python
def test_update_service_status_updates_log_state_and_header_without_config_signal(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["ai-grammar"])
    qtbot.addWidget(detail)
    detail.update_service_status(
        ServiceStatus(service_id="ai-grammar", state=ServiceRunState.TRANSITIONING, pid=7)
    )
    assert detail.log_view._service_state_label.text() == "service restarting"
    assert "Restarting" in detail._status_badge._text_label.text()
    assert detail._known_log_path is None
```
- [ ] Run the exact focused red suite before implementation and confirm the new tests fail because no tabs, `log_view`, or path memory exists:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/test_app_views.py -q
```
- [ ] Import `Path`, `QTabWidget`, `default_log_path`, and `LogViewWidget`; initialize `_known_log_path = None`; leave existing signal declarations, config state, load/get-draft logic, fetch logic, and save/restart controls intact.
- [ ] Refactor only the UI containment in `_init_ui`: after the unchanged header, create a `QTabWidget`; create a Configuration page whose layout contains the current `scroll` widget and current `footer` frame in that order; create a Logs page containing `LogViewWidget(self.app_meta.id, logs_page)`; add the two tabs in the required order; select index 0; and add the tab widget to `main_layout` with stretch 1. Do not leave the scroll/footer as siblings outside the Configuration page.
- [ ] Implement `log_view` as a property returning the single Logs-page `LogViewWidget`, and ensure the widget exposes `service_id == self.app_meta.id` for tests and future window integration.
- [ ] Replace `update_service_status` with the exact five-step order in the Interfaces block. Normalize a non-empty `status.log_path` with `str()`, preserve `_known_log_path` across missing-path updates, use the fallback only while `_known_log_path is None`, then update the log path, service-state line, and existing header badge. Do not emit `config_changed` from status or tab changes.
- [ ] Re-run the exact focused command and confirm existing sidebar/detail tests plus the new tab, draft, fallback-memory, and status-independence tests pass.
- [ ] Run the complete required suite after the focused tests pass:
```bash
source /home/bin/yesconda && AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src python -m pytest tests/ -q
```
- [ ] Inspect the full-suite result for regressions in existing mnemonic, navigation, settings, tray, supervisor, and widget tests; do not modify `tests/conftest.py`, `pyproject.toml`, or any documentation file to make tests pass.

### Commit Instructions:
- [ ] Stage only `src/ai_manager/ui/app_detail_view.py` and `tests/test_app_views.py`.
- [ ] Commit with message `feat(ui): add configuration and live logs tabs to app details`.

