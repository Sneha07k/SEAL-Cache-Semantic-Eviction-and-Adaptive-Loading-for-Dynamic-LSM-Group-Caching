"""Fidelity check: does our Group Cache reproduce the TRENDS its paper reports?

Paper claims tested (Wang et al., SIGMOD 2026), all at equal memory:
  scan     Fig. 7: group beats block and range; with 0% scans range ~= group (both act as
           KV caches); the advantage shrinks as the scan share grows.
  write    Fig. 11: group stays best as writes grow; range approaches group; block suffers
           most from compaction invalidation.
  size     p.47:3: block cache needs ~4x the memory to match group.
The paper reports throughput/latency on RocksDB; we compare block reads in a simulator,
so only the DIRECTION and rough size of effects can be checked.

    python -m app.experiments.fidelity --sweep scan|write|size|zipf [--seeds 3] [--quick]
"""
import argparse
import csv
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .common import run_trace, summarize

BASE = ["none", "block", "range", "group"]
SWEEPS = {
    "scan": ("scan_share", [0.0, 0.2, 0.5, 0.8], dict(write_ratio=0.0)),
    "write": ("write_ratio", [0.0, 0.2, 0.5, 0.8], dict(scan_share=0.2)),
    "size": ("cache_frac", [0.01, 0.05, 0.1, 0.2], dict(write_ratio=0.0, scan_share=0.2)),
    "zipf": ("zipf", [0.6, 0.8, 0.99], dict(write_ratio=0.0, scan_share=0.2)),
}


def _one(cache, seed, kw):
    return run_trace(cache, seed, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", choices=SWEEPS, required=True)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--caches", default=",".join(BASE))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--block-size", type=int, default=16)
    ap.add_argument("--policy", default="leveling")
    ap.add_argument("--granularity", default="file", choices=["file", "level"])
    ap.add_argument("--seed-offset", type=int, default=0,
                    help="first seed (use a disjoint range to validate tuned choices)")
    ap.add_argument("--values", default=None, help="override the sweep values, e.g. 0.5,0.8")
    ap.add_argument("--insert-share", type=float, default=0.0,
                    help="share of writes that insert NEW keys (paper Sec. 7.2 uses 0.5)")
    ap.add_argument("--write-ratio", type=float, default=None,
                    help="override the fixed write ratio of the scan/size/zipf sweeps "
                         "(week-3 sweeps use 0.5)")
    ap.add_argument("--keys", type=int, default=None, help="loaded keys (default 50000)")
    ap.add_argument("--warmup", type=int, default=None, help="warm-up ops (default 20000)")
    ap.add_argument("--ops", type=int, default=None, help="measured ops (default 40000)")
    ap.add_argument("--workers", type=int, default=1,
                    help="processes; every run keeps its own seed, so results are identical "
                         "to --workers 1 (rows keep the same order)")
    ap.add_argument("--out", default=None)
    p = ap.parse_args(argv)
    param, values, fixed = SWEEPS[p.sweep]
    fixed = dict(fixed)
    if p.write_ratio is not None:
        if param == "write_ratio":
            ap.error("--write-ratio conflicts with --sweep write")
        fixed["write_ratio"] = p.write_ratio
    if p.values:
        values = [float(x) for x in p.values.split(",")]
    caches = p.caches.split(",")
    size = dict(keys=5000, warmup=2000, ops=4000, memtable=256) if p.quick else {}
    size.update({k: v for k, v in (("keys", p.keys), ("warmup", p.warmup), ("ops", p.ops))
                 if v is not None})
    size.update(block_size=p.block_size, policy=p.policy, granularity=p.granularity,
                insert_share=p.insert_share)

    rows, t0 = [], time.time()
    pool = ProcessPoolExecutor(p.workers) if p.workers > 1 else None
    for v in values:
        jobs = [(c, seed) for seed in range(p.seed_offset, p.seed_offset + p.seeds)
                for c in caches]
        if pool:
            futs = [pool.submit(_one, c, seed, {param: v, **fixed, **size}) for c, seed in jobs]
            rows.extend(f.result() for f in futs)
        else:
            rows.extend(_one(c, seed, {param: v, **fixed, **size}) for c, seed in jobs)
        print(f"  {param}={v} done ({time.time() - t0:.0f}s)", flush=True)
    if pool:
        pool.shutdown()

    out = Path(p.out or f"results/fidelity_{p.sweep}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r})
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    s = summarize(rows, param, caches)
    print(f"\nQuery block reads per query, mean ± 95% CI ({p.seeds} seeds). Lower is better.")
    print(f"{param:>11} " + " ".join(f"{c:>15}" for c in caches)
          + "   block/group  range/group")
    for v in values:
        cells = [f"{s[(v, c)][0]:7.3f} ±{s[(v, c)][1]:5.3f}" for c in caches]
        g = s[(v, "group")][0]
        ratios = "".join(f" {s[(v, c)][0] / g:>10.2f}x" if (v, c) in s else f" {'-':>11}"
                         for c in ("block", "range"))
        print(f"{v:>11} " + " ".join(f"{x:>15}" for x in cells) + "  " + ratios)
    print(f"\nRaw rows: {out}")


if __name__ == "__main__":
    main()
