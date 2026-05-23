import datetime
import enum
import re
from decimal import Decimal
from json import dumps
from struct import Struct
from uuid import UUID

from .exceptions import (InterfaceError, ProgrammingError,
                         ArrayContentNotHomogenousError,
                         ArrayContentNotSupportedError,
                         ArrayDimensionsNotConsistentError)


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

min_int2, max_int2 = -2 ** 15, 2 ** 15
min_int4, max_int4 = -2 ** 31, 2 ** 31
min_int8, max_int8 = -2 ** 63, 2 ** 63


def _quote_text_literal(value):
    return "'" + value.replace("'", "''") + "'"


def convert_paramstyle(style, query):
    OUTSIDE = 0
    INSIDE_SQ = 1
    INSIDE_QI = 2
    INSIDE_ES = 3
    INSIDE_CO = 4

    output_query = []
    state = OUTSIDE
    prev_c = None
    i = 0
    positional_count = 0
    ordered_names = []
    name_to_index = {}

    def remember_name(name):
        if name not in name_to_index:
            name_to_index[name] = len(ordered_names) + 1
            ordered_names.append(name)
        return name_to_index[name]

    while i < len(query):
        c = query[i]
        next_c = query[i + 1] if i + 1 < len(query) else None

        if state == OUTSIDE:
            if c == "'":
                output_query.append(c)
                state = INSIDE_ES if prev_c == 'E' else INSIDE_SQ
                prev_c = c
                i += 1
                continue
            if c == '"':
                output_query.append(c)
                state = INSIDE_QI
                prev_c = c
                i += 1
                continue
            if c == '-' and next_c == '-':
                output_query.extend((c, next_c))
                state = INSIDE_CO
                prev_c = next_c
                i += 2
                continue
            if style == "qmark" and c == "?":
                positional_count += 1
                output_query.append(f"${positional_count}")
                prev_c = c
                i += 1
                continue
            if style == "numeric" and c == ":" and next_c is not None and next_c.isdigit() and prev_c != ":":
                j = i + 1
                while j < len(query) and query[j].isdigit():
                    j += 1
                output_query.append("$" + query[i + 1:j])
                prev_c = query[j - 1]
                i = j
                continue
            if style == "named" and c == ":" and next_c is not None and (next_c.isalpha() or next_c == "_") and prev_c != ":":
                j = i + 1
                while j < len(query) and (query[j].isalnum() or query[j] == "_"):
                    j += 1
                name = query[i + 1:j]
                output_query.append(f"${remember_name(name)}")
                prev_c = query[j - 1]
                i = j
                continue
            if style == "pyformat" and c == "%" and next_c == "(":
                j = i + 2
                while j < len(query) and (query[j].isalnum() or query[j] == "_"):
                    j += 1
                name = query[i + 2:j]
                if not name or j + 1 >= len(query) or query[j] != ")" or query[j + 1] != "s":
                    raise InterfaceError("Only %(name)s and %% are supported in the query.")
                output_query.append(f"${remember_name(name)}")
                prev_c = "s"
                i = j + 2
                continue
            if style in ("format", "pyformat") and c == "%":
                if next_c == "%":
                    output_query.extend((c, next_c))
                    prev_c = next_c
                    i += 2
                    continue
                if next_c == "s":
                    positional_count += 1
                    output_query.append(f"${positional_count}")
                    prev_c = next_c
                    i += 2
                    continue
                raise InterfaceError("Only %s and %% are supported in the query.")

            output_query.append(c)

        elif state == INSIDE_SQ:
            output_query.append(c)
            if c == "'":
                if next_c == "'":
                    output_query.append(next_c)
                    prev_c = next_c
                    i += 2
                    continue
                state = OUTSIDE

        elif state == INSIDE_QI:
            output_query.append(c)
            if c == '"':
                state = OUTSIDE

        elif state == INSIDE_ES:
            output_query.append(c)
            if c == "'" and prev_c != "\\":
                state = OUTSIDE

        elif state == INSIDE_CO:
            output_query.append(c)
            if c == "\n":
                state = OUTSIDE

        prev_c = c
        i += 1

    def make_args(vals):
        if vals is None:
            return ()
        if style in ("named", "pyformat") and ordered_names:
            try:
                return tuple(vals[name] for name in ordered_names)
            except KeyError as exc:
                raise ProgrammingError(f"Missing value for parameter '{exc.args[0]}'") from exc
            except TypeError as exc:
                raise ProgrammingError("Named parameters require a mapping.") from exc
        if isinstance(vals, tuple):
            return vals
        if isinstance(vals, list):
            return tuple(vals)
        if isinstance(vals, dict):
            raise ProgrammingError("Positional parameters require a sequence, not a mapping.")
        try:
            return tuple(vals)
        except TypeError:
            return (vals,)

    return ''.join(output_query), make_args


def _sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, datetime.datetime):
        return _quote_text_literal(value.isoformat(sep=" "))
    if isinstance(value, datetime.date):
        return _quote_text_literal(value.isoformat())
    if isinstance(value, datetime.time):
        return _quote_text_literal(value.isoformat())
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"x'{bytes(value).hex()}'"
    if isinstance(value, UUID):
        return _quote_text_literal(str(value))
    if isinstance(value, enum.Enum):
        return _quote_text_literal(str(value.value))
    if isinstance(value, dict):
        return _quote_text_literal(dumps(value))
    if isinstance(value, (list, tuple)):
        return "ARRAY[" + ", ".join(_sql_literal(item) for item in value) + "]"
    return _quote_text_literal(str(value))


def _render_prepared_statement(statement, args):
    OUTSIDE = 0
    INSIDE_SQ = 1
    INSIDE_QI = 2
    INSIDE_ES = 3
    INSIDE_CO = 4

    output_query = []
    state = OUTSIDE
    prev_c = None
    i = 0
    max_index = 0

    while i < len(statement):
        c = statement[i]
        next_c = statement[i + 1] if i + 1 < len(statement) else None

        if state == OUTSIDE:
            if c == "'":
                output_query.append(c)
                state = INSIDE_ES if prev_c == 'E' else INSIDE_SQ
                prev_c = c
                i += 1
                continue
            if c == '"':
                output_query.append(c)
                state = INSIDE_QI
                prev_c = c
                i += 1
                continue
            if c == '-' and next_c == '-':
                output_query.extend((c, next_c))
                state = INSIDE_CO
                prev_c = next_c
                i += 2
                continue
            if c == "$" and next_c is not None and next_c.isdigit():
                j = i + 1
                while j < len(statement) and statement[j].isdigit():
                    j += 1
                param_index = int(statement[i + 1:j])
                if param_index <= 0 or param_index > len(args):
                    raise ProgrammingError(
                        f"Statement requires parameter ${param_index}, but only {len(args)} values were supplied."
                    )
                max_index = max(max_index, param_index)
                output_query.append(_sql_literal(args[param_index - 1]))
                prev_c = statement[j - 1]
                i = j
                continue
            output_query.append(c)

        elif state == INSIDE_SQ:
            output_query.append(c)
            if c == "'":
                if next_c == "'":
                    output_query.append(next_c)
                    prev_c = next_c
                    i += 2
                    continue
                state = OUTSIDE

        elif state == INSIDE_QI:
            output_query.append(c)
            if c == '"':
                state = OUTSIDE

        elif state == INSIDE_ES:
            output_query.append(c)
            if c == "'" and prev_c != "\\":
                state = OUTSIDE

        elif state == INSIDE_CO:
            output_query.append(c)
            if c == "\n":
                state = OUTSIDE

        prev_c = c
        i += 1

    return ''.join(output_query), max_index


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


pg_array_types = {
    16: 1000,
    25: 1009,
    701: 1022,
    1043: 1009,
    1700: 1231,
}

pg_to_py_encodings = {
    "mule_internal": None,
    "euc_tw": None,
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
    "unicode": "utf-8",
}


_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TIME_RE = re.compile(r'^\d{2}:\d{2}:\d{2}$')
_TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
_INT_RE = re.compile(r'^-?\d+$')
_FLOAT_RE = re.compile(r'^-?\d+\.?\d*(?:[eE][+-]?\d+)?$')
_BOOL_RE = re.compile(r'^(true|false|t|f|0|1|yes|no)$', re.IGNORECASE)


def _infer_nz_type(val):
    if val is None:
        return 'VARCHAR(255)'
    if isinstance(val, bool):
        return 'BOOLEAN'
    if isinstance(val, int):
        if -32768 <= val <= 32767:
            return 'SMALLINT'
        if -2147483648 <= val <= 2147483647:
            return 'INT'
        return 'BIGINT'
    if isinstance(val, float):
        return 'FLOAT'
    if isinstance(val, Decimal):
        sign, digits, exponent = val.as_tuple()
        precision = len(digits)
        scale = max(0, -exponent)
        precision = min(max(precision, 1), 38)
        return f'NUMERIC({precision},{scale})'
    if isinstance(val, datetime.datetime):
        return 'TIMESTAMP'
    if isinstance(val, datetime.date):
        return 'DATE'
    if isinstance(val, datetime.time):
        return 'TIME'
    if isinstance(val, (bytes, bytearray)):
        return 'BYTEA'
    s = str(val)
    max_len = max(len(s), 1)
    if max_len <= 255:
        return 'VARCHAR(255)'
    if max_len <= 65535:
        return 'VARCHAR(65535)'
    return 'CLOB'


def _infer_type_from_strings(str_vals):
    non_empty = [s for s in str_vals if s and s.strip()]
    if not non_empty:
        return 'VARCHAR(255)'

    stripped = [s.strip() for s in non_empty]
    lowers = [s.lower() for s in stripped]

    # Boolean detection — only if at least one explicit bool keyword present
    # (0/1 alone are treated as integers, not booleans)
    bool_keywords = {'true', 'false', 't', 'f', 'yes', 'no'}
    has_bool_keyword = any(s in bool_keywords for s in lowers)
    if has_bool_keyword and all(s in {'true', 'false', 't', 'f', '0', '1', 'yes', 'no'} for s in lowers):
        return 'BOOLEAN'

    # Integer detection — reject values with leading zeros (data preservation)
    if all(_INT_RE.match(s) for s in stripped):
        has_leading_zero = any(
            len(s.lstrip('-+')) > 1 and s.lstrip('-+')[0] == '0'
            for s in stripped
        )
        if not has_leading_zero:
            ints = [int(s) for s in stripped]
            min_v, max_v = min(ints), max(ints)
            if -32768 <= min_v and max_v <= 32767:
                return 'SMALLINT'
            if -2147483648 <= min_v and max_v <= 2147483647:
                return 'INT'
            return 'BIGINT'

    # Date detection
    if all(_DATE_RE.match(s) for s in stripped):
        try:
            for s in stripped:
                datetime.datetime.strptime(s, '%Y-%m-%d')
            return 'DATE'
        except ValueError:
            pass

    # Time detection
    if all(_TIME_RE.match(s) for s in stripped):
        return 'TIME'

    # Timestamp detection
    if all(_TIMESTAMP_RE.match(s) for s in stripped):
        try:
            for s in stripped:
                datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
            return 'TIMESTAMP'
        except ValueError:
            pass

    # Numeric (Decimal) detection — values with explicit decimal point(s)
    has_dot = any('.' in s for s in stripped)
    if has_dot and all(_FLOAT_RE.match(s) for s in stripped):
        max_int_digits = 0
        max_scale = 0
        for s in stripped:
            raw = s.lstrip('-+')
            if '.' in raw:
                int_part, frac_part = raw.split('.')
            else:
                int_part, frac_part = raw, ''
            int_digits = len(int_part.lstrip('0') or '0')
            scale = len(frac_part)
            max_int_digits = max(max_int_digits, int_digits)
            max_scale = max(max_scale, scale)
        precision = max(max_int_digits + max_scale, 1)
        precision = min(precision, 38)
        max_scale = min(max_scale, precision)
        return f'NUMERIC({precision},{max_scale})'

    has_unicode = any(ord(c) > 127 for s in str_vals for c in s)
    max_len = max(len(s) for s in str_vals)
    if has_unicode:
        if max_len <= 255:
            return 'NVARCHAR(255)'
        if max_len <= 65535:
            return 'NVARCHAR(65535)'
        return 'NCLOB'
    if max_len <= 255:
        return 'VARCHAR(255)'
    if max_len <= 65535:
        return 'VARCHAR(65535)'
    return 'CLOB'


def _infer_columns_from_rows(rows):
    if not rows:
        return []
    ncols = len(rows[0])
    columns = []
    for i in range(ncols):
        col_vals = [row[i] for row in rows]
        non_null = [v for v in col_vals if v is not None]

        if not non_null:
            col_type = 'VARCHAR(255)'
        elif all(isinstance(v, str) for v in non_null):
            col_type = _infer_type_from_strings([str(v) for v in non_null])
        else:
            types = set(type(v) for v in non_null)
            if len(types) == 1:
                col_type = _infer_nz_type(non_null[0])
            elif any(isinstance(v, float) for v in non_null):
                col_type = 'FLOAT'
            elif any(isinstance(v, Decimal) for v in non_null):
                col_type = 'FLOAT'
            else:
                max_len = max(len(str(v)) for v in non_null)
                col_type = f'VARCHAR({max(max_len, 1)})'

        columns.append((f'col{i + 1}', col_type))
    return columns


def _rows_to_csv_bytes(rows, delimiter='|', encoding='latin-1', escape_char='\\',
                       columns=None):
    parts = []
    for row in rows:
        fields = []
        for i, val in enumerate(row):
            if val is None:
                fields.append('')
            elif isinstance(val, bool):
                fields.append('1' if val else '0')
            elif (isinstance(val, str) and columns is not None
                  and i < len(columns) and columns[i][1] == 'BOOLEAN'):
                fields.append('1' if val.lower() in ('true', 't', 'yes', '1') else '0')
            else:
                s = str(val)
                if escape_char is not None and delimiter in s:
                    s = s.replace(delimiter, escape_char + delimiter)
                fields.append(s)
        parts.append(delimiter.join(fields))
    return ('\n'.join(parts) + '\n').encode(encoding)
