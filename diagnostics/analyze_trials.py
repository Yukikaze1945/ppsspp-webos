#!/usr/bin/env python3
"""Summarize PPSSPP performance trial artifacts without modifying them.

Usage: python diagnostics/analyze_trials.py logs/performance/20261031-enemy
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


INVALID_SCENES = {
    "A1_noAI": "captured settings page, not gameplay",
    "B1_15AI": "captured settings page, not gameplay",
    "R1_15AI_1x": "captured settings page, not gameplay",
}
WINDOW_START_ADJUSTMENTS = {
    # Initial real-game capture included its feed warmup in uptime_before.
    "B-game1x": 2.2,
}
INVALID_OPTIMIZATION_TRIALS = {
    "O-game1x": "optimization flag not compiled; control replay only",
}
WINDOW_NOTE = (
    "Window uses summary uptime_before/uptime_after as an approximate interval. "
    "The initial capture's feed warmup is removed with an explicit 2.2-second "
    "start correction; later captures already start after warmup. Cumulative core/proxy counters "
    "are differenced at the nearest available 1-second records; boundary error is "
    "approximately one sample interval."
)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and isinstance(row.get("mono_ns"), (int, float)):
                        rows.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return sorted(rows, key=lambda row: row["mono_ns"])


def uptime_value(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.split()[0] if value.split() else None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def selected_cumulative_rows(rows: list[dict[str, Any]], start: float | None,
                              end: float | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not rows:
        return None
    if start is None or end is None:
        return rows[0], rows[-1]
    start_ns, end_ns = start * 1e9, end * 1e9
    before = [row for row in rows if row["mono_ns"] <= start_ns]
    through = [row for row in rows if row["mono_ns"] <= end_ns]
    left = before[-1] if before else rows[0]
    right = through[-1] if through else rows[0]
    if right["mono_ns"] < left["mono_ns"]:
        right = left
    return left, right


def nonnegative_delta(new: Any, old: Any) -> int:
    try:
        return max(0, int(new) - int(old))
    except (TypeError, ValueError):
        return 0


def top_ops(entries: dict[str, dict[str, int]], limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    for name, values in entries.items():
        count = values.get("count", 0)
        ns = values.get("ns", 0)
        if count == 0 and ns == 0:
            continue
        rows.append({"name": name, "count": count, "ms": round(ns / 1e6, 3),
                     "avg_us": round(ns / count / 1e3, 3) if count else None})
    return sorted(rows, key=lambda row: row["ms"], reverse=True)[:limit]


def summarize_bridge(path: Path, start: float | None, end: float | None,
                     proxy: bool) -> dict[str, Any]:
    rows = read_jsonl(path)
    selected = selected_cumulative_rows(rows, start, end)
    result: dict[str, Any] = {"available": bool(rows), "records": len(rows)}
    if not selected:
        return result
    left, right = selected
    result["record_window"] = [left["mono_ns"], right["mono_ns"]]
    result["observed_seconds"] = round((right["mono_ns"] - left["mono_ns"]) / 1e9, 3)
    result["depth_max_lifetime_high_water_observed"] = max(
        (int(row.get("depth_max", 0) or 0) for row in rows
         if left["mono_ns"] <= row["mono_ns"] <= right["mono_ns"]),
        default=int(right.get("depth_max", 0) or 0))
    if proxy:
        old_ops = {row[0]: row for row in left.get("ops", []) if isinstance(row, list) and row}
        new_ops = {row[0]: row for row in right.get("ops", []) if isinstance(row, list) and row}
        totals: dict[str, dict[str, int]] = {}
        for name in old_ops.keys() | new_ops.keys():
            old, new = old_ops.get(name, [name, 0, 0, 0, 0, 0]), new_ops.get(name, [name, 0, 0, 0, 0, 0])
            totals[name] = {"count": nonnegative_delta(new[1], old[1]),
                            "ns": nonnegative_delta(new[3], old[3]),
                            "sync_count": nonnegative_delta(new[2], old[2]),
                            "bind_ns": nonnegative_delta(new[5], old[5])}
        result["top_handler_wall_time"] = top_ops(totals)
        result["top_bind_time"] = top_ops({name: {"count": val["count"], "ns": val["bind_ns"]}
                                            for name, val in totals.items()})
        result["slow_calls"] = summarize_slow_calls(
            path.with_name(path.stem + ".slow.jsonl"), start, end)
        result["timing_definition"] = "handler CLOCK_MONOTONIC elapsed wall time; not GPU execution time"
    else:
        for category in ("begin", "data", "wl_call", "enqueue"):
            old = left.get(category, [0, 0, 0])
            new = right.get(category, [0, 0, 0])
            result[category] = {"count": nonnegative_delta(new[0], old[0]),
                                "ms": round(nonnegative_delta(new[1], old[1]) / 1e6, 3),
                                "avg_us": round(nonnegative_delta(new[1], old[1]) /
                                                nonnegative_delta(new[0], old[0]) / 1e3, 3)
                                if nonnegative_delta(new[0], old[0]) else None}
        old_ops = {row[0]: row for row in left.get("ops", []) if isinstance(row, list) and row}
        new_ops = {row[0]: row for row in right.get("ops", []) if isinstance(row, list) and row}
        totals = {name: {"count": nonnegative_delta(new_ops.get(name, [name, 0])[1],
                                                     old_ops.get(name, [name, 0])[1]),
                         "ns": nonnegative_delta(new_ops.get(name, [name, 0, 0])[2],
                                                 old_ops.get(name, [name, 0, 0])[2])}
                  for name in old_ops.keys() | new_ops.keys()}
        result["top_ops"] = top_ops(totals)
        old_sleep, new_sleep = left.get("sleeps", []), right.get("sleeps", [])
        phase_names = {0: "unclassified_or_idle", 1: "ring_slot_full", 2: "data_arena_full", 3: "other"}
        result["sleep_waits_by_phase"] = [
            {"phase": phase_names.get(idx, str(idx)),
             "count": nonnegative_delta(new_sleep[idx][0], old_sleep[idx][0]),
             "ms": round(nonnegative_delta(new_sleep[idx][1], old_sleep[idx][1]) / 1e6, 3)}
            for idx in range(min(len(old_sleep), len(new_sleep)))
        ]
    return result


def summarize_slow_calls(path: Path, start: float | None,
                         end: float | None) -> dict[str, Any]:
    rows = read_jsonl(path)
    if start is not None:
        rows = [row for row in rows if row["mono_ns"] >= start * 1e9]
    if end is not None:
        rows = [row for row in rows if row["mono_ns"] <= end * 1e9]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row.get("op"), str) or not isinstance(row.get("ns"), (int, float)):
            continue
        grouped[row["op"]].append(row)
    by_opcode = []
    for name, events in grouped.items():
        durations = sorted(int(row["ns"]) for row in events)
        p95_index = max(0, math.ceil(0.95 * len(durations)) - 1)
        by_opcode.append({
            "op": name,
            "slow_count": len(events),
            "p95_ms": round(durations[p95_index] / 1e6, 3),
            "max_ms": round(durations[-1] / 1e6, 3),
            "raw_timestamps": [
                {"mono_ns": int(row["mono_ns"]), "ns": int(row["ns"]),
                 "bind_ns": int(row.get("bind_ns", 0))}
                for row in events
            ],
        })
    by_opcode.sort(key=lambda item: item["max_ms"], reverse=True)
    return {"available": path.exists(), "events": sum(len(v) for v in grouped.values()),
            "by_opcode": by_opcode}


def task_schedstat(task: dict[str, Any]) -> tuple[int, int] | None:
    try:
        fields = str(task.get("schedstat", "")).split()
        return int(fields[0]), int(fields[1])
    except (ValueError, IndexError):
        return None


def summarize_system(path: Path, start: float | None, end: float | None) -> dict[str, Any]:
    payload = read_json(path)
    result: dict[str, Any] = {"available": bool(payload)}
    if not payload:
        return result
    samples = payload.get("samples", [])
    samples = [s for s in samples if isinstance(s, dict) and isinstance(s.get("uptime_seconds"), (int, float))]
    if start is not None:
        samples = [s for s in samples if start <= s["uptime_seconds"] <= (end if end is not None else float("inf"))]
    if not samples:
        result["samples"] = 0
        return result
    result["samples"] = len(samples)
    roles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        for proc in sample.get("processes", {}).values():
            if proc.get("role") in ("app", "proxy"):
                roles[proc["role"]].append((sample, proc))

    result["processes"] = {}
    for role, observations in roles.items():
        process_cpu = [p.get("cpu_percent_one_core_100") for _, p in observations
                       if isinstance(p.get("cpu_percent_one_core_100"), (int, float))]
        rss = [int(p.get("status", {}).get("VmRSS", "0 kB").split()[0])
               for _, p in observations if p.get("status", {}).get("VmRSS")]
        swaps = [int(p.get("status", {}).get("VmSwap", "0 kB").split()[0])
                 for _, p in observations if p.get("status", {}).get("VmSwap")]
        major_fault_deltas = []
        last_faults: dict[str, int] = {}
        threads: dict[tuple[str, str], list[float]] = defaultdict(list)
        waits: dict[tuple[str, str], list[int]] = defaultdict(list)
        wchan = Counter()
        last_tasks: dict[tuple[str, str], tuple[float, int, int, int]] = {}
        for sample, proc in observations:
            pid = str(proc.get("pid", ""))
            if isinstance(proc.get("majflt"), int):
                if pid in last_faults and proc["majflt"] >= last_faults[pid]:
                    major_fault_deltas.append(proc["majflt"] - last_faults[pid])
                last_faults[pid] = proc["majflt"]
            for tid, task in proc.get("tasks", {}).items():
                name = str(task.get("comm", task.get("comm_name", tid)))
                key = (pid, name)
                elapsed = float(sample["uptime_seconds"])
                ticks = int(sample.get("clk_tck", 100) or 100)
                cpu_ticks = int(task.get("utime_ticks", 0)) + int(task.get("stime_ticks", 0))
                task_start = int(task.get("starttime_ticks", 0))
                previous = last_tasks.get((pid, str(tid)))
                if previous and previous[3] == task_start and elapsed > previous[0] and cpu_ticks >= previous[1]:
                    threads[key].append((cpu_ticks - previous[1]) * 100.0 / ticks /
                                         (elapsed - previous[0]))
                sched = task_schedstat(task)
                if sched:
                    if previous and previous[3] == task_start and sched[1] >= previous[2]:
                        waits[key].append(sched[1] - previous[2])
                last_tasks[(pid, str(tid))] = (elapsed, cpu_ticks, sched[1] if sched else -1,
                                               task_start)
                chan = task.get("wchan")
                if chan:
                    wchan[str(chan)] += 1
        top_threads = []
        for (pid, name), values in threads.items():
            top_threads.append({"pid": pid, "name": name,
                                "mean_cpu_percent_one_core": round(statistics.mean(values), 2),
                                "max_cpu_percent_one_core": round(max(values), 2),
                                "samples": len(values)})
        top_threads.sort(key=lambda item: item["mean_cpu_percent_one_core"], reverse=True)
        top_waits = [{"pid": pid, "name": name,
                      "runqueue_wait_total_ms": round(sum(vals) / 1e6, 3),
                      "runqueue_wait_mean_delta_ms": round(statistics.mean(vals) / 1e6, 3),
                      "intervals": len(vals)}
                     for (pid, name), vals in waits.items() if vals]
        top_waits.sort(key=lambda item: item["runqueue_wait_total_ms"], reverse=True)
        result["processes"][role] = {
            "cpu_percent_one_core_mean": round(statistics.mean(process_cpu), 2) if process_cpu else None,
            "cpu_percent_one_core_max": round(max(process_cpu), 2) if process_cpu else None,
            "rss_kb_range": [min(rss), max(rss)] if rss else None,
            "swap_kb_range": [min(swaps), max(swaps)] if swaps else None,
            "major_faults_delta": sum(major_fault_deltas) if major_fault_deltas else None,
            "top_threads": top_threads[:12],
            "top_runqueue_wait_threads": top_waits[:12],
            "wchan_observations": dict(wchan.most_common(12)),
        }
    result["hardware_samples"] = [{
        "uptime_seconds": s.get("uptime_seconds"),
        "cpu_online": s.get("cpu_online"),
        "frequencies": s.get("frequencies", {}),
        "thermal": s.get("thermal", {}),
        "lg_private": s.get("lgpm", {}),
    } for s in samples]
    return result


def analyze_trial(directory: Path, summary_path: Path) -> dict[str, Any]:
    label = summary_path.name[:-len(".summary.json")]
    summary = read_json(summary_path) or {}
    raw_start = uptime_value(summary.get("uptime_before"))
    end = uptime_value(summary.get("uptime_after"))
    correction = WINDOW_START_ADJUSTMENTS.get(label, 0.0)
    start = raw_start + correction if raw_start is not None else None
    invalid = INVALID_SCENES.get(label)
    if invalid is None and "-game" not in label.lower() and "-fixed" not in label.lower():
        invalid = "label does not identify a gameplay scene; requires manual validation"
    optimization_invalid = INVALID_OPTIMIZATION_TRIALS.get(label)
    result: dict[str, Any] = {"label": label, "valid_gameplay_scene": invalid is None,
                              "valid_optimization_trial": invalid is None and optimization_invalid is None,
                              "invalid_reason": invalid or optimization_invalid,
                              "window_uptime_seconds": [start, end],
                              "summary_uptime_before": raw_start,
                              "window_start_adjustment_seconds": correction,
                              "fps": {k: summary.get(k) for k in
                                      ("elapsed_s", "flip_fps", "median_ms", "p95_ms", "p99_ms", "max_ms",
                                       "over50ms", "over100ms", "emulated_speed_percent") if k in summary},
                              "window_note": WINDOW_NOTE}
    result["core"] = summarize_bridge(directory / f"{label}.core.jsonl", start, end, proxy=False)
    result["proxy"] = summarize_bridge(directory / f"{label}.proxy.jsonl", start, end, proxy=True)
    result["system"] = summarize_system(directory / f"{label}.system.json", start, end)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing <label> trial artifacts")
    args = parser.parse_args()
    trials = [analyze_trial(args.directory, path)
              for path in sorted(args.directory.glob("*.summary.json"))]
    payload = {
        "format": "ppsspp-webos-trial-analysis-v1",
        "cpu_note": "Process and thread CPU percentages use 100% = one logical core.",
        "max_note": "Bridge max_total fields are lifetime maxima and are intentionally not reported as window maxima.",
        "trials": trials,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False))
    valid = sum(t["valid_gameplay_scene"] for t in trials)
    print(f"{len(trials)} trial(s): {valid} gameplay scene(s) included; invalid/setup captures retained as invalid metadata.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
