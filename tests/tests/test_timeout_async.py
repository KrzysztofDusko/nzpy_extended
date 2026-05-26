import asyncio
import time

import pytest

import nzpy_extended as nzpy

pytestmark = pytest.mark.full

HEAVY_SQL = """
    /*OPIS:test_timeout_async*/
    SELECT F1.PRODUCTKEY, COUNT(DISTINCT (F1.PRODUCTKEY / F2.PRODUCTKEY))
    FROM
    ( SELECT * FROM JUST_DATA..FACTPRODUCTINVENTORY LIMIT 30000) F1,
    ( SELECT * FROM JUST_DATA..FACTPRODUCTINVENTORY LIMIT 30000) F2
    GROUP BY 1
    LIMIT 500
"""

READER_HEAVY_SQL = """
    /*OPIS:test_timeout_async_reader*/
    SELECT 2, F1.*
    FROM JUST_DATA..FACTPRODUCTINVENTORY F1
    JOIN JUST_DATA..DIMDATE D1 ON 1=1
    LIMIT 50000000
"""


@pytest.mark.asyncio
async def test_command_timeout(con):
    cursor = con.cursor()
    start = asyncio.get_event_loop().time()
    try:
        await cursor.execute(HEAVY_SQL, timeout=3.0)
        await cursor.fetchall()
        pytest.fail("Query should have timed out")
    except nzpy.OperationalError as e:
        elapsed = asyncio.get_event_loop().time() - start
        assert "timeout" in str(e).lower()
        assert elapsed < 10.0


@pytest.mark.asyncio
async def test_manual_cancel(con):
    cursor = con.cursor()

    async def run_long():
        try:
            await cursor.execute(HEAVY_SQL)
            await cursor.fetchall()
        except Exception:
            pass

    task = asyncio.create_task(run_long())
    await asyncio.sleep(1.0)
    await con.cancel()
    await task


@pytest.mark.asyncio
async def test_temp_table_alive_after_cancel(con):
    cursor = con.cursor()
    await cursor.execute("CREATE TEMP TABLE temp_cancel_py (id INT)")
    await cursor.execute("INSERT INTO temp_cancel_py VALUES (1)")

    error = None

    async def run_long():
        nonlocal error
        try:
            c2 = con.cursor()
            await c2.execute(HEAVY_SQL)
            await c2.fetchall()
        except Exception as e:
            error = e

    task = asyncio.create_task(run_long())
    await asyncio.sleep(1.0)
    await con.cancel()
    await task

    assert error is not None
    await cursor.execute("SELECT COUNT(*) FROM temp_cancel_py")
    rows = []
    async for row in cursor:
        rows.append(row)
    assert rows[0][0] == 1


@pytest.mark.asyncio
async def test_multiple_cancels_preserve_session(con):
    cursor = con.cursor()
    await cursor.execute("CREATE TEMP TABLE abc_cancel_py AS (SELECT 1 AS col1)")

    for i in range(3):
        error = None

        async def run_heavy():
            nonlocal error
            try:
                c2 = con.cursor()
                await c2.execute(HEAVY_SQL)
                await c2.fetchall()
            except Exception as e:
                error = e

        task = asyncio.create_task(run_heavy())
        await asyncio.sleep(1.0)
        await con.cancel()
        await task
        assert error is not None, f"Iteration {i+1} should have been cancelled"

    await cursor.execute("SELECT col1 FROM abc_cancel_py")
    rows = []
    async for row in cursor:
        rows.append(row)
    assert rows[0][0] == 1


# ---------------------------------------------------------------------------
# Cancel during active reader — mirrors Node.js CancelTests.test.js
# "Should cancel active reader and execute next SQL within SLA"
# and C# CommandAbortTest.cs CancelDuringReaderRead_Test
# ---------------------------------------------------------------------------

CANCEL_SLA = 2.0  # seconds — same as Node.js/C# reference


@pytest.mark.asyncio
async def test_cancel_during_reader_next_sql_sla(con):
    """Cancel while actively reading rows; verify next simple SQL executes
    within SLA and session state (temp table) survives."""
    cursor = con.cursor()
    await cursor.execute("CREATE TEMP TABLE tt1 (column_one INT)")
    await cursor.execute("INSERT INTO tt1 VALUES (1)")

    error = None

    async def run_heavy():
        nonlocal error
        try:
            c2 = con.cursor()
            await c2.execute(READER_HEAVY_SQL)
            async for _row in c2:
                pass
        except Exception as e:
            error = e

    task = asyncio.create_task(run_heavy())
    await asyncio.sleep(1.0)

    t0 = time.monotonic()
    await con.cancel()
    await task

    assert error is not None, "Cancel should have interrupted the reader"

    # Next simple SQL must complete within SLA
    await cursor.execute("SELECT column_one FROM tt1")
    row = await cursor.fetchone()
    elapsed = time.monotonic() - t0
    assert elapsed < CANCEL_SLA, f"Next SQL after cancel took {elapsed:.2f}s (SLA: {CANCEL_SLA}s)"
    assert row[0] == 1


@pytest.mark.asyncio
async def test_reader_close_after_cancel_sla(con):
    """Cancel while reading; verify reader close completes within SLA
    and session survives.  Mirrors Node.js CancelTests.test.js
    "Reader close after cancel should complete quickly" and
    C# CommandAbortTest.cs ReaderCloseAfterCancel_CompletesWithinSla_Test."""
    cursor = con.cursor()
    await cursor.execute("DROP TABLE tt2 IF EXISTS")
    await cursor.execute("CREATE TEMP TABLE tt2 (column_one INT)")
    await cursor.execute("INSERT INTO tt2 VALUES (1)")

    error = None

    async def run_heavy():
        nonlocal error
        c2 = None
        try:
            c2 = con.cursor()
            await c2.execute(READER_HEAVY_SQL)
            async for _row in c2:
                pass
        except Exception as e:
            error = e
            return c2

    task = asyncio.create_task(run_heavy())
    await asyncio.sleep(1.0)
    await con.cancel()
    c2 = await task

    assert error is not None, "Cancel should have interrupted the reader"

    t0 = time.monotonic()
    # Close the reader cursor (should complete quickly even after cancel)
    if c2 is not None:
        await c2.close()
    elapsed = time.monotonic() - t0
    assert elapsed < CANCEL_SLA, f"Close after cancel took {elapsed:.2f}s (SLA: {CANCEL_SLA}s)"

    # Session state must survive
    await cursor.execute("SELECT column_one FROM tt2")
    row = await cursor.fetchone()
    assert row[0] == 1
