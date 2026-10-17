"""Shared experiment machinery: identical engines, traces and metrics for every cache.

Every run: load all keys once (random order) -> warm-up ops -> measured ops.
Main metric: query block reads per query (gets + scans), lower is better.
"""
import math
import random
import statistics

from ..config import LSMConfig
from ..lsm.engine import LSMEngine
from ..cache.group_cache import GroupCache, MAINT_ORIGINS
from ..cache.block_cache import BlockCache
from ..cache.range_cache import RangeCache
from ..workload.generator import generate

KEY_BYTES, VALUE_BYTES = 8, 256          # Group Cache paper's setting (p.47:14)
MAX_LEVELS = 8                           # per-level read columns qreads_L0..L7

CACHES = {
    "none": None,
    "block": ("run", BlockCache, {}),
    "range": ("query", RangeCache, {}),
    "group": ("run", GroupCache, {}),
    "group+complete": ("run", GroupCache, dict(complete_on_compaction=True)),
    "group+seed": ("run", GroupCache, dict(seed_on_flush=True)),
    "group+both": ("run", GroupCache, dict(complete_on_compaction=True, seed_on_flush=True)),
    # Our mechanism with a decision rule (naive / lrus / hot) and placement (inherit / tail).
    **{f"zio-{rule}{'-tail' if pri == 'tail' else ''}":
       ("run", GroupCache, dict(complete_on_compaction=True, seed_on_flush=True,
                                zio_rule=rule, zio_priority=pri))
       for rule in ("naive", "lrus", "hot") for pri in ("inherit", "tail")},
    # Diagnostics (not from the paper): plain-LRU admission instead of LRU-S.
    "group-lru": ("run", GroupCache, dict(admission="always")),
    "group-lru+both": ("run", GroupCache, dict(admission="always", complete_on_compaction=True,
                                               seed_on_flush=True)),
}

T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26,
       10: 2.23, 14: 2.14, 19: 2.09, 29: 2.05}


def ci95(xs):
    """Half-width of a two-sided 95% t confidence interval."""
    if len(xs) < 2:
        return 0.0
    df = len(xs) - 1
    t = T95.get(df) or T95[max(k for k in T95 if k <= df)]
    return t * statistics.stdev(xs) / math.sqrt(len(xs))


def build_engine(cache, keys, cache_frac, block_size=16, memtable=1024, policy="leveling",
                 seed=0, granularity="file"):
    cfg = LSMConfig(block_size=block_size, memtable_size=memtable, size_ratio=10,
                    l0_run_limit=4, l1_capacity=memtable * 10, policy=policy,
                    granularity=granularity)
    eng = LSMEngine(cfg)
    spec = CACHES[cache]
    if spec is not None:
        kind, cls, kw = spec
        capacity = int(keys * (KEY_BYTES + VALUE_BYTES) * cache_frac)
        obj = cls(capacity, key_bytes=KEY_BYTES, value_bytes=VALUE_BYTES, seed=seed, **kw)
        (eng.attach_cache if kind == "run" else eng.attach_query_cache)(obj)
    return eng


def with_inserts(ops, insert_share, keys, seed):
    """Map the generator's key ids k -> 2k (loaded keys are even) and turn a share of the
    writes into INSERTS of new keys at random odd positions, as in Group Cache Sec. 7.2
    ("50% of the write operations are insert, and the others are update").
    Scans keep the same number of loaded keys (range bounds are doubled)."""
    rng = random.Random(seed * 7919 + 17)
    out = []
    for op in ops:
        if op[0] == "put" and insert_share and rng.random() < insert_share:
            out.append(("put", 2 * rng.randrange(keys) + 1, op[2]))
        elif op[0] == "scan":
            out.append(("scan", 2 * op[1], 2 * op[2]))
        else:
            out.append((op[0], 2 * op[1]) + tuple(op[2:]))
    return out


def run_trace(cache, seed, *, keys=50_000, warmup=20_000, ops=40_000, cache_frac=0.05,
              write_ratio=0.0, scan_share=0.2, zipf=0.8, scan_len=(10, 100),
              block_size=16, memtable=1024, policy="leveling", granularity="file",
              insert_share=0.0):
    """One run; returns a dict of metrics. Same seed => same trace for every cache.

    insert_share > 0 switches to the paper's write mix (see with_inserts); loaded keys are
    then the even numbers 0..2*keys-2."""
    eng = build_engine(cache, keys, cache_frac, block_size, memtable, policy, seed,
                       granularity)
    order = list(range(keys))
    random.Random(seed).shuffle(order)
    scale = 2 if insert_share else 1
    for k in order:
        eng.put(scale * k, f"init{k}")
    mix = dict(write_ratio=write_ratio, delete_ratio=0.0,
               scan_ratio=scan_share * (1 - write_ratio), scan_len=scan_len, zipf_theta=zipf)
    # same hot-key set (perm_seed) for warm-up and measurement; see DECISIONS.md §11
    warm = generate(warmup, keys, seed + 1000, perm_seed=seed, **mix)
    measured = generate(ops, keys, seed, perm_seed=seed, **mix)
    if insert_share:
        warm = with_inserts(warm, insert_share, keys, seed + 1000)
        measured = with_inserts(measured, insert_share, keys, seed)
    for op in warm:
        getattr(eng, op[0])(*op[1:])
    before = eng.io.snapshot()
    lv_before = eng.io.level_snapshot()
    c = eng.cache or eng.query_cache
    maint = c is not None and hasattr(c, "maintenance_report")
    if maint:
        stats_before, eng_before = dict(c.stats), dict(eng.stats)
    for op in measured:
        getattr(eng, op[0])(*op[1:])
    after = eng.io.snapshot()
    d = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    queries = sum(op[0] in ("get", "scan") for op in measured)
    reads = d.get("point_read", 0) + d.get("scan_read", 0)
    row = dict(cache=cache, seed=seed, write_ratio=write_ratio, scan_share=scan_share,
               cache_frac=cache_frac, zipf=zipf, policy=policy, granularity=granularity,
               block_size=block_size, insert_share=insert_share, queries=queries,
               query_reads=reads, reads_per_query=reads / max(queries, 1),
               compactions=eng.stats["compactions"],
               trivial_moves=eng.stats["trivial_moves"])
    # query reads per level (L0 = flushed, not yet compacted)
    lv_after = eng.io.level_snapshot()
    for lvl in range(MAX_LEVELS):
        row[f"qreads_L{lvl}"] = lv_after.get(lvl, 0) - lv_before.get(lvl, 0)
    assert sum(row[f"qreads_L{i}"] for i in range(MAX_LEVELS)) == reads, "levels > MAX_LEVELS?"
    row["qreads_L0_share"] = row["qreads_L0"] / reads if reads else 0.0
    if c is not None:
        row["cache_bytes"] = c.bytes
        row.update({f"stat_{k}": v for k, v in c.stats.items()})
    if maint:
        row.update(maintenance_columns(c, stats_before, eng_before, eng.stats))
    return row


def maintenance_columns(c, stats_before, eng_before, eng_after):
    """GroupCache overhead columns. meas_* = measured window only; maint_* = end-of-run snapshot;
    maint_hit_frac is NaN when no maintained group was created."""
    st = c.stats
    out = {f"meas_{k}": st[k] - stats_before[k] for k in st if not k.startswith("maint_")}
    out["meas_flushes"] = eng_after["flushes"] - eng_before["flushes"]
    out["meas_compactions"] = eng_after["compactions"] - eng_before["compactions"]
    rep = c.maintenance_report()
    out.update(rep)
    held = sum(st[f"maint_bytes_{o}"] for o in MAINT_ORIGINS)
    created = sum(st[f"groups_created_{o}"] for o in MAINT_ORIGINS)
    hit = sum(st[f"{k}_hit_{o}"] for o in MAINT_ORIGINS for k in ("evicted", "retired")) \
        + sum(rep[f"resident_hit_{o}"] for o in MAINT_ORIGINS)
    out["maint_byte_frac"] = held / c.bytes if c.bytes else 0.0
    out["maint_hit_frac"] = hit / created if created else float("nan")   # undefined, not 0
    return out


def summarize(rows, by, caches, value="reads_per_query"):
    """{(by-value, cache): (mean, ci95)} over seeds."""
    out = {}
    for x in sorted({r[by] for r in rows}):
        for c in caches:
            xs = [r[value] for r in rows if r[by] == x and r["cache"] == c]
            if xs:
                out[(x, c)] = (statistics.mean(xs), ci95(xs))
    return out
