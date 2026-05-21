import asyncio
import inspect
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import nzpy_extended as nzpy
import nzpy_extended.sync as sync_nzpy
from nzpy_extended.pool import SyncPool, NullPool, AsyncNullPool

pytestmark = pytest.mark.smoke


@pytest.fixture
def synccon(db_kwargs_fn):
    """Fresh sync connection, closed after every test."""
    conn = sync_nzpy.connect(**db_kwargs_fn)
    yield conn
    try:
        conn.close()
    except Exception:
        pass


def _drop_table(conn, table_name):
    """Safely drop a table, ignoring errors if it doesn't exist."""
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE {table_name}")
    except Exception:
        pass


class TestSyncBasic:
    """Test 1: sync API (basic operations)."""

    TABLE = "test_nzpy_sync_basic"

    def test_execute_fetchone(self, synccon):
        with synccon.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 1

    def test_connection_context_manager(self, db_kwargs_fn):
        with sync_nzpy.connect(**db_kwargs_fn) as conn:
            _drop_table(conn, self.TABLE)
            with conn.cursor() as cur:
                cur.execute(f"CREATE TABLE {self.TABLE} (id INT, name VARCHAR(50))")
                cur.execute(f"INSERT INTO {self.TABLE} VALUES (?, ?)", (1, "Alice"))
                cur.execute(f"SELECT * FROM {self.TABLE} WHERE id = 1")
                row = cur.fetchone()
                assert row[0] == 1
                assert row[1] == "Alice"
            _drop_table(conn, self.TABLE)

    def test_cleanup(self, db_kwargs_fn):
        with sync_nzpy.connect(**db_kwargs_fn) as conn:
            _drop_table(conn, self.TABLE)


class TestSyncIteration:
    """Test 3: cursor iteration (__iter__)."""

    TABLE = "test_nzpy_sync_iter"

    def test_cursor_iteration(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT, name VARCHAR(50))")
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?, ?)", (1, "Alice"))
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?, ?)", (2, "Bob"))

        with synccon.cursor() as cur:
            cur.execute(f"SELECT * FROM {self.TABLE} ORDER BY id")
            rows = []
            for row in cur:
                rows.append(row)
            assert len(rows) == 2
            assert rows[0][0] == 1
            assert rows[1][0] == 2
        _drop_table(synccon, self.TABLE)

    def test_cleanup(self, synccon):
        _drop_table(synccon, self.TABLE)


class TestSyncPool:
    """Test 4: SyncPool."""

    def test_pool_acquire_release(self, db_kwargs_fn):
        pool = SyncPool(min_size=1, max_size=5, **db_kwargs_fn)
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            stats = pool.get_stats()
            assert stats["pool_size"] >= 1
            assert stats["pool_in_use"] == 0
        finally:
            pool.close_all()

    def test_pool_context_manager(self, db_kwargs_fn):
        with SyncPool(min_size=1, max_size=5, **db_kwargs_fn) as pool:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            stats = pool.get_stats()
            assert stats["pool_closed"] is False

    def test_pool_stats(self, db_kwargs_fn):
        pool = SyncPool(min_size=2, max_size=5, **db_kwargs_fn)
        try:
            stats = pool.get_stats()
            assert "pool_min" in stats
            assert "pool_max" in stats
            assert "pool_size" in stats
            assert "pool_available" in stats
            assert "pool_in_use" in stats
            assert "pool_closed" in stats
            assert stats["pool_min"] == 2
            assert stats["pool_closed"] is False
        finally:
            pool.close_all()


class TestNullPool:
    """Test 5: NullPool."""

    def test_nullpool(self, db_kwargs_fn):
        pool = NullPool(**db_kwargs_fn)
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        stats = pool.get_stats()
        assert stats["type"] == "NullPool"

    def test_nullpool_context_manager(self, db_kwargs_fn):
        with NullPool(**db_kwargs_fn) as pool:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")


class TestAsyncRegression:
    """Test 6: async API still works (no regression)."""

    @pytest.mark.asyncio
    async def test_async_connect_and_query(self, db_kwargs_fn):
        async with await nzpy.connect(**db_kwargs_fn) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                row = await cur.fetchone()
                assert row is not None
                assert row[0] == 1

    @pytest.mark.asyncio
    async def test_async_context_manager_on_close(self, db_kwargs_fn):
        conn = await nzpy.connect(**db_kwargs_fn)
        cur = conn.cursor()
        await cur.execute("SELECT 1")
        assert (await cur.fetchone()) is not None
        await conn.close()

    @pytest.mark.asyncio
    async def test_asyncnullpool(self, db_kwargs_fn):
        pool = AsyncNullPool(**db_kwargs_fn)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                row = await cur.fetchone()
                assert row is not None
        stats = pool.get_stats()
        assert stats["type"] == "AsyncNullPool"


class TestPortDefaults:
    """Test 7: default port is 5480."""

    def test_async_connect_port_default(self):
        sig_async = inspect.signature(nzpy.connect)
        assert sig_async.parameters["port"].default == 5480

    def test_sync_connect_port_default(self):
        sig_sync = inspect.signature(sync_nzpy.connect)
        assert sig_sync.parameters["port"].default == 5480


class TestSyncExecutemany:
    """Test executemany on sync cursor."""

    TABLE = "test_nzpy_sync_emany"

    def test_executemany(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT, name VARCHAR(50))")
            cur.executemany(
                f"INSERT INTO {self.TABLE} VALUES (?, ?)",
                [(1, "Alice"), (2, "Bob"), (3, "Charlie")]
            )
            cur.execute(f"SELECT COUNT(*) FROM {self.TABLE}")
            row = cur.fetchone()
            assert row[0] == 3
        _drop_table(synccon, self.TABLE)

    def test_cleanup(self, synccon):
        _drop_table(synccon, self.TABLE)


class TestSyncFetchMany:
    """Test fetchmany on sync cursor."""

    TABLE = "test_nzpy_sync_fmany"

    def test_fetchmany(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT)")
            for i in range(5):
                cur.execute(f"INSERT INTO {self.TABLE} VALUES (?)", (i,))
            cur.execute(f"SELECT * FROM {self.TABLE} ORDER BY id")
            rows = cur.fetchmany(3)
            assert len(rows) == 3
            more = cur.fetchmany(10)
            assert len(more) == 2
        _drop_table(synccon, self.TABLE)

    def test_cleanup(self, synccon):
        _drop_table(synccon, self.TABLE)


class TestSyncDescription:
    """Test description property on sync cursor."""

    def test_description(self, synccon):
        with synccon.cursor() as cur:
            cur.execute("SELECT 1 AS col1, 2 AS col2")
            desc = cur.description
            assert desc is not None
            assert len(desc) == 2
            assert desc[0][0].upper() == "COL1"
            assert desc[1][0].upper() == "COL2"


class TestSyncRowcount:
    """Test rowcount property on sync cursor."""

    TABLE = "test_nzpy_sync_rcount"

    def test_rowcount(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT)")
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?)", (1,))
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?)", (2,))
            cur.execute(f"SELECT * FROM {self.TABLE}")
            rows = cur.fetchall()
            assert len(rows) >= 2
        _drop_table(synccon, self.TABLE)

    def test_cleanup(self, synccon):
        _drop_table(synccon, self.TABLE)


class TestSyncNextset:
    """Test nextset on sync cursor."""

    TABLE = "test_nzpy_sync_ns"

    def test_nextset(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT, name VARCHAR(50))")
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?, ?)", (1, "Alice"))
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?, ?)", (2, "Bob"))
            cur.execute(f"SELECT id FROM {self.TABLE} ORDER BY id")
            rows = cur.fetchall()
            assert len(rows) >= 2
        _drop_table(synccon, self.TABLE)

    def test_cleanup(self, synccon):
        _drop_table(synccon, self.TABLE)
