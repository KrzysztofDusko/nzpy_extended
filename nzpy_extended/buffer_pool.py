import threading

class BufferPool:
    """
    Simple byte buffer pool (bytearray) for reducing allocations.
    """
    def __init__(self, buffer_size=65536):
        self.buffer_size = buffer_size
        self._pool = []
        self._lock = threading.Lock()

    def acquire(self) -> bytearray:
        with self._lock:
            if self._pool:
                return self._pool.pop()
        return bytearray(self.buffer_size)

    def release(self, buffer: bytearray):
        # Reset the view before returning (optional)
        if len(buffer) == self.buffer_size:
            with self._lock:
                self._pool.append(buffer)

# Global buffer pool
global_pool = BufferPool()
