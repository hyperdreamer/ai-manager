from pathlib import Path


def test_readme_documents_version_display():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )
    assert (
        "- **Version Display**: The version appears in the window title and in "
        "the About dialog (tray menu or Settings)."
    ) in readme
    assert (
        "Bump the version only in `src/ai_manager/__init__.py`; packaging "
        "metadata derives from it. Re-run the editable install after a bump."
    ) in readme
