# nzpy_extended: High-performance IBM Netezza driver for Python

**nzpy_extended** is a hard fork of [IBM nzpy](https://github.com/IBM/nzpy) — enriched with new features, major performance improvements via a C extension, and expanded platform support.

## Key differences from upstream nzpy

| Feature | nzpy (IBM) | nzpy_extended |
|---|---|---|
| Row parsing performance (mixed types) | ~4 800 rows/s | ~37 000 rows/s (no C ext) → ~51 000 rows/s (+ C ext, on par with ODBC ~50 k) |
| Supported Python | 3.5+ | **3.12, 3.13, 3.14** |
| Platform wheels | ❌ None | ✅ Linux x64, macOS ARM, Windows x64 (pre-built) |
| Async support | ❌ | ✅ Fully async API |

Performance gains vary by data type. For mixed-type workloads (most representative of real-world queries), nzpy_extended reaches **~51 000 rows/s with C extension** (vs. ~4 800 rows/s for official nzpy — a **~10.7×** improvement) and **~37 000 rows/s without C extension** (~7.7× improvement). Per-type benchmarks with 100 k rows:

| Data type | official nzpy | nzpy_extended (no C ext) | nzpy_extended (+ C ext) | vs. ODBC |
|---|---|---|---|---|
| INTEGER | ~16 k rows/s | ~200 k rows/s | **~281 k rows/s** | ≈ ODBC (~283 k) |
| NUMERIC | ~8 k rows/s | ~73 k rows/s | **~109 k rows/s** | ≈ ODBC (~106 k) |
| STRING | ~18 k rows/s | ~94 k rows/s | **~96 k rows/s** | ≈ ODBC (~96 k) |
| DATETIME | ~17 k rows/s | ~122 k rows/s | **~274 k rows/s** | ≈ ODBC (~273 k) |
| BOOLEAN | ~22 k rows/s | ~235 k rows/s | **~433 k rows/s** | ≈ ODBC (~435 k) |
| Mixed | ~4 800 rows/s | ~37 k rows/s | **~51 k rows/s** | ≈ ODBC (~50 k) |

The C extension accelerates integer, decimal, datetime, and boolean parsing by avoiding Python object allocations per field and `struct.unpack` overhead. String parsing is primarily network-bound, so the C extension offers minimal benefit there.

If the compiled extension is not available (unsupported platform or Python version), the driver **gracefully falls back** to pure Python with identical semantics.

## Installation

```shell
pip install nzpy_extended
```

Pre-built wheels are provided for:

| Platform | Architecture | Python |
|---|---|---|
| Linux | x86_64 (manylinux) | 3.12 / 3.13 / 3.14 |
| macOS | ARM64 (Apple Silicon) | 3.12 / 3.13 / 3.14 |
| Windows | x86_64 | 3.12 / 3.13 / 3.14 |

For other platforms or Python versions, `pip install` will compile the C extension from source (requires a C compiler: GCC, Clang, or MSVC). On systems without a compiler the install will fail — use a supported platform or version.

## Quick Start

### Sync — scripts, ETL, Jupyter, Django

```python
import nzpy_extended.sync as nzpy

conn = nzpy.connect(
    user="admin", password="secret",
    host="netezza-host", database="mydb",
)
with conn.cursor() as cur:
    cur.execute("SELECT id, name FROM users WHERE active = ?", (1,))
    for row in cur:
        print(row)
```

### Async — FastAPI, asyncio

```python
import asyncio
import nzpy_extended as nzpy

async def main():
    async with await nzpy.connect(
        user="admin", password="secret",
        host="netezza-host", database="mydb",
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM users WHERE active = ?", (1,))
            return await cur.fetchall()

asyncio.run(main())
```

### FastAPI with connection pool

```python
from fastapi import FastAPI, Depends
import nzpy_extended as nzpy
import nzpy_extended.fastapi as nzpy_fastapi

pool = nzpy.NzPool(
    min_size=2, max_size=10,
    host="netezza-host", database="mydb",
    user="admin", password="secret",
)

app = FastAPI(lifespan=nzpy_fastapi.lifespan(pool))

@app.get("/users")
async def get_users(conn=Depends(nzpy_fastapi.get_connection)):
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM users LIMIT 100")
        return await cur.fetchall()
```

## Requirements

- Python ≥ 3.12
- CPython (PyPy not supported for C extension, pure-Python fallback only)

## Documentation

- [GitHub Wiki](https://github.com/KrzysztofDusko/nzpy_extended/wiki)
- [Issue tracker](https://github.com/KrzysztofDusko/nzpy_extended/issues)

## Testing

### Running the test suite

Tests require a running Netezza instance. Set the connection environment variables:

```shell
export NZ_DEV_HOST=your_netezza_host
export NZ_DEV_PORT=5480
export NZ_DEV_DB=JUST_DATA
export NZ_DEV_USER=admin
export NZ_DEV_PASSWORD=password
```

Run all tests:
```shell
pytest tests/ -v
```

### C Extension / Pure Python parity

The C extension and pure-Python fallback must produce identical results for all data types. Parity tests verify this in two ways:

**Unit tests** (`tests/test_c_python_parity_unit.py`) — compare individual C parser functions against Python reference implementations byte-by-byte. No database required.

```shell
pytest tests/test_c_python_parity_unit.py -v
```

**Integration tests** (`tests/test_c_python_parity_integration.py`) — run real SQL queries through both code paths and verify results match. Requires a database.

```shell
pytest tests/test_c_python_parity_integration.py -v
```

**Verification script** — runs both test suites in C-extension and pure-Python modes side-by-side:

```shell
python tools/verify_c_python_parity.py
```

**Disabling C extension at runtime:**

Set the environment variable `NZPY_EXTENDED_NO_CEXT=1` to force pure-Python mode even when the compiled extension is available. Useful for debugging or verifying fallback correctness.

```shell
NZPY_EXTENDED_NO_CEXT=1 pip install nzpy_extended
# or at runtime:
NZPY_EXTENDED_NO_CEXT=1 python -c "import nzpy_extended.core; print(nzpy_extended.core._HAVE_C_EXT)"  # False
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
