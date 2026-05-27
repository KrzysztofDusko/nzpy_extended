from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._constants import DEFAULT_BUFFER_SIZE

from nzpy_extended.core import (ArrayContentNotHomogenousError,
                       ArrayContentNotSupportedError,
                       ArrayDimensionsNotConsistentError, BINARY,
                       Binary, Connection, Cursor, DataError,
                       DatabaseError, Date, DateFromTicks, Error,
                       IntegrityError, InterfaceError, InternalError,
                       Interval, LogOptions, NotSupportedError,
                       OperationalError, PGEnum, PGJson, PGJsonb,
                       PGText, PGTsvector, PGVarchar, ProgrammingError,
                       Time, TimeFromTicks, Timestamp, TimestampFromTicks,
                       Warning, load_data)
from nzpy_extended.pool import AsyncNullPool, NullPool, NzPool, SyncPool
from nzpy_extended._metadata_api import ConnectionMetadataProvider

from . import sync

try:
    from . import fastapi as fastapi
except ImportError:
    import typing
    fastapi: typing.Any = None  # type: ignore[no-redef]

from ._version import get_versions

__version__: str = get_versions()['version']  # type: ignore[no-untyped-call]
del get_versions


async def connect(
    user: str,
    host: str = 'localhost',
    unix_sock: str | None = None,
    port: int = 5480,
    database: str | None = None,
    password: str | None = None,
    ssl: Any = None,
    securityLevel: int = 0,
    timeout: float | None = None,
    application_name: str | None = None,
    max_prepared_statements: int = 1000,
    datestyle: str = 'ISO',
    logLevel: int = 0,
    tcp_keepalive: bool = True,
    char_varchar_encoding: str = 'latin',
    client_encoding: str = 'utf8',
    logOptions: LogOptions = LogOptions.Inherit,
    pgOptions: str | None = None,
    on_connect: Callable[[Connection], Any] | None = None,
    ssl_verify: bool = True,
    connect_timeout: float | None = None,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
) -> Connection:
    conn = Connection()
    await conn.connect(user, host, unix_sock, port, database, password, ssl,
                      securityLevel, timeout, application_name,
                      max_prepared_statements, datestyle, logLevel,
                      tcp_keepalive, char_varchar_encoding,
                      logOptions, client_encoding,
                      pgOptions, ssl_verify=ssl_verify,
                      connect_timeout=connect_timeout,
                      buffer_size=buffer_size)
    if on_connect is not None:
        result = on_connect(conn)
        if hasattr(result, '__await__'):
            await result
    return conn


apilevel: str = "2.0"

threadsafety: int = 1

paramstyle: str = 'qmark'

max_prepared_statements: int = 1000

STRING: int = 1043

NUMBER: int = 1700

DATETIME: int = 1114

ROWID: int = 26

__all__ = [
    "Warning", "DataError", "DatabaseError", "connect", "InterfaceError",
    "ProgrammingError", "Error", "OperationalError", "IntegrityError", "InternalError",
    "NotSupportedError", "ArrayContentNotHomogenousError",
    "ArrayDimensionsNotConsistentError", "ArrayContentNotSupportedError",
    "Connection", "Cursor", "Binary", "Date", "DateFromTicks", "Time", "TimeFromTicks",
    "Timestamp", "TimestampFromTicks", "BINARY", "Interval", "PGEnum", "PGJson", "PGJsonb",
    "PGTsvector", "PGText", "PGVarchar",
    "NzPool", "SyncPool", "NullPool", "AsyncNullPool",
    "sync", "load_data",
    "ConnectionMetadataProvider",
    "DEFAULT_BUFFER_SIZE",
]
