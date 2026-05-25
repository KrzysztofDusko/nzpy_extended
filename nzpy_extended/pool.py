from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

from nzpy_extended.core import Connection

from . import sync as _sync

_CONNECT_DEFAULTS: dict[str, Any] = {
    'unix_sock': None,
    'ssl': None,
    'securityLevel': 0,
    'timeout': None,
    'application_name': None,
    'max_prepared_statements': 1000,
    'datestyle': 'ISO',
    'logLevel': 0,
    'tcp_keepalive': True,
    'char_varchar_encoding': 'latin',
}


@dataclass
class _PooledConnection:
    conn: Connection
    created_at: float
    last_used: float
    use_count: int


@dataclass
class _SyncPooledConnection:
    conn: Any
    created_at: float
    last_used: float
    use_count: int


class NzPool:
    def __init__(
        self,
        min_size: int = 1,
        max_size: int = 10,
        idle_timeout: float = 300.0,
        max_lifetime: float = 3600.0,
        max_uses: int = 1000,
        acquire_timeout: float = 30.0,
        ping_query: str | None = "SELECT 1",
        on_connect: Callable[[Connection], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.min_size = min_size
        self.max_size = max_size
        if self.min_size > self.max_size:
            raise ValueError(
                f"min_size ({min_size}) cannot exceed max_size ({max_size})"
        )
        self.idle_timeout = idle_timeout
        self.max_lifetime = max_lifetime
        self.max_uses = max_uses
        self.acquire_timeout = acquire_timeout
        self.ping_query = ping_query
        self.on_connect = on_connect
        self.kwargs = kwargs

        self._pool: deque[_PooledConnection] = deque()
        self._created = 0
        self._cond = asyncio.Condition()
        self._closed = False
        self._checked_out: set[int] = set()
        self._log = logging.getLogger("nzpy_extended.NzPool")
        self._maintain_task: asyncio.Task[None] | None = None

    async def _create_new_connection(self) -> Connection:
        conn = Connection()
        merged = dict(_CONNECT_DEFAULTS)
        merged.update(self.kwargs)
        await conn.connect(**merged)
        conn._nzpy_pool_created = time.monotonic()  # type: ignore[attr-defined]
        conn._nzpy_pool_uses = 0  # type: ignore[attr-defined]
        if self.on_connect is not None:
            try:
                result = self.on_connect(conn)
                if hasattr(result, '__await__'):
                    await result
            except Exception:
                try:
                    await conn.close()
                except Exception:
                    pass
                raise
        return conn

    async def _validate_connection(self, pc: _PooledConnection) -> bool:
        now = time.monotonic()
        if self.idle_timeout > 0 and (now - pc.last_used) > self.idle_timeout:
            return False
        if self.max_lifetime > 0 and (now - pc.created_at) > self.max_lifetime:
            return False
        if self.max_uses > 0 and pc.use_count >= self.max_uses:
            return False
        if self.ping_query:
            try:
                cursor = pc.conn.cursor()
                await asyncio.wait_for(
                    pc.conn.execute(cursor, self.ping_query, None),
                    timeout=10.0
                )
                await cursor.fetchall()
            except (asyncio.TimeoutError, Exception):
                return False
        return True

    async def _close_connection(self, pc: _PooledConnection) -> None:
        try:
            await pc.conn.close()
        except Exception:
            pass

    async def _fill_idle(self) -> None:
        while self._created < self.min_size:
            try:
                conn = await self._create_new_connection()
                now = time.monotonic()
                self._pool.append(_PooledConnection(conn, now, now, 0))
                self._created += 1
            except Exception as e:
                self._log.warning("Failed to pre-create connection: %s", e)
                break

    def get_stats(self) -> dict[str, Any]:
        return {
            "type":           "NzPool",
            "pool_min":       self.min_size,
            "pool_max":       self.max_size,
            "pool_size":      self._created,
            "pool_available": len(self._pool),
            "pool_in_use":    len(self._checked_out),
            "pool_closed":    self._closed,
        }

    async def open(self) -> None:
        await self._fill_idle()
        if self._maintain_task is None and not self._closed:
            self._maintain_task = asyncio.create_task(self._background_maintain())

    async def _background_maintain(self) -> None:
        while not self._closed:
            await asyncio.sleep(30)

            async with self._cond:
                candidates = list(self._pool)

            stale: list[_PooledConnection] = []
            for pc in candidates:
                if not await self._validate_connection(pc):
                    stale.append(pc)

            for pc in stale:
                await self._close_connection(pc)

            async with self._cond:
                for pc in stale:
                    if pc in self._pool:
                        self._pool.remove(pc)
                        self._created -= 1
                await self._fill_idle()

    async def acquire(self) -> Connection:
        if self._closed:
            raise RuntimeError("Pool is closed")

        deadline = time.monotonic() + self.acquire_timeout if self.acquire_timeout > 0 else float("inf")

        while True:
            async with self._cond:
                if self._created < self.min_size:
                    await self._fill_idle()

                if self._pool:
                    pc = self._pool.popleft()
                elif self._created < self.max_size:
                    try:
                        conn = await self._create_new_connection()
                        _ = time.monotonic()
                        self._created += 1
                        conn._nzpy_pool_uses = 1  # type: ignore[attr-defined]
                        self._checked_out.add(id(conn))
                        return conn
                    except Exception:
                        raise
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Timed out waiting for a connection from pool "
                            f"(created={self._created}, max_size={self.max_size})"
                        )

                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                    except asyncio.TimeoutError:
                        raise TimeoutError(
                            f"Timed out waiting for a connection from pool "
                            f"(created={self._created}, max_size={self.max_size})"
                        )
                    continue

            if await self._validate_connection(pc):
                async with self._cond:
                    pc.use_count += 1
                    pc.conn._nzpy_pool_uses = pc.use_count  # type: ignore[attr-defined]
                    self._checked_out.add(id(pc.conn))
                return pc.conn
            else:
                await self._close_connection(pc)
                async with self._cond:
                    self._created -= 1

    async def release(self, conn: Connection) -> None:
        conn_id = id(conn)

        async with self._cond:
            if self._closed:
                await conn.close()
                return
            if conn_id not in self._checked_out:
                raise RuntimeError(
                    "Connection was not acquired from this pool or has already been released."
                )
            self._checked_out.discard(conn_id)

            now = time.monotonic()
            created = getattr(conn, '_nzpy_pool_created', now)
            uses = getattr(conn, '_nzpy_pool_uses', 0)
            pc = _PooledConnection(conn, created, now, uses)
            self._pool.append(pc)
            self._cond.notify(1)

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[Connection, None]:
        conn = await self.acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

    async def close_all(self) -> None:
        if self._maintain_task is not None:
            self._maintain_task.cancel()
            self._maintain_task = None
        async with self._cond:
            self._closed = True
            while self._pool:
                pc = self._pool.popleft()
                await self._close_connection(pc)
            self._created = 0
            self._checked_out.clear()
            self._cond.notify_all()

    async def __aenter__(self) -> NzPool:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close_all()


class SyncPool:
    def __init__(
        self,
        min_size: int = 1,
        max_size: int = 10,
        idle_timeout: float = 300.0,
        max_lifetime: float = 3600.0,
        max_uses: int = 1000,
        acquire_timeout: float = 30.0,
        ping_query: str | None = "SELECT 1",
        on_connect: Callable[[Any], Any] | None = None,
        **conn_kwargs: Any,
    ) -> None:
        if min_size > max_size:
            raise ValueError(
                f"min_size ({min_size}) cannot exceed max_size ({max_size})"
            )
        self.min_size = min_size
        self.max_size = max_size
        self.idle_timeout = idle_timeout
        self.max_lifetime = max_lifetime
        self.max_uses = max_uses
        self.acquire_timeout = acquire_timeout
        self.ping_query = ping_query
        self.on_connect = on_connect
        self._kwargs = conn_kwargs

        self._pool: deque[_SyncPooledConnection] = deque()
        self._lock = threading.Lock()
        self._sem = threading.Semaphore(max_size)
        self._created = 0
        self._checked_out: set[int] = set()
        self._checked_out_pc: dict[int, _SyncPooledConnection] = {}
        self._closed = False
        self._maintain_active = True
        self._maintain_thread = threading.Thread(
            target=self._maintain_loop, daemon=True
        )
        self._maintain_thread.start()

        for _ in range(min_size):
            try:
                conn = _sync.connect(on_connect=on_connect, **conn_kwargs)
                now = time.monotonic()
                self._pool.append(_SyncPooledConnection(conn, now, now, 0))
                self._created += 1
            except Exception:
                break

    def open(self) -> None:
        with self._lock:
            while self._created < self.min_size and not self._closed:
                try:
                    conn = _sync.connect(on_connect=self.on_connect, **self._kwargs)
                    now = time.monotonic()
                    self._pool.append(_SyncPooledConnection(conn, now, now, 0))
                    self._created += 1
                except Exception:
                    break

    def _validate_connection(self, pc: _SyncPooledConnection) -> bool:
        now = time.monotonic()
        if self.idle_timeout > 0 and (now - pc.last_used) > self.idle_timeout:
            return False
        if self.max_lifetime > 0 and (now - pc.created_at) > self.max_lifetime:
            return False
        if self.max_uses > 0 and pc.use_count >= self.max_uses:
            return False
        if self.ping_query:
            try:
                cur = pc.conn.cursor()
                cur.execute(self.ping_query)
                cur.fetchall()
            except Exception:
                return False
        return True

    def _maintain_loop(self) -> None:
        while self._maintain_active:
            time.sleep(30)
            if not self._maintain_active or self._closed:
                break
            stale: list[_SyncPooledConnection] = []
            with self._lock:
                if self._closed:
                    break
                for pc in list(self._pool):
                    if not self._validate_connection(pc):
                        stale.append(pc)
                for pc in stale:
                    try:
                        self._pool.remove(pc)
                        self._created -= 1
                    except ValueError:
                        pass
            for pc in stale:
                try:
                    pc.conn.close()
                except Exception:
                    pass

    def acquire(self) -> Any:
        if self._closed:
            raise RuntimeError("Pool is closed")
        acquired = self._sem.acquire(timeout=self.acquire_timeout)
        if not acquired:
            raise TimeoutError(
                f"Could not acquire connection within {self.acquire_timeout}s "
                f"(pool_size={self._created}, in_use={len(self._checked_out)})"
            )
        with self._lock:
            if self._closed:
                self._sem.release()
                raise RuntimeError("Pool was closed while waiting for a connection")
            while self._pool:
                pc = self._pool.popleft()
                if self._validate_connection(pc):
                    pc.use_count += 1
                    conn_id = id(pc.conn)
                    self._checked_out.add(conn_id)
                    self._checked_out_pc[conn_id] = pc
                    return pc.conn
                else:
                    try:
                        pc.conn.close()
                    except Exception:
                        pass
                    self._created -= 1

            conn = _sync.connect(on_connect=self.on_connect, **self._kwargs)
            now = time.monotonic()
            self._created += 1
            conn_id = id(conn)
            self._checked_out.add(conn_id)
            self._checked_out_pc[conn_id] = _SyncPooledConnection(conn, now, now, 1)
            return conn

    def release(self, conn: Any) -> None:
        with self._lock:
            conn_id = id(conn)
            if conn_id not in self._checked_out:
                raise RuntimeError(
                    "Connection was not acquired from this pool or has already been released."
                )
            self._checked_out.discard(conn_id)
            pc = self._checked_out_pc.pop(conn_id)
            if self._closed:
                try:
                    conn.close()
                except Exception:
                    pass
                finally:
                    if self._created > 0:
                        self._created -= 1
            else:
                pc.last_used = time.monotonic()
                self._pool.append(pc)
        self._sem.release()

    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type":           "SyncPool",
                "pool_min":       self.min_size,
                "pool_max":       self.max_size,
                "pool_size":      self._created,
                "pool_available": len(self._pool),
                "pool_in_use":    len(self._checked_out),
                "pool_closed":    self._closed,
            }

    def close_all(self) -> None:
        self._maintain_active = False
        with self._lock:
            self._closed = True
            while self._pool:
                pc = self._pool.popleft()
                try:
                    pc.conn.close()
                except Exception:
                    pass
            self._created = 0
            self._checked_out.clear()
            self._checked_out_pc.clear()
            for _ in range(self.max_size):
                try:
                    self._sem.release()
                except ValueError:
                    pass

    def __enter__(self) -> SyncPool:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close_all()


class NullPool:
    def __init__(self, on_connect: Callable[[Any], Any] | None = None, **conn_kwargs: Any) -> None:
        self._kwargs = conn_kwargs
        self._on_connect = on_connect

    def acquire(self) -> Any:
        return _sync.connect(on_connect=self._on_connect, **self._kwargs)

    def release(self, conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            pass

    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def get_stats(self) -> dict[str, str]:
        return {"type": "NullPool"}

    def close_all(self) -> None:
        pass

    def __enter__(self) -> NullPool:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class AsyncNullPool:
    def __init__(self, on_connect: Callable[[Connection], Any] | None = None, **conn_kwargs: Any) -> None:
        self._kwargs = conn_kwargs
        self._on_connect = on_connect

    async def acquire(self) -> Connection:
        conn = Connection()
        merged = dict(_CONNECT_DEFAULTS)
        merged.update(self._kwargs)
        await conn.connect(**merged)
        if self._on_connect is not None:
            result = self._on_connect(conn)
            if hasattr(result, '__await__'):
                await result
        return conn

    async def release(self, conn: Connection) -> None:
        try:
            await conn.close()
        except Exception:
            pass

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[Connection, None]:
        conn = await self.acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

    def get_stats(self) -> dict[str, str]:
        return {"type": "AsyncNullPool"}

    async def close_all(self) -> None:
        pass

    async def __aenter__(self) -> AsyncNullPool:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


__all__ = ["NzPool", "SyncPool", "NullPool", "AsyncNullPool"]
