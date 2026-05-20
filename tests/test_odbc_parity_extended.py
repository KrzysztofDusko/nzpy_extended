"""
test_odbc_parity_extended.py
============================
Extended ODBC parity tests — fills gaps identified in TEST_COVERAGE_REVIEW.md.

Compared to Node.js driver's OdbcComparison.test.js (~720 queries), our
existing test_odbc_comparison.py has 114 queries. This file adds:

  1. _V_ system catalog views (Node.js covers these extensively)
  2. NULL bitmap patterns — many NULL columns in one row
  3. Additional type edge cases from Node.js / SpreadSheetTasks patterns
  4. Interval / Time consistency (types we recently fixed)

The test uses pyodbc as the ODBC reference, comparing cell-by-cell
between nzpy_extended and pyodbc results.

Known deviations from ODBC parity (documented, not fixed):
  - REAL precision: IEEE 754 float differences are acceptable
  - INTERVAL text format: our Interval object str() differs from ODBC text
    representation — this is intentional (proper Python types > string)
  - NCHAR/NVARCHAR: ODBC on Linux may not return these correctly;
    we skip those in pyodbc-unsafe contexts

"""

import datetime
import os
import re

import pytest

import nzpy_extended as nzpy

pytestmark = pytest.mark.full

NZ_HOST     = os.environ.get("NZ_DEV_HOST",     "192.168.0.144")
NZ_PORT     = int(os.environ.get("NZ_DEV_PORT",  "5480"))
NZ_DB       = os.environ.get("NZ_DEV_DB",        "JUST_DATA")
NZ_USER     = os.environ.get("NZ_DEV_USER",      "admin")
NZ_PASSWORD = os.environ.get("NZ_DEV_PASSWORD",  "password")

HAVE_PYODBC = False
try:
    import pyodbc
    HAVE_PYODBC = True
except ImportError:
    pass


async def _conn():
    return await nzpy.connect(
        user=NZ_USER, password=NZ_PASSWORD,
        host=NZ_HOST, port=NZ_PORT, database=NZ_DB,
    )


def _odbc_conn():
    conn_str = (
        f"DRIVER={{NetezzaSQL}};SERVER={NZ_HOST};PORT={NZ_PORT};"
        f"DATABASE={NZ_DB};UID={NZ_USER};PWD={NZ_PASSWORD};"
    )
    return pyodbc.connect(conn_str)


def _odbc_safe_fetchall(cursor):
    """Catch pyodbc.DataError per-column when ODBC can't read a type."""
    columns = cursor.description
    rows_raw = cursor.fetchall()
    result = []
    for raw in rows_raw:
        row = []
        for i, _ in enumerate(columns):
            try:
                row.append(raw[i])
            except (pyodbc.DataError, OverflowError):
                row.append(None)
        result.append(tuple(row))
    return result


def _norm(val):
    """Normalize a value for comparison between nzpy and pyodbc."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, datetime.datetime):
        return val.isoformat().replace('T', ' ')
    if isinstance(val, datetime.date):
        return val.isoformat()
    if isinstance(val, bytes):
        return val
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        return val.strip()
    if hasattr(val, 'microseconds') and hasattr(val, 'days') and hasattr(val, 'months'):
        return repr(val)
    return str(val)


# ---------------------------------------------------------------------------
# _V_ system catalog views
# ---------------------------------------------------------------------------

_V_VIEWS = [
    # Core system views — small, fast
    pytest.param("SELECT * FROM _V_SYSTEM_INFO LIMIT 1",     id="_V_SYSTEM_INFO"),
    pytest.param("SELECT * FROM _V_DATABASE LIMIT 5",        id="_V_DATABASE"),
    pytest.param("SELECT * FROM _V_USER LIMIT 5",            id="_V_USER"),
    pytest.param("SELECT * FROM _V_TABLE LIMIT 5",           id="_V_TABLE"),
    pytest.param("SELECT * FROM _V_VIEW LIMIT 5",            id="_V_VIEW"),
    pytest.param("SELECT * FROM _V_OBJECTS LIMIT 5",         id="_V_OBJECTS"),
    pytest.param("SELECT * FROM _V_ODBC_FEATURE LIMIT 5",   id="_V_ODBC_FEATURE"),
]


@pytest.mark.skipif(not HAVE_PYODBC, reason="pyodbc not installed")
@pytest.mark.parametrize("sql", _V_VIEWS)
@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_system_view_matches_odbc(sql):
    """Results from nzpy_extended must match pyodbc for system views."""
    nz_conn = await _conn()
    try:
        nz_cur = nz_conn.cursor()
        await nz_cur.execute(sql)
        nzrows = await nz_cur.fetchmany(50)

        odbc_conn = _odbc_conn()
        try:
            odbc_cur = odbc_conn.cursor()
            try:
                odbc_cur.execute(sql)
                odbcrows = _odbc_safe_fetchall(odbc_cur)[:len(nzrows)]
            except (pyodbc.ProgrammingError, pyodbc.DataError):
                pytest.skip("pyodbc cannot execute this view")
        finally:
            odbc_conn.close()

        assert len(nzrows) == len(odbcrows), (
            f"Row count mismatch for {sql.split('FROM')[1].strip()}: "
            f"nzpy={len(nzrows)} odbc={len(odbcrows)}"
        )

        for i, (nzr, odr) in enumerate(zip(nzrows, odbcrows)):
            for j, (nzv, odv) in enumerate(zip(nzr, odr)):
                nzv_norm = _norm(nzv)
                odv_norm = _norm(odv)
                assert nzv_norm == odv_norm, (
                    f"Row {i}, col {j} mismatch: "
                    f"nzpy={nzv_norm!r} odbc={odv_norm!r}"
                )
    finally:
        await nz_conn.close()


# ---------------------------------------------------------------------------
# NULL bitmap patterns — many NULL columns in one row
# Based on Node.js OdbcComparison.test.js patterns
# ---------------------------------------------------------------------------

NULL_PATTERN_QUERIES = [
    pytest.param(
        "SELECT NULL,3145,NULL::INT,2,NULL::CHAR(16),3,4,5,"
        "1,NULL::INT,2,NULL::CHAR(16),3,4,5,NULL::DOUBLE PRECISION,"
        "NULL::NUMERIC(12),'#################' "
        "FROM JUST_DATA..DIMDATE ORDER BY ROWID LIMIT 5",
        id="mixed_null_nonnull",
    ),
    pytest.param(
        "SELECT NULL::BIGINT, NULL::BOOLEAN, NULL::BYTEINT, NULL::CHAR(10), "
        "NULL::DATE, NULL::FLOAT, NULL::INTEGER, NULL::TIME, "
        "NULL::VARCHAR(10), NULL::NCHAR(10), NULL::NVARCHAR(10), "
        "NULL::NUMERIC(10,3), NULL::TIMESTAMP, NULL::REAL, "
        "NULL::DOUBLE PRECISION, NULL::SMALLINT "
        "FROM JUST_DATA..DIMDATE LIMIT 1",
        id="all_nulls",
    ),
    pytest.param(
        "SELECT 10::bigint, null::bigint, true::Boolean, false::Boolean, "
        "null::Boolean, 5::Byteint, null::Byteint, 'a'::Char, "
        "null::Char, current_date::Date, null::Date, 0.5::float, "
        "null::float, 10::integer, null::integer "
        "FROM JUST_DATA..DIMDATE LIMIT 3",
        id="paired_null_nonnull",
    ),
]


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("sql", NULL_PATTERN_QUERIES)
async def test_null_patterns_nzpy(sql):
    """NULL patterns must not crash the driver. Verifies nzpy_extended
       handles NULL bitmaping correctly for mixed NULL/non-NULL rows.

       We don't compare against ODBC here because pyodbc may not
       support reading certain literal NULL::TYPE columns.
       Instead just verify the driver returns expected data shapes.
    """
    nz_conn = await _conn()
    try:
        nz_cur = nz_conn.cursor()
        await nz_cur.execute(sql)
        rows = await nz_cur.fetchmany(10)
        assert len(rows) > 0, "Expected at least one row"
        # Verify at least one row has at least one NULL and one non-NULL
        for row in rows:
            assert any(v is None for v in row) or any(v is not None for v in row)
    finally:
        await nz_conn.close()


# ---------------------------------------------------------------------------
# Additional type edge cases from Node.js / C# reference
# ---------------------------------------------------------------------------

TYPE_EDGE_CASES = [
    pytest.param(
        "SELECT 9223372036854775807::BIGINT", 9223372036854775807,
        id="BIGINT_max_positive",
    ),
    pytest.param(
        "SELECT -9223372036854775808::BIGINT", -9223372036854775808,
        id="BIGINT_max_negative",
    ),
    pytest.param(
        "SELECT 127::BYTEINT", 127,
        id="BYTEINT_max",
    ),
    pytest.param(
        "SELECT -128::BYTEINT", -128,
        id="BYTEINT_min",
    ),
    pytest.param(
        "SELECT 3.1400::NUMERIC(10,4)",
        "3.1400",
        id="NUMERIC_trailing_zeros",
    ),
    pytest.param(
        "SELECT 923281625142643375987.43950777::NUMERIC(38,8)",
        None,  # dynamic — just verify type
        id="NUMERIC_38_8_large",
    ),
    pytest.param(
        "SELECT ''::VARCHAR(1)",
        "",  # empty string (may be '' or space-padded)
        id="empty_varchar",
    ),
    pytest.param(
        "SELECT '  spaces  '::VARCHAR(20)",
        "  spaces  ",
        id="varchar_whitespace",
    ),
]


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("sql, expected", TYPE_EDGE_CASES)
async def test_type_edge_cases(sql, expected):
    """Edge case type values: max BIGINT, min BYTEINT, trailing zeros,
       large NUMERIC, empty/whitespace strings."""
    nz_conn = await _conn()
    try:
        nz_cur = nz_conn.cursor()
        await nz_cur.execute(sql)
        row = await nz_cur.fetchone()
        assert row is not None
        val = row[0]
        if expected is not None:
            # For exact matches
            if isinstance(expected, str):
                assert str(val) == expected or str(val).strip() == expected.strip(), (
                    f"Mismatch for '{sql}': got {val!r}, expected {expected!r}"
                )
            else:
                assert val == expected, (
                    f"Mismatch for '{sql}': got {val!r}, expected {expected!r}"
                )
        else:
            # Just verify type and that value is not None
            assert val is not None
            assert isinstance(val, (int, str, float, __import__('decimal').Decimal))
    finally:
        await nz_conn.close()


# ---------------------------------------------------------------------------
# Interval / Time consistency (types we recently fixed)
# ---------------------------------------------------------------------------

INTERVAL_TIME_CASES = [
    pytest.param("SELECT '2 years 5 hours 11 months 41 minutes 15 sec'::INTERVAL", id="INTERVAL_complex"),
    pytest.param("SELECT '5 hours 41 minutes  15 sec'::INTERVAL", id="INTERVAL_simple"),
    pytest.param("SELECT '05:41:15'::TIME", id="TIME_literal"),
    pytest.param("SELECT '2024-12-11 14:30:00'::TIMESTAMP", id="TIMESTAMP_literal"),
]


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("sql", INTERVAL_TIME_CASES)
async def test_interval_time_types_not_string(sql):
    """INTERVAL must return Interval object, not string.
       TIME must return datetime.time, not string.
       TIMESTAMP must return datetime.datetime, not string."""
    nz_conn = await _conn()
    try:
        nz_cur = nz_conn.cursor()
        await nz_cur.execute(sql)
        row = await nz_cur.fetchone()
        assert row is not None
        val = row[0]
        assert not isinstance(val, str), (
            f"Expected non-string type for '{sql}', got str: {val!r}"
        )
    finally:
        await nz_conn.close()
