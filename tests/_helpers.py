"""Shared helpers for ODBC parity and integration tests."""

from __future__ import annotations

import datetime
import decimal
import os
from typing import Any


def normalize(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, bool):
        return 't' if val else 'f'
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, datetime.timedelta):
        return str(val)
    if isinstance(val, decimal.Decimal):
        return str(val)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, bytes):
        try:
            return val.decode('utf-8').strip()
        except UnicodeDecodeError:
            return str(val)
    if isinstance(val, (list, tuple)):
        return ' '.join(str(v) for v in val)
    return str(val)


def _to_number(s: str) -> float | int | None:
    try:
        if '.' in s or 'e' in s or 'E' in s:
            return float(s)
        return int(s)
    except (ValueError, TypeError):
        return None


def compare_rows(nz_rows: list[Any], odbc_rows: list[Any], query: str) -> None:
    assert len(nz_rows) == len(odbc_rows), (
        f"Row count mismatch for {query!r}: nzpy={len(nz_rows)}, odbc={len(odbc_rows)}"
    )
    for row_idx, (n_row, o_row) in enumerate(zip(nz_rows, odbc_rows)):
        assert len(n_row) == len(o_row), (
            f"Column count mismatch row {row_idx}: nzpy={len(n_row)}, odbc={len(o_row)}"
        )
        for col_idx, (n_val, o_val) in enumerate(zip(n_row, o_row)):
            n_norm = normalize(n_val)
            o_norm = normalize(o_val)

            if n_norm is None and o_norm is None:
                continue
            if n_norm == o_norm:
                continue

            if isinstance(n_norm, str) and isinstance(o_norm, str):
                n_num = _to_number(n_norm)
                o_num = _to_number(o_norm)
                if n_num is not None and o_num is not None:
                    if n_num < 0 and o_num == n_num + 256:
                        continue
                    if (o_num == 2147483647 and n_num > o_num) or \
                       (o_num == -2147483648 and n_num < o_num):
                        continue
                    if abs(n_num - o_num) <= 1e-3 or \
                       abs(n_num - o_num) / max(1, abs(o_num)) <= 1e-3:
                        continue

                if len(n_norm) > len(o_norm) and o_norm and n_norm.startswith(o_norm):
                    continue

                try:
                    d_n = datetime.datetime.fromisoformat(n_norm)
                    d_o = datetime.datetime.fromisoformat(o_norm)
                    if abs((d_n - d_o).total_seconds()) < 5:
                        continue
                except (ValueError, TypeError):
                    pass

            assert n_norm == o_norm, (
                f"Row {row_idx} Col {col_idx}: nzpy={n_val!r} odbc={o_val!r}"
            )


def odbc_skip_literal_date(query: str) -> bool:
    if os.name != "nt":
        return False
    stripped = query.strip().upper()
    if stripped.startswith("SELECT '") and ("::DATE" in stripped or "::TIME" in stripped):
        if "FROM" not in stripped:
            return True
    return False
