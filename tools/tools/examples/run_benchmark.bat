@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo === nzpy_extended Benchmark Runner (Windows) ===
echo.

if not exist "nzpy_bench_venv" (
    echo [1/4] Creating virtual environment...
    python -m venv nzpy_bench_venv
    if !errorlevel! neq 0 (
        echo ERROR: Failed to create venv. Is Python installed? ^(requires ^>= 3.12^)
        pause
        exit /b 1
    )
) else (
    echo [1/4] Using existing virtual environment...
)

call nzpy_bench_venv\Scripts\activate.bat

echo [2/4] Installing nzpy_extended and nzpy...
pip install -q --upgrade pip
pip install -q nzpy_extended nzpy
if !errorlevel! neq 0 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

if not exist "performance_test.py" (
    echo [3/4] Downloading benchmark script from GitHub...
    curl -sSL -o performance_test.py ^
        https://raw.githubusercontent.com/KrzysztofDusko/nzpy_extended/main/tools/examples/performance_test.py
    if !errorlevel! neq 0 (
        echo ERROR: Failed to download benchmark script.
        pause
        exit /b 1
    )
) else (
    echo [3/4] Using local performance_test.py...
)

echo [4/4] Running benchmark...
echo.
echo ^> Set NZ_HOST=your_server before running, or edit .env defaults.
echo.
python -X utf8 performance_test.py

call deactivate
echo.
echo Done. Results saved to benchmark_windows_rerun.txt ^(if NZ_OUTPUT was set^)
pause
