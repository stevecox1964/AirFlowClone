"""In-process cron scheduler. One BackgroundScheduler for the whole app.

Single source of truth for pause is `dag.is_paused` in the DB — the scheduler
re-reads it inside the job callback so a stale in-memory registration can't
fire a paused DAG. Catchup is intentionally OFF: missed ticks while the server
was down are discarded (coalesce=True, misfire_grace_time small)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from .db import SessionLocal
from .models import Dag as DagRow

log = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _scheduler_instance() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            timezone="UTC",
            job_defaults={"coalesce": True, "misfire_grace_time": 30, "max_instances": 1},
        )
    return _scheduler


def start() -> None:
    sched = _scheduler_instance()
    if not sched.running:
        sched.start()
        log.info("scheduler started")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler shut down")
    _scheduler = None


def compute_next(cron: str) -> Optional[datetime]:
    try:
        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
    except Exception:
        return None
    return trigger.get_next_fire_time(None, datetime.now(timezone.utc))


def _job_callback(dag_id: str) -> None:
    """Fired by APScheduler. Re-checks pause state from DB before triggering."""
    from .executor import trigger_run  # local import to avoid import cycles at module load

    with SessionLocal() as session:
        row = session.get(DagRow, dag_id)
        if row is None:
            log.warning("scheduled fire for unknown dag '%s' — skipping", dag_id)
            return
        if row.is_paused:
            log.info("skipped scheduled fire for paused dag '%s'", dag_id)
            return
        if row.parse_error:
            log.warning("skipped scheduled fire for dag '%s' with parse error", dag_id)
            return
        cron = row.schedule
    try:
        trigger_run(dag_id, trigger_type="scheduled")
    except Exception:
        log.exception("scheduled run failed to launch for '%s'", dag_id)
    # Refresh next_run_at after firing.
    if cron:
        _persist_next_run(dag_id, compute_next(cron))


def _persist_next_run(dag_id: str, next_run: Optional[datetime]) -> None:
    with SessionLocal() as session:
        row = session.get(DagRow, dag_id)
        if row is None:
            return
        row.next_run_at = next_run
        session.commit()


def register(dag_id: str, cron: str) -> Optional[datetime]:
    """Register or replace the job for dag_id. Returns the computed next_run_at."""
    sched = _scheduler_instance()
    try:
        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
    except Exception as exc:
        log.warning("invalid cron '%s' for dag '%s': %s", cron, dag_id, exc)
        return None
    sched.add_job(
        _job_callback,
        trigger=trigger,
        id=dag_id,
        args=[dag_id],
        replace_existing=True,
    )
    return trigger.get_next_fire_time(None, datetime.now(timezone.utc))


def unregister(dag_id: str) -> None:
    sched = _scheduler_instance()
    if sched.get_job(dag_id) is not None:
        sched.remove_job(dag_id)


def sync_from_db() -> None:
    """Reconcile in-memory jobs with current DB state.

    A DAG gets a job iff: row exists, has a schedule, has no parse_error, is not paused.
    Also refreshes next_run_at on every DAG (None when no schedule or paused)."""
    sched = _scheduler_instance()
    with SessionLocal() as session:
        rows = session.execute(select(DagRow)).scalars().all()
        active_dag_ids: set[str] = set()
        for row in rows:
            should_schedule = (
                row.schedule
                and not row.parse_error
                and not row.is_paused
            )
            if should_schedule:
                next_run = register(row.dag_id, row.schedule)
                row.next_run_at = next_run
                active_dag_ids.add(row.dag_id)
            else:
                unregister(row.dag_id)
                row.next_run_at = None
        session.commit()

    # Clean up jobs for DAGs that no longer exist in the DB.
    for job in list(sched.get_jobs()):
        if job.id not in active_dag_ids:
            sched.remove_job(job.id)
