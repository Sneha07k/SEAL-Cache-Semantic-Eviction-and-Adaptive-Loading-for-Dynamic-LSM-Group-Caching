"""Read-only aggregation of backend/results/**/*.csv for the UI (mean, 95% CI, paired reductions).
"""
import csv
import re
import statistics
from pathlib import Path

from .experiments.common import ci95

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"
SWEEP_COLUMNS = ("write_ratio", "scan_share", "cache_frac", "zipf")
CONSTANT_COLUMNS = SWEEP_COLUMNS + ("block_size", "policy", "granularity", "insert_share")
REQUIRED = {"cache", "seed", "reads_per_query"}
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-/]+\.csv$")


def _read(path):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        if not REQUIRED <= cols:
            return None, None
        return cols, list(reader)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f                 # NaN = undefined; JSON has no NaN


def _sweep_param(rows):
    for c in SWEEP_COLUMNS:
        if len({r.get(c) for r in rows}) > 1:
            return c
    return None


def list_results():
    out = []
    for p in sorted(RESULTS_DIR.rglob("*.csv")):
        cols, rows = _read(p)
        if rows is None or not rows:
            continue
        rel = p.relative_to(RESULTS_DIR).as_posix()
        out.append({"name": rel, "rows": len(rows), "param": _sweep_param(rows),
                    "seeds": len({r["seed"] for r in rows}),
                    "caches": sorted({r["cache"] for r in rows}),
                    "archived": "mismatched_warmup" in rel,
                    "bytes": p.stat().st_size, "modified": int(p.stat().st_mtime)})
    return out


def load_result(name):
    if not NAME_RE.match(name) or ".." in name:
        raise ValueError("bad result name")
    path = (RESULTS_DIR / name).resolve()
    if RESULTS_DIR.resolve() not in path.parents or not path.is_file():
        raise ValueError("no such result file")
    cols, rows = _read(path)
    if rows is None:
        raise ValueError("not an experiment CSV (needs cache, seed, reads_per_query)")
    param = _sweep_param(rows)
    caches = sorted({r["cache"] for r in rows})
    xs = sorted({_num(r[param]) for r in rows}) if param else [None]
    seeds = sorted({int(float(r["seed"])) for r in rows})

    def vals(cache, x, col="reads_per_query"):
        """{seed: value} for one cache at one sweep value."""
        return {int(float(r["seed"])): _num(r.get(col)) for r in rows
                if r["cache"] == cache and (param is None or _num(r[param]) == x)
                and _num(r.get(col)) is not None}

    series = {}
    for c in caches:
        series[c] = [{"x": x, "mean": statistics.mean(v.values()), "ci": ci95(list(v.values())),
                      "per_seed": v, "n": len(v)}
                     for x in xs if (v := vals(c, x))]
    paired = {}
    for cand in caches:
        for base in caches:
            if cand == base:
                continue
            pts = []
            for x in xs:
                a, b = vals(cand, x), vals(base, x)
                red = [100 * (1 - a[s] / b[s]) for s in a if s in b and b[s]]
                if len(red) >= 2:
                    m = statistics.mean(red)
                    hw = ci95(red)
                    pts.append({"x": x, "reduction": m, "ci": hw, "n": len(red),
                                "worse_seeds": sum(r < 0 for r in red),
                                "significant": abs(m) > hw})
            if pts:
                paired[f"{cand}|{base}"] = pts
    meta = {c: sorted({r[c] for r in rows}) for c in CONSTANT_COLUMNS if c in cols}
    extras = {}
    for col in ("qreads_L0_share", "maint_byte_frac", "maint_hit_frac"):
        if col in cols:
            extras[col] = {c: [{"x": x, "mean": statistics.mean(v.values())}
                               for x in xs if (v := vals(c, x, col))]
                           for c in caches}
            extras[col] = {c: p for c, p in extras[col].items() if p}
    return {"name": name, "param": param, "xs": xs, "caches": caches, "seeds": seeds,
            "series": series, "paired": paired, "meta": meta, "extras": extras,
            "archived": "mismatched_warmup" in name}
