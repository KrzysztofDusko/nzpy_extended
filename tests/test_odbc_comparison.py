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

pytestmark = pytest.mark.full

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

QUERIES = [
    "SELECT 10::bigint, null::bigint, true::Boolean, false::Boolean, null::Boolean, "
    "5::Byteint, null::Byteint, 'a'::Char, null::Char, current_date::Date, "
    "null::Date, 0.5::float, null::float, 10::integer, null::integer, "
    "'02:00:00'::TIME, 'abc'::nchar(10), null::nchar(10), 1.54::numeric(30, 6), "
    "null::numeric(30, 6), 'abc'::Nvarchar(10), null::Nvarchar(10), 1.54::real, "
    "null::real, 5::smallint, null::smallint, '10:12:13'::TIME, null::time, "
    "DATE_TRUNC('hour',current_timestamp)::Timestamp, null::Timestamp, "
    "'abc'::varchar(10), null::varchar(10) FROM JUST_DATA..FACTPRODUCTINVENTORY "
    "ORDER BY ROWID ASC LIMIT 1",
    "SELECT 1",
    "SELECT 'abc'",
    "SELECT 12345::BIGINT",
    "SELECT 3.14::FLOAT",
    "SELECT 3.14::DOUBLE PRECISION",
    "SELECT 123.456::NUMERIC(10,3)",
    "SELECT CAST('2023-01-01'::DATE AS VARCHAR(50))",
    "SELECT * FROM JUST_DATA.ADMIN.DIMDATE ORDER BY ROWID ASC LIMIT 5",
    "SELECT CAST('12:00:00'::TIME AS VARCHAR(50))",
    "SELECT CAST('12:00:00'::TIMETZ AS VARCHAR(50))",
    "SELECT NOW()",
    "SELECT * FROM JUST_DATA.ADMIN.DIMDATE ORDER BY ROWID LIMIT 1000",
    "SELECT false::BOOLEAN FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 15::BYTEINT FROM JUST_DATA.ADMIN.DIMDATE ORDER BY ROWID LIMIT 1",
    "SELECT 'ABC'::VARCHAR(10) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 'ABC'::NCHAR(10) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 'ABC'::NVARCHAR(10) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT '2024-12-12'::DATE FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT '2024-12-12'::TIMESTAMP FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT '12:15:17'::TIME FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::NUMERIC(10,4) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::NUMERIC(20,4) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::NUMERIC(30,4) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::NUMERIC(38,8) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 123456789::NUMERIC(38,0) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 923281625142643375987.43950777::numeric(38,8) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT -923281625142643375987.43950777::numeric(38,8) FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::REAL FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::DOUBLE PRECISION FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 3.14::FLOAT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 12345678::INTEGER FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 12345678::INT4 FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT -128::BYTEINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT -125::BYTEINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 127::BYTEINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 25000::SMALLINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT -9223372036854775808::BIGINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 9223372036854775807::BIGINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT 5223372036854775807::BIGINT FROM JUST_DATA.ADMIN.DIMDATE LIMIT 1",
    "SELECT false::BOOLEAN",
    "SELECT 15::BYTEINT",
    "SELECT 'ABC'::VARCHAR(10)",
    "SELECT 'ABC'::NCHAR(10)",
    "SELECT 'ABC'::NVARCHAR(10)",
    "SELECT CAST('2024-12-12'::DATE AS VARCHAR(50))",
    "SELECT '2024-12-12'::TIMESTAMP",
    "SELECT CAST('12:15:17'::TIME AS VARCHAR(50))",
    "SELECT 3.14::NUMERIC(10,4)",
    "SELECT 3.14::NUMERIC(20,4)",
    "SELECT 3.14::NUMERIC(30,4)",
    "SELECT 3.14::NUMERIC(38,8)",
    "SELECT 123456789::NUMERIC(38,0)",
    "SELECT 923281625142643375987.43950777::numeric(38,8)",
    "SELECT -923281625142643375987.43950777::numeric(38,8)",
    "SELECT 3.14::REAL",
    "SELECT 3.14::DOUBLE PRECISION",
    "SELECT 3.14::FLOAT",
    "SELECT 12345678::INTEGER",
    "SELECT 12345678::INT4",
    "SELECT -128::BYTEINT",
    "SELECT -125::BYTEINT",
    "SELECT 127::BYTEINT",
    "SELECT 25000::SMALLINT",
    "SELECT -9223372036854775808::BIGINT",
    "SELECT 9223372036854775807::BIGINT",
    "SELECT 5223372036854775807::BIGINT",
    "SELECT 0, CREATEDATE FROM _V_TABLE ORDER BY CREATEDATE DESC LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMACCOUNT ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMCURRENCY ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMCUSTOMER ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMDEPARTMENTGROUP ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMEMPLOYEE ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMGEOGRAPHY ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMORGANIZATION ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMPRODUCT ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMPRODUCTCATEGORY ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMPRODUCTSUBCATEGORY ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMPROMOTION ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMRESELLER ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMSALESREASON ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMSALESTERRITORY ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.DIMSCENARIO ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTADDITIONALINTERNATIONALPRODUCTDESCRIPTION ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTCALLCENTER ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTCURRENCYRATE ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTFINANCE ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTINTERNETSALES ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTINTERNETSALESREASON ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTPRODUCTINVENTORY ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTRESELLERSALES ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTSALESQUOTA ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.FACTSURVEYRESPONSE ORDER BY ROWID LIMIT 1000",
    "SELECT * FROM JUST_DATA.ADMIN.NEWFACTCURRENCYRATE ORDER BY ROWID LIMIT 1000",
    "SELECT 123,3.14::NUMERIC(20,4), 3.14::FLOAT, CAST(CURRENT_DATE AS VARCHAR(50)), "
    "CAST(CURRENT_TIMESTAMP AS VARCHAR(50)), NULL",
    "SELECT NULL,3145,NULL::INT,2, NULL::CHAR(16),3,4,5,1,NULL::INT,2, NULL::CHAR(16),"
    "3,4,5,NULL::DOUBLE PRECISION,NULL::NUMERIC(12),'#################' "
    "FROM JUST_DATA..DIMDATE ORDER BY ROWID LIMIT 1000",
    "SELECT CAST('2025-01-01 12:00:00'::DATETIME AS VARCHAR(50)), 1,2,3,4::smallint,5,6,7,8,9,10,11,12,"
    "NULL,13,14,15,16,17,18,19,20,CAST(CURRENT_DATE AS VARCHAR(50)),"
    "CAST(CURRENT_DATE AS VARCHAR(50)),CAST(CURRENT_DATE AS VARCHAR(50)),* "
    "FROM FACTPRODUCTINVENTORY FI ORDER BY ROWID LIMIT 1000",
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
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8').strip()
        except UnicodeDecodeError:
            return str(val)
    if isinstance(val, (list, tuple)):
        return ' '.join(str(v) for v in val)
    return str(val)


def _to_number(s):
    try:
        if '.' in s or 'e' in s or 'E' in s:
            return float(s)
        return int(s)
    except (ValueError, TypeError):
        return None


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
                f"Row {row_idx} Col {col_idx}: nzpy={n_val!r} odbc={o_val!r}  [{query[:80]}]"
            )


def _odbc_safe_fetchall(odbc_cur):
    rows = []
    while True:
        try:
            row = odbc_cur.fetchone()
        except pyodbc.DataError:
            continue
        if row is None:
            break
        safe = []
        for i in range(len(row)):
            try:
                safe.append(row[i])
            except pyodbc.DataError:
                safe.append(None)
        rows.append(safe)
    return rows


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


@pytest.mark.parametrize("sql", QUERIES)
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
            odbc_rows = _odbc_safe_fetchall(odbc_cur)

            compare_rows(nz_rows, odbc_rows, sql)
        finally:
            await nz_cur.close()
            odbc_cur.close()
    finally:
        odbc_con.close()
        await nzpy_con.close()
