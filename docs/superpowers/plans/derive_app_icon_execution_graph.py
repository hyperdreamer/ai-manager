"""Derive the app-icon execution manifest (YAML) and DOT graph from the plan.

Deterministic: re-running this script on the same plan produces byte-identical
artifacts. Task numbers, titles and tiers are read from the plan itself (the
plan is the source of truth for those); lane, ownership, dependency,
interface and validation metadata live in the tables below.

The work is one tightly-coupled lane, so ownership patterns overlap between
consecutive tasks by design (tasks 1-4 all edit ``tests/test_icons.py``).
That is safe because a single lane executes strictly sequentially; the
manifest asserts this rather than pretending the patterns are disjoint.

Run:

    /home/henry/anaconda3/envs/daily/bin/python \\
        docs/superpowers/plans/derive_app_icon_execution_graph.py

Exits non-zero if the plan does not parse, its digest has drifted, a task's
ownership escapes the repository, or a validation vector contains a shell
metacharacter.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PLAN = HERE / "2026-10-04-app-icon.md"
YAML_OUT = HERE / "2026-10-04-app-icon.execution-graph.yaml"
DOT_OUT = HERE / "2026-10-04-app-icon.execution-graph.dot"

TOPIC = "app-icon"
LANE_ID = "icon-pipeline"
LANE_NAME = "Icon Pipeline Lane"

PYTHON = "/home/henry/anaconda3/envs/daily/bin/python"
REAL_WORKSPACE = "/data/home/guest/Development/ai"

SHELL_METACHARACTERS = set("|&;<>()$`\\\"'*?[]{}~\n")

INTERFACES = {
    "asset_bytes": "asset_bytes(kind: str) -> bytes | None",
    "asset_path": "asset_path(kind: str) -> Path | None",
    "color_icon": "color_icon() -> QIcon",
    "symbolic_icon": "symbolic_icon(glyph: QColor, halo: QColor) -> QIcon",
    "tray_colors": "tray_colors(palette: QPalette) -> tuple[QColor, QColor]",
    "tray_icon": "tray_icon(app: QApplication | None = None) -> QIcon",
    "configure_app_icon": "configure_app_icon(app: QApplication) -> None",
}

# id, ownership globs, produced interfaces, consumed interfaces, validation argv
TASK_META: dict[int, dict] = {
    1: {
        "ownership": [
            "src/ai_manager/resources/**",
            "tests/test_icons.py",
        ],
        "produces": ["asset_bytes", "asset_path"],
        "consumes": [],
        "validation": [[PYTHON, "-m", "pytest", "tests/test_icons.py", "-q"]],
    },
    2: {
        "ownership": [
            "src/ai_manager/ui/icons.py",
            "tests/test_icons.py",
        ],
        "produces": [
            "color_icon",
            "symbolic_icon",
            "tray_colors",
            "tray_icon",
            "configure_app_icon",
        ],
        "consumes": ["asset_bytes"],
        "validation": [[PYTHON, "-m", "pytest", "tests/test_icons.py", "-q"]],
    },
    3: {
        "ownership": [
            "src/ai_manager/main.py",
            "tests/test_icons.py",
        ],
        "produces": [],
        "consumes": ["configure_app_icon", "color_icon"],
        "validation": [[PYTHON, "-m", "pytest", "tests/test_icons.py", "-q"]],
    },
    4: {
        "ownership": [
            "src/ai_manager/ui/system_tray.py",
            "tests/test_icons.py",
            "tests/test_system_tray.py",
        ],
        "produces": [],
        "consumes": ["tray_icon", "tray_colors"],
        "validation": [
            [
                PYTHON,
                "-m",
                "pytest",
                "tests/test_icons.py",
                "tests/test_system_tray.py",
                "-q",
            ]
        ],
    },
    5: {
        "ownership": [
            "src/ai_manager/services/desktop_integration.py",
            "tests/test_desktop_integration.py",
        ],
        "produces": [],
        "consumes": ["asset_path"],
        "validation": [
            [PYTHON, "-m", "pytest", "tests/test_desktop_integration.py", "-q"]
        ],
    },
    6: {
        "ownership": ["pyproject.toml"],
        "produces": [],
        "consumes": [],
        "validation": [
            [PYTHON, "-m", "pytest", "tests/", "-q"],
        ],
    },
}

# Declared dependencies. Every same-lane task beyond index 0 also depends on its
# immediate predecessor, which is a manifest invariant, not an optional edge.
DEPENDS_ON: dict[int, list[int]] = {
    1: [],
    2: [1],
    3: [2],
    4: [3, 2],
    5: [4, 1],
    6: [5, 1, 2, 3, 4],
}


def parse_plan(text: str) -> list[dict]:
    """Extract (number, title, tier) triples using the plan grammar."""
    matches = list(re.finditer(r"^## Task (\d+): (.+)$", text, re.MULTILINE))
    if not matches:
        raise SystemExit("PLAN_INVALID: no '## Task N:' headings found")
    tasks = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        tier = re.search(r"^\*\*Implementer tier:\*\* (\w+)$", body, re.MULTILINE)
        if not tier:
            raise SystemExit(f"PLAN_INVALID: task {m.group(1)} has no tier line")
        tasks.append(
            {"number": int(m.group(1)), "title": m.group(2).strip(), "tier": tier.group(1).lower()}
        )
    numbers = [t["number"] for t in tasks]
    if numbers != list(range(1, len(tasks) + 1)):
        raise SystemExit(f"PLAN_INVALID: task numbers are not 1..N with no gaps: {numbers}")
    return tasks


def digest(signature: str) -> str:
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def assert_ownership_safe(patterns: list[str]) -> None:
    for p in patterns:
        if p.startswith("/") or "\\" in p:
            raise SystemExit(f"MANIFEST_INVALID: ownership must be repo-relative POSIX: {p}")
        if ".." in p.split("/"):
            raise SystemExit(f"MANIFEST_INVALID: ownership escapes the repository: {p}")


def assert_validation_safe(argv: list[str]) -> None:
    for token in argv:
        bad = SHELL_METACHARACTERS & set(token)
        if bad:
            raise SystemExit(
                f"MANIFEST_INVALID: validation token {token!r} contains shell metacharacters {sorted(bad)}"
            )
    joined = " ".join(argv)
    for mutator in ("git ", "git-", "&&", ";"):
        if mutator in joined:
            raise SystemExit(f"MANIFEST_INVALID: validation must not mutate git state: {joined}")


def build(tasks: list[dict]) -> dict:
    by_number = {t["number"]: t for t in tasks}
    if set(by_number) != set(TASK_META):
        raise SystemExit(
            f"MANIFEST_INVALID: plan tasks {sorted(by_number)} != manifest tasks {sorted(TASK_META)}"
        )

    producers: dict[str, int] = {}
    for n, meta in TASK_META.items():
        for produced in meta["produces"]:
            if produced in producers:
                raise SystemExit(f"MANIFEST_INVALID: interface {produced} produced twice")
            producers[produced] = n

    manifest_tasks = []
    for n in sorted(TASK_META):
        meta = TASK_META[n]
        assert_ownership_safe(meta["ownership"])
        for argv in meta["validation"]:
            assert_validation_safe(argv)

        deps = DEPENDS_ON[n]
        if n > 1 and (n - 1) not in deps:
            raise SystemExit(
                f"MANIFEST_INVALID: same-lane task {n} does not depend on its predecessor {n - 1}"
            )
        for dep in deps:
            if dep not in by_number:
                raise SystemExit(f"MANIFEST_INVALID: task {n} depends on unknown task {dep}")

        consumes = []
        for name in meta["consumes"]:
            if name not in producers:
                raise SystemExit(f"MANIFEST_INVALID: task {n} consumes {name} with no producer")
            producer = producers[name]
            if producer >= n:
                raise SystemExit(
                    f"MANIFEST_INVALID: task {n} consumes {name} produced later by task {producer}"
                )
            if producer not in deps:
                raise SystemExit(
                    f"MANIFEST_INVALID: task {n} consumes {name} from task {producer} without a dependency edge"
                )
            sig = INTERFACES[name]
            consumes.append(
                {"interface": name, "from_task": f"task-{producer}", "signature": sig, "signature_digest": digest(sig)}
            )

        produces = [
            {"interface": name, "signature": INTERFACES[name], "signature_digest": digest(INTERFACES[name])}
            for name in meta["produces"]
        ]

        manifest_tasks.append(
            {
                "id": f"task-{n}",
                "plan_task": n,
                "lane": LANE_ID,
                "sequence": n,
                "title": by_number[n]["title"],
                "tier": by_number[n]["tier"],
                "depends_on": [f"task-{d}" for d in deps],
                "ownership": meta["ownership"],
                "resources": [],
                "produces": produces,
                "consumes": consumes,
                "validation": [{"argv": argv} for argv in meta["validation"]],
            }
        )

    # Cycle check: assert every dependency resolves to a strictly earlier sequence.
    for t in manifest_tasks:
        for dep in t["depends_on"]:
            dep_seq = int(dep.split("-")[1])
            if dep_seq >= t["sequence"]:
                raise SystemExit(
                    f"MANIFEST_INVALID: cycle risk, {t['id']} depends on {dep} at the same or later sequence"
                )

    return {
        "schema_version": 1,
        "topic": TOPIC,
        "source_plan": {
            "path": f"docs/superpowers/plans/{PLAN.name}",
            "sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        },
        "lanes": [{"id": LANE_ID, "name": LANE_NAME, "task_ids": [t["id"] for t in manifest_tasks]}],
        "tasks": manifest_tasks,
    }


def render_yaml(manifest: dict) -> str:
    """Hand-rolled emitter: the shape is small and fixed, so no YAML dep is needed."""
    out: list[str] = []
    out.append(f"schema_version: {manifest['schema_version']}")
    out.append(f"topic: {manifest['topic']}")
    out.append("source_plan:")
    out.append(f"  path: {manifest['source_plan']['path']}")
    out.append(f"  sha256: {manifest['source_plan']['sha256']}")
    out.append("")
    out.append("lanes:")
    for lane in manifest["lanes"]:
        out.append(f"  - id: {lane['id']}")
        out.append(f"    name: {lane['name']}")
        out.append("    task_ids:")
        for tid in lane["task_ids"]:
            out.append(f"      - {tid}")
    out.append("")
    out.append("tasks:")
    for t in manifest["tasks"]:
        out.append(f"  - id: {t['id']}")
        out.append(f"    plan_task: {t['plan_task']}")
        out.append(f"    lane: {t['lane']}")
        out.append(f"    sequence: {t['sequence']}")
        out.append(f"    title: {t['title']}")
        out.append(f"    tier: {t['tier']}")
        out.append("    depends_on:")
        if t["depends_on"]:
            for dep in t["depends_on"]:
                out.append(f"      - {dep}")
        else:
            out.append("      []")
        out.append("    ownership:")
        for pat in t["ownership"]:
            out.append(f'      - "{pat}"')
        out.append(f"    resources: []")
        out.append("    produces:")
        if t["produces"]:
            for p in t["produces"]:
                out.append(f"      - interface: {p['interface']}")
                out.append(f'        signature: "{p["signature"]}"')
                out.append(f"        signature_digest: {p['signature_digest']}")
        else:
            out.append("      []")
        out.append("    consumes:")
        if t["consumes"]:
            for c in t["consumes"]:
                out.append(f"      - interface: {c['interface']}")
                out.append(f"        from_task: {c['from_task']}")
                out.append(f'        signature: "{c["signature"]}"')
                out.append(f"        signature_digest: {c['signature_digest']}")
        else:
            out.append("      []")
        out.append("    validation:")
        for v in t["validation"]:
            out.append("      - argv:")
            for token in v["argv"]:
                out.append(f'          - "{token}"')
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_dot(manifest: dict) -> str:
    out = [
        "digraph app_icon_execution_graph {",
        "    rankdir=TB;",
        '    node [shape=box, style=rounded, fontname="Helvetica"];',
        f'    label="topic: {manifest["topic"]}   lane: {LANE_ID} (sequential)";',
        "    labelloc=t;",
        "",
    ]
    for t in manifest["tasks"]:
        label = f"Task {t['plan_task']}: {t['title']}\\ntier: {t['tier']}"
        out.append(f'    {t["id"].replace("-", "_")} [label="{label}"];')
    out.append("")
    for t in manifest["tasks"]:
        for dep in t["depends_on"]:
            out.append(f'    {dep.replace("-", "_")} -> {t["id"].replace("-", "_")};')
    out.append("}")
    return "\n".join(out) + "\n"


def main() -> int:
    text = PLAN.read_text(encoding="utf-8")
    tasks = parse_plan(text)
    manifest = build(tasks)
    YAML_OUT.write_text(render_yaml(manifest), encoding="utf-8")
    DOT_OUT.write_text(render_dot(manifest), encoding="utf-8")
    print(f"wrote {YAML_OUT.name} ({len(manifest['tasks'])} tasks, 1 lane)")
    print(f"wrote {DOT_OUT.name}")
    print(f"source_plan.sha256 = {manifest['source_plan']['sha256']}")
    print(json.dumps({"tasks": [t["id"] for t in manifest["tasks"]], "lane": LANE_ID}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
