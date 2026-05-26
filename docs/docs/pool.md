# Connection Pools

nzpy_extended provides four pool implementations for both async and sync usage.

## Overview

| Pool | API | Reuse | Description |
|---|---|---|---|
| `NzPool` | Async | ✅ | Full async pool with health checks, idle timeout, maintenance |
| `SyncPool` | Sync | ✅ | Sync pool built on NzPool concepts, thread-safe |
| `NullPool` | Sync | ❌ | Creates new connection per `acquire()`, closes on `release()` |
| `AsyncNullPool` | Async | ❌ | Same as NullPool, async variant |

## NzPool (Async)

```python
import nzpy_extended as nzpy

pool = nzpy.NzPool(
    min_size=2,              # pre-create 2 connections
    max_size=10,             # maximum connections
    idle_timeout=300.0,      # close idle after 5 min
    max_lifetime=3600.0,     # max connection age (1 hour)
    max_uses=1000,           # max uses before recycle
    acquire_timeout=30.0,    # timeout waiting for connection
    ping_query="SELECT 1",   # validate on acquire (None to skip)
    host="localhost",
    port=5480,
    user="admin",
    password="password",
    database="mydb",
)

async with pool.connection() as conn:
    async with conn.cursor() as cur:
        await cur.execute("SELECT 1")
        print(await cur.fetchone())

stats = pool.get_stats()
print(stats)
# {'type': 'NzPool', 'pool_min': 2, 'pool_max': 10, 'pool_size': 2,
#  'pool_available': 1, 'pool_in_use': 1, 'pool_closed': False}

await pool.close_all()
```

### Key behaviors
- `release()` **rolls back** open transactions (`autocommit=False`, `in_transaction=True`) before returning the connection to the pool
- `close_all()` closes ALL connections, including currently checked-out ones
- A background maintenance task runs every 30s to validate and remove stale connections

## SyncPool (Sync)

```python
from nzpy_extended import SyncPool
import nzpy_extended.sync as nzpy

pool = SyncPool(
    min_size=2, max_size=10,
    host="localhost", port=5480,
    user="admin", password="password",
    database="mydb",
)

# Context manager
with pool.connection() as conn:
    conn.execute("SELECT 1").fetchone()

# Manual acquire/release
conn = pool.acquire()
conn.execute("SELECT 1")
pool.release(conn)

stats = pool.get_stats()
pool.close_all()
```

### Key behaviors
- `release()` rolls back open transactions
- `close_all()` closes all connections including checked-out
- Uses `threading.Event` for proper shutdown signaling (no race conditions)
- Maintenance thread runs every 30s, properly joined on `close_all()`

## NullPool (Sync)

Simple pool that creates a new connection for every `acquire()` and closes it on `release()`. Useful when you want the pool API without connection reuse.

```python
from nzpy_extended import NullPool

pool = NullPool(host="localhost", port=5480, user="admin", password="password", database="mydb")
with pool.connection() as conn:
    conn.execute("SELECT 1")
```

## AsyncNullPool (Async)

Async variant of NullPool.

```python
from nzpy_extended import AsyncNullPool

pool = AsyncNullPool(host="localhost", ...)
async with pool.connection() as conn:
    await conn.execute("SELECT 1")
```

## Common methods

| Method | NzPool | SyncPool | NullPool | AsyncNullPool |
|---|---|---|---|---|
| `acquire()` | ✅ | ✅ | ✅ | ✅ |
| `release(conn)` | ✅ | ✅ | ✅ | ✅ |
| `connection()` context manager | ✅ | ✅ | ✅ | ✅ |
| `get_stats()` | ✅ | ✅ | ✅ | ✅ |
| `close_all()` | ✅ | ✅ | ✅ | ✅ |

## Double release protection

All pools raise `RuntimeError` if you try to `release()` a connection that was not acquired from that pool or has already been released:

```python
conn = pool.acquire()
pool.release(conn)
pool.release(conn)  # RuntimeError
```
