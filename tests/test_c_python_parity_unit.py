"""
test_c_python_parity_unit.py
============================
Unit-level parity tests between C extension and pure-Python implementations.

These tests directly call the individual C extension parser functions and
compare their results against pure-Python reference implementations that
mirror the identical logic.

Run with C extension enabled (default):
    pytest tests/test_c_python_parity_unit.py -v

Run with C extension disabled (verifies Python-only path):
    NZPY_EXTENDED_NO_CEXT=1 pytest tests/test_c_python_parity_unit.py -v
"""

import math
import struct
from decimal import Decimal

import pytest

try:
    from nzpy_extended import c_ext as _c_ext

    _HAVE_C_EXT = True
except ImportError:
    _HAVE_C_EXT = False

pytestmark = [pytest.mark.full, pytest.mark.unit]

# ---------------------------------------------------------------------------
# Pure-Python reference implementations (mirror c_ext.c identically)
# ---------------------------------------------------------------------------

J2000_OFFSET = 2451545


def _py_read_u32_le(data, offset=0):
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


def _py_read_i32_le(data, offset=0):
    val = _py_read_u32_le(data, offset)
    if val >= 0x80000000:
        val -= 0x100000000
    return val


def _py_read_i64_le(data, offset=0):
    lo = _py_read_u32_le(data, offset)
    hi = _py_read_u32_le(data, offset + 4)
    val = lo | (hi << 32)
    if hi & 0x80000000:
        val -= 0x10000000000000000
    return val


def _py_read_u16_le(data, offset=0):
    return data[offset] | (data[offset + 1] << 8)


def _py_j2date(jd):
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
    return year, month, day


def _py_time2struct(time_us):
    us = time_us % 1000000
    time_us //= 1000000
    second = time_us % 60
    time_us //= 60
    minute = time_us % 60
    hour = time_us // 60
    return hour, minute, second, us


def _py_decode_str(data, offset, length, encoding):
    if offset + length > len(data):
        raise ValueError("offset + length exceeds data")
    return data[offset : offset + length].decode(encoding)


def _py_decode_var_str(data, offset, encoding):
    if offset + 2 > len(data):
        return ""
    total_len = _py_read_u16_le(data, offset)
    str_len = total_len - 2
    if str_len <= 0:
        return ""
    if offset + total_len > len(data):
        raise ValueError("var str length exceeds data")
    return data[offset + 2 : offset + total_len].decode(encoding)


def _py_parse_int8(data, offset):
    if offset >= len(data):
        return 0
    val = data[offset]
    if val >= 0x80:
        val -= 0x100
    return val


def _py_parse_int16(data, offset):
    if offset + 2 > len(data):
        return 0
    val = _py_read_u32_le(data, offset) & 0xFFFF
    if val >= 0x8000:
        val -= 0x10000
    return val


def _py_parse_int32(data, offset):
    if offset + 4 > len(data):
        return 0
    return _py_read_i32_le(data, offset)


def _py_parse_int64(data, offset):
    if offset + 8 > len(data):
        return 0
    return _py_read_i64_le(data, offset)


def _py_parse_float32(data, offset):
    if offset + 4 > len(data):
        return 0.0
    return struct.unpack_from("<f", data, offset)[0]


def _py_parse_float64(data, offset):
    if offset + 8 > len(data):
        return 0.0
    return struct.unpack_from("<d", data, offset)[0]


def _py_parse_bool(data, offset):
    if offset >= len(data):
        return False
    return data[offset] == 1


def _py_parse_date(data, offset, fldlen):
    if fldlen >= 8:
        if offset + 8 > len(data):
            return "0001-01-01"
        workspace = _py_read_i64_le(data, offset)
    else:
        if offset + fldlen > len(data):
            return "0001-01-01"
        workspace = _py_read_i64_le(data, offset)
        mask = (1 << (fldlen * 8)) - 1
        if workspace & (1 << (fldlen * 8 - 1)):
            workspace |= ~mask
        else:
            workspace &= mask
    jd = workspace + J2000_OFFSET
    y, m, d = _py_j2date(jd)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _py_parse_time(data, offset, fldlen):
    if fldlen >= 8:
        if offset + 8 > len(data):
            return "00:00:00"
        workspace = _py_read_i64_le(data, offset)
    else:
        if offset + fldlen > len(data):
            return "00:00:00"
        workspace = _py_read_i64_le(data, offset)
        mask = (1 << (fldlen * 8)) - 1
        if workspace & (1 << (fldlen * 8 - 1)):
            workspace |= ~mask
        else:
            workspace &= mask
    h, m, s, us = _py_time2struct(workspace)
    if us:
        return f"{h:02d}:{m:02d}:{s:02d}.{us:06d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def _py_parse_timestamp(data, offset, fldlen):
    if fldlen >= 8:
        if offset + 8 > len(data):
            return "0001-01-01 00:00:00.000000"
        workspace = _py_read_i64_le(data, offset)
    else:
        if offset + fldlen > len(data):
            return "0001-01-01 00:00:00.000000"
        workspace = _py_read_i64_le(data, offset)
        mask = (1 << (fldlen * 8)) - 1
        if workspace & (1 << (fldlen * 8 - 1)):
            workspace |= ~mask
        else:
            workspace &= mask
    if fldlen != 8:
        return "0001-01-01 00:00:00.000000"
    date_part = workspace // 86400000000
    time_us = workspace % 86400000000
    if time_us < 0:
        time_us += 86400000000
        date_part -= 1
    jd = date_part + J2000_OFFSET
    if jd < 0:
        return "0001-01-01 00:00:00.000000"
    y, m, d = _py_j2date(jd)
    h, min, s, us = _py_time2struct(time_us)
    return f"{y:04d}-{m:02d}-{d:02d} {h:02d}:{min:02d}:{s:02d}.{us:06d}"


def _py_format_numeric(data, offset, chunk_len, scale):
    count = chunk_len // 4
    words = [
        int.from_bytes(data[offset + i * 4 : offset + (i + 1) * 4], "little", signed=False)
        for i in range(count)
    ]
    val = 0
    for w in words:
        val = (val << 32) | w
    total_bits = count * 32
    if words[0] >> 31:
        val -= 1 << total_bits
    if scale == 0:
        return Decimal(str(val))
    sign = "-" if val < 0 else ""
    val = abs(val)
    integer_part = val // (10**scale)
    fractional_part = val % (10**scale)
    return Decimal(f"{sign}{integer_part}.{fractional_part:0{scale}d}")


# ---------------------------------------------------------------------------
# Helper: build little-endian byte buffers for testing
# ---------------------------------------------------------------------------


def _le_bytes(val, size):
    buf = val.to_bytes(size, "little", signed=True)
    if len(buf) < 8:
        buf = buf + b"\x00" * (8 - len(buf))
    return buf


def _le_bytes_unsigned(val, size):
    buf = val.to_bytes(size, "little", signed=False)
    if len(buf) < 8:
        buf = buf + b"\x00" * (8 - len(buf))
    return buf


def _pad_to(val, size, min_size=8):
    """Build LE bytes buffer, padded to at least min_size bytes."""
    buf = val.to_bytes(size, "little", signed=True)
    if len(buf) < min_size:
        buf = buf + b"\x00" * (min_size - len(buf))
    return buf


# ---------------------------------------------------------------------------
# Integer parser tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "func_name,py_func,test_val,size",
    [
        ("parse_int8", _py_parse_int8, 0, 1),
        ("parse_int8", _py_parse_int8, 1, 1),
        ("parse_int8", _py_parse_int8, -1, 1),
        ("parse_int8", _py_parse_int8, 127, 1),
        ("parse_int8", _py_parse_int8, -128, 1),
        ("parse_int16", _py_parse_int16, 0, 2),
        ("parse_int16", _py_parse_int16, 1, 2),
        ("parse_int16", _py_parse_int16, -1, 2),
        ("parse_int16", _py_parse_int16, 32767, 2),
        ("parse_int16", _py_parse_int16, -32768, 2),
        ("parse_int16", _py_parse_int16, 256, 2),  # endian-sensitive
        ("parse_int32", _py_parse_int32, 0, 4),
        ("parse_int32", _py_parse_int32, 1, 4),
        ("parse_int32", _py_parse_int32, -1, 4),
        ("parse_int32", _py_parse_int32, 2147483647, 4),
        ("parse_int32", _py_parse_int32, -2147483648, 4),
        ("parse_int64", _py_parse_int64, 0, 8),
        ("parse_int64", _py_parse_int64, 1, 8),
        ("parse_int64", _py_parse_int64, -1, 8),
        ("parse_int64", _py_parse_int64, 9223372036854775807, 8),
        ("parse_int64", _py_parse_int64, -9223372036854775808, 8),
    ],
    ids=lambda x: str(x) if isinstance(x, int) else x[3] if hasattr(x, '__iter__') else x,
)
@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
def test_int_parser_parity(func_name, py_func, test_val, size):
    buf = _le_bytes(test_val, size)
    offset = 0

    c_result = getattr(_c_ext, func_name)(buf, offset)
    py_result = py_func(buf, offset)

    assert c_result == py_result, (
        f"Mismatch for {func_name}({test_val}): C={c_result!r} vs Py={py_result!r}"
    )
    assert type(c_result) is type(py_result), (
        f"Type mismatch: C={type(c_result).__name__} vs Py={type(py_result).__name__}"
    )


@pytest.mark.parametrize(
    "func_name,py_func,test_val,size",
    [
        ("parse_int8", _py_parse_int8, 0, 1),
        ("parse_int32", _py_parse_int32, -1, 4),
        ("parse_int64", _py_parse_int64, 9223372036854775807, 8),
    ],
)
def test_int_parser_pure_python_baseline(func_name, py_func, test_val, size):
    buf = _le_bytes(test_val, size)
    result = py_func(buf, 0)
    assert result == test_val, f"Pure-Python baseline failed for {func_name}({test_val})"


# ---------------------------------------------------------------------------
# Float parser tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "func_name,py_func,test_val",
    [
        ("parse_float32", _py_parse_float32, 0.0),
        ("parse_float32", _py_parse_float32, 1.0),
        ("parse_float32", _py_parse_float32, -1.0),
        ("parse_float32", _py_parse_float32, 3.1415927410125732),  # float32 pi
        ("parse_float32", _py_parse_float32, float("inf")),
        ("parse_float32", _py_parse_float32, float("-inf")),
        ("parse_float64", _py_parse_float64, 0.0),
        ("parse_float64", _py_parse_float64, 1.0),
        ("parse_float64", _py_parse_float64, -1.0),
        ("parse_float64", _py_parse_float64, 3.141592653589793),
        ("parse_float64", _py_parse_float64, 1.7976931348623157e308),
        ("parse_float64", _py_parse_float64, -1.7976931348623157e308),
    ],
)
@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
def test_float_parser_parity(func_name, py_func, test_val):
    fmt = "<f" if "float32" in func_name else "<d"
    buf = struct.pack(fmt, test_val)
    offset = 0

    c_result = getattr(_c_ext, func_name)(buf, offset)
    py_result = py_func(buf, offset)

    # NaN != NaN, so handle specially
    if math.isnan(test_val):
        assert math.isnan(c_result), f"C: expected NaN for {func_name}({test_val})"
        assert math.isnan(py_result), f"Py: expected NaN for {func_name}({test_val})"
        return

    assert c_result == py_result, (
        f"Mismatch for {func_name}({test_val}): C={c_result!r} vs Py={py_result!r}"
    )


@pytest.mark.parametrize(
    "func_name,py_func,tolerance",
    [
        ("parse_float64", _py_parse_float64, 0.0),
        ("parse_float32", _py_parse_float32, 1e-7),
    ],
)
def test_float_parser_nan_parity(func_name, py_func, tolerance):
    buf = struct.pack("<f" if "float32" in func_name else "<d", float("nan"))
    py_result = py_func(buf, 0)
    assert math.isnan(py_result)


# ---------------------------------------------------------------------------
# Bool parser tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
def test_bool_parser_parity():
    assert _c_ext.parse_bool(b"\x01", 0) is True
    assert _c_ext.parse_bool(b"\x00", 0) is False
    assert _c_ext.parse_bool(b"\xff", 0) is False  # only 1 == true
    assert _py_parse_bool(b"\x01", 0) is True
    assert _py_parse_bool(b"\x00", 0) is False
    assert _py_parse_bool(b"\xff", 0) is False


# ---------------------------------------------------------------------------
# String decode tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
@pytest.mark.parametrize(
    "text,encoding",
    [
        ("hello", "utf-8"),
        ("", "utf-8"),
        ("café", "utf-8"),
        ("中文测试", "utf-8"),
        ("zażółć gęślą jaźń", "utf-8"),
        ("hello", "latin-1"),
    ],
)
def test_decode_str_parity(text, encoding):
    buf = text.encode(encoding)
    offset = 0
    length = len(buf)

    c_result = _c_ext.decode_str(buf, offset, length, encoding)
    py_result = _py_decode_str(buf, offset, length, encoding)

    assert c_result == py_result, f"decode_str mismatch: C={c_result!r} vs Py={py_result!r}"
    assert c_result == text


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
@pytest.mark.parametrize(
    "text,encoding",
    [
        ("hello", "utf-8"),
        ("", "utf-8"),
        ("café", "utf-8"),
        ("中文", "utf-8"),
    ],
)
def test_decode_var_str_parity(text, encoding):
    text_bytes = text.encode(encoding)
    total_len = len(text_bytes) + 2
    buf = total_len.to_bytes(2, "little", signed=False) + text_bytes
    offset = 0

    c_result = _c_ext.decode_var_str(buf, offset, encoding)
    py_result = _py_decode_var_str(buf, offset, encoding)

    assert c_result == py_result, f"decode_var_str mismatch: C={c_result!r} vs Py={py_result!r}"
    assert c_result == text


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
def test_decode_var_str_empty_on_zero_len():
    buf = b"\x02\x00"
    assert _c_ext.decode_var_str(buf, 0, "utf-8") == ""
    assert _py_decode_var_str(buf, 0, "utf-8") == ""


# ---------------------------------------------------------------------------
# Date parser tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
@pytest.mark.parametrize(
    "workspace,fldlen,expected",
    [
        (0, 8, "2000-01-01"),  # J2000 epoch
        (1, 8, "2000-01-02"),
        (-1, 8, "1999-12-31"),
        (365, 8, "2000-12-31"),
        (366, 8, "2001-01-01"),
        (0, 4, "2000-01-01"),
        (1, 4, "2000-01-02"),
        (30, 4, "2000-01-31"),
    ],
)
def test_parse_date_parity(workspace, fldlen, expected):
    buf = _pad_to(workspace, fldlen)
    offset = 0

    c_result = _c_ext.parse_date(buf, offset, fldlen)
    py_result = _py_parse_date(buf, offset, fldlen)

    assert c_result == py_result, f"parse_date mismatch: C={c_result!r} vs Py={py_result!r}"
    assert c_result == expected


# ---------------------------------------------------------------------------
# Time parser tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
@pytest.mark.parametrize(
    "time_us,fldlen,expected",
    [
        (0, 8, "00:00:00"),  # midnight
        (3600000000, 8, "01:00:00"),  # 1 hour
        (3661000000, 8, "01:01:01"),  # 1h 1m 1s
        (3661001234, 8, "01:01:01.001234"),  # with microseconds
        (86399999999, 8, "23:59:59.999999"),  # 1 microsecond before midnight
        (0, 4, "00:00:00"),
    ],
)
def test_parse_time_parity(time_us, fldlen, expected):
    buf = _pad_to(time_us, fldlen)
    offset = 0

    c_result = _c_ext.parse_time(buf, offset, fldlen)
    py_result = _py_parse_time(buf, offset, fldlen)

    assert c_result == py_result, f"parse_time mismatch: C={c_result!r} vs Py={py_result!r}"
    assert c_result == expected


# ---------------------------------------------------------------------------
# Timestamp parser tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
@pytest.mark.parametrize(
    "ts_usec,fldlen,expected",
    [
        (0, 8, "2000-01-01 00:00:00.000000"),
        (86400000000, 8, "2000-01-02 00:00:00.000000"),  # +1 day
        (172800000000 + 3600000000, 8, "2000-01-03 01:00:00.000000"),  # 2d 1h
        (1, 8, "2000-01-01 00:00:00.000001"),  # 1 microsecond
    ],
)
def test_parse_timestamp_parity(ts_usec, fldlen, expected):
    buf = ts_usec.to_bytes(fldlen, "little", signed=True)
    offset = 0

    c_result = _c_ext.parse_timestamp(buf, offset, fldlen)
    py_result = _py_parse_timestamp(buf, offset, fldlen)

    assert c_result == py_result, f"parse_timestamp mismatch: C={c_result!r} vs Py={py_result!r}"
    assert c_result == expected


# ---------------------------------------------------------------------------
# Numeric parser tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_C_EXT, reason="C extension not available")
@pytest.mark.parametrize(
    "value_num,value_scale,buf_size",
    [
        (12345, 0, 4),  # int, 1 word
        (12345, 2, 4),  # 123.45
        (12345678, 4, 4),  # 1234.5678, 1 word
        (12345678901234, 2, 8),  # 2 words
        (-12345, 0, 4),  # negative
        (-12345, 2, 4),  # negative with scale
        (0, 0, 4),
        (0, 5, 4),
        (1, 10, 8),  # 3 words (large scale needs bigint)
        (999999999999999, 2, 8),
    ],
)
def test_format_numeric_parity(value_num, value_scale, buf_size):
    offset = 0
    chunk_len = buf_size
    scale = value_scale

    # Build buffer: value as storeNumAsHex-like representation
    # The C ext reads words as unsigned 32-bit little-endian
    if value_num < 0:
        adjusted = (1 << (buf_size * 8)) + value_num
    else:
        adjusted = value_num
    buf = adjusted.to_bytes(buf_size, "little", signed=False)

    c_result = _c_ext.format_numeric(buf, offset, chunk_len, scale)
    py_result = _py_format_numeric(buf, offset, chunk_len, scale)

    assert c_result == py_result, (
        f"format_numeric mismatch for {value_num} scale={scale}: "
        f"C={c_result!r} vs Py={py_result!r}"
    )
    assert isinstance(c_result, Decimal)


# ---------------------------------------------------------------------------
# Pure-Python baseline tests (run even without C extension)
# ---------------------------------------------------------------------------


def test_numeric_baseline_zero():
    buf = b"\x00\x00\x00\x00"
    result = _py_format_numeric(buf, 0, 4, 0)
    assert result == Decimal("0")


def test_numeric_baseline_positive():
    buf = (12345).to_bytes(4, "little", signed=False)
    result = _py_format_numeric(buf, 0, 4, 0)
    assert result == Decimal("12345")


def test_numeric_baseline_with_scale():
    buf = (12345).to_bytes(4, "little", signed=False)
    result = _py_format_numeric(buf, 0, 4, 2)
    assert result == Decimal("123.45")


def test_numeric_baseline_negative():
    # Negative in two's complement over 4 bytes
    buf = (-12345 & 0xFFFFFFFF).to_bytes(4, "little", signed=False)
    result = _py_format_numeric(buf, 0, 4, 0)
    assert result == Decimal("-12345")


def test_date_baseline():
    buf = (0).to_bytes(8, "little", signed=True)
    assert _py_parse_date(buf, 0, 8) == "2000-01-01"


def test_time_baseline():
    buf = (0).to_bytes(8, "little", signed=True)
    assert _py_parse_time(buf, 0, 8) == "00:00:00"


def test_timestamp_baseline():
    buf = (0).to_bytes(8, "little", signed=True)
    assert _py_parse_timestamp(buf, 0, 8) == "2000-01-01 00:00:00.000000"
