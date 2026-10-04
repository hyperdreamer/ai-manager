from pathlib import Path
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import AppAIConfig, ServiceRunState, ServiceStatus
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.app_sidebar import AppSidebar


def test_app_sidebar(qtbot):
    apps = get_managed_apps(Path("/tmp"))
    sidebar = AppSidebar(apps)
    qtbot.addWidget(sidebar)

    assert sidebar.current_app_id() == "ai-grammar"

    # Select textkit
    sidebar.select_app("textkit")
    assert sidebar.current_app_id() == "textkit"

    # Set dirty
    sidebar.set_dirty("textkit", True)
    item = sidebar._list_widget.currentItem()
    assert "*" in item.text()

    # Update status
    sidebar.update_status(
        "textkit",
        ServiceStatus(
            service_id="textkit",
            state=ServiceRunState.RUNNING,
            pid=1234,
        ),
    )
    assert "●" in sidebar._list_widget.currentItem().text()


def test_app_detail_view(qtbot):
    apps = get_managed_apps(Path("/tmp"))
    meta_textkit = apps["textkit"]

    detail = AppDetailView(meta_textkit)
    qtbot.addWidget(detail)

    cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        model="gemini-flash-high",
    )
    detail.load_config(cfg)

    draft = detail.get_current_draft()
    assert draft.api_base == "http://localhost:3000"
    assert draft.model == "gemini-flash-high"
    assert not draft.is_split_model

    # Toggle split models
    detail._split_chk.setChecked(True)
    detail._ocr_combo.setEditText("qwen-ocr")
    detail._text_combo.setEditText("deepseek-text")

    split_draft = detail.get_current_draft()
    assert split_draft.is_split_model is True
    assert split_draft.ocr_model == "qwen-ocr"
    assert split_draft.text_model == "deepseek-text"
