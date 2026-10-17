"""Markdown tables for results/week3/SUMMARY.md, straight from the CSVs.

    python analysis/summarize_week3.py > backend/results/week3/SUMMARY_tables.md
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired import load, paired  # noqa: E402

RES = Path(__file__).resolve().parents[1] / "backend" / "results" / "week3"
SWEEPS = [  # (csv stem, sweep column, heading)
    ("write_sweep_200k", "write_ratio", "Write ratio (leveling, 48-key blocks)"),
    ("scan_sweep_200k", "scan_share", "Scan share at 50% writes"),
    ("size_sweep_200k", "cache_frac", "Cache size (fraction of data) at 50% writes"),
    ("zipf_sweep_200k", "zipf", "Zipf skew at 50% writes"),
    ("tiering_write_200k", "write_ratio", "Write ratio, tiering"),
    ("block16_write_200k", "write_ratio", "Write ratio, 16-key blocks (sensitivity)"),
    ("warm160k_write_200k", "write_ratio", "Robustness: 160K warm-up, 50% writes"),
    ("rules_write_200k", "write_ratio", "Decision rules for maintained groups (vs zio-naive)"),
]
MAIN = ["none", "block", "range", "group", "zio-naive", "group+seed", "group+complete",
        "zio-lrus", "zio-hot", "zio-naive-tail", "zio-lrus-tail", "zio-hot-tail"]
PAIRS = [("zio-naive", "group"), ("zio-naive", "block"), ("zio-naive", "range"),
         ("group", "block"), ("group", "range"), ("group+seed", "group"),
         ("group+complete", "group"), ("zio-naive", "group+seed"),
         ("zio-lrus", "zio-naive"), ("zio-hot", "zio-naive"), ("zio-naive-tail", "zio-naive"),
         ("zio-lrus-tail", "zio-naive"), ("zio-hot-tail", "zio-naive"),
         ("zio-lrus", "group"), ("zio-hot", "group"), ("zio-naive-tail", "group"),
         ("zio-lrus-tail", "group"), ("zio-hot-tail", "group")]


def main():
    for stem, col, head in SWEEPS:
        f = RES / f"{stem}.csv"
        if not f.exists():
            print(f"## {head}\n\n_missing: {f.name}_\n")
            continue
        df = load([f])
        seeds = sorted(df.seed.unique())
        print(f"## {head}\n\nSource `{f.name}`; seeds {seeds[0]}-{seeds[-1]} (n={len(seeds)}); "
              f"rows {len(df)}; block_size {[int(b) for b in sorted(df.block_size.unique())]}, "
              f"policy {sorted(df.policy.unique())}.\n")
        print("Mean query block reads per query:\n")
        caches = [c for c in MAIN if c in set(df.cache)]
        m = df.groupby([col, "cache"]).reads_per_query.mean().unstack()[caches]
        print("| " + col + " | " + " | ".join(caches) + " |")
        print("|" + "---|" * (len(caches) + 1))
        for x, r in m.iterrows():
            print(f"| {x:g} | " + " | ".join(f"{r[c]:.4f}" for c in caches) + " |")
        print("\nPaired reduction in reads per query, % (+ = first cache better), mean ± 95% CI;"
              " `*` = CI excludes 0; in brackets = seeds where the first cache is worse.\n")
        rows = [r for p in PAIRS for r in paired(df, col, *p)]
        pairs = [p for p in PAIRS if any(r["cand"] == p[0] and r["base"] == p[1] for r in rows)]
        print("| " + col + " | " + " | ".join(f"{a} vs {b}" for a, b in pairs) + " |")
        print("|" + "---|" * (len(pairs) + 1))
        for x in sorted({r["x"] for r in rows}):
            cells = []
            for a, b in pairs:
                r = next((r for r in rows if r["x"] == x and r["cand"] == a and r["base"] == b),
                         None)
                cells.append("-" if r is None else
                             f"{r['reduction']:+.2f} ± {r['ci']:.2f}{'*' if r['sig'] else ''}"
                             f" ({r['worse_seeds']}/{r['n']})")
            print(f"| {x:g} | " + " | ".join(cells) + " |")
        print()


if __name__ == "__main__":
    main()
