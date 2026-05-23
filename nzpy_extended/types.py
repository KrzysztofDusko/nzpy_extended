import datetime
import enum
from calendar import timegm
from datetime import date, datetime as Datetime, time, timedelta as Timedelta
from datetime import timezone as Timezone
from decimal import Decimal
from json import dumps

from .utils import (
    d_pack, d_unpack, dii_pack, f_unpack, h_le_unpack, h_pack,
    i_le_unpack, i_pack, i_unpack, ii_unpack, iii_unpack,
    min_int4, max_int4, min_int8, max_int8,
    q_le_unpack, q_pack, q_unpack, qii_pack,
)

ZERO = Timedelta(0)
BINARY = bytes


class LogOptions(enum.IntFlag):
    Disabled = 0
    Inherit = enum.auto()
    Logfile = enum.auto()


class Interval():
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

    def __ne__(self, other):
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


def Date(year, month, day):
    return date(year, month, day)


def Time(hour, minute, second):
    return time(hour, minute, second)


def Timestamp(year, month, day, hour, minute, second):
    return Datetime(year, month, day, hour, minute, second)


def DateFromTicks(ticks):
    from time import localtime
    return Date(*localtime(ticks)[:3])


def TimeFromTicks(ticks):
    from time import localtime
    return Time(*localtime(ticks)[3:6])


def TimestampFromTicks(ticks):
    from time import localtime
    return Timestamp(*localtime(ticks)[:6])


def Binary(value):
    return value


FC_TEXT = 0
FC_BINARY = 1


J2000_OFFSET = 2451545

EPOCH = Datetime(2000, 1, 1)
EPOCH_TZ = EPOCH.replace(tzinfo=Timezone.utc)
EPOCH_SECONDS = timegm(EPOCH.timetuple())
INFINITY_MICROSECONDS = 2 ** 63 - 1
MINUS_INFINITY_MICROSECONDS = -1 * INFINITY_MICROSECONDS - 1


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


def timestamp_recv_float(data, offset, length):
    return Datetime.utcfromtimestamp(EPOCH_SECONDS + d_unpack(data, offset)[0])


def timestamp_send_integer(v):
    return q_pack(
        int((timegm(v.timetuple()) - EPOCH_SECONDS) * 1e6) + v.microsecond)


def timestamp_send_float(v):
    return d_pack(timegm(v.timetuple()) + v.microsecond / 1e6 - EPOCH_SECONDS)


def timestamptz_send_integer(v):
    return timestamp_send_integer(
        v.astimezone(Timezone.utc).replace(tzinfo=None))


def timestamptz_send_float(v):
    return timestamp_send_float(
        v.astimezone(Timezone.utc).replace(tzinfo=None))


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
    import re
    months = 0
    days = 0
    microseconds = 0

    s = s.strip()
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


def bytea_recv(data, offset, length):
    return data[offset:offset + length]


def uuid_send(v):
    return v.bytes


def uuid_recv(data, offset, length):
    from uuid import UUID
    return UUID(bytes=data[offset:offset + length])


def bool_send(v):
    return b"\x01" if v else b"\x00"


def null_send(v):
    from .protocol import NULL
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
    import re
    s = data[offset:offset + length].decode('utf-8')
    try:
        text = s.strip()
        if ' ' not in text:
            return Datetime(int(text[:4]), int(text[5:7]), int(text[8:10]), 0, 0, 0)

        if text.endswith((' UTC', ' utc')):
            text = text[:-4] + '+00:00'
        text = re.sub(r'([+-]\d{2})$', r'\1:00', text)
        text = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', text)
        value = Datetime.fromisoformat(text.replace(' ', 'T', 1))
        if value.tzinfo is None:
            return value
        return value.astimezone(Timezone.utc)
    except (ValueError, IndexError):
        return s


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
    time = int(time / 1000000)
    second = time % 60
    time = int(time / 60)
    minute = time % 60
    hour = int(time / 60)

    time_value.append(hour)
    time_value.append(minute)
    time_value.append(second)
    time_value.append(us)

    return time_value


def decimalToBinary(dec, bitmaplen):
    bin = []
    while bitmaplen != 0:
        remainder = dec % 2
        dec = dec // 2
        bin.append(remainder)
        bitmaplen -= 1
    return bin


def timestamp2struct(dt):
    ts = []
    date = int(dt // 86400000000)
    date0 = J2000_OFFSET

    time = dt % 86400000000

    if time < 0:
        time += 86400000000
        date -= 1

    if date < -date0:
        return False

    date += date0
    ts = j2date(date)
    fraction = (time % 1000000)

    time = int(time / 1000000)

    hour = int(time / 3600)
    time -= (hour * 3600)
    minute = int(time / 60)
    second = time - (minute * 60)

    ts.append(hour)
    ts.append(minute)
    ts.append(second)
    ts.append(fraction)

    return ts


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


def _abs(n):
    if n < 0:
        return -n
    else:
        return n


def EncodeTimeSpan(tm, fsec):
    is_nonzero = is_before = minus = False
    str = ""

    if tm[0] != 0:
        str = "{} year"
        str = str.format(tm[0])
        if _abs(tm[0]) != 1:
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

        if _abs(tm[1]) != 1:
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

        if _abs(tm[2]) != 1:
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
        str = str + str_hr_min.format(_abs(tm[3]), _abs(tm[4]))

        is_nonzero = True

        if fsec != 0:
            fsec += tm[5]
            str_hr_sec = ":{0:09.6f}"
            str = str + str_hr_sec.format(_abs(fsec))
            is_nonzero = True
        elif tm[5] != 0:
            str_hr_sec = ":{0:02d}"
            str = str + str_hr_sec.format(_abs(tm[5]))
            is_nonzero = True

    if not is_nonzero:
        str = str + "0"

    return str


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
        tz_hour = _abs(display_zone) // 3600
        tz_min = (_abs(display_zone) % 3600) // 60
        sign = '+' if display_zone > 0 else '-'

        if tz_min != 0:
            str_tz = "{0}{1:02d}:{2:02d}"
            str = str + str_tz.format(sign, tz_hour, tz_min)
        else:
            str_tz = "{0}{1:02d}"
            str = str + str_tz.format(sign, tz_hour)

    return str
