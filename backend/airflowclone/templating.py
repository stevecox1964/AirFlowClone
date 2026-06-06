"""DAG spec → .py file. Single source of truth for UI-authored / MCP-authored DAGs.

Spec shape (JSON):
    {
      "dag_id": "my_dag",
      "description": "optional",
      "schedule": "0 9 * * *" | null,
      "tasks": [
        {"task_id": "extract", "depends_on": [], "body": "return [1,2,3]"},
        {"task_id": "load",    "depends_on": ["extract"], "body": "print(extract)"}
      ]
    }

Function signatures are auto-derived from depends_on — each upstream task name
becomes a kwarg, matching `core.py`'s parameter-name → upstream-output convention."""
from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from typing import Any

from apscheduler.triggers.cron import CronTrigger

from .parameters import validate_param_schema

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ValidationError:
    field: str  # dotted path, e.g. "tasks[1].depends_on"
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


def _is_valid_identifier(name: str) -> bool:
    return bool(_IDENT.match(name)) and not keyword.iskeyword(name)


def validate_spec(spec: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    dag_id = spec.get("dag_id", "")
    if not dag_id:
        errors.append(ValidationError("dag_id", "required"))
    elif not _is_valid_identifier(dag_id):
        errors.append(ValidationError("dag_id", "must be a valid Python identifier"))
    elif dag_id.startswith("_"):
        # Loader convention: underscore-prefixed files are skipped (hidden DAGs).
        errors.append(ValidationError(
            "dag_id", "cannot start with underscore (reserved for hidden DAGs)"
        ))

    schedule = spec.get("schedule")
    if schedule:
        try:
            CronTrigger.from_crontab(schedule)
        except Exception as exc:
            errors.append(ValidationError("schedule", f"invalid cron: {exc}"))

    for field, message in validate_param_schema(spec.get("params")):
        errors.append(ValidationError(field, message))

    tasks = spec.get("tasks") or []
    if not tasks:
        errors.append(ValidationError("tasks", "at least one task is required"))

    seen_ids: set[str] = set()
    declared_ids: set[str] = {t.get("task_id", "") for t in tasks if isinstance(t, dict)}

    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            errors.append(ValidationError(f"tasks[{i}]", "must be an object"))
            continue
        tid = t.get("task_id", "")
        if not tid:
            errors.append(ValidationError(f"tasks[{i}].task_id", "required"))
        elif not _is_valid_identifier(tid):
            errors.append(ValidationError(
                f"tasks[{i}].task_id", "must be a valid Python identifier"
            ))
        elif tid in seen_ids:
            errors.append(ValidationError(
                f"tasks[{i}].task_id", f"duplicate task_id '{tid}'"
            ))
        else:
            seen_ids.add(tid)

        deps = t.get("depends_on") or []
        if not isinstance(deps, list):
            errors.append(ValidationError(f"tasks[{i}].depends_on", "must be a list"))
        else:
            for dep in deps:
                if dep not in declared_ids:
                    errors.append(ValidationError(
                        f"tasks[{i}].depends_on",
                        f"unknown task '{dep}'",
                    ))
                elif dep == tid:
                    errors.append(ValidationError(
                        f"tasks[{i}].depends_on", "task cannot depend on itself"
                    ))

    if not errors and _has_cycle(tasks):
        errors.append(ValidationError("tasks", "dependency cycle detected"))

    return errors


def _has_cycle(tasks: list[dict[str, Any]]) -> bool:
    graph = {t["task_id"]: list(t.get("depends_on") or []) for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in graph}

    def visit(tid: str) -> bool:
        color[tid] = GRAY
        for dep in graph.get(tid, []):
            if color.get(dep) == GRAY:
                return True
            if color.get(dep) == WHITE and visit(dep):
                return True
        color[tid] = BLACK
        return False

    return any(color[t] == WHITE and visit(t) for t in graph)


def _indent_body(body: str, indent: str = "    ") -> str:
    body = (body or "").strip("\n")
    if not body.strip():
        return f"{indent}pass"
    return "\n".join(indent + line if line.strip() else "" for line in body.splitlines())


def _py_str(s: str | None) -> str:
    return repr(s) if s is not None else "None"


def render_dag_py(spec: dict[str, Any]) -> str:
    """Render a spec to .py source. Caller is responsible for validation."""
    dag_id = spec["dag_id"]
    description = spec.get("description") or None
    schedule = spec.get("schedule") or None
    params = spec.get("params") or []
    tasks = spec.get("tasks") or []

    lines: list[str] = [
        "# AUTO-GENERATED by AirFlowClone UI. Re-running the form will be rejected",
        "# if this file still exists; delete it first or pick a different dag_id.",
        "from __future__ import annotations",
        "",
        "from airflowclone import DAG",
        "",
        "dag = DAG(",
        f"    dag_id={_py_str(dag_id)},",
    ]
    if description is not None:
        lines.append(f"    description={_py_str(description)},")
    if schedule is not None:
        lines.append(f"    schedule={_py_str(schedule)},")
    if params:
        lines.append("    params=[")
        for p in params:
            clean = {"name": p["name"], "type": p.get("type", "str")}
            if p.get("default") is not None:
                clean["default"] = p["default"]
            if p.get("required"):
                clean["required"] = True
            lines.append(f"        {clean!r},")
        lines.append("    ],")
    lines += [")", ""]

    for t in tasks:
        tid = t["task_id"]
        deps = list(t.get("depends_on") or [])
        if deps:
            deps_repr = ", ".join(repr(d) for d in deps)
            lines.append(f"@dag.task(depends_on=[{deps_repr}])")
        else:
            lines.append("@dag.task")
        sig = ", ".join(deps)
        lines.append(f"def {tid}({sig}):")
        lines.append(_indent_body(t.get("body", "")))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
