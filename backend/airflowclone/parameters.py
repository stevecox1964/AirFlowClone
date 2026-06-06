"""Run Param schema: validation + typed coercion. Dependency-free (no DB, no FastAPI)
so it can be shared by core.py (hand-authored DAGs), templating.py (UI specs), and the
executor (resolving values at trigger time).

A param schema is a list of definitions:
    {"name": "date", "type": "str", "required": True}
    {"name": "limit", "type": "int", "default": 100}

Allowed types: str, int, float, bool. Values supplied at trigger time are coerced to the
declared type; missing required params (with no default) raise."""
from __future__ import annotations

import keyword
import re
from typing import Any

ALLOWED_TYPES = ("str", "int", "float", "bool")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_ident(name: str) -> bool:
    return bool(_IDENT.match(name)) and not keyword.iskeyword(name)


def is_identifier(name: str) -> bool:
    """Public: keys/ids must be valid identifiers so they map cleanly to env var names."""
    return _is_ident(name)


def validate_param_schema(params: Any) -> list[tuple[str, str]]:
    """Return a list of (field, message) errors. Empty list == valid."""
    errors: list[tuple[str, str]] = []
    if params in (None, []):
        return errors
    if not isinstance(params, list):
        return [("params", "must be a list")]

    seen: set[str] = set()
    for i, p in enumerate(params):
        field = f"params[{i}]"
        if not isinstance(p, dict):
            errors.append((field, "must be an object"))
            continue
        name = p.get("name", "")
        if not name:
            errors.append((f"{field}.name", "required"))
        elif not _is_ident(name):
            errors.append((f"{field}.name", "must be a valid Python identifier"))
        elif name in seen:
            errors.append((f"{field}.name", f"duplicate param '{name}'"))
        else:
            seen.add(name)

        ptype = p.get("type", "str")
        if ptype not in ALLOWED_TYPES:
            errors.append((f"{field}.type", f"must be one of {', '.join(ALLOWED_TYPES)}"))
            continue  # can't validate default against an unknown type

        if "default" in p and p["default"] is not None:
            try:
                coerce_value(p["default"], ptype)
            except (ValueError, TypeError) as exc:
                errors.append((f"{field}.default", f"not a valid {ptype}: {exc}"))
    return errors


def coerce_value(value: Any, ptype: str) -> Any:
    """Coerce a single value to the declared type. Raises ValueError/TypeError on failure."""
    if ptype == "str":
        return str(value)
    if ptype == "int":
        if isinstance(value, bool):  # bool is an int subclass — reject the surprise
            raise ValueError("expected an integer, got a boolean")
        return int(value)
    if ptype == "float":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        return float(value)
    if ptype == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
        raise ValueError(f"cannot interpret '{value}' as a boolean")
    raise ValueError(f"unknown param type '{ptype}'")


def resolve_params(schema: list[dict], provided: dict | None) -> dict:
    """Build the resolved param values for a run: coerce provided values to declared
    types, fill defaults, error on missing-required or unknown keys. Raises ValueError
    with a human-readable message (surfaced to the API caller / LLM)."""
    provided = provided or {}
    schema = schema or []
    declared = {p["name"]: p for p in schema if isinstance(p, dict) and p.get("name")}

    unknown = set(provided) - set(declared)
    if unknown:
        raise ValueError(f"unknown param(s): {', '.join(sorted(unknown))}")

    resolved: dict[str, Any] = {}
    for name, p in declared.items():
        ptype = p.get("type", "str")
        if name in provided and provided[name] is not None:
            try:
                resolved[name] = coerce_value(provided[name], ptype)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"param '{name}': {exc}") from exc
        elif "default" in p and p["default"] is not None:
            resolved[name] = coerce_value(p["default"], ptype)
        elif p.get("required"):
            raise ValueError(f"param '{name}' is required")
        else:
            resolved[name] = None
    return resolved
