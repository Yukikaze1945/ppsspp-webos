"""Align flip gaps with sampled thread run/runqueue time and slow proxy calls.

Thread counters are apportioned linearly within each sampling interval. This is
an estimate, not a precise blocked-stack attribution.
"""
import argparse
import collections
import json
from pathlib import Path

def read(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]

def align(prefix):
    prefix=Path(prefix)
    frames=read(str(prefix)+'.frames.jsonl')
    threads=read(str(prefix)+'.threads.jsonl')
    slowpath=Path(str(prefix)+'.proxy.slow.jsonl')
    slow=read(slowpath) if slowpath.exists() else []
    tasks=collections.defaultdict(list)
    for row in threads: tasks[(row['pid'],row['tid'],row['name'])].append(row)
    biggest=sorted([r for r in frames if r.get('mono_ns') and r['timing']['frames']],
        key=lambda r:r['timing']['frames'][0],reverse=True)[:5]
    results=[]
    for frame in biggest:
        end=frame['mono_ns']; start=end-frame['timing']['frames'][0]*1e9
        task_results=[]
        for (pid,tid,name),rows in tasks.items():
            if name!='EmuThread' and pid!=tid: continue
            run=wait=coverage=0
            for a,b in zip(rows,rows[1:]):
                dt=b['mono_ns']-a['mono_ns']
                overlap=max(0,min(end,b['mono_ns'])-max(start,a['mono_ns']))
                if not dt or not overlap: continue
                fraction=overlap/dt
                run+=max(0,b['run_ns']-a['run_ns'])*fraction
                wait+=max(0,b['wait_ns']-a['wait_ns'])*fraction
                coverage+=overlap
            task_results.append(dict(pid=pid,tid=tid,name=name,coverage_ms=coverage/1e6,
                run_ms=run/1e6,runqueue_ms=wait/1e6,
                remaining_ms=max(0,coverage-run-wait)/1e6))
        events=[r for r in slow if start<=r['mono_ns']<=end]
        results.append(dict(start_s=start/1e9,end_s=end/1e9,frame_ms=(end-start)/1e6,
            threads=task_results,slow_proxy_calls=events))
    return dict(note=__doc__,slow_log_available=slowpath.exists(),hitches=results)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('prefix');p.add_argument('--output',required=True)
    a=p.parse_args()
    Path(a.output).write_text(json.dumps(align(a.prefix),indent=2)+'\n',encoding='utf-8')
