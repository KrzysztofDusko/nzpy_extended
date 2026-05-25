from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

import asyncio
import atexit
import threading


class _SyncRunner:
    _instance: _SyncRunner | None = None

    def __new__(cls) -> _SyncRunner:
        if cls._instance is not None:
            return cls._instance
        cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, '_loop'):
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="nzpy-sync-runner",
        )
        self._thread.start()
        atexit.register(self._atexit_cleanup)

    def run(self, coro: Coroutine[Any, Any, Any] | asyncio.Future[Any]) -> Any:
        if not self._loop.is_running():
            raise RuntimeError("nzpy _SyncRunner event loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()  # type: ignore[arg-type]

    def close(self) -> None:
        if not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        try:
            self._thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            self._loop.close()
        except Exception:
            pass

    @property
    def is_running(self) -> bool:
        return hasattr(self, '_loop') and self._loop.is_running()

    def _atexit_cleanup(self) -> None:
        try:
            self.close()
        except Exception:
            pass


runner: _SyncRunner = _SyncRunner()
