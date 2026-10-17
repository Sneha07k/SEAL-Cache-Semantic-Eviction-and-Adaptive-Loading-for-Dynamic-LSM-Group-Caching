"""Warm-up calibration (not a result). Rule, fixed beforehand: smallest warm-up W where W -> 2W
changes mean reads/query by < 1% for group and zio-naive. Seeds 100-102.

    python -m app.experiments.calibrate_warmup --workers 12
"""
import argparse
import csv
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .common import run_trace


def _one(cache, seed, kw):
    return run_trace(cache, seed, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", type=int, default=200_000)
    ap.add_argument("--ops", type=int, default=40_000)
    ap.add_argument("--warmups", default="20000,40000,80000,160000")
    ap.add_argument("--caches", default="group,zio-naive,block")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seed-offset", type=int, default=100)
    ap.add_argument("--write-ratio", type=float, default=0.5)
    ap.add_argument("--block-size", type=int, default=48)
    ap.add_argument("--insert-share", type=float, default=0.5,
                    help="0.5 = paper mix; 0 is a diagnostic only (no database growth)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", default="results/week3/calibrate_warmup.csv")
    p = ap.parse_args(argv)
    warmups = [int(x) for x in p.warmups.split(",")]
    caches = p.caches.split(",")
    seeds = range(p.seed_offset, p.seed_offset + p.seeds)
    base = dict(keys=p.keys, ops=p.ops, write_ratio=p.write_ratio, insert_share=p.insert_share,
                block_size=p.block_size)

    jobs = [(c, s, w) for w in warmups for s in seeds for c in caches]
    with ProcessPoolExecutor(p.workers) as pool:
        futs = [pool.submit(_one, c, s, dict(base, warmup=w)) for c, s, w in jobs]
        rows = []
        for (c, s, w), f in zip(jobs, futs):
            r = f.result()
            r["warmup"] = w
            rows.append(r)

    out = Path(p.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        wr.writeheader()
        wr.writerows(rows)

    def mean(c, w):
        return statistics.mean(r["reads_per_query"] for r in rows
                               if r["cache"] == c and r["warmup"] == w)

    print(f"keys={p.keys} measured ops={p.ops} write_ratio={p.write_ratio} "
          f"seeds={list(seeds)} (mean reads/query; % = change vs previous warm-up)")
    print(f"{'warmup':>8} " + " ".join(f"{c:>20}" for c in caches) + "   zio gain vs group")
    for i, w in enumerate(warmups):
        cells = []
        for c in caches:
            m = mean(c, w)
            d = f" ({100 * (m / mean(c, warmups[i - 1]) - 1):+.2f}%)" if i else ""
            cells.append(f"{m:.4f}{d}")
        gain = ""
        if "group" in caches and "zio-naive" in caches:
            gain = f"{100 * (1 - mean('zio-naive', w) / mean('group', w)):+.2f}%"
        print(f"{w:>8} " + " ".join(f"{x:>20}" for x in cells) + f"   {gain}")
    chosen = None
    for i, w in enumerate(warmups[:-1]):
        if all(abs(mean(c, warmups[i + 1]) / mean(c, w) - 1) < 0.01
               for c in caches if c in ("group", "zio-naive")):
            chosen = w
            break
    print(f"\nRule (<1% change on doubling, group and zio-naive): "
          f"{'smallest warm-up = %d' % chosen if chosen else 'NOT met within the range tried'}")
    print(f"Raw rows: {out}")


if __name__ == "__main__":
    main()
