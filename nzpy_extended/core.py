import os
import stat
import datetime
import enum
import getpass
import logging
import logging.handlers
import platform
import socket
import asyncio
import struct
from calendar import timegm
from collections import defaultdict, deque
from copy import deepcopy
from datetime import (date, datetime as Datetime,
                      time, timedelta as Timedelta)
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
from uuid import UUID
from warnings import warn

import nzpy_extended

from . import handshake
from .buffered_stream import NzBufferedStream

_FORCE_PURE_PYTHON = os.environ.get("NZPY_EXTENDED_NO_CEXT", "").lower() in ("1", "true", "yes")

if _FORCE_PURE_PYTHON:
    _HAVE_C_EXT = False
    _c_ext = None
else:
    try:
        from . import c_ext as _c_ext
        _HAVE_C_EXT = True
    except ImportError:
        _HAVE_C_EXT = False
        _c_ext = None

# Copyright (c) 2007-2009, Mathieu Fenniak
# Copyright (c) The Contributors
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
# * The name of the author may not be used to endorse or promote products
# derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

__author__ = "Mathieu Fenniak"

ZERO = Timedelta(0)
BINARY = bytes


class LogOptions(enum.IntFlag):
    Disabled = 0
    Inherit = enum.auto()  # inherit the logging settings from the caller
    Logfile = enum.auto()  # add


class Interval():
    """An Interval represents a measurement of time.  In PostgreSQL, an
    interval is defined in the measure of months, days, and microseconds; as
    such, the nzpy_extended interval type represents the same information.
    Note that values of the :attr:`microseconds`, :attr:`days` and
    :attr:`months` properties are independently measured and cannot be
    converted to each other.  A month may be 28, 29, 30, or 31 days, and a day
    may occasionally be lengthened slightly by a leap second.
    .. attribute:: microseconds
        Measure of microseconds in the interval.
        The microseconds value is constrained to fit into a signed 64-bit
        integer.  Any attempt to set a value too large or too small will result
        in an OverflowError being raised.
    .. attribute:: days
        Measure of days in the interval.
        The days value is constrained to fit into a signed 32-bit integer.
        Any attempt to set a value too large or too small will result in an
        OverflowError being raised.
    .. attribute:: months
        Measure of months in the interval.
        The months value is constrained to fit into a signed 32-bit integer.
        Any attempt to set a value too large or too small will result in an
        OverflowError being raised.
    """

    def __init__(self, microseconds=0, days=0, months=0):
        self.microseconds = microseconds
        self.days = days
        self.months = months

    def _setMicroseconds(self, value):
        if not isinstance(value, int):
            raise TypeError("microseconds must be an integer type")
        elif not (min_int8 < value < max_int8):
            raise OverflowError(
                "microseconds must be representable as a 64-bit integer")
        else:
            self._microseconds = value

    def _setDays(self, value):
        if not isinstance(value, int):
            raise TypeError("days must be an integer type")
        elif not (min_int4 < value < max_int4):
            raise OverflowError(
                "days must be representable as a 32-bit integer")
        else:
            self._days = value

    def _setMonths(self, value):
        if not isinstance(value, int):
            raise TypeError("months must be an integer type")
        elif not (min_int4 < value < max_int4):
            raise OverflowError(
                "months must be representable as a 32-bit integer")
        else:
            self._months = value

    microseconds = property(lambda self: self._microseconds, _setMicroseconds)
    days = property(lambda self: self._days, _setDays)
    months = property(lambda self: self._months, _setMonths)

    def __repr__(self):
        return "<Interval %s months %s days %s microseconds>" % (
            self.months, self.days, self.microseconds)

    def __eq__(self, other):
        return other is not None and isinstance(other, Interval) and \
               self.months == other.months and self.days == other.days and \
               self.microseconds == other.microseconds

    def __neq__(self, other):
        return not self.__eq__(other)


class PGType():
    def __init__(self, value):
        self.value = value

    def encode(self, encoding):
        return str(self.value).encode(encoding)


class PGEnum(PGType):
    def __init__(self, value):
        if isinstance(value, str):
            self.value = value
        else:
            self.value = value.value


class PGJson(PGType):
    def encode(self, encoding):
        return dumps(self.value).encode(encoding)


class PGJsonb(PGType):
    def encode(self, encoding):
        return dumps(self.value).encode(encoding)


class PGTsvector(PGType):
    pass


class PGVarchar(str):
    pass


class PGText(str):
    pass


def pack_funcs(fmt):
    struc = Struct('!' + fmt)
    return struc.pack, struc.unpack_from


i_pack, i_unpack = pack_funcs('i')
h_pack, h_unpack = pack_funcs('h')
q_pack, q_unpack = pack_funcs('q')
d_pack, d_unpack = pack_funcs('d')
f_pack, f_unpack = pack_funcs('f')
iii_pack, iii_unpack = pack_funcs('iii')
ii_pack, ii_unpack = pack_funcs('ii')
qii_pack, qii_unpack = pack_funcs('qii')
dii_pack, dii_unpack = pack_funcs('dii')
ihic_pack, ihic_unpack = pack_funcs('ihic')
ci_pack, ci_unpack = pack_funcs('ci')
c_pack, c_unpack = pack_funcs('c')
bh_pack, bh_unpack = pack_funcs('bh')
cccc_pack, cccc_unpack = pack_funcs('cccc')
h_le_unpack = Struct('<H').unpack_from
i_le_unpack = Struct('<i').unpack_from
q_le_unpack = Struct('<q').unpack_from
J2000_OFFSET = 2451545

min_int2, max_int2 = -2 ** 15, 2 ** 15
min_int4, max_int4 = -2 ** 31, 2 ** 31
min_int8, max_int8 = -2 ** 63, 2 ** 63


class Warning(Exception):
    """Generic exception raised for important database warnings like data
    truncations.  This exception is not currently used by nzpy_extended.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class Error(Exception):
    """Generic exception that is the base exception of all other error
    exceptions.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class InterfaceError(Error):
    """Generic exception raised for errors that are related to the database
    interface rather than the database itself.  For example, if the interface
    attempts to use an SSL connection but the server refuses, an InterfaceError
    will be raised.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class ConnectionClosedError(InterfaceError):
    """An interface error, which identifies error occurring due tothe underlying
    connection being already closed"""

    def __init__(self, msg=None):
        super().__init__(msg if msg is not None else "connection is closed")


class DatabaseError(Error):
    """Generic exception raised for errors that are related to the database.
    This exception is currently never raised by nzpy_extended.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class DataError(DatabaseError):
    """Generic exception raised for errors that are due to problems with the
    processed data.  This exception is not currently raised by nzpy_extended.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class OperationalError(DatabaseError):
    """
    Generic exception raised for errors that are related to the database's
    operation and not necessarily under the control of the programmer. This
    exception is currently never raised by nzpy_extended.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class IntegrityError(DatabaseError):
    """
    Generic exception raised when the relational integrity of the database is
    affected.  This exception is not currently raised by nzpy_extended.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class InternalError(DatabaseError):
    """Generic exception raised when the database encounters an internal error.
    This is currently only raised when unexpected state occurs in the nzpy_extended
    interface itself, and is typically the result of a interface bug.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class ProgrammingError(DatabaseError):
    """Generic exception raised for programming errors.  For example, this
    exception is raised if more parameter fields are in a query string than
    there are available parameters.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class NotSupportedError(DatabaseError):
    """Generic exception raised in case a method or database API was used which
    is not supported by the database.
    This exception is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    pass


class ArrayContentNotSupportedError(NotSupportedError):
    """
    Raised when attempting to transmit an array where the base type is not
    supported for binary data transfer by the interface.
    """
    pass


class ArrayContentNotHomogenousError(ProgrammingError):
    """
    Raised when attempting to transmit an array that doesn't contain only a
    single type of object.
    """
    pass


class ArrayDimensionsNotConsistentError(ProgrammingError):
    """
    Raised when attempting to transmit an array that has inconsistent
    multi-dimension sizes.
    """
    pass


def Date(year, month, day):
    """Constuct an object holding a date value.
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    :rtype: :class:`datetime.date`
    """
    return date(year, month, day)


def Time(hour, minute, second):
    """Construct an object holding a time value.
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    :rtype: :class:`datetime.time`
    """
    return time(hour, minute, second)


def Timestamp(year, month, day, hour, minute, second):
    """Construct an object holding a timestamp value.
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    :rtype: :class:`datetime.datetime`
    """
    return Datetime(year, month, day, hour, minute, second)


def DateFromTicks(ticks):
    """Construct an object holding a date value from the given ticks value
    (number of seconds since the epoch).
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    :rtype: :class:`datetime.date`
    """
    return Date(*localtime(ticks)[:3])


def TimeFromTicks(ticks):
    """Construct an objet holding a time value from the given ticks value
    (number of seconds since the epoch).
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    :rtype: :class:`datetime.time`
    """
    return Time(*localtime(ticks)[3:6])


def TimestampFromTicks(ticks):
    """Construct an object holding a timestamp value from the given ticks value
    (number of seconds since the epoch).
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    :rtype: :class:`datetime.datetime`
    """
    return Timestamp(*localtime(ticks)[:6])


def Binary(value):
    """Construct an object holding binary data.
    This function is part of the `DBAPI 2.0 specification
    <http://www.python.org/dev/peps/pep-0249/>`_.
    """
    return value


FC_TEXT = 0
FC_BINARY = 1


def convert_paramstyle(style, query):
    # I don't see any way to avoid scanning the query string char by char,
    # so we might as well take that careful approach and create a
    # state-based scanner.  We'll use int variables for the state.
    OUTSIDE = 0  # outside quoted string
    INSIDE_SQ = 1  # inside single-quote string '...'
    INSIDE_QI = 2  # inside quoted identifier   "..."
    INSIDE_ES = 3  # inside escaped single-quote string, E'...'
    INSIDE_PN = 4  # inside parameter name eg. :name
    INSIDE_CO = 5  # inside inline comment eg. --

    in_quote_escape = False
    in_param_escape = False
    placeholders = []
    output_query = []
    param_idx = map(lambda x: "$" + str(x), count(1))
    state = OUTSIDE
    prev_c = None
    for i, c in enumerate(query):
        if i + 1 < len(query):
            next_c = query[i + 1]
        else:
            next_c = None

        if state == OUTSIDE:
            if c == "'":
                output_query.append(c)
                if prev_c == 'E':
                    state = INSIDE_ES
                else:
                    state = INSIDE_SQ
            elif c == '"':
                output_query.append(c)
                state = INSIDE_QI
            elif c == '-':
                output_query.append(c)
                if prev_c == '-':
                    state = INSIDE_CO
            elif style == "qmark" and c == "?":
                output_query.append("NULL")
            elif style == "numeric" and c == ":" and next_c is not None and next_c not in (':', '=') \
                    and prev_c != ':':
                # Treat : as beginning of parameter name if and only
                # if it's the only : around
                # Needed to properly process type conversions
                # i.e. sum(x)::float
                output_query.append("$")
            elif style == "named" and c == ":" and next_c is not None and next_c not in (':', '=') \
                    and prev_c != ':':
                # Same logic for : as in numeric parameters
                state = INSIDE_PN
                placeholders.append('')
            elif style == "pyformat" and c == '%' and next_c == "(":
                state = INSIDE_PN
                placeholders.append('')
            elif style in ("format", "pyformat") and c == "%":
                style = "format"
                if in_param_escape:
                    in_param_escape = False
                    output_query.append(c)
                else:
                    if next_c == "%":
                        in_param_escape = True
                    elif next_c == "s":
                        state = INSIDE_PN
                        output_query.append(next(param_idx))
                    else:
                        raise InterfaceError(
                            "Only %s and %% are supported in the query.")
            else:
                output_query.append(c)

        elif state == INSIDE_SQ:
            if c == "'":
                if in_quote_escape:
                    in_quote_escape = False
                else:
                    if next_c == "'":
                        in_quote_escape = True
                    else:
                        state = OUTSIDE
            output_query.append(c)

        elif state == INSIDE_QI:
            if c == '"':
                state = OUTSIDE
            output_query.append(c)

        elif state == INSIDE_ES:
            if c == "'" and prev_c != "\\":
                # check for escaped single-quote
                state = OUTSIDE
            output_query.append(c)

        elif state == INSIDE_PN:
            if style == 'named':
                placeholders[-1] += c
                if next_c is None or (not next_c.isalnum() and next_c != '_'):
                    state = OUTSIDE
                    try:
                        pidx = placeholders.index(placeholders[-1], 0, -1)
                        output_query.append("$" + str(pidx + 1))
                        del placeholders[-1]
                    except ValueError:
                        output_query.append("$" + str(len(placeholders)))
            elif style == 'pyformat':
                if prev_c == ')' and c == "s":
                    state = OUTSIDE
                    try:
                        pidx = placeholders.index(placeholders[-1], 0, -1)
                        output_query.append("$" + str(pidx + 1))
                        del placeholders[-1]
                    except ValueError:
                        output_query.append("$" + str(len(placeholders)))
                elif c in "()":
                    pass
                else:
                    placeholders[-1] += c
            elif style == 'format':
                state = OUTSIDE

        elif state == INSIDE_CO:
            output_query.append(c)
            if c == '\n':
                state = OUTSIDE

        prev_c = c

    def make_args(vals):
        return vals

    return ''.join(output_query), make_args


EPOCH = Datetime(2000, 1, 1)
EPOCH_TZ = EPOCH.replace(tzinfo=Timezone.utc)
EPOCH_SECONDS = timegm(EPOCH.timetuple())
INFINITY_MICROSECONDS = 2 ** 63 - 1
MINUS_INFINITY_MICROSECONDS = -1 * INFINITY_MICROSECONDS - 1


# data is 64-bit integer representing microseconds since 2000-01-01
def timestamp_recv_integer(data, offset, length):
    micros = q_unpack(data, offset)[0]
    try:
        return EPOCH + Timedelta(microseconds=micros)
    except OverflowError:
        if micros == INFINITY_MICROSECONDS:
            return 'infinity'
        elif micros == MINUS_INFINITY_MICROSECONDS:
            return '-infinity'
        else:
            return micros


# data is double-precision float representing seconds since 2000-01-01
def timestamp_recv_float(data, offset, length):
    return Datetime.utcfromtimestamp(EPOCH_SECONDS + d_unpack(data, offset)[0])


# data is 64-bit integer representing microseconds since 2000-01-01
def timestamp_send_integer(v):
    return q_pack(
        int((timegm(v.timetuple()) - EPOCH_SECONDS) * 1e6) + v.microsecond)


# data is double-precision float representing seconds since 2000-01-01
def timestamp_send_float(v):
    return d_pack(timegm(v.timetuple()) + v.microsecond / 1e6 - EPOCH_SECONDS)


def timestamptz_send_integer(v):
    # timestamps should be sent as UTC.  If they have zone info,
    # convert them.
    return timestamp_send_integer(
        v.astimezone(Timezone.utc).replace(tzinfo=None))


def timestamptz_send_float(v):
    # timestamps should be sent as UTC.  If they have zone info,
    # convert them.
    return timestamp_send_float(
        v.astimezone(Timezone.utc).replace(tzinfo=None))


# return a timezone-aware datetime instance if we're reading from a
# "timestamp with timezone" type.  The timezone returned will always be
# UTC, but providing that additional information can permit conversion
# to local.
def timestamptz_recv_integer(data, offset, length):
    return (data[offset:offset + length]).decode("utf-8")


def timestamptz_recv_float(data, offset, length):
    return (data[offset:offset + length]).decode("utf-8")


def interval_send_integer(v):
    microseconds = v.microseconds
    try:
        microseconds += int(v.seconds * 1e6)
    except AttributeError:
        pass

    try:
        months = v.months
    except AttributeError:
        months = 0

    return qii_pack(microseconds, v.days, months)


def interval_send_float(v):
    seconds = v.microseconds / 1000.0 / 1000.0
    try:
        seconds += v.seconds
    except AttributeError:
        pass

    try:
        months = v.months
    except AttributeError:
        months = 0

    return dii_pack(seconds, v.days, months)


def interval_recv_integer(data, offset, length):
    return _parse_interval_text(data[offset:offset + length].decode("utf-8"))


def interval_recv_float(data, offset, length):
    return _parse_interval_text(data[offset:offset + length].decode("utf-8"))


def _parse_interval_text(s):
    months = 0
    days = 0
    microseconds = 0

    s = s.strip()
    import re
    normalized = re.sub(r'([+-])\s+(\d)', r'\1\2', s)
    parts = re.split(r'\s+', normalized)

    i = 0
    while i < len(parts):
        tok = parts[i]

        time_match = re.match(r'^([+-]?)(\d+):(\d+):(\d+(?:\.\d+)?)$', tok)
        if time_match:
            neg = time_match.group(1) == '-'
            h = int(time_match.group(2))
            m = int(time_match.group(3))
            sec = float(time_match.group(4))
            us = h * 3600000000 + m * 60000000 + int(sec * 1000000)
            if neg:
                us = -us
            microseconds += us
            i += 1
            continue

        try:
            val = int(tok)
        except ValueError:
            i += 1
            continue

        if i + 1 < len(parts):
            unit = parts[i + 1]
            if unit.startswith('year'):
                months += val * 12
                i += 2
                continue
            elif unit.startswith('mon'):
                months += val
                i += 2
                continue
            elif unit.startswith('day'):
                days += val
                i += 2
                continue

        i += 1

    return Interval(microseconds=microseconds, days=days, months=months)


def int8_recv(data, offset, length):
    return int(data[offset:offset + length])


def int2_recv(data, offset, length):
    return int(data[offset:offset + length])


def int4_recv(data, offset, length):
    return int(data[offset:offset + length])


def float4_recv(data, offset, length):
    return float(data[offset:offset + length])


def float8_recv(data, offset, length):
    return float(data[offset:offset + length])


def bytea_send(v):
    return v


# bytea
def bytea_recv(data, offset, length):
    return data[offset:offset + length]


def uuid_send(v):
    return v.bytes


def uuid_recv(data, offset, length):
    return UUID(bytes=data[offset:offset + length])


def bool_send(v):
    return b"\x01" if v else b"\x00"


NULL = i_pack(-1)

NULL_BYTE = b'\x00'


def null_send(v):
    return NULL


def int_in(data, offset, length):
    return int(data[offset: offset + length])


def timestamp_in(data, offset, length):
    s = data[offset:offset + length].decode('utf-8')
    try:
        if ' ' in s:
            parts = s.split('.')
            date_time_parts = parts[0]
            microseconds = int(parts[1][:6].ljust(6, '0')) if len(parts) > 1 else 0
            dt_parts = date_time_parts.replace('-', ' ').replace(':', ' ').split()
            return Datetime(int(dt_parts[0]), int(dt_parts[1]), int(dt_parts[2]),
                          int(dt_parts[3]), int(dt_parts[4]), int(dt_parts[5]), microseconds)
        return Datetime(int(s[:4]), int(s[5:7]), int(s[8:10]), 0, 0, 0)
    except (ValueError, IndexError):
        return s


def timestamptz_in(data, offset, length):
    s = data[offset:offset + length].decode('utf-8')
    try:
        if ' ' in s:
            parts = s.split('.')
            base = parts[0]
            microseconds = int(parts[1][:6].ljust(6, '0')) if len(parts) > 1 else 0
            # Strip timezone suffix (e.g., +00:00, -05, UTC)
            dt_str = base
            plus_idx = base.find('+', 10)
            minus_idx = base.find('-', 10)
            tz_idx = None
            if plus_idx >= 0:
                tz_idx = plus_idx
            elif minus_idx >= 0:
                tz_idx = minus_idx
            if tz_idx is not None:
                dt_str = base[:tz_idx]
            elif base.endswith(' UTC'):
                dt_str = base[:-4]
            elif base.endswith(' utc'):
                dt_str = base[:-4]
            dt_parts = dt_str.replace('-', ' ').replace(':', ' ').split()
            return Datetime(int(dt_parts[0]), int(dt_parts[1]), int(dt_parts[2]),
                          int(dt_parts[3]), int(dt_parts[4]), int(dt_parts[5]), microseconds)
        return Datetime(int(s[:4]), int(s[5:7]), int(s[8:10]), 0, 0, 0)
    except (ValueError, IndexError):
        return s


class Cursor():
    """A cursor object is returned by the :meth:`~Connection.cursor` method of
    a connection. It has the following attributes and methods:
    .. attribute:: arraysize
        This read/write attribute specifies the number of rows to fetch at a
        time with :meth:`fetchmany`.  It defaults to 1.
    .. attribute:: connection
        This read-only attribute contains a reference to the connection object
        (an instance of :class:`Connection`) on which the cursor was
        created.
        This attribute is part of a DBAPI 2.0 extension.  Accessing this
        attribute will generate the following warning: ``DB-API extension
        cursor.connection used``.
    .. attribute:: rowcount
        This read-only attribute contains the number of rows that the last
        ``execute()`` or ``executemany()`` method produced (for query
        statements like ``SELECT``) or affected (for modification statements
        like ``UPDATE``).
        The value is -1 if:
        - No ``execute()`` or ``executemany()`` method has been performed yet
          on the cursor.
        - There was no rowcount associated with the last ``execute()``.
        - At least one of the statements executed as part of an
          ``executemany()`` had no row count associated with it.
        - Using a ``SELECT`` query statement on PostgreSQL server older than
          version 9.
        - Using a ``COPY`` query statement on PostgreSQL server version 8.1 or
          older.
        This attribute is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
    .. attribute:: description
        This read-only attribute is a sequence of 7-item sequences.  Each value
        contains information describing one result column.  The 7 items
        returned for each column are (name, type_code, display_size,
        internal_size, precision, scale, null_ok).  Only the first two values
        are provided by the current implementation.
        This attribute is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
    """

    def __init__(self, connection):
        self._c = connection
        self.arraysize = 1
        self.ps = None
        self._row_count = -1
        self._cached_rows = deque()
        self.notices = deque()
        self._generator = None
        self._has_rows = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    @property
    def connection(self):
        warn("DB-API extension cursor.connection used", stacklevel=3)
        return self._c

    @property
    def rowcount(self):
        return self._row_count

    description = property(lambda self: self._getDescription())

    @property
    def has_rows(self):
        """Whether the current result set has at least one row (Node/C# HasRows parity)."""
        return self._has_rows

    def _getDescription(self):
        if self.ps is None:
            return None
        row_desc = self.ps['row_desc']
        if len(row_desc) == 0:
            return None
        tupdesc = self.ps.get('tupdesc')
        columns = []
        for i, col in enumerate(row_desc):  # type: ignore
            meta = self._c._resolve_column_metadata(col, i, tupdesc) if self._c else None
            if meta is None:
                columns.append((col["name"].decode(), col["type_oid"],
                                None, None, None, None, None))
            else:
                columns.append((
                    meta['name'],
                    meta['provider_type'],
                    meta['display_size'],
                    meta['internal_size'],
                    meta['numeric_precision'] if meta['numeric_precision'] >= 0 else None,
                    meta['numeric_scale'] if meta['numeric_scale'] >= 0 else None,
                    meta['null_ok'],
                ))
        return tuple(columns)

    def get_schema_table(self):
        """Return column schema metadata (ADO.NET / Node getSchemaTable parity)."""
        if self.ps is None:
            return []
        row_desc = self.ps['row_desc']
        if len(row_desc) == 0:
            return []
        tupdesc = self.ps.get('tupdesc')
        rows = []
        for i, col in enumerate(row_desc):
            meta = self._c._resolve_column_metadata(col, i, tupdesc) if self._c else None
            if meta is None:
                continue
            rows.append({
                'ColumnName': meta['name'],
                'ColumnOrdinal': i + 1,
                'ColumnSize': meta['column_size'],
                'NumericPrecision': meta['numeric_precision'],
                'NumericScale': meta['numeric_scale'],
                'DataType': meta['data_type'],
                'ProviderType': meta['provider_type'],
                'AllowDBNull': meta['null_ok'],
                'IsReadOnly': True,
                'IsLong': meta['is_long'],
                'IsAutoIncrement': False,
            })
        return rows

    def get_column_metadata(self, index):
        """Per-column metadata (Node getColumnMetadata parity)."""
        if self.ps is None or index < 0 or index >= len(self.ps['row_desc']):
            raise ProgrammingError(f"Column ordinal {index} is out of range")
        col = self.ps['row_desc'][index]
        tupdesc = self.ps.get('tupdesc')
        if self._c is None:
            raise ProgrammingError("Cursor closed")
        return self._c._resolve_column_metadata(col, index, tupdesc)

    ##
    # Executes a database operation.  Parameters may be provided as a sequence
    # or mapping and will be bound to variables in the operation.
    # <p>
    # Stability: Part of the DBAPI 2.0 specification.
    async def execute(self, operation, args=None, stream=None, timeout=None):
        """Executes a database operation.  Parameters may be provided as a
        sequence, or as a mapping, depending upon the value of
        :data:`nzpy_extended.paramstyle`.
        This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        :param operation:
            The SQL statement to execute.
        :param args:
            If :data:`paramstyle` is ``qmark``, ``numeric``, or ``format``,
            this argument should be an array of parameters to bind into the
            statement.  If :data:`paramstyle` is ``named``, the argument should
            be a dict mapping of parameters.  If the :data:`paramstyle` is
            ``pyformat``, the argument value may be either an array or a
            mapping.
        :param stream: This is a nzpy_extended extension for use with the PostgreSQL
            `COPY
            <http://www.postgresql.org/docs/current/static/sql-copy.html>`_
            command. For a COPY FROM the parameter must be a readable file-like
            object, and for COPY TO it must be writable.
            .. versionadded:: 1.9.11
        :param timeout:
            Optional timeout in seconds for this specific command.
        """
        try:
            self.stream = stream
            self._timeout = timeout
            await self.clear()

            if self._c is not None and not self._c.in_transaction and not self._c.autocommit:
                await self._c.execute(self, "begin", None)
                self._c.in_transaction = True

            if self._c is not None:
                coro = self._c.execute(self, operation, args)
                if timeout is not None and timeout > 0:
                    try:
                        await asyncio.wait_for(coro, timeout=timeout)
                    except asyncio.TimeoutError:
                        await self._c.cancel()
                        raise OperationalError("Command execution timeout")
                else:
                    await coro

        except AttributeError as e:
            if self._c is None:
                raise InterfaceError("Cursor closed")
            elif self._c._sock is None:
                raise ConnectionClosedError()
            else:
                raise e
        return self

    async def executemany(self, operation, param_sets):
        """Prepare a database operation, and then execute it against all
        parameter sequences or mappings provided.
        This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        :param operation:
            The SQL statement to execute
        :param parameter_sets:
            A sequence of parameters to execute the statement with. The values
            in the sequence should be sequences or mappings of parameters, the
            same as the args argument of the :meth:`execute` method.
        """
        await self.clear()
        rowcounts = []
        for parameters in param_sets:
            await self.execute(operation, parameters)
            rowcounts.append(self._row_count)

        self._row_count = -1 if -1 in rowcounts else sum(rowcounts)
        return self

    async def fetchone(self):
        """Fetch the next row of a query result set.
        This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        :returns:
            A row as a sequence of field values, or ``None`` if no more rows
            are available.
        """
        try:
            return await self.__anext__()
        except StopAsyncIteration:
            return None
        except TypeError:
            raise ProgrammingError("attempting to use unexecuted cursor")
        except AttributeError:
            raise ProgrammingError("attempting to use unexecuted cursor")

    async def fetchmany(self, num=None):
        """Fetches the next set of rows of a query result.
        This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        :param size:
            The number of rows to fetch when called.  If not provided, the
            :attr:`arraysize` attribute value is used instead.
        :returns:
            A sequence, each entry of which is a sequence of field values
            making up a row.  If no more rows are available, an empty sequence
            will be returned.
        """
        try:
            rows = []
            for _ in range(self.arraysize if num is None else num):
                try:
                    rows.append(await self.__anext__())
                except StopAsyncIteration:
                    break
            return tuple(rows)
        except TypeError:
            raise ProgrammingError("attempting to use unexecuted cursor")

    async def fetchall(self):
        """Fetches all remaining rows of a query result.
        This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        :returns:
            A sequence, each entry of which is a sequence of field values
            making up a row.
        """
        try:
            generator = getattr(self, '_generator', None)
            if generator is None:
                if self.ps is None:
                    raise ProgrammingError("A query hasn't been issued.")
                elif len(self.ps['row_desc']) == 0:
                    raise ProgrammingError("no result set")
                return []
            rows = list(self._cached_rows)
            self._cached_rows.clear()
            async for state in generator:
                if state in ("DATA_ROW", "DATA_BATCH"):
                    rows.extend(self._cached_rows)
                    self._cached_rows.clear()
                elif state == "COMMAND_COMPLETE":
                    self._has_rows = len(rows) > 0
                    continue
                elif state in ("ROW_DESCRIPTION", "DESCRIPTION", "DBOS_COLUMN_DESCRIPTION"):
                    self._has_rows = (
                        len(self._cached_rows) > 0 or
                        (self.ps is not None and len(self.ps.get('row_desc', [])) > 0)
                    )
                    self._generator = generator
                    return rows
                elif state == "READY_FOR_QUERY":
                    self._generator = None
                    return rows
                elif state == "ERROR":
                    err = self._c.error if self._c is not None else None
                    if self._c is not None:
                        await self._c._drain_protocol_generator(generator)
                    self._generator = None
                    if err is not None:
                        raise ProgrammingError(err)
                    return rows
            self._generator = None
            return rows
        except TypeError:
            raise ProgrammingError("attempting to use unexecuted cursor")

    async def close(self):
        """Closes the cursor.
        This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        """
        generator = getattr(self, '_generator', None)
        if generator is not None:
            if self._c is not None:
                await self._c._drain_protocol_generator(generator)
            self._generator = None
        self._c = None

    def __aiter__(self):
        return self

    def setinputsizes(self, sizes):
        """This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_, however, it is not
        implemented by nzpy_extended.
        """
        pass

    def setoutputsize(self, size, column=None):
        """This method is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_, however, it is not
        implemented by nzpy_extended.
        """
        pass

    async def __anext__(self):
        if getattr(self, '_timeout', None) is not None and self._timeout > 0:
            try:
                return await asyncio.wait_for(self._anext_internal(), timeout=self._timeout)
            except asyncio.TimeoutError:
                if self._c is not None:
                    await self._c.cancel()
                raise OperationalError("Command fetch timeout")
        else:
            return await self._anext_internal()

    async def _anext_internal(self):
        try:
            return self._cached_rows.popleft()
        except IndexError:
            generator = getattr(self, '_generator', None)
            if generator is not None:
                while True:
                    try:
                        state = await generator.__anext__()
                    except StopAsyncIteration:
                        break
                    if state in ("DATA_ROW", "DATA_BATCH"):
                        if len(self._cached_rows) > 0:
                            return self._cached_rows.popleft()
                    elif state == "COMMAND_COMPLETE":
                        if not self._cached_rows:
                            raise StopAsyncIteration()
                        continue
                    elif state == "READY_FOR_QUERY":
                        self._generator = None
                        raise StopAsyncIteration()
                    elif state == "ERROR":
                        err = self._c.error if self._c is not None else None
                        if self._c is not None:
                            await self._c._drain_protocol_generator(generator)
                        self._generator = None
                        if err is not None:
                            raise ProgrammingError(err)
                        raise StopAsyncIteration()
                self._generator = None
                raise StopAsyncIteration()

            if self.ps is None:
                raise ProgrammingError("A query hasn't been issued.")
            elif len(self.ps['row_desc']) == 0:
                raise ProgrammingError("no result set")
            else:
                raise StopAsyncIteration()

    async def clear(self):
        generator = getattr(self, '_generator', None)
        if generator is not None:
            if self._c is not None:
                await self._c._drain_protocol_generator(generator)
            else:
                async for state in generator:
                    pass
            self._generator = None
            
        self.ps = None
        self._row_count = -1
        self._has_rows = False
        self._cached_rows.clear()

    async def nextset(self):
        """Advance to the next result set of a multi-statement query.

        Returns ``True`` if another result set is available, ``None`` if
        no more result sets remain (per DB-API 2.0).
        
        Remaining rows from the current result set are discarded.
        ``cursor.description`` is updated to reflect the new result set.
        """
        # Discard remaining rows from current result set
        self._cached_rows.clear()

        generator = getattr(self, '_generator', None)
        if generator is None:
            return None

        while True:
            try:
                state = await generator.__anext__()
            except StopAsyncIteration:
                self._generator = None
                return None

            if state in ("ROW_DESCRIPTION", "DESCRIPTION", "DBOS_COLUMN_DESCRIPTION"):
                self._has_rows = (
                    len(self._cached_rows) > 0 or
                    (self.ps is not None and len(self.ps.get('row_desc', [])) > 0)
                )
                return True
            elif state == "COMMAND_COMPLETE":
                # Non-row-returning statement consumed; continue
                continue
            elif state == "READY_FOR_QUERY":
                self._generator = None
                return None
            elif state == "ERROR":
                err = self._c.error if self._c is not None else None
                if self._c is not None:
                    await self._c._drain_protocol_generator(generator)
                self._generator = None
                if err is not None:
                    raise ProgrammingError(err)
                return None
            # DATA_ROW, DATA_BATCH — rows land in _cached_rows.
            # When fetchall() has consumed the ROW_DESCRIPTION for the next
            # result set, nextset() sees DATA_ROW directly.
            if state in ("DATA_ROW", "DATA_BATCH"):
                self._has_rows = len(self._cached_rows) > 0
                return True


# Message codes
NOTICE_RESPONSE = b"N"
AUTHENTICATION_REQUEST = b"R"
PARAMETER_STATUS = b"S"
BACKEND_KEY_DATA = b"K"
READY_FOR_QUERY = b"Z"
ROW_DESCRIPTION = b"T"
ERROR_RESPONSE = b"E"
DATA_ROW = b"D"
COMMAND_COMPLETE = b"C"
PARSE_COMPLETE = b"1"
BIND_COMPLETE = b"2"
CLOSE_COMPLETE = b"3"
PORTAL_SUSPENDED = b"s"
NO_DATA = b"n"
PARAMETER_DESCRIPTION = b"t"
NOTIFICATION_RESPONSE = b"A"
COPY_DONE = b"c"
COPY_DATA = b"d"
COPY_IN_RESPONSE = b"G"
COPY_OUT_RESPONSE = b"H"
EMPTY_QUERY_RESPONSE = b"I"

BIND = b"B"
PARSE = b"P"
EXECUTE = b"E"
FLUSH = b'H'
SYNC = b'S'
PASSWORD = b'p'
DESCRIBE = b'D'
TERMINATE = b'X'
CLOSE = b'C'


def create_message(code, data=b''):
    return code + i_pack(len(data) + 4) + data


FLUSH_MSG = create_message(FLUSH)
SYNC_MSG = create_message(SYNC)
TERMINATE_MSG = create_message(TERMINATE)
COPY_DONE_MSG = create_message(COPY_DONE)
EXECUTE_MSG = create_message(EXECUTE, NULL_BYTE + i_pack(0))

# DESCRIBE constants
STATEMENT = b'S'
PORTAL = b'P'

# ErrorResponse codes
RESPONSE_SEVERITY = "S"  # always present
RESPONSE_SEVERITY = "V"  # always present
RESPONSE_CODE = "C"  # always present
RESPONSE_MSG = "M"  # always present
RESPONSE_DETAIL = "D"
RESPONSE_HINT = "H"
RESPONSE_POSITION = "P"
RESPONSE__POSITION = "p"
RESPONSE__QUERY = "q"
RESPONSE_WHERE = "W"
RESPONSE_FILE = "F"
RESPONSE_LINE = "L"
RESPONSE_ROUTINE = "R"

IDLE = b"I"
IDLE_IN_TRANSACTION = b"T"
IDLE_IN_FAILED_TRANSACTION = b"E"

TYPE_MOD_OFFSET = 16

# PostgreSQL / Netezza type OIDs for schema metadata
_OID_BOOL = 16
_OID_BYTEINT = 2500
_OID_INT2 = 21
_OID_INT4 = 23
_OID_INT8 = 20
_OID_NUMERIC = 1700
_OID_FLOAT4 = 700
_OID_FLOAT8 = 701
_OID_BPCHAR = 1042
_OID_VARCHAR = 1043
_OID_TEXT = 25
_OID_DATE = 1082
_OID_TIME = 1083
_OID_TIMESTAMP = 1114
_OID_TIMESTAMPTZ = 1184
_OID_TIMETZ = 1266
_OID_NCHAR = 2522
_OID_NVARCHAR = 2530

_NZ_TYPE_NUMERIC = 7


class DbosTupleDesc():

    def __init__(self):
        self.version = None
        self.nullsAllowed = None
        self.sizeWord = None
        self.sizeWordSize = None
        self.numFixedFields = None
        self.numVaryingFields = None
        self.fixedFieldsSize = None
        self.maxRecordSize = None
        self.numFields = None
        self.field_type = []
        self.field_size = []
        self.field_trueSize = []
        self.field_offset = []
        self.field_physField = []
        self.field_logField = []
        self.field_nullAllowed = []
        self.field_fixedSize = []
        self.field_springField = []
        self.DateStyle = None
        self.EuroDates = None
        self.DBcharset = None
        self.EnableTime24 = None


# Connection status
CONN_NOT_CONNECTED = 0
CONN_CONNECTED = 1
CONN_EXECUTING = 2
CONN_FETCHING = 3
CONN_CANCELLED = 4

# External table stuff (copied from nde/client/exttable.h)

EXTAB_SOCK_DATA = 1  # block of records
EXTAB_SOCK_ERROR = 2  # error message
EXTAB_SOCK_DONE = 3  # normal wrap-up
EXTAB_SOCK_FLUSH = 4  # Flush the current buffer/data

# NZ datatype
NzTypeRecAddr = 1
NzTypeDouble = 2
NzTypeInt = 3
NzTypeFloat = 4
NzTypeMoney = 5
NzTypeDate = 6
NzTypeNumeric = 7
NzTypeTime = 8
NzTypeTimestamp = 9
NzTypeInterval = 10
NzTypeTimeTz = 11
NzTypeBool = 12
NzTypeInt1 = 13
NzTypeBinary = 14
NzTypeChar = 15
NzTypeVarChar = 16
NzDEPR_Text = 17
#  OBSOLETE 3.0: BLAST Era Large 'text' Object
NzTypeUnknown = 18
#  corresponds to PG UNKNOWNOID data type - an untyped string literal
NzTypeInt2 = 19
NzTypeInt8 = 20
NzTypeVarFixedChar = 21
NzTypeGeometry = 22
NzTypeVarBinary = 23
NzDEPR_Blob = 24
#  OBSOLETE 3.0: BLAST Era Large 'binary' Object
NzTypeNChar = 25
NzTypeNVarChar = 26
NzDEPR_NText = 27
#  OBSOLETE 3.0: BLAST Era Large 'nchar text' Object
#  skip 28
#  skip 29
NzTypeJson = 30
NzTypeJsonb = 31
NzTypeJsonpath = 32
NzTypeVector = 33
NzTypeLastEntry = 34
#  KEEP THIS ENTRY LAST - used internally to size an array

#  this is version of nzpy_extended driver
nzpy_extended_client_version = "Release 11.3.1.3"

dataType = {
    NzTypeChar: "NzTypeChar",
    NzTypeVarChar: "NzTypeVarChar",
    NzTypeVarFixedChar: "NzTypeVarFixedChar",
    NzTypeGeometry: "NzTypeGeometry",
    NzTypeVarBinary: "NzTypeVarBinary",
    NzTypeNChar: "NzTypeNChar",
    NzTypeNVarChar: "NzTypeNVarChar",
    NzTypeJson: "NzTypeJson",
    NzTypeJsonb: "NzTypeJsonb",
    NzTypeJsonpath: "NzTypeJsonpath",
    NzTypeVector: "NzTypeVector"

}

arr_trans = dict(zip(map(ord, "[] 'u"), list('{}') + [None] * 3))


class Connection():
    # DBAPI Extension: supply exceptions as attributes on the connection
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        try:
            await self.close()
        except ConnectionClosedError:
            pass

    def __del__(self):
        try:
            if hasattr(self, '_sock') and self._sock is not None:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.close())
                else:
                    loop.run_until_complete(self.close())
        except (ConnectionClosedError, RuntimeError):
            pass

    def _getError(self, error):
        warn(
            "DB-API extension connection.%s used" %
            error.__name__, stacklevel=3)
        return error

    def __init__(self):
        self._sock = None
        self._usock = None
        self._stream = None
        self.in_transaction = False
        self.error = None

    async def _connect(
            self, user, host, unix_sock, port, database, password, ssl,
            securityLevel, timeout, application_name,
            max_prepared_statements, datestyle, logLevel, tcp_keepalive,
            char_varchar_encoding, logOptions=LogOptions.Inherit,
            pgOptions=None):
        self._char_varchar_encoding = char_varchar_encoding
        self._client_encoding = "utf8"
        self._commands_with_count = (
            b"INSERT", b"DELETE", b"UPDATE"
        )
        self.notifications = deque(maxlen=100)
        self.parameter_statuses = deque(maxlen=100)
        self.max_prepared_statements = int(max_prepared_statements)

        # honor logging.* log level constants if specified
        if logLevel not in (logging.DEBUG, logging.ERROR,
                            logging.CRITICAL, logging.FATAL,
                            logging.WARN, logging.WARNING):
            if logLevel == 0:
                logLevel = logging.DEBUG
            elif logLevel == 1:
                logLevel = logging.INFO
            elif logLevel == 2:
                logLevel = logging.WARNING
            else:  # else default to INFO
                logLevel = logging.INFO

        # if no logging has been setup by the caller,
        # and no filename is specified
        # then come up with a file name
        self.log = logging.getLogger("nzpy_extended.Connection["+database+"}]")
        self.log.setLevel(logLevel)

        if logOptions & LogOptions.Logfile:
            h = logging.handlers.\
                RotatingFileHandler('nzpy_extended.log', maxBytes=1024 ** 3 * 10)
            fmt = logging.Formatter(
                '%(asctime)s (%(process)s) [%(name)s:%(filename)s:'
                '%(lineno)s] %(levelname)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S.000000 %Z')
            h.setFormatter(fmt)
            self.log.addHandler(h)
        if not logOptions & LogOptions.Inherit:
            # don't send log messages to the parent loggers
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
                self._usock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore
            else:
                raise ProgrammingError(
                    "one of host or unix_sock must be provided")
            if timeout is not None:
                self._usock.settimeout(timeout)

            self._usock.setblocking(False)
            loop = asyncio.get_event_loop()
            if unix_sock is None and host is not None:
                await loop.sock_connect(self._usock, (host, port))
            elif unix_sock is not None:
                await loop.sock_connect(self._usock, unix_sock)

            if tcp_keepalive:
                self._usock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except socket.error as e:
            self._usock.close()
            raise InterfaceError("communication error", e)

        if hasattr(asyncio, 'to_thread'):
            self._usock.setblocking(True)
            hs = handshake.SyncHandshake(self._usock, ssl, self.log)
            self._usock = await asyncio.to_thread(
                hs.startup, database, securityLevel,
                user, password, pgOptions)
            if self._usock is False:
                raise ProgrammingError("Error in handshake")
            self._backend_pid = hs.backend_pid
            self._backend_key = hs.backend_key
            self._usock.setblocking(False)

            self._stream = NzBufferedStream(self._usock)

            async def _read(n):
                return await self._stream.read(n)

            async def _write(data):
                await self._stream.write(data)

            async def _flush():
                pass

            self._read = _read
            self._write = _write
            self._flush = _flush
            self._backend_key_data = None
            self._dirty_socket = False
        else:
            self._stream = NzBufferedStream(self._usock)

            async def _read(n):
                return await self._stream.read(n)

            async def _write(data):
                await self._stream.write(data)

            async def _flush():
                pass

            self._read = _read
            self._write = _write
            self._flush = _flush
            self._backend_key_data = None
            self._dirty_socket = False

        def text_out(v):
            return v.encode(self._client_encoding)

        def enum_out(v):
            return str(v.value).encode(self._client_encoding)

        def time_out(v):
            return v.isoformat().encode(self._client_encoding)

        def date_out(v):
            return v.isoformat().encode(self._client_encoding)

        def unknown_out(v):
            return str(v).encode(self._client_encoding)

        def array_in(data, idx, length):
            text = data[idx:idx + length].decode(self._client_encoding)
            
            def parse_array(s, pos):
                result = []
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

        def array_recv(data, idx, length):
            final_idx = idx + length
            dim, hasnull, typeoid = iii_unpack(data, idx)
            idx += 12

            # get type conversion method for typeoid
            conversion = self.pg_types[typeoid][1]

            # Read dimension info
            dim_lengths = []
            for i in range(dim):
                dim_lengths.append(ii_unpack(data, idx)[0])
                idx += 8

            # Read all array values
            values = []
            while idx < final_idx:
                element_len, = i_unpack(data, idx)
                idx += 4
                if element_len == -1:
                    values.append(None)
                else:
                    values.append(conversion(data, idx, element_len))
                    idx += element_len

            # at this point, {{1,2,3},{4,5,6}}::int[][] looks like
            # [1,2,3,4,5,6]. go through the dimensions and fix up the array
            # contents to match expected dimensions
            for length in reversed(dim_lengths[1:]):
                values = list(map(list, zip(*[iter(values)] * length)))
            return values

        def vector_in(data, idx, length):
            text = data[idx:idx + length].decode(self._client_encoding)
            return [int(x) for x in text.replace(',', ' ').split()]

        def text_recv(data, offset, length):
            view = memoryview(data)
            return str(view[offset: offset + length], self._client_encoding)

        def bool_recv(data, offset, length):
            return data[offset] == 116  # ascii for t

        def json_in(data, offset, length):
            return loads(
                str(data[offset: offset + length], self._client_encoding))

        def time_in(data, offset, length):
            hour = int(data[offset:offset + 2])
            minute = int(data[offset + 3:offset + 5])
            sec = Decimal(
                data[offset + 6:offset + length].decode(self._client_encoding))
            return time(
                hour, minute, int(sec), int((sec - int(sec)) * 1000000))

        def date_in(data, offset, length):
            d = data[offset:offset + length].decode(self._client_encoding)
            try:
                return date(int(d[:4]), int(d[5:7]), int(d[8:10]))
            except ValueError:
                return d

        def numeric_in(data, offset, length):
            return Decimal(
                data[offset: offset + length].decode(self._client_encoding))

        def numeric_out(d):
            return str(d).encode(self._client_encoding)

        self.pg_types = defaultdict(
            lambda: (FC_TEXT, text_recv), {
                16: (FC_BINARY, bool_recv),  # boolean
                17: (FC_BINARY, bytea_recv),  # bytea
                19: (FC_BINARY, text_recv),  # name type
                20: (FC_BINARY, int8_recv),  # int8
                21: (FC_BINARY, int2_recv),  # int2
                22: (FC_TEXT, vector_in),  # int2vector
                23: (FC_BINARY, int4_recv),  # int4
                25: (FC_BINARY, text_recv),  # TEXT type
                26: (FC_TEXT, int_in),  # oid
                28: (FC_TEXT, int_in),  # xid
                114: (FC_TEXT, json_in),  # json
                700: (FC_BINARY, float4_recv),  # float4
                701: (FC_BINARY, float8_recv),  # float8
                705: (FC_BINARY, text_recv),  # unknown
                829: (FC_TEXT, text_recv),  # MACADDR type
                1000: (FC_BINARY, array_recv),  # BOOL[]
                1003: (FC_BINARY, array_recv),  # NAME[]
                1005: (FC_BINARY, array_recv),  # INT2[]
                1007: (FC_BINARY, array_recv),  # INT4[]
                1009: (FC_BINARY, array_recv),  # TEXT[]
                1014: (FC_BINARY, array_recv),  # CHAR[]
                1015: (FC_BINARY, array_recv),  # VARCHAR[]
                1016: (FC_BINARY, array_recv),  # INT8[]
                1021: (FC_BINARY, array_recv),  # FLOAT4[]
                1022: (FC_BINARY, array_recv),  # FLOAT8[]
                1042: (FC_BINARY, text_recv),  # CHAR type
                1043: (FC_BINARY, text_recv),  # VARCHAR type
                 1082: (FC_TEXT, date_in),  # date
                 1083: (FC_TEXT, time_in),
                 1114: (FC_TEXT, timestamp_in),  # timestamp
                 1184: (FC_TEXT, timestamptz_in),  # timestamp w/ tz
                 1186: (FC_TEXT, interval_recv_integer),  # interval
                 2500: (FC_TEXT, int_in),  # byteint
                1231: (FC_TEXT, array_in),  # NUMERIC[]
                1263: (FC_BINARY, array_recv),  # cstring[]
                1700: (FC_TEXT, numeric_in),  # NUMERIC
                2275: (FC_BINARY, text_recv),  # cstring
                2950: (FC_BINARY, uuid_recv),  # uuid
                3802: (FC_TEXT, json_in),  # jsonb
            })

        self.py_types = {
            type(None): (-1, FC_BINARY, null_send),  # null
            bool: (16, FC_BINARY, bool_send),
            bytearray: (17, FC_BINARY, bytea_send),  # bytea
            20: (20, FC_BINARY, q_pack),  # int8
            21: (21, FC_BINARY, h_pack),  # int2
            23: (23, FC_BINARY, i_pack),  # int4
            PGText: (25, FC_TEXT, text_out),  # text
            float: (701, FC_BINARY, d_pack),  # float8
            PGEnum: (705, FC_TEXT, enum_out),
            date: (1082, FC_TEXT, date_out),  # date
            time: (1083, FC_TEXT, time_out),  # time
            1114: (1114, FC_BINARY, timestamp_send_integer),  # timestamp
            # timestamp w/ tz
            PGVarchar: (1043, FC_TEXT, text_out),  # varchar
            1184: (1184, FC_BINARY, timestamptz_send_integer),
            PGJson: (114, FC_TEXT, text_out),
            PGJsonb: (3802, FC_TEXT, text_out),
            Timedelta: (1186, FC_BINARY, interval_send_integer),
            Interval: (1186, FC_BINARY, interval_send_integer),
            Decimal: (1700, FC_TEXT, numeric_out),  # Decimal
            PGTsvector: (3614, FC_TEXT, text_out),
            UUID: (2950, FC_BINARY, uuid_send)}  # uuid

        self.inspect_funcs = {
            Datetime: self.inspect_datetime,
            list: self.array_inspect,
            tuple: self.array_inspect,
            int: self.inspect_int}

        self.py_types[bytes] = (17, FC_BINARY, bytea_send)  # bytea
        self.py_types[str] = (705, FC_TEXT, text_out)  # unknown
        self.py_types[enum.Enum] = (705, FC_TEXT, enum_out)

        def inet_out(v):
            return str(v).encode(self._client_encoding)

        def inet_in(data, offset, length):
            inet_str = data[offset: offset + length].decode(
                self._client_encoding)
            if '/' in inet_str:
                return ip_network(inet_str, False)
            else:
                return ip_address(inet_str)

        self.py_types[IPv4Address] = (869, FC_TEXT, inet_out)  # inet
        self.py_types[IPv6Address] = (869, FC_TEXT, inet_out)  # inet
        self.py_types[IPv4Network] = (869, FC_TEXT, inet_out)  # inet
        self.py_types[IPv6Network] = (869, FC_TEXT, inet_out)  # inet
        self.pg_types[869] = (FC_TEXT, inet_in)  # inet

        async def conn_send_query():

            if not await self.execute(self._cursor, "set nz_encoding to "
                                              "'utf8'", None):
                return False

            # Set the Datestyle to the format the driver expects it to be in */
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

        if not hasattr(asyncio, 'to_thread'):
            hs = handshake.Handshake(self._stream, ssl, self.log)
            response = await hs.startup(database, securityLevel,
                                  user, password, pgOptions)

            if response is not False:
                if response is True: # Legacy or success bool
                    pass
                else:
                    # Handshake returned the final reader/writer stream
                    # We need to update our internal stream reference in case it changed (SSL)
                    self._stream = response
                    self._read = self._stream.read
                    self._write = self._stream.write
                    
                self._backend_pid = hs.backend_pid
                self._backend_key = hs.backend_key
            else:
                raise ProgrammingError("Error in handshake")

        self._cursor = self.cursor()
        #  code = self.error = None
        self.error = None

        if not await conn_send_query():
            self.log.warning("Error sending initial setup queries")

        self.commandNumber = 0

        if self.error is not None:
            raise ProgrammingError(self.error)

        self.in_transaction = False
        # Drain the 4 trailing bytes from the final READY_FOR_QUERY
        # of conn_send_query() so the stream is clean for the next command.
        await self._read(4)
        self.status = None

    async def handle_ERROR_RESPONSE(self, data, ps):
        msg = dict(
            (
                s[:1].decode(self._client_encoding),
                s[1:].decode(self._client_encoding)) for s in
            data.split(NULL_BYTE) if s != b'')

        response_code = msg[RESPONSE_CODE]
        if response_code == '28000':
            cls = InterfaceError
        elif response_code == '23505':
            cls = IntegrityError
        else:
            cls = ProgrammingError

        self.error = cls(msg)

    async def handle_EMPTY_QUERY_RESPONSE(self, data, ps):
        self.error = ProgrammingError("query was empty")

    async def handle_CLOSE_COMPLETE(self, data, ps):
        pass

    async def handle_PARSE_COMPLETE(self, data, ps):
        # Byte1('1') - Identifier.
        # Int32(4) - Message length, including self.
        pass

    async def handle_BIND_COMPLETE(self, data, ps):
        pass

    async def handle_PORTAL_SUSPENDED(self, data, cursor):
        pass

    async def handle_PARAMETER_DESCRIPTION(self, data, ps):
        # Well, we don't really care -- we're going to send whatever we
        # want and let the database deal with it.  But thanks anyways!

        # count = h_unpack(data)[0]
        # type_oids = unpack_from("!" + "i" * count, data, 2)
        pass

    async def handle_COPY_DONE(self, data, ps):
        self._copy_done = True

    async def handle_COPY_OUT_RESPONSE(self, data, ps):
        # Int8(1) - 0 textual, 1 binary
        # Int16(2) - Number of columns
        # Int16(N) - Format codes for each column (0 text, 1 binary)

        is_binary, num_cols = bh_unpack(data)
        # column_formats = unpack_from('!' + 'h' * num_cols, data, 3)
        if ps.stream is None:
            raise InterfaceError(
                "An output stream is required for the COPY OUT response.")

    async def handle_COPY_DATA(self, data, ps):
        ps.stream.write(data)

    async def handle_COPY_IN_RESPONSE(self, data, ps):
        # Int16(2) - Number of columns
        # Int16(N) - Format codes for each column (0 text, 1 binary)
        is_binary, num_cols = bh_unpack(data)
        # column_formats = unpack_from('!' + 'h' * num_cols, data, 3)
        if ps.stream is None:
            raise InterfaceError(
                "An input stream is required for the COPY IN response.")

        bffr = bytearray(8192)
        while True:
            bytes_read = ps.stream.readinto(bffr)
            if bytes_read == 0:
                break
            await self._write(COPY_DATA + i_pack(bytes_read + 4))
            await self._write(bffr[:bytes_read])
            await self._flush()

        # Send CopyDone
        # Byte1('c') - Identifier.
        # Int32(4) - Message length, including self.
        await self._write(COPY_DONE_MSG)
        await self._write(SYNC_MSG)
        await self._flush()

    async def handle_NOTIFICATION_RESPONSE(self, data, ps):
        ##
        # A message sent if this connection receives a NOTIFY that it was
        # LISTENing for.
        # <p>
        # Stability: Added in nzpy_extended v1.03.  When limited to accessing
        # properties from a notification event dispatch, stability is
        # guaranteed for v1.xx.
        backend_pid = i_unpack(data)[0]
        idx = 4
        null = data.find(NULL_BYTE, idx) - idx
        condition = data[idx:idx + null].decode("ascii")
        idx += null + 1
        null = data.find(NULL_BYTE, idx) - idx
        # additional_info = data[idx:idx + null]

        self.notifications.append((backend_pid, condition))

    def cursor(self):
        """Creates a :class:`Cursor` object bound to this
        connection.
        This function is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        """
        return Cursor(self)

    async def commit(self):
        """Commits the current database transaction.
        This function is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        """
        await self.execute(self._cursor, "commit", None)

    async def rollback(self):
        """Rolls back the current database transaction.
        This function is part of the `DBAPI 2.0 specification
        <http://www.python.org/dev/peps/pep-0249/>`_.
        """
        if not self.in_transaction:
            return
        await self.execute(self._cursor, "rollback", None)

    async def close(self):
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

    async def cancel(self):
        """Cancels the current database operation."""
        if getattr(self, '_backend_pid', None) is None or getattr(self, '_backend_key', None) is None:
            return

        try:
            if getattr(self, '_unix_sock', None) is not None:
                reader, writer = await asyncio.open_unix_connection(self._unix_sock)
            else:
                if getattr(self, '_host', None) is None:
                    return
                reader, writer = await asyncio.open_connection(self._host, self._port)

            cancel_code = 80877102
            msg = bytearray(i_pack(16) + i_pack(cancel_code) + i_pack(self._backend_pid) + i_pack(self._backend_key))
            writer.write(msg)
            await writer.drain()
            try:
                # Wait for the backend to acknowledge and close the socket.
                # If we close immediately, the TCP stack might send a RST and drop the payload.
                await reader.read(1)
            except Exception:
                pass
            writer.close()
            await writer.wait_closed()
            self.log.info("Sent cancellation request to backend")
        except Exception as e:
            self.log.warning("Could not send cancel request: %s", str(e))

    async def handle_READY_FOR_QUERY(self, data, ps):
        # Byte1 -   Status indicator.
        self.in_transaction = data != IDLE

    def inspect_datetime(self, value):
        if value.tzinfo is None:
            return self.py_types[1114]  # timestamp
        else:
            return self.py_types[1184]  # send as timestamptz

    def inspect_int(self, value):
        if min_int2 < value < max_int2:
            return self.py_types[21]
        if min_int4 < value < max_int4:
            return self.py_types[23]
        if min_int8 < value < max_int8:
            return self.py_types[20]

    def make_params(self, values):
        params = []
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

    async def handle_ROW_DESCRIPTION(self, data, cursor):
        count = h_unpack(data)[0]
        idx = 2
        for i in range(count):
            name = data[idx:data.find(NULL_BYTE, idx)]
            idx += len(name) + 1
            field = dict(zip(("type_oid", "type_size", "type_modifier",
                              "format"), ihic_unpack(data, idx)))
            field['name'] = name  # type: ignore
            idx += 11
            cursor.ps['row_desc'].append(field)
            field['nzpy_extended_fc'] = self.pg_types[field['type_oid']][0]  # type: ignore
            field['func'] = self.pg_types[field['type_oid']][1]  # type: ignore

    async def Prepare(self, cursor, query, vals):

        statement, make_args = convert_paramstyle(nzpy_extended.paramstyle, query)
        args = make_args(vals)
        placeholderCount = query.count('?')
        if placeholderCount == 0:
            return query
        if len(args) >= 65536:
            self.log.warning("got %d parameters but PostgreSQL only "
                             "supports 65535 parameters", len(args))
        if len(args) != placeholderCount:
            self.log.warning("got %d parameters but the statement "
                             "requires %d", len(args), placeholderCount)

        for arg in args:
            if isinstance(arg, str) or isinstance(arg, datetime.time) or \
                    isinstance(arg, datetime.date) or \
                    isinstance(arg, datetime.datetime) or \
                    isinstance(arg, dict):
                escaped = str(arg).replace("'", "''")
                query = query.replace('?', "'{}'".format(escaped), 1)
            elif isinstance(arg, bytes):
                bytfmt = "x'{}'"
                query = \
                    query.replace('?',
                                  bytfmt.
                                  format(arg.decode(self._client_encoding)),
                                  1)
            elif arg is None:
                query = query.replace('?', 'NULL', 1)
            else:
                query = query.replace('?', str(arg), 1)

        return query

    async def _drain_protocol_generator(self, generator):
        """Consume remaining protocol messages after an error (C# DoNextStep parity)."""
        if generator is None:
            return
        try:
            async for _state in generator:
                pass
        except StopAsyncIteration:
            pass
        finally:
            self._active_generator = None

    async def _drain_socket(self):
        """Drains all pending messages on the socket until READY_FOR_QUERY ('Z') is received."""
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
                    # null terminated filename
                    while True:
                        char = await self._read(1)
                        if char == b'\x00':
                            break
                    await self._read(4) # logType
                    # Drain file payload blocks
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
                    
                # Unknown/fallback
                length = i_unpack(await self._read(4))[0]
                await self._read(length)
        except Exception as e:
            self.log.warning("Error during socket draining: %s", e)

    async def execute(self, cursor, query, vals):

        # Always drain the active generator first.  It may have buffered data from
        # a previous query that is still in the stream buffer (e.g. after a direct
        # cancel where the server sent ErrorResponse+ReadyForQuery and the generator
        # consumed those into its internal buffer).
        active_gen = getattr(self, '_active_generator', None)
        if active_gen is not None:
            old_cursor = getattr(self, '_active_cursor', None)
            await self._drain_protocol_generator(active_gen)
            if old_cursor is not None:
                old_cursor._cached_rows.clear()
                old_cursor._generator = None
                self._active_cursor = None
        
        # If the socket is still dirty (e.g. a timeout interrupted the generator
        # mid-stream, or the cancel left behind data that the generator did not
        # consume), drain whatever remains on the wire.
        if getattr(self, '_dirty_socket', False):
            await self._drain_socket()

        self._dirty_socket = True

        self.error = None
        cursor.notices = []
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

        if query is not None:
            if isinstance(query, str):
                query = query.encode('utf8')
        buf.extend(query + NULL_BYTE)
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
            raise ProgrammingError(self.error)

        if response == "ROW_DESCRIPTION" and len(cursor.ps.get('row_desc', [])) > 0:
            cursor._has_rows = True
        else:
            cursor._has_rows = len(cursor._cached_rows) > 0
        return response

    async def _connNextResultSetGenerator(self, cursor):

        fname = None
        fh = None
        self._cached_header = None

        while (1):
            if self._cached_header is not None:
                header = self._cached_header
                self._cached_header = None
            else:
                header = await self._read(5)
            response = header[:1]

            if response == COMMAND_COMPLETE:
                #  portal query command, no tuples returned
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
                self.error = str(await self._read(length), self._client_encoding)
                self.log.debug("Response received from backend:%s", self.error)
                yield "ERROR"
                continue
            if response == ROW_DESCRIPTION:
                length = i_unpack(await self._read(4))[0]
                prev_tupdesc = cursor.ps.get('tupdesc') if cursor.ps else None
                cursor.ps = {'row_desc': [], 'tupdesc': prev_tupdesc}
                await self.handle_ROW_DESCRIPTION(await self._read(length), cursor)
                # We've got row_desc that allows us to identify what we're
                # going to get back from this statement.
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
                inner_header = self._stream.read_view_sync(8)
                if inner_header is None:
                    inner_header = await self._read(8)
                tup_len = i_unpack(inner_header, 4)[0]
                data = self._stream.read_view_sync(tup_len)
                if data is None:
                    data = await self._read(tup_len)
                self._process_dbos_payload(cursor, self.tupdesc, data)

                if _HAVE_C_EXT:
                    view = self._stream.read_available_view()
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
                            self._stream.advance_head(consumed)

                # Peek at the next header; save it as cached for the next iteration.
                # This allows the generator to yield DATA_BATCH immediately rather
                # than blocking while processing all consecutive Y messages.
                header = self._stream.read_view_sync(5)
                if header is None:
                    header = await self._read(5)
                self._cached_header = header
                if len(cursor._cached_rows) > 0:
                    cursor._has_rows = True
                yield "DATA_BATCH"
                continue
            if response == b"u":
                #  unload - initialize application protocol
                #  in ODBC, the first 10 bytes are utilized to
                #  populate clientVersion, formatType and bufSize
                #  these are not needed in go lang, hence ignoring 10 bytes
                await self._read(10)
                # Next 16 bytes are Reserved Bytes for future extension
                await self._read(16)
                # Get the filename (specified in dataobject)
                length = i_unpack(await self._read(4))[0]
                fnameBuf = await self._read(length)
                fname = str(fnameBuf, self._client_encoding)
                try:
                    is_fifo = stat.S_ISFIFO(os.stat(fname).st_mode) if os.path.exists(fname) else False
                    if is_fifo:
                        fh = open(fname, "wb")
                    else:
                        fh = open(fname, "wb+")
                    self.log.debug("Successfully opened file: %s", fname)
                    # file open successfully, send status back to datawriter
                    buf = bytearray(i_pack(0))
                    await self._write(buf)
                    await self._flush()
                except Exception:
                    self.log.warning("Error while opening file")

            if response == b"U":  # handle unload data
                await self.receiveAndWriteDatatoExternal(fname, fh)
                yield "EXTAB_DATA"

            if response == b"l":
                await self.xferTable()
                yield "EXTAB_IMPORT"

            if response == b"x":  # handle Ext Tbl parser abort
                await self._read(4)
                self.log.warning("Error operation cancel")
                yield "EXTAB_CANCEL"

            if response == b"e":

                length = i_unpack(await self._read(4))[0]
                logDir = str(await self._read(length - 1), self._client_encoding)

                await self._read(1)
                #  ignore one byte as it is null character at
                #  the end of the string
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
                if getattr(cursor, 'notice_handler', None) and callable(cursor.notice_handler):
                    try:
                        cursor.notice_handler(notice)
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
                if getattr(cursor, 'notice_handler', None) and callable(cursor.notice_handler):
                    try:
                        cursor.notice_handler(notice)
                    except Exception as e:
                        self.log.warning("Error in notice_handler: %s", e)
                self.log.debug("Response received from backend:%s", notice)
                cursor._cached_rows.append([])
                yield "NOTICE"

    def Res_get_dbos_column_descriptions(self, data, tupdesc):

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
        for ix in range(tupdesc.numFields):
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

    def _process_dbos_payload(self, cursor, tupdesc, data):
        numFields = tupdesc.numFields
        mv = memoryview(data)

        if _HAVE_C_EXT:
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

    def _build_dbos_row_python(self, cursor, tupdesc, mv, data):
        numFields = tupdesc.numFields

        bitmaplen = numFields // 8
        if (numFields % 8) > 0:
            bitmaplen += 1

        b_data = mv[2:2+bitmaplen]
        bitmap = [(b >> j) & 1 for b in b_data for j in range(8)]

        var_offsets = []
        current_voff = tupdesc.fixedFieldsSize
        for _ in range(tupdesc.numVaryingFields):
            var_offsets.append(current_voff)
            if current_voff + 2 <= len(data):
                vlen = h_le_unpack(data, current_voff)[0]
                if vlen % 2 == 0:
                    current_voff += vlen
                else:
                    current_voff += vlen + 1

        field_lf = 0
        cur_field = 0
        row = []

        while field_lf < numFields and cur_field < numFields:

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
                timestamp_value = (0, 0, 0, 0, 0, 0, 0)
                if fldlen == 8:
                    result = timestamp2struct(workspace)
                    if result is not False:
                        timestamp_value = result
                row.append(datetime(timestamp_value[0], timestamp_value[1], timestamp_value[2], timestamp_value[3], timestamp_value[4], timestamp_value[5], timestamp_value[6]))
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
                if scale == 0:
                    row.append(Decimal(str(val)))
                else:
                    sign = '-' if val < 0 else ''
                    val = abs(val)
                    integer_part = val // (10 ** scale)
                    fractional_part = val % (10 ** scale)
                    row.append(Decimal(f'{sign}{integer_part}.{fractional_part:0{scale}d}'))
            elif fldtype == NzTypeBool:
                row.append(data[offset] == 1)

            cur_field += 1
            field_lf += 1

        cursor._cached_rows.append(row)

    async def Res_read_dbos_tuple(self, cursor, tupdesc):
        header = await self._read(8)
        length = i_unpack(header, 4)[0]
        data = await self._read(length)
        self._process_dbos_payload(cursor, tupdesc, data)

    def CTable_FieldAt(self, tupdesc, data, cur_field):
        if tupdesc.field_fixedSize[cur_field] != 0:
            return self.CTable_i_fixedFieldPtr(data,
                                               tupdesc.field_offset[cur_field])

        return self.CTable_i_varFieldPtr(data, tupdesc.fixedFieldsSize,
                                         tupdesc.field_offset[cur_field])

    def CTable_i_fixedFieldPtr(self, data, offset):
        data = data[offset:]
        return data

    def CTable_i_varFieldPtr(self, data, fixedOffset, varDex):

        lenP = data[fixedOffset:]
        for ctr in range(varDex):
            length = int.from_bytes(lenP[0:2], 'little')
            if length % 2 == 0:
                lenP = lenP[length:]
            else:
                lenP = lenP[length + 1:]

        return lenP

    @staticmethod
    def _oid_type_name(oid):
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
    def _numeric_precision_scale_from_modifier(type_mod):
        if type_mod > TYPE_MOD_OFFSET:
            normalized = type_mod - TYPE_MOD_OFFSET
            return normalized >> 16, normalized & 0xffff
        return 0, 0

    @staticmethod
    def _character_declared_length(oid, type_mod):
        if oid in (_OID_BPCHAR, _OID_VARCHAR, _OID_TEXT, _OID_NCHAR, _OID_NVARCHAR):
            if type_mod > TYPE_MOD_OFFSET:
                return type_mod - TYPE_MOD_OFFSET
        return None

    def _column_null_ok(self, index, tupdesc):
        if tupdesc is None:
            return True
        if tupdesc.nullsAllowed is not None and tupdesc.nullsAllowed <= 0:
            return False
        if index < len(tupdesc.field_nullAllowed):
            return bool(tupdesc.field_nullAllowed[index])
        return True

    def _resolve_column_metadata(self, col, index, tupdesc):
        oid = col['type_oid']
        type_mod = col.get('type_modifier', -1)
        type_size = col.get('type_size', -1)
        name = col['name'].decode() if isinstance(col['name'], bytes) else col['name']
        type_name = self._oid_type_name(oid)
        declared_len = self._character_declared_length(oid, type_mod)
        num_prec, num_scale = self._numeric_precision_scale_from_modifier(type_mod)

        column_size = type_size if type_size > 0 else -1
        num_prec = 0
        num_scale = 0

        if tupdesc is not None and index < tupdesc.numFields:
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
            'numeric_scale': num_scale,
            'data_type': data_type,
            'null_ok': self._column_null_ok(index, tupdesc),
            'is_long': column_size > 8000,
            'declared_length': declared_len,
        }

    @staticmethod
    def _oid_to_python_type(oid):
        import decimal as _decimal
        mapping = {
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

    def CTable_i_fieldType(self, tupdesc, coldex):
        return (tupdesc.field_type[coldex])

    def CTable_i_fieldSize(self, tupdesc, coldex):
        return (tupdesc.field_size[coldex])

    def CTable_i_fieldPrecision(self, tupdesc, coldex):
        return (((tupdesc.field_size[coldex]) >> 8) & 0x7F)

    def CTable_i_fieldScale(self, tupdesc, coldex):
        return ((tupdesc.field_size[coldex]) & 0x00FF)

    def CTable_i_fieldNumericDigit32Count(self, tupdesc, coldex):
        sizeTNumericDigit = 4
        return int(tupdesc.field_trueSize[coldex] / sizeTNumericDigit)
        #  sizeof(TNumericDigit)

    async def receiveAndWriteDatatoExternal(self, fname, fh):

        await self._read(4)

        try:
            while True:

                #  Get EXTAB_SOCK Status
                try:
                    status = i_unpack(await self._read(4))[0]
                except Exception as e:
                    self.log.warning("Error while retrieving status: %s", str(e))
                    break

                if status == EXTAB_SOCK_DATA:
                    # get number of bytes in block
                    numBytes = i_unpack(await self._read(4))[0]
                    try:
                        blockBuffer = await self._read(numBytes)
                        fh.write(blockBuffer)
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
            try:
                fh.close()
                self.log.debug("Closed export file: %s", fname)
            except Exception:
                pass

        return

    async def xferTable(self):
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

        try:
            filehandle = open(filename, 'rb')
            self.log.info("Successfully opened External"
                          " file to read:%s", filename)
            while True:
                data = filehandle.read(blockSize)
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
            filehandle.close()
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

    ##################################################################
    #  Function: getFileFromBE - This Routine opens a file in
    #           the temp directory
    #           using the filename specified by the BE in /tmp
    #           or c:\.
    #           The data sent by the BE are then written into
    #           this file.
    #
    #  Parameters:
    #
    #   In       logDir - directory to put the file
    #           filename - name of file to write.
    #           logType - not used at this implementation.
    #
    #   Out      boolean - success or failure.
    #
    #################################################################
    async def getFileFromBE(self, logDir, filename, logType):

        status = True

        # If no explicit -logDir mentioned (defaulted by backend to /tmp)
        fullpath = path.join(logDir, filename)

        if logType == 1:
            fullpath = fullpath + ".nzlog"
            fh = open(fullpath, "wb+")
        elif logType == 2:
            fullpath = fullpath + ".nzbad"
            fh = open(fullpath, "wb+")
        elif logType == 3:
            fullpath = fullpath + ".nzstats"
            fh = open(fullpath, "wb+")
        else:
            fh = open(fullpath, "wb+")

        try:
            while (1):

                numBytes = i_unpack(await self._read(4))[0]

                if numBytes == 0:
                    break

                dataBuffer = await self._read(numBytes)

                if status:
                    try:
                        fh.write(dataBuffer)
                        self.log.info("Successfully written data "
                                      "into file: %s", fullpath)
                    except Exception as e:
                        self.log.error("Error in writing data to file '%s': %s",
                                      fullpath, str(e))
                        status = False

        finally:
            fh.close()

        return status

    async def _send_message(self, code, data):
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

    async def send_EXECUTE(self, cursor):
        # Byte1('E') - Identifies the message as an execute message.
        # Int32 -   Message length, including self.
        # String -  The name of the portal to execute.
        # Int32 -   Maximum number of rows to return, if portal
        #           contains a query # that returns rows.
        #           0 = no limit.
        await self._write(EXECUTE_MSG)
        await self._write(FLUSH_MSG)

    def handle_NO_DATA(self, msg, ps):
        pass

    async def handle_COMMAND_COMPLETE(self, data, cursor):
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

    async def handle_DATA_ROW(self, data, cursor):

        numberofcol = len(cursor.ps['row_desc'])
        bitmaplen = numberofcol // 8
        if (numberofcol % 8) > 0:
            bitmaplen += 1

        hex = data[0:bitmaplen].hex()
        dec = int(hex, 16)

        bitmap = decimalToBinary(dec, bitmaplen * 8)
        bitmap.reverse()

        data_idx = bitmaplen
        row = []
        row_desc = cursor.ps['row_desc']
        for i, func in enumerate(cursor.ps['input_funcs']):
            if bitmap[i] == 0:
                row.append(None)
            else:
                vlen = i_unpack(data, data_idx)[0]
                data_idx += 4
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

    async def handle_messages(self, cursor):
        code = self.error = None

        while code != READY_FOR_QUERY:
            code, data_len = ci_unpack(await self._read(5))
            await self.message_types[code](await self._read(data_len - 4), cursor)

        if self.error is not None:
            raise self.error

    # Byte1('C') - Identifies the message as a close command.
    # Int32 - Message length, including self.
    # Byte1 - 'S' for prepared statement, 'P' for portal.
    # String - The name of the item to close.
    async def close_prepared_statement(self, statement_name_bin):
        await self._send_message(CLOSE, STATEMENT + statement_name_bin)
        await self._write(SYNC_MSG)
        await self._flush()
        await self.handle_messages(self._cursor)

    async def handle_PARAMETER_STATUS(self, data, ps):
        pos = data.find(NULL_BYTE)
        key, value = data[:pos], data[pos + 1:-1]
        self.parameter_statuses.append((key, value))
        if key == b"client_encoding":
            encoding = value.decode("ascii").lower()
            self._client_encoding = pg_to_py_encodings.get(encoding, encoding)
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

    def array_inspect(self, value):
        # Check if array has any values. If empty, we can just assume it's an
        # array of strings
        first_element = array_find_first_element(value)
        if first_element is None:
            oid = 25
            # Use binary ARRAY format to avoid having to properly
            # escape text in the array literals
            fc = FC_BINARY
            array_oid = pg_array_types[oid]
        else:
            # supported array output
            typ = type(first_element)

            if issubclass(typ, int):
                # special int array support -- send as smallest possible array
                # type
                typ = int
                int2_ok, int4_ok, int8_ok = True, True, True
                for v in array_flatten(value):
                    if v is None:
                        continue
                    if min_int2 < v < max_int2:
                        continue
                    int2_ok = False
                    if min_int4 < v < max_int4:
                        continue
                    int4_ok = False
                    if min_int8 < v < max_int8:
                        continue
                    int8_ok = False
                if int2_ok:
                    array_oid = 1005  # INT2[]
                    oid, fc, send_func = (21, FC_BINARY, h_pack)
                elif int4_ok:
                    array_oid = 1007  # INT4[]
                    oid, fc, send_func = (23, FC_BINARY, i_pack)
                elif int8_ok:
                    array_oid = 1016  # INT8[]
                    oid, fc, send_func = (20, FC_BINARY, q_pack)
                else:
                    raise ArrayContentNotSupportedError(
                        "numeric not supported as array contents")
            else:
                try:
                    oid, fc, send_func = self.make_params((first_element,))[0]

                    # If unknown or string, assume it's a string array
                    if oid in (705, 1043, 25):
                        oid = 25
                        # Use binary ARRAY format to avoid having to properly
                        # escape text in the array literals
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
            def send_array_binary(arr):
                # check that all array dimensions are consistent
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
            def send_array_text(arr):
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


# pg element oid -> pg array typeoid
pg_array_types = {
    16: 1000,
    25: 1009,  # TEXT[]
    701: 1022,
    1043: 1009,
    1700: 1231,  # NUMERIC[]
}

# PostgreSQL encodings:
#   http://www.postgresql.org/docs/8.3/interactive/multibyte.html
# Python encodings:
#   http://www.python.org/doc/2.4/lib/standard-encodings.html
#
# Commented out encodings don't require a name change between PostgreSQL and
# Python.  If the py side is None, then the encoding isn't supported.
pg_to_py_encodings = {
    # Not supported:
    "mule_internal": None,
    "euc_tw": None,

    # Name fine as-is:
    # "euc_jp",
    # "euc_jis_2004",
    # "euc_kr",
    # "gb18030",
    # "gbk",
    # "johab",
    # "sjis",
    # "shift_jis_2004",
    # "uhc",
    # "utf8",

    # Different name:
    "euc_cn": "gb2312",
    "iso_8859_5": "is8859_5",
    "iso_8859_6": "is8859_6",
    "iso_8859_7": "is8859_7",
    "iso_8859_8": "is8859_8",
    "koi8": "koi8_r",
    "latin1": "iso8859-1",
    "latin2": "iso8859_2",
    "latin3": "iso8859_3",
    "latin4": "iso8859_4",
    "latin5": "iso8859_9",
    "latin6": "iso8859_10",
    "latin7": "iso8859_13",
    "latin8": "iso8859_14",
    "latin9": "iso8859_15",
    "sql_ascii": "ascii",
    "win866": "cp886",
    "win874": "cp874",
    "win1250": "cp1250",
    "win1251": "cp1251",
    "win1252": "cp1252",
    "win1253": "cp1253",
    "win1254": "cp1254",
    "win1255": "cp1255",
    "win1256": "cp1256",
    "win1257": "cp1257",
    "win1258": "cp1258",
    "unicode": "utf-8",  # Needed for Amazon Redshift
}


def walk_array(arr):
    for i, v in enumerate(arr):
        if isinstance(v, list):
            for a, i2, v2 in walk_array(v):
                yield a, i2, v2
        else:
            yield arr, i, v


def array_find_first_element(arr):
    for v in array_flatten(arr):
        if v is not None:
            return v
    return None


def array_flatten(arr):
    for v in arr:
        if isinstance(v, list):
            for v2 in array_flatten(v):
                yield v2
        else:
            yield v


def array_check_dimensions(arr):
    if len(arr) > 0:
        v0 = arr[0]
        if isinstance(v0, list):
            req_len = len(v0)
            req_inner_lengths = array_check_dimensions(v0)
            for v in arr:
                inner_lengths = array_check_dimensions(v)
                if len(v) != req_len or inner_lengths != req_inner_lengths:
                    raise ArrayDimensionsNotConsistentError(
                        "array dimensions not consistent")
            retval = [req_len]
            retval.extend(req_inner_lengths)
            return retval
        else:
            # make sure nothing else at this level is a list
            for v in arr:
                if isinstance(v, list):
                    raise ArrayDimensionsNotConsistentError(
                        "array dimensions not consistent")
    return []


def array_has_null(arr):
    for v in array_flatten(arr):
        if v is None:
            return True
    return False


def array_dim_lengths(arr):
    len_arr = len(arr)
    retval = [len_arr]
    if len_arr > 0:
        v0 = arr[0]
        if isinstance(v0, list):
            retval.extend(array_dim_lengths(v0))
    return retval


def decimalToBinary(dec, bitmaplen):
    """This function converts decimal number
    to binary and prints it"""
    bin = []
    while bitmaplen != 0:
        remainder = dec % 2
        dec = dec // 2
        bin.append(remainder)
        bitmaplen -= 1

    return bin


def date2j(y, m, d):
    m12 = int((m - 14) / 12)
    return ((1461 * (y + 4800 + m12)) // 4 + (367 * (m - 2 - 12 * m12))
            // 12 - (3 * ((y + 4900 + m12) // 100)) // 4 + d - 32075)


def j2date(jd):
    date = []
    lval = jd + 68569
    nval = (4 * lval) // 146097
    lval -= (146097 * nval + 3) // 4
    ival = (4000 * (lval + 1)) // 1461001
    lval += 31 - (1461 * ival) // 4
    jval = (80 * lval) // 2447
    day = lval - (2447 * jval) // 80
    lval = jval // 11
    month = (jval + 2) - (12 * lval)
    year = 100 * (nval - 49) + ival + lval

    date.append(year)
    date.append(month)
    date.append(day)

    return date


def time2struct(time):
    time_value = []
    us = time % 1000000
    time = int(time / 1000000) # NZ microsecs
    second = time % 60
    time = int(time / 60)
    minute = time % 60
    hour = int(time / 60)

    time_value.append(hour)
    time_value.append(minute)
    time_value.append(second)
    time_value.append(us)

    return time_value


def IntervalToText(interval_time, interval_month):
    fsec = 0

    tm, fsec = interval2tm(interval_time, interval_month, fsec)

    fsec = fsec / 1000000

    return EncodeTimeSpan(tm, fsec)


def interval2tm(interval_time, interval_month, fsec):
    tmpVal = 0
    time = []

    if interval_month != 0:
        year = int(interval_month / 12)
        mon = interval_month % 12
    else:
        year = 0
        mon = 0

    tmpVal = interval_time // 86400000000

    if tmpVal != 0:
        interval_time -= tmpVal * 86400000000
        mday = tmpVal
    else:
        mday = 0

    tmpVal = interval_time // 3600000000

    if tmpVal != 0:
        interval_time -= tmpVal * 3600000000
        hour = tmpVal
    else:
        hour = 0

    tmpVal = interval_time // 60000000

    if tmpVal != 0:
        interval_time -= tmpVal * 60000000
        min = tmpVal
    else:
        min = 0

    tmpVal = interval_time // 1000000

    if tmpVal != 0:
        interval_time -= tmpVal * 1000000
        sec = tmpVal
    else:
        sec = 0

    time.append(year)
    time.append(mon)
    time.append(mday)
    time.append(hour)
    time.append(min)
    time.append(sec)

    fsec = interval_time

    return time, fsec


def EncodeTimeSpan(tm, fsec):
    # The sign of year and month are guaranteed to match,
    # since they are stored internally as "month".
    # But we'll need to check for is_before and is_nonzero
    # when determining the signs of hour/minute/seconds fields.
    #
    is_nonzero = is_before = minus = False
    str = ""

    if tm[0] != 0:
        str = "{} year"
        str = str.format(tm[0])
        if abs(tm[0]) != 1:
            str = str + "s"
        else:
            str = str + ""

        if tm[0] < 0:
            is_before = True

        is_nonzero = True

    if tm[1] != 0:

        if is_nonzero:
            str = str + " "
        else:
            str = str + ""

        if is_before and tm[1] > 0:
            str = str + "+"
        else:
            str = str + ""

        str_mon = "{} mon"
        str_mon = str_mon.format(tm[1])

        if abs(tm[1]) != 1:
            str_mon = str_mon + "s"
        else:
            str_mon = str_mon + ""

        str = str + str_mon

        if tm[1] < 0:
            is_before = True

        is_nonzero = True

    if tm[2] != 0:

        if is_nonzero:
            str = str + " "
        else:
            str = str + ""

        if is_before and tm[2] > 0:
            str = str + "+"
        else:
            str = str + ""

        str_day = "{} day"
        str_day = str_day.format(tm[2])

        if abs(tm[2]) != 1:
            str_day = str_day + "s"
        else:
            str_day = str_day + ""

        str = str + str_day

        if tm[2] < 0:
            is_before = True

        is_nonzero = True

    if (not is_nonzero) or (tm[3] != 0) or \
            (tm[4] != 0) or (tm[5] != 0) or (fsec != 0):

        if tm[3] < 0 or tm[4] < 0 or tm[5] < 0 or fsec < 0:
            minus = True

        if is_nonzero:
            str = str + " "
        else:
            str = str + ""

        if minus:
            str = str + "-"
        else:
            if is_before:
                str = str + "+"
            else:
                str = str + ""

        str_hr_min = "{0:02d}:{1:02d}"
        str = str + str_hr_min.format(abs(tm[3]), abs(tm[4]))

        is_nonzero = True

        # fractional seconds?

        if fsec != 0:
            fsec += tm[5]
            str_hr_sec = ":{0:09.6f}"
            str = str + str_hr_sec.format(abs(fsec))
            is_nonzero = True
        # otherwise, integer seconds only?
        elif tm[5] != 0:
            str_hr_sec = ":{0:02d}"
            str = str + str_hr_sec.format(abs(tm[5]))
            is_nonzero = True

    # identically zero? then put in a unitless zero...
    if not is_nonzero:
        str = str + "0"

    return str


def abs(n):
    if n < 0:
        return -n
    else:
        return n


def timetz_out_timetzadt(timetz_time, timetz_zone):
    tm = []

    time = int(timetz_time / 1000000)
    fusec = timetz_time % 1000000

    hour = int(time / 3600)
    time = time % 3600
    min = int(time / 60)
    sec = time % 60

    tm.append(hour)
    tm.append(min)
    tm.append(sec)

    return EncodeTimeOnly(tm, fusec, timetz_zone)


# EncodeTimeOnly()
# Encode time fields only.

def EncodeTimeOnly(tm, fusec, timetz_zone):
    if (tm[0] < 0) or (tm[0] > 24):
        return ""

    if (tm[1] < 0) or (tm[1] > 59):
        return ""

    fusec = fusec / 1000000

    if fusec != 0:
        fusec += tm[2]
        str = "{0:02d}:{1:02d}:{2:09.6f}"
        str = str.format(tm[0], tm[1], fusec)
        str = str.rstrip('0')
        if str.endswith('.'):
            str = str[:-1]
    else:
        str = "{0:02d}:{1:02d}:{2:02d}"
        str = str.format(tm[0], tm[1], tm[2])

    if timetz_zone != 0:
        display_zone = -timetz_zone
        tz_hour = abs(display_zone) // 3600
        tz_min = (abs(display_zone) % 3600) // 60
        sign = '+' if display_zone > 0 else '-'

        if tz_min != 0:
            str_tz = "{0}{1:02d}:{2:02d}"
            str = str + str_tz.format(sign, tz_hour, tz_min)
        else:
            str_tz = "{0}{1:02d}"
            str = str + str_tz.format(sign, tz_hour)

    return str


def timestamp2struct(dt):
    ts = []
    date = int(dt // 86400000000)
    date0 = J2000_OFFSET

    time = dt % 86400000000

    if time < 0:
        time += 86400000000
        #  NZ - was 86400 w/o exp
        date -= 1

    #  Julian day routine does not work for negative Julian days
    if date < -date0:
        return False

    #  add offset to go from J2000 back to standard Julian date
    date += date0

    ts = j2date(date)

    fraction = (time % 1000000)  # NZ microsecs

    #  Netezza stores the fraction field of TIMESTAMP_STRUCT to
    #  microsecond precision. The fraction field of a must be in
    #  billionths, per ODBC spec. Therefore, multiply by 1000.

    time = int(time / 1000000)
    #  NZ microsecs

    hour = int(time / 3600)
    time -= (hour * 3600)
    minute = int(time / 60)
    second = time - (minute * 60)

    ts.append(hour)
    ts.append(minute)
    ts.append(second)
    ts.append(fraction)

    return ts
