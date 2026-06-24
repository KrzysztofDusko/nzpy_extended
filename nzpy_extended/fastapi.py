from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

_log = logging.getLogger("nzpy_extended.fastapi")

try:
    from fastapi import FastAPI, Request  # type: ignore[import-not-found,unused-ignore]
except ImportError:
    FastAPI = Any
    Request = Any


def lifespan(pool: Any) -> Any:
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:  # pyright: ignore
        if hasattr(pool, "open"):
            result = pool.open()
            if inspect.iscoroutine(result):
                await result
        app.state.nz_pool = pool  # pyright: ignore
        try:
            yield
        finally:
            if hasattr(pool, "close_all"):
                try:
                    result = pool.close_all()
                    if inspect.iscoroutine(result):
                        await result
                except Exception as exc:
                    _log.debug(
                        "Error closing pool in FastAPI lifespan: %s",
                        exc,
                        exc_info=True,
                    )

    return _lifespan


def get_pool(request: Request) -> Any:  # pyright: ignore
    return request.app.state.nz_pool  # pyright: ignore


async def get_connection(request: Request) -> AsyncGenerator[Any, None]:  # pyright: ignore
    pool = request.app.state.nz_pool  # pyright: ignore

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


__all__ = ["lifespan", "get_pool", "get_connection"]
