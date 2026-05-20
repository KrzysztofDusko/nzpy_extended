"""
Extended ODBC parity tests ported from Node.js OdbcComparison.test.js (~727 queries).
Run explicitly: pytest tests/test_odbc_comparison_node.py -m odbc_node
"""

import pytest

from test_odbc_comparison import (
    compare_rows,
    _odbc_conn,
    _nzpy_conn,
)
from odbc_queries_node import QUERIES_NODE

pytestmark = [pytest.mark.full, pytest.mark.odbc_node]


def _skip_nvarchar_linux(sql: str) -> None:
    import sys
    if sys.platform != "linux":
        return
    if "::nchar" in sql.lower() or "::nvarchar" in sql.lower():
        pytest.skip("NCHAR/NVARCHAR ODBC parity skipped on Linux (node-odbc limitation)")


def _skip_known_odbc_gaps(sql: str) -> None:
    """Skip queries where ODBC driver has known gaps (returns 0 rows or tables missing)."""
    sql_upper = sql.upper()

    missing_tables = [
        "JUST_DATA.ADMIN.CUSTOMERADDRESS",
        "JUST_DATA.ADMIN.CUSTOMERDATA",
    ]
    for tb in missing_tables:
        if tb in sql_upper:
            pytest.skip(f"Table {tb} does not exist in this environment")

    if "_T_USER" in sql_upper or "_V_USER" in sql_upper:
        pytest.skip("ODBC returns 0 rows for _T_USER/_V_USER on this environment")

    if "'::DATE" in sql_upper or "'::TIME" in sql_upper:
        pytest.skip("ODBC returns 0 rows for DATE/TIME literal cast (type conversion gap)")

    if "CURRENT_DATE" in sql_upper or "CURRENT_TIMESTAMP" in sql_upper:
        if " FROM " not in sql_upper:
            pytest.skip("ODBC returns 0 rows for CURRENT_DATE/TIMESTAMP without FROM")


@pytest.mark.parametrize("sql", QUERIES_NODE)
@pytest.mark.asyncio
@pytest.mark.timeout(600)  # 10 min timeout per query
async def test_node_query_matches_odbc(sql):
    _skip_nvarchar_linux(sql)
    _skip_known_odbc_gaps(sql)
    odbc_con = _odbc_conn()
    nzpy_con = await _nzpy_conn()
    try:
        nz_cur = nzpy_con.cursor()
        odbc_cur = odbc_con.cursor()
        try:
            await nz_cur.execute(sql)
            nz_rows = await nz_cur.fetchall()
            odbc_cur.execute(sql)
            from test_odbc_comparison import _odbc_safe_fetchall
            odbc_rows = _odbc_safe_fetchall(odbc_cur)
            compare_rows(nz_rows, odbc_rows, sql)
        finally:
            await nz_cur.close()
            odbc_cur.close()
    finally:
        odbc_con.close()
        await nzpy_con.close()
