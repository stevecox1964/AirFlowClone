"""User-facing primitives. This is what gets imported in dags/*.py files."""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Task:
    task_id: str
    fn: Callable[..., Any]
    depends_on: list[str] = field(default_factory=list)


class DAG:
    def __init__(
        self,
        dag_id: str,
        description: Optional[str] = None,
        schedule: Optional[str] = None,
        params: Optional[list[dict]] = None,
    ) -> None:
        self.dag_id = dag_id
        self.description = description
        self.schedule = schedule
        # Run Param schema: list of {name, type, default, required}. Values are supplied
        # at trigger time and reach tasks via the injected `params` accessor.
        self.params: list[dict] = list(params or [])
        self.tasks: dict[str, Task] = {}

    def task(
        self,
        _fn: Optional[Callable[..., Any]] = None,
        *,
        depends_on: Optional[list[str]] = None,
        task_id: Optional[str] = None,
    ):
        """Decorator. Usage:

            @dag.task
            def extract(): ...

            @dag.task(depends_on=["extract"])
            def transform(extract): ...
        """
        def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            tid = task_id or fn.__name__
            if tid in self.tasks:
                raise ValueError(f"duplicate task_id '{tid}' in DAG '{self.dag_id}'")
            self.tasks[tid] = Task(task_id=tid, fn=fn, depends_on=list(depends_on or []))
            return fn

        if _fn is not None and callable(_fn):
            return wrap(_fn)
        return wrap

    def validate(self) -> None:
        for t in self.tasks.values():
            for dep in t.depends_on:
                if dep not in self.tasks:
                    raise ValueError(
                        f"task '{t.task_id}' depends on unknown task '{dep}'"
                    )
        if self._has_cycle():
            raise ValueError(f"DAG '{self.dag_id}' has a cycle")

    def _has_cycle(self) -> bool:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self.tasks}

        def visit(tid: str) -> bool:
            color[tid] = GRAY
            for dep in self.tasks[tid].depends_on:
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE and visit(dep):
                    return True
            color[tid] = BLACK
            return False

        return any(color[t] == WHITE and visit(t) for t in self.tasks)

    def topological_order(self) -> list[str]:
        in_deg = {t: 0 for t in self.tasks}
        for t in self.tasks.values():
            for d in t.depends_on:
                in_deg[t.task_id] += 1
        ready = [t for t, d in in_deg.items() if d == 0]
        order: list[str] = []
        while ready:
            ready.sort()
            cur = ready.pop(0)
            order.append(cur)
            for t in self.tasks.values():
                if cur in t.depends_on:
                    in_deg[t.task_id] -= 1
                    if in_deg[t.task_id] == 0:
                        ready.append(t.task_id)
        return order

    def task_kwargs_for(self, task_id: str) -> list[str]:
        """Names of upstream task outputs this function expects as kwargs.

        The framework wires upstream outputs into the task function by parameter name —
        each parameter must match the name of a declared upstream task.
        """
        sig = inspect.signature(self.tasks[task_id].fn)
        return [p for p in sig.parameters]


# Convenience for users who prefer a free-standing decorator factory
def task(*args, **kwargs):  # noqa: D401 — alias placeholder
    raise RuntimeError(
        "Use `@dag.task` on a DAG instance, not the module-level `task`. "
        "See backend/dags/example_etl.py for usage."
    )
