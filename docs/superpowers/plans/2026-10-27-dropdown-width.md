# Drop-down Width Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap the upstream-protocol and three model dropdowns at 480 Qt logical pixels while leaving the API Base URL and API Key full-width and preserving existing interaction.

**Architecture:** Define one module-level `DROPDOWN_MAX_WIDTH = 480` constant in `app_detail_view.py` and apply it immediately after constructing each of the four specified combos. First commit the approved regression tests with their intentional missing-constant ImportError (RED); only then add the constant and four maximum-width calls (GREEN). No layout, widget implementation, styling, or configuration behavior changes are needed.

**Tech Stack:** Python, PyQt6, pytest, pytest-qt, the existing `meta_for` / `snapshot` fixtures, and the conda environment entered with `source /home/bin/yesconda`.

**Approved inputs:** `docs/superpowers/specs/2026-10-27-dropdown-width-spec.md` (sections 2, 4, and 5 are the implementation, test, and mutation contracts) and `docs/superpowers/specs/2026-10-27-dropdown-width-design.md` (approved option A). Inputs are settled; do not redesign.

### File structure and execution order

- `tests/test_app_views.py`: merge the section 4 imports into the existing import block at lines 5-15 and append the 12 exact section 4 tests after current line 1098. Existing tests and fixture helpers remain unchanged.
- `src/ai_manager/ui/app_detail_view.py`: insert the shared constant at the imports/class boundary at lines 43-46 and the four calls at the construction sites at lines 158-166 and 222-244. It remains the only production file modified.
- Single sequential lane: Task 1 (tests-only RED commit) → Task 2 (production-only GREEN commit). Task 2 depends on the committed Task 1 and its recorded collection failure; never parallelize or combine these tasks.
- All line ranges refer to the integration tree before Task 1. New imports and appended tests shift subsequent test-file line numbers; use the exact code anchors as well as the original ranges.

## Global Constraints

- `DROPDOWN_MAX_WIDTH` is the integer `480`, in Qt logical pixels, and is not calculated from window or column dimensions.
- These are the complete set of call sites: `self._protocol_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)`, `self._model_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)`, `self._ocr_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)`, and `self._text_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)`; each occurs exactly once, immediately after construction and before layout insertion.
- The protocol combo remains conditional on protocol support; the three model combos remain constructed as they are today.
- Do **not** change their size policies, set any minimum or fixed width, change layout stretch or alignment, or add layout wrappers. Do not edit theme QSS or `src/ai_manager/ui/widgets/model_combo.py`.
- Do not apply the cap to `_preset_combo`, `_base_url_edit`, `_key_edit`, or any other widget; do not set popup width. In particular, `API Base URL` and `API Key` must remain able to use the full form-column width.
- Do not alter spacing, labels, model fetching, protocol semantics, or any supervisor/network behavior. Do not modify `tests/test_widgets.py`, `tests/endpoint_helpers.py`, or `tests/conftest.py` for this change.
- No test may read/write the user's real configuration, invoke the real supervisor, or access the network. Use `meta_for(tmp_path, "textkit")`, `snapshot()`, local Qt widgets, and the existing inert supervisor fixtures.
- Add all 12 section 4 tests verbatim, without skips, expected-failure markers, altered geometry assertions, or replacement oracles. Keep `QStyle` subcontrol measurement and `inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)` exactly as approved.
- The only persistent implementation modifications are `tests/test_app_views.py` in Task 1 and `src/ai_manager/ui/app_detail_view.py` in Task 2. Leave the approved design, spec, and this plan unchanged during execution; use temporary copies for mutation probes.
- Strict TDD: Task 1 must commit its tests-only RED state after observing the required missing-constant ImportError. Do not add a stub, constant, width call, or import workaround in Task 1. Task 2 is permitted only after that RED commit and must finish with the focused file and the whole `tests/` directory passing.
- Run test commands from the repository root after `source /home/bin/yesconda`. The operator-required focused command is `PYTHONPATH=src QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_app_views.py -q`.
- The full-suite command is `PYTHONPATH=src QT_QPA_PLATFORM=offscreen AI_WORKSPACE_ROOT=/data/home/guest/Development/ai python3 -m pytest tests/ -q`. `AI_WORKSPACE_ROOT` is required because `tests/test_e2e_integration.py` resolves sibling application directories; do not omit it or repair that test as part of this change.
- The spec's repository-root invocation is retained verbatim below for traceability; the executable RED/GREEN steps use the operator-required conda / `PYTHONPATH=src` / `python3 -m pytest` form above.

```bash
QT_QPA_PLATFORM=offscreen pytest -q tests/test_app_views.py
```

- Never execute reboot, shutdown, poweroff, halt, kexec, any systemctl power or sleep verb, init 0|6, or telinit 0|6; never restart or stop the display manager or graphical.target; never terminate the session or signal the process tree hosting the PM. No host transition is required for this UI-only change.
- Every task's requirements implicitly include this section. Keep the plan checkboxes unticked; the deterministic controller tracks progress.

## Task 1: Append the approved dropdown regression tests and commit RED

**Implementer tier:** Economy

**Files:**

- Modify: `tests/test_app_views.py:5-6` — merge the Qt imports and add `QFontMetrics`.
- Modify: `tests/test_app_views.py:14-15` — retain the existing helper import and import the deliberately absent constant alongside `AppDetailView`.
- Modify: `tests/test_app_views.py:1098-1098` — append the 12 exact tests after the current final assertion.
- Test: `tests/test_app_views.py` — intentional collection-time RED; no production file changes.

**Interfaces:**

- Consumes: existing `AppDetailView(app_meta: AppMetadata, parent: Optional[QWidget] = None)`, `AppDetailView.load_config(self, snapshot: ConfigSnapshot) -> None`, `AppDetailView.set_available_models(self, models: List[str]) -> None`, and `AppDetailView.get_current_draft(self) -> AppAIConfig`.
- Consumes: `AppDetailView._protocol_combo: QComboBox | None` (a `QComboBox` when protocol selection is supported), `AppDetailView._model_combo: ModelComboBox`, `AppDetailView._ocr_combo: ModelComboBox`, and `AppDetailView._text_combo: ModelComboBox`. The tests also use the existing `_protocol_labels`, `_split_chk`, `_provider_group`, `_model_group`, `_base_url_edit`, and `_key_edit` attributes without changing their interfaces.
- Consumes: `meta_for(root: Path, app_id: str = "ai-grammar", *, selectable: bool = True) -> AppMetadata` and `snapshot(config: AppAIConfig | None = None, *, present: bool = True, digest: bytes = b"s" * 32) -> ConfigSnapshot` from `tests.endpoint_helpers`.
- Produces: the 12 exact pytest functions below and their import of `ai_manager.ui.app_detail_view.DROPDOWN_MAX_WIDTH`. That module-level name is deliberately absent in this task; Task 2 must produce `DROPDOWN_MAX_WIDTH: int = 480` and cap `_protocol_combo`, `_model_combo`, `_ocr_combo`, and `_text_combo`. This task produces no production API or width change.

- [ ] **Step 1: Merge the section 4 imports without changing existing test bodies**

Replace the two existing Qt import lines at original lines 5-6 with:

```python
from PyQt6.QtCore import QRect, QSignalBlocker, Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QStyle,
    QStyleOptionComboBox,
    QTabWidget,
    QToolButton,
)
```

Keep the existing helper import exactly once and replace the existing `AppDetailView` import so these adjacent lines read:

```python
from tests.endpoint_helpers import meta_for, snapshot
from ai_manager.ui.app_detail_view import AppDetailView, DROPDOWN_MAX_WIDTH
```

- [ ] **Step 2: Append all 12 approved tests verbatim**

Append the following functions after the existing final line 1098, with two blank lines separating top-level functions. Do not alter any of the existing tests or any test/helper file other than `tests/test_app_views.py`.

```python
def test_dropdown_maximum_width_applied_to_all_four_combos(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())

    assert (
        view._protocol_combo.maximumWidth(),
        view._model_combo.maximumWidth(),
        view._ocr_combo.maximumWidth(),
        view._text_combo.maximumWidth(),
    ) == (DROPDOWN_MAX_WIDTH,) * 4


def test_api_text_fields_remain_uncapped(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())

    assert view._base_url_edit.maximumWidth() > DROPDOWN_MAX_WIDTH
    assert view._key_edit.maximumWidth() > DROPDOWN_MAX_WIDTH


def test_dropdown_caps_are_effective_in_live_layout_at_1400px(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.resize(1400, 900)
    view.show()
    qtbot.waitUntil(lambda: view._protocol_combo.width() > 0 and view._model_combo.width() > 0)

    assert view.width() == 1400
    assert 0 < view._protocol_combo.width() <= DROPDOWN_MAX_WIDTH + 1
    assert 0 < view._model_combo.width() <= DROPDOWN_MAX_WIDTH + 1

    view._split_chk.setChecked(True)
    qtbot.waitUntil(lambda: view._ocr_combo.width() > 0 and view._text_combo.width() > 0)
    assert 0 < view._ocr_combo.width() <= DROPDOWN_MAX_WIDTH + 1
    assert 0 < view._text_combo.width() <= DROPDOWN_MAX_WIDTH + 1


def test_base_url_remains_full_width_in_1400px_live_layout(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.resize(1400, 900)
    view.show()
    qtbot.waitUntil(lambda: view._base_url_edit.width() > DROPDOWN_MAX_WIDTH + 100)

    assert view.width() == 1400
    assert view._base_url_edit.width() > DROPDOWN_MAX_WIDTH + 100


def test_dropdown_maximum_is_independent_of_window_width(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.show()
    combos = (
        view._protocol_combo, view._model_combo, view._ocr_combo, view._text_combo,
    )

    for width in (1400, 600):
        view.resize(width, 900)
        qtbot.waitUntil(lambda: view.width() == width)
        assert tuple(combo.maximumWidth() for combo in combos) == (DROPDOWN_MAX_WIDTH,) * 4


def test_dropdowns_shrink_below_cap_when_column_is_narrower(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.resize(420, 900)
    view.show()
    qtbot.waitUntil(
        lambda: view._provider_group.contentsRect().width() < DROPDOWN_MAX_WIDTH
        and view._model_group.contentsRect().width() < DROPDOWN_MAX_WIDTH
    )

    assert view._protocol_combo.width() < DROPDOWN_MAX_WIDTH
    assert view._model_combo.width() < DROPDOWN_MAX_WIDTH

    view._split_chk.setChecked(True)
    qtbot.waitUntil(lambda: view._ocr_combo.width() > 0 and view._text_combo.width() > 0)
    assert view._ocr_combo.width() < DROPDOWN_MAX_WIDTH
    assert view._text_combo.width() < DROPDOWN_MAX_WIDTH


def test_widest_protocol_label_fits_inside_dropdown_cap(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    combo = view._protocol_combo
    metrics = QFontMetrics(combo.font())
    widest = "OpenAI Chat Completions — /v1/chat/completions"

    assert widest == max(view._protocol_labels, key=metrics.horizontalAdvance)
    option = QStyleOptionComboBox()
    option.initFrom(combo)
    option.rect = QRect(0, 0, DROPDOWN_MAX_WIDTH, combo.sizeHint().height())
    option.currentText = widest
    option.editable = combo.isEditable()
    option.frame = combo.hasFrame()
    text_rect = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox,
        option,
        QStyle.SubControl.SC_ComboBoxEditField,
        combo,
    )

    assert metrics.horizontalAdvance(widest) <= text_rect.width()


def test_long_model_value_remains_editable_and_scrolls_to_cursor(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.resize(900, 700)
    view.show()
    long_value = "m365-copilot-gpt-5.5-think-deeper-reasoning-" * 4
    view._model_combo.setEditText(long_value)
    line_edit = view._model_combo.lineEdit()
    assert line_edit is not None
    line_edit.setFocus()
    line_edit.setCursorPosition(len(long_value))
    qtbot.waitUntil(line_edit.hasFocus)
    caret = line_edit.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)

    assert QFontMetrics(line_edit.font()).horizontalAdvance(long_value) > line_edit.contentsRect().width()
    assert view._model_combo.currentText() == long_value
    assert line_edit.cursorPosition() == len(long_value)
    assert line_edit.contentsRect().contains(caret.center())


def test_unified_and_split_model_combo_widths_match(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.resize(1400, 900)
    view.show()
    view._split_chk.setChecked(False)
    qtbot.waitUntil(lambda: view._model_combo.width() > 0)
    unified_width = view._model_combo.width()

    view._split_chk.setChecked(True)
    qtbot.waitUntil(lambda: view._ocr_combo.width() > 0 and view._text_combo.width() > 0)
    assert unified_width == view._ocr_combo.width() == view._text_combo.width()
    assert unified_width == DROPDOWN_MAX_WIDTH


def test_model_combo_still_lists_all_available_models(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    models = ["gemini-flash-high", "deepseek-flash", "m365-copilot"]

    view.set_available_models(models)

    assert [view._model_combo.itemText(i) for i in range(view._model_combo.count())] == models


def test_model_quick_pick_click_fills_unified_combo(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    model = "deepseek-flash"
    view.set_available_models([model])
    chip = view.findChild(QToolButton, "modelChip")
    assert chip is not None

    qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)

    assert view._model_combo.currentText() == model


def test_protocol_selection_updates_current_draft_endpoint(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    index = view._protocol_combo.findData("/v1/messages")
    assert index >= 0

    view._protocol_combo.setCurrentIndex(index)

    assert view.get_current_draft().endpoint == "/v1/messages"
```

- [ ] **Step 3: Run the focused file and verify the required RED diagnostic**

Run from the repository root:

```bash
source /home/bin/yesconda
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_app_views.py -q
```

Expected: pytest exits **2** during collection. The required exact diagnostic text is:

```text
ImportError: cannot import name 'DROPDOWN_MAX_WIDTH' from 'ai_manager.ui.app_detail_view'
```

The traceback may append the module's filesystem path after that exact text. This is the intended RED result, not an assertion failure or a missing dependency. Record the command, exit code, and diagnostic in the task report. Stop if the command passes or fails for another reason; do not repair production code or weaken the import in this task.

- [ ] **Step 4: Verify the RED change is tests-only**

```bash
git diff --check
git diff --name-only
git diff -- tests/test_app_views.py
```

Expected: `git diff --check` exits **0** with no output; the task's only modified tracked path is `tests/test_app_views.py`; the diff contains only the merged section 4 imports and the 12 verbatim appended functions. `src/ai_manager/ui/app_detail_view.py` still has no `DROPDOWN_MAX_WIDTH` definition or width calls.

- [ ] **Step 5: Commit**

Commit the intentional tests-only RED state before Task 2 starts:

```bash
git add -- tests/test_app_views.py
git commit -m "test(ui): specify dropdown width limits (RED)"
```

Expected: commit exits **0** and includes only `tests/test_app_views.py`. The required ImportError remains the recorded verification result for this task.

## Task 2: Add the shared cap and four construction-time calls, then commit GREEN

**Implementer tier:** Standard

**Files:**

- Modify: `src/ai_manager/ui/app_detail_view.py:43-46` — add the module-level constant between imports and `class AppDetailView`.
- Modify: `src/ai_manager/ui/app_detail_view.py:158-166` — cap the conditional protocol combo immediately after construction.
- Modify: `src/ai_manager/ui/app_detail_view.py:222-244` — cap the unified, OCR, and text model combos immediately after each construction.
- Test: `tests/test_app_views.py` — consume Task 1's committed tests without editing them.
- Test: `tests/` — run the complete suite without editing other tests or fixtures.

**Interfaces:**

- Consumes: Task 1's import contract `from ai_manager.ui.app_detail_view import AppDetailView, DROPDOWN_MAX_WIDTH` and its 12 regression functions in `tests/test_app_views.py`: `test_dropdown_maximum_width_applied_to_all_four_combos`, `test_api_text_fields_remain_uncapped`, `test_dropdown_caps_are_effective_in_live_layout_at_1400px`, `test_base_url_remains_full_width_in_1400px_live_layout`, `test_dropdown_maximum_is_independent_of_window_width`, `test_dropdowns_shrink_below_cap_when_column_is_narrower`, `test_widest_protocol_label_fits_inside_dropdown_cap`, `test_long_model_value_remains_editable_and_scrolls_to_cursor`, `test_unified_and_split_model_combo_widths_match`, `test_model_combo_still_lists_all_available_models`, `test_model_quick_pick_click_fills_unified_combo`, and `test_protocol_selection_updates_current_draft_endpoint`; each takes `(qtbot, tmp_path)` and returns `None`.
- Consumes: existing `AppDetailView._init_ui(self) -> None`, with `AppDetailView._protocol_combo: QComboBox | None` constructed only when `self.app_meta.supports_protocol_selection` is true; `AppDetailView._model_combo: ModelComboBox`, `AppDetailView._ocr_combo: ModelComboBox`, and `AppDetailView._text_combo: ModelComboBox` remain unconditionally constructed in their existing unified/split boxes.
- Produces: module-level `ai_manager.ui.app_detail_view.DROPDOWN_MAX_WIDTH: int = 480` and exactly one `setMaximumWidth(DROPDOWN_MAX_WIDTH)` call per `_protocol_combo`, `_model_combo`, `_ocr_combo`, and `_text_combo`. Their configured `maximumWidth() -> int` becomes `480` without changing their types, editability, minimums, size policies, layouts, or interactions. A non-protocol app still has `_protocol_combo is None`.

Prerequisite: Task 1's tests-only RED commit exists and its report records the exact missing-constant ImportError. This task contains the complete production delta; make no other persistent implementation changes.

- [ ] **Step 1: Define the shared module-level constant**

Insert the following after all imports and before `class AppDetailView`, at the original lines 43-46 boundary; keep normal blank-line separation:

```python
DROPDOWN_MAX_WIDTH = 480
```

- [ ] **Step 2: Cap the protocol combo in its existing conditional branch**

At the construction site inside `if self.app_meta.supports_protocol_selection:`, make these lines adjacent, retaining their existing indentation and all subsequent item/signal/layout code:

```python
            self._protocol_combo = QComboBox(self)
            self._protocol_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)
```

Do not move the call outside the branch or apply it to `_preset_combo`.

- [ ] **Step 3: Cap the three model combos immediately after construction**

At the three existing construction sites in `_init_ui`, make each pair adjacent. Leave their current signal connections, layout insertion, and visibility logic unchanged:

```python
        self._model_combo = ModelComboBox(self)
        self._model_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)
```

```python
        self._ocr_combo = ModelComboBox(self)
        self._ocr_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)
```

```python
        self._text_combo = ModelComboBox(self)
        self._text_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)
```

- [ ] **Step 4: Run the entire focused test file and verify GREEN**

```bash
source /home/bin/yesconda
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_app_views.py -q
status=$?
test "$status" -eq 0 && printf 'PASS: tests/test_app_views.py; exit 0; no failures or errors.\n'
```

Expected: pytest exits **0**, every test in the file passes, and its summary contains `176 passed` for the approved baseline (164 existing cases plus 12 new tests; elapsed time is variable). The final verification line must be exactly:

```text
PASS: tests/test_app_views.py; exit 0; no failures or errors.
```

Do not accept skips, expected-failure markers, or changed tests as substitutes for GREEN.

- [ ] **Step 5: Run the whole tests directory with the required sibling-workspace root**

```bash
source /home/bin/yesconda
PYTHONPATH=src QT_QPA_PLATFORM=offscreen AI_WORKSPACE_ROOT=/data/home/guest/Development/ai python3 -m pytest tests/ -q
status=$?
test "$status" -eq 0 && printf 'PASS: tests/; exit 0; no failures or errors.\n'
```

Expected: pytest exits **0** with **no failures or errors** across the complete `tests/` directory. Record its actual test totals and summary in the task report; do not infer a total from the focused run. The final verification line must be exactly:

```text
PASS: tests/; exit 0; no failures or errors.
```

Keep `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai` on this command: `tests/test_e2e_integration.py` resolves sibling app directories. Any full-suite failure blocks the GREEN commit; do not change unrelated source or tests to hide it.

- [ ] **Step 6: Run the 11 section 5 mutation probes in isolated temporary copies**

Run the following from the repository root. It first proves the unmutated focused-file control passes, verifies every subprocess imports the copied source, and then makes one source replacement per fresh copy. A mutant counts as killed only when its named test exits **1**, reports `1 failed`, and displays the required assertion evidence. No mutation reaches the active worktree, and the temporary directory is removed even if an assertion fails. The population probe suppresses only the unified combo's iteration of the existing `combo.set_models(self._available_models, current=current)` loop, preserving the OCR/text iterations; this is the current source form of the spec's unified population call.

```bash
source /home/bin/yesconda
python3 - <<'PY'
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

repo = Path.cwd()
relative_source = Path("src/ai_manager/ui/app_detail_view.py")
cap_test = "test_dropdown_maximum_width_applied_to_all_four_combos"
probes = [
    (
        "remove_protocol_cap",
        "            self._protocol_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)\n",
        "",
        cap_test,
        "16777215",
    ),
    (
        "remove_model_cap",
        "        self._model_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)\n",
        "",
        cap_test,
        "16777215",
    ),
    (
        "remove_ocr_cap",
        "        self._ocr_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)\n",
        "",
        cap_test,
        "16777215",
    ),
    (
        "remove_text_cap",
        "        self._text_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)\n",
        "",
        cap_test,
        "16777215",
    ),
    (
        "shrink_cap_to_300",
        "DROPDOWN_MAX_WIDTH = 480\n",
        "DROPDOWN_MAX_WIDTH = 300\n",
        "test_widest_protocol_label_fits_inside_dropdown_cap",
        "assert metrics.horizontalAdvance(widest) <= text_rect.width()",
    ),
    (
        "cap_base_url",
        "        self._base_url_edit = QLineEdit(self)\n",
        "        self._base_url_edit = QLineEdit(self)\n"
        "        self._base_url_edit.setMaximumWidth(DROPDOWN_MAX_WIDTH)\n",
        "test_api_text_fields_remain_uncapped",
        "assert view._base_url_edit.maximumWidth() > DROPDOWN_MAX_WIDTH",
    ),
    (
        "fix_model_width",
        "        self._model_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)\n",
        "        self._model_combo.setFixedWidth(DROPDOWN_MAX_WIDTH)\n",
        "test_dropdowns_shrink_below_cap_when_column_is_narrower",
        "assert view._model_combo.width() < DROPDOWN_MAX_WIDTH",
    ),
    (
        "disable_model_editability",
        "        self._model_combo = ModelComboBox(self)\n",
        "        self._model_combo = ModelComboBox(self)\n"
        "        self._model_combo.setEditable(False)\n",
        "test_long_model_value_remains_editable_and_scrolls_to_cursor",
        "assert line_edit is not None",
    ),
    (
        "remove_unified_population",
        "                combo.set_models(self._available_models, current=current)\n",
        "                if combo is not self._model_combo:\n"
        "                    combo.set_models(self._available_models, current=current)\n",
        "test_model_combo_still_lists_all_available_models",
        "assert [view._model_combo.itemText(i) for i in range(view._model_combo.count())] == models",
    ),
    (
        "disable_unified_quick_pick",
        "            self._model_combo.setEditText(model_name)\n",
        "            pass\n",
        "test_model_quick_pick_click_fills_unified_combo",
        "assert view._model_combo.currentText() == model",
    ),
    (
        "disable_protocol_endpoint_update",
        "        self._endpoint = self._protocol_combo.itemData(index)\n",
        "",
        "test_protocol_selection_updates_current_draft_endpoint",
        'assert view.get_current_draft().endpoint == "/v1/messages"',
    ),
]


def run_tests(root, target):
    env = os.environ.copy()
    env.update(
        PYTHONPATH="src",
        QT_QPA_PLATFORM="offscreen",
        PYTHONDONTWRITEBYTECODE="1",
    )
    location = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import ai_manager.ui.app_detail_view as m; "
            "print(Path(m.__file__).resolve())",
        ],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert location.returncode == 0, location.stderr
    assert location.stdout.strip() == str((root / relative_source).resolve()), location.stdout
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q"],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
with tempfile.TemporaryDirectory(prefix="dropdown-width-probes-") as temporary:
    root = Path(temporary)
    control = root / "control"
    control.mkdir()
    shutil.copytree(repo / "src", control / "src", symlinks=True, ignore=ignore)
    shutil.copytree(repo / "tests", control / "tests", symlinks=True, ignore=ignore)
    shutil.copy2(repo / "pyproject.toml", control / "pyproject.toml")
    result = run_tests(control, "tests/test_app_views.py")
    assert result.returncode == 0, result.stdout
    print("CONTROL PASS: tests/test_app_views.py")
    for name, old, new, test_name, evidence in probes:
        probe = root / name
        shutil.copytree(control, probe, symlinks=True, ignore=ignore)
        source = probe / relative_source
        original = source.read_text(encoding="utf-8")
        assert original.count(old) == 1, (name, original.count(old))
        source.write_text(original.replace(old, new, 1), encoding="utf-8")
        result = run_tests(probe, f"tests/test_app_views.py::{test_name}")
        assert result.returncode == 1, (name, result.returncode, result.stdout)
        assert "1 failed" in result.stdout, (name, result.stdout)
        assert evidence in result.stdout, (name, evidence, result.stdout)
        print(f"MUTATION KILLED: {name}")
print("PASS: all 11 isolated mutation probes killed by the required assertions")
PY
```

Expected: exit **0** and exactly these verification lines (a collection/setup error, timeout, missing anchor, or surviving mutant is not an acceptable kill):

```text
CONTROL PASS: tests/test_app_views.py
MUTATION KILLED: remove_protocol_cap
MUTATION KILLED: remove_model_cap
MUTATION KILLED: remove_ocr_cap
MUTATION KILLED: remove_text_cap
MUTATION KILLED: shrink_cap_to_300
MUTATION KILLED: cap_base_url
MUTATION KILLED: fix_model_width
MUTATION KILLED: disable_model_editability
MUTATION KILLED: remove_unified_population
MUTATION KILLED: disable_unified_quick_pick
MUTATION KILLED: disable_protocol_endpoint_update
PASS: all 11 isolated mutation probes killed by the required assertions
```

- [ ] **Step 7: Review the exact production delta and confirm scope**

```bash
git diff --check
git diff --name-only
git diff -- src/ai_manager/ui/app_detail_view.py
```

Expected: `git diff --check` exits **0** with no output; the only modified tracked path since Task 1's commit is `src/ai_manager/ui/app_detail_view.py`. Its only executable additions are `DROPDOWN_MAX_WIDTH = 480` and the four exact construction-time `setMaximumWidth(DROPDOWN_MAX_WIDTH)` calls. The tests from Task 1, URL/key/preset widths, layout code, model-combo implementation, theme, and all behavior methods are unchanged. Record focused-file, full-suite, and mutation evidence in the task report before committing.

- [ ] **Step 8: Commit**

```bash
git add -- src/ai_manager/ui/app_detail_view.py
git commit -m "fix(ui): cap protocol and model dropdown widths at 480px"
```

Expected: commit exits **0** and includes only `src/ai_manager/ui/app_detail_view.py`. The branch retains the separate Task 1 RED commit followed by this GREEN commit; do not squash away the required TDD order.
