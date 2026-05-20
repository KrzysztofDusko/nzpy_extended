import datetime
import os
import time

import nzpy_extended as nzpy

import pytest

pytestmark = pytest.mark.full

@pytest.fixture
def has_tzset():

    # Neither Windows nor Jython 2.5.3 have a time.tzset() so skip
    if hasattr(time, 'tzset'):
        os.environ['TZ'] = "UTC"
        time.tzset()
        return True
    return False


# DBAPI compatible interface tests
@pytest.fixture
async def db_table(con, has_tzset):
    cursor = con.cursor()
    try:
        await cursor.execute("DROP TABLE nzpy_test_t1")
    except Exception:
        pass

    await cursor.execute(
        "CREATE TABLE nzpy_test_t1 "
        "(f1 int primary key, f2 int not null, f3 varchar(50) null) "
        )
    await cursor.execute(
        "INSERT INTO nzpy_test_t1 (f1, f2, f3) VALUES (?, ?, ?)", (1, 1, ''))
    await cursor.execute(
        "INSERT INTO nzpy_test_t1 (f1, f2, f3) VALUES (?, ?, ?)", (2, 10, ''))
    await cursor.execute(
        "INSERT INTO nzpy_test_t1 (f1, f2, f3) VALUES (?, ?, ?)", (3, 100, ''))
    await cursor.execute(
        "INSERT INTO nzpy_test_t1 (f1, f2, f3) VALUES (?, ?, ?)", (4, 1000, ''))
    await cursor.execute(
        "INSERT INTO nzpy_test_t1 (f1, f2, f3) VALUES (?, ?, ?)",
        (5, 10000, ''))
    
    yield con

    try:
        await cursor.execute("DROP TABLE nzpy_test_t1")
    except Exception:
        pass


@pytest.mark.skip(reason="Netezza protocol does not support multiplexing concurrent active queries on a single connection without portals.")
@pytest.mark.asyncio
async def test_parallel_queries(db_table):
    c1 = db_table.cursor()
    c2 = db_table.cursor()

    await c1.execute("SELECT f1, f2, f3 FROM nzpy_test_t1")
    while 1:
        row = await c1.fetchone()
        if row is None:
            break
        f1, f2, f3 = row
        await c2.execute("SELECT f1, f2, f3 FROM nzpy_test_t1 WHERE f1 > ?", (f1,))
        while 1:
            row = await c2.fetchone()
            if row is None:
                break
            f1, f2, f3 = row
    await c1.execute("drop table nzpy_test_t1")


@pytest.mark.asyncio
async def test_qmark(db_table):
    orig_paramstyle = nzpy.paramstyle
    try:
        nzpy.paramstyle = "qmark"
        c1 = db_table.cursor()
        await c1.execute("SELECT f1, f2, f3 FROM nzpy_test_t1 WHERE f1 > ?", (3,))
        while 1:
            row = await c1.fetchone()
            if row is None:
                break
            f1, f2, f3 = row
        await c1.execute("drop table nzpy_test_t1")
    finally:
        nzpy.paramstyle = orig_paramstyle


@pytest.mark.asyncio
async def test_arraysize(db_table):
    c1 = db_table.cursor()
    c1.arraysize = 3
    await c1.execute("SELECT * FROM nzpy_test_t1")
    retval = await c1.fetchmany()
    assert len(retval) == c1.arraysize
    await c1.execute("drop table nzpy_test_t1")


def test_date():
    val = nzpy.Date(2001, 2, 3)
    assert val == datetime.date(2001, 2, 3)


def test_time():
    val = nzpy.Time(4, 5, 6)
    assert val == datetime.time(4, 5, 6)


def test_timestamp():
    val = nzpy.Timestamp(2001, 2, 3, 4, 5, 6)
    assert val == datetime.datetime(2001, 2, 3, 4, 5, 6)


def test_date_from_ticks(has_tzset):
    if has_tzset:
        val = nzpy.DateFromTicks(1173804319)
        assert val == datetime.date(2007, 3, 13)


def testTimeFromTicks(has_tzset):
    if has_tzset:
        val = nzpy.TimeFromTicks(1173804319)
        assert val == datetime.time(16, 45, 19)


def test_timestamp_from_ticks(has_tzset):
    if has_tzset:
        val = nzpy.TimestampFromTicks(1173804319)
        assert val == datetime.datetime(2007, 3, 13, 16, 45, 19)


def test_binary():
    v = nzpy.Binary(b"\x00\x01\x02\x03\x02\x01\x00")
    assert v == b"\x00\x01\x02\x03\x02\x01\x00"
    assert isinstance(v, nzpy.BINARY)


@pytest.mark.asyncio
async def test_row_count(db_table):
    async with db_table.cursor() as c1:
        await c1.execute("SELECT count(*) FROM nzpy_test_t1")

        assert [5] == (await c1.fetchall())[0]

        await c1.execute("UPDATE nzpy_test_t1 SET f3 = ? WHERE f2 > 101", ("Hello!",))
        assert 2 == c1.rowcount

        await c1.execute("DELETE FROM nzpy_test_t1")
        assert 5 == c1.rowcount


@pytest.mark.asyncio
async def test_fetch_many(db_table):
    async with db_table.cursor() as cursor:
        cursor.arraysize = 2
        await cursor.execute("SELECT * FROM nzpy_test_t1")
        assert 2 == len(await cursor.fetchmany())
        assert 2 == len(await cursor.fetchmany())
        assert 1 == len(await cursor.fetchmany())
        assert 0 == len(await cursor.fetchmany())


@pytest.mark.asyncio
async def test_iterator(db_table):
    async with db_table.cursor() as cursor:
        await cursor.execute("SELECT * FROM nzpy_test_t1 ORDER BY f1")
        f1 = 0
        async for row in cursor:
            next_f1 = row[0]
            assert next_f1 > f1
            f1 = next_f1


# Vacuum can't be run inside a transaction, so we need to turn
# autocommit on.
@pytest.mark.asyncio
async def test_vacuum(con):
    con.autocommit = True
    async with con.cursor() as cursor:
        await cursor.execute("vacuum")


def test_cursor_type(cursor):
    assert str(type(cursor)) == "<class 'nzpy_extended.core.Cursor'>"


'''
def test_prepared_statement(con):
    with con.cursor() as cursor:
        cursor.execute('PREPARE gen_series AS SELECT generate_series(1, 10);')
        cursor.execute('EXECUTE gen_series')
def test_numeric(db_table):
    orig_paramstyle = nzpy.paramstyle
    try:
        nzpy.paramstyle = "numeric"
        with db_table.cursor() as c1:
            c1.execute("SELECT f1, f2, f3 FROM nzpy_test_t1 WHERE f1 > :1", (3,))
            while 1:
                row = c1.fetchone()
                if row is None:
                    break
                f1, f2, f3 = row
    finally:
        nzpy.paramstyle = orig_paramstyle
def test_named(db_table):
    orig_paramstyle = nzpy.paramstyle
    try:
        nzpy.paramstyle = "named"
        with db_table.cursor() as c1:
            c1.execute(
                "SELECT f1, f2, f3 FROM nzpy_test_t1 WHERE f1 > :f1", {"f1": 3})
            while 1:
                row = c1.fetchone()
                if row is None:
                    break
                f1, f2, f3 = row
    finally:
        nzpy.paramstyle = orig_paramstyle
def test_format(db_table):
    orig_paramstyle = nzpy.paramstyle
    try:
        nzpy.paramstyle = "format"
        with db_table.cursor() as c1:
            c1.execute("SELECT f1, f2, f3 FROM nzpy_test_t1 WHERE f1 > %s", (3,))
            while 1:
                row = c1.fetchone()
                if row is None:
                    break
                f1, f2, f3 = row
    finally:
        nzpy.paramstyle = orig_paramstyle
def test_pyformat(db_table):
    orig_paramstyle = nzpy.paramstyle
    try:
        nzpy.paramstyle = "pyformat"
        with db_table.cursor() as c1:
            c1.execute(
                "SELECT f1, f2, f3 FROM nzpy_test_t1 WHERE f1 > %(f1)s", {"f1": 3})
            while 1:
                row = c1.fetchone()
                if row is None:
                    break
                f1, f2, f3 = row
    finally:
        nzpy.paramstyle = orig_paramstyle
'''
