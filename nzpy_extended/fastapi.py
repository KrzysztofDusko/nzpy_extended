"""
FastAPI integration for nzpy_extended.

Full application example:

    from contextlib import asynccontextmanager
    from fastapi import FastAPI, Depends
    import nzpy_extended as nzpy
    import nzpy_extended.fastapi as nzpy_fastapi

    pool = nzpy.NzPool(
        min_size=2, max_size=10,
        host="nz-host", port=5480,
        database="mydb", user="admin", password="secret",
        securityLevel=1,
    )

    app = FastAPI(lifespan=nzpy_fastapi.lifespan(pool))

    @app.get("/users")
    async def get_users(pool=Depends(nzpy_fastapi.get_pool)):
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, name FROM users LIMIT 100")
                return await cur.fetchall()

    @app.get("/health/db")
    async def db_health(pool=Depends(nzpy_fastapi.get_pool)):
        stats = pool.get_stats()
        return {"status": "ok", "pool": stats}
"""

import inspect
from contextlib import asynccontextmanager
from typing import AsyncGenerator


def lifespan(pool):
    """Lifespan factory — manages pool lifecycle in FastAPI.

    Opens the pool on startup, closes on shutdown.
    Stores the pool on app.state.nz_pool.

    Args:
        pool: an NzPool, SyncPool, or NullPool instance

    Returns:
        An async context manager ready to pass to FastAPI(lifespan=...)
    """
    @asynccontextmanager
    async def _lifespan(app):
        if hasattr(pool, "open"):
            result = pool.open()
            if inspect.iscoroutine(result):
                await result
        app.state.nz_pool = pool
        try:
            yield
        finally:
            if hasattr(pool, "close_all"):
                try:
                    result = pool.close_all()
                    if inspect.iscoroutine(result):
                        await result
                except Exception:
                    pass

    return _lifespan


def get_pool(request):
    """FastAPI dependency — injects the pool into an endpoint.

    Usage:
        @app.get("/data")
        async def endpoint(pool=Depends(nzpy_fastapi.get_pool)):
            async with pool.connection() as conn:
                ...
    """
    return request.app.state.nz_pool


async def get_connection(request) -> AsyncGenerator:
    """FastAPI dependency — injects a ready connection (with auto-release).

    Automatically returns the connection to the pool after the request.

    Works with NzPool (async) and SyncPool/NullPool (sync).
    For async pools use `await cur.execute()`; for sync pools omit `await`.

    Usage:
        @app.get("/data")
        async def endpoint(conn=Depends(nzpy_fastapi.get_connection)):
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
    """
    pool = request.app.state.nz_pool

    if hasattr(pool, "connection"):
        ctx = pool.connection()
        if hasattr(ctx, "__aenter__"):
            async with ctx as conn:
                yield conn
        else:
            with ctx as conn:
                yield conn
    else:
        raise RuntimeError("Pool does not support connection() context manager")
