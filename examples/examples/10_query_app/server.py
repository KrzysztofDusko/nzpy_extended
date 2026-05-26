#!/usr/bin/env python
"""
FastAPI test harness for nzpy_extended.
Features: SQL editor, query execution with timeout & cancel, import/export, virtualized results grid.

Usage:
    pip install fastapi uvicorn aiofiles python-multipart
    python server.py
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import nzpy_extended as nzpy
from nzpy_extended.pool import NzPool

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
except ImportError as exc:
    print(f"Missing dependencies. Run: pip install fastapi uvicorn aiofiles python-multipart")
    raise SystemExit(1) from exc


# ---------------------------------------------------------------------------
# Configuration — read from environment, same convention as tests
# ---------------------------------------------------------------------------
NZ_HOST = os.environ.get("NZ_DEV_HOST", "192.168.0.144")
NZ_PORT = int(os.environ.get("NZ_DEV_PORT", "5480"))
NZ_DB = os.environ.get("NZ_DEV_DB", "JUST_DATA")
NZ_USER = os.environ.get("NZ_DEV_USER", "admin")
NZ_PASSWORD = os.environ.get("NZ_DEV_PASSWORD", "password")
NZ_MIN_POOL = int(os.environ.get("NZ_MIN_POOL", "2"))
NZ_MAX_POOL = int(os.environ.get("NZ_MAX_POOL", "8"))

DEFAULT_QUERY_TIMEOUT = 30.0
MAX_IMPORT_ROWS = 50_000


class _JsonEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, (datetime, date, time)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def _jsonable_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _jsonable_rows(rows: list[list[Any]]) -> list[list[Any]]:
    return [[_jsonable_value(cell) for cell in row] for row in rows]


# ---------------------------------------------------------------------------
# Active query tracking (for cancel)
# ---------------------------------------------------------------------------
_active_queries: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# App & pool
# ---------------------------------------------------------------------------
static_dir = Path(__file__).resolve().parent / "static"

app = FastAPI(title="nzpy_extended Query App", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _global_exc_handler(request: Any, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    pool = NzPool(
        min_size=NZ_MIN_POOL,
        max_size=NZ_MAX_POOL,
        acquire_timeout=10.0,
        ping_query="SELECT 1",
        user=NZ_USER,
        password=NZ_PASSWORD,
        host=NZ_HOST,
        port=NZ_PORT,
        database=NZ_DB,
    )
    await pool.open()
    app.state.nz_pool = pool
    try:
        yield
    finally:
        await pool.close_all()


app.router.lifespan_context = lifespan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_columns(cur: Any) -> list[dict[str, Any]]:
    schema = cur.get_schema_table()
    if not schema:
        desc = cur.description
        if desc:
            return [
                {"ColumnName": d[0], "DataType": "unknown", "ColumnOrdinal": i + 1}
                for i, d in enumerate(desc)
            ]
        return []
    for col in schema:
        dt = col.get("DataType")
        if isinstance(dt, type):
            col["DataType"] = dt.__name__
    return schema


async def _execute_and_fetch(
    query_id: str, sql: str, timeout: float | None
) -> tuple[list[dict[str, Any]], list[list[Any]], int]:
    pool: NzPool = app.state.nz_pool
    async with pool.connection() as conn:
        cur = conn.cursor()
        _active_queries[query_id] = {"cursor": cur, "conn": conn, "cancelled": False}

        async def _check_cancel() -> None:
            while True:
                await asyncio.sleep(0.2)
                if _active_queries.get(query_id, {}).get("cancelled"):
                    await conn.cancel()
                    break

        cancel_task = asyncio.create_task(_check_cancel())

        try:
            await cur.execute(sql, timeout=timeout)
            rows = await cur.fetchall()
            columns = _build_columns(cur)
            row_count = cur.rowcount if cur.rowcount >= 0 else len(rows)
        finally:
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass
            _active_queries.pop(query_id, None)

    return columns, [list(r) for r in rows], row_count


def _rows_to_csv_stream(
    columns: list[dict[str, Any]], rows: list[list[Any]], delimiter: str = ","
) -> io.StringIO:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
    header = [col["ColumnName"] for col in columns]
    writer.writerow(header)
    for row in rows:
        writer.writerow([str(v) if v is not None else "" for v in row])
    output.seek(0)
    return output


def _csv_to_rows(data: str, delimiter: str = ",") -> list[list[str | None]]:
    reader = csv.reader(io.StringIO(data), delimiter=delimiter)
    rows: list[list[str | None]] = []
    for row in reader:
        rows.append([cell if cell.strip() != "" else None for cell in row])
    return rows


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    raise HTTPException(404, "index.html not found")


@app.get("/api/tables")
async def list_tables() -> dict[str, Any]:
    pool: NzPool = app.state.nz_pool
    async with pool.connection() as conn:
        cur = conn.cursor()
        await cur.execute(
            "SELECT tablename FROM _v_table WHERE objtype='TABLE' "
            "AND tablename NOT LIKE 'SYS%' ORDER BY tablename"
        )
        rows = await cur.fetchall()
        return {"tables": [r[0] for r in rows]}


@app.post("/api/query")
async def run_query(
    sql: str = Form(...),
    timeout: float | None = Form(None),
    export: str | None = Form(None),
    query_id: str | None = Form(None),
) -> dict[str, Any]:
    if not sql.strip():
        raise HTTPException(400, "SQL query is empty")

    qid = query_id or os.urandom(8).hex()
    effective_timeout = timeout if timeout and timeout > 0 else DEFAULT_QUERY_TIMEOUT

    try:
        columns, rows, row_count = await _execute_and_fetch(
            qid, sql.strip(), effective_timeout
        )
    except nzpy.OperationalError as exc:
        raise HTTPException(408, f"Query timeout: {exc}") from exc
    except nzpy.Error as exc:
        raise HTTPException(500, str(exc)) from exc

    jsonable_rows = _jsonable_rows(rows)

    response: dict[str, Any] = {
        "query_id": qid,
        "columns": columns,
        "row_count": row_count,
        "truncated": False,
    }

    if export == "csv":
        stream = _rows_to_csv_stream(columns, rows)
        response["csv_content"] = stream.getvalue()
    else:
        response["rows"] = jsonable_rows
        if len(jsonable_rows) > 10000:
            response["rows"] = jsonable_rows[:10000]
            response["truncated"] = True
            response["message"] = f"Showing first 10 000 of {len(jsonable_rows)} rows"

    return JSONResponse(content=response)


@app.post("/api/cancel")
async def cancel_query(query_id: str = Form(...)) -> dict[str, Any]:
    entry = _active_queries.get(query_id)
    if entry is None:
        return {"status": "no_active_query", "query_id": query_id}

    entry["cancelled"] = True
    return {"status": "cancelling", "query_id": query_id}


@app.post("/api/export")
async def export_results(
    sql: str = Form(...),
    format: str = Form("csv"),
) -> StreamingResponse:
    if not sql.strip():
        raise HTTPException(400, "SQL query is empty")

    pool: NzPool = app.state.nz_pool
    async with pool.connection() as conn:
        cur = conn.cursor()
        await cur.execute(sql, timeout=DEFAULT_QUERY_TIMEOUT)
        rows = await cur.fetchall()
        columns = _build_columns(cur)

    output = _rows_to_csv_stream(columns, [list(r) for r in rows])
    filename = "export.csv"

    if format == "json":
        json_rows = []
        header = [c["ColumnName"] for c in columns]
        for row in rows:
            json_rows.append({header[i]: v for i, v in enumerate(row)})
        output = io.StringIO(json.dumps(json_rows, indent=2, default=str))
        filename = "export.json"

    return StreamingResponse(
        output,
        media_type="text/csv" if format == "csv" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/import")
async def import_data(
    file: UploadFile = File(...),
    table: str = Form(...),
    delimiter: str = Form(","),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, "No file provided")

    content = (await file.read()).decode("utf-8-sig")
    if not content.strip():
        raise HTTPException(400, "File is empty")

    rows = _csv_to_rows(content, delimiter)
    if not rows:
        raise HTTPException(400, "No data rows found")

    header = [c.replace('"', "").strip() for c in rows[0]]
    data_rows = rows[1:]
    total_rows = len(data_rows)

    columns_schema: list[tuple[str, str]] = [
        (h, "VARCHAR(32000)") for h in header
    ]

    pool: NzPool = app.state.nz_pool
    batch_size = 5000
    imported = 0
    errors: list[str] = []

    async with pool.connection() as conn:
        for start in range(0, min(total_rows, MAX_IMPORT_ROWS), batch_size):
            batch = data_rows[start : start + batch_size]
            try:
                await conn.load_data(
                    table_name=table,
                    rows=batch,
                    columns=columns_schema,
                )
                imported += len(batch)
            except nzpy.Error as exc:
                errors.append(f"Batch {start}-{start + len(batch)}: {exc}")
                break

    return {
        "table": table,
        "total_rows_in_file": total_rows,
        "imported": imported,
        "errors": errors if errors else None,
    }


@app.get("/api/version")
async def get_version() -> dict[str, str]:
    pool: NzPool = app.state.nz_pool
    async with pool.connection() as conn:
        cur = conn.cursor()
        await cur.execute("SELECT version()")
        row = await cur.fetchone()
    return {"version": row[0] if row else "unknown"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8480,
        reload=True,
    )
