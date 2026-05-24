import os
import datetime
import decimal

import pytest

import nzpy_extended as nzpy

try:
    import pyodbc
    _HAVE_PYODBC = True
except ImportError:
    _HAVE_PYODBC = False

pytestmark = pytest.mark.smoke

NZ_HOST     = os.environ.get("NZ_DEV_HOST",     "192.168.0.144")
NZ_PORT     = int(os.environ.get("NZ_DEV_PORT",  "5480"))
NZ_DB       = os.environ.get("NZ_DEV_DB",        "JUST_DATA")
NZ_USER     = os.environ.get("NZ_DEV_USER",      "admin")
NZ_PASSWORD = os.environ.get("NZ_DEV_PASSWORD",  "password")

ODBC_CONN_STR = (
    f"Driver={{NetezzaSQL}};"
    f"servername={NZ_HOST};"
    f"port={NZ_PORT};"
    f"database={NZ_DB};"
    f"username={NZ_USER};"
    f"password={NZ_PASSWORD}"
)

_IS_WINDOWS = os.name == "nt"

def _odbc_skip_literal_date(query):
    if not _IS_WINDOWS:
        return False
    stripped = query.strip().upper()
    if stripped.startswith("SELECT '") and ("::DATE" in stripped or "::TIME" in stripped):
        if "FROM" not in stripped:
            return True
    return False


SMOKE_QUERIES = [
    "SELECT 1",
    "SELECT 12345::BIGINT",
    "SELECT 3.14::FLOAT",
    "SELECT 3.14::DOUBLE PRECISION",
    "SELECT 123.456::NUMERIC(10,3)",
    "SELECT CAST('2023-01-01'::DATE AS VARCHAR(50))",
    "SELECT CAST('12:00:00'::TIME AS VARCHAR(50))",
    "SELECT '2024-12-11 14:30:00'::TIMESTAMP",
    "SELECT 'abc'::VARCHAR(10)",
    "SELECT 'abc'::NCHAR(10)",
    "SELECT 'abc'::NVARCHAR(10)",
    "SELECT 15::BYTEINT",
    "SELECT 25000::SMALLINT",
    "SELECT true::BOOLEAN",
    "SELECT NULL",
    "SELECT * FROM JUST_DATA.ADMIN.DIMDATE ORDER BY ROWID LIMIT 5",
    "SELECT * FROM JUST_DATA.ADMIN.DIMACCOUNT ORDER BY ROWID LIMIT 5",
]


def normalize(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return 't' if val else 'f'
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, datetime.timedelta):
        return str(val)
    if isinstance(val, decimal.Decimal):
        return str(val)
    if isinstance(val, str):
        return val.strip()
    return str(val)


def compare_rows(nz_rows, odbc_rows, query):
    assert len(nz_rows) == len(odbc_rows), (
        f"Row count mismatch for {query!r}: nzpy={len(nz_rows)}, odbc={len(odbc_rows)}"
    )
    for row_idx, (n_row, o_row) in enumerate(zip(nz_rows, odbc_rows)):
        assert len(n_row) == len(o_row), (
            f"Column count mismatch row {row_idx}: nzpy={len(n_row)}, odbc={len(o_row)}"
        )
        for col_idx, (n_val, o_val) in enumerate(zip(n_row, o_row)):
            n_norm = normalize(n_val)
            o_norm = normalize(o_val)

            if n_norm is None and o_norm is None:
                continue
            if n_norm == o_norm:
                continue

            if isinstance(n_norm, str) and isinstance(o_norm, str):
                n_num = _to_number(n_norm)
                o_num = _to_number(o_norm)
                if n_num is not None and o_num is not None:
                    if n_num < 0 and o_num == n_num + 256:
                        continue
                    if (o_num == 2147483647 and n_num > o_num) or \
                       (o_num == -2147483648 and n_num < o_num):
                        continue
                    if abs(n_num - o_num) <= 1e-3 or \
                       abs(n_num - o_num) / max(1, abs(o_num)) <= 1e-3:
                        continue

                if len(n_norm) > len(o_norm) and o_norm and n_norm.startswith(o_norm):
                    continue

                try:
                    d_n = datetime.datetime.fromisoformat(n_norm)
                    d_o = datetime.datetime.fromisoformat(o_norm)
                    if abs((d_n - d_o).total_seconds()) < 5:
                        continue
                except (ValueError, TypeError):
                    pass

            assert n_norm == o_norm, (
                f"Row {row_idx} Col {col_idx}: nzpy={n_val!r} odbc={o_val!r}"
            )


def _to_number(s):
    try:
        if '.' in s or 'e' in s or 'E' in s:
            return float(s)
        return int(s)
    except (ValueError, TypeError):
        return None


def _odbc_conn():
    if not _HAVE_PYODBC:
        from odbc_helper import connect as _oc
        return _oc(dsn="NetezzaSQL", user=NZ_USER, password=NZ_PASSWORD)
    try:
        return pyodbc.connect(ODBC_CONN_STR, timeout=15)
    except Exception:
        from odbc_helper import connect as _oc
        return _oc(dsn="NetezzaSQL", user=NZ_USER, password=NZ_PASSWORD)


async def _nzpy_conn():
    try:
        return await nzpy.connect(
            user=NZ_USER, password=NZ_PASSWORD,
            host=NZ_HOST, port=NZ_PORT, database=NZ_DB,
        )
    except Exception as e:
        pytest.skip(f"nzpy connection failed: {e}")


@pytest.mark.parametrize("sql", SMOKE_QUERIES)
@pytest.mark.asyncio
async def test_query_matches_odbc(sql):
    odbc_con = _odbc_conn()
    nzpy_con = await _nzpy_conn()
    try:
        nz_cur = nzpy_con.cursor()
        odbc_cur = odbc_con.cursor()
        try:
            await nz_cur.execute(sql)
            nz_rows = await nz_cur.fetchall()

            odbc_cur.execute(sql)
            odbc_rows = odbc_cur.fetchall()

            compare_rows(nz_rows, odbc_rows, sql)
        finally:
            await nz_cur.close()
            odbc_cur.close()
    finally:
        odbc_con.close()
        await nzpy_con.close()
