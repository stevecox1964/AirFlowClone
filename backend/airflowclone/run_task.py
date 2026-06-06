"""Subprocess entrypoint: runs a single task.

Invoked as: python -m airflowclone.run_task <dag_file> <task_id> <run_id>

Reads upstream task outputs from runs/<run_id>/<upstream>.json (matched by parameter
name → upstream task name), calls the task function, writes the return value as JSON
to runs/<run_id>/<task_id>.json. stdout/stderr are NOT redirected here — the parent
process captures them and tees to the log file.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from .loader import load_dag_from_file
from .paths import task_output_path
from .runtime_context import inject as inject_context, load_context


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: python -m airflowclone.run_task <dag_file> <task_id> <run_id>", file=sys.stderr)
        return 2

    dag_file = Path(sys.argv[1])
    task_id = sys.argv[2]
    run_id = sys.argv[3]

    dag = load_dag_from_file(dag_file)
    if dag is None:
        print(f"FATAL: could not load DAG from {dag_file}", file=sys.stderr)
        return 3
    if task_id not in dag.tasks:
        print(f"FATAL: task '{task_id}' not in DAG '{dag.dag_id}'", file=sys.stderr)
        return 3

    task = dag.tasks[task_id]
    print(f"[airflowclone] starting task '{task_id}' (dag={dag.dag_id}, run={run_id})", flush=True)

    kwargs = {}
    for param_name in dag.task_kwargs_for(task_id):
        if param_name not in task.depends_on:
            print(
                f"FATAL: parameter '{param_name}' on task '{task_id}' has no matching "
                f"upstream task in depends_on={task.depends_on}",
                file=sys.stderr,
            )
            return 4
        upstream_path = task_output_path(run_id, param_name)
        if not upstream_path.exists():
            print(
                f"FATAL: upstream output missing: {upstream_path}",
                file=sys.stderr,
            )
            return 5
        with open(upstream_path, "r", encoding="utf-8") as fh:
            kwargs[param_name] = json.load(fh)
        print(f"[airflowclone] loaded upstream '{param_name}' from {upstream_path}", flush=True)

    # Inject params / Variable / Connection into the DAG module's globals so the task
    # body can reference them without declaring them as function parameters.
    inject_context(task.fn.__globals__, load_context())

    try:
        result = task.fn(**kwargs)
    except Exception:
        print("[airflowclone] TASK FAILED:", file=sys.stderr)
        traceback.print_exc()
        return 1

    out_path = task_output_path(run_id, task_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, default=str, indent=2)
    except TypeError as exc:
        print(
            f"[airflowclone] task '{task_id}' returned a value that is not JSON-serializable: {exc}",
            file=sys.stderr,
        )
        return 6
    print(f"[airflowclone] task '{task_id}' completed, output -> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
