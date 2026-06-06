# Design Notes — Session 1 (2026-05-20)

Captures the reasoning behind the choices made today, for picking this back up later.

## The core insight

A DAG is not "a graph of compute steps" — it's **a waterfall of data being handed off
between nodes**. The framework's job is to move data on/off disk between subprocesses;
the actual compute is incidental.

Everything else follows from that framing.

## Decisions made and why

### Data passing — JSON files on disk, period
- **No XCom-style metadata-DB shenanigans.** XCom was designed for tiny strings/dicts and gets abused for real data. We skipped it.
- The framework calls `json.dump(return_value)` on each task's output → `runs/<run_id>/<task>.json`
- Downstream tasks declare upstream dependencies by parameter name; framework `json.load`s the matching upstream file and passes it in
- For pandas DataFrames: user calls `df.to_dict(orient="records")` themselves — explicit, inspectable, no framework magic
- For huge data: user writes their own file (parquet/csv/whatever) and returns the path as a string — framework only sees the path

Why not Parquet/Arrow/multi-format dispatch? Because the user wants inspectable artifacts (`cat extract.json` works). We can add format selection later if a real perf bottleneck shows up.

### Execution — subprocess per task
- Each task runs as `python -m airflowclone.run_task <dag_file> <task_id> <run_id>`
- True process isolation: one task crashing or hanging doesn't poison anything else
- Clean stdout/stderr capture into per-attempt log files
- Can run for hours (long-running tasks were an explicit requirement)
- Trades a small startup cost per task (~100ms on Windows) for safety
- Single machine only for baseline — distributed comes later if needed

### Retry — per-task with downstream cascade
- "Retry this task" is the killer operational feature
- When you retry a task, the framework also resets any downstream tasks marked `upstream_failed` and re-orchestrates from that point
- Already-successful upstream tasks are NOT re-run — their `.json` outputs are still on disk and reused
- This mirrors Airflow's "Clear Task" semantics, which Airflow gets right and most newer tools fumble

### API-first, UI is observability
- This engine is intended to have **two consumers**:
  1. Humans writing Python DAG files in `dags/` for their own ETL
  2. Agents (Claude via MCP, or any LLM via the REST API) composing long-running tasks on demand
- Every UI action is a documented REST endpoint
- An MCP server wrapping the REST API is a next-session item — the gap it fills is "agent gives the user proper async work orchestration with logs + partial results + retries", which is missing from current agent tooling

## What's intentionally NOT built yet

Roadmap, listed in the order they'd add the most value:

1. **File watcher** for automatic DAG reload on file change (currently uses `POST /api/reload` button)
2. **WebSocket log streaming** instead of 1s polling — better UX during long log output
3. **Cron scheduling** — the `schedule` field on `DAG()` is parsed and stored, just not yet wired to APScheduler
4. **"Retry from here" and "retry whole run"** buttons in addition to per-task retry
5. **ReactFlow graph view** of the DAG (currently a flat task list)
6. **MCP server** wrapping the REST API for agent use
7. **Larger I/O patterns** — first-class helper for "write a parquet file and return its path" if the pattern becomes common

## State at end of session

- **Backend:** `backend/airflowclone/` — 9 modules, working end-to-end
- **Frontend:** `frontend/src/` — 3 pages (DagList, DagDetail, RunDetail), 1 component (StatusBadge), full type-safe API client
- **Example DAG:** `dags/example_etl.py` — 3-task waterfall with a deliberate first-attempt flake on `transform` to exercise the retry button
- **Both servers verified live** end-to-end with a real trigger → fail → retry → cascade success flow

## To restart later

```powershell
# Backend
cd C:\Users\user\Desktop\React\AirFlowClone\backend
.\.venv\Scripts\Activate.ps1
python -m airflowclone.main

# Frontend (new terminal)
cd C:\Users\user\Desktop\React\AirFlowClone\frontend
npm run dev
```

Then open `http://localhost:5173`.

## Open questions for next session

- **Schedule semantics.** Do we want strict cron, or also `@hourly`/`@daily` shortcuts and interval-based (`every 30m`) triggers? Airflow supports all three.
- **DAG creation via API.** When wiring the MCP layer, the agent will want to define a DAG programmatically. Open question: does the API write a `.py` file to `dags/` (single source of truth), or do we store DAG-as-JSON separately and run it from a generic harness? Leaning toward "API writes a .py file" because it keeps one execution path.
- **Result retention policy.** No cleanup of old `runs/*` directories yet. Disk fills up over time. Probably want a "keep last N runs per DAG" knob.
