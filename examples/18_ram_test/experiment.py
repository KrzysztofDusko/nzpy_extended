"""
Ad-hoc experiment client for RAM diagnostic server.

Repeatedly calls /query or /query-cancel and /memory to track RSS growth.

Usage:
    python experiment.py --url http://127.0.0.1:8480 [options]
    python experiment.py --mode cancel --fetch-rows 5 --iterations 25
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def _fmt(val: float) -> str:
    return f"{val:>8.1f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="RAM experiment driver")
    parser.add_argument("--url", default="http://127.0.0.1:8480", help="Server URL")
    parser.add_argument(
        "--sql",
        default="select * from JUST_DATA..FACTPRODUCTINVENTORY limit 100000",
        help="SQL to execute on each iteration",
    )
    parser.add_argument("--iterations", type=int, default=25, help="Number of query calls")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between iterations")
    parser.add_argument(
        "--mode",
        choices=("fetchall", "cancel"),
        default="fetchall",
        help="fetchall = POST /query; cancel = POST /query-cancel",
    )
    parser.add_argument(
        "--fetch-rows",
        type=int,
        default=5,
        help="Rows to read before cancel (only with --mode cancel)",
    )
    parser.add_argument("--no-progress", action="store_true", help="Suppress per-iteration output")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    endpoint = "/query" if args.mode == "fetchall" else "/query-cancel"

    measurements: list[float] = []
    gc_measurements: list[int] = []
    errors: int = 0

    if not args.no_progress:
        print(f"Server      : {base_url}")
        print(f"Endpoint    : {endpoint}")
        print(f"SQL         : {args.sql[:100]}{'...' if len(args.sql) > 100 else ''}")
        print(f"Iterations  : {args.iterations}")
        print(f"Delay       : {args.delay}s")
        if args.mode == "cancel":
            print(f"Fetch rows  : {args.fetch_rows}")
        print()
        print(f"{'#':>4} | {'RSS (MB)':>10} | {'Delta (MB)':>10} | {'GC Objs':>10} | {'Status':>15}")
        print("-" * 60)

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        try:
            resp = client.get("/memory")
            resp.raise_for_status()
            data = resp.json()
            baseline = data["rss_mb"]
            gc_objs = data.get("gc_objects", 0)
        except Exception as exc:
            print(f"Failed to get baseline: {exc}", file=sys.stderr)
            sys.exit(1)

        measurements.append(baseline)
        gc_measurements.append(gc_objs)

        if not args.no_progress:
            print(f"{'base':>4} | {_fmt(baseline):>10} | {_fmt(0.0):>10} | {gc_objs:>10} | {'baseline'}")

        for i in range(1, args.iterations + 1):
            line = f"{i:>4} | " if not args.no_progress else ""
            sys.stdout.write(line)
            sys.stdout.flush()

            try:
                t0 = time.perf_counter()
                if args.mode == "fetchall":
                    resp = client.post(endpoint, json={"sql": args.sql}, timeout=300.0)
                else:
                    resp = client.post(
                        endpoint,
                        json={"sql": args.sql, "fetch_rows": args.fetch_rows},
                        timeout=300.0,
                    )
                elapsed = time.perf_counter() - t0
                resp.raise_for_status()
                data = resp.json()
                if args.mode == "fetchall":
                    rows = data.get("row_count", 0)
                    status = f"ok ({rows}r, {elapsed:.1f}s)"
                else:
                    read = data.get("fetch_rows_read", 0)
                    status = f"cancel ({read}r, {elapsed:.1f}s)"
                rss = data.get("rss_mb_after", data.get("rss_mb", 0))
                delta = rss - baseline
                gc_objs = 0
            except Exception as exc:
                rss = measurements[-1]
                delta = rss - baseline
                errors += 1
                status = f"ERR: {exc}"
                try:
                    m = client.get("/memory")
                    rss = m.json().get("rss_mb", rss)
                    delta = rss - baseline
                    status += "/mem"
                except Exception:
                    pass

            measurements.append(rss)
            gc_measurements.append(gc_objs)

            if not args.no_progress:
                print(f"{_fmt(rss):>10} | {_fmt(delta):>10} | {gc_objs:>10} | {status}")
            else:
                print(f"  iter {i:>2}: RSS={rss:.1f} MB  delta={delta:+.1f} MB  {status}")

            if i < args.iterations:
                time.sleep(args.delay)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    vals = measurements[1:]
    if vals:
        rss_min = min(vals)
        rss_max = max(vals)
        rss_mean = sum(vals) / len(vals)
        rss_first = vals[0]
        rss_last = vals[-1]
        grow = rss_last - rss_first

        print(f"  Mode         : {args.mode}")
        print(f"  Baseline     : {measurements[0]:>8.1f} MB")
        print(f"  Min (post)   : {rss_min:>8.1f} MB")
        print(f"  Max (post)   : {rss_max:>8.1f} MB")
        print(f"  Mean (post)  : {rss_mean:>8.1f} MB")
        print(f"  First (post) : {rss_first:>8.1f} MB  (iteration 1)")
        print(f"  Last  (post) : {rss_last:>8.1f} MB  (iteration {len(vals)})")
        print(f"  Total growth : {grow:>+8.1f} MB")
        print(f"  Avg growth   : {grow / len(vals):>+8.2f} MB/iter")
        print(f"  Errors       : {errors}")
        print()

        third = max(1, len(vals) // 3)
        early_avg = sum(vals[:third]) / third
        late_avg = sum(vals[-third:]) / third
        growth_rate = (vals[-1] - vals[0]) / len(vals)
        print(f"  Early {third} avg  : {early_avg:>8.1f} MB")
        print(f"  Late  {third} avg  : {late_avg:>8.1f} MB")
        print(f"  Growth rate  : {growth_rate:>+8.2f} MB/iter")

        leak_threshold = 5.0 if args.mode == "fetchall" else 2.0
        stable_threshold = 1.0 if args.mode == "fetchall" else 0.5

        if growth_rate < stable_threshold:
            print(f"  VERDICT: STABLE at ~{late_avg:.0f} MB (negligible growth)")
        elif growth_rate < leak_threshold:
            print(f"  VERDICT: SLIGHT GROWTH ({growth_rate:.1f} MB/iter) – may stabilise later")
        else:
            print(f"  VERDICT: LEAKING ({growth_rate:.1f} MB/iter) – linear growth, no stabilisation")

        print()
        print("Raw measurements (MB):")
        print(f"  {[f'{v:.1f}' for v in measurements]}")
    else:
        print("  No successful measurements.")


if __name__ == "__main__":
    main()
