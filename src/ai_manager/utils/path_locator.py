import os
from pathlib import Path
from typing import Optional


def find_ai_workspace_root(start_dir: Optional[Path] = None) -> Path:
    """Finds the root directory containing ai backends and ai-backends supervisor."""
    env_override = os.environ.get("AI_WORKSPACE_ROOT")
    if env_override:
        p = Path(env_override).resolve()
        if p.is_dir():
            return p

    current = (start_dir or Path.cwd()).resolve()

    # Look upwards until we find a directory with ai-backends or sibling repositories
    for candidate in [current, *current.parents]:
        if (candidate / "ai-backends").exists():
            return candidate
        if (candidate / "ai-grammar").exists() and (candidate / "textkit").exists():
            return candidate

    # Fallback to parent of ai-manager if current directory is inside ai-manager
    if current.name == "ai-manager":
        return current.parent

    return current
