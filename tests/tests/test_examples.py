"""Verify that patterns from examples/ files actually work."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import nzpy_extended as nzpy
import nzpy_extended.sync as sync_nzpy
from nzpy_extended import SyncPool

pytestmark = pytest.mark.smoke


@pytest.fixture
def synccon(db_kwargs_fn):
    conn = sync_nzpy.connect(**db_kwargs_fn)
    yield conn
    try:
        conn.close()
    except Exception:
        pass


class TestExample13SyncBasic:
    """Verify patterns from examples/13_sync_basic.py."""

    def test_basic_query(self, synccon):
        cur = synccon.cursor()
        cur.execute("SELECT 1")
        row = cur.fetchone()
        assert row is not None

    def test_chaining(self, synccon):
        row = synccon.execute("SELECT 1 AS col1, 'hello' AS col2, 3.14 AS col3").fetchone()
        assert row[0] == 1

    def test_oneshot(self, synccon):
        row = synccon.execute("SELECT 2 + 3").fetchone()
        assert row[0] == 5

    def test_iteration(self, synccon):
        TABLE = "test_ex13_iter"
        _drop_table(synccon, TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TEMP TABLE {TABLE} (id INT)")
            for i in range(5):
                cur.execute(f"INSERT INTO {TABLE} VALUES (?)", (i,))
        cur = synccon.cursor()
        cur.execute(f"SELECT id FROM {TABLE} ORDER BY id")
        rows = []
        for row in cur:
            rows.append(row)
        assert len(rows) == 5
        _drop_table(synccon, TABLE)


class TestExample14SyncTransactions:
    """Verify patterns from examples/14_sync_transactions.py."""

    TABLE = "test_ex14_tx"

    def test_autocommit_false_commit(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT, label VARCHAR(50))")
        synccon.autocommit = False
        with synccon.cursor() as cur:
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?, ?)", (1, "alpha"))
        synccon.commit()
        synccon.autocommit = True
        row = synccon.execute(f"SELECT id FROM {self.TABLE}").fetchone()
        assert row[0] == 1
        _drop_table(synccon, self.TABLE)

    def test_transaction_context_manager(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT)")
        with synccon.transaction():
            with synccon.cursor() as cur:
                cur.execute(f"INSERT INTO {self.TABLE} VALUES (?)", (42,))
        row = synccon.execute(f"SELECT id FROM {self.TABLE}").fetchone()
        assert row[0] == 42
        _drop_table(synccon, self.TABLE)

    def test_rollback_on_error(self, synccon):
        _drop_table(synccon, self.TABLE)
        with synccon.cursor() as cur:
            cur.execute(f"CREATE TABLE {self.TABLE} (id INT)")
        synccon.autocommit = False
        with synccon.cursor() as cur:
            cur.execute(f"INSERT INTO {self.TABLE} VALUES (?)", (99,))
        synccon.rollback()
        synccon.autocommit = True
        row = synccon.execute(f"SELECT COUNT(*) FROM {self.TABLE}").fetchone()
        assert row[0] == 0
        _drop_table(synccon, self.TABLE)


class TestExample15SyncTimeout:
    """Verify patterns from examples/15_sync_timeout.py."""

    def test_conn_timeout_property(self, synccon):
        conn = synccon
        conn.timeout = 10.0
        c = conn.cursor()
        assert c.timeout == 10.0
        conn.timeout = None
        c = conn.cursor()
        assert c.timeout is None

    def test_cursor_timeout_property(self, synccon):
        c = synccon.cursor()
        c.timeout = 30.0
        assert c.timeout == 30.0
        c.timeout = 0
        assert c.timeout == 0

    def test_explicit_timeout_succeeds(self, synccon):
        synccon.execute("SELECT 1", timeout=10.0).fetchone()

    def test_timeout_disabled(self, synccon):
        c = synccon.cursor()
        c.timeout = 0
        c.execute("SELECT 1")
        c.fetchone()
        synccon.timeout = None
        c2 = synccon.cursor()
        c2.execute("SELECT 1")


class TestExample16SyncCallproc:
    """Verify patterns from examples/16_sync_callproc.py."""

    PROC_ADD = "test_ex16_add"
    PROC_NOOP = "test_ex16_noop"
    PROC_NOTICE = "test_ex16_notice"

    def _create_add_proc(self, cur):
        cur.execute(f"""
            CREATE OR REPLACE PROCEDURE {self.PROC_ADD}(INTEGER, INTEGER)
            RETURNS INTEGER
            EXECUTE AS OWNER
            LANGUAGE NZPLSQL AS
            BEGIN_PROC
            BEGIN
                RETURN $1 + $2;
            END;
            END_PROC;
        """)

    def _create_noop_proc(self, cur):
        cur.execute(f"""
            CREATE OR REPLACE PROCEDURE {self.PROC_NOOP}()
            RETURNS INTEGER
            EXECUTE AS OWNER
            LANGUAGE NZPLSQL AS
            BEGIN_PROC
            BEGIN
                RETURN 0;
            END;
            END_PROC;
        """)

    def _create_notice_proc(self, cur):
        cur.execute(f"""
            CREATE OR REPLACE PROCEDURE {self.PROC_NOTICE}(INTEGER)
            RETURNS INTEGER
            EXECUTE AS OWNER
            LANGUAGE NZPLSQL AS
            BEGIN_PROC
            BEGIN
                RAISE NOTICE 'Processing value %', $1;
                RETURN $1;
            END;
            END_PROC;
        """)

    def test_callproc_with_params(self, synccon):
        with synccon.cursor() as cur:
            try:
                self._create_add_proc(cur)
            except Exception as e:
                pytest.skip(f"NZPLSQL not available: {e}")
            try:
                result = cur.callproc(self.PROC_ADD, [10, 20])
                assert result == [10, 20]
            finally:
                try:
                    cur.execute(f"DROP PROCEDURE {self.PROC_ADD}(INTEGER)")
                except Exception:
                    pass

    def test_callproc_no_params(self, synccon):
        with synccon.cursor() as cur:
            try:
                self._create_noop_proc(cur)
            except Exception as e:
                pytest.skip(f"NZPLSQL not available: {e}")
            try:
                result = cur.callproc(self.PROC_NOOP)
                assert result is None
            finally:
                try:
                    cur.execute(f"DROP PROCEDURE {self.PROC_NOOP}()")
                except Exception:
                    pass

    def test_notice_in_messages(self, synccon):
        with synccon.cursor() as cur:
            try:
                self._create_notice_proc(cur)
            except Exception as e:
                pytest.skip(f"NZPLSQL not available: {e}")
            try:
                cur.callproc(self.PROC_NOTICE, [99])
                found = any("Processing value 99" in str(m) for m in cur.messages)
                assert found
            finally:
                try:
                    cur.execute(f"DROP PROCEDURE {self.PROC_NOTICE}(INTEGER)")
                except Exception:
                    pass


class TestExample17SyncPool:
    """Verify patterns from examples/17_sync_pool.py."""

    def test_pool_connect_and_query(self, db_kwargs_fn):
        pool = SyncPool(min_size=1, max_size=5, **db_kwargs_fn)
        try:
            with pool.connection() as conn:
                row = conn.execute("SELECT 1").fetchone()
                assert row[0] == 1
        finally:
            pool.close_all()

    def test_pool_acquire_release(self, db_kwargs_fn):
        pool = SyncPool(min_size=1, max_size=5, **db_kwargs_fn)
        try:
            conn = pool.acquire()
            conn.execute("SELECT 1")
            pool.release(conn)
        finally:
            pool.close_all()

    def test_pool_rollback_on_release(self, db_kwargs_fn):
        TABLE = "test_ex17_rollback"
        pool = SyncPool(min_size=1, max_size=5, **db_kwargs_fn)
        try:
            conn0 = pool.acquire()
            conn0.execute(f"CREATE TABLE {TABLE} (x INT)")
            conn0.execute(f"INSERT INTO {TABLE} VALUES (0)")
            pool.release(conn0)

            conn = pool.acquire()
            conn.autocommit = False
            conn.execute(f"INSERT INTO {TABLE} VALUES (99)")
            pool.release(conn)

            conn2 = pool.acquire()
            row = conn2.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()
            assert row[0] == 1
            pool.release(conn2)
        finally:
            pool.close_all()
            # cleanup via separate connection
            conn = sync_nzpy.connect(**db_kwargs_fn)
            _drop_table(conn, TABLE)
            conn.close()

    def test_pool_stats(self, db_kwargs_fn):
        pool = SyncPool(min_size=2, max_size=5, **db_kwargs_fn)
        try:
            stats = pool.get_stats()
            assert "pool_min" in stats
            assert "pool_max" in stats
            assert stats["pool_closed"] is False
        finally:
            pool.close_all()


def _drop_table(conn, table_name):
    try:
        conn.execute(f"DROP TABLE {table_name}")
    except Exception:
        pass
