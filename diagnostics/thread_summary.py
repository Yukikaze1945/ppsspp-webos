#!/usr/bin/env python3
"""Summarize thread_sampler JSONL into per-thread CPU and run-queue deltas."""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def load_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    malformed += 1
                    continue
                if not all(isinstance(row.get(k), int) for k in
                           ("mono_ns", "pid", "tid", "run_ns", "wait_ns", "slices")):
                    malformed += 1
                    continue
                rows.append(row)
            except json.JSONDecodeError:
                malformed += 1
    rows.sort(key=lambda row: row["mono_ns"])
    return rows, malformed


def infer_overhead_path(input_path: Path) -> Path:
    suffix = ".threads.jsonl"
    if input_path.name.endswith(suffix):
        return input_path.with_name(input_path.name[:-len(suffix)] + ".thread-overhead.log")
    return input_path.with_suffix(".thread-overhead.log")


def load_overhead(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"elapsed=([0-9.]+)s\s+self_cpu=([0-9.]+)s\s+"
        r"self_cpu_percent_one_core=([0-9.]+)%",
        text,
    )
    if not match:
        return {"available": True, "raw": text.strip(), "parsed": False}
    return {
        "available": True,
        "parsed": True,
        "elapsed_seconds": float(match.group(1)),
        "self_cpu_seconds": float(match.group(2)),
        "self_cpu_percent_one_core": float(match.group(3)),
        "interpretation": "sampler CPU as percent of one core, measured with getrusage",
    }


def summarize(path: Path, start_uptime: float | None,
              end_uptime: float | None, overhead_path: Path) -> dict[str, Any]:
    rows, malformed = load_rows(path)
    if start_uptime is not None:
        rows = [r for r in rows if r["mono_ns"] >= start_uptime * 1e9]
    if end_uptime is not None:
        rows = [r for r in rows if r["mono_ns"] <= end_uptime * 1e9]

    process_names: dict[int, str] = {}
    for row in rows:
        if row["pid"] == row["tid"]:
            process_names[row["pid"]] = str(row.get("name", ""))

    previous: dict[tuple[int, int], dict[str, Any]] = {}
    per_thread: dict[tuple[int, int], dict[str, Any]] = {}
    intervals_ns: list[int] = []
    for row in rows:
        key = (row["pid"], row["tid"])
        name = str(row.get("name", ""))
        aggregate = per_thread.setdefault(key, {
            "pid": row["pid"], "tid": row["tid"], "name": name,
            "role": process_names.get(row["pid"], "unknown"),
            "cpu_percent_one_core": [], "wait_delta_ns": [],
            "run_delta_ns": [], "slice_delta": [], "states": Counter(),
        })
        aggregate["states"][str(row.get("state", "?"))] += 1
        old = previous.get(key)
        if old:
            elapsed = row["mono_ns"] - old["mono_ns"]
            run_delta = row["run_ns"] - old["run_ns"]
            wait_delta = row["wait_ns"] - old["wait_ns"]
            slice_delta = row["slices"] - old["slices"]
            if elapsed > 0 and run_delta >= 0 and wait_delta >= 0 and slice_delta >= 0:
                intervals_ns.append(elapsed)
                aggregate["cpu_percent_one_core"].append(100.0 * run_delta / elapsed)
                aggregate["run_delta_ns"].append(run_delta)
                aggregate["wait_delta_ns"].append(wait_delta)
                aggregate["slice_delta"].append(slice_delta)
        previous[key] = row

    thread_summaries = []
    for aggregate in per_thread.values():
        rates = aggregate["cpu_percent_one_core"]
        wait_deltas = aggregate["wait_delta_ns"]
        states = aggregate["states"]
        thread_summaries.append({
            "pid": aggregate["pid"],
            "tid": aggregate["tid"],
            "role": aggregate["role"],
            "name": aggregate["name"],
            "samples": states.total(),
            "rate_intervals": len(rates),
            "cpu_percent_one_core_mean": round(statistics.mean(rates), 2) if rates else None,
            "cpu_percent_one_core_p95": round(percentile(rates, 0.95), 2) if rates else None,
            "cpu_percent_one_core_max": round(max(rates), 2) if rates else None,
            "run_time_delta_ms": round(sum(aggregate["run_delta_ns"]) / 1e6, 3),
            "runqueue_wait_delta_ms": round(sum(wait_deltas) / 1e6, 3),
            "runqueue_wait_mean_delta_ms": round(statistics.mean(wait_deltas) / 1e6, 3) if wait_deltas else None,
            "slices_delta": sum(aggregate["slice_delta"]),
            "state_observations": dict(states),
        })
    thread_summaries.sort(
        key=lambda t: (t["cpu_percent_one_core_max"] or 0,
                       t["cpu_percent_one_core_p95"] or 0),
        reverse=True,
    )

    durations_ms = [duration / 1e6 for duration in intervals_ns]
    start_ns = rows[0]["mono_ns"] if rows else None
    end_ns = rows[-1]["mono_ns"] if rows else None
    pids = sorted({row["pid"] for row in rows})
    return {
        "format": "ppsspp-webos-thread-summary-v1",
        "input": str(path),
        "window_uptime_seconds": [start_uptime, end_uptime],
        "observed_monotonic_window_ns": [start_ns, end_ns],
        "cpu_note": "CPU percentage is one-core normalized: 100% equals one fully occupied logical core.",
        "sampling_note": "Rates are differences of cumulative schedstat run time between consecutive records of the same PID/TID; intervals use recorded monotonic timestamps.",
        "wchan": {"available": False, "note": "Raw thread_sampler records contain stat state and schedstat only; kernel wait-channel names cannot be inferred."},
        "record_count": len(rows),
        "malformed_records_in_file": malformed,
        "pids": [{"pid": pid, "main_thread_name": process_names.get(pid, "unknown")}
                 for pid in pids],
        "sample_interval_ms": {
            "count": len(durations_ms),
            "mean": round(statistics.mean(durations_ms), 3) if durations_ms else None,
            "p95": round(percentile(durations_ms, 0.95), 3) if durations_ms else None,
            "max": round(max(durations_ms), 3) if durations_ms else None,
        },
        "sampler_overhead": load_overhead(overhead_path),
        "top_threads": thread_summaries[:20],
        "threads": thread_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw <label>.threads.jsonl file")
    parser.add_argument("--start-uptime", type=float, help="optional inclusive monotonic/uptime lower bound in seconds")
    parser.add_argument("--end-uptime", type=float, help="optional inclusive monotonic/uptime upper bound in seconds")
    parser.add_argument("--overhead-log", type=Path, help="sampler getrusage log; defaults to matching .thread-overhead.log")
    parser.add_argument("--json-out", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()
    if args.start_uptime is not None and args.end_uptime is not None and args.start_uptime > args.end_uptime:
        parser.error("--start-uptime must not exceed --end-uptime")
    overhead = args.overhead_log or infer_overhead_path(args.input)
    payload = summarize(args.input, args.start_uptime, args.end_uptime, overhead)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
        destination = str(args.json_out)
    else:
        print(rendered)
        destination = "stdout"

    top = payload["top_threads"][:5]
    top_text = ", ".join(
        f"{item['name']} pid={item['pid']} tid={item['tid']} "
        f"mean/p95/max={item['cpu_percent_one_core_mean']}/"
        f"{item['cpu_percent_one_core_p95']}/{item['cpu_percent_one_core_max']}%"
        for item in top
    ) or "no thread intervals"
    overhead_data = payload["sampler_overhead"]
    overhead_text = (f"sampler CPU={overhead_data['self_cpu_seconds']}s "
                     f"({overhead_data['self_cpu_percent_one_core']}% of one core)"
                     if overhead_data and overhead_data.get("parsed") else "sampler CPU overhead unavailable")
    print(f"{payload['record_count']} records / {len(payload['threads'])} threads; "
          f"{overhead_text}; top: {top_text}; JSON: {destination}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
