# nzpy_extended: High-performance IBM Netezza driver for Python

**nzpy_extended** is a hard fork of [IBM nzpy](https://github.com/IBM/nzpy) — enriched with new features, major performance improvements via a C extension, and expanded platform support.

## Key differences from upstream nzpy

| Feature | nzpy (IBM) | nzpy_extended |
|---|---|---|
| Row parsing performance (mixed types) | ~10 000 rows/s | ~63 000 rows/s (no C ext) → **~93 000 rows/s** (+ C ext) |
| Supported Python | 3.5+ | **3.12, 3.13, 3.14** |
| Platform wheels | ❌ None | ✅ Linux x64, macOS ARM, Windows x64 (pre-built) |
| Async support | ❌ | ✅ Fully async API |

Performance gains vary by data type. For mixed-type workloads (most representative of real-world queries), nzpy_extended reaches **~49 000 rows/s with C extension** (vs. ~5‬400 rows/s for official nzpy — a **~9×** improvement on WSL2) and **~33 000 rows/s without C extension** (~6× improvement). Per-type benchmarks with 100 k rows:

### Windows 11

| Data type | official nzpy | nzpy_extended (no C ext) | nzpy_extended (+ C ext) | vs. ODBC |
|---|---|---|---|---|
| INTEGER | ~18 k rows/s | ~196 k rows/s | **~256 k rows/s** | ≈ ODBC (~239 k) |
| NUMERIC | ~10 k rows/s | ~75 k rows/s | **~97 k rows/s** | ≈ ODBC (~90 k) |
| STRING | ~18 k rows/s | ~75 k rows/s | **~79 k rows/s** | ≈ ODBC (~69 k) |
| DATETIME | ~18 k rows/s | ~135 k rows/s | **~255 k rows/s** | ≈ ODBC (~249 k) |
| BOOLEAN | ~23 k rows/s | ~243 k rows/s | **~401 k rows/s** | ≈ ODBC (~359 k) |
| Mixed | ~4 900 rows/s | ~36 k rows/s | **~45 k rows/s** | ≈ ODBC (~44 k) |

### WSL2 (Linux x86_64)

| Data type | official nzpy | nzpy_extended (no C ext) | nzpy_extended (+ C ext) | vs. ODBC |
|---|---|---|---|---|
| INTEGER | ~21 k rows/s | ~203 k rows/s | **~640 k rows/s** | ~92 k rows/s |
| NUMERIC | ~11 k rows/s | ~79 k rows/s | **~150 k rows/s** | ~63 k rows/s |
| STRING | ~22 k rows/s | ~71 k rows/s | **~160 k rows/s** | ~80 k rows/s |
| DATETIME | ~21 k rows/s | ~126 k rows/s | **~407 k rows/s** | ~111 k rows/s |
| BOOLEAN | ~25 k rows/s | ~186 k rows/s | **~418 k rows/s** | ~192 k rows/s |
| Mixed | ~5.4 k rows/s | ~33 k rows/s | **~49 k rows/s** | ~20 k rows/s |

Note: WSL2 results were obtained on the same Netezza server as Windows 11 (192.168.0.144) — the higher throughput reflects Linux network stack efficiency. ODBC results use a ctypes-based ANSI-ODBC fallback (because pyodbc's Unicode API is incompatible with the Netezza ODBC driver on Linux). This wrapper fetches every cell individually via `SQLGetData`, so ODBC numbers on WSL2 are **understated** vs. native pyodbc on Windows (which uses `SQLBindCol` batch fetching). The real ODBC-vs-native gap on Linux is likely smaller.

### macOS ARM64 (Apple M4)

Benchmarks run on a Mac mini (Apple M4, 16 GB RAM) — same Netezza server at 192.168.0.144. 100 k rows per query.

| Data type | official nzpy | nzpy_extended (no C ext) | nzpy_extended (+ C ext) |
|---|---|---|---|
| INTEGER | ~44 k rows/s | ~356 k rows/s | **~726 k rows/s** |
| NUMERIC | ~22 k rows/s | ~122 k rows/s | **~195 k rows/s** |
| STRING | ~39 k rows/s | ~143 k rows/s | **~183 k rows/s** |
| DATETIME | ~42 k rows/s | ~253 k rows/s | **~683 k rows/s** |
| BOOLEAN | ~53 k rows/s | ~449 k rows/s | **~786 k rows/s** |
| Mixed | ~10 k rows/s | ~63 k rows/s | **~93 k rows/s** |

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

### Bulk data loading via external table protocol

`load_data()` inserts rows from a Python iterable into a Netezza table using the native external table protocol (`REMOTESOURCE 'python'`). It supports optional automatic table creation.

```python
# --- Auto-infer: create table + load in one step ---
rows = [(1, "Alice", 100.50), (2, "Bob", 200.75)]
count = await nzpy.load_data(conn, "my_table", rows)
print(f"Inserted {count} rows")

# --- Mixed types with auto-infer (INT, VARCHAR, NUMERIC, BOOLEAN, DATE) ---
from decimal import Decimal
from datetime import date
rows = [
    (10, "item", Decimal("19.99"), True, date(2025, 1, 15)),
]
count = await conn.load_data("products", rows)
# Creates: col1 SMALLINT, col2 VARCHAR(255), col3 NUMERIC(4,2),
#          col4 BOOLEAN, col5 DATE

# --- Explicit columns (no auto-infer) ---
count = await conn.load_data(
    table_name="products",
    rows=[(101, "Widget", 9.99)],
    columns=[("id", "INT"), ("name", "VARCHAR(200)"), ("price", "NUMERIC(10,2)")],
)

# --- Generator for large datasets ---
def generate_rows(n):
    for i in range(n):
        yield (i, f"item_{i}")

count = await nzpy.load_data(conn, "my_table", rows=generate_rows(50000))
```

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `conn` / `table_name` / `rows` | (required) | Connection, target table, row iterable |
| `columns` | `None` | `[(name, nz_type), ...]` or `None` for auto-infer from data |
| `delimiter` | `'\|'` | Field delimiter (pipe is safe; use `,` with `escape_char`) |
| `encoding` | `'LATIN9'` | Text encoding (use `'UTF8'` for NVARCHAR columns) |
| `create_if_missing` | `True` | Auto-create table if not exists |
| `temporary` | `False` | Create TEMP TABLE |
| `distribute_on_random` | `True` | Add `DISTRIBUTE ON RANDOM` to DDL |
| `logdir` | temp dir | Netezza log directory |
| `escape_char` | `'\\'` | Escape character for delimiter within values (`None` to disable) |

**Auto-infer column types:** When `columns` is `None` and `create_if_missing=True`, the driver reads the first row and maps Python types to Netezza DDL: `int` → `SMALLINT`/`INT`/`BIGINT`, `float` → `FLOAT`, `str` → `VARCHAR(255)`, `Decimal` → `NUMERIC(p,s)`, `bool` → `BOOLEAN`, `date` → `DATE`, `datetime` → `TIMESTAMP`, `bytes` → `BYTEA`. Column names default to `col1`, `col2`, etc.

**Note on delimiters and escaping:** Netezza external tables do not support standard CSV double-quote quoting. When a value contains the delimiter character, it must be escaped with the escape character (default: `\`). The driver does this automatically.

The function is available both as a standalone `nzpy.load_data()` and as `conn.load_data()`.

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

## Reproducing benchmark results

The per-type benchmark table above is generated by [`tools/examples/performance_test.py`](tools/examples/performance_test.py).

### Prerequisites

- A running Netezza instance with a table named `JUST_DATA..FACTPRODUCTINVENTORY` (or adjust `SOURCE_TABLE` in the script)
- Python ≥ 3.12
- Install the required packages:

```shell
pip install nzpy_extended
```

The official IBM driver is also tested for comparison (`pip install nzpy`).

Optional (for ODBC comparison):
- `pip install pyodbc` — with `NetezzaSQL` ODBC driver installed (rows labeled `pyodbc`)
- Set `NZ_ODBC_DRIVER` if your ODBC driver uses a different name (default: `NetezzaSQL`). On Linux/WSL2 the name is defined in `/etc/odbcinst.ini`, e.g.:
  ```shell
  export NZ_ODBC_DRIVER=NetezzaSQL  # Linux/WSL2
  ```
- **Linux/WSL2**: pyodbc's Unicode API is incompatible with the Netezza ODBC driver. The benchmark auto-detects this and falls back to a ctypes-based ANSI-ODBC wrapper. No additional configuration needed.

### Steps

1. **Set connection environment variables:**

```shell
set NZ_HOST=your_netezza_host     # Windows
set NZ_PORT=5480
set NZ_USER=admin
set NZ_PASSWORD=password
set NZ_DATABASE=JUST_DATA

# or on Linux/macOS:
export NZ_HOST=your_netezza_host
export NZ_PORT=5480
export NZ_USER=admin
export NZ_PASSWORD=password
export NZ_DATABASE=JUST_DATA
```

All variables have defaults — only `NZ_HOST` is required if your setup differs from the defaults.

ODBC driver name can be set separately:
```shell
export NZ_ODBC_DRIVER=NetezzaSQL  # Linux/macOS — defaults to "NetezzaSQL"
```

2. **Run the benchmark:**

```shell
python tools/examples/performance_test.py
```

3. **Adjust row count** (default: 100 000):

```shell
set NZ_ROWS=100000     # Windows
export NZ_ROWS=100000  # Linux/macOS
```

### What the script does

1. Connects using each driver: `official_nzpy` (always), `pyodbc` (via ANSI-ODBC ctypes fallback on Linux), `nzpy_extended` (async + sync, with and without C extension).
2. Runs six query categories: `integer_types`, `numeric_types`, `string_types`, `datetime_types`, `boolean_types`, and `all_types` (mixed).
3. Prints per-query timing, a compact DRIVER × TYPE comparison table (matching the README layout), and visual bar charts.

### Saving results to a TXT file

Use the `--output` / `-o` flag or the `NZ_OUTPUT` environment variable:

```shell
python tools/examples/performance_test.py -o benchmark_results.txt

# or via env var:
set NZ_OUTPUT=benchmark_results.txt
python tools/examples/performance_test.py
```

### Force pure-Python mode

```shell
set NZPY_EXTENDED_NO_CEXT=1
python tools/examples/performance_test.py
```

### Pytest benchmark (alternative)

A simpler pytest-based benchmark is also available (10 k rows, nzpy_extended only):

```shell
pytest tests/test_benchmark.py -v -m benchmark
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
