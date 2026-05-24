import threading

from ._constants import DEFAULT_BUFFER_SIZE


class BufferPool:
    def __init__(self, buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        self.buffer_size = buffer_size
        self._pool: list[bytearray] = []
        self._lock = threading.Lock()

    def acquire(self) -> bytearray:
        with self._lock:
            if self._pool:
                return self._pool.pop()
        return bytearray(self.buffer_size)

    def release(self, buffer: bytearray) -> None:
        if len(buffer) == self.buffer_size:
            with self._lock:
                self._pool.append(buffer)


global_pool: BufferPool = BufferPool()


__all__ = ["BufferPool", "global_pool"]
