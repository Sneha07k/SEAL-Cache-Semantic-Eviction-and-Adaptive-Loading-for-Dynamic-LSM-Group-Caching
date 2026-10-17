import argparse
import math
import statistics
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.experiments.common import ci95  # noqa: E402  (t-based half-width, same as the runner)

DEFAULT_PAIRS = ["zio-naive:group", "zio-naive:block", "zio-naive:range", "zio-naive:none",
                 "group:block", "group:range", "group:none",
                 "group+seed:group", "group+complete:group"]


def paired(df, param, cand, base):
    """Rows (one per sweep value) of the paired comparison cand vs base."""
    out = []
    for x, g in df.groupby(param):
        piv = g.pivot_table(index="seed", columns="cache", values="reads_per_query",
                            aggfunc="mean")          # mean only collapses accidental repeats
        if cand not in piv or base not in piv:
            continue
        both = piv[[cand, base]].dropna()
        if len(both) < 2:
            continue
        red = 100 * (1 - both[cand] / both[base])
        hw = ci95(list(red))
        out.append(dict(x=x, cand=cand, base=base, n=len(both),
                        base_rpq=both[base].mean(), cand_rpq=both[cand].mean(),
                        reduction=red.mean(), ci=hw, sig=abs(red.mean()) > hw,
                        worse_seeds=int((red < 0).sum())))
    return out


def load(paths):
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    dup = df.duplicated(["cache", "seed"] + [c for c in df.columns
                                            if c in ("write_ratio", "scan_share", "cache_frac",
                                                     "zipf", "policy", "block_size")])
    if dup.any():
        sys.exit(f"{int(dup.sum())} duplicated (cache, seed, setting) rows: refusing to pool")
    return df


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--param", required=True, help="sweep column, e.g. write_ratio")
    ap.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="cand:base,cand:base")
    ap.add_argument("--out", default=None, help="also write the table as CSV")
    p = ap.parse_args(argv)
    df = load(p.csv)
    rows = []
    for pair in p.pairs.split(","):
        cand, base = pair.split(":")
        rows += paired(df, p.param, cand, base)
    if not rows:
        sys.exit("no comparable (candidate, baseline) pairs found")
    res = pd.DataFrame(rows)
    print(f"Paired reduction in query block reads per query, % (+ = candidate better), "
          f"mean ± 95% CI over seeds; * = CI excludes 0")
    print(f"{p.param:>11} {'candidate vs baseline':>26} {'n':>3} {'base rpq':>9} "
          f"{'reduction %':>16} {'worse seeds':>12}")
    for _, r in res.sort_values(["x", "cand", "base"]).iterrows():
        tag = "*" if r.sig else " "
        print(f"{r.x:>11} {r.cand + ' vs ' + r.base:>26} {r.n:>3} {r.base_rpq:>9.4f} "
              f"{r.reduction:>+9.2f} ±{r.ci:5.2f}{tag} {r.worse_seeds:>8}/{r.n}")
    if p.out:
        res.to_csv(p.out, index=False)
        print(f"\nTable: {p.out}")


if __name__ == "__main__":
    main()
