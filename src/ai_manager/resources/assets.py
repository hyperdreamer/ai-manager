"""Qt-free access to the packaged icon assets.

Both public helpers never raise for an unavailable resource: they return
``None`` so callers such as the ``.desktop`` entry generator stay valid when
an asset is missing. An unknown ``kind`` is a programming error and raises
``ValueError`` immediately instead of silently defaulting.
"""

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

_TABLE: dict[str, str] = {
    "color": "ai-manager.svg",
    "symbolic": "ai-manager-symbolic.svg",
}

_PACKAGE = "ai_manager.resources"
_ICON_DIR = "icons"


def _filename(kind: str) -> str:
    try:
        return _TABLE[kind]
    except KeyError:
        raise ValueError(f"unknown icon asset kind: {kind!r}") from None


def _traversable(kind: str) -> Traversable:
    return resources.files(_PACKAGE).joinpath(_ICON_DIR, _filename(kind))


def asset_bytes(kind: str) -> bytes | None:
    """Raw bytes of a packaged icon asset, or ``None`` when unavailable."""
    try:
        return _traversable(kind).read_bytes()
    except (ModuleNotFoundError, OSError):
        return None


def asset_path(kind: str) -> Path | None:
    """Filesystem path of a packaged icon asset, or ``None`` when unavailable."""
    try:
        path = Path(str(_traversable(kind)))
    except (ModuleNotFoundError, OSError):
        return None
    return path if path.is_file() else None
