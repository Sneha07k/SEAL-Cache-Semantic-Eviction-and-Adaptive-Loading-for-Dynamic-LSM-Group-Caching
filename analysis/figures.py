"""Write-sweep and generic sweep figures from the experiment CSVs.

    python analysis/figures.py backend/results/week3/write_sweep_200k.csv --outdir analysis/figures
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired import load, paired, ci95  # noqa: E402

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
STYLE = {   # cache -> (label, color, marker, linestyle)
    "zio-naive": ("zero-I/O maintenance (ours)", "#2a78d6", "o", "-"),
    "group": ("Group Cache", "#eb6834", "s", "-"),
    "block": ("Block cache", "#1baf7a", "^", "-"),
    "range": ("Range Cache", "#eda100", "D", "-"),
    "none": ("No cache", MUTED, "x", "--"),
    "group+seed": ("Group + flush seeding", "#e87ba4", "v", "-"),
    "group+complete": ("Group + completion", "#6250d6", "P", "-"),
}
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.axisbelow": True, "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "legend.frameon": False})


def stat(df, param, col, cache):
    """(x, mean, ci95 half-width) of a per-run column for one cache, over seeds."""
    g = df[df.cache == cache].dropna(subset=[col]).groupby(param)[col]   # NaN = undefined
    xs = sorted(g.groups)
    return xs, [g.mean()[x] for x in xs], [ci95(list(g.get_group(x))) for x in xs]


def line(ax, xs, ys, es, cache, label=True):
    lab, col, mk, ls = STYLE[cache]
    ax.errorbar(xs, ys, yerr=es, color=col, marker=mk, ls=ls, lw=2, ms=6, capsize=2.5,
                elinewidth=1, mec="#fcfcfb", mew=1, label=lab if label else None)


def save(fig, outdir, name):
    for ext in ("png", "pdf"):
        fig.savefig(outdir / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("wrote", outdir / f"{name}.png")


def fig_write_sweep(df, param, outdir, xlabel):
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    for c in ("none", "block", "range", "group", "zio-naive"):
        if c in set(df.cache):
            line(ax, *stat(df, param, "reads_per_query", c), c)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("query block reads per query (lower is better)")
    ax.legend(fontsize=8)
    n = df.seed.nunique()
    ax.set_title(f"Mean ± 95% CI over {n} seeds", fontsize=8, color=INK2, loc="left")
    save(fig, outdir, "fig_write_sweep")


def fig_motivation(df, param, outdir, xlabel):
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.2))
    # (a) benefit over no cache, paired per seed
    ax = axs[0]
    for c in ("block", "range", "group", "zio-naive"):
        r = pd.DataFrame(paired(df, param, c, "none"))
        if len(r):
            line(ax, list(r.x), list(r.reduction), list(r.ci), c)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("reads saved vs no cache, % (paired)")
    ax.set_title("(a) Caching benefit as writes grow", fontsize=9, loc="left", color=INK)
    ax.legend(fontsize=7)
    # (b) Case-2 discards per compaction, measured window only (Group Cache baseline).
    # Cumulative stat_* would include load-phase compactions, when the cache is empty.
    ax = axs[1]
    g = df[df.cache == "group"].copy()
    if "meas_case2_discarded" in g:
        g["d"] = g.meas_case2_discarded / g.meas_compactions.where(g.meas_compactions > 0)  # 0 compactions: NaN
        line(ax, *stat(g, param, "d", "group"), "group", label=False)
        ax.set_ylabel("Case-2 ranges discarded / compaction")
        ax.set_ylim(bottom=0)
    ax.set_xlabel(xlabel)
    ax.set_title("(b) Case-2 discards (Group Cache)", fontsize=9, loc="left", color=INK)
    # (c) share of query reads that go to L0 (flushed, not yet compacted) runs
    ax = axs[2]
    if "qreads_L0_share" in df:
        for c in ("none", "block", "group"):
            line(ax, *stat(df, param, "qreads_L0_share", c), c)
        ax.set_ylabel("share of query reads served from L0 runs")
        ax.legend(fontsize=7)
    ax.set_xlabel(xlabel)
    ax.set_title("(c) Reads on fresh (L0) runs", fontsize=9, loc="left", color=INK)
    fig.tight_layout()
    save(fig, outdir, "fig_motivation")


def fig_overhead(df, param, outdir, xlabel):
    z = df[df.cache == "zio-naive"].copy()
    if "maint_byte_frac" not in z:
        print("overhead columns missing; skipped")
        return
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.2))
    ax = axs[0]
    for col, lab, mk in (("maint_byte_frac", "share of cache bytes held by maintained groups", "o"),
                         ("maint_hit_frac", "share of maintained groups hit at least once", "s")):
        xs, ys, es = stat(z, param, col, "zio-naive")
        ax.errorbar(xs, ys, yerr=es, color="#2a78d6", marker=mk, lw=2, ms=6, capsize=2.5,
                    ls="-" if mk == "o" else "--", mec="#fcfcfb", label=lab)
    ax.set_ylim(0, 1)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("fraction")
    ax.set_title("(a) Memory held / usefulness", fontsize=9, loc="left", color=INK)
    ax.legend(fontsize=7, loc="upper left")
    z["seed_kv_per_flush"] = z.meas_kv_copied_flush_seed / z.meas_flushes.clip(lower=1)
    z["comp_kv_per_compaction"] = z.meas_kv_copied_completed / z.meas_compactions.clip(lower=1)
    ax = axs[1]
    for col, lab, ls in (("seed_kv_per_flush", "flush seeding, per flush", "-"),
                         ("comp_kv_per_compaction", "completion, per compaction", "--")):
        xs, ys, es = stat(z, param, col, "zio-naive")
        ax.errorbar(xs, ys, yerr=es, color="#2a78d6", marker="o", lw=2, ms=6, capsize=2.5,
                    ls=ls, mec="#fcfcfb", label=lab)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("KVs copied into groups (CPU-work proxy)")
    ax.set_title("(b) In-memory copy work", fontsize=9, loc="left", color=INK)
    ax.legend(fontsize=7)
    ax = axs[2]
    for o, mk, ls in (("flush_seed", "o", "-"), ("completed", "s", "--")):
        cr = z[f"stat_groups_created_{o}"]
        z[f"unused_{o}"] = (z[f"stat_evicted_unused_{o}"] + z[f"stat_retired_unused_{o}"]
                            + z[f"resident_unused_{o}"]) / cr.where(cr > 0)   # 0 created: NaN
        xs, ys, es = stat(z, param, f"unused_{o}", "zio-naive")
        ax.errorbar(xs, ys, yerr=es, color="#2a78d6", marker=mk, lw=2, ms=6, capsize=2.5,
                    ls=ls, mec="#fcfcfb", label={"flush_seed": "flush-seeded",
                                                 "completed": "completed"}[o])
    ax.set_ylim(0, 1)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("fraction never hit")
    ax.set_title("(c) Maintained groups never used", fontsize=9, loc="left", color=INK)
    ax.legend(fontsize=7)
    fig.tight_layout()
    save(fig, outdir, "fig_overhead")


PAIR_PANEL = (("zio-naive", "group"), ("zio-naive", "block"), ("group", "block"),
              ("group+seed", "group"))


def fig_sweep(df, param, outdir, name, xlabel, logx=False, title=""):
    """Generic sweep figure: (a) reads per query per cache, (b) paired gains between caches.
    One axis per panel; panel (b) is the paired per-seed reduction with 95% CI."""
    fig, axs = plt.subplots(1, 2, figsize=(8.6, 4.0))
    ax = axs[0]
    for c in ("none", "block", "range", "group", "zio-naive"):
        if c in set(df.cache):
            line(ax, *stat(df, param, "reads_per_query", c), c)
    ax.set_ylabel("block reads per query (lower = better)")
    ax.set_title("(a) " + (title or "Reads per query"), fontsize=9, loc="left", color=INK)
    ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    ax = axs[1]
    styles = {("zio-naive", "group"): ("#2a78d6", "o", "-", "ours vs Group Cache"),
              ("zio-naive", "block"): ("#1baf7a", "^", "-", "ours vs block"),
              ("group", "block"): ("#eb6834", "s", "-", "Group Cache vs block"),
              ("group+seed", "group"): ("#e87ba4", "v", "--", "flush seeding only vs Group Cache")}
    for pair in PAIR_PANEL:
        r = pd.DataFrame(paired(df, param, *pair))
        if len(r):
            col, mk, ls, lab = styles[pair]
            ax.errorbar(list(r.x), list(r.reduction), yerr=list(r.ci), color=col, marker=mk,
                        ls=ls, lw=2, ms=6, capsize=2.5, elinewidth=1, mec="#fcfcfb", label=lab)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_ylabel("fewer reads, % (+ = first is better)")
    ax.set_title("(b) Paired gains, mean ± 95% CI", fontsize=9, loc="left", color=INK)
    ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    for a in axs:
        a.set_xlabel(xlabel)
        if logx:
            a.set_xscale("log")
            a.set_xticks(sorted(set(df[param])))
            a.set_xticklabels([f"{v:g}" for v in sorted(set(df[param]))])
    fig.tight_layout()
    save(fig, outdir, name)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--kind", choices=["write", "sweep"], default="write",
                    help="write = the 3 write-sweep figures; sweep = one generic sweep figure")
    ap.add_argument("--param", default="write_ratio")
    ap.add_argument("--name", default=None, help="output name for --kind sweep, e.g. fig_scan")
    ap.add_argument("--title", default="")
    ap.add_argument("--logx", action="store_true")
    ap.add_argument("--xlabel", default="write ratio (50% inserts / 50% updates)")
    ap.add_argument("--outdir", default="analysis/figures")
    p = ap.parse_args(argv)
    df = load(p.csv)
    out = Path(p.outdir)
    out.mkdir(parents=True, exist_ok=True)
    if p.kind == "sweep":
        fig_sweep(df, p.param, out, p.name or f"fig_{p.param}", p.xlabel, p.logx, p.title)
        return
    fig_write_sweep(df, p.param, out, p.xlabel)
    fig_motivation(df, p.param, out, p.xlabel)
    fig_overhead(df, p.param, out, p.xlabel)


if __name__ == "__main__":
    main()
