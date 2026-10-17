"""Week-1 GO/NO-GO experiment.

Question: how many query block reads does Group Cache lose, as writes increase, that
zero-I/O maintenance could recover?  We run IDENTICAL traces through:
    none          no cache (reference for how many reads a cache can save at all)
    group_cache   faithful baseline (Case-2 groups discarded, flushes not seeded)
    +complete     naive: Case-2 groups completed from the compaction stream
    +seed         naive: new L0 runs seeded for currently cached ranges
    +both         naive: both
All caches get the same byte budget. The naive variants have NO size-aware rule yet,
so they can also do worse (completed/seeded groups may push out better groups).

Main metric: query block reads per query (lower is better).

    python -m app.experiments.motivation                 # default sweep
    python -m app.experiments.motivation --quick         # smoke run
"""
import argparse
import csv
import math
import random
import statistics
import time
from pathlib import Path

from ..config import LSMConfig
from ..lsm.engine import LSMEngine
from ..cache.group_cache import GroupCache
from ..workload.generator import generate

VARIANTS = {
    "none": None,
    "group_cache": dict(),
    "+complete": dict(complete_on_compaction=True),
    "+seed": dict(seed_on_flush=True),
    "+both": dict(complete_on_compaction=True, seed_on_flush=True),
}
# Two-sided 95% t critical values by degrees of freedom.
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26,
       10: 2.23, 14: 2.14, 19: 2.09, 29: 2.05}


def ci95(xs):
    if len(xs) < 2:
        return 0.0
    df = len(xs) - 1
    t = T95.get(df) or T95[max(k for k in T95 if k <= df)]
    return t * statistics.stdev(xs) / math.sqrt(len(xs))


def run_one(variant, write_ratio, seed, p):
    cfg = LSMConfig(block_size=p.block_size, memtable_size=p.memtable, size_ratio=10,
                    l0_run_limit=4, l1_capacity=p.memtable * 10, policy=p.policy)
    eng = LSMEngine(cfg)
    if VARIANTS[variant] is not None:
        data_bytes = p.keys * (8 + 256)
        eng.attach_cache(GroupCache(int(data_bytes * p.cache_frac), seed=seed,
                                    **VARIANTS[variant]))
    # Load: every key once, in random order (same order for every variant).
    order = list(range(p.keys))
    random.Random(seed).shuffle(order)
    for k in order:
        eng.put(k, f"init{k}")

    scan_ratio = p.scan_share * (1 - write_ratio)     # share of reads that are scans
    mix = dict(write_ratio=write_ratio, delete_ratio=0.0, scan_ratio=scan_ratio,
               scan_len=(10, 100), zipf_theta=p.zipf)
    for op in generate(p.warmup, p.keys, seed + 1000, **mix):
        getattr(eng, op[0])(*op[1:])

    measured = generate(p.ops, p.keys, seed, **mix)
    before = eng.io.snapshot()
    for op in measured:
        getattr(eng, op[0])(*op[1:])
    after = eng.io.snapshot()
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    queries = sum(op[0] in ("get", "scan") for op in measured)
    reads = delta.get("point_read", 0) + delta.get("scan_read", 0)
    row = dict(variant=variant, write_ratio=write_ratio, seed=seed, queries=queries,
               query_reads=reads, reads_per_query=reads / max(queries, 1),
               compactions=eng.stats["compactions"])
    if eng.cache is not None:
        s = eng.cache.stats
        row.update(run_hit_rate=s["run_hits"] / max(s["run_probes"], 1),
                   case2_discarded=s["case2_discarded"], case2_completed=s["case2_completed"],
                   case1_kept=s["case1_kept"], flush_seeded=s["flush_seeded"],
                   cache_bytes=eng.cache.bytes)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keys", type=int, default=50_000)
    ap.add_argument("--ops", type=int, default=40_000)
    ap.add_argument("--warmup", type=int, default=20_000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--block-size", type=int, default=32)
    ap.add_argument("--memtable", type=int, default=1024)
    ap.add_argument("--cache-frac", type=float, default=0.05)
    ap.add_argument("--zipf", type=float, default=0.8)
    ap.add_argument("--scan-share", type=float, default=0.2,
                    help="fraction of reads that are scans (Group Cache default 0.2)")
    ap.add_argument("--policy", default="leveling")
    ap.add_argument("--write-ratios", default="0,0.2,0.5,0.8")
    ap.add_argument("--out", default="results/motivation.csv")
    ap.add_argument("--quick", action="store_true")
    p = ap.parse_args(argv)
    if p.quick:
        p.keys, p.ops, p.warmup, p.seeds, p.memtable = 5000, 4000, 2000, 2, 256

    rows = []
    t0 = time.time()
    for w in [float(x) for x in p.write_ratios.split(",")]:
        for seed in range(p.seeds):
            for v in VARIANTS:
                rows.append(run_one(v, w, seed, p))
        print(f"  write ratio {w:.1f} done ({time.time() - t0:.0f}s)", flush=True)

    out = Path(p.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r})
    with out.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)

    print(f"\nQuery block reads per query (mean ± 95% CI over {p.seeds} seeds; lower is better)")
    print(f"{'write':>6} " + " ".join(f"{v:>16}" for v in VARIANTS)
          + f" {'GC vs none':>11} {'+both vs GC':>12}")
    for w in sorted({r['write_ratio'] for r in rows}):
        cells, means = [], {}
        for v in VARIANTS:
            xs = [r["reads_per_query"] for r in rows if r["variant"] == v and r["write_ratio"] == w]
            means[v] = statistics.mean(xs)
            cells.append(f"{means[v]:8.3f} ±{ci95(xs):5.3f}")
        saved_gc = 1 - means["group_cache"] / means["none"]
        gain = 1 - means["+both"] / means["group_cache"]
        print(f"{w:>6.1f} " + " ".join(f"{c:>16}" for c in cells)
              + f" {saved_gc:>10.1%} {gain:>11.1%}")
    print(f"\nRaw rows: {out}")


if __name__ == "__main__":
    main()
