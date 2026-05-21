import asyncio
from .buffer_pool import global_pool

class NzBufferedStream:
    """
    Async stream with a built-in circular buffer (pre-allocated bytearray).
    Reduces the number of system calls and small object allocations.
    """
    def __init__(self, sock, max_size=65536):
        self.sock = sock
        self.max_size = max_size
        self.buffer = global_pool.acquire()
        self.view = memoryview(self.buffer)
        self.head = 0
        self.tail = 0
        self.loop = asyncio.get_event_loop()

    def close(self):
        """Releases the buffer back to the pool."""
        if self.buffer:
            global_pool.release(self.buffer)
            self.buffer = None
            self.view = None

    def read_view_sync(self, n: int):
        """Synchronous read from buffer without copying (returns memoryview) if data is available."""
        avail = self.tail - self.head
        if avail >= n:
            result = self.view[self.head:self.head + n]
            self.head += n
            return result
        return None

    def read_available_view(self):
        """Returns all available contiguous data in the buffer as a memoryview without consuming it."""
        avail = self.tail - self.head
        if avail > 0:
            return self.view[self.head:self.tail]
        return None

    def advance_head(self, n: int):
        """Advances the head pointer by n bytes (marks data from read_available_view as consumed)."""
        self.head += n

    async def read(self, n: int) -> bytes:
        if n == 0:
            return b""

        if n > self.max_size:
            if n > 100 * 1024 * 1024:
                raise ValueError(
                    f"Requested read size {n} exceeds maximum allowed 104857600"
                )
            result = bytearray(n)
            res_view = memoryview(result)
            bytes_read = 0

            avail = self.tail - self.head
            if avail > 0:
                to_copy = min(n, avail)
                res_view[:to_copy] = self.view[self.head:self.head + to_copy]
                self.head += to_copy
                bytes_read += to_copy

            while bytes_read < n:
                chunk_len = await self.loop.sock_recv_into(self.sock, res_view[bytes_read:])
                if not chunk_len:
                    break
                bytes_read += chunk_len
            return bytes(result)

        avail = self.tail - self.head
        if avail >= n:
            result = bytes(self.view[self.head:self.head + n])
            self.head += n
            return result

        result = bytearray(n)
        res_view = memoryview(result)
        bytes_read = 0
        
        while bytes_read < n:
            avail = self.tail - self.head
            if avail > 0:
                to_copy = min(n - bytes_read, avail)
                res_view[bytes_read:bytes_read+to_copy] = self.view[self.head:self.head+to_copy]
                self.head += to_copy
                bytes_read += to_copy
                
            if bytes_read < n:
                await self._fill_buffer()
                if self.tail == self.head:
                    break
                    
        return bytes(result)

    async def _fill_buffer(self):
        self._rotate_buffer()
        chunk_len = await self.loop.sock_recv_into(self.sock, self.view[self.tail:])
        self.tail += chunk_len

    def _rotate_buffer(self):
        avail = self.tail - self.head
        if avail > 0 and self.head > 0:
            self.view[:avail] = self.view[self.head:self.tail]
        self.head = 0
        self.tail = avail

    async def write(self, data: bytes | bytearray):
        # Currently using simple sendall for writing
        await self.loop.sock_sendall(self.sock, data)
