# nzpy_extended: High-performance IBM Netezza driver for Python

**nzpy_extended** is a hard fork of [IBM nzpy](https://github.com/IBM/nzpy) — enriched with new features, major performance improvements via a C extension, and expanded platform support.

## Key differences from upstream nzpy

| Feature | nzpy (IBM) | nzpy_extended |
|---|---|---|
| Row parsing performance | ~13 000 rows/s (pure Python) | ~50 000 rows/s (optimized Python) → ~200 000 rows/s (+ C ext, exceeds ODBC ~160 k) |
| Supported Python | 3.5+ | **3.12, 3.13, 3.14** |
| Platform wheels | ❌ None | ✅ Linux x64, macOS ARM, Windows x64 (pre-built) |
| Async support | ❌ | ✅ Fully async API |

A large portion of the speedup comes from avoiding unnecessary object allocations in pure Python (~13 k → ~50 k rows/s). When the C extension is available (`_HAVE_C_EXT = True`), parsing of integers, floats, decimals, dates, times, timestamps, booleans, and strings all happen in native C — avoiding Python object allocations per field and `struct.unpack` overhead — boosting throughput to ~200 k rows/s.

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

## Quick start

```python
import nzpy_extended as nzpy

conn = nzpy.connect(
    user="admin", password="password",
    host="localhost", port=5480, database="db1",
    securityLevel=1,
)

with conn.cursor() as cursor:
    cursor.execute("CREATE TABLE IF NOT EXISTS test (id INT, name VARCHAR(50))")
    cursor.execute("INSERT INTO test VALUES (?, ?)", (1, "Alice"))
    cursor.execute("SELECT * FROM test")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
```

## Requirements

- Python ≥ 3.12
- CPython (PyPy not supported for C extension, pure-Python fallback only)

## Documentation

- [GitHub Wiki](https://github.com/JustyBase/nzpy_extended/wiki)
- [Issue tracker](https://github.com/JustyBase/nzpy_extended/issues)

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
