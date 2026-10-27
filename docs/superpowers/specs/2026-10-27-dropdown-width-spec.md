# Drop-down width implementation specification

Date: 2026-10-27  
Status: approved for implementation

## 1. Scope and non-goals

**Scope.** In `AppDetailView`, cap the upstream-protocol combo and all three model combos at a shared maximum of 480 Qt logical pixels. Keep the cap independent of window width, allow each combo to become narrower when its form column is narrower, and preserve model/protocol interaction. Add the headless regression tests in §4 to `tests/test_app_views.py`; use only temporary metadata/config fixtures and local Qt widgets.

**Non-goals.** Do not alter the API Base URL or API Key width, the preset combo, model-combo implementation, popup-list width, theme/QSS, size policies, minimum widths, layout stretch/alignment, spacing, labels, model fetching, protocol semantics, or any supervisor/network behavior. Do not modify `tests/test_widgets.py`, `tests/endpoint_helpers.py`, or `tests/conftest.py` for this change.

## 2. Exact code contract

Add the following **module-level** constant in `src/ai_manager/ui/app_detail_view.py`, after the imports and before `class AppDetailView`:

```python
DROPDOWN_MAX_WIDTH = 480
```

In `AppDetailView._init_ui`, call `setMaximumWidth(DROPDOWN_MAX_WIDTH)` exactly once for each of the following attributes, immediately after that widget is constructed and before it is added to its layout:

| Attribute | Enclosing method / creation branch | Required call |
| --- | --- | --- |
| `self._protocol_combo` | `AppDetailView._init_ui`, inside `if self.app_meta.supports_protocol_selection:` | `self._protocol_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` |
| `self._model_combo` | `AppDetailView._init_ui`, unified model box | `self._model_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` |
| `self._ocr_combo` | `AppDetailView._init_ui`, split model box | `self._ocr_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` |
| `self._text_combo` | `AppDetailView._init_ui`, split model box | `self._text_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` |

These are the complete set of call sites. The protocol combo remains conditional on protocol support; the three model combos remain constructed as they are today. Do **not** change their size policies, set any minimum or fixed width, change layout stretch or alignment, or add layout wrappers. Do not edit theme QSS or `src/ai_manager/ui/widgets/model_combo.py`. Do not apply the cap to `_preset_combo`, `_base_url_edit`, `_key_edit`, or any other widget; do not set popup width. In particular, `API Base URL` and `API Key` must remain able to use the full form-column width.

## 3. Invariants after the change

Each statement below is a separately testable contract:

1. `DROPDOWN_MAX_WIDTH` is the integer `480`, in Qt logical pixels, and is not calculated from window or column dimensions.
2. `_protocol_combo`, `_model_combo`, `_ocr_combo`, and `_text_combo` each report `maximumWidth() == DROPDOWN_MAX_WIDTH`.
3. In a wide live layout, no in-use combo exceeds `DROPDOWN_MAX_WIDTH + 1` pixels. The `+ 1` allowance is for Qt geometry rounding only.
4. Resizing the view does not change the four combos' configured `maximumWidth()`; the property remains 480 at both wide and narrow window widths.
5. When the provider/model column is narrower than 480 pixels, each combo in that column has an actual width below 480. A maximum is not a minimum or fixed width.
6. A model string whose rendered advance is wider than the editable model combo's line-edit contents area remains the exact current text, with the end cursor inside that contents area. Qt's editable line edit horizontally scrolls the value; the combo does not truncate the stored text.
7. The widest protocol label, `OpenAI Chat Completions — /v1/chat/completions`, fits in the combo's text/edit-field subcontrol at a 480-pixel combo width according to `QFontMetrics`. The subcontrol measurement accounts for style frame, padding, and arrow space; do not substitute a hand-coded allowance.
8. In the wide layout, the unified `_model_combo` and split `_ocr_combo` / `_text_combo` have equal actual widths. All three use the same maximum.
9. The fetched model list remains present in `_model_combo`; clicking a model quick-pick continues to populate the active unified combo; selecting a protocol continues to update `get_current_draft().endpoint`.
10. `_base_url_edit.maximumWidth()` and `_key_edit.maximumWidth()` remain greater than 480, and the base URL remains materially wider than a combo in a 1400-pixel live view.

## 4. Test fixtures and exact tests

Add these imports to `tests/test_app_views.py` (merge them into existing import statements where appropriate):

```python
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QStyle, QStyleOptionComboBox, QToolButton
from ai_manager.ui.app_detail_view import AppDetailView, DROPDOWN_MAX_WIDTH
from tests.endpoint_helpers import meta_for, snapshot
```

Each test below is one contract. The tests use `meta_for(tmp_path, "textkit")` because that fixture enables split models and, by default, protocol selection. `snapshot()` supplies an in-memory configuration; `meta_for()` places its launch path under `tmp_path`. No test may read/write the user's real configuration, invoke the real supervisor, or access the network. Existing `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` by default and supplies the inert supervisor fixtures. Run from the repository root with:

```bash
QT_QPA_PLATFORM=offscreen pytest -q tests/test_app_views.py
```

### 4.1 Cap applies to all four combos

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
```

### 4.2 Text fields remain uncapped

```python
def test_api_text_fields_remain_uncapped(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())

    assert view._base_url_edit.maximumWidth() > DROPDOWN_MAX_WIDTH
    assert view._key_edit.maximumWidth() > DROPDOWN_MAX_WIDTH
```

### 4.3 Cap is effective in the live layout at 1400 pixels

Check each presentation while it is visible; do not treat the hidden unified/split box as the live-layout measurement.

```python
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
```

### 4.4 Base URL remains wide in the 1400-pixel live layout

```python
def test_base_url_remains_full_width_in_1400px_live_layout(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.resize(1400, 900)
    view.show()
    qtbot.waitUntil(lambda: view._base_url_edit.width() > DROPDOWN_MAX_WIDTH + 100)

    assert view.width() == 1400
    assert view._base_url_edit.width() > DROPDOWN_MAX_WIDTH + 100
```

### 4.5 Configured cap is independent of window width

The view clamps itself to a minimum width of 441 px (522 px with an application
stylesheet), so the narrow sample is 600 px; requesting anything below the clamp makes
the `view.width() == width` wait unsatisfiable.

```python
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
```

### 4.6 Combos shrink below the cap in a narrower column

```python
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
```

### 4.7 Widest protocol label fits using style geometry and `QFontMetrics`

```python
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
```

### 4.8 Long model text scrolls in the editable combo

`QLineEdit.cursorRect()` is protected and raises `RuntimeError` for a C++-owned line
edit, and the caret rectangle legitimately overhangs the contents edge by its own width,
so full-rectangle containment is a false oracle. Query the caret rectangle through
`inputMethodQuery` and assert that its centre lies inside the contents rectangle.

```python
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
```

### 4.9 Unified and split model combos agree in the live layout

```python
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
```

### 4.10 Fetched model values remain listed

```python
def test_model_combo_still_lists_all_available_models(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    models = ["gemini-flash-high", "deepseek-flash", "m365-copilot"]

    view.set_available_models(models)

    assert [view._model_combo.itemText(i) for i in range(view._model_combo.count())] == models
```

### 4.11 Quick-pick click still fills the unified combo

```python
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
```

### 4.12 Protocol selection still reaches the current draft

```python
def test_protocol_selection_updates_current_draft_endpoint(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "textkit"))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    index = view._protocol_combo.findData("/v1/messages")
    assert index >= 0

    view._protocol_combo.setCurrentIndex(index)

    assert view.get_current_draft().endpoint == "/v1/messages"
```

## 5. Mutation probes

Run each probe in an isolated copy of the implementation/test change. Each probe is one source edit; the named test must fail for the stated reason.

| Single edit | Test that must fail | Expected failure mode |
| --- | --- | --- |
| Remove only the `_protocol_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` line. | `test_dropdown_maximum_width_applied_to_all_four_combos` | The protocol combo reports its default maximum width instead of 480. |
| Remove only the `_model_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` line. | `test_dropdown_maximum_width_applied_to_all_four_combos` | The unified model combo reports its default maximum width instead of 480. |
| Remove only the `_ocr_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` line. | `test_dropdown_maximum_width_applied_to_all_four_combos` | The OCR combo reports its default maximum width instead of 480. |
| Remove only the `_text_combo.setMaximumWidth(DROPDOWN_MAX_WIDTH)` line. | `test_dropdown_maximum_width_applied_to_all_four_combos` | The text combo reports its default maximum width instead of 480. |
| Change `DROPDOWN_MAX_WIDTH = 480` to `DROPDOWN_MAX_WIDTH = 300`. | `test_widest_protocol_label_fits_inside_dropdown_cap` | The widest label's `QFontMetrics.horizontalAdvance()` exceeds the style's edit-field width. |
| Add `self._base_url_edit.setMaximumWidth(DROPDOWN_MAX_WIDTH)` as a single extra call. | `test_api_text_fields_remain_uncapped` | The base URL maximum becomes 480, not greater than 480. |
| Replace the model combo's `setMaximumWidth(...)` call with `setFixedWidth(...)`. | `test_dropdowns_shrink_below_cap_when_column_is_narrower` | The model combo remains fixed at 480 when its column is narrower. |
| Insert `self._model_combo.setEditable(False)` immediately after the unified model combo is constructed. | `test_long_model_value_remains_editable_and_scrolls_to_cursor` | `lineEdit()` returns `None`, so `assert line_edit is not None` fails. Do not mutate `ModelComboBox.__init__` instead: its completer dereference raises `AttributeError` during construction, which errors the test without exercising the scroll contract. |
| Remove the `_model_combo.set_models(...)` population call from `_display_draft`. | `test_model_combo_still_lists_all_available_models` | The fetched model strings are absent from the combo items. |
| Change `_apply_model_choice` so it no longer sets the unified combo's edit text. | `test_model_quick_pick_click_fills_unified_combo` | A real quick-pick click leaves the model combo unchanged. |
| Change `_on_protocol_selected` so it no longer updates `_endpoint` from the selected item. | `test_protocol_selection_updates_current_draft_endpoint` | The draft endpoint remains unset after selecting `/v1/messages`. |

## 6. Rollback

This is a UI-only change with no persisted-data or migration rollback. If implementation must be reverted, selectively remove the four maximum-width calls and the module-level `DROPDOWN_MAX_WIDTH` constant from `src/ai_manager/ui/app_detail_view.py`, then remove only the new test functions and their now-unused imports from `tests/test_app_views.py`. Do not restore either whole file or discard unrelated edits. Review the resulting diff, then run `QT_QPA_PLATFORM=offscreen pytest -q tests/test_app_views.py` to verify the prior behavior and remaining tests. If only this specification artifact is being withdrawn before implementation, delete only `docs/superpowers/specs/2026-10-27-dropdown-width-spec.md`.
