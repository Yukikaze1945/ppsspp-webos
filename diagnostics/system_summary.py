#!/usr/bin/env python3
"""Summarize tagged output from system_sampler.sh into JSON and a short report."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, TextIO


def parse_proc_stat(line: str) -> dict[str, Any] | None:
    """Parse /proc/PID/stat, whose comm field may contain spaces and ')' chars."""
    left = line.find("(")
    right = line.rfind(")")
    if left <= 0 or right <= left:
        return None
    try:
        pid = int(line[:left].strip())
        fields = line[right + 1 :].strip().split()
        if len(fields) < 22:
            return None
        return {
            "pid": pid,
            "comm": line[left + 1 : right],
            "state": fields[0],
            "ppid": int(fields[1]),
            "minflt": int(fields[7]),
            "majflt": int(fields[9]),
            "utime_ticks": int(fields[11]),
            "stime_ticks": int(fields[12]),
            "threads": int(fields[17]),
            "starttime_ticks": int(fields[19]),
            "rss_pages": int(fields[21]),
        }
    except (ValueError, IndexError):
        return None


def parse_int(value: str) -> int | None:
    try:
        return int(value.split()[0])
    except (ValueError, IndexError):
        return None


def parse_sample(rows: list[list[str]]) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "system_cpus": {},
        "vmstat": {},
        "meminfo_kb": {},
        "frequencies": {},
        "devfreq": {},
        "thermal": {},
        "lgpm": {},
        "processes": {},
    }
    for fields in rows:
        if not fields:
            continue
        tag = fields[0]
        try:
            if tag == "TS" and len(fields) > 1:
                sample["uptime_seconds"] = float(fields[1])
            elif tag == "CLK_TCK" and len(fields) > 1:
                sample["clk_tck"] = int(fields[1])
            elif tag == "UPTIME" and len(fields) > 2:
                sample["uptime_seconds"] = float(fields[1])
                sample["idle_seconds"] = float(fields[2].split()[0])
            elif tag == "LOADAVG" and len(fields) > 1:
                sample["loadavg_raw"] = fields[1]
                sample["loadavg"] = [float(x) for x in fields[1].split()[:3]]
            elif tag == "STAT" and len(fields) > 1:
                parts = fields[1].split()
                key = parts[0]
                values = [int(x) for x in parts[1:] if x.isdigit()]
                if key == "cpu" or key.startswith("cpu") and key[3:].isdigit():
                    sample["system_cpus"][key] = values
                elif key in {"ctxt", "processes", "procs_running", "procs_blocked"} and values:
                    sample["processes_created" if key == "processes" else key] = values[0]
            elif tag == "VMSTAT" and len(fields) > 2:
                value = parse_int(fields[2])
                if value is not None:
                    sample["vmstat"][fields[1]] = value
            elif tag == "MEMINFO" and len(fields) > 2:
                value = parse_int(fields[2])
                if value is not None:
                    sample["meminfo_kb"][fields[1]] = value
            elif tag == "CPU_ONLINE" and len(fields) > 1:
                sample["cpu_online"] = fields[1]
            elif tag == "FREQ" and len(fields) > 3:
                value = parse_int(fields[3])
                sample["frequencies"].setdefault(fields[1], {})[fields[2]] = value if value is not None else fields[3]
            elif tag == "DEVFREQ" and len(fields) > 3:
                value = parse_int(fields[3])
                sample["devfreq"].setdefault(fields[1], {})[fields[2]] = value if value is not None else fields[3]
            elif tag == "THERMAL" and len(fields) > 3:
                raw_temp = fields[3]
                temp = parse_int(raw_temp)
                row = {"type": fields[2], "raw": raw_temp}
                if temp is not None:
                    row["value"] = temp
                    if abs(temp) >= 1000:
                        row["celsius"] = temp / 1000.0
                sample["thermal"][fields[1]] = row
                sample["thermal_interfaces_available"] = True
            elif tag == "THERMAL_NONE":
                sample["thermal_interfaces_available"] = False
            elif tag == "LGPM" and len(fields) > 2:
                sample["lgpm"][fields[1]] = fields[2]
            elif tag == "PROC" and len(fields) > 4:
                pid = int(fields[1])
                proc = parse_proc_stat(fields[4])
                if proc is not None:
                    proc.update({"role": fields[2], "exe": fields[3], "status": {}, "tasks": {}})
                    sample["processes"][str(pid)] = proc
            elif tag == "STATUS" and len(fields) > 3:
                proc = sample["processes"].get(fields[1])
                if proc is not None:
                    proc["status"][fields[2]] = fields[3]
            elif tag == "TASK" and len(fields) > 3:
                proc = sample["processes"].get(fields[1])
                task = parse_proc_stat(fields[3])
                if proc is not None and task is not None:
                    proc["tasks"][fields[2]] = task
            elif tag in {"TASKCOMM", "WCHAN", "SCHEDSTAT"} and len(fields) > 3:
                proc = sample["processes"].get(fields[1])
                task = proc["tasks"].get(fields[2]) if proc else None
                if task is not None:
                    key = {"TASKCOMM": "comm", "WCHAN": "wchan", "SCHEDSTAT": "schedstat"}[tag]
                    task[key] = fields[3]
        except (ValueError, IndexError):
            # A process can disappear while the shell samples /proc. Keep the
            # rest of the block rather than losing the whole capture.
            continue
    return sample


def read_blocks(stream: TextIO) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: list[list[str]] | None = None
    for raw in stream:
        line = raw.rstrip("\r\n")
        if line == "END":
            if current is not None:
                blocks.append(parse_sample(current))
                current = None
            continue
        fields = line.split("\t")
        if fields[0] == "TS":
            current = [fields]
        elif current is not None:
            current.append(fields)
    return blocks


def cpu_counters(values: list[int]) -> tuple[int, int]:
    # Linux /proc/stat: user,nice,system,idle,iowait,irq,softirq,steal.
    padded = values[:8] + [0] * max(0, 8 - len(values))
    total = sum(padded)
    idle = padded[3] + padded[4]
    return total, idle


def delta_rate(now: int | None, before: int | None, elapsed: float) -> float | None:
    if now is None or before is None or elapsed <= 0 or now < before:
        return None
    return (now - before) / elapsed


def enrich(samples: list[dict[str, Any]]) -> None:
    previous: dict[str, Any] | None = None
    for sample in samples:
        if previous is None:
            previous = sample
            continue
        elapsed = sample.get("uptime_seconds", 0) - previous.get("uptime_seconds", 0)
        if elapsed <= 0:
            previous = sample
            continue
        sample["elapsed_seconds"] = elapsed
        current_cpus = sample.get("system_cpus", {})
        prior_cpus = previous.get("system_cpus", {})
        cpu_percent: dict[str, float] = {}
        core_percent: dict[str, float] = {}
        for name, values in current_cpus.items():
            before = prior_cpus.get(name)
            if before is None:
                continue
            total, idle = cpu_counters(values)
            old_total, old_idle = cpu_counters(before)
            delta_total, delta_idle = total - old_total, idle - old_idle
            if delta_total > 0:
                busy = max(0, delta_total - delta_idle)
                if name == "cpu":
                    cpu_percent["machine_utilization_percent"] = busy * 100.0 / delta_total
                    cpu_percent["busy_percent_cores"] = busy * 100.0 / (sample.get("clk_tck", 100) * elapsed)
                else:
                    core_percent[name] = busy * 100.0 / delta_total
        if cpu_percent:
            sample["cpu"] = cpu_percent
        if core_percent:
            sample["per_core_cpu_percent"] = core_percent

        ticks = sample.get("clk_tck", previous.get("clk_tck", 100)) or 100
        process_rates: dict[str, Any] = {}
        for pid, proc in sample.get("processes", {}).items():
            old_proc = previous.get("processes", {}).get(pid)
            if not old_proc or proc.get("starttime_ticks") != old_proc.get("starttime_ticks"):
                continue
            cpu_delta = (proc["utime_ticks"] + proc["stime_ticks"]) - (old_proc["utime_ticks"] + old_proc["stime_ticks"])
            proc["cpu_percent_one_core_100"] = max(0.0, cpu_delta * 100.0 / ticks / elapsed)
            proc["major_faults_per_second"] = delta_rate(proc.get("majflt"), old_proc.get("majflt"), elapsed)
            proc["minor_faults_per_second"] = delta_rate(proc.get("minflt"), old_proc.get("minflt"), elapsed)
            old_status = old_proc.get("status", {})
            status = proc.get("status", {})
            proc["voluntary_context_switches_per_second"] = delta_rate(parse_int(status.get("voluntary_ctxt_switches", "")), parse_int(old_status.get("voluntary_ctxt_switches", "")), elapsed)
            proc["nonvoluntary_context_switches_per_second"] = delta_rate(parse_int(status.get("nonvoluntary_ctxt_switches", "")), parse_int(old_status.get("nonvoluntary_ctxt_switches", "")), elapsed)
            try:
                proc["rss_kb"] = parse_int(status.get("VmRSS", ""))
                proc["swap_kb"] = parse_int(status.get("VmSwap", ""))
            except (TypeError, ValueError):
                pass
            thread_rates: dict[str, float] = {}
            for tid, task in proc.get("tasks", {}).items():
                old_task = old_proc.get("tasks", {}).get(tid)
                if not old_task or task.get("starttime_ticks") != old_task.get("starttime_ticks"):
                    continue
                thread_delta = (task["utime_ticks"] + task["stime_ticks"]) - (old_task["utime_ticks"] + old_task["stime_ticks"])
                thread_rates[tid] = max(0.0, thread_delta * 100.0 / ticks / elapsed)
            proc["task_cpu_percent_one_core_100"] = thread_rates
            process_rates[pid] = proc["cpu_percent_one_core_100"]
        sample["process_cpu_percent_one_core_100"] = process_rates

        prior_vm = previous.get("vmstat", {})
        sample["vmstat_per_second"] = {
            key: delta_rate(value, prior_vm.get(key), elapsed)
            for key, value in sample.get("vmstat", {}).items()
            if prior_vm.get(key) is not None
        }
        if "ctxt" in sample and "ctxt" in previous:
            sample["context_switches_per_second"] = delta_rate(sample["ctxt"], previous["ctxt"], elapsed)
        previous = sample


def make_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    app_samples: list[tuple[float, float, float | None, float | None]] = []
    for sample in samples:
        for proc in sample.get("processes", {}).values():
            if proc.get("role") == "app":
                app_samples.append((
                    sample.get("uptime_seconds", 0),
                    proc.get("cpu_percent_one_core_100", 0.0),
                    proc.get("rss_kb"),
                    proc.get("swap_kb"),
                ))
    measured_cpu = [row[1] for row in app_samples if row[0] != (samples[0].get("uptime_seconds") if samples else None)]
    result: dict[str, Any] = {
        "sample_count": len(samples),
        "duration_seconds": round(samples[-1]["uptime_seconds"] - samples[0]["uptime_seconds"], 3) if len(samples) > 1 else 0.0,
        "ppsspp_seen": bool(app_samples),
    }
    if measured_cpu:
        result["ppsspp_cpu_percent_one_core_100_mean"] = round(statistics.mean(measured_cpu), 2)
        result["ppsspp_cpu_percent_one_core_100_max"] = round(max(measured_cpu), 2)
    if app_samples:
        result["ppsspp_last_rss_kb"] = app_samples[-1][2]
        result["ppsspp_last_swap_kb"] = app_samples[-1][3]
    proxy_count = max((sum(proc.get("role") == "proxy" for proc in s.get("processes", {}).values()) for s in samples), default=0)
    result["proxy_processes_seen_max"] = proxy_count
    if samples:
        result["last_loadavg"] = samples[-1].get("loadavg")
        result["last_cpu_online"] = samples[-1].get("cpu_online")
        result["last_lgpm"] = samples[-1].get("lgpm", {})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="sampler output file; defaults to stdin")
    parser.add_argument("--json-out", type=Path, help="write formatted JSON to this file (otherwise stdout)")
    args = parser.parse_args()
    if args.input:
        with args.input.open("r", encoding="utf-8", errors="replace") as stream:
            samples = read_blocks(stream)
    else:
        samples = read_blocks(sys.stdin)
    enrich(samples)
    payload = {
        "format": "ppsspp-webos-system-sampler-v1",
        "clock_note": "Process and thread CPU are percent of one logical CPU (100% = one full core). System machine_utilization_percent is normalized across all online CPUs.",
        "samples": samples,
        "summary": make_summary(samples),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
        destination = str(args.json_out)
    else:
        print(rendered)
        destination = "stdout"
    summary = payload["summary"]
    if summary["ppsspp_seen"]:
        if "ppsspp_cpu_percent_one_core_100_mean" in summary:
            cpu_text = f"mean={summary['ppsspp_cpu_percent_one_core_100_mean']:.1f}% max={summary['ppsspp_cpu_percent_one_core_100_max']:.1f}% of one core"
        else:
            cpu_text = "no interval CPU sample"
        mem_text = f"RSS={summary.get('ppsspp_last_rss_kb')} KiB Swap={summary.get('ppsspp_last_swap_kb')} KiB"
        message = f"{summary['sample_count']} samples / {summary['duration_seconds']:.1f}s; PPSSPP CPU {cpu_text}; {mem_text}; JSON: {destination}"
    else:
        message = f"{summary['sample_count']} samples / {summary['duration_seconds']:.1f}s; PPSSPP not running; JSON: {destination}"
    print(message, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
