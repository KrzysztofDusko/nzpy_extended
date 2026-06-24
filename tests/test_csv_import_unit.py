"""Unit tests for nzpy_extended.csv_import helpers."""

from __future__ import annotations

import csv
import os
import tempfile

import pytest

from nzpy_extended.csv_import import _resolve_encoding, _sample_csv_rows
from nzpy_extended.exceptions import ProgrammingError

pytestmark = pytest.mark.unit


def test_resolve_encoding_utf8_variants() -> None:
    assert _resolve_encoding("UTF8") == "utf-8-sig"
    assert _resolve_encoding("utf-8") == "utf-8-sig"
    assert _resolve_encoding("LATIN9") == "LATIN9"


def test_sample_csv_rows_with_header() -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", newline="") as f:
        writer = csv.writer(f, delimiter="|")
        writer.writerow(["id", "name"])
        writer.writerow(["1", "alice"])
        writer.writerow(["2", "bob"])
        path = f.name
    try:
        rows, header = _sample_csv_rows(path, "|", True, 10, "UTF8")
        assert header == ["id", "name"]
        assert rows == [("1", "alice"), ("2", "bob")]
    finally:
        os.unlink(path)


def test_sample_csv_rows_empty_file_raises() -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", newline="") as f:
        path = f.name
    try:
        with pytest.raises(ProgrammingError, match="empty"):
            _sample_csv_rows(path, ",", True, 10, "UTF8")
    finally:
        os.unlink(path)


def test_sample_csv_rows_respects_sample_size() -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["a"])
        for i in range(10):
            writer.writerow([str(i)])
        path = f.name
    try:
        rows, header = _sample_csv_rows(path, ",", True, 3, "UTF8")
        assert header == ["a"]
        assert len(rows) == 3
    finally:
        os.unlink(path)
