from __future__ import annotations

import os
import stat
import tempfile
import datetime
import enum
import getpass
import logging
import logging.handlers
import platform
import re
import socket
import asyncio
from calendar import timegm
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Callable, Generator
from copy import deepcopy
from datetime import (date, datetime as Datetime, time, timedelta as Timedelta)
from datetime import timezone as Timezone
from decimal import Decimal
from looseversion import LooseVersion
from ipaddress import (IPv4Address, IPv4Network, IPv6Address,
                       IPv6Network, ip_address, ip_network)
from itertools import count, islice
from json import dumps, loads
from os import path
from struct import Struct
from time import localtime
from typing import Any
from uuid import UUID
from warnings import warn

import nzpy_extended

from . import handshake
from ._constants import DEFAULT_BUFFER_SIZE
from .buffered_stream import NzBufferedStream

_FORCE_PURE_PYTHON = os.environ.get("NZPY_EXTENDED_NO_CEXT", "").lower() in ("1", "true", "yes")

if _FORCE_PURE_PYTHON:
    _HAVE_C_EXT = False
    _c_ext = None
else:
    try:
        from . import c_ext as _c_ext  # type: ignore[attr-defined,no-redef]
        _HAVE_C_EXT = True
    except ImportError:
        _HAVE_C_EXT = False
        _c_ext = None

from .exceptions import (Warning, Error, InterfaceError,
                         ConnectionClosedError, DatabaseError, DataError,
                         OperationalError, IntegrityError, InternalError,
                         ProgrammingError, NotSupportedError,
                         ArrayContentNotSupportedError,
                         ArrayContentNotHomogenousError,
                         ArrayDimensionsNotConsistentError)

from .types import (ZERO, BINARY, Binary, Date, Time, Timestamp,
                    DateFromTicks, TimeFromTicks, TimestampFromTicks,
                    Interval, LogOptions,
                    PGType, PGEnum, PGJson, PGJsonb, PGText, PGTsvector,
                    PGVarchar,
                    FC_TEXT, FC_BINARY,
                    DbosTupleDesc,
                    timestamp_recv_integer, timestamp_recv_float,
                    timestamp_send_integer, timestamp_send_float,
                    timestamptz_send_integer, timestamptz_send_float,
                    timestamptz_recv_integer, timestamptz_recv_float,
                    interval_send_integer, interval_send_float,
                    interval_recv_integer, interval_recv_float,
                    _parse_interval_text,
                    int8_recv, int2_recv, int4_recv,
                    float4_recv, float8_recv,
                    bytea_send, bytea_recv,
                    uuid_send, uuid_recv,
                    bool_send, null_send,
                    int_in, timestamp_in, timestamptz_in,
                    EPOCH, EPOCH_TZ, EPOCH_SECONDS,
                    INFINITY_MICROSECONDS, MINUS_INFINITY_MICROSECONDS,
                    J2000_OFFSET,
                    _OID_BOOL, _OID_BYTEINT, _OID_INT2, _OID_INT4,
                    _OID_INT8, _OID_NUMERIC, _OID_FLOAT4, _OID_FLOAT8,
                    _OID_BPCHAR, _OID_VARCHAR, _OID_TEXT,
                    _OID_DATE, _OID_TIME, _OID_TIMESTAMP, _OID_TIMESTAMPTZ,
                    _OID_TIMETZ, _OID_NCHAR, _OID_NVARCHAR,
                    _NZ_TYPE_NUMERIC,
                    date2j, j2date, time2struct, timestamp2struct,
                    timetz_out_timetzadt, EncodeTimeOnly, EncodeTimeSpan,
                    IntervalToText, interval2tm,
                    decimalToBinary)

from .protocol import (NzTypeRecAddr, NzTypeDouble, NzTypeInt,
                       NzTypeFloat, NzTypeMoney, NzTypeDate, NzTypeNumeric,
                       NzTypeTime, NzTypeTimestamp, NzTypeInterval,
                       NzTypeTimeTz, NzTypeBool, NzTypeInt1, NzTypeChar,
                       NzTypeVarChar, NzDEPR_Text, NzTypeUnknown,
                       NzTypeInt2, NzTypeInt8, NzTypeVarFixedChar,
                       NzTypeGeometry, NzTypeVarBinary, NzDEPR_Blob,
                       NzTypeNChar, NzTypeNVarChar, NzDEPR_NText,
                       NzTypeJson, NzTypeJsonb, NzTypeJsonpath,
                       NzTypeVector, NzTypeLastEntry,
                       dataType, nzpy_extended_client_version)

from .protocol import (NOTICE_RESPONSE, AUTHENTICATION_REQUEST,
                       PARAMETER_STATUS, BACKEND_KEY_DATA,
                       READY_FOR_QUERY, ROW_DESCRIPTION, ERROR_RESPONSE,
                       DATA_ROW, COMMAND_COMPLETE,
                       PARSE_COMPLETE, BIND_COMPLETE, CLOSE_COMPLETE,
                       PORTAL_SUSPENDED, NO_DATA, PARAMETER_DESCRIPTION,
                       NOTIFICATION_RESPONSE, COPY_DONE, COPY_DATA,
                       COPY_IN_RESPONSE, COPY_OUT_RESPONSE,
                       EMPTY_QUERY_RESPONSE,
                       BIND, PARSE, EXECUTE, FLUSH, SYNC, PASSWORD,
                       DESCRIBE, TERMINATE, CLOSE,
                       create_message,
                       FLUSH_MSG, SYNC_MSG, TERMINATE_MSG,
                       COPY_DONE_MSG, EXECUTE_MSG,
                       STATEMENT, PORTAL,
                       RESPONSE_SEVERITY, RESPONSE_CODE, RESPONSE_MSG,
                       RESPONSE_DETAIL, RESPONSE_HINT, RESPONSE_POSITION,
                       RESPONSE__POSITION, RESPONSE__QUERY, RESPONSE_WHERE,
                       RESPONSE_FILE, RESPONSE_LINE, RESPONSE_ROUTINE,
                       IDLE, IDLE_IN_TRANSACTION, IDLE_IN_FAILED_TRANSACTION,
                       TYPE_MOD_OFFSET,
                       NULL, NULL_BYTE,
                       EXTAB_SOCK_DATA, EXTAB_SOCK_ERROR,
                       EXTAB_SOCK_DONE, EXTAB_SOCK_FLUSH,
                       EXTERNAL_TABLE_STREAM_MARKER,
                       CONN_NOT_CONNECTED, CONN_CONNECTED,
                       CONN_EXECUTING, CONN_FETCHING, CONN_CANCELLED)

from .cursor import Cursor

from .load_data import load_data

from .utils import (pack_funcs, i_pack, i_unpack, h_pack, h_unpack,
                    q_pack, q_unpack, d_pack, d_unpack,
                    f_pack, f_unpack,
                    iii_pack, iii_unpack, ii_pack, ii_unpack,
                    qii_pack, qii_unpack, dii_pack, dii_unpack,
                    ihic_pack, ihic_unpack, ci_pack, ci_unpack,
                    c_pack, c_unpack, bh_pack, bh_unpack,
                    cccc_pack, cccc_unpack,
                    h_le_unpack, i_le_unpack, q_le_unpack,
                    min_int2, max_int2, min_int4, max_int4,
                    min_int8, max_int8,
                    convert_paramstyle, _sql_literal,
                    _render_prepared_statement,
                    walk_array, array_find_first_element, array_flatten,
                    array_check_dimensions, array_has_null,
                    array_dim_lengths,
                    pg_array_types, pg_to_py_encodings,
                    _infer_nz_type, _infer_columns_from_rows,
                    _rows_to_csv_bytes)

arr_trans = dict(zip(map(ord, "[] 'u"), list('{}') + [None] * 3))


class Connection:
    _sock: Any
    _usock: Any
    _stream: NzBufferedStream | None
    in_transaction: bool
    error: Any
    _ext_table_source: Any
    _command_generation: int
    _char_varchar_encoding: str
    _client_encoding: str
    _commands_with_count: tuple[bytes, ...]
    notifications: deque[Any]
    parameter_statuses: deque[Any]
    max_prepared_statements: int
    log: logging.Logger
    user: bytes
    password: bytes | None
    autocommit: bool
    _caches: dict[str, Any]
    commandNumber: int
    status: int | None
    _host: str | None
    _port: int
    _unix_sock: str | None
    _backend_pid: int | None
    _backend_key: int | None
    _read: Callable[[int], Any]
    _write: Callable[[bytes | bytearray], Any]
    _flush: Callable[[], Any]
    _backend_key_data: Any
    _dirty_socket: bool
    pg_types: defaultdict[Any, Any]
    py_types: dict[Any, Any] = {}
    inspect_funcs: dict[Any, Any] = {}
    message_types: dict[Any, Any]
    _cursor: Cursor
    _active_generator: Any
    _active_cursor: Any
    _cached_header: Any
    _copy_done: bool
    _server_version: Any
    tupdesc: Any

    Warning = property(lambda self: self._getError(Warning))
    Error = property(lambda self: self._getError(Error))
    InterfaceError = property(lambda self: self._getError(InterfaceError))
    ConnectionClosedError = property(lambda self:
                                     self._getError(ConnectionClosedError))
    DatabaseError = property(lambda self: self._getError(DatabaseError))
    OperationalError = property(lambda self: self._getError(OperationalError))
    IntegrityError = property(lambda self: self._getError(IntegrityError))
    InternalError = property(lambda self: self._getError(InternalError))
    ProgrammingError = property(lambda self: self._getError(ProgrammingError))
    NotSupportedError = property(
        lambda self: self._getError(NotSupportedError))

    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type:
            try:
                await self.rollback()
            except Exception:
                pass
        else:
            try:
                await self.commit()
            except Exception:
                pass
        try:
            await self.close()
        except ConnectionClosedError:
            pass

    def __del__(self) -> None:
        try:
            if hasattr(self, '_sock') and self._sock is not None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.close())
                except RuntimeError:
                    pass
        except (ConnectionClosedError, RuntimeError):
            pass

    def _getError(self, error: type) -> type:
        warn(
            "DB-API extension connection.%s used" %
            error.__name__, stacklevel=3)
        return error

    def __init__(self) -> None:
        self._sock = None
        self._usock = None
        self._stream = None
        self.in_transaction = False
        self.error = None
        self._ext_table_source = None
        self._command_generation = 0
        self._buffer_size = DEFAULT_BUFFER_SIZE

    async def _connect(
            self, user: str | bytes, host: str | None, unix_sock: str | None, port: int,
            database: str | None, password: str | bytes | None, ssl: Any,
            securityLevel: int, timeout: float | None, application_name: str | None,
            max_prepared_statements: int, datestyle: str, logLevel: int, tcp_keepalive: bool,
            char_varchar_encoding: str, logOptions: LogOptions = LogOptions.Inherit,
            pgOptions: str | None = None, ssl_verify: bool = True,
            connect_timeout: float | None = None,
            buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size
        self._char_varchar_encoding = char_varchar_encoding
        self._client_encoding = "utf8"
        self._commands_with_count = (
            b"INSERT", b"DELETE", b"UPDATE"
        )
        self.notifications = deque(maxlen=100)
        self.parameter_statuses = deque(maxlen=100)
        self.max_prepared_statements = int(max_prepared_statements)

        if logLevel not in (logging.DEBUG, logging.ERROR,
                            logging.CRITICAL, logging.FATAL,
                            logging.WARN, logging.WARNING):
            if logLevel == 0:
                logLevel = logging.DEBUG
            elif logLevel == 1:
                logLevel = logging.INFO
            elif logLevel == 2:
                logLevel = logging.WARNING
            else:
                logLevel = logging.INFO

        database_name = database if database is not None else "<default>"
        self.log = logging.getLogger(f"nzpy_extended.Connection[{database_name}]")
        self.log.setLevel(logLevel)

        if logOptions & LogOptions.Logfile:
            h = logging.handlers. \
                RotatingFileHandler('nzpy_extended.log', maxBytes=1024 ** 3 * 10)
            fmt = logging.Formatter(
                '%(asctime)s (%(process)s) [%(name)s:%(filename)s:'
                '%(lineno)s] %(levelname)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S.000000 %Z')
            h.setFormatter(fmt)
            self.log.addHandler(h)
        if not logOptions & LogOptions.Inherit:
            self.log.propagate = False

        if user is None:
            raise InterfaceError(
                "The 'user' connection parameter cannot be None")

        if isinstance(user, str):
            self.user = user.encode('utf8')
        else:
            self.user = user

        if isinstance(password, str):
            self.password = password.encode('utf8')
        else:
            self.password = password

        self.autocommit = True

        self._caches = {}
        self.commandNumber = -1
        self.status = None
        self._host = host
        self._port = port
        self._unix_sock = unix_sock

        try:
            if unix_sock is None and host is not None:
                self._usock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            elif unix_sock is not None:
                if not hasattr(socket, "AF_UNIX"):
                    raise InterfaceError(
                        "attempt to connect to unix socket on unsupported "
                        "platform")
                self._usock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            else:
                raise ProgrammingError(
                    "one of host or unix_sock must be provided")
            sock_timeout = connect_timeout if connect_timeout is not None else timeout

            self._usock.setblocking(False)
            loop = asyncio.get_event_loop()
            if unix_sock is None and host is not None:
                connect_coro = loop.sock_connect(self._usock, (host, port))
            elif unix_sock is not None:
                connect_coro = loop.sock_connect(self._usock, unix_sock)
            else:
                connect_coro = None
            if sock_timeout is not None and connect_coro is not None:
                await asyncio.wait_for(connect_coro, timeout=sock_timeout)
            elif connect_coro is not None:
                await connect_coro

            if tcp_keepalive:
                self._usock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except socket.error as e:
            self._usock.close()
            raise InterfaceError("communication error", e)

        self._usock.setblocking(True)
        if not isinstance(ssl, dict):
            hs_ssl: dict[str, Any] = {}
        else:
            hs_ssl = dict(ssl)
        hs_ssl.setdefault('ssl_verify', ssl_verify)
        hs = handshake.SyncHandshake(self._usock, hs_ssl, self.log)
        if application_name:
            hs.guardium_applName = application_name
        self._usock = await asyncio.to_thread(
            hs.startup, database, securityLevel,
            user, password, pgOptions)
        if self._usock is False:
            raise ProgrammingError("Error in handshake")
        self._backend_pid = hs.backend_pid
        self._backend_key = hs.backend_key
        self._usock.setblocking(False)

        self._stream = NzBufferedStream(self._usock, max_size=self._buffer_size,
                                        buffer_size=self._buffer_size)

        stream = self._stream
        assert stream is not None

        async def _read(n: int) -> bytes:
            return await stream.read(n)

        async def _write(data: bytes | bytearray) -> None:
            await stream.write(data)

        async def _flush() -> None:
            pass

        self._read = _read
        self._write = _write
        self._flush = _flush
        self._backend_key_data = None
        self._dirty_socket = False

        def text_out(v: str) -> bytes:
            return v.encode(self._client_encoding)

        def enum_out(v: enum.Enum) -> bytes:
            return str(v.value).encode(self._client_encoding)

        def time_out(v: time) -> bytes:
            return v.isoformat().encode(self._client_encoding)

        def date_out(v: date) -> bytes:
            return v.isoformat().encode(self._client_encoding)

        def _unknown_out(v: object) -> bytes:
            return str(v).encode(self._client_encoding)

        def array_in(data: bytes, idx: int, length: int) -> list[Any]:
            text = data[idx:idx + length].decode(self._client_encoding)

            def parse_array(s: str, pos: int) -> tuple[list[Any], int]:
                result: list[Any] = []
                while pos < len(s) and s[pos].isspace():
                    pos += 1
                if pos >= len(s) or s[pos] != '{':
                    raise ValueError("Expected '{'")
                pos += 1

                while pos < len(s):
                    while pos < len(s) and s[pos].isspace():
                        pos += 1
                    if pos >= len(s):
                        break
                    if s[pos] == '}':
                        pos += 1
                        break
                    elif s[pos] == '{':
                        arr, pos = parse_array(s, pos)
                        result.append(arr)
                    else:
                        start = pos
                        while pos < len(s) and s[pos] not in ('}', ','):
                            pos += 1
                        val_str = s[start:pos].strip()
                        if val_str.upper() == 'NULL':
                            result.append(None)
                        elif val_str:
                            result.append(Decimal(val_str))
                    while pos < len(s) and s[pos].isspace():
                        pos += 1
                    if pos < len(s) and s[pos] == ',':
                        pos += 1
                return result, pos

            arr, _ = parse_array(text, 0)
            return arr

        def array_recv(data: bytes, idx: int, length: int) -> list[Any]:
            final_idx = idx + length
            dim, _hasnull, typeoid = iii_unpack(data, idx)
            idx += 12

            conversion = self.pg_types[typeoid][1]

            dim_lengths: list[int] = []
            for _ in range(dim):
                dim_lengths.append(ii_unpack(data, idx)[0])
                idx += 8

            values: list[Any] = []
            while idx < final_idx:
                element_len, = i_unpack(data, idx)
                idx += 4
                if element_len == -1:
                    values.append(None)
                else:
                    values.append(conversion(data, idx, element_len))
                    idx += element_len

            for length in reversed(dim_lengths[1:]):
                values = list(map(list, zip(*[iter(values)] * length)))
            return values

        def vector_in(data: bytes, idx: int, length: int) -> list[int]:
            text = data[idx:idx + length].decode(self._client_encoding)
            return [int(x) for x in text.replace(',', ' ').split()]

        def text_recv(data: bytes, offset: int, length: int) -> str:
            view = memoryview(data)
            return str(view[offset: offset + length], self._client_encoding)

        def bool_recv(data: bytes, offset: int, length: int) -> bool:
            return data[offset] == 116

        def json_in(data: bytes, offset: int, length: int) -> Any:
            return loads(
                str(data[offset: offset + length], self._client_encoding))

        def time_in(data: bytes, offset: int, length: int) -> time:
            hour = int(data[offset:offset + 2])
            minute = int(data[offset + 3:offset + 5])
            sec = Decimal(
                data[offset + 6:offset + length].decode(self._client_encoding))
            return time(
                hour, minute, int(sec), int((sec - int(sec)) * 1000000))

        def date_in(data: bytes, offset: int, length: int) -> date | str:
            d = data[offset:offset + length].decode(self._client_encoding)
            try:
                return date(int(d[:4]), int(d[5:7]), int(d[8:10]))
            except ValueError:
                return d

        def numeric_in(data: bytes, offset: int, length: int) -> Decimal:
            return Decimal(
                data[offset: offset + length].decode(self._client_encoding))

        def numeric_out(d: Decimal) -> bytes:
            return str(d).encode(self._client_encoding)

        self.pg_types = defaultdict(
            lambda: (FC_TEXT, text_recv), {
                16: (FC_BINARY, bool_recv),
                17: (FC_BINARY, bytea_recv),
                19: (FC_BINARY, text_recv),
                20: (FC_BINARY, int8_recv),
                21: (FC_BINARY, int2_recv),
                22: (FC_TEXT, vector_in),
                23: (FC_BINARY, int4_recv),
                25: (FC_BINARY, text_recv),
                26: (FC_TEXT, int_in),
                28: (FC_TEXT, int_in),
                114: (FC_TEXT, json_in),
                700: (FC_BINARY, float4_recv),
                701: (FC_BINARY, float8_recv),
                705: (FC_BINARY, text_recv),
                829: (FC_TEXT, text_recv),
                1000: (FC_BINARY, array_recv),
                1003: (FC_BINARY, array_recv),
                1005: (FC_BINARY, array_recv),
                1007: (FC_BINARY, array_recv),
                1009: (FC_BINARY, array_recv),
                1014: (FC_BINARY, array_recv),
                1015: (FC_BINARY, array_recv),
                1016: (FC_BINARY, array_recv),
                1021: (FC_BINARY, array_recv),
                1022: (FC_BINARY, array_recv),
                1042: (FC_BINARY, text_recv),
                1043: (FC_BINARY, text_recv),
                1082: (FC_TEXT, date_in),
                1083: (FC_TEXT, time_in),
                1114: (FC_TEXT, timestamp_in),
                1184: (FC_TEXT, timestamptz_in),
                1186: (FC_TEXT, interval_recv_integer),
                2500: (FC_TEXT, int_in),
                1231: (FC_TEXT, array_in),
                1263: (FC_BINARY, array_recv),
                1700: (FC_TEXT, numeric_in),
                2275: (FC_BINARY, text_recv),
                2950: (FC_BINARY, uuid_recv),
                3802: (FC_TEXT, json_in),
            })

        self.py_types = {
            type(None): (-1, FC_BINARY, null_send),
            bool: (16, FC_BINARY, bool_send),
            bytearray: (17, FC_BINARY, bytea_send),
            20: (20, FC_BINARY, q_pack),
            21: (21, FC_BINARY, h_pack),
            23: (23, FC_BINARY, i_pack),
            PGText: (25, FC_TEXT, text_out),
            float: (701, FC_BINARY, d_pack),
            PGEnum: (705, FC_TEXT, enum_out),
            date: (1082, FC_TEXT, date_out),
            time: (1083, FC_TEXT, time_out),
            1114: (1114, FC_BINARY, timestamp_send_integer),
            PGVarchar: (1043, FC_TEXT, text_out),
            1184: (1184, FC_BINARY, timestamptz_send_integer),
            PGJson: (114, FC_TEXT, text_out),
            PGJsonb: (3802, FC_TEXT, text_out),
            Timedelta: (1186, FC_BINARY, interval_send_integer),
            Interval: (1186, FC_BINARY, interval_send_integer),
            Decimal: (1700, FC_TEXT, numeric_out),
            PGTsvector: (3614, FC_TEXT, text_out),
            UUID: (2950, FC_BINARY, uuid_send)}

        self.inspect_funcs = {
            Datetime: self.inspect_datetime,
            list: self.array_inspect,
            tuple: self.array_inspect,
            int: self.inspect_int}

        self.py_types[bytes] = (17, FC_BINARY, bytea_send)
        self.py_types[str] = (705, FC_TEXT, text_out)
        self.py_types[enum.Enum] = (705, FC_TEXT, enum_out)

        def inet_out(v: object) -> bytes:
            return str(v).encode(self._client_encoding)

        def inet_in(data: bytes, offset: int, length: int) -> IPv4Address | IPv6Address | IPv4Network | IPv6Network:
            inet_str = data[offset: offset + length].decode(
                self._client_encoding)
            if '/' in inet_str:
                return ip_network(inet_str, False)
            else:
                return ip_address(inet_str)

        self.py_types[IPv4Address] = (869, FC_TEXT, inet_out)
        self.py_types[IPv6Address] = (869, FC_TEXT, inet_out)
        self.py_types[IPv4Network] = (869, FC_TEXT, inet_out)
        self.py_types[IPv6Network] = (869, FC_TEXT, inet_out)
        self.pg_types[869] = (FC_TEXT, inet_in)

        async def conn_send_query() -> bool:

            if not await self.execute(self._cursor, "set nz_encoding to "
                                               "'utf8'", None):
                return False

            if datestyle == 'MDY':
                query = "set DateStyle to 'US'"
            elif datestyle == 'DMY':
                query = "set DateStyle to 'EUROPEAN'"
            else:
                query = "set DateStyle to 'ISO'"

            if not await self.execute(self._cursor, query, None):
                return False

            client_info = "select version(), 'Netezza Python " \
                          "Client Version: {}', " \
                          "'{}', 'OS Platform: {}', 'OS Username: {}'"

            query = client_info.format(nzpy_extended_client_version,
                                       platform.uname().machine,
                                       platform.system(),
                                       getpass.getuser())

            if not await self.execute(self._cursor, query, None):
                return False
            else:
                results = await self._cursor.fetchall()
                for c1, c2, c3, c4, c5 in results:
                    self.log.debug("c1 = %s, c2 = %s, c3 = %s, c4 = %s, "
                                   "c5 = %s" % (c1, c2, c3, c4, c5))

            client_info = "SET CLIENT_VERSION = '{}'"
            query = client_info.format(nzpy_extended_client_version)
            if not await self.execute(self._cursor, query, None):
                return False

            if not await self.execute(self._cursor, "select ascii(' ') as space, "
                                               "encoding as ccsid "
                                               "from _v_database "
                                               "where objid = current_db",
                                  None):
                return False
            else:
                results = await self._cursor.fetchall()
                for c1, c2 in results:
                    self.log.debug("c1 = %s, c2 = %s" % (c1, c2))

            if not await self.execute(self._cursor, "select feature from "
                                               "_v_odbc_feature "
                                               "where spec_level = '3.5'",
                                  None):
                return False
            else:
                results = await self._cursor.fetchall()
                for c1 in results:
                    self.log.debug("c1 = %s" % (c1))

            if not await self.execute(self._cursor, "select identifier_case, "
                                               "current_catalog, "
                                               "current_user", None):
                return False
            else:
                results = await self._cursor.fetchall()
                for c1, c2, c3 in results:
                    self.log.debug("c1 = %s, c2 = %s, c3 = %s" % (c1, c2, c3))

            return True

        self.message_types = {
            PARAMETER_STATUS: self.handle_PARAMETER_STATUS,
            READY_FOR_QUERY: self.handle_READY_FOR_QUERY,
            ROW_DESCRIPTION: self.handle_ROW_DESCRIPTION,
            ERROR_RESPONSE: self.handle_ERROR_RESPONSE,
            EMPTY_QUERY_RESPONSE: self.handle_EMPTY_QUERY_RESPONSE,
            DATA_ROW: self.handle_DATA_ROW,
            COMMAND_COMPLETE: self.handle_COMMAND_COMPLETE,
            PARSE_COMPLETE: self.handle_PARSE_COMPLETE,
            BIND_COMPLETE: self.handle_BIND_COMPLETE,
            CLOSE_COMPLETE: self.handle_CLOSE_COMPLETE,
            PORTAL_SUSPENDED: self.handle_PORTAL_SUSPENDED,
            NO_DATA: self.handle_NO_DATA,
            PARAMETER_DESCRIPTION: self.handle_PARAMETER_DESCRIPTION,
            NOTIFICATION_RESPONSE: self.handle_NOTIFICATION_RESPONSE,
            COPY_DONE: self.handle_COPY_DONE,
            COPY_DATA: self.handle_COPY_DATA,
            COPY_IN_RESPONSE: self.handle_COPY_IN_RESPONSE,
            COPY_OUT_RESPONSE: self.handle_COPY_OUT_RESPONSE}

        self._cursor = self.cursor()
        self.error = None

        if not await conn_send_query():
            self.log.warning("Error sending initial setup queries")

        self.commandNumber = 0

        if self.error is not None:
            raise self.error

        self.in_transaction = False
        await self._read(4)
        self.status = None

    async def handle_ERROR_RESPONSE(self, data: bytes, ps: Any) -> None:
        msg = dict(
            (
                s[:1].decode(self._client_encoding),
                s[1:].decode(self._client_encoding)) for s in
            data.split(NULL_BYTE) if s != b'')

        response_code = msg.get(RESPONSE_CODE, '')
        cls: type[Error]
        if response_code == '28000':
            cls = InterfaceError
        elif response_code == '23505':
            cls = IntegrityError
        elif response_code.startswith('08'):
            cls = OperationalError
        elif response_code.startswith('22'):
            cls = DataError
        elif response_code.startswith('26'):
            cls = InternalError
        else:
            cls = ProgrammingError

        self.error = cls(msg)

    async def handle_EMPTY_QUERY_RESPONSE(self, data: bytes, ps: Any) -> None:
        self.error = ProgrammingError("query was empty")

    async def handle_CLOSE_COMPLETE(self, data: bytes, ps: Any) -> None:
        pass

    async def handle_PARSE_COMPLETE(self, data: bytes, ps: Any) -> None:
        pass

    async def handle_BIND_COMPLETE(self, data: bytes, ps: Any) -> None:
        pass

    async def handle_PORTAL_SUSPENDED(self, data: bytes, cursor: Any) -> None:
        pass

    async def handle_PARAMETER_DESCRIPTION(self, data: bytes, ps: Any) -> None:
        pass

    async def handle_COPY_DONE(self, data: bytes, ps: Any) -> None:
        self._copy_done = True

    async def handle_COPY_OUT_RESPONSE(self, data: bytes, ps: Any) -> None:
        _, _ = bh_unpack(data)
        if ps.stream is None:
            raise InterfaceError(
                "An output stream is required for the COPY OUT response.")

    async def handle_COPY_DATA(self, data: bytes, ps: Any) -> None:
        await asyncio.to_thread(ps.stream.write, data)

    async def handle_COPY_IN_RESPONSE(self, data: bytes, ps: Any) -> None:
        _, _ = bh_unpack(data)
        if ps.stream is None:
            raise InterfaceError(
                "An input stream is required for the COPY IN response.")

        bffr = bytearray(self._buffer_size)
        while True:
            bytes_read = await asyncio.to_thread(ps.stream.readinto, bffr)
            if bytes_read == 0:
                break
            await self._write(COPY_DATA + i_pack(bytes_read + 4))
            await self._write(bffr[:bytes_read])
            await self._flush()

        await self._write(COPY_DONE_MSG)
        await self._write(SYNC_MSG)
        await self._flush()

    async def handle_NOTIFICATION_RESPONSE(self, data: bytes, ps: Any) -> None:
        backend_pid = i_unpack(data)[0]
        idx = 4
        null = data.find(NULL_BYTE, idx) - idx
        condition = data[idx:idx + null].decode("ascii")
        idx += null + 1
        null = data.find(NULL_BYTE, idx) - idx

        self.notifications.append((backend_pid, condition))

    def cursor(self) -> Cursor:
        return Cursor(self)

    async def commit(self) -> None:
        await self.execute(self._cursor, "commit", None)

    async def rollback(self) -> None:
        if not self.in_transaction:
            return
        await self.execute(self._cursor, "rollback", None)

    async def close(self) -> None:
        if getattr(self, '_usock', None) is None:
            return

        try:
            if getattr(self, '_usock', None) is not None:
                try:
                    self._usock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._usock.close()
                except Exception:
                    pass
                self._usock = None
        except Exception:
            pass

        if hasattr(self, '_stream') and self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        self._sock = None

    async def cancel(self, exec_gen: int | None = None) -> None:
        if getattr(self, '_backend_pid', None) is None or getattr(self, '_backend_key', None) is None:
            return

        if exec_gen is not None and exec_gen != self._command_generation:
            return

        try:
            if getattr(self, '_unix_sock', None) is not None:
                reader, writer = await asyncio.open_unix_connection(self._unix_sock)
            else:
                if getattr(self, '_host', None) is None:
                    return
                reader, writer = await asyncio.open_connection(self._host, self._port)

            if exec_gen is not None and exec_gen != self._command_generation:
                writer.close()
                return

            cancel_code = 80877102
            msg = bytearray(i_pack(16) + i_pack(cancel_code) + i_pack(self._backend_pid) + i_pack(self._backend_key))
            writer.write(msg)
            await writer.drain()
            try:
                await reader.read(1)
            except Exception:
                pass
            writer.close()
            await writer.wait_closed()
            self.log.info("Sent cancellation request to backend")
        except Exception as e:
            self.log.warning("Could not send cancel request: %s", str(e))

    async def load_data(self, table_name: str, rows: list[Any], columns: list[tuple[str, str]] | None = None,
                        delimiter: str = '|', encoding: str = 'LATIN9',
                        create_if_missing: bool = True, temporary: bool = False,
                        distribute_on_random: bool = True, logdir: str | None = None,
                        escape_char: str | None = '\\', quoting: object | None = None) -> int:
        if logdir is None:
            logdir = tempfile.gettempdir()

        if create_if_missing and columns is None:
            rows_iter = iter(rows)
            try:
                first_row = next(rows_iter)
            except StopIteration:
                raise ProgrammingError("No rows to load") from None
            remaining = list(rows_iter)
            all_rows = [first_row] + remaining
            columns = _infer_columns_from_rows(all_rows)
            rows = all_rows

        if create_if_missing and columns:
            col_defs = ', '.join(f'{name} {nz_type}'
                                 for name, nz_type in columns)
            parts = ['CREATE']
            if temporary:
                parts.append('TEMP')
            parts.append(f'TABLE IF NOT EXISTS {table_name} ({col_defs})')
            if distribute_on_random:
                parts.append('DISTRIBUTE ON RANDOM')
            ddl = ' '.join(parts)
            cur = self.cursor()
            await cur.execute(ddl)

        if columns is not None and any(t.startswith('NVARCHAR') or t.startswith('NCLOB') for _, t in columns):
            encoding = 'UTF8'

        csv_bytes = _rows_to_csv_bytes(rows, delimiter, encoding, escape_char,
                                       columns=columns)
        self._ext_table_source = csv_bytes

        using_opts = f"ENCODING '{encoding}' REMOTESOURCE 'python' DELIMITER '{delimiter}'"
        if escape_char is not None:
            using_opts += f" ESCAPECHAR '{escape_char}'"
        using_opts += f" LOGDIR '{logdir}'"

        sql = (
            f"INSERT INTO {table_name} SELECT * "
            f"FROM EXTERNAL '{EXTERNAL_TABLE_STREAM_MARKER}' "
            f"SAMEAS {table_name} "
            f"USING ({using_opts})"
        )
        cur = self.cursor()
        await cur.execute(sql)
        return cur.rowcount

    async def handle_READY_FOR_QUERY(self, data: bytes, ps: Any) -> None:
        self.in_transaction = data != IDLE

    def inspect_datetime(self, value: Datetime) -> Any:
        if value.tzinfo is None:
            return self.py_types[1114]
        else:
            return self.py_types[1184]

    def inspect_int(self, value: int) -> Any | None:
        if min_int2 < value < max_int2:
            return self.py_types[21]
        if min_int4 < value < max_int4:
            return self.py_types[23]
        if min_int8 < value < max_int8:
            return self.py_types[20]
        return None

    def make_params(self, values: tuple[Any, ...]) -> tuple[Any, ...]:
        params: list[Any] = []
        for value in values:
            typ = type(value)
            try:
                params.append(self.py_types[typ])
            except KeyError:
                try:
                    params.append(self.inspect_funcs[typ](value))
                except KeyError as e:
                    param = None
                    for k, v in self.py_types.items():
                        try:
                            if isinstance(value, k):
                                param = v
                                break
                        except TypeError:
                            pass

                    if param is None:
                        for k, v in self.inspect_funcs.items():
                            try:
                                if isinstance(value, k):
                                    param = v(value)
                                    break
                            except TypeError:
                                pass
                            except KeyError:
                                pass

                    if param is None:
                        raise NotSupportedError(
                            "type " + str(e) + " not mapped to pg type")
                    else:
                        params.append(param)

        return tuple(params)

    async def handle_ROW_DESCRIPTION(self, data: bytes, cursor: Cursor) -> None:
        count = h_unpack(data)[0]
        idx = 2
        for _ in range(count):
            name = data[idx:data.find(NULL_BYTE, idx)]
            idx += len(name) + 1
            field: dict[str, Any] = dict(zip(("type_oid", "type_size", "type_modifier",
                              "format"), ihic_unpack(data, idx)))
            field['name'] = name
            idx += 11
            cursor.ps['row_desc'].append(field)  # type: ignore[index]
            field['nzpy_extended_fc'] = self.pg_types[field['type_oid']][0]
            field['func'] = self.pg_types[field['type_oid']][1]

    async def Prepare(self, cursor: Cursor, query: str, vals: Any) -> str:
        statement, make_args = convert_paramstyle(nzpy_extended.paramstyle, query)
        args = tuple(make_args(vals))
        if len(args) >= 65536:
            self.log.warning("got %d parameters but PostgreSQL only "
                             "supports 65535 parameters", len(args))
        rendered_query, expected_args = _render_prepared_statement(statement, args)
        if expected_args == 0:
            return statement
        if len(args) != expected_args:
            self.log.warning("got %d parameters but the statement requires %d", len(args), expected_args)
        return rendered_query

    async def _drain_protocol_generator(self, generator: Any) -> None:
        if generator is None:
            return
        try:
            async for _state in generator:
                pass
        except StopAsyncIteration:
            pass
        finally:
            self._active_generator = None

    async def _drain_socket(self) -> None:
        assert self._stream is not None
        self.log.debug("Draining dirty socket stream...")
        try:
            cached_header = None
            while True:
                if cached_header is not None:
                    header = cached_header
                    cached_header = None
                else:
                    header = await self._read(5)
                response = header[:1]

                self.log.debug("Drain read msg code: %s", response)

                if response in (READY_FOR_QUERY, b"L"):
                    self.status = CONN_EXECUTING
                    self._dirty_socket = False
                    self.log.debug("Socket successfully drained to READY_FOR_QUERY.")
                    break

                if response in (COMMAND_COMPLETE, b"P", ERROR_RESPONSE, ROW_DESCRIPTION, DATA_ROW, b"X"):
                    length = i_unpack(await self._read(4))[0]
                    await self._read(length)
                    continue

                if response == b"Y":
                    inner_header = self._stream.read_view_sync(8)
                    if inner_header is None:
                        inner_header = await self._read(8)
                    tup_len = i_unpack(inner_header, 4)[0]
                    data = self._stream.read_view_sync(tup_len)
                    if data is None:
                        await self._read(tup_len)

                    while True:
                        header = self._stream.read_view_sync(5)
                        if header is None:
                            header = await self._read(5)
                        if header[:1] != b"Y":
                            cached_header = header
                            break
                        inner_header = self._stream.read_view_sync(8)
                        if inner_header is None:
                            inner_header = await self._read(8)
                        tup_len = i_unpack(inner_header, 4)[0]
                        data = self._stream.read_view_sync(tup_len)
                        if data is None:
                            await self._read(tup_len)
                    continue

                if response == b"u":
                    await self._read(10)
                    await self._read(16)
                    length = i_unpack(await self._read(4))[0]
                    await self._read(length)
                    continue

                if response == b"U":
                    try:
                        await self.receiveAndWriteDatatoExternal(None, None)
                    except Exception:
                        pass
                    continue

                if response == b"l":
                    await self.xferTable()
                    continue

                if response == b"x":
                    await self._read(4)
                    continue

                if response == b"e":
                    length = i_unpack(await self._read(4))[0]
                    await self._read(length - 1)
                    await self._read(1)
                    while True:
                        char = await self._read(1)
                        if char == b'\x00':
                            break
                    await self._read(4)
                    while True:
                        numBytes = i_unpack(await self._read(4))[0]
                        if numBytes == 0:
                            break
                        await self._read(numBytes)
                    continue

                if response in (NOTICE_RESPONSE, b"I"):
                    length = i_unpack(await self._read(4))[0]
                    await self._read(length)
                    continue

                length = i_unpack(await self._read(4))[0]
                await self._read(length)
        except Exception as e:
            self.log.warning("Error during socket draining: %s", e)

    async def execute(self, cursor: Cursor, query: str, vals: Any) -> str | None:
        active_gen = getattr(self, '_active_generator', None)
        if active_gen is not None:
            old_cursor = getattr(self, '_active_cursor', None)
            await self._drain_protocol_generator(active_gen)
            if old_cursor is not None:
                old_cursor._cached_rows.clear()
                old_cursor._generator = None
                self._active_cursor = None

        if getattr(self, '_dirty_socket', False):
            await self._drain_socket()

        self._dirty_socket = True

        self._command_generation += 1
        self.error = None
        cursor.notices = deque()
        cursor._row_count = -1
        cursor._has_rows = False
        cursor.ps = {'row_desc': []}

        if vals is None:
            vals = ()
        else:
            query = await self.Prepare(cursor, query, vals)

        if self.status == CONN_EXECUTING:
            await self._read(4)

        buf = bytearray(b'P\xFF\xFF\xFF\xFF')

        if self.commandNumber != -1:
            self.commandNumber += 1
            buf = bytearray(b'P' + i_pack(self.commandNumber))

        if self.commandNumber > 100000:
            self.commandNumber = 1

        query_bytes = query.encode('utf8')
        buf.extend(query_bytes + NULL_BYTE)
        await self._write(buf)
        await self._flush()

        self.log.debug("Buffer sent to nps:%s", buf)

        self.status = CONN_EXECUTING

        cursor._generator = self._connNextResultSetGenerator(cursor)
        self._active_generator = cursor._generator
        self._active_cursor = cursor
        response = None
        try:
            while True:
                try:
                    state = await cursor._generator.__anext__()
                except StopAsyncIteration:
                    break
                if state == "ROW_DESCRIPTION":
                    response = state
                    if (cursor.ps.get('tupdesc') is None and
                            len(cursor.ps.get('row_desc', [])) > 0):
                        continue
                    break
                if state in ("DATA_ROW", "DATA_BATCH"):
                    response = "ROW_DESCRIPTION"
                    break
                if state == "COMMAND_COMPLETE":
                    response = "COMMAND_COMPLETE"
                    continue
                if state == "READY_FOR_QUERY":
                    response = "READY_FOR_QUERY"
                    break
                if state == "ERROR":
                    response = state
                    await self._drain_protocol_generator(cursor._generator)
                    cursor._generator = None
                    break
        except StopAsyncIteration:
            pass

        if self.error is not None:
            raise self.error

        if response == "ROW_DESCRIPTION" and len(cursor.ps.get('row_desc', [])) > 0:
            cursor._has_rows = True
        else:
            cursor._has_rows = len(cursor._cached_rows) > 0
        return response

    async def _connNextResultSetGenerator(self, cursor: Cursor) -> AsyncGenerator[str, None]:
        stream = self._stream
        assert stream is not None
        fname = None
        fh = None
        self._cached_header = None

        while True:
            if self._cached_header is not None:
                header = self._cached_header
                self._cached_header = None
            else:
                header = await self._read(5)
            response = header[:1]

            if response == COMMAND_COMPLETE:
                length = i_unpack(await self._read(4))[0]
                data = await self._read(length)
                await self.handle_COMMAND_COMPLETE(data, cursor)
                self.log.debug("Response received from "
                               "backend: %s", str(data, self._client_encoding))
                yield "COMMAND_COMPLETE"
                continue
            if response == READY_FOR_QUERY:
                self._dirty_socket = False
                self._active_generator = None
                self._active_cursor = None
                yield "READY_FOR_QUERY"
                return
            if response == b"L":
                self._dirty_socket = False
                self._active_generator = None
                self._active_cursor = None
                yield "READY_FOR_QUERY"
                return
            if response == b"0":
                pass
            if response == b"A":
                pass
            if response == b"P":
                length = i_unpack(await self._read(4))[0]
                self.log.debug("Response received from "
                               "backend:%s", str(await self._read(length),
                                                 self._client_encoding))
                continue
            if response == ERROR_RESPONSE:
                length = i_unpack(await self._read(4))[0]
                data = await self._read(length)
                await self.handle_ERROR_RESPONSE(data, cursor)
                self.log.debug("Response received from backend:%s", self.error)
                yield "ERROR"
                continue
            if response == ROW_DESCRIPTION:
                length = i_unpack(await self._read(4))[0]
                prev_tupdesc = cursor.ps.get('tupdesc') if cursor.ps else None
                cursor.ps = {'row_desc': [], 'tupdesc': prev_tupdesc}
                await self.handle_ROW_DESCRIPTION(await self._read(length), cursor)
                cursor.ps['input_funcs'] = list(f['func'] for
                                                 f in cursor.ps['row_desc'])
                yield "ROW_DESCRIPTION"
            if response == DATA_ROW:
                length = i_unpack(await self._read(4))[0]
                await self.handle_DATA_ROW(await self._read(length), cursor)
                cursor._has_rows = True
                yield "DATA_ROW"
            if response == b"X":
                length = i_unpack(await self._read(4))[0]
                self.tupdesc = DbosTupleDesc()
                self.Res_get_dbos_column_descriptions(await self._read(length),
                                                      self.tupdesc)
                if cursor.ps is not None:
                    cursor.ps['tupdesc'] = self.tupdesc
                yield "ROW_DESCRIPTION"
                continue
            if response == b"Y":
                inner_header = stream.read_view_sync(8)
                if inner_header is None:
                    inner_header = await self._read(8)
                tup_len = i_unpack(inner_header, 4)[0]
                data = stream.read_view_sync(tup_len)
                if data is None:
                    data = await self._read(tup_len)
                self._process_dbos_payload(cursor, self.tupdesc, bytes(data))

                if _HAVE_C_EXT:
                    assert _c_ext is not None
                    view = stream.read_available_view()
                    if view is not None and len(view) > 13:
                        rows, consumed = _c_ext.process_dbos_batch(
                            view,
                            self.tupdesc.field_type, self.tupdesc.field_size, self.tupdesc.field_trueSize,
                            self.tupdesc.field_offset, self.tupdesc.field_fixedSize, self.tupdesc.field_physField,
                            self.tupdesc.numFields, self.tupdesc.nullsAllowed, self.tupdesc.fixedFieldsSize, self.tupdesc.numVaryingFields,
                            self._char_varchar_encoding, self._client_encoding
                        )
                        if rows:
                            cursor._cached_rows.extend(rows)
                            stream.advance_head(consumed)

                header = stream.read_view_sync(5)
                if header is None:
                    header = await self._read(5)
                self._cached_header = header
                if len(cursor._cached_rows) > 0:
                    cursor._has_rows = True
                yield "DATA_BATCH"
                continue
            if response == b"u":
                await self._read(10)
                await self._read(16)
                length = i_unpack(await self._read(4))[0]
                fnameBuf = await self._read(length)
                fname = str(fnameBuf, self._client_encoding)
                try:
                    stat_result = await asyncio.to_thread(os.stat, fname) if os.path.exists(fname) else None
                    is_fifo = stat.S_ISFIFO(stat_result.st_mode) if stat_result else False
                    if is_fifo:
                        fh = await asyncio.to_thread(open, fname, "wb")
                    else:
                        fh = await asyncio.to_thread(open, fname, "wb+")  # type: ignore[arg-type]
                    self.log.debug("Successfully opened file: %s", fname)
                    buf = bytearray(i_pack(0))
                    await self._write(buf)
                    await self._flush()
                except Exception:
                    self.log.warning("Error while opening file")

            if response == b"U":
                if fh is not None:
                    await self.receiveAndWriteDatatoExternal(fname, fh)
                yield "EXTAB_DATA"

            if response == b"l":
                await self.xferTable()
                yield "EXTAB_IMPORT"

            if response == b"x":
                await self._read(4)
                self.log.warning("Error operation cancel")
                yield "EXTAB_CANCEL"

            if response == b"e":
                length = i_unpack(await self._read(4))[0]
                logDir = str(await self._read(length - 1), self._client_encoding)

                await self._read(1)
                char = c_unpack(await self._read(1))[0]
                filenameBuf = bytearray(char)
                while True:
                    char = c_unpack(await self._read(1))[0]
                    if char == b'\x00':
                        break
                    filenameBuf.extend(char)

                filename = str(filenameBuf, self._client_encoding)
                logType = i_unpack(await self._read(4))[0]
                if not await self.getFileFromBE(logDir, filename, logType):
                    self.log.debug("Error in writing file received from BE")
                continue

            if response == NOTICE_RESPONSE:
                length = i_unpack(await self._read(4))[0]
                notice = str(await self._read(length), self._client_encoding)
                if notice.startswith('NOTICE:'):
                    notice = notice[len('NOTICE:'):]
                notice = notice.strip().rstrip('\x00')
                cursor.notices.append(notice)
                if getattr(cursor, 'notice_handler', None) and callable(cursor.notice_handler):  # type: ignore[attr-defined]
                    try:
                                                cursor.notice_handler(notice)  # type: ignore[attr-defined]
                    except Exception as e:
                        self.log.warning("Error in notice_handler: %s", e)
                self.log.debug("Response received from backend:%s", notice)
                yield "NOTICE"

            if response == b"I":
                length = i_unpack(await self._read(4))[0]
                notice = str(await self._read(length), self._client_encoding)
                if notice.startswith('NOTICE:'):
                    notice = notice[len('NOTICE:'):]
                notice = notice.strip().rstrip('\x00')
                cursor.notices.append(notice)
                if getattr(cursor, 'notice_handler', None) and callable(cursor.notice_handler):  # type: ignore[attr-defined]
                    try:
                                                cursor.notice_handler(notice)  # type: ignore[attr-defined]
                    except Exception as e:
                        self.log.warning("Error in notice_handler: %s", e)
                self.log.debug("Response received from backend:%s", notice)
                cursor._cached_rows.append([])
                yield "NOTICE"

            if response == b"s":
                length = i_unpack(await self._read(4))[0]
                await self._read(length)
                continue

    def Res_get_dbos_column_descriptions(self, data: bytes, tupdesc: DbosTupleDesc) -> None:
        data_idx = 0
        tupdesc.version = i_unpack(data, data_idx)[0]
        tupdesc.nullsAllowed = i_unpack(data, data_idx + 4)[0]
        tupdesc.sizeWord = i_unpack(data, data_idx + 8)[0]
        tupdesc.sizeWordSize = i_unpack(data, data_idx + 12)[0]
        tupdesc.numFixedFields = i_unpack(data, data_idx + 16)[0]
        tupdesc.numVaryingFields = i_unpack(data, data_idx + 20)[0]
        tupdesc.fixedFieldsSize = i_unpack(data, data_idx + 24)[0]
        tupdesc.maxRecordSize = i_unpack(data, data_idx + 28)[0]
        tupdesc.numFields = i_unpack(data, data_idx + 32)[0]

        data_idx += 36
        nfields = tupdesc.numFields
        if nfields is None:
            return
        for _ in range(nfields):
            tupdesc.field_type.append(i_unpack(data, data_idx)[0])
            tupdesc.field_size.append(i_unpack(data, data_idx + 4)[0])
            tupdesc.field_trueSize.append(i_unpack(data, data_idx + 8)[0])
            tupdesc.field_offset.append(i_unpack(data, data_idx + 12)[0])
            tupdesc.field_physField.append(i_unpack(data, data_idx + 16)[0])
            tupdesc.field_logField.append(i_unpack(data, data_idx + 20)[0])
            tupdesc.field_nullAllowed.append(i_unpack(data, data_idx + 24)[0])
            tupdesc.field_fixedSize.append(i_unpack(data, data_idx + 28)[0])
            tupdesc.field_springField.append(i_unpack(data, data_idx + 32)[0])
            data_idx += 36

        tupdesc.DateStyle = i_unpack(data, data_idx)[0]
        tupdesc.EuroDates = i_unpack(data, data_idx + 4)[0]

    def _process_dbos_payload(self, cursor: Cursor, tupdesc: DbosTupleDesc, data: bytes) -> None:
        numFields = tupdesc.numFields
        mv = memoryview(data)

        if _HAVE_C_EXT:
            assert _c_ext is not None
            row = _c_ext.process_dbos_row(
                data,
                tupdesc.field_type, tupdesc.field_size, tupdesc.field_trueSize,
                tupdesc.field_offset, tupdesc.field_fixedSize, tupdesc.field_physField,
                numFields, tupdesc.nullsAllowed, tupdesc.fixedFieldsSize, tupdesc.numVaryingFields,
                self._char_varchar_encoding, self._client_encoding
            )
            cursor._cached_rows.append(row)
            return

        self._build_dbos_row_python(cursor, tupdesc, mv, data)

    def _build_dbos_row_python(self, cursor: Cursor, tupdesc: DbosTupleDesc, mv: memoryview, data: bytes) -> None:
        import struct
        numFields = tupdesc.numFields
        if numFields is None:
            return
        nfields: int = numFields

        bitmaplen = nfields // 8
        if (nfields % 8) > 0:
            bitmaplen += 1

        b_data = mv[2:2+bitmaplen]
        bitmap = [(b >> j) & 1 for b in b_data for j in range(8)]

        var_offsets: list[int] = []
        current_voff = tupdesc.fixedFieldsSize
        if current_voff is None:
            return
        for _ in range(tupdesc.numVaryingFields if tupdesc.numVaryingFields is not None else 0):
            var_offsets.append(current_voff)
            if current_voff + 2 <= len(data):
                vlen = h_le_unpack(data, current_voff)[0]
                if vlen % 2 == 0:
                    current_voff += vlen
                else:
                    current_voff += vlen + 1

        field_lf = 0
        cur_field = 0
        row: list[Any] = []

        while field_lf < nfields and cur_field < nfields:

            if bitmap[tupdesc.field_physField[field_lf]] == 1 and tupdesc.nullsAllowed != 0:
                row.append(None)
                cur_field += 1
                field_lf += 1
                continue

            if tupdesc.field_fixedSize[cur_field] != 0:
                offset = tupdesc.field_offset[cur_field]
            else:
                offset = var_offsets[tupdesc.field_offset[cur_field]]

            fldtype = tupdesc.field_type[cur_field]
            if fldtype == NzTypeUnknown:
                fldtype = NzTypeVarChar

            if fldtype == NzTypeChar:
                fldlen = tupdesc.field_size[cur_field]
                value = str(mv[offset:offset+fldlen], self._char_varchar_encoding)
                value = value.rstrip('\x00').ljust(fldlen)
                row.append(value)
            elif fldtype in [NzTypeNChar, NzTypeNVarChar]:
                cursize = h_le_unpack(data, offset)[0] - 2
                value = str(mv[offset+2:offset+cursize+2], self._client_encoding)
                if fldtype == NzTypeNChar:
                    value = value.rstrip('\x00').ljust(tupdesc.field_size[cur_field])
                row.append(value)
            elif fldtype in [NzTypeVarChar, NzTypeVarFixedChar, NzTypeGeometry, NzTypeVarBinary,
                           NzTypeJson, NzTypeJsonb, NzTypeJsonpath, NzTypeVector]:
                cursize = h_le_unpack(data, offset)[0] - 2
                value = str(mv[offset+2:offset+cursize+2], self._char_varchar_encoding)
                row.append(value)
            elif fldtype == NzTypeInt8:
                row.append(q_le_unpack(data, offset)[0])
            elif fldtype == NzTypeInt:
                row.append(i_le_unpack(data, offset)[0])
            elif fldtype == NzTypeInt2:
                row.append(h_le_unpack(data, offset)[0])
            elif fldtype == NzTypeInt1:
                row.append(data[offset])
            elif fldtype == NzTypeDouble:
                row.append(struct.unpack_from('<d', data, offset)[0])
            elif fldtype == NzTypeFloat:
                row.append(struct.unpack_from('<f', data, offset)[0])
            elif fldtype == NzTypeDate:
                fldlen = tupdesc.field_size[cur_field]
                workspace = q_le_unpack(data, offset)[0] if fldlen >= 8 else int.from_bytes(mv[offset:offset+fldlen], 'little', signed=True)
                date_value = j2date(workspace + J2000_OFFSET)
                row.append(date(date_value[0], date_value[1], date_value[2]))
            elif fldtype == NzTypeTime:
                fldlen = tupdesc.field_size[cur_field]
                workspace = q_le_unpack(data, offset)[0] if fldlen >= 8 else int.from_bytes(mv[offset:offset+fldlen], 'little', signed=True)
                time_value = time2struct(workspace)
                if time_value[3]:
                    row.append(time(time_value[0], time_value[1], time_value[2], time_value[3]))
                else:
                    row.append(time(time_value[0], time_value[1], time_value[2]))
            elif fldtype == NzTypeInterval:
                fldlen = tupdesc.field_size[cur_field]
                interval_time = q_le_unpack(data, offset)[0] if fldlen >= 12 else int.from_bytes(mv[offset:offset+fldlen-4], 'little', signed=True)
                interval_month = i_le_unpack(data, offset+fldlen-4)[0]
                row.append(Interval(microseconds=interval_time, days=0, months=interval_month))
            elif fldtype == NzTypeTimeTz:
                fldlen = tupdesc.field_size[cur_field]
                timetz_time = q_le_unpack(data, offset)[0] if fldlen >= 12 else int.from_bytes(mv[offset:offset+fldlen-4], 'little', signed=True)
                timetz_zone = i_le_unpack(data, offset+fldlen-4)[0]
                row.append(timetz_out_timetzadt(timetz_time, timetz_zone))
            elif fldtype == NzTypeTimestamp:
                fldlen = tupdesc.field_size[cur_field]
                workspace = q_le_unpack(data, offset)[0] if fldlen >= 8 else int.from_bytes(mv[offset:offset+fldlen], 'little', signed=True)
                timestamp_value: tuple[int, int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0, 0)
                if fldlen == 8:
                    result = timestamp2struct(workspace)
                    if result is not False:
                        timestamp_value = result  # type: ignore[assignment]
                row.append(Datetime(timestamp_value[0], timestamp_value[1], timestamp_value[2], timestamp_value[3], timestamp_value[4], timestamp_value[5], timestamp_value[6]))
            elif fldtype == NzTypeNumeric:
                fsize = tupdesc.field_size[cur_field]
                scale = fsize & 0x00FF
                chunk_len = tupdesc.field_trueSize[cur_field]
                count = chunk_len // 4
                words = [int.from_bytes(data[offset+i*4:offset+(i+1)*4], 'little', signed=False) for i in range(count)]
                val = 0
                for w in words:
                    val = (val << 32) | w
                total_bits = count * 32
                if words[0] >> 31:
                    val -= (1 << total_bits)
                row.append(Decimal(val) * (Decimal(10) ** -scale))
            elif fldtype == NzTypeBool:
                row.append(data[offset] == 1)

            cur_field += 1
            field_lf += 1

        cursor._cached_rows.append(row)

    async def Res_read_dbos_tuple(self, cursor: Cursor, tupdesc: DbosTupleDesc) -> None:
        header = await self._read(8)
        length = i_unpack(header, 4)[0]
        data = await self._read(length)
        self._process_dbos_payload(cursor, tupdesc, data)

    def CTable_FieldAt(self, tupdesc: DbosTupleDesc, data: bytes, cur_field: int) -> Any:
        if tupdesc.field_fixedSize[cur_field] != 0:
            return self.CTable_i_fixedFieldPtr(data,
                                               tupdesc.field_offset[cur_field])

        return self.CTable_i_varFieldPtr(data, tupdesc.fixedFieldsSize,  # type: ignore[arg-type]
                                         tupdesc.field_offset[cur_field])

    def CTable_i_fixedFieldPtr(self, data: bytes, offset: int) -> bytes:
        data = data[offset:]
        return data

    def CTable_i_varFieldPtr(self, data: bytes, fixedOffset: int, varDex: int) -> bytes:
        lenP = data[fixedOffset:]
        for _ in range(varDex):
            length = int.from_bytes(lenP[0:2], 'little')
            if length % 2 == 0:
                lenP = lenP[length:]
            else:
                lenP = lenP[length + 1:]

        return lenP

    @staticmethod
    def _oid_type_name(oid: int) -> str:
        names = {
            _OID_BOOL: 'BOOLEAN',
            _OID_BYTEINT: 'BYTEINT',
            _OID_INT2: 'SMALLINT',
            _OID_INT4: 'INTEGER',
            _OID_INT8: 'BIGINT',
            _OID_NUMERIC: 'NUMERIC',
            _OID_FLOAT4: 'REAL',
            _OID_FLOAT8: 'DOUBLE PRECISION',
            _OID_BPCHAR: 'CHAR',
            _OID_VARCHAR: 'VARCHAR',
            _OID_TEXT: 'TEXT',
            _OID_DATE: 'DATE',
            _OID_TIME: 'TIME',
            _OID_TIMESTAMP: 'TIMESTAMP',
            _OID_TIMESTAMPTZ: 'TIMESTAMPTZ',
            _OID_TIMETZ: 'TIMETZ',
            _OID_NCHAR: 'NCHAR',
            _OID_NVARCHAR: 'NVARCHAR',
        }
        return names.get(oid, f'UNKNOWN({oid})')

    @staticmethod
    def _numeric_precision_scale_from_modifier(type_mod: int) -> tuple[int, int]:
        if type_mod > TYPE_MOD_OFFSET:
            normalized = type_mod - TYPE_MOD_OFFSET
            return normalized >> 16, normalized & 0xffff
        return 0, 0

    @staticmethod
    def _character_declared_length(oid: int, type_mod: int) -> int | None:
        if oid in (_OID_BPCHAR, _OID_VARCHAR, _OID_TEXT, _OID_NCHAR, _OID_NVARCHAR):
            if type_mod > TYPE_MOD_OFFSET:
                return type_mod - TYPE_MOD_OFFSET
        return None

    def _column_null_ok(self, index: int, tupdesc: DbosTupleDesc | None) -> bool:
        if tupdesc is None:
            return True
        if tupdesc.nullsAllowed is not None and tupdesc.nullsAllowed <= 0:
            return False
        if index < len(tupdesc.field_nullAllowed):
            return bool(tupdesc.field_nullAllowed[index])
        return True

    def _resolve_column_metadata(self, col: dict[str, Any], index: int, tupdesc: DbosTupleDesc | None) -> dict[str, Any]:
        oid = col['type_oid']
        type_mod = col.get('type_modifier', -1)
        type_size = col.get('type_size', -1)
        name = col['name'].decode() if isinstance(col['name'], bytes) else col['name']
        type_name = self._oid_type_name(oid)
        declared_len = self._character_declared_length(oid, type_mod)
        num_prec, num_scale = self._numeric_precision_scale_from_modifier(type_mod)

        column_size = type_size if type_size > 0 else -1

        if tupdesc is not None and index < tupdesc.numFields:  # type: ignore[operator]
            nz_type = tupdesc.field_type[index]
            if nz_type == _NZ_TYPE_NUMERIC:
                num_prec = self.CTable_i_fieldPrecision(tupdesc, index)
                num_scale = self.CTable_i_fieldScale(tupdesc, index)
                if num_prec > 0:
                    column_size = max(column_size, tupdesc.field_size[index] & 0xFFFF)
            elif type_size <= 0:
                fs = tupdesc.field_size[index]
                if fs > 0:
                    column_size = fs & 0xFFFF if fs > 255 else fs

        if oid == _OID_NUMERIC and num_prec == 0:
            num_prec, num_scale = self._numeric_precision_scale_from_modifier(type_mod)
            if num_prec > 0 and column_size <= 0:
                column_size = num_prec // 2 + 1

        if declared_len is not None:
            column_size = declared_len

        numeric_precision = num_prec if oid == _OID_NUMERIC else -1
        numeric_scale = num_scale if oid == _OID_NUMERIC else -1

        if oid == _OID_FLOAT8:
            numeric_precision, numeric_scale = 53, -1
        elif oid == _OID_FLOAT4:
            numeric_precision, numeric_scale = 24, -1

        data_type = self._oid_to_python_type(oid)
        declared_type_name = type_name
        if declared_len is not None:
            declared_type_name = f'{type_name}({declared_len})'
        elif oid == _OID_NUMERIC and num_prec > 0:
            declared_type_name = f'NUMERIC({num_prec},{num_scale})'

        display_size = column_size if column_size > 0 else None
        internal_size = type_size if type_size > 0 else column_size if column_size > 0 else None

        return {
            'name': name,
            'type_name': type_name,
            'declared_type_name': declared_type_name,
            'provider_type': oid,
            'type_modifier': type_mod,
            'column_size': column_size,
            'display_size': display_size,
            'internal_size': internal_size,
            'numeric_precision': numeric_precision,
            'numeric_scale': numeric_scale,
            'data_type': data_type,
            'null_ok': self._column_null_ok(index, tupdesc),
            'is_long': column_size > 8000,
            'declared_length': declared_len,
        }

    @staticmethod
    def _oid_to_python_type(oid: int) -> type:
        import decimal as _decimal
        mapping: dict[int, type] = {
            _OID_BOOL: bool,
            _OID_BYTEINT: int,
            _OID_INT2: int,
            _OID_INT4: int,
            _OID_INT8: int,
            _OID_NUMERIC: _decimal.Decimal,
            _OID_FLOAT4: float,
            _OID_FLOAT8: float,
            _OID_BPCHAR: str,
            _OID_VARCHAR: str,
            _OID_TEXT: str,
            _OID_DATE: datetime.date,
            _OID_TIME: datetime.time,
            _OID_TIMESTAMP: datetime.datetime,
            _OID_TIMESTAMPTZ: datetime.datetime,
            _OID_TIMETZ: str,
            _OID_NCHAR: str,
            _OID_NVARCHAR: str,
        }
        return mapping.get(oid, str)

    def CTable_i_fieldType(self, tupdesc: DbosTupleDesc, coldex: int) -> int:
        return (tupdesc.field_type[coldex])

    def CTable_i_fieldSize(self, tupdesc: DbosTupleDesc, coldex: int) -> int:
        return (tupdesc.field_size[coldex])

    def CTable_i_fieldPrecision(self, tupdesc: DbosTupleDesc, coldex: int) -> int:
        return (((tupdesc.field_size[coldex]) >> 8) & 0x7F)

    def CTable_i_fieldScale(self, tupdesc: DbosTupleDesc, coldex: int) -> int:
        return ((tupdesc.field_size[coldex]) & 0x00FF)

    def CTable_i_fieldNumericDigit32Count(self, tupdesc: DbosTupleDesc, coldex: int) -> int:
        sizeTNumericDigit = 4
        return int(tupdesc.field_trueSize[coldex] / sizeTNumericDigit)

    async def receiveAndWriteDatatoExternal(self, fname: str | None, fh: Any) -> None:
        await self._read(4)

        try:
            while True:
                try:
                    status = i_unpack(await self._read(4))[0]
                except Exception as e:
                    self.log.warning("Error while retrieving status: %s", str(e))
                    break

                if status == EXTAB_SOCK_DATA:
                    numBytes = i_unpack(await self._read(4))[0]
                    try:
                        blockBuffer = await self._read(numBytes)
                        if fh is not None:
                            await asyncio.to_thread(fh.write, blockBuffer)
                            await asyncio.to_thread(fh.flush)
                        self.log.info("Successfully written %d bytes to file", numBytes)
                    except Exception as e:
                        self.log.error("Error writing data to file '%s': %s", fname, str(e))
                        raise
                    continue

                elif status == EXTAB_SOCK_DONE:
                    self.log.info("unload - done receiving data")
                    break

                elif status == EXTAB_SOCK_ERROR:
                    len_msg = h_unpack(await self._read(2))[0]
                    errorMsg = str(await self._read(len_msg), self._client_encoding)

                    len_obj = h_unpack(await self._read(2))[0]
                    errorObject = str(await self._read(len_obj), self._client_encoding)

                    self.log.warning("unload - ErrorMsg: %s", errorMsg)
                    self.log.warning("unload - ErrorObj: %s", errorObject)
                    break

                else:
                    self.log.warning("unload - unexpected status: %d", status)
                    break

        finally:
            if fh is not None:
                try:
                    await asyncio.to_thread(fh.close)
                    self.log.debug("Closed export file: %s", fname)
                except Exception:
                    pass

        return

    async def xferTable(self) -> None:
        await self._read(4)
        clientversion = 1

        char = c_unpack(await self._read(1))[0]
        filenameBuf = bytearray(char)
        while True:
            char = c_unpack(await self._read(1))[0]
            if char == b'\x00':
                break
            filenameBuf.extend(char)

        filename = str(filenameBuf, self._client_encoding)

        hostversion = i_unpack(await self._read(4))[0]

        val = bytearray(i_pack(clientversion))
        await self._write(val)
        await self._flush()

        format = i_unpack(await self._read(4))[0]
        blockSize = i_unpack(await self._read(4))[0]
        self.log.info("Format=%d Block size=%d "
                      "Host version=%d ", format,
                      blockSize, hostversion)

        effectiveBlockSize = max(blockSize, 1)

        try:
            if (filename.startswith(EXTERNAL_TABLE_STREAM_MARKER)
                    and self._ext_table_source is not None):
                self.log.info("Using in-memory data source for external table import")
                source = self._ext_table_source
                self._ext_table_source = None

                async def _send_chunk(data_chunk: bytes) -> None:
                    data_len = len(data_chunk)
                    if blockSize < data_len:
                        diff = data_len - blockSize
                        val = bytearray(i_pack(EXTAB_SOCK_DATA) + i_pack(blockSize))
                        val.extend(data_chunk[:blockSize])
                        await self._write(val)
                        await self._flush()
                        val = bytearray(i_pack(EXTAB_SOCK_DATA) + i_pack(diff))
                        val.extend(data_chunk[blockSize:])
                        await self._write(val)
                        await self._flush()
                    else:
                        val = bytearray(i_pack(EXTAB_SOCK_DATA) + i_pack(data_len))
                        val.extend(data_chunk)
                        await self._write(val)
                        await self._flush()
                    self.log.debug("No. of bytes sent to BE:%s", data_len)

                if isinstance(source, (bytes, bytearray, memoryview)):
                    offset = 0
                    total_len = len(source)
                    while offset < total_len:
                        end = min(offset + effectiveBlockSize, total_len)
                        chunk = source[offset:end]
                        await _send_chunk(bytes(chunk))
                        offset += effectiveBlockSize
                elif hasattr(source, '__aiter__'):
                    async for chunk in source:
                        if not chunk:
                            continue
                        await _send_chunk(bytes(chunk))
                else:
                    for chunk in source:
                        if not chunk:
                            continue
                        await _send_chunk(bytes(chunk))
            else:
                filehandle = await asyncio.to_thread(open, filename, 'rb')
                self.log.info("Successfully opened External"
                              " file to read:%s", filename)
                while True:
                    data = await asyncio.to_thread(filehandle.read, effectiveBlockSize)
                    if not data:
                        break
                    data_len = len(data)
                    if blockSize < data_len:
                        diff = data_len - blockSize
                        val = bytearray(i_pack(EXTAB_SOCK_DATA) +
                                        i_pack(blockSize))
                        val.extend(data[:blockSize])
                        await self._write(val)
                        await self._flush()
                        val = bytearray(i_pack(EXTAB_SOCK_DATA) +
                                        i_pack(diff))
                        val.extend(data[blockSize:])
                        await self._write(val)
                        await self._flush()
                    else:
                        val = bytearray(i_pack(EXTAB_SOCK_DATA) +
                                        i_pack(data_len))
                        val.extend(data)
                        await self._write(val)
                        await self._flush()
                    self.log.debug("No. of bytes sent to BE:%s", data_len)
                await asyncio.to_thread(filehandle.close)

            val = bytearray(i_pack(EXTAB_SOCK_DONE))
            await self._write(val)
            await self._flush()
            self.log.info("sent EXTAB_SOCK_DONE to reader")

        except Exception as e:
            self.log.error("Error opening file '%s': %s", filename, str(e))
            try:
                val = bytearray(i_pack(EXTAB_SOCK_ERROR))
                await self._write(val)
                await self._flush()
            except Exception:
                pass
            raise

    async def getFileFromBE(self, logDir: str, filename: str, logType: int) -> bool:
        status = True

        fullpath = path.join(logDir, filename)

        if logType == 1:
            fullpath = fullpath + ".nzlog"
            fh = await asyncio.to_thread(open, fullpath, "wb+")
        elif logType == 2:
            fullpath = fullpath + ".nzbad"
            fh = await asyncio.to_thread(open, fullpath, "wb+")
        elif logType == 3:
            fullpath = fullpath + ".nzstats"
            fh = await asyncio.to_thread(open, fullpath, "wb+")
        else:
            fh = await asyncio.to_thread(open, fullpath, "wb+")

        try:
            while True:
                numBytes = i_unpack(await self._read(4))[0]

                if numBytes == 0:
                    break

                dataBuffer = await self._read(numBytes)

                if status:
                    try:
                        await asyncio.to_thread(fh.write, dataBuffer)
                        self.log.info("Successfully written data "
                                      "into file: %s", fullpath)
                    except Exception as e:
                        self.log.error("Error in writing data to file '%s': %s",
                                      fullpath, str(e))
                        status = False

        finally:
            await asyncio.to_thread(fh.close)

        return status

    async def _send_message(self, code: bytes, data: bytes) -> None:
        try:
            await self._write(code)
            await self._write(i_pack(len(data) + 4))
            await self._write(data)
            await self._write(FLUSH_MSG)
        except ValueError as e:
            if str(e) == "write to closed file":
                raise ConnectionClosedError()
            else:
                raise e
        except AttributeError:
            raise ConnectionClosedError()

    async def send_EXECUTE(self, cursor: Cursor) -> None:
        await self._write(EXECUTE_MSG)
        await self._write(FLUSH_MSG)

    def handle_NO_DATA(self, msg: bytes, ps: Any) -> None:
        pass

    async def handle_COMMAND_COMPLETE(self, data: bytes, cursor: Cursor) -> None:
        values = data[:-1].split(b' ')
        command = values[0]
        if command in self._commands_with_count:
            row_count = int(values[-1])
            if cursor._row_count == -1:
                cursor._row_count = row_count
            else:
                cursor._row_count += row_count

        if command in (b"ALTER", b"CREATE"):
            for scache in self._caches.values():
                for pcache in scache.values():
                    for ps in pcache['ps'].values():
                        await self.close_prepared_statement(ps['statement_name_bin'])
                    pcache['ps'].clear()

    async def handle_DATA_ROW(self, data: bytes, cursor: Cursor) -> None:
        numberofcol = len(cursor.ps['row_desc'])  # type: ignore[index]
        bitmaplen = numberofcol // 8
        if (numberofcol % 8) > 0:
            bitmaplen += 1

        hex = data[0:bitmaplen].hex()
        dec = int(hex, 16)

        bitmap = decimalToBinary(dec, bitmaplen * 8)
        bitmap.reverse()

        data_idx = bitmaplen
        row: list[Any] = []
        row_desc = cursor.ps['row_desc']  # type: ignore[index]
        for i, func in enumerate(cursor.ps['input_funcs']):  # type: ignore[index]
            if bitmap[i] == 0:
                row.append(None)
            else:
                vlen = i_unpack(data, data_idx)[0]
                data_idx += 4
                if vlen < 4:
                    raise InterfaceError(
                        f"Invalid data row: vlen={vlen} for column {i} "
                        f"(min 4 expected)"
                    )
                val = func(data, data_idx, vlen - 4)
                data_idx += vlen - 4
                if row_desc[i]['type_oid'] == 1042:
                    mod = row_desc[i]['type_modifier']
                    if mod > 0:
                        pad_to = (mod >> 16) & 0xFFFF
                        if pad_to > 0:
                            val = val.rstrip('\x00').ljust(pad_to)
                row.append(val)

        cursor._cached_rows.append(row)

    async def handle_messages(self, cursor: Cursor) -> None:
        code = self.error = None

        while code != READY_FOR_QUERY:
            code, data_len = ci_unpack(await self._read(5))
            await self.message_types[code](await self._read(data_len - 4), cursor)

        if self.error is not None:
            raise self.error

    async def close_prepared_statement(self, statement_name_bin: bytes) -> None:
        await self._send_message(CLOSE, STATEMENT + statement_name_bin)
        await self._write(SYNC_MSG)
        await self._flush()
        await self.handle_messages(self._cursor)

    async def handle_PARAMETER_STATUS(self, data: bytes, ps: Any) -> None:
        pos = data.find(NULL_BYTE)
        key, value = data[:pos], data[pos + 1:-1]
        self.parameter_statuses.append((key, value))
        if key == b"client_encoding":
            encoding = value.decode("ascii").lower()
            self._client_encoding = pg_to_py_encodings.get(encoding, encoding)  # type: ignore[assignment]
            self._char_varchar_encoding = self._client_encoding

        elif key == b"integer_datetimes":
            if value == b'on':
                self.py_types[1114] = (1114, FC_BINARY, timestamp_send_integer)
                self.pg_types[1114] = (FC_TEXT, timestamp_in)

                self.py_types[1184] = (
                    1184, FC_BINARY, timestamptz_send_integer)
                self.pg_types[1184] = (FC_TEXT, timestamptz_in)

                self.py_types[Interval] = (
                    1186, FC_BINARY, interval_send_integer)
                self.py_types[Timedelta] = (
                    1186, FC_BINARY, interval_send_integer)
                self.pg_types[1186] = (FC_TEXT, interval_recv_integer)
            else:
                self.py_types[1114] = (1114, FC_BINARY, timestamp_send_float)
                self.pg_types[1114] = (FC_TEXT, timestamp_in)
                self.py_types[1184] = (1184, FC_BINARY, timestamptz_send_float)
                self.pg_types[1184] = (FC_TEXT, timestamptz_in)

                self.py_types[Interval] = (
                    1186, FC_BINARY, interval_send_float)
                self.py_types[Timedelta] = (
                    1186, FC_BINARY, interval_send_float)
                self.pg_types[1186] = (FC_TEXT, interval_recv_float)

        elif key == b"server_version":
            self._server_version = LooseVersion(value.decode('ascii'))
            if self._server_version < LooseVersion('8.2.0'):
                self._commands_with_count = (
                    b"INSERT", b"DELETE", b"UPDATE", b"MOVE", b"FETCH")
            elif self._server_version < LooseVersion('9.0.0'):
                self._commands_with_count = (
                    b"INSERT", b"DELETE", b"UPDATE", b"MOVE", b"FETCH",
                    b"COPY")

    def array_inspect(self, value: list[Any]) -> Any:
        first_element = array_find_first_element(value)
        oid: int = 25
        fc: int = FC_BINARY
        array_oid: int = 0
        send_func: Any = null_send
        typ: Any = str
        if first_element is None:
            oid = 25
            fc = FC_BINARY
            array_oid = pg_array_types[oid]
        else:
            typ = type(first_element)

            if issubclass(typ, int):
                typ = int
                int2_ok, int4_ok, int8_ok = True, True, True
                for v in array_flatten(value):
                    if v is None:
                        continue
                    if min_int2 < v < max_int2:  # type: ignore[operator]
                        continue
                    int2_ok = False
                    if min_int4 < v < max_int4:  # type: ignore[operator]
                        continue
                    int4_ok = False
                    if min_int8 < v < max_int8:  # type: ignore[operator]
                        continue
                    int8_ok = False
                if int2_ok:
                    array_oid = 1005
                    oid, fc, send_func = (21, FC_BINARY, h_pack)
                elif int4_ok:
                    array_oid = 1007
                    oid, fc, send_func = (23, FC_BINARY, i_pack)
                elif int8_ok:
                    array_oid = 1016
                    oid, fc, send_func = (20, FC_BINARY, q_pack)
                else:
                    raise ArrayContentNotSupportedError(
                        "numeric not supported as array contents")
            else:
                try:
                    oid, fc, send_func = self.make_params((first_element,))[0]

                    if oid in (705, 1043, 25):
                        oid = 25
                        fc = FC_BINARY
                    array_oid = pg_array_types[oid]
                except KeyError:
                    raise ArrayContentNotSupportedError(
                        "oid " + str(oid) + " not supported as array contents")
                except NotSupportedError:
                    raise ArrayContentNotSupportedError(
                        "type " + str(typ) +
                        " not supported as array contents")
        if fc == FC_BINARY:
            def send_array_binary(arr: list[Any]) -> bytearray:
                array_check_dimensions(arr)

                has_null = array_has_null(arr)
                dim_lengths = array_dim_lengths(arr)
                data = bytearray(iii_pack(len(dim_lengths), has_null, oid))
                for i in dim_lengths:
                    data.extend(ii_pack(i, 1))
                for v in array_flatten(arr):
                    if v is None:
                        data += i_pack(-1)
                    elif isinstance(v, typ):
                        inner_data = send_func(v)
                        data += i_pack(len(inner_data))
                        data += inner_data
                    else:
                        raise ArrayContentNotHomogenousError(
                            "not all array elements are of type " + str(typ))
                return data
        else:
            def send_array_text(arr: list[Any]) -> bytes:
                array_check_dimensions(arr)
                ar = deepcopy(arr)
                for a, i, v in walk_array(ar):
                    if v is None:
                        a[i] = 'NULL'
                    elif isinstance(v, typ):
                        a[i] = send_func(v).decode('ascii')
                    else:
                        raise ArrayContentNotHomogenousError(
                            "not all array elements are of type " + str(typ))
                return str(ar).translate(arr_trans).encode('ascii')

        return (array_oid, fc, send_array_binary if fc == FC_BINARY else send_array_text)


__all__ = [
    "Connection",
    "Warning", "Error", "InterfaceError", "ConnectionClosedError",
    "DatabaseError", "DataError", "OperationalError", "IntegrityError",
    "InternalError", "ProgrammingError", "NotSupportedError",
    "ArrayContentNotSupportedError", "ArrayContentNotHomogenousError",
    "ArrayDimensionsNotConsistentError",
    "BINARY", "Binary", "Date", "Time", "Timestamp",
    "DateFromTicks", "TimeFromTicks", "TimestampFromTicks",
    "Interval", "LogOptions",
    "PGType", "PGEnum", "PGJson", "PGJsonb", "PGText", "PGTsvector",
    "PGVarchar",
    "Cursor",
    "load_data",
]
