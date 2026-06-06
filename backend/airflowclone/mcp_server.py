"""MCP server for AirFlowClone — lets an LLM read the existing workflow library and
author/run new workflows by chatting.

It is a THIN client over the running REST engine (httpx → AFC_API_URL, default
http://127.0.0.1:8000). The engine must be running (`python -m airflowclone.main`).
This indirection is deliberate: runs you trigger keep executing inside the persistent
engine even after the chat session ends — true fire-and-forget.

--- The DAG model the LLM must follow when authoring ---
A DAG is a set of tasks with dependencies — a waterfall of data handed task to task.
* Each task has a `body` of plain Python (the function body only; the engine generates
  the `def` line from `depends_on`).
* A task receives each upstream task's output as a variable named after that upstream
  task_id. Every such name MUST appear in the task's `depends_on`.
* The body returns a JSON-serializable value — that becomes the task's output and is
  passed to downstream tasks (for DataFrames, return `df.to_dict(orient="records")`;
  for big files, write the file and return a metadata dict).
* The body also has these injected in scope (no import needed):
    - params.get("name")        per-run inputs (declared in `params`)
    - Variable.get("key")       global config / secrets
    - Connection.get("conn_id") structured credentials (.host/.login/.password/...)
* `depends_on` must reference declared task_ids; cycles are rejected.
Read existing DAGs with get_dag (returns each task's Python) to learn the patterns
before composing new ones.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

API_URL = os.environ.get("AFC_API_URL", "http://127.0.0.1:8000").rstrip("/")

mcp = FastMCP("airflowclone")


# ---- spec models (mirror the REST DagSpec; give the LLM a clear input schema) ----

class TaskSpec(BaseModel):
    task_id: str = Field(description="valid Python identifier, unique within the DAG")
    depends_on: list[str] = Field(
        default=[], description="upstream task_ids; each becomes a variable in the body"
    )
    body: str = Field(default="", description="Python function body; should `return` a JSON value")


class ParamSpec(BaseModel):
    name: str = Field(description="valid Python identifier")
    type: str = Field(default="str", description="one of: str, int, float, bool")
    default: Optional[Any] = Field(default=None, description="omit for no default")
    required: bool = Field(default=False)


# ---- http helper ----

def _req(method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
    try:
        r = httpx.request(method, f"{API_URL}{path}", json=json, params=params, timeout=60)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot reach the AirFlowClone engine at {API_URL}. Start it with "
            f"`python -m airflowclone.main` (uvicorn on :8000)."
        ) from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    if r.status_code == 204 or not r.content:
        return {"ok": True}
    return r.json()


def _spec(
    dag_id: str,
    tasks: list[TaskSpec],
    description: str,
    schedule: str,
    params: list[ParamSpec],
) -> dict:
    return {
        "dag_id": dag_id,
        "description": description or None,
        "schedule": schedule or None,
        "params": [p.model_dump() for p in params],
        "tasks": [t.model_dump() for t in tasks],
    }


# ---- read tools (the "library") ----

@mcp.tool()
def list_dags() -> list[dict]:
    """List all DAGs with their id, description, schedule, tasks, param schema, and
    paused/parse-error state. The starting point for understanding the library."""
    return _req("GET", "/api/dags")


@mcp.tool()
def get_dag(dag_id: str) -> dict:
    """Full detail of one DAG: its summary, its raw .py source, and (if UI-authored)
    its editable spec with each task's Python body. Use this to read existing tasks
    and functions before composing a new workflow."""
    out: dict[str, Any] = {"summary": _req("GET", f"/api/dags/{dag_id}")}
    out["source"] = _req("GET", f"/api/dags/{dag_id}/source").get("source")
    try:
        out["spec"] = _req("GET", f"/api/dags/{dag_id}/spec")
    except RuntimeError:
        out["spec"] = None  # hand-authored DAG: no editable spec, source is above
    return out


@mcp.tool()
def recent_runs(limit: int = 20, status: Optional[str] = None) -> list[dict]:
    """Recent runs across ALL DAGs, newest first — the entry point when you've been away
    (e.g. the engine kept running after CC was closed). Use this to discover what ran and
    its outcome without already knowing a dag_id or run_id, then drill in with get_run /
    get_task_output. Optional `status` filter: running, success, failed, pending."""
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    return _req("GET", "/api/runs", params=params)


@mcp.tool()
def list_runs(dag_id: str) -> list[dict]:
    """Run history for ONE DAG (newest first): status, trigger type, params used, times.
    For runs across the whole library, use recent_runs."""
    return _req("GET", f"/api/dags/{dag_id}/runs")


@mcp.tool()
def get_run(run_id: str) -> dict:
    """A run's status plus per-task status/attempt/error. For a single status check.
    To wait for completion instead of polling yourself, use wait_for_run."""
    return _req("GET", f"/api/runs/{run_id}")


@mcp.tool()
def wait_for_run(
    run_id: str, timeout_seconds: float = 30.0, poll_interval: float = 1.5
) -> dict:
    """Block until a run finishes, then return it — the "callback" for chat. After
    trigger_run, call wait_for_run(run_id) instead of polling get_run in a loop.

    Returns the same shape as get_run, plus a `waited` flag:
      * waited=true  -> the run reached a terminal status (success/failed); you're done.
      * waited=false -> the timeout elapsed and the run is still pending/running. The
        run keeps executing in the engine — just call wait_for_run(run_id) again.
    timeout_seconds is capped at 55s so the tool call returns before the MCP client's
    own timeout; raise it toward that cap for long jobs, or call again to keep waiting."""
    timeout_seconds = max(1.0, min(float(timeout_seconds), 55.0))
    poll_interval = max(0.25, min(float(poll_interval), 10.0))
    terminal = {"success", "failed"}
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = _req("GET", f"/api/runs/{run_id}")
        if run.get("status") in terminal:
            run["waited"] = True
            return run
        if time.monotonic() >= deadline:
            run["waited"] = False
            return run
        time.sleep(poll_interval)


@mcp.tool()
def get_task_output(run_id: str, task_id: str) -> dict:
    """The JSON output a task produced in a run ({present, value})."""
    return _req("GET", f"/api/runs/{run_id}/tasks/{task_id}/output")


@mcp.tool()
def get_task_log(run_id: str, task_id: str, attempt: Optional[int] = None) -> dict:
    """A task attempt's captured stdout/stderr log (secrets already redacted)."""
    params = {"attempt": attempt} if attempt is not None else None
    return _req("GET", f"/api/runs/{run_id}/tasks/{task_id}/log", params=params)


@mcp.tool()
def list_variables() -> list[dict]:
    """Global Variables available to tasks via Variable.get(). Secret values are masked
    (value=null) — you can reference a secret by key without seeing it."""
    return _req("GET", "/api/variables")


@mcp.tool()
def list_connections() -> list[dict]:
    """Connections available to tasks via Connection.get(). Passwords are never returned
    (has_password flag only)."""
    return _req("GET", "/api/connections")


# ---- author / run tools ----

@mcp.tool()
def preview_dag(
    dag_id: str,
    tasks: list[TaskSpec],
    description: str = "",
    schedule: str = "",
    params: list[ParamSpec] = [],
) -> dict:
    """Validate a workflow spec and return the .py source that WOULD be generated,
    plus any validation errors — without creating anything. Use this to check a draft
    before create_dag."""
    return _req("POST", "/api/dags/preview", json=_spec(dag_id, tasks, description, schedule, params))


@mcp.tool()
def create_dag(
    dag_id: str,
    tasks: list[TaskSpec],
    description: str = "",
    schedule: str = "",
    params: list[ParamSpec] = [],
) -> dict:
    """Create a new workflow. Writes dags/<dag_id>.py and registers it. Fails if the
    dag_id already exists or the spec is invalid (call preview_dag first if unsure).
    `schedule` is an optional cron string; omit for manual-only."""
    return _req("POST", "/api/dags", json=_spec(dag_id, tasks, description, schedule, params))


@mcp.tool()
def update_dag(
    dag_id: str,
    tasks: list[TaskSpec],
    description: str = "",
    schedule: str = "",
    params: list[ParamSpec] = [],
) -> dict:
    """Replace a UI/MCP-authored DAG's definition (full spec). Renames are not allowed;
    hand-authored DAGs cannot be edited this way."""
    return _req("PUT", f"/api/dags/{dag_id}", json=_spec(dag_id, tasks, description, schedule, params))


@mcp.tool()
def delete_dag(dag_id: str) -> dict:
    """Delete a DAG: removes its .py file, DB row, and run history. runs/ artifacts on
    disk are preserved."""
    return _req("DELETE", f"/api/dags/{dag_id}")


@mcp.tool()
def trigger_run(dag_id: str, params: Optional[dict] = None) -> dict:
    """Start a run (fire-and-forget — returns a run_id immediately; the engine executes
    it in the background). `params` supplies this DAG's Run Param values; required params
    with no default must be provided. Poll get_run(run_id) for status."""
    return _req("POST", f"/api/dags/{dag_id}/runs", json={"params": params or {}})


@mcp.tool()
def retry_task(run_id: str, task_id: str) -> dict:
    """Re-run a single task (and any downstream tasks blocked by it) within an existing
    run. Mirrors Airflow's Clear Task."""
    return _req("POST", f"/api/runs/{run_id}/tasks/{task_id}/retry")


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
