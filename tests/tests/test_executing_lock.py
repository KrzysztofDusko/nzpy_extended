"""Second execute on same connection drains previous cursor gracefully."""

import asyncio
import os

import pytest

import nzpy_extended as nzpy

pytestmark = pytest.mark.full

CONN_KWARGS = dict(
    user=os.environ.get("NZ_DEV_USER", "admin"),
    password=os.environ.get("NZ_DEV_PASSWORD", "password"),
    host=os.environ.get("NZ_DEV_HOST", "192.168.0.144"),
    port=int(os.environ.get("NZ_DEV_PORT", "5480")),
    database=os.environ.get("NZ_DEV_DB", "JUST_DATA"),
)


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_second_execute_while_fetching_drains_previous():
    """Executing a second query on the same connection while one cursor
    is still fetching must drain the previous generator gracefully,
    allowing the new command to proceed."""
    conn = await nzpy.connect(**CONN_KWARGS)
    try:
        cur = conn.cursor()
        await cur.execute(
            "SELECT * FROM JUST_DATA..DIMDATE ORDER BY ROWID LIMIT 100"
        )
        # Second cursor on same connection — must drain previous generator.
        cur2 = conn.cursor()
        await cur2.execute("SELECT 1")
        row = await cur2.fetchone()
        assert row is not None and row[0] == 1

        # First cursor should yield no more rows (generator drained)
        remaining = await cur.fetchall()
        assert len(remaining) == 0
    finally:
        await conn.close()
