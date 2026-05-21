import asyncio
import time
import os
import sys

# Automatically add the main directory to the path to avoid ModuleNotFoundError
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import nzpy_extended
from nzpy_extended import core as nzpy_core
from nzpy_extended.pool import NzPool

# Try to import official nzpy for comparison
try:
    import nzpy
    NZPY_AVAILABLE = True
except ImportError:
    nzpy = None
    NZPY_AVAILABLE = False
    print("Warning: Official nzpy not available for comparison")

# Try to import pyodbc for comparison
try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    pyodbc = None
    PYODBC_AVAILABLE = False
    print("Warning: pyodbc not available for comparison")

# Connection configuration (retrieved from environment variables or default values)
HOST = os.getenv("NZ_HOST", "192.168.0.144")
PORT = int(os.getenv("NZ_PORT", "5480"))
USER = os.getenv("NZ_USER", "admin")
PASSWORD = os.getenv("NZ_PASSWORD", "password")
DATABASE = os.getenv("NZ_DATABASE", "SYSTEM")
ROW_LIMIT = int(os.getenv("NZ_ROWS", "100000"))

SOURCE_TABLE = "JUST_DATA..FACTPRODUCTINVENTORY"

# ─── Data-type-specific queries ───────────────────────────────────────────────

QUERIES = {
    "integer_types": f"""
        SELECT
            (RANDOM()*10000)::INT       AS col_int,
            (RANDOM()*10000)::BIGINT    AS col_bigint,
            (RANDOM()*100)::SMALLINT    AS col_smallint,
            (RANDOM()*10)::BYTEINT      AS col_byteint
        FROM {SOURCE_TABLE}
        LIMIT {ROW_LIMIT}
    """,
    "numeric_types": f"""
        SELECT
            (RANDOM()*10000)::NUMERIC(20,4)  AS col_numeric,
            (RANDOM()*10000)::DECIMAL(18,2)  AS col_decimal,
            (RANDOM()*10000)::REAL           AS col_real,
            (RANDOM()*10000)::DOUBLE PRECISION AS col_double
        FROM {SOURCE_TABLE}
        LIMIT {ROW_LIMIT}
    """,
    "string_types": f"""
        SELECT
            (RANDOM()*10000)::VARCHAR(50)  AS col_varchar,
            (RANDOM()*10000)::NVARCHAR(50) AS col_nvarchar,
            (RANDOM()*10000)::CHAR(20)     AS col_char
        FROM {SOURCE_TABLE}
        LIMIT {ROW_LIMIT}
    """,
    "datetime_types": f"""
        SELECT
            CURRENT_DATE + (RANDOM()*365)::INT    AS col_date,
            CURRENT_TIME                          AS col_time,
            CURRENT_TIMESTAMP                     AS col_timestamp
        FROM {SOURCE_TABLE}
        LIMIT {ROW_LIMIT}
    """,
    "boolean_types": f"""
        SELECT
            CASE WHEN RANDOM() > 0.5 THEN TRUE  ELSE FALSE END AS col_bool,
            CASE WHEN RANDOM() > 0.5 THEN TRUE  ELSE FALSE END AS col_boolean
        FROM {SOURCE_TABLE}
        LIMIT {ROW_LIMIT}
    """,
}

ALL_TYPES_QUERY = f"""
    SELECT
        (RANDOM()*10000)::INT              AS col_int,
        (RANDOM()*10000)::BIGINT           AS col_bigint,
        (RANDOM()*100)::SMALLINT           AS col_smallint,
        (RANDOM()*10)::BYTEINT             AS col_byteint,
        (RANDOM()*10000)::NUMERIC(20,4)    AS col_numeric,
        (RANDOM()*10000)::DECIMAL(18,2)    AS col_decimal,
        (RANDOM()*10000)::REAL             AS col_real,
        (RANDOM()*10000)::DOUBLE PRECISION AS col_double,
        (RANDOM()*10000)::VARCHAR(50)      AS col_varchar,
        (RANDOM()*10000)::NVARCHAR(50)     AS col_nvarchar,
        (RANDOM()*10000)::CHAR(20)         AS col_char,
        CURRENT_DATE + (RANDOM()*365)::INT AS col_date,
        CURRENT_TIME                       AS col_time,
        CURRENT_TIMESTAMP                  AS col_timestamp,
        CASE WHEN RANDOM() > 0.5 THEN TRUE ELSE FALSE END AS col_bool
    FROM {SOURCE_TABLE}
    LIMIT {ROW_LIMIT}
"""


QUERIES["all_types"] = ALL_TYPES_QUERY


DRIVER_NAMES = [
    "official_nzpy",
    "pyodbc",
    "nzpy_extended_async",
    "nzpy_extended_sync",
    "nzpy_extended_async_nocext",
    "nzpy_extended_sync_nocext",
]


def fmt_num(n):
    """Format an integer with a space as thousand separator."""
    return f"{n:,}".replace(",", " ")


def fmt_rps(rps):
    """Format rows/s value with a space as thousand separator."""
    return f"{rps:_.2f}".replace("_", " ")


async def _run_async_query(conn, label, query, results_dict):
    async with conn.cursor() as cursor:
        print(f"  {label}: Executing...", end=" ")
        start = time.perf_counter()
        await cursor.execute(query)
        rows = await cursor.fetchall()
        elapsed = time.perf_counter() - start
        count = len(rows)
        rps = count / elapsed if elapsed > 0 else 0
        print(f"fetched {fmt_num(count)} rows in {elapsed:.4f}s ({fmt_rps(rps)} rows/s)")
        results_dict[label] = {
            "query_time": elapsed,
            "rows_per_second": rps,
            "row_count": count,
        }


def _run_sync_query(conn, label, query, results_dict):
    with conn.cursor() as cursor:
        print(f"  {label}: Executing...", end=" ")
        start = time.perf_counter()
        cursor.execute(query)
        rows = cursor.fetchall()
        elapsed = time.perf_counter() - start
        count = len(rows)
        rps = count / elapsed if elapsed > 0 else 0
        print(f"fetched {fmt_num(count)} rows in {elapsed:.4f}s ({fmt_rps(rps)} rows/s)")
        results_dict[label] = {
            "query_time": elapsed,
            "rows_per_second": rps,
            "row_count": count,
        }


def _print_bar(label, rps, max_rps):
    bar_len = int((rps / max_rps) * 40) if max_rps > 0 else 0
    bar = "#" * bar_len + "-" * (40 - bar_len)
    print(f"  {label:30s} [{bar}] {fmt_rps(rps):>12s} rows/s")


async def _run_sync_driver(label, connect_fn, query, results_dict):
    try:
        start_conn = time.perf_counter()
        conn = connect_fn()
        ct = time.perf_counter() - start_conn
        flags = []
        if not nzpy_core._HAVE_C_EXT:
            flags.append("C ext disabled")
        tag = f" ({', '.join(flags)})" if flags else ""
        print(f"  {label}: Connected in {ct:.4f}s{tag}")
        _run_sync_query(conn, label, query, results_dict)
        conn.close()
    except Exception as e:
        print(f"  {label}: ERROR - {e}")
        results_dict[label] = {"error": str(e)}


async def _run_async_driver_extended(label, query, results_dict):
    try:
        start_conn = time.perf_counter()
        conn = await nzpy_extended.connect(
            user=USER, password=PASSWORD, host=HOST, port=PORT, database=DATABASE
        )
        ct = time.perf_counter() - start_conn
        flags = []
        if not nzpy_core._HAVE_C_EXT:
            flags.append("C ext disabled")
        tag = f" ({', '.join(flags)})" if flags else ""
        print(f"  {label}: Connected in {ct:.4f}s{tag}")
        await _run_async_query(conn, label, query, results_dict)
        await conn.close()
    except Exception as e:
        print(f"  {label}: ERROR - {e}")
        results_dict[label] = {"error": str(e)}


async def run_single_type(type_name, query):
    """Run one query across all available drivers, return {driver: result}."""
    results = {}

    # official nzpy (sync)
    if NZPY_AVAILABLE:
        await _run_sync_driver(
            "official_nzpy",
            lambda: nzpy.connect(  # type: ignore[union-attr]
                user=USER, password=PASSWORD, host=HOST, port=PORT, database=DATABASE
            ),
            query,
            results,
        )

    # pyodbc (sync)
    if PYODBC_AVAILABLE:
        conn_str = (
            f"DRIVER={{NetezzaSQL}};SERVER={HOST};PORT={PORT};"
            f"DATABASE={DATABASE};UID={USER};PWD={PASSWORD};"
        )
        await _run_sync_driver(
            "pyodbc",
            lambda: pyodbc.connect(conn_str),  # type: ignore[union-attr]
            query,
            results,
        )

    # nzpy_extended async (with C extension)
    await _run_async_driver_extended("nzpy_extended_async", query, results)

    # nzpy_extended sync (with C extension)
    await _run_sync_driver(
        "nzpy_extended_sync",
        lambda: nzpy_extended.sync.connect(
            user=USER, password=PASSWORD, host=HOST, port=PORT, database=DATABASE
        ),
        query,
        results,
    )

    # nzpy_extended async (pure Python, no C extension)
    original_cext = nzpy_core._HAVE_C_EXT
    nzpy_core._HAVE_C_EXT = False
    try:
        await _run_async_driver_extended("nzpy_extended_async_nocext", query, results)
    finally:
        nzpy_core._HAVE_C_EXT = original_cext

    # nzpy_extended sync (pure Python, no C extension)
    original_cext = nzpy_core._HAVE_C_EXT
    nzpy_core._HAVE_C_EXT = False
    try:
        await _run_sync_driver(
            "nzpy_extended_sync_nocext",
            lambda: nzpy_extended.sync.connect(
                user=USER, password=PASSWORD, host=HOST, port=PORT, database=DATABASE
            ),
            query,
            results,
        )
    finally:
        nzpy_core._HAVE_C_EXT = original_cext

    return results


async def run_performance_test():
    print(f"--- nzpy_extended performance test (data-type breakdown) ---")
    print(f"Host: {HOST}:{PORT}, DB: {DATABASE}, Rows: {fmt_num(ROW_LIMIT)}")
    print(f"Official nzpy: {NZPY_AVAILABLE},  pyodbc: {PYODBC_AVAILABLE}")
    print()

    all_results = {}

    for type_name, query in QUERIES.items():
        header = f"  {type_name.replace('_', ' ').upper()}"
        print(f"─── {header} ───")
        drv_results = await run_single_type(type_name, query)
        all_results[type_name] = drv_results
        print()

    # ── Per-type summary with driver comparison ────────────────────────────
    print("=" * 68)
    print("  PER-TYPE × DRIVER COMPARISON (rows/s)")
    print("=" * 68)

    header_row = f"  {'type':20s}"
    for d in DRIVER_NAMES:
        header_row += f"  {d:>16s}"
    print(header_row)
    print("  " + "-" * (20 + 18 * len(DRIVER_NAMES)))

    for type_name in QUERIES:
        row = f"  {type_name:20s}"
        for d in DRIVER_NAMES:
            r = all_results.get(type_name, {}).get(d)
            if r and "error" not in r:
                row += f"  {fmt_rps(r['rows_per_second']):>16s}"
            elif r:
                row += f"  {'ERROR':>16s}"
            else:
                row += f"  {'N/A':>16s}"
        print(row)

    # ── Visual bars per query type ─────────────────────────────────────────
    print()
    for type_name in QUERIES:
        drv_results = all_results.get(type_name, {})
        valid = {k: v for k, v in drv_results.items() if "error" not in v}
        if not valid:
            continue
        max_rps = max(v["rows_per_second"] for v in valid.values())
        print(f"  [{type_name}]")
        for d in DRIVER_NAMES:
            r = valid.get(d)
            if r:
                _print_bar(d, r["rows_per_second"], max_rps)
        print()

    # ── Detailed timings ───────────────────────────────────────────────────
    print("=" * 68)
    print("  DETAILED TIMINGS")
    print("=" * 68)

    for type_name in QUERIES:
        for driver_name, r in all_results.get(type_name, {}).items():
            if "error" not in r:
                print(
                    f"  {type_name:20s}  {driver_name:20s}  "
                    f"{r['query_time']:.4f}s  |  "
                    f"{fmt_rps(r['rows_per_second']):>12s} rows/s  |  "
                    f"{fmt_num(r['row_count'])} rows"
                )
            else:
                print(
                    f"  {type_name:20s}  {driver_name:20s}  "
                    f"ERROR - {r['error']}"
                )


if __name__ == "__main__":
    asyncio.run(run_performance_test())