"""Orchestrator. One background thread per DagRun. Dispatches tasks in dep order,
each task as a subprocess, log streamed to file, status tracked in DB."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from .db import SessionLocal
from .loader import get_dag
from .models import Connection, Dag as DagRow, DagRun, TaskInstance, Variable, utcnow
from .parameters import resolve_params
from .paths import run_dir, task_log_path, task_output_path  # noqa: F401 — re-exported
from .runtime_context import (
    secret_env_for_conn_password,
    secret_env_for_variable,
)


def _new_run_id(dag_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{dag_id}_{stamp}_{uuid.uuid4().hex[:6]}"


def create_run(
    dag_id: str,
    trigger_type: str = "manual",
    params: Optional[dict] = None,
) -> str:
    """Create a DagRun + TaskInstance rows and freeze the run context. Returns run_id.

    Raises ValueError if the supplied Run Param values don't satisfy the DAG's schema."""
    dag = get_dag(dag_id)
    if dag is None:
        raise ValueError(f"unknown dag_id '{dag_id}'")
    resolved = resolve_params(getattr(dag, "params", []), params)  # raises on bad input
    run_id = _new_run_id(dag_id)

    with SessionLocal() as session:
        run = DagRun(
            id=run_id,
            dag_id=dag_id,
            status="pending",
            trigger_type=trigger_type,
            params_json=json.dumps(resolved),
            started_at=utcnow(),
        )
        session.add(run)
        for tid in dag.tasks:
            session.add(
                TaskInstance(run_id=run_id, task_id=tid, status="pending", attempt=0)
            )
        session.commit()

    _freeze_context(run_id, resolved)
    return run_id


def trigger_run(
    dag_id: str,
    trigger_type: str = "manual",
    params: Optional[dict] = None,
) -> str:
    run_id = create_run(dag_id, trigger_type=trigger_type, params=params)
    threading.Thread(target=_orchestrate, args=(run_id,), daemon=True).start()
    return run_id


def _context_path(run_id: str) -> Path:
    return run_dir(run_id) / "context.json"


def _freeze_context(run_id: str, resolved_params: dict) -> None:
    """Snapshot non-secret config into runs/<run_id>/context.json. Secrets are excluded
    here on purpose — they're passed to tasks via env (see _collect_secret_env)."""
    with SessionLocal() as session:
        variables = session.execute(select(Variable)).scalars().all()
        conns = session.execute(select(Connection)).scalars().all()
    context = {
        "params": resolved_params,
        "variables": {v.key: v.value for v in variables if not v.is_secret},
        "connections": {
            c.conn_id: {
                "conn_type": c.conn_type,
                "host": c.host,
                "port": c.port,
                "login": c.login,
                "extra": c.extra,
            }
            for c in conns
        },
    }
    _context_path(run_id).write_text(
        json.dumps(context, indent=2, default=str), encoding="utf-8"
    )


def _collect_secret_env() -> tuple[dict[str, str], set[str]]:
    """Resolve secrets fresh from the DB at task-spawn time. Returns (env additions,
    set of secret string values to redact from logs). Secrets are never written to disk."""
    env: dict[str, str] = {}
    secret_values: set[str] = set()
    with SessionLocal() as session:
        for v in session.execute(
            select(Variable).where(Variable.is_secret.is_(True))
        ).scalars():
            if v.value is not None:
                env[secret_env_for_variable(v.key)] = v.value
                if v.value:
                    secret_values.add(v.value)
        for c in session.execute(select(Connection)).scalars():
            if c.password:
                env[secret_env_for_conn_password(c.conn_id)] = c.password
                secret_values.add(c.password)
    return env, secret_values


def retry_task(run_id: str, task_id: str) -> None:
    """Reset a task and any downstream tasks that were blocked by it; re-orchestrate."""
    with SessionLocal() as session:
        run = session.get(DagRun, run_id)
        if run is None:
            raise ValueError(f"unknown run '{run_id}'")
        ti = session.execute(
            select(TaskInstance).where(
                TaskInstance.run_id == run_id, TaskInstance.task_id == task_id
            )
        ).scalar_one_or_none()
        if ti is None:
            raise ValueError(f"task '{task_id}' not in run '{run_id}'")

        dag = get_dag(run.dag_id)
        if dag is None:
            raise ValueError(f"DAG '{run.dag_id}' could not be loaded")

        # Compute the set of downstream task_ids transitively reachable from this task.
        downstream: set[str] = set()
        frontier = {task_id}
        while frontier:
            current = frontier.pop()
            for t in dag.tasks.values():
                if current in t.depends_on and t.task_id not in downstream:
                    downstream.add(t.task_id)
                    frontier.add(t.task_id)

        # Reset the target + any downstream tasks that are stuck or failed.
        to_reset = {task_id} | downstream
        all_tis = session.execute(
            select(TaskInstance).where(TaskInstance.run_id == run_id)
        ).scalars().all()
        for t in all_tis:
            if t.task_id in to_reset and t.status in (
                "pending", "failed", "upstream_failed", "running"
            ):
                t.status = "pending"
                t.error = None
                t.started_at = None
                t.finished_at = None

        run.status = "running"
        run.finished_at = None
        session.commit()

    threading.Thread(target=_orchestrate, args=(run_id,), daemon=True).start()


def _set_run_status(session, run_id: str, status: str) -> None:
    run = session.get(DagRun, run_id)
    if run is None:
        return
    run.status = status
    if status in ("success", "failed"):
        run.finished_at = utcnow()


def _orchestrate(run_id: str) -> None:
    """Drives a DagRun. Runs pending tasks in dep order; skips already-successful ones.
    Safe to invoke multiple times — used for both fresh runs and post-retry continuation."""
    with SessionLocal() as session:
        run = session.get(DagRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.finished_at = None
        session.commit()
        dag = get_dag(run.dag_id)
        if dag is None:
            run.status = "failed"
            session.commit()
            return
        order = dag.topological_order()

    for tid in order:
        # Re-check status each step — task may have been retried or already succeeded
        with SessionLocal() as session:
            ti = session.execute(
                select(TaskInstance).where(
                    TaskInstance.run_id == run_id, TaskInstance.task_id == tid
                )
            ).scalar_one()
            cur_status = ti.status

        if cur_status == "success":
            continue
        if cur_status not in ("pending",):
            # failed / upstream_failed left over from a prior run that wasn't retried —
            # block downstream and stop.
            with SessionLocal() as session:
                for downstream in order[order.index(tid) + 1 :]:
                    d_ti = session.execute(
                        select(TaskInstance).where(
                            TaskInstance.run_id == run_id,
                            TaskInstance.task_id == downstream,
                        )
                    ).scalar_one()
                    if d_ti.status == "pending":
                        d_ti.status = "upstream_failed"
                _set_run_status(session, run_id, "failed")
                session.commit()
            return

        ok = _run_single_task(run_id, tid)
        if not ok:
            with SessionLocal() as session:
                for downstream in order[order.index(tid) + 1 :]:
                    d_ti = session.execute(
                        select(TaskInstance).where(
                            TaskInstance.run_id == run_id,
                            TaskInstance.task_id == downstream,
                        )
                    ).scalar_one()
                    if d_ti.status == "pending":
                        d_ti.status = "upstream_failed"
                _set_run_status(session, run_id, "failed")
                session.commit()
            return

    with SessionLocal() as session:
        _set_run_status(session, run_id, "success")
        session.commit()


def _run_single_task(run_id: str, task_id: str) -> bool:
    """Spawn a subprocess for one task. Streams output to its log file."""
    with SessionLocal() as session:
        run = session.get(DagRun, run_id)
        if run is None:
            return False
        ti = session.execute(
            select(TaskInstance).where(
                TaskInstance.run_id == run_id, TaskInstance.task_id == task_id
            )
        ).scalar_one()
        ti.attempt += 1
        attempt = ti.attempt
        ti.status = "running"
        ti.started_at = utcnow()
        ti.error = None
        session.commit()
        dag_row = session.get(DagRow, run.dag_id)
        dag_file = Path(dag_row.file_path)

    log_path = task_log_path(run_id, task_id, attempt)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Subprocess: force UTF-8 on stdout/stderr so log files are clean on Windows
    cmd = [sys.executable, "-u", "-m", "airflowclone.run_task", str(dag_file), task_id, run_id]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["AFC_RUN_CONTEXT"] = str(_context_path(run_id))
    secret_env, secret_values = _collect_secret_env()
    env.update(secret_env)

    def _redact(text: str) -> str:
        for s in secret_values:
            if s:
                text = text.replace(s, "***")
        return text

    rc = 0
    err_excerpt: Optional[str] = None
    try:
        with open(log_path, "w", encoding="utf-8") as log_fh:
            log_fh.write(f"$ {' '.join(cmd)}\n\n")
            log_fh.flush()
            # Pipe + line-pump so we can redact secrets before they hit disk.
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(Path(__file__).resolve().parents[1]),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                log_fh.write(_redact(line))
                log_fh.flush()
            rc = proc.wait()
    except Exception as exc:
        rc = 99
        err_excerpt = f"orchestrator failed to spawn subprocess: {exc}"
        with open(log_path, "a", encoding="utf-8") as log_fh:
            log_fh.write(f"\n[orchestrator] {err_excerpt}\n")

    success = rc == 0
    if not success and err_excerpt is None:
        # Tail the log file to give a quick error preview in the UI
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            err_excerpt = text[-600:]
        except OSError:
            err_excerpt = f"subprocess exited rc={rc}"

    with SessionLocal() as session:
        ti = session.execute(
            select(TaskInstance).where(
                TaskInstance.run_id == run_id, TaskInstance.task_id == task_id
            )
        ).scalar_one()
        ti.status = "success" if success else "failed"
        ti.finished_at = utcnow()
        ti.error = None if success else (err_excerpt or f"exit code {rc}")
        # If retried in isolation and succeeded, the run might be revivable.
        if success:
            # Check if all tasks succeeded — if so, run is success
            all_done = session.execute(
                select(TaskInstance).where(TaskInstance.run_id == run_id)
            ).scalars().all()
            if all(t.status == "success" for t in all_done):
                _set_run_status(session, run_id, "success")
            elif any(t.status == "failed" for t in all_done):
                _set_run_status(session, run_id, "failed")
            else:
                run = session.get(DagRun, run_id)
                if run is not None:
                    run.status = "running"
        else:
            _set_run_status(session, run_id, "failed")
        session.commit()

    return success
