#!/usr/bin/env python3
"""Derive the supervisor-auto-start execution manifest and DOT graph.

Deterministic: reads the committed plan bytes, takes the source-plan SHA-256 from
them, and emits both artifacts. The YAML manifest is the canonical scheduling
source; the DOT graph is an inspection artifact generated from the manifest plus
the parsed plan headers (titles and tiers come from the plan, not from this file).

Usage:
    PYTHONPATH= python3 docs/superpowers/plans/derive_supervisor_auto_start_execution_graph.py
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = REPO_ROOT / "docs/superpowers/plans/2026-10-17-supervisor-auto-start.md"
YAML_PATH = PLAN_PATH.with_suffix(".execution-graph.yaml")
DOT_PATH = PLAN_PATH.with_suffix(".execution-graph.dot")

TOPIC_SLUG = "supervisor-auto-start"
EPOCH = 1
PYTHON = "/home/henry-arch/anaconda3/envs/daily/bin/python"
WORKSPACE = "/data/home/henry/Development/ai"

# Lane ownership, ordered by lane id. Every path is repository-relative POSIX.
LANES = [
    {
        "id": "fixtures",
        "owns": ["tests/__init__.py", "tests/helpers.py", "tests/conftest.py"],
        "task_ids": ["T-001"],
    },
    {
        "id": "supervisor",
        "owns": ["src/ai_manager/services/supervisor.py", "tests/test_supervisor_autostart.py"],
        "task_ids": ["T-002", "T-004"],
    },
    {
        "id": "window",
        "owns": ["src/ai_manager/ui/main_window.py", "tests/test_main_window_autostart.py"],
        "task_ids": ["T-003"],
    },
]

INTERFACES = {
    "IF-001": (
        "T-001",
        "tests/helpers.py: FakeStatusProcess(state() -> QProcess.ProcessState, "
        "start(program: str, args: list[str] | None = None) -> None, finish() -> None, "
        "starts: list[list[str]]); install_fake_status_process(original_init) -> wrapper; "
        "tests/conftest.py: autouse _disable_supervisor_autostart, "
        "_no_destructive_supervisor_commands, _no_real_status_probe, and "
        "autostart_enabled; module-level AUTOSTART_DISABLE_ENV re-exported from supervisor",
    ),
    "IF-002": (
        "T-002",
        "SupervisorManager: _autostart_consumed: ClassVar[bool] = False; "
        "_autostart_cancel_epoch: ClassVar[int] = 0; self._autostart_epoch: Optional[int]; "
        "@staticmethod autostart_disabled() -> bool; start_if_not_running() -> bool; "
        "cancel_pending_autostart() -> None; claim_is_live() -> bool; "
        "_spawn_supervisor(command: str, *, silent: bool) -> bool; start_supervisor() -> None; "
        "stop_supervisor() -> None; _on_status_finished(exit_code: int, exit_status) -> None; "
        "_on_status_error(error) -> None",
    ),
    "IF-003": (
        "T-003",
        "MainWindow.__init__ calls supervisor_manager.start_if_not_running() once and connects "
        "QApplication.instance().aboutToQuit to cancel_pending_autostart; "
        "_exit_application() calls cancel_pending_autostart() first; "
        "_on_supervisor_btn_clicked() calls start_supervisor() once",
    ),
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_plan(plan_text: str) -> list[dict]:
    """Extract task headers, tiers, and Files/validation info from the plan."""
    tasks: list[dict] = []
    current: dict | None = None
    for line in plan_text.splitlines():
        m = re.match(r"^## Task (\d+): (.+)$", line)
        if m:
            current = {"number": int(m.group(1)), "title": m.group(2).strip()}
            tasks.append(current)
            continue
        if current is None:
            continue
        m = re.match(r"^\*\*Implementer tier:\*\* (\w+)$", line)
        if m:
            current["tier"] = m.group(1).lower()
    return tasks


def build_manifest(plan_text: str, commit_oid: str) -> dict:
    parsed = parse_plan(plan_text)
    plan_sha = digest(plan_text)

    by_number = {t["number"]: t for t in parsed}
    assert sorted(by_number) == [1, 2, 3, 4], f"unexpected task numbers: {sorted(by_number)}"

    def task(tid, plan_task, lane, sequence, depends_on, owns, resources, produces, consumes, test):
        src = by_number[plan_task]
        return {
            "id": tid,
            "plan_task": plan_task,
            "title": src["title"],
            "tier": src["tier"],
            "lane": lane,
            "sequence": sequence,
            "depends_on": depends_on,
            "owns": owns,
            "resources": resources,
            "produces": produces,
            "consumes": consumes,
            "validation": [
                {
                    "argv": [PYTHON, "-m", "pytest", test, "-q"],
                    "cwd": ".",
                    "env": {"PYTHONPATH": "src", "AI_WORKSPACE_ROOT": WORKSPACE},
                    "timeout_seconds": 900,
                }
            ],
        }

    tasks = [
        task(
            "T-001", 1, "fixtures", 1, [], LANES[0]["owns"], [], ["IF-001"], [],
            "tests/test_main_window.py",
        ),
        task(
            "T-002", 2, "supervisor", 1, ["T-001"], LANES[1]["owns"], [], ["IF-002"], ["IF-001"],
            "tests/test_supervisor_autostart.py",
        ),
        task(
            "T-003", 3, "window", 1, ["T-002"], LANES[2]["owns"], [], ["IF-003"],
            ["IF-001", "IF-002"], "tests/test_main_window_autostart.py",
        ),
        task(
            "T-004", 4, "supervisor", 2, ["T-002", "T-003"], LANES[1]["owns"], [], [],
            ["IF-001", "IF-002", "IF-003"], "tests/",
        ),
    ]

    produces = {"produces": [
        {"id": iid, "producer": producer, "signature": signature, "sha256": digest(signature)}
        for iid, (producer, signature) in INTERFACES.items()
    ]}
    consumes = {"consumes": [
        {"id": iid, "consumers": consumers, "signature": signature, "sha256": digest(signature)}
        for iid, consumers, signature in [
            ("IF-001", ["T-002", "T-003", "T-004"], INTERFACES["IF-001"][1]),
            ("IF-002", ["T-003", "T-004"], INTERFACES["IF-002"][1]),
            ("IF-003", ["T-004"], INTERFACES["IF-003"][1]),
        ]
    ]}

    manifest = {
        "source_plan": {
            "path": "docs/superpowers/plans/2026-10-17-supervisor-auto-start.md",
            "sha256": plan_sha,
            "commit_oid": commit_oid,
        },
        "topic_slug": TOPIC_SLUG,
        "epoch": EPOCH,
        "lanes": LANES,
        "tasks": tasks,
        "interfaces": {**produces, **consumes},
    }
    return manifest


def to_yaml(manifest: dict) -> str:
    """Tiny deterministic YAML emitter (no third-party dependency)."""
    def scalar(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if value is None:
            return "null"
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return json.dumps(value, ensure_ascii=False)

    out: list[str] = []
    out.append("# PM execution manifest for the supervisor-auto-start plan (epoch 1).")
    out.append("# Derived by the PM from the validated source plan; never hand-edited.")
    out.append("source_plan:")
    for k in ("path", "sha256", "commit_oid"):
        out.append(f"  {k}: {scalar(manifest['source_plan'][k])}")
    out.append(f"topic_slug: {scalar(manifest['topic_slug'])}")
    out.append(f"epoch: {manifest['epoch']}")
    out.append("lanes:")
    for lane in manifest["lanes"]:
        out.append(f"  - id: {lane['id']}")
        out.append(f"    owns: {scalar(lane['owns'])}")
        out.append(f"    task_ids: {scalar(lane['task_ids'])}")
    out.append("tasks:")
    for task in manifest["tasks"]:
        out.append(f"  - id: {task['id']}")
        out.append(f"    plan_task: {task['plan_task']}")
        out.append(f"    title: {scalar(task['title'])}")
        out.append(f"    tier: {task['tier']}")
        out.append(f"    lane: {task['lane']}")
        out.append(f"    sequence: {task['sequence']}")
        out.append(f"    depends_on: {scalar(task['depends_on'])}")
        out.append(f"    owns: {scalar(task['owns'])}")
        out.append(f"    resources: {scalar(task['resources'])}")
        out.append(f"    produces: {scalar(task['produces'])}")
        out.append(f"    consumes: {scalar(task['consumes'])}")
        out.append("    validation:")
        for v in task["validation"]:
            out.append(f"      - argv: {scalar(v['argv'])}")
            out.append(f"        cwd: {scalar(v['cwd'])}")
            out.append(f"        env: {json.dumps(v['env'])}")
            out.append(f"        timeout_seconds: {v['timeout_seconds']}")
    out.append("interfaces:")
    out.append("  produces:")
    for item in manifest["interfaces"]["produces"]:
        out.append(f"    - id: {item['id']}")
        out.append(f"      producer: {item['producer']}")
        out.append(f"      signature: {scalar(item['signature'])}")
        out.append(f"      sha256: {item['sha256']}")
    out.append("  consumes:")
    for item in manifest["interfaces"]["consumes"]:
        out.append(f"    - id: {item['id']}")
        out.append(f"      consumers: {scalar(item['consumers'])}")
        out.append(f"      signature: {scalar(item['signature'])}")
        out.append(f"      sha256: {item['sha256']}")
    return "\n".join(out) + "\n"


def to_dot(manifest: dict) -> str:
    tasks = {t["id"]: t for t in manifest["tasks"]}
    lines = [
        "// Derived from the execution-graph.yaml manifest; inspection artifact only.",
        f"// topic: {manifest['topic_slug']}  epoch: {manifest['epoch']}",
        f"// source_plan sha256: {manifest['source_plan']['sha256']}",
        "digraph supervisor_auto_start {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica"];',
        '  edge [fontname="Helvetica"];',
    ]
    lane_colors = {"fixtures": "#e8f4ea", "supervisor": "#e8eef9", "window": "#fdf1e3"}
    for lane in manifest["lanes"]:
        lines.append(f'  subgraph cluster_{lane["id"]} {{')
        lines.append(f'    label="lane: {lane["id"]}";')
        lines.append(f'    style="rounded,dashed"; color="#999999";')
        for tid in lane["task_ids"]:
            t = tasks[tid]
            label = f'{tid}\\nplan task {t["plan_task"]}\\n{t["title"].replace(chr(34), chr(39))}\\ntier: {t["tier"]}'
            color = lane_colors.get(lane["id"], "#ffffff")
            lines.append(f'    "{tid}" [label="{label}", fillcolor="{color}"];')
        lines.append("  }")
    lines.append("")
    for t in manifest["tasks"]:
        for dep in t["depends_on"]:
            label = "same-lane" if tasks[dep]["lane"] == t["lane"] else "interface"
            lines.append(f'  "{dep}" -> "{t["id"]}" [label="{label}"];')
    lines.append("")
    for item in manifest["interfaces"]["produces"]:
        for consumer in next(
            (c["consumers"] for c in manifest["interfaces"]["consumes"] if c["id"] == item["id"]),
            [],
        ):
            style = "" if consumer != item["producer"] else " [style=dotted]"
            lines.append(
                f'  "{item["producer"]}" -> "{consumer}" '
                f'[label="{item["id"]}", color="#5b7ea8", style=dashed]{style};'
            )
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    plan_text = PLAN_PATH.read_text(encoding="utf-8")
    # Resolve the commit OID of the plan's last modification.
    import subprocess

    commit_oid = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%H", "--", str(PLAN_PATH.relative_to(REPO_ROOT))],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    manifest = build_manifest(plan_text, commit_oid)
    YAML_PATH.write_text(to_yaml(manifest), encoding="utf-8")
    DOT_PATH.write_text(to_dot(manifest), encoding="utf-8")
    print(f"wrote {YAML_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {DOT_PATH.relative_to(REPO_ROOT)}")
    print(f"source_plan sha256: {manifest['source_plan']['sha256']}")


if __name__ == "__main__":
    main()
