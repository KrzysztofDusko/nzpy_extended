"""Document query execution path (extended query vs simple query)."""

from __future__ import annotations

import inspect

import pytest

import nzpy_extended.core as core

pytestmark = [pytest.mark.unit, pytest.mark.benchmark]


def test_execute_uses_simple_query_protocol() -> None:
    """Normal SQL execution uses PostgreSQL simple-query ('P') messages, not extended query."""
    source = inspect.getsource(core.Connection._execute)
    assert "b'P'" in source or 'b"P"' in source
    assert "PARSE" not in source.split("async def _execute")[1].split("async def")[0]
