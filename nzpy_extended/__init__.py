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
                       Warning)
from nzpy_extended.pool import AsyncNullPool, NullPool, NzPool, SyncPool

from . import sync

try:
    from . import fastapi as fastapi
except ImportError:
    fastapi = None  # fastapi package not installed — optional integration

from ._version import get_versions

__version__ = get_versions()['version']
del get_versions

__author__ = "Mathieu Fenniak"

async def connect(user, host='localhost', unix_sock=None, port=5480, database=None,
            password=None, ssl=None, securityLevel=0, timeout=None,
            application_name=None, max_prepared_statements=1000,
            datestyle='ISO', logLevel=0, tcp_keepalive=True,
            char_varchar_encoding='latin', logOptions=LogOptions.Inherit,
            pgOptions=None, on_connect=None, ssl_verify=True,
            connect_timeout=None):

    conn = Connection()
    await conn._connect(user, host, unix_sock, port, database, password, ssl,
                      securityLevel, timeout, application_name,
                      max_prepared_statements, datestyle, logLevel,
                      tcp_keepalive, char_varchar_encoding,
                      logOptions, pgOptions, ssl_verify=ssl_verify,
                      connect_timeout=connect_timeout)
    if on_connect is not None:
        result = on_connect(conn)
        if hasattr(result, '__await__'):
            await result
    return conn


apilevel = "2.0"
"""The DBAPI level supported, currently "2.0".
This property is part of the `DBAPI 2.0 specification
<http://www.python.org/dev/peps/pep-0249/>`_.
"""

threadsafety = 1
"""Integer constant stating the level of thread safety the DBAPI interface
supports. This DBAPI module supports sharing of the module only. Connections
and cursors my not be shared between threads. This gives nzpy_extended a threadsafety
value of 1.
This property is part of the `DBAPI 2.0 specification
<http://www.python.org/dev/peps/pep-0249/>`_.
"""

paramstyle = 'qmark'

max_prepared_statements = 1000

# I have no idea what this would be used for by a client app.  Should it be
# TEXT, VARCHAR, CHAR?  It will only compare against row_description's
# type_code if it is this one type.  It is the varchar type oid for now, this
# appears to match expectations in the DB API 2.0 compliance test suite.

STRING = 1043
"""String type oid."""


NUMBER = 1700
"""Numeric type oid"""

DATETIME = 1114
"""Timestamp type oid"""

ROWID = 26
"""ROWID type oid"""

__all__ = [
    "Warning", "DataError", "DatabaseError", "connect", "InterfaceError",
    "ProgrammingError", "Error", "OperationalError", "IntegrityError", "InternalError",
    "NotSupportedError", "ArrayContentNotHomogenousError",
    "ArrayDimensionsNotConsistentError", "ArrayContentNotSupportedError",
    "Connection", "Cursor", "Binary", "Date", "DateFromTicks", "Time", "TimeFromTicks",
    "Timestamp", "TimestampFromTicks", "BINARY", "Interval", "PGEnum", "PGJson", "PGJsonb",
    "PGTsvector", "PGText", "PGVarchar",
    "NzPool", "SyncPool", "NullPool", "AsyncNullPool",
    "sync",
]

"""Version string for nzpy_extended.
    .. versionadded:: 1.9.11
"""
