"""Scans the dags/ folder, imports each .py, finds DAG instances, records them."""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from .core import DAG
from .db import SessionLocal
from .models import Dag as DagRow, utcnow
from .paths import DAGS_DIR


def _load_module(file_path: Path):
    """Import a .py file as a standalone module. Returns module or raises."""
    module_name = f"_dags_{file_path.stem}_{abs(hash(str(file_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not create spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _find_dags(module) -> list[DAG]:
    return [v for v in vars(module).values() if isinstance(v, DAG)]


def load_dag_from_file(file_path: Path) -> Optional[DAG]:
    """Parse one DAG file, returning the first DAG instance found (or None on error)."""
    try:
        module = _load_module(file_path)
        dags = _find_dags(module)
        if not dags:
            return None
        dag = dags[0]
        dag.validate()
        return dag
    except Exception:
        return None


def scan_and_register() -> dict:
    """Scan dags/ folder, parse every .py, upsert into DB. Returns a summary."""
    DAGS_DIR.mkdir(parents=True, exist_ok=True)
    found, errors = 0, 0

    with SessionLocal() as session:
        for file_path in sorted(DAGS_DIR.glob("*.py")):
            if file_path.name.startswith("_"):
                continue

            parse_error: Optional[str] = None
            dag: Optional[DAG] = None
            try:
                module = _load_module(file_path)
                dags = _find_dags(module)
                if not dags:
                    parse_error = "no DAG instance found in file"
                else:
                    dag = dags[0]
                    dag.validate()
            except Exception:
                parse_error = traceback.format_exc()

            dag_id = dag.dag_id if dag else file_path.stem
            tasks_payload = (
                [
                    {"task_id": t.task_id, "depends_on": t.depends_on}
                    for t in dag.tasks.values()
                ]
                if dag
                else []
            )

            row = session.get(DagRow, dag_id)
            if row is None:
                row = DagRow(dag_id=dag_id, file_path=str(file_path))
                session.add(row)
            row.file_path = str(file_path)
            row.description = dag.description if dag else None
            row.schedule = dag.schedule if dag else None
            row.parse_error = parse_error
            row.tasks_json = json.dumps(tasks_payload)
            row.params_json = json.dumps(dag.params if dag else [])
            row.last_parsed_at = utcnow()

            if parse_error:
                errors += 1
            else:
                found += 1

        session.commit()

    return {"found": found, "errors": errors}


# In-memory cache so the executor can look up DAG functions without re-parsing every time.
_dag_cache: dict[str, DAG] = {}


def get_dag(dag_id: str) -> Optional[DAG]:
    if dag_id in _dag_cache:
        return _dag_cache[dag_id]
    with SessionLocal() as session:
        row = session.execute(
            select(DagRow).where(DagRow.dag_id == dag_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        dag = load_dag_from_file(Path(row.file_path))
        if dag is not None:
            _dag_cache[dag.dag_id] = dag
        return dag


def invalidate_cache() -> None:
    _dag_cache.clear()
