import ast
from pathlib import Path
import re
import tomllib

from ai_manager import __version__


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "ai_manager" / "__init__.py"


def test_version_is_release_triplet():
    assert re.fullmatch(r"^\d+\.\d+\.\d+$", __version__) is not None


def test_pyproject_derives_version():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "ai-manager"
    assert "version" not in project
    assert project["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "ai_manager.__version__"
    }
    assert project["authors"] == [
        {"name": "Henry", "email": "wenhepku@gmail.com"}
    ]
    assert project["description"] == (
        "Desktop administration GUI for local AI backends"
    )
    assert project["dependencies"] == [
        "PyQt6>=6.5.0",
        "pydantic>=2.0.0",
        "ruamel.yaml>=0.18.0",
        "httpx>=0.25.0",
    ]
    assert project["optional-dependencies"]["dev"] == [
        "pytest>=7.0.0",
        "pytest-qt>=4.2.0",
        "respx>=0.20.0",
    ]
    assert project["scripts"] == {"ai-manager": "ai_manager.main:main"}
    assert data["build-system"] == {
        "requires": ["setuptools>=61.0"],
        "build-backend": "setuptools.build_meta",
    }
    assert data["tool"]["setuptools"]["package-data"]["ai_manager"] == [
        "resources/icons/*.svg"
    ]


def test_version_literal_is_static_string():
    tree = ast.parse(VERSION_FILE.read_text(encoding="utf-8"))
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    assignment = assignments[0]
    assert isinstance(assignment.value, ast.Constant)
    assert isinstance(assignment.value.value, str)
    version_stores = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "__version__"
        and isinstance(node.ctx, ast.Store)
    ]
    assert len(version_stores) == 1
    assert version_stores[0] in assignment.targets


def test_version_init_has_no_imports():
    tree = ast.parse(VERSION_FILE.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body
    )


def test_version_consumers_import_the_symbol():
    forbidden = (
        "importlib", "importlib.metadata", "subprocess", "platform", "tomllib"
    )
    for relative in (
        "src/ai_manager/ui/main_window.py",
        "src/ai_manager/ui/about_dialog.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "ai_manager"
            and any(alias.name == "__version__" for alias in node.names)
            for node in ast.walk(tree)
        ), relative
        assert re.search(
            r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", source
        ) is None, relative
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ), (relative, name)
