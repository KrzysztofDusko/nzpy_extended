"""
Synchronous API for nzpy_extended — thin wrapper over async core.

Usage:
    import nzpy_extended.sync as nzpy

    conn = nzpy.connect(
        user="admin", password="secret",
        host="netezza-host", database="mydb",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM mytable WHERE id = ?", (42,))
        for row in cur:
            print(row)
"""

from ._runner import _runner
from .core import Connection


class SyncCursor:
    """Synchronous cursor — wrapper over async Cursor."""

    def __init__(self, async_cursor):
        self._c = async_cursor

    def execute(self, sql, args=None):
        _runner.run(self._c.execute(sql, args))

    def executemany(self, sql, seq_of_args):
        _runner.run(self._c.executemany(sql, seq_of_args))

    def fetchone(self):
        return _runner.run(self._c.fetchone())

    def fetchmany(self, num=None):
        if num is None:
            num = self.arraysize
        return _runner.run(self._c.fetchmany(num))

    def fetchall(self):
        return _runner.run(self._c.fetchall())

    def nextset(self):
        return _runner.run(self._c.nextset())

    @property
    def rowcount(self):
        return self._c.rowcount

    @property
    def description(self):
        return self._c.description

    @property
    def statusmessage(self):
        return getattr(self._c, 'statusmessage', None)

    @property
    def arraysize(self):
        return self._c.arraysize

    @arraysize.setter
    def arraysize(self, value):
        self._c.arraysize = value

    def close(self):
        _runner.run(self._c.close())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.close()
        except Exception:
            pass

    def __iter__(self):
        while True:
            rows = self.fetchmany()
            if not rows:
                break
            for row in rows:
                yield row

    def setinputsizes(self, *args):
        self._c.setinputsizes(*args)

    def setoutputsize(self, *args):
        self._c.setoutputsize(*args)


class SyncConnection:
    """Synchronous connection — wrapper over async Connection."""

    def __init__(self, async_conn):
        self._conn = async_conn

    def cursor(self):
        return SyncCursor(self._conn.cursor())

    def commit(self):
        _runner.run(self._conn.commit())

    def rollback(self):
        _runner.run(self._conn.rollback())

    def close(self):
        _runner.run(self._conn.close())

    def __del__(self):
        try:
            if self._conn is not None:
                _runner.run(self._conn.close())
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            try:
                self.rollback()
            except Exception:
                pass
        else:
            try:
                self.commit()
            except Exception:
                pass
        try:
            self.close()
        except Exception:
            pass
        return False


async def _async_connect(
    user,
    host,
    unix_sock,
    port,
    database,
    password,
    ssl,
    securityLevel,
    timeout,
    application_name,
    max_prepared_statements,
    datestyle,
    logLevel,
    tcp_keepalive,
    char_varchar_encoding,
    on_connect,
    ssl_verify=True,
    connect_timeout=None,
    **kwargs,
):
    conn = Connection()
    try:
        await conn._connect(
            user=user,
            host=host,
            unix_sock=unix_sock,
            port=port,
            database=database,
            password=password,
            ssl=ssl,
            securityLevel=securityLevel,
            timeout=timeout,
            application_name=application_name,
            max_prepared_statements=max_prepared_statements,
            datestyle=datestyle,
            logLevel=logLevel,
            tcp_keepalive=tcp_keepalive,
            char_varchar_encoding=char_varchar_encoding,
            ssl_verify=ssl_verify,
            connect_timeout=connect_timeout,
            **kwargs,
        )
        if on_connect is not None:
            result = on_connect(SyncConnection(conn))
            if hasattr(result, '__await__'):
                await result
    except Exception:
        try:
            await conn.close()
        except Exception:
            pass
        raise
    return conn


def connect(
    user,
    host="localhost",
    unix_sock=None,
    port=5480,
    database=None,
    password=None,
    ssl=None,
    securityLevel=0,
    timeout=None,
    application_name=None,
    max_prepared_statements=1000,
    datestyle="ISO",
    logLevel=0,
    tcp_keepalive=True,
    char_varchar_encoding="latin",
    on_connect=None,
    ssl_verify=True,
    connect_timeout=None,
    **kwargs,
):
    """Synchronous connection to a Netezza database.

    Example:
        conn = nzpy.sync.connect(
            user="admin", password="secret",
            host="nz-host", database="mydb",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            print(cur.fetchone())
        conn.close()
    """
    async_conn = _runner.run(
        _async_connect(
            user=user,
            host=host,
            unix_sock=unix_sock,
            port=port,
            database=database,
            password=password,
            ssl=ssl,
            securityLevel=securityLevel,
            timeout=timeout,
            application_name=application_name,
            max_prepared_statements=max_prepared_statements,
            datestyle=datestyle,
            logLevel=logLevel,
            tcp_keepalive=tcp_keepalive,
            char_varchar_encoding=char_varchar_encoding,
            on_connect=on_connect,
            ssl_verify=ssl_verify,
            connect_timeout=connect_timeout,
            **kwargs,
        )
    )
    return SyncConnection(async_conn)
