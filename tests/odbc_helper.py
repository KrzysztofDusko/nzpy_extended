"""
odbc_helper.py — Minimal ODBC helper using SQLConnectA (ctypes).

On Linux, pyodbc uses SQLDriverConnectW which has a bug with the Netezza
ODBC driver (broken Unicode negotiation).  This module calls SQLConnectA
directly via ctypes — the same path that ``isql -v DSN UID PWD`` uses.

Why SQLConnect works
--------------------
``isql -v NetezzaSQL admin password`` succeeds because it calls
**SQLConnect** (which accepts DSN / UID / PWD as separate parameters),
while ``pyodbc.connect(…)`` calls **SQLDriverConnectW** with an inline
connection string.  The Netezza driver's SQLDriverConnectW implementation
is broken on Linux and garbles the connection-string parameters, but
SQLConnectA works correctly.

Usage
-----
    from odbc_helper import connect

    conn = connect(dsn="NetezzaSQL", user="admin", password="password")
    cur = conn.cursor()
    cur.execute("SELECT 1")
    rows = cur.fetchall()
"""

import ctypes
import ctypes.util
import datetime
import re
from decimal import Decimal

SQL_HANDLE_ENV = 1
SQL_HANDLE_DBC = 2
SQL_HANDLE_STMT = 3

SQL_SUCCESS = 0
SQL_SUCCESS_WITH_INFO = 1
SQL_NO_DATA = 100
SQL_NULL_DATA = -1

SQL_C_CHAR = 1

# ODBC SQL type constants
SQL_CHAR = 1
SQL_NUMERIC = 2
SQL_DECIMAL = 3
SQL_INTEGER = 4
SQL_SMALLINT = 5
SQL_FLOAT = 6
SQL_REAL = 7
SQL_DOUBLE = 8
SQL_VARCHAR = 12
SQL_TYPE_DATE = 91
SQL_TYPE_TIME = 92
SQL_TYPE_TIMESTAMP = 93
SQL_BOOLEAN = 16
SQL_BIGINT = -5
SQL_TINYINT = -6
SQL_BIT = -7
SQL_WCHAR = -8
SQL_WVARCHAR = -9
SQL_WLONGVARCHAR = -10
SQL_GUID = -11

_lib = None


def _get_lib():
    global _lib
    if _lib is None:
        path = ctypes.util.find_library("odbc")
        if not path:
            raise RuntimeError("unixODBC library not found")
        _lib = ctypes.cdll.LoadLibrary(path)
        _lib.SQLGetDiagRecA.argtypes = [
            ctypes.c_short,
            ctypes.c_void_p,
            ctypes.c_short,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_char_p,
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_short),
        ]
        _lib.SQLGetDiagRecA.restype = ctypes.c_short
    return _lib


def _check(ret, handle, handle_type, msg=""):
    """Raise RuntimeError if ret is not success."""
    if ret in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
        return
    if ret == SQL_NO_DATA:
        return
    lib = _get_lib()
    state = ctypes.create_string_buffer(6)
    native = ctypes.c_int()
    msg_buf = ctypes.create_string_buffer(2048)
    lib.SQLGetDiagRecA(
        handle_type,
        handle,
        1,
        state,
        ctypes.byref(native),
        msg_buf,
        ctypes.c_int(2048),
        None,
    )
    raise RuntimeError(
        f"ODBC error [{state.value.decode('ascii', errors='replace')}] "
        f"{msg_buf.value.decode('ascii', errors='replace')}  {msg}"
    )


# ---------------------------------------------------------------------------
# Column type → Python converter
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})(\.\d+)?$")
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[\sT](\d{2}):(\d{2}):(\d{2})(\.\d+)?$"
)


def _make_date(raw: str):
    m = _DATE_RE.match(raw)
    if m:
        return datetime.date(int(m[1]), int(m[2]), int(m[3]))
    return raw


def _make_time(raw: str):
    m = _TIME_RE.match(raw)
    if m:
        hour, minute, second = int(m[1]), int(m[2]), int(m[3])
        frac = m[4]
        microsecond = 0
        if frac:
            frac_str = frac[1:]  # strip leading '.'
            frac_str = frac_str.ljust(6, "0")[:6]
            microsecond = int(frac_str)
        return datetime.time(hour, minute, second, microsecond)
    return raw


def _make_timestamp(raw: str):
    m = _TS_RE.match(raw)
    if m:
        parts = [int(m[i]) for i in range(1, 7)]
        frac = m[7]
        microsecond = 0
        if frac:
            frac_str = frac[1:]
            frac_str = frac_str.ljust(6, "0")[:6]
            microsecond = int(frac_str)
        return datetime.datetime(*parts, microsecond)
    return raw


def _convert_val(raw: str, sql_type: int):
    if raw is None:
        return None
    raw = raw.strip()

    if sql_type in (SQL_BOOLEAN, SQL_BIT):
        if raw in ("t", "true", "1"):
            return True
        if raw in ("f", "false", "0"):
            return False
        return raw

    if sql_type in (SQL_INTEGER, SQL_SMALLINT, SQL_TINYINT, SQL_BIGINT):
        try:
            return int(raw)
        except ValueError:
            return raw

    if sql_type in (SQL_FLOAT, SQL_REAL, SQL_DOUBLE, SQL_NUMERIC, SQL_DECIMAL):
        try:
            return Decimal(raw)
        except Exception:
            return raw

    if sql_type == SQL_TYPE_DATE:
        return _make_date(raw)

    if sql_type == SQL_TYPE_TIME:
        return _make_time(raw)

    if sql_type == SQL_TYPE_TIMESTAMP:
        return _make_timestamp(raw)

    # CHAR / VARCHAR / NCHAR / NVARCHAR → str
    return raw


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

class OdbcCursor:
    def __init__(self, hstmt):
        self._hstmt = hstmt
        self._ncols = 0
        self._col_types = []
        self._col_names = []
        self._rows = []
        self._row_index = 0

    @property
    def description(self):
        return [(n,) for n in self._col_names]

    def execute(self, sql):
        lib = _get_lib()
        hstmt = self._hstmt

        sql_bytes = sql.encode("utf-8") if isinstance(sql, str) else sql
        ret = lib.SQLExecDirect(hstmt, sql_bytes, ctypes.c_int(len(sql_bytes)))
        if ret not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            self._rows = []
            self._ncols = 0
            _check(ret, hstmt, SQL_HANDLE_STMT, f"execute: {sql[:100]}")
            return

        ncols = ctypes.c_short()
        lib.SQLNumResultCols(hstmt, ctypes.byref(ncols))
        self._ncols = ncols.value
        self._col_types = []
        self._col_names = []

        for i in range(1, self._ncols + 1):
            name_buf = ctypes.create_string_buffer(256)
            name_len = ctypes.c_short()
            data_type = ctypes.c_short()
            lib.SQLDescribeColA(
                hstmt,
                ctypes.c_short(i),
                name_buf,
                ctypes.c_short(256),
                ctypes.byref(name_len),
                ctypes.byref(data_type),
                None, None, None,
            )
            self._col_names.append(
                name_buf.value.decode("utf-8", errors="replace")
            )
            self._col_types.append(data_type.value)

        self._rows = []
        while True:
            ret = lib.SQLFetch(hstmt)
            if ret == SQL_NO_DATA:
                break
            if ret not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                continue
            row = []
            for i in range(1, self._ncols + 1):
                buf = ctypes.create_string_buffer(4096)
                indicator = ctypes.c_int()
                ret = lib.SQLGetData(
                    hstmt,
                    ctypes.c_ushort(i),
                    ctypes.c_short(SQL_C_CHAR),
                    buf,
                    ctypes.c_ulong(4096),
                    ctypes.byref(indicator),
                )
                if indicator.value == SQL_NULL_DATA:
                    row.append(None)
                else:
                    raw = buf.value.decode("utf-8", errors="replace")
                    row.append(_convert_val(raw, self._col_types[i - 1]))
            self._rows.append(tuple(row))
        self._row_index = 0

    def fetchall(self):
        if self._rows is None:
            return []
        return self._rows

    def fetchmany(self, size=None):
        if self._rows is None:
            return []
        if size is None:
            return self._rows[self._row_index:]
        result = self._rows[self._row_index: self._row_index + size]
        self._row_index += len(result)
        return result

    def fetchone(self):
        if self._rows is None or self._row_index >= len(self._rows):
            return None
        row = self._rows[self._row_index]
        self._row_index += 1
        return row

    def close(self):
        lib = _get_lib()
        lib.SQLFreeHandle(SQL_HANDLE_STMT, self._hstmt)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class OdbcConnection:
    def __init__(self, hdbc):
        self._hdbc = hdbc

    def cursor(self):
        lib = _get_lib()
        hstmt = ctypes.c_void_p()
        ret = lib.SQLAllocHandle(SQL_HANDLE_STMT, self._hdbc, ctypes.byref(hstmt))
        _check(ret, self._hdbc, SQL_HANDLE_DBC, "allocate stmt")
        return OdbcCursor(hstmt)

    def close(self):
        lib = _get_lib()
        lib.SQLDisconnect(self._hdbc)
        lib.SQLFreeHandle(SQL_HANDLE_DBC, self._hdbc)


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

def connect(dsn="NetezzaSQL", user="admin", password="password"):
    """Connect using SQLConnectA (works around pyodbc's SQLDriverConnectW bug)."""
    lib = _get_lib()

    henv = ctypes.c_void_p()
    ret = lib.SQLAllocHandle(SQL_HANDLE_ENV, None, ctypes.byref(henv))
    _check(ret, None, SQL_HANDLE_ENV, "allocate env")

    ret = lib.SQLSetEnvAttr(
        henv, 200, ctypes.c_void_p(3), 0
    )
    _check(ret, henv, SQL_HANDLE_ENV, "set env attr")

    hdbc = ctypes.c_void_p()
    ret = lib.SQLAllocHandle(SQL_HANDLE_DBC, henv, ctypes.byref(hdbc))
    _check(ret, henv, SQL_HANDLE_ENV, "allocate dbc")

    dsn_b = dsn.encode("utf-8") if isinstance(dsn, str) else dsn
    uid_b = user.encode("utf-8") if isinstance(user, str) else user
    pwd_b = password.encode("utf-8") if isinstance(password, str) else password

    lib.SQLConnectA.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_short,
        ctypes.c_char_p,
        ctypes.c_short,
        ctypes.c_char_p,
        ctypes.c_short,
    ]
    lib.SQLConnectA.restype = ctypes.c_short

    ret = lib.SQLConnectA(
        hdbc,
        dsn_b,
        ctypes.c_short(len(dsn_b)),
        uid_b,
        ctypes.c_short(len(uid_b)),
        pwd_b,
        ctypes.c_short(len(pwd_b)),
    )
    _check(ret, hdbc, SQL_HANDLE_DBC, "connect")

    conn = OdbcConnection(hdbc)
    conn._henv = henv
    return conn
