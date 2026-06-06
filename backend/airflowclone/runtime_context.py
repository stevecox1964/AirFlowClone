"""Runtime accessors injected into a task's scope: `params`, `Variable`, `Connection`.

These run inside the task subprocess. Non-secret config (params, non-secret variables,
non-secret connection fields) is read from the frozen run context file
(runs/<run_id>/context.json). Secrets (secret variable values, connection passwords) are
NOT on disk — the executor passes them via subprocess env vars, read here.

Env var contract (set by executor._run_single_task):
    AFC_RUN_CONTEXT       absolute path to this run's context.json
    AFC_VAR__<key>        value of a secret Variable
    AFC_CONN_PW__<id>     password of a Connection
"""
from __future__ import annotations

import json
import os
from typing import Any

_UNSET = object()


def secret_env_for_variable(key: str) -> str:
    return f"AFC_VAR__{key}"


def secret_env_for_conn_password(conn_id: str) -> str:
    return f"AFC_CONN_PW__{conn_id}"


class _Params:
    """Per-run inputs. Read-only view over resolved Run Param values."""

    def __init__(self, values: dict[str, Any]):
        self._v = dict(values)

    def get(self, name: str, default: Any = None) -> Any:
        return self._v.get(name, default)

    def __getitem__(self, name: str) -> Any:
        return self._v[name]

    def __contains__(self, name: str) -> bool:
        return name in self._v

    def to_dict(self) -> dict[str, Any]:
        return dict(self._v)

    def __repr__(self) -> str:
        return f"params({self._v!r})"


class _Variables:
    """`Variable.get('key')`. Non-secret values come from the frozen context; secret
    values come from the subprocess env. Missing key with no default raises (fail loud)."""

    def __init__(self, non_secret: dict[str, str]):
        self._ns = dict(non_secret)

    def get(self, key: str, default: Any = _UNSET) -> Any:
        if key in self._ns:
            return self._ns[key]
        env_val = os.environ.get(secret_env_for_variable(key))
        if env_val is not None:
            return env_val
        if default is _UNSET:
            raise KeyError(f"Variable '{key}' is not defined")
        return default


class Conn:
    """A resolved connection. Non-secret fields from context; password from env."""

    def __init__(self, conn_id: str, fields: dict[str, Any]):
        self.conn_id = conn_id
        self.conn_type = fields.get("conn_type")
        self.host = fields.get("host")
        self.port = fields.get("port")
        self.login = fields.get("login")
        self.password = os.environ.get(secret_env_for_conn_password(conn_id))
        raw_extra = fields.get("extra")
        try:
            self.extra = json.loads(raw_extra) if raw_extra else {}
        except (json.JSONDecodeError, TypeError):
            self.extra = {}

    def __repr__(self) -> str:
        return f"Conn(conn_id={self.conn_id!r}, host={self.host!r}, login={self.login!r})"


class _Connections:
    """`Connection.get('conn_id')` -> Conn. Unknown conn_id raises (fail loud)."""

    def __init__(self, conns: dict[str, dict]):
        self._c = dict(conns)

    def get(self, conn_id: str) -> Conn:
        if conn_id not in self._c:
            raise KeyError(f"Connection '{conn_id}' is not defined")
        return Conn(conn_id, self._c[conn_id])


def load_context() -> dict:
    """Read the frozen run context. Returns empty sections if absent (e.g. tests)."""
    path = os.environ.get("AFC_RUN_CONTEXT")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"params": {}, "variables": {}, "connections": {}}


def inject(globals_dict: dict, context: dict | None = None) -> None:
    """Bind `params`, `Variable`, `Connection` into a DAG module's globals so task
    bodies can use them without declaring them in the function signature."""
    ctx = context if context is not None else load_context()
    globals_dict["params"] = _Params(ctx.get("params") or {})
    globals_dict["Variable"] = _Variables(ctx.get("variables") or {})
    globals_dict["Connection"] = _Connections(ctx.get("connections") or {})
