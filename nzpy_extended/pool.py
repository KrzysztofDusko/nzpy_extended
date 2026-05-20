import asyncio
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

from nzpy_extended.core import Connection


@dataclass
class _PooledConnection:
    conn: Connection
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
        ping_query: Optional[str] = "SELECT 1",
        **kwargs: Any,
    ):
        self.min_size = min_size
        self.max_size = max_size
        self.idle_timeout = idle_timeout
        self.max_lifetime = max_lifetime
        self.max_uses = max_uses
        self.acquire_timeout = acquire_timeout
        self.ping_query = ping_query
        self.kwargs = kwargs

        self._pool: deque[_PooledConnection] = deque()
        self._created = 0
        self._cond = asyncio.Condition()
        self._closed = False
        self._checked_out: set[int] = set()
        self._log = logging.getLogger("nzpy_extended.NzPool")

    _CONNECT_DEFAULTS = {
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

    async def _create_new_connection(self) -> Connection:
        conn = Connection()
        merged = dict(self._CONNECT_DEFAULTS)
        merged.update(self.kwargs)
        await conn._connect(**merged)
        conn._nzpy_pool_created = time.monotonic()
        conn._nzpy_pool_uses = 0
        return conn

    async def _validate_connection(self, pc: _PooledConnection) -> bool:
        now = time.monotonic()
        if self.idle_timeout > 0 and (now - pc.last_used) > self.idle_timeout:
            return False
        if self.max_lifetime > 0 and (now - pc.created_at) > self.max_lifetime:
            return False
        if self.max_uses > 0 and pc.use_count >= self.max_uses:
            return False
        if self.ping_query is not None:
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

    async def acquire(self) -> Connection:
        if self._closed:
            raise RuntimeError("Pool is closed")

        async with self._cond:
            if self._created < self.min_size:
                await self._fill_idle()

            deadline = time.monotonic() + self.acquire_timeout if self.acquire_timeout > 0 else float("inf")

            while True:
                while self._pool:
                    pc = self._pool.popleft()
                    if await self._validate_connection(pc):
                        pc.use_count += 1
                        pc.conn._nzpy_pool_uses = pc.use_count
                        self._checked_out.add(id(pc.conn))
                        return pc.conn
                    else:
                        await self._close_connection(pc)
                        self._created -= 1

                if self._created < self.max_size:
                    try:
                        conn = await self._create_new_connection()
                        now = time.monotonic()
                        self._created += 1
                        conn._nzpy_pool_uses = 1
                        self._checked_out.add(id(conn))
                        pc = _PooledConnection(conn, now, now, 1)
                        return pc.conn
                    except Exception as e:
                        raise e

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

    async def release(self, conn: Connection) -> None:
        if self._closed:
            await conn.close()
            return

        conn_id = id(conn)
        if conn_id not in self._checked_out:
            raise RuntimeError(
                "Release called on connection which has already been released to the pool."
            )
        self._checked_out.discard(conn_id)

        now = time.monotonic()
        created = getattr(conn, '_nzpy_pool_created', now)
        uses = getattr(conn, '_nzpy_pool_uses', 0)
        pc = _PooledConnection(conn, created, now, uses)

        async with self._cond:
            self._pool.append(pc)
            self._cond.notify(1)

    @asynccontextmanager
    async def connection(self):
        conn = await self.acquire()
        try:
            yield conn
        finally:
            await self.release(conn)

    async def close_all(self) -> None:
        async with self._cond:
            self._closed = True
            while self._pool:
                pc = self._pool.popleft()
                await self._close_connection(pc)
            self._created = 0
            self._checked_out.clear()
            self._cond.notify_all()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close_all()
