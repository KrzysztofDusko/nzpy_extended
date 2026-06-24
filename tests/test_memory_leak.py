"""
Memory leak regression test.

Verifies that no Python objects (Decimals, row-lists) accumulate when
fetching large result sets across multiple queries.  Runs as a
parametrized test with the C extension BOTH enabled and disabled.

This test requires:
  - A live Netezza / IBM Netezza database (env vars: NZ_DEV_HOST, etc.)
  - ``psutil`` installed  (``pip install psutil``)

Skipped when psutil is not available or the connection fails.
"""

from __future__ import annotations

import gc
import os
from typing import Any

import psutil
import pytest

# ---------------------------------------------------------------------------
# Thresholds (tune these if the test environment changes)
# ---------------------------------------------------------------------------
# Maximum allowed Decimal object count after gc.collect() across iterations.
# With C-ext enabled, CPython's arena free-list keeps ~3500 Decimals alive
# even after gc.collect() – this is not a leak, just deferred deallocation.
# Pure Python mode stays near 0.
# Observed C-ext baseline fluctuation: 3146–3755 (max ~3800).
# Threshold 4500 => 4500 − 3800 = 700 margin over 5 iterations,
# i.e. catches persistent leaks >140 objects/iter.
# Pure Python mode stays near 0–34, well within threshold.
MAX_DECIMALS = 4500

# Maximum allowed row-length list count (len=7 for FACTPRODUCTINVENTORY).
MAX_ROW_LISTS = 4500

# Number of iterations to run the query
ITERATIONS = 5

# SQL – returns 7 columns
SQL = "select * from JUST_DATA..FACTPRODUCTINVENTORY limit 100000"

# Markers
pytestmark = [
    pytest.mark.smoke,
    pytest.mark.full,
]


def _count_leaked() -> tuple[int, int]:
    """Count Decimal and len=7 list objects currently alive."""
    decimals = 0
    row_lists = 0
    for obj in gc.get_objects():
        tn = type(obj).__name__
        if tn == "Decimal":
            decimals += 1
        elif tn == "list" and len(obj) == 7:
            row_lists += 1
    return decimals, row_lists


def _rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / 1_000_000


@pytest.fixture
def db_kwargs_mem() -> dict[str, Any]:
    """Connection kwargs for memory tests."""
    return {
        "user":     os.environ.get("NZ_DEV_USER", "admin"),
        "password": os.environ.get("NZ_DEV_PASSWORD", "password"),
        "database": os.environ.get("NZ_DEV_DB", "JUST_DATA"),
        "host":     os.environ.get("NZ_DEV_HOST", "192.168.0.144"),
        "port":     int(os.environ.get("NZ_DEV_PORT", "5480")),
    }


@pytest.mark.parametrize("cext_on", [True, False], ids=["C_ext", "pure_python"])
def test_no_memory_leak(
    cext_on: bool,
    db_kwargs_mem: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert that repeated large-select queries do not leak objects."""
    import nzpy_extended._cstate as _cstate

    monkeypatch.setattr(_cstate, "_HAVE_C_EXT", cext_on)

    # Clean baseline
    gc.collect()
    rss0 = _rss_mb()
    dec0, rl0 = _count_leaked()
    print(f"\n[{cext_on=}]  init: RSS={rss0:.1f} MB  decimals={dec0}  rowlists={rl0}")

    import nzpy_extended.sync as nzpy_sync

    conn = nzpy_sync.connect(**db_kwargs_mem)
    try:
        for i in range(ITERATIONS):
            cur = conn.cursor()
            cur.execute(SQL)
            rows = cur.fetchall()
            rowcnt = len(rows)
            cur.close()
            del rows, cur

            gc.collect()
            rss = _rss_mb()
            dec, rl = _count_leaked()
            print(f"  iter {i}: RSS={rss:.1f} MB  decimals={dec}  rowlists={rl}  rows={rowcnt}")

        # Final check
        gc.collect()
        dec_final, rl_final = _count_leaked()
        rss_final = _rss_mb()
        print(f"[{cext_on=}]  final: RSS={rss_final:.1f} MB  decimals={dec_final}  rowlists={rl_final}")
    finally:
        conn.close()

    # Assert
    assert dec_final < MAX_DECIMALS, (
        f"Decimal leak detected: {dec_final} Decimals alive "
        f"(limit {MAX_DECIMALS}) after {ITERATIONS} iterations"
    )
    assert rl_final < MAX_ROW_LISTS, (
        f"Row-list leak detected: {rl_final} row-lists alive "
        f"(limit {MAX_ROW_LISTS}) after {ITERATIONS} iterations"
    )
