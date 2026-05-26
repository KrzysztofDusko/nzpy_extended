import pytest
import nzpy_extended as nzpy

pytestmark = pytest.mark.full

@pytest.mark.asyncio
async def test_select_integer(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 1")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert int(rows[0][0]) == 1


@pytest.mark.asyncio
async def test_select_byteint(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 15::BYTEINT")
    rows = await cursor.fetchall()
    assert int(rows[0][0]) == 15


@pytest.mark.asyncio
async def test_select_smallint(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 1234::SMALLINT")
    rows = await cursor.fetchall()
    assert int(rows[0][0]) == 1234


@pytest.mark.asyncio
async def test_select_bigint(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 9223372036854775807::BIGINT")
    rows = await cursor.fetchall()
    assert int(rows[0][0]) == 9223372036854775807


@pytest.mark.asyncio
async def test_select_float(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 3.14::FLOAT")
    rows = await cursor.fetchall()
    assert abs(float(rows[0][0]) - 3.14) < 0.01


@pytest.mark.asyncio
async def test_select_double(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 3.14159265358979::DOUBLE PRECISION")
    rows = await cursor.fetchall()
    assert abs(float(rows[0][0]) - 3.14159265358979) < 0.0000000001


@pytest.mark.asyncio
async def test_select_numeric(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 12345.6789::NUMERIC(10,4)")
    rows = await cursor.fetchall()
    # Depending on how Python driver parses numeric, it could be decimal or float or string
    assert "12345.6789" in str(rows[0][0]) or abs(float(rows[0][0]) - 12345.6789) < 0.0001


@pytest.mark.asyncio
async def test_select_high_precision_numeric(con):
    cursor = con.cursor()
    await cursor.execute("SELECT 12345678901234567890.1234567890::NUMERIC(38,10)")
    rows = await cursor.fetchall()
    assert "12345678901234567890" in str(rows[0][0])
