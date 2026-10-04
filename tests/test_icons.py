"""Unit tests for the application icon pipeline (colour, symbolic, tray).

Headless via ``QT_QPA_PLATFORM=offscreen`` in ``conftest.py``; the pytest-qt
``qapp`` fixture supplies the ``QGuiApplication`` that ``QPixmap`` requires.
The no-application test deliberately runs in a subprocess with no application.
"""

from pathlib import Path

import pytest
from PyQt6.QtCore import QByteArray
from PyQt6.QtSvg import QSvgRenderer

from ai_manager.resources import assets

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_assets_exist_and_parse():
    color_bytes = assets.asset_bytes("color")
    symbolic_bytes = assets.asset_bytes("symbolic")
    assert color_bytes is not None
    assert symbolic_bytes is not None
    assert QSvgRenderer(QByteArray(color_bytes)).isValid()

    substituted = symbolic_bytes.replace(b"__HALO__", b"#ffffff").replace(
        b"__GLYPH__", b"#000000"
    )
    assert b"__HALO__" not in substituted
    assert b"__GLYPH__" not in substituted
    assert QSvgRenderer(QByteArray(substituted)).isValid()


def test_asset_path_returns_existing_files_and_rejects_unknown_kind():
    for kind in ("color", "symbolic"):
        path = assets.asset_path(kind)
        assert path is not None
        assert path.is_file()
    with pytest.raises(ValueError):
        assets.asset_path("bogus")
