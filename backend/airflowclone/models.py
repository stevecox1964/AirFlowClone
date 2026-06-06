from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Dag(Base):
    __tablename__ = "dag"

    dag_id: Mapped[str] = mapped_column(String, primary_key=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    schedule: Mapped[Optional[str]] = mapped_column(String)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    parse_error: Mapped[Optional[str]] = mapped_column(Text)
    tasks_json: Mapped[str] = mapped_column(Text, default="[]")
    # Run Param schema (JSON list of {name,type,default,required}). Source: DAG(params=[...]).
    params_json: Mapped[str] = mapped_column(Text, default="[]")
    # UI-authored spec preserved for round-trip editing. Null => hand-authored .py.
    spec_json: Mapped[Optional[str]] = mapped_column(Text)
    last_parsed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DagRun(Base):
    __tablename__ = "dag_run"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dag_id: Mapped[str] = mapped_column(String, ForeignKey("dag.dag_id"), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, running, success, failed
    trigger_type: Mapped[str] = mapped_column(String, default="manual")  # manual, scheduled
    # Resolved Run Param values this run executed with (JSON object). Frozen at trigger.
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    tasks: Mapped[list["TaskInstance"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class TaskInstance(Base):
    __tablename__ = "task_instance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("dag_run.id"), index=True)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending, queued, running, success, failed, skipped, upstream_failed
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped[DagRun] = relationship(back_populates="tasks")


class Variable(Base):
    """Global key/value config. Values are strings — tasks cast as needed.
    Secret values are masked in the UI, redacted from logs, and never written to
    runs/ on disk (passed to tasks via subprocess env instead)."""
    __tablename__ = "variable"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Connection(Base):
    """Structured credentials for an external system. `password` is the secret
    part (same handling as a secret Variable); other fields are non-secret config."""
    __tablename__ = "connection"

    conn_id: Mapped[str] = mapped_column(String, primary_key=True)
    conn_type: Mapped[Optional[str]] = mapped_column(String)
    host: Mapped[Optional[str]] = mapped_column(String)
    port: Mapped[Optional[int]] = mapped_column(Integer)
    login: Mapped[Optional[str]] = mapped_column(String)
    password: Mapped[Optional[str]] = mapped_column(Text)  # secret
    extra: Mapped[Optional[str]] = mapped_column(Text)  # JSON string
    description: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
