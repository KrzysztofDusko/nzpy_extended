from decimal import Decimal
import csv
import pathlib

import pytest

import nzpy_extended as nzpy

pytestmark = pytest.mark.full

DATA_DIR = pathlib.Path(__file__).parent / "test_data"


def _read_csv(filename):
    path = DATA_DIR / filename
    rows = []
    with open(path, newline='') as f:
        reader = csv.reader(f, delimiter='|')
        for row in reader:
            rows.append(tuple(row))
    return rows


def _val_match(orig, actual):
    """Compare an original CSV string with the value returned by the DB,
    tolerating type normalisation (e.g. 0.5 vs 0.500, True vs true, None vs '')."""
    if actual is None:
        return orig.strip() == ''
    if isinstance(actual, bool):
        ol = orig.strip().lower()
        return (ol in ('true', 't', 'yes', '1')) if actual else (ol in ('false', 'f', 'no', '0'))
    if isinstance(actual, Decimal):
        return Decimal(orig.strip()) == actual
    return orig.strip() == str(actual)


async def _do_test(con, filename):
    table_name = f"test_infer_{pathlib.Path(filename).stem}"
    original_rows = _read_csv(filename)
    cur = con.cursor()

    try:
        await cur.execute(f"DROP TABLE {table_name} IF EXISTS")

        count = await nzpy.load_data(con, table_name, original_rows)
        assert count == len(original_rows), (
            f"Expected {len(original_rows)} rows, got {count}"
        )

        await cur.execute(f"SELECT * FROM {table_name}")
        actual_rows = await cur.fetchall()

        assert len(actual_rows) == len(original_rows), (
            f"Row count mismatch: {len(actual_rows)} vs {len(original_rows)}"
        )

        # Sort both by string representation for order-independent comparison
        zipped = sorted(zip(original_rows, actual_rows),
                        key=lambda pair: str(pair[0]))
        for orig_row, act_row in zipped:
            for j, (o, a) in enumerate(zip(orig_row, act_row)):
                assert _val_match(o, a), (
                    f"Row mismatch at col {j + 1}:\n"
                    f"  original: {o!r} (type {type(o).__name__})\n"
                    f"  actual:   {a!r} (type {type(a).__name__})"
                )

    finally:
        try:
            await cur.execute(f"DROP TABLE {table_name} IF EXISTS")
        except Exception:
            pass


# ----- Tests -----

class TestLoadDataInference:

    @pytest.mark.asyncio
    async def test_all_dates(self, con):
        await _do_test(con, "all_dates.csv")

    @pytest.mark.asyncio
    async def test_mostly_dates(self, con):
        """99 date strings + 1 'NOT_A_DATE' -> col1 must be VARCHAR(255), not DATE.
        Verifies inference prefers VARCHAR over DATE when not all values are valid dates.
        """
        await _do_test(con, "mostly_dates.csv")

    @pytest.mark.asyncio
    async def test_all_ints(self, con):
        await _do_test(con, "all_ints.csv")

    @pytest.mark.asyncio
    async def test_all_floats(self, con):
        await _do_test(con, "all_floats.csv")

    @pytest.mark.asyncio
    async def test_mixed_numbers(self, con):
        """Ints and floats in same column -> NUMERIC; text column -> VARCHAR(255)."""
        await _do_test(con, "mixed_numbers.csv")

    @pytest.mark.asyncio
    async def test_booleans(self, con):
        await _do_test(con, "booleans.csv")

    @pytest.mark.asyncio
    async def test_booleans_all_numeric(self, con):
        """0/1 only, no keywords -> should be SMALLINT, not BOOLEAN."""
        await _do_test(con, "booleans_all_numeric.csv")

    @pytest.mark.asyncio
    async def test_timestamps(self, con):
        await _do_test(con, "timestamps.csv")

    @pytest.mark.asyncio
    async def test_times(self, con):
        await _do_test(con, "times.csv")

    @pytest.mark.asyncio
    async def test_empty_and_values(self, con):
        await _do_test(con, "empty_and_values.csv")

    @pytest.mark.asyncio
    async def test_all_varchar(self, con):
        await _do_test(con, "all_varchar.csv")

    @pytest.mark.asyncio
    async def test_decimals(self, con):
        await _do_test(con, "decimals.csv")

    @pytest.mark.asyncio
    async def test_big_ints(self, con):
        await _do_test(con, "big_ints.csv")

    @pytest.mark.asyncio
    async def test_unicode_text(self, con):
        await _do_test(con, "unicode_text.csv")
