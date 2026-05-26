#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== nzpy_extended Benchmark Runner (Linux/macOS) ==="
echo ""

# Step 1: virtual environment
if [ ! -d "nzpy_bench_venv" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv nzpy_bench_venv
else
    echo "[1/4] Using existing virtual environment..."
fi

source nzpy_bench_venv/bin/activate

# Step 2: install dependencies
echo "[2/4] Installing nzpy_extended and nzpy..."
pip install -q --upgrade pip
pip install -q nzpy_extended nzpy

# Step 3: get the benchmark script
BENCH_SCRIPT="performance_test.py"
if [ ! -f "$BENCH_SCRIPT" ]; then
    echo "[3/4] Downloading benchmark script from GitHub..."
    curl -sSL -o "$BENCH_SCRIPT" \
        https://raw.githubusercontent.com/KrzysztofDusko/nzpy_extended/main/tools/examples/performance_test.py
else
    echo "[3/4] Using local $BENCH_SCRIPT..."
fi

# Step 4: run
echo "[4/4] Running benchmark..."
echo ""
echo "> Set NZ_HOST=your_server before running, or edit .env defaults."
echo ""
python3 -X utf8 "$BENCH_SCRIPT"

deactivate
echo ""
echo "Done."
