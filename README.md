# AirFlowClone

A modern, local-first DAG engine for long-running Python tasks. Web UI + REST API.

## What it is

- **DAG-style workflows** — declare tasks and dependencies in Python, run them in topological order
- **Data passes between nodes as JSON files on disk** — `runs/<run_id>/<task>.json`. No XCom, no metadata DB abuse. For huge data, write a file yourself and return its path.
- **Discrete log per task attempt** — `runs/<run_id>/<task>.<attempt>.log`. Preserved across retries.
- **Per-task retry as a first-class action** — re-run any single node; downstream tasks blocked as `upstream_failed` are cascaded automatically.
- **Subprocess-per-task** — process isolation, clean stdout/stderr capture, can run for hours.
- **API-first** — every UI action is a documented REST endpoint. Intended to be drivable by agents (MCP/HTTP) as well as humans.

## Stack

- **Backend** — FastAPI · SQLAlchemy 2.0 · SQLite · subprocess executor · APScheduler (planned, not yet wired)
- **Frontend** — Vite · React 19 · TypeScript · Tailwind v4 · TanStack Query · React Router
- **Single machine, no broker, no Celery.**

## Quick start

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m airflowclone.main
```

Serves at `http://127.0.0.1:8000`.

### 2. Frontend (new terminal)

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 3. Try the demo

1. The shipped DAG (`dags/example_etl.py`) appears in the list — three tasks: `extract → transform → load`
2. Click **trigger run**
3. Watch `extract` succeed, then `transform` fail on its first attempt (intentional — simulates a transient error)
4. `load` is marked `upstream_failed` and does not run
5. Click on `transform` in the run detail view, then click **retry this task**
6. `transform` reruns and succeeds; `load` cascades and runs automatically; the whole run flips to `success`

The output of `load` (a small JSON summary) is visible in the right pane.

## Writing your own DAG

Drop a `.py` file into `dags/` and click **rescan dags/** in the UI (or restart the server).

```python
from airflowclone import DAG

dag = DAG(
    dag_id="my_pipeline",
    description="Whatever you want here",
)

@dag.task
def step1() -> list[dict]:
    return [{"id": i} for i in range(3)]

@dag.task(depends_on=["step1"])
def step2(step1: list[dict]) -> dict:
    return {"count": len(step1)}
```

**Rules:**
- Define exactly one `DAG` instance at module scope
- Decorate task functions with `@dag.task` (no args) or `@dag.task(depends_on=[...])`
- Function parameter names must match the names of upstream tasks declared in `depends_on`
- Return values must be JSON-serializable (`json.dump` is called on them directly). For DataFrames, do `df.to_dict(orient="records")` yourself. For huge data, write to a file and return the path.

## Layout

```
AirFlowClone/
├── backend/
│   ├── pyproject.toml
│   └── airflowclone/
│       ├── api.py          # FastAPI routes
│       ├── core.py         # DAG, @task decorator
│       ├── db.py           # SQLAlchemy engine
│       ├── models.py       # Dag, DagRun, TaskInstance
│       ├── loader.py       # scans dags/ folder
│       ├── executor.py     # orchestrator + retry cascade
│       ├── run_task.py     # subprocess entrypoint
│       ├── paths.py        # filesystem helpers
│       └── main.py         # uvicorn launcher
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── types.ts
│       ├── pages/
│       │   ├── DagList.tsx
│       │   ├── DagDetail.tsx
│       │   └── RunDetail.tsx
│       └── components/StatusBadge.tsx
├── dags/                   # drop user DAG files here
│   └── example_etl.py
├── runs/                   # per-run outputs + logs (created at runtime)
└── airflowclone.db         # SQLite (created at runtime)
```

## REST API (current)

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/dags` | list DAGs |
| `GET` | `/api/dags/{dag_id}` | one DAG with task list + parse error if any |
| `POST` | `/api/reload` | rescan `dags/` folder |
| `GET` | `/api/dags/{dag_id}/runs` | list runs for a DAG (newest first) |
| `POST` | `/api/dags/{dag_id}/runs` | trigger a new run |
| `GET` | `/api/runs/{run_id}` | run + all task instances |
| `POST` | `/api/runs/{run_id}/tasks/{task_id}/retry` | retry one task (cascades downstream) |
| `GET` | `/api/runs/{run_id}/tasks/{task_id}/log?attempt=N` | full log for a task attempt |
| `GET` | `/api/runs/{run_id}/tasks/{task_id}/output` | parsed JSON output of a task |

## Roadmap

This is a **walking skeleton** — proves the architecture end-to-end. Next steps when you want them:

- File watcher for automatic DAG reload (currently uses POST `/api/reload`)
- Cron scheduling (`schedule="@hourly"` already accepted; just needs APScheduler wiring)
- WebSocket log streaming (currently 1s polling on running tasks)
- ReactFlow graph view of the DAG
- "Retry from here" and "retry whole run" buttons
- MCP server wrapping the REST API for agent use
