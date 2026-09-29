"""Read-only SQL over local data files (CSV/TSV/Parquet) using DuckDB.

Only SELECT/WITH/EXPLAIN-style queries are permitted. Files must be registered
explicitly (name -> path) and live inside the allowed root; raw file paths in
query text are rejected.
"""

import logging
import os
import re
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

_WRITE_RE = re.compile(
    r"\b(insert|update|delete|drop|create|alter|copy|attach|detach|install|load|"
    r"export|truncate|merge|vacuum|call|set)\b", re.I)
_ALLOWED = ("select", "with", "describe", "show", "summarize", "explain")


def _root(base=None) -> Path:
    return Path(base or os.path.expanduser("~")).resolve()


def _within(base: Path, target: Path) -> bool:
    target = target.resolve()
    return target == base or base in target.parents


def run_sql(sql: str, files=None, root=None, limit: int = 200) -> str:
    sql = (sql or "").strip().rstrip(";")
    if not sql:
        return "(empty query)"
    if not sql.lstrip().lower().startswith(_ALLOWED):
        raise PermissionError("Only read-only SELECT/WITH/EXPLAIN queries are allowed.")
    if _WRITE_RE.search(sql):
        raise PermissionError("Query contains a disallowed (write/DDL) keyword.")

    base = _root(root)
    for lit in re.findall(r"'([^']*)'", sql):
        if ("/" in lit or "\\" in lit) and (".." in lit or os.path.isabs(lit)):
            raise PermissionError("Inline file paths are not allowed; register files instead.")

    con = duckdb.connect(":memory:")
    try:
        for name, path in (files or {}).items():
            p = Path(path)
            if not p.is_absolute():
                p = base / p
            if not _within(base, p):
                raise PermissionError(f"File '{path}' is outside the allowed root.")
            view = re.sub(r"\W", "_", name) or "t"
            ext = p.suffix.lower()
            safe = str(p).replace("'", "''")
            if ext in (".csv", ".tsv"):
                con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_csv_auto('{safe}')")
            elif ext == ".parquet":
                con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{safe}')")
            else:
                raise ValueError(f"Unsupported file type: {ext}")
        df = con.execute(sql).fetchdf()
        return df.head(limit).to_string(index=False) if df is not None else "(no result)"
    finally:
        con.close()