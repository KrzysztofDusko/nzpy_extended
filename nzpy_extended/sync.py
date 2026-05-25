from __future__ import annotations

import socket
from typing import Any, Callable, Literal


from ._runner import runner  # pyright: ignore[reportPrivateUsage]
from .core import Connection


class SyncCursor:
    def __init__(self, async_cursor: Any) -> None:
        self._c: Any = async_cursor

    def execute(self, sql: str, args: Any | None = None) -> None:
        runner.run(self._c.execute(sql, args))

    def executemany(self, sql: str, seq_of_args: list[Any]) -> None:
        runner.run(self._c.executemany(sql, seq_of_args))

    def fetchone(self) -> Any:
        return runner.run(self._c.fetchone())

    def fetchmany(self, num: int | None = None) -> list[Any]:
        if num is None:
            num = self.arraysize
        return runner.run(self._c.fetchmany(num))  # type: ignore[no-any-return]

    def fetchall(self) -> list[Any]:
        return runner.run(self._c.fetchall())  # type: ignore[no-any-return]

    def nextset(self) -> Any:
        return runner.run(self._c.nextset())

    @property
    def rowcount(self) -> int:
        return self._c.rowcount  # type: ignore[no-any-return]

    @property
    def description(self) -> Any:
        return self._c.description

    @property
    def statusmessage(self) -> Any:
        return getattr(self._c, 'statusmessage', None)

    @property
    def arraysize(self) -> int:
        return self._c.arraysize  # type: ignore[no-any-return]

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        self._c.arraysize = value

    def cancel(self, exec_gen: Any = None) -> None:
        runner.run(self._c.cancel(exec_gen))

    def interrupt(self) -> None:
        self.cancel()

    def close(self) -> None:
        try:
            if self._c is not None:
                runner.run(self._c.close())
        finally:
            self._c = None

    def __enter__(self) -> SyncCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __iter__(self) -> Any:
        while True:
            rows = self.fetchmany()
            if not rows:
                break
            for row in rows:
                yield row

    def __repr__(self) -> str:
        return f"<{type(self).__name__} at 0x{id(self):x}>"

    def __del__(self) -> None:
        try:
            self._c = None
        except Exception:
            pass

    def setinputsizes(self, *args: Any) -> None:
        self._c.setinputsizes(*args)

    def setoutputsize(self, *args: Any) -> None:
        self._c.setoutputsize(*args)


class _TransactionContext:
    def __init__(self, conn: SyncConnection) -> None:
        self._conn = conn

    def __enter__(self) -> SyncConnection:
        return self._conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        if self._conn._conn is None:  # pyright: ignore[reportPrivateUsage]
            return False
        if exc_type:
            try:
                self._conn.rollback()
            except Exception:
                pass
        else:
            try:
                self._conn.commit()
            except Exception:
                pass
        return False


class SyncConnection:
    def __init__(self, async_conn: Connection) -> None:
        self._conn: Connection | None = async_conn

    def cursor(self) -> SyncCursor:
        if self._conn is None:
            raise RuntimeError("Connection is closed")
        return SyncCursor(self._conn.cursor())

    def commit(self) -> None:
        if self._conn is not None:
            runner.run(self._conn.commit())

    def rollback(self) -> None:
        if self._conn is not None:
            runner.run(self._conn.rollback())

    def cancel(self, exec_gen: Any = None) -> None:
        if self._conn is not None:
            runner.run(self._conn.cancel(exec_gen))

    def transaction(self) -> _TransactionContext:
        return _TransactionContext(self)

    def close(self) -> None:
        try:
            if self._conn is not None:
                runner.run(self._conn.close())
        finally:
            self._conn = None

    def __repr__(self) -> str:
        status = "closed" if self._conn is None else "open"
        return f"<{type(self).__name__}({status}) at 0x{id(self):x}>"

    def __del__(self) -> None:
        try:
            if self._conn is not None:
                usock = getattr(self._conn, '_usock', None)
                if usock is not None:
                    try:
                        usock.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    try:
                        usock.close()
                    except Exception:
                        pass
        except Exception:
            pass

    def __enter__(self) -> SyncConnection:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
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
    user: str | bytes,
    host: str | None = None,
    unix_sock: str | None = None,
    port: int = 5480,
    database: str | None = None,
    password: str | bytes | None = None,
    ssl: Any = None,
    securityLevel: int = 0,
    timeout: float | None = None,
    application_name: str | None = None,
    max_prepared_statements: int = 1000,
    datestyle: str = "ISO",
    logLevel: int = 0,
    tcp_keepalive: bool = True,
    char_varchar_encoding: str = "latin",
    on_connect: Callable[[SyncConnection], Any] | None = None,
    ssl_verify: bool = True,
    connect_timeout: float | None = None,
    **kwargs: Any,
) -> Connection:
    conn = Connection()
    try:
        await conn.connect(
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
    user: str,
    host: str = "localhost",
    unix_sock: str | None = None,
    port: int = 5480,
    database: str | None = None,
    password: str | None = None,
    ssl: Any = None,
    securityLevel: int = 0,
    timeout: float | None = None,
    application_name: str | None = None,
    max_prepared_statements: int = 1000,
    datestyle: str = "ISO",
    logLevel: int = 0,
    tcp_keepalive: bool = True,
    char_varchar_encoding: str = "latin",
    on_connect: Callable[[SyncConnection], Any] | None = None,
    ssl_verify: bool = True,
    connect_timeout: float | None = None,
    **kwargs: Any,
) -> SyncConnection:
    async_conn = runner.run(
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


__all__ = ["SyncCursor", "SyncConnection", "connect"]
