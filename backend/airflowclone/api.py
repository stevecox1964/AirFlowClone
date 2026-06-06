"""FastAPI routes — primary surface of the engine."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, desc

from . import scheduler
from .db import SessionLocal, init_db
from .executor import retry_task, trigger_run
from .loader import invalidate_cache, scan_and_register
from .models import Connection, Dag as DagRow, DagRun, TaskInstance, Variable, utcnow
from .parameters import is_identifier
from .paths import DAGS_DIR, task_log_path, task_output_path
from .templating import ValidationError, render_dag_py, validate_spec


class DagSummary(BaseModel):
    dag_id: str
    description: Optional[str]
    schedule: Optional[str]
    is_paused: bool
    next_run_at: Optional[str]
    parse_error: Optional[str]
    is_ui_editable: bool
    tasks: list[dict[str, Any]]
    params: list[dict[str, Any]]  # Run Param schema


class TaskSpec(BaseModel):
    task_id: str
    depends_on: list[str] = []
    body: str = ""


class ParamSpec(BaseModel):
    name: str
    type: str = "str"  # str | int | float | bool
    default: Optional[Any] = None
    required: bool = False


class DagSpec(BaseModel):
    dag_id: str
    description: Optional[str] = None
    schedule: Optional[str] = None
    params: list[ParamSpec] = []
    tasks: list[TaskSpec] = []


class ValidationErrorOut(BaseModel):
    field: str
    message: str


class PreviewResponse(BaseModel):
    source: str
    errors: list[ValidationErrorOut]


class TaskInstanceOut(BaseModel):
    task_id: str
    status: str
    attempt: int
    started_at: Optional[str]
    finished_at: Optional[str]
    error: Optional[str]


class RunSummary(BaseModel):
    id: str
    dag_id: str
    status: str
    trigger_type: str
    params: dict[str, Any] = {}
    started_at: Optional[str]
    finished_at: Optional[str]


class RunDetail(RunSummary):
    tasks: list[TaskInstanceOut]


class TriggerRequest(BaseModel):
    params: dict[str, Any] = {}


class VariableIn(BaseModel):
    value: str
    is_secret: bool = False
    description: Optional[str] = None


class VariableOut(BaseModel):
    key: str
    value: Optional[str]  # None when secret (masked)
    is_secret: bool
    description: Optional[str]
    updated_at: Optional[str]


class ConnectionIn(BaseModel):
    conn_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    login: Optional[str] = None
    # None = leave existing password unchanged; "" = clear it; otherwise set it.
    password: Optional[str] = None
    extra: Optional[str] = None
    description: Optional[str] = None


class ConnectionOut(BaseModel):
    conn_id: str
    conn_type: Optional[str]
    host: Optional[str]
    port: Optional[int]
    login: Optional[str]
    has_password: bool
    extra: Optional[str]
    description: Optional[str]
    updated_at: Optional[str]


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    scan_and_register()
    scheduler.start()
    scheduler.sync_from_db()
    try:
        yield
    finally:
        scheduler.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="AirFlowClone", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/reload")
    def reload_dags() -> dict:
        invalidate_cache()
        result = scan_and_register()
        scheduler.sync_from_db()
        return result

    def _dag_summary(r: DagRow) -> DagSummary:
        return DagSummary(
            dag_id=r.dag_id,
            description=r.description,
            schedule=r.schedule,
            is_paused=bool(r.is_paused),
            next_run_at=_iso(r.next_run_at),
            parse_error=r.parse_error,
            is_ui_editable=r.spec_json is not None,
            tasks=json.loads(r.tasks_json or "[]"),
            params=json.loads(r.params_json or "[]"),
        )

    @app.get("/api/dags", response_model=list[DagSummary])
    def list_dags() -> list[DagSummary]:
        with SessionLocal() as session:
            rows = session.execute(select(DagRow).order_by(DagRow.dag_id)).scalars().all()
            return [_dag_summary(r) for r in rows]

    @app.get("/api/dags/{dag_id}", response_model=DagSummary)
    def get_dag_route(dag_id: str) -> DagSummary:
        with SessionLocal() as session:
            r = session.get(DagRow, dag_id)
            if r is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            return _dag_summary(r)

    @app.post("/api/dags/preview", response_model=PreviewResponse)
    def preview_dag(spec: DagSpec) -> PreviewResponse:
        spec_dict = spec.model_dump()
        errors = validate_spec(spec_dict)
        try:
            source = render_dag_py(spec_dict)
        except Exception as exc:
            source = ""
            errors.append(ValidationError("template", f"render failed: {exc}"))
        return PreviewResponse(
            source=source,
            errors=[ValidationErrorOut(**e.to_dict()) for e in errors],
        )

    @app.post("/api/dags", response_model=DagSummary, status_code=201)
    def create_dag(spec: DagSpec) -> DagSummary:
        spec_dict = spec.model_dump()
        errors = validate_spec(spec_dict)
        if errors:
            raise HTTPException(
                400,
                {"message": "spec validation failed",
                 "errors": [e.to_dict() for e in errors]},
            )
        DAGS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = DAGS_DIR / f"{spec.dag_id}.py"
        if file_path.exists():
            raise HTTPException(409, f"dags/{spec.dag_id}.py already exists")
        with SessionLocal() as session:
            if session.get(DagRow, spec.dag_id) is not None:
                raise HTTPException(409, f"dag '{spec.dag_id}' already registered")
        source = render_dag_py(spec_dict)
        file_path.write_text(source, encoding="utf-8")
        invalidate_cache()
        scan_and_register()
        scheduler.sync_from_db()
        with SessionLocal() as session:
            row = session.get(DagRow, spec.dag_id)
            if row is None:
                # Should not happen — scan succeeded but DAG missing. Clean up.
                file_path.unlink(missing_ok=True)
                raise HTTPException(500, "DAG was created but failed to register")
            if row.parse_error:
                file_path.unlink(missing_ok=True)
                session.delete(row)
                session.commit()
                raise HTTPException(400, {
                    "message": "generated DAG failed to parse",
                    "parse_error": row.parse_error,
                })
            row.spec_json = json.dumps(spec_dict)
            session.commit()
            return _dag_summary(row)

    @app.get("/api/dags/{dag_id}/source")
    def get_dag_source(dag_id: str) -> dict:
        """Raw .py source of a DAG — works for hand- and UI-authored alike, so an
        LLM can read existing tasks/functions as library examples."""
        with SessionLocal() as session:
            r = session.get(DagRow, dag_id)
            if r is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            path = Path(r.file_path)
        if not path.exists():
            raise HTTPException(404, f"source file missing for '{dag_id}'")
        return {"dag_id": dag_id, "source": path.read_text(encoding="utf-8")}

    @app.get("/api/dags/{dag_id}/spec", response_model=DagSpec)
    def get_dag_spec(dag_id: str) -> DagSpec:
        with SessionLocal() as session:
            r = session.get(DagRow, dag_id)
            if r is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            if r.spec_json is None:
                raise HTTPException(
                    404, f"dag '{dag_id}' was not authored in the UI — not editable here"
                )
            return DagSpec(**json.loads(r.spec_json))

    @app.put("/api/dags/{dag_id}", response_model=DagSummary)
    def update_dag(dag_id: str, spec: DagSpec) -> DagSummary:
        if spec.dag_id != dag_id:
            raise HTTPException(
                400,
                f"dag_id mismatch: path='{dag_id}' body='{spec.dag_id}' (renames not supported)",
            )
        with SessionLocal() as session:
            existing = session.get(DagRow, dag_id)
            if existing is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            if existing.spec_json is None:
                raise HTTPException(
                    409, f"dag '{dag_id}' was hand-authored; edit the .py file directly"
                )
        spec_dict = spec.model_dump()
        errors = validate_spec(spec_dict)
        if errors:
            raise HTTPException(
                400,
                {"message": "spec validation failed",
                 "errors": [e.to_dict() for e in errors]},
            )
        file_path = DAGS_DIR / f"{dag_id}.py"
        source = render_dag_py(spec_dict)
        file_path.write_text(source, encoding="utf-8")
        invalidate_cache()
        scan_and_register()
        scheduler.sync_from_db()
        with SessionLocal() as session:
            row = session.get(DagRow, dag_id)
            if row is None:
                raise HTTPException(500, "DAG vanished after update")
            if row.parse_error:
                # Generated file is broken — surface error but DON'T revert; the user's
                # spec is the source of truth and they may want to fix-forward.
                raise HTTPException(400, {
                    "message": "generated DAG failed to parse",
                    "parse_error": row.parse_error,
                })
            row.spec_json = json.dumps(spec_dict)
            session.commit()
            return _dag_summary(row)

    @app.delete("/api/dags/{dag_id}/runs")
    def clear_dag_runs(dag_id: str) -> dict:
        """Remove all DagRun + TaskInstance rows for this DAG. Preserves runs/ on disk."""
        with SessionLocal() as session:
            if session.get(DagRow, dag_id) is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            run_ids = [
                r for (r,) in session.execute(
                    select(DagRun.id).where(DagRun.dag_id == dag_id)
                )
            ]
            if not run_ids:
                return {"deleted_runs": 0}
            session.execute(
                TaskInstance.__table__.delete().where(
                    TaskInstance.run_id.in_(run_ids)
                )
            )
            session.execute(
                DagRun.__table__.delete().where(DagRun.dag_id == dag_id)
            )
            session.commit()
            return {"deleted_runs": len(run_ids)}

    @app.delete("/api/dags/{dag_id}", status_code=204)
    def delete_dag(dag_id: str) -> None:
        """Remove DAG file, DB row, and all run history. Keeps runs/<id>/ on disk."""
        with SessionLocal() as session:
            row = session.get(DagRow, dag_id)
            if row is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            file_path = Path(row.file_path)
            # Delete task instances + runs (FK cascade isn't enforced by SQLite by default)
            run_ids = [
                r for (r,) in session.execute(
                    select(DagRun.id).where(DagRun.dag_id == dag_id)
                )
            ]
            if run_ids:
                session.execute(
                    TaskInstance.__table__.delete().where(
                        TaskInstance.run_id.in_(run_ids)
                    )
                )
                session.execute(
                    DagRun.__table__.delete().where(DagRun.dag_id == dag_id)
                )
            session.delete(row)
            session.commit()
        scheduler.unregister(dag_id)
        invalidate_cache()
        if file_path.exists():
            file_path.unlink()

    @app.post("/api/dags/{dag_id}/pause", response_model=DagSummary)
    def pause_dag(dag_id: str) -> DagSummary:
        return _set_paused(dag_id, True)

    @app.post("/api/dags/{dag_id}/unpause", response_model=DagSummary)
    def unpause_dag(dag_id: str) -> DagSummary:
        return _set_paused(dag_id, False)

    def _set_paused(dag_id: str, paused: bool) -> DagSummary:
        with SessionLocal() as session:
            r = session.get(DagRow, dag_id)
            if r is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            r.is_paused = paused
            session.commit()
        scheduler.sync_from_db()
        with SessionLocal() as session:
            return _dag_summary(session.get(DagRow, dag_id))

    @app.get("/api/dags/{dag_id}/runs", response_model=list[RunSummary])
    def list_dag_runs(dag_id: str) -> list[RunSummary]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    select(DagRun)
                    .where(DagRun.dag_id == dag_id)
                    .order_by(desc(DagRun.started_at))
                )
                .scalars()
                .all()
            )
            return [
                RunSummary(
                    id=r.id,
                    dag_id=r.dag_id,
                    status=r.status,
                    trigger_type=r.trigger_type,
                    params=json.loads(r.params_json or "{}"),
                    started_at=_iso(r.started_at),
                    finished_at=_iso(r.finished_at),
                )
                for r in rows
            ]

    @app.post("/api/dags/{dag_id}/runs", response_model=RunSummary)
    def trigger_dag(dag_id: str, body: Optional[TriggerRequest] = None) -> RunSummary:
        with SessionLocal() as session:
            r = session.get(DagRow, dag_id)
            if r is None:
                raise HTTPException(404, f"unknown dag '{dag_id}'")
            if r.parse_error:
                raise HTTPException(400, "DAG has a parse error; cannot run")
        try:
            run_id = trigger_run(dag_id, params=(body.params if body else None))
        except ValueError as exc:
            raise HTTPException(400, str(exc))  # bad / missing Run Param values
        with SessionLocal() as session:
            run = session.get(DagRun, run_id)
            return RunSummary(
                id=run.id,
                dag_id=run.dag_id,
                status=run.status,
                trigger_type=run.trigger_type,
                params=json.loads(run.params_json or "{}"),
                started_at=_iso(run.started_at),
                finished_at=_iso(run.finished_at),
            )

    @app.get("/api/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: str) -> RunDetail:
        with SessionLocal() as session:
            run = session.get(DagRun, run_id)
            if run is None:
                raise HTTPException(404, f"unknown run '{run_id}'")
            tasks = (
                session.execute(
                    select(TaskInstance)
                    .where(TaskInstance.run_id == run_id)
                    .order_by(TaskInstance.task_id)
                )
                .scalars()
                .all()
            )
            return RunDetail(
                id=run.id,
                dag_id=run.dag_id,
                status=run.status,
                trigger_type=run.trigger_type,
                params=json.loads(run.params_json or "{}"),
                started_at=_iso(run.started_at),
                finished_at=_iso(run.finished_at),
                tasks=[
                    TaskInstanceOut(
                        task_id=t.task_id,
                        status=t.status,
                        attempt=t.attempt,
                        started_at=_iso(t.started_at),
                        finished_at=_iso(t.finished_at),
                        error=t.error,
                    )
                    for t in tasks
                ],
            )

    @app.post("/api/runs/{run_id}/tasks/{task_id}/retry", response_model=RunDetail)
    def retry(run_id: str, task_id: str) -> RunDetail:
        try:
            retry_task(run_id, task_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return get_run(run_id)

    @app.get("/api/runs/{run_id}/tasks/{task_id}/log")
    def get_log(run_id: str, task_id: str, attempt: Optional[int] = None) -> dict:
        with SessionLocal() as session:
            ti = session.execute(
                select(TaskInstance).where(
                    TaskInstance.run_id == run_id, TaskInstance.task_id == task_id
                )
            ).scalar_one_or_none()
            if ti is None:
                raise HTTPException(404, "task instance not found")
            n = attempt if attempt is not None else ti.attempt
            if n < 1:
                return {"attempt": 0, "content": ""}
        path = task_log_path(run_id, task_id, n)
        if not path.exists():
            return {"attempt": n, "content": "(no log yet)"}
        return {"attempt": n, "content": path.read_text(encoding="utf-8", errors="replace")}

    @app.get("/api/runs/{run_id}/tasks/{task_id}/output")
    def get_output(run_id: str, task_id: str) -> dict:
        path = task_output_path(run_id, task_id)
        if not path.exists():
            return {"present": False, "value": None}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = json.load(fh)
        except json.JSONDecodeError as exc:
            return {"present": True, "value": None, "error": f"invalid JSON: {exc}"}
        return {"present": True, "value": value}

    # ---- Variables -----------------------------------------------------------

    def _variable_out(v: Variable) -> VariableOut:
        return VariableOut(
            key=v.key,
            value=None if v.is_secret else v.value,  # never leak secret values
            is_secret=bool(v.is_secret),
            description=v.description,
            updated_at=_iso(v.updated_at),
        )

    @app.get("/api/variables", response_model=list[VariableOut])
    def list_variables() -> list[VariableOut]:
        with SessionLocal() as session:
            rows = session.execute(select(Variable).order_by(Variable.key)).scalars().all()
            return [_variable_out(v) for v in rows]

    @app.put("/api/variables/{key}", response_model=VariableOut)
    def upsert_variable(key: str, body: VariableIn) -> VariableOut:
        if not is_identifier(key):
            raise HTTPException(400, "variable key must be a valid identifier")
        with SessionLocal() as session:
            v = session.get(Variable, key)
            if v is None:
                v = Variable(key=key)
                session.add(v)
            v.value = body.value
            v.is_secret = body.is_secret
            v.description = body.description
            v.updated_at = utcnow()
            session.commit()
            return _variable_out(session.get(Variable, key))

    @app.delete("/api/variables/{key}", status_code=204)
    def delete_variable(key: str) -> None:
        with SessionLocal() as session:
            v = session.get(Variable, key)
            if v is None:
                raise HTTPException(404, f"unknown variable '{key}'")
            session.delete(v)
            session.commit()

    # ---- Connections ---------------------------------------------------------

    def _connection_out(c: Connection) -> ConnectionOut:
        return ConnectionOut(
            conn_id=c.conn_id,
            conn_type=c.conn_type,
            host=c.host,
            port=c.port,
            login=c.login,
            has_password=bool(c.password),
            extra=c.extra,
            description=c.description,
            updated_at=_iso(c.updated_at),
        )

    @app.get("/api/connections", response_model=list[ConnectionOut])
    def list_connections() -> list[ConnectionOut]:
        with SessionLocal() as session:
            rows = session.execute(
                select(Connection).order_by(Connection.conn_id)
            ).scalars().all()
            return [_connection_out(c) for c in rows]

    @app.put("/api/connections/{conn_id}", response_model=ConnectionOut)
    def upsert_connection(conn_id: str, body: ConnectionIn) -> ConnectionOut:
        if not is_identifier(conn_id):
            raise HTTPException(400, "conn_id must be a valid identifier")
        if body.extra:
            try:
                json.loads(body.extra)
            except json.JSONDecodeError as exc:
                raise HTTPException(400, f"extra must be valid JSON: {exc}")
        with SessionLocal() as session:
            c = session.get(Connection, conn_id)
            creating = c is None
            if creating:
                c = Connection(conn_id=conn_id)
                session.add(c)
            c.conn_type = body.conn_type
            c.host = body.host
            c.port = body.port
            c.login = body.login
            c.extra = body.extra
            c.description = body.description
            # password: None => keep existing (or empty on create); "" => clear; else set
            if body.password is not None:
                c.password = body.password or None
            elif creating:
                c.password = None
            c.updated_at = utcnow()
            session.commit()
            return _connection_out(session.get(Connection, conn_id))

    @app.delete("/api/connections/{conn_id}", status_code=204)
    def delete_connection(conn_id: str) -> None:
        with SessionLocal() as session:
            c = session.get(Connection, conn_id)
            if c is None:
                raise HTTPException(404, f"unknown connection '{conn_id}'")
            session.delete(c)
            session.commit()

    return app


app = create_app()
