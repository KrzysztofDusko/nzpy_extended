"""Unit tests for pool acquire / validation behaviour (no live DB)."""

from __future__ import annotations

import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nzpy_extended.pool import NzPool, SyncPool, _PooledConnection

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_nzpool_discards_invalid_pooled_connection() -> None:
    pool = NzPool(min_size=0, max_size=2)
    conn = MagicMock()
    now = time.monotonic()
    pool._pool.append(_PooledConnection(conn, now, now, 0))
    pool._created = 1

    pool._validate_connection = AsyncMock(return_value=False)  # type: ignore[method-assign]
    pool._close_connection = AsyncMock()  # type: ignore[method-assign]

    with patch.object(pool, "_create_new_connection", side_effect=RuntimeError("no db")):
        with pytest.raises(RuntimeError, match="no db"):
            await pool.acquire()

    assert pool._created == 0
    assert len(pool._pool) == 0
    assert len(pool._reserving) == 0
    pool._close_connection.assert_awaited_once()


def test_syncpool_validate_runs_outside_lock() -> None:
    lock_held_during_validate: list[bool] = []
    pool = SyncPool.__new__(SyncPool)
    pool._closed = False
    pool.min_size = 0
    pool.max_size = 2
    pool.acquire_timeout = 1.0
    pool.on_connect = None
    pool._kwargs = {}
    pool._pool = __import__("collections").deque()
    pool._lock = threading.Lock()
    pool._sem = threading.Semaphore(2)
    pool._created = 0
    pool._checked_out = set()
    pool._checked_out_pc = {}
    pool._log = __import__("logging").getLogger("test")
    pool._stop_event = threading.Event()
    pool._maintain_thread = threading.Thread(target=lambda: None, daemon=True)

    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    from nzpy_extended.pool import _SyncPooledConnection

    now = time.monotonic()
    pool._pool.append(_SyncPooledConnection(mock_conn, now, now, 0))
    pool._created = 1

    original_validate = SyncPool._validate_connection

    def tracking_validate(self, pc):  # type: ignore[no-untyped-def]
        lock_held_during_validate.append(self._lock.locked())
        return True

    with patch.object(SyncPool, "_validate_connection", tracking_validate):
        conn = pool.acquire()
        assert conn is mock_conn

    assert lock_held_during_validate
    assert not any(lock_held_during_validate)


def test_syncpool_decrements_created_when_closed_during_validation() -> None:
    pool = SyncPool.__new__(SyncPool)
    pool._closed = False
    pool.min_size = 0
    pool.max_size = 2
    pool.acquire_timeout = 1.0
    pool.on_connect = None
    pool._kwargs = {}
    pool._pool = __import__("collections").deque()
    pool._lock = threading.Lock()
    pool._sem = threading.Semaphore(2)
    pool._created = 1
    pool._checked_out = set()
    pool._checked_out_pc = {}
    pool._log = __import__("logging").getLogger("test")
    pool._stop_event = threading.Event()
    pool._maintain_thread = threading.Thread(target=lambda: None, daemon=True)

    mock_conn = MagicMock()
    mock_conn.close = MagicMock()
    from nzpy_extended.pool import _SyncPooledConnection

    now = time.monotonic()
    pool._pool.append(_SyncPooledConnection(mock_conn, now, now, 0))

    def validate_then_close(self, pc):  # type: ignore[no-untyped-def]
        pool._closed = True
        return True

    with patch.object(SyncPool, "_validate_connection", validate_then_close):
        with pytest.raises(RuntimeError, match="closed during connection validation"):
            pool.acquire()

    assert pool._created == 0
    mock_conn.close.assert_called_once()
