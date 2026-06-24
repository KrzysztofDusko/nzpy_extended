from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Connection

from .exceptions import ProgrammingError
from .protocol import EXTERNAL_TABLE_STREAM_MARKER
from .utils import infer_columns_from_rows, rows_to_csv_chunks


_UTF8_VARIANTS = frozenset({'UTF8', 'UTF-8', 'UTF_8', 'utf8', 'utf-8', 'utf_8'})


def _resolve_encoding(encoding: str) -> str:
    """Use utf-8-sig when user specifies UTF-8 to auto-strip BOM."""
    return 'utf-8-sig' if encoding in _UTF8_VARIANTS else encoding


def _sample_csv_rows(
    path: str,
    delimiter: str,
    has_header: bool,
    sample_size: int,
    encoding: str = 'UTF8',
) -> tuple[list[tuple[str, ...]], list[str] | None]:
    """Return (data_rows, header) from the CSV file."""
    encoding = _resolve_encoding(encoding)
    rows: list[tuple[str, ...]] = []
    header: list[str] | None = None
    with open(path, newline='', encoding=encoding) as f:
        reader = csv.reader(f, delimiter=delimiter)
        if has_header:
            try:
                header = next(reader)
            except StopIteration:
                raise ProgrammingError("CSV file is empty") from None
        for row in reader:
            rows.append(tuple(row))
            if len(rows) >= sample_size:
                break
    return rows, header


def _csv_row_generator(path: str, delimiter: str, has_header: bool, encoding: str) -> Iterable[tuple[str, ...]]:
    """Read CSV rows one-by-one via csv.reader (handles quoting, multi-line fields)."""
    encoding = _resolve_encoding(encoding)
    with open(path, newline='', encoding=encoding) as f:
        reader = csv.reader(f, delimiter=delimiter)
        if has_header:
            try:
                next(reader)
            except StopIteration:
                return
        for row in reader:
            yield tuple(row)


async def load_csv(
    conn: Connection,
    table_name: str,
    csv_path: str,
    delimiter: str = ',',
    has_header: bool = True,
    sample_size: int = 1000,
    encoding: str = 'LATIN9',
    create_if_missing: bool = True,
    temporary: bool = False,
    distribute_on_random: bool = True,
    escape_char: str | None = '\\',
    logdir: str | None = None,
) -> int:
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    if logdir is None:
        logdir = tempfile.gettempdir()

    sample, header_names = _sample_csv_rows(csv_path, delimiter, has_header, sample_size, encoding)
    if not sample:
        raise ProgrammingError("No data rows found in CSV file")

    columns = infer_columns_from_rows(sample)
    if header_names and columns:
        if len(header_names) < len(columns):
            raise ProgrammingError(
                f"CSV header has {len(header_names)} column name(s) but "
                f"data has {len(columns)} column(s)"
            )
        columns = [
            (header_names[i], col_type)
            for i, (_, col_type) in enumerate(columns)
        ]

    if create_if_missing and columns:
        col_defs = ', '.join(f'{name} {nz_type}' for name, nz_type in columns)
        parts = ['CREATE']
        if temporary:
            parts.append('TEMP')
        parts.append(f'TABLE IF NOT EXISTS {table_name} ({col_defs})')
        if distribute_on_random:
            parts.append('DISTRIBUTE ON RANDOM')
        ddl = ' '.join(parts)
        cur = conn.cursor()
        await cur.execute(ddl)

    # The encoding for the Netezza EXTERNAL TABLE must match column types:
    #   VARCHAR → LATIN9, NVARCHAR/NCLOB → UTF8
    if columns is not None and any(t.startswith('NVARCHAR') or t.startswith('NCLOB') for _, t in columns):
        ext_encoding = 'UTF8'
    else:
        ext_encoding = 'LATIN9'

    # Stream: csv.reader → rows_to_csv_chunks (escapes delimiters, newlines,
    # carriage returns, and escape chars for Netezza ESCAPECHAR protocol)
    conn._ext_table_source = rows_to_csv_chunks(
        _csv_row_generator(csv_path, delimiter, has_header, encoding),
        delimiter=delimiter,
        encoding=ext_encoding,
        escape_char=escape_char,
        columns=columns,
    )

    using_opts = (
        f"ENCODING '{ext_encoding}' REMOTESOURCE 'python' DELIMITER '{delimiter}'"
    )
    if escape_char is not None:
        using_opts += f" ESCAPECHAR '{escape_char}'"
    if logdir is not None:
        using_opts += f" LOGDIR '{logdir}'"
    if columns is not None and any(t == 'BOOLEAN' for _, t in columns):
        using_opts += " BOOLSTYLE '1_0'"

    sql = (
        f"INSERT INTO {table_name} SELECT * "
        f"FROM EXTERNAL '{EXTERNAL_TABLE_STREAM_MARKER}' "
        f"SAMEAS {table_name} "
        f"USING ({using_opts})"
    )
    cur = conn.cursor()
    await cur.execute(sql)
    return cur.rowcount


__all__ = [
    "load_csv",
]
