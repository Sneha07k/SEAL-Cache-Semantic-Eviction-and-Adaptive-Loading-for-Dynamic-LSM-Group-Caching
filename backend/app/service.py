"""Service layer used by the API (testable without a server).

Session = engine + optional cache + flush/compaction log. run_benchmark() wraps run_trace().
"""
from dataclasses import asdict, fields

from .config import LSMConfig
from .experiments.common import CACHES, KEY_BYTES, VALUE_BYTES, ci95, run_trace
from .lsm.engine import LSMEngine
from .lsm.io import LSMObserver
from .workload.generator import generate

LAYERS_SHOWN = 8        # cap for the UI
MAX_GROUPS_SHOWN = 4000
MAX_EVENTS = 200
UI_CACHES = ["none", "block", "range", "group", "group+seed", "group+complete", "zio-naive"]

# counters only touched in on_flush/on_compaction
EVENT_KEYS = ("flush_seeded", "case1_kept", "case2_discarded", "case2_completed",
              "zio_skipped", "groups_created_flush_seed", "groups_created_completed",
              "kv_copied_flush_seed", "kv_copied_completed")


class EventLog(LSMObserver):
    """Flush/compaction log with the cache counters each event changed (registered after the cache)."""

    def __init__(self, session):
        self.session = session
        self.events = []
        self.total = 0
        self.prev = self._snap()

    def _snap(self):
        c = self.session.cache_obj
        return dict(getattr(c, "stats", {}))

    def _push(self, kind, detail):
        cur = self._snap()
        delta = {k: cur[k] - self.prev.get(k, 0) for k in EVENT_KEYS
                 if k in cur and cur[k] != self.prev.get(k, 0)}
        self.prev = cur
        self.total += 1
        self.events.append({"n": self.total, "op": self.session.ops_applied, "kind": kind,
                            **detail, "cache": delta})
        del self.events[:-MAX_EVENTS]

    def on_flush(self, new_run, entries):
        self._push("flush", {"run": new_run.run_id, "entries": len(entries)})

    def on_compaction(self, inputs, outputs, merged):
        self._push("compaction", {
            "inputs": [r.run_id for r in inputs], "outputs": [r.run_id for r in outputs],
            "from_levels": sorted({r.level for r in inputs if r.level is not None}),
            "to_level": outputs[0].level if outputs else None, "merged": len(merged)})


class Session:
    def __init__(self, **cfg):
        self.reset(**cfg)

    def reset(self, cache="none", cache_kb=32, cache_seed=0, **cfg):
        allowed = {f.name for f in fields(LSMConfig)}
        unknown = set(cfg) - allowed
        if unknown:
            raise ValueError(f"unknown config fields: {sorted(unknown)}")
        if cache not in UI_CACHES:
            raise ValueError(f"cache must be one of {UI_CACHES}")
        if not 1 <= cache_kb <= 4096:
            raise ValueError("cache_kb must be between 1 and 4096")
        self.cfg = LSMConfig(**cfg)
        self.engine = LSMEngine(self.cfg)
        self.cache_name, self.cache_kb, self.cache_obj = cache, cache_kb, None
        if cache != "none":
            kind, cls, kw = CACHES[cache]
            self.cache_obj = cls(cache_kb * 1024, key_bytes=KEY_BYTES, value_bytes=VALUE_BYTES,
                                 seed=cache_seed, **kw)
            (self.engine.attach_cache if kind == "run" else self.engine.attach_query_cache)(
                self.cache_obj)
        self.ops_applied = 0
        self.last_query = None
        self.log = EventLog(self)
        self.engine.observers.append(self.log)
        return self.state()

    # ------------------------------------------------------------ operations
    def apply(self, ops):
        eng = self.engine
        arity = {"put": 3, "delete": 2, "get": 2, "scan": 3}
        for op in ops:                                  # validate the WHOLE batch first
            if not op or op[0] not in arity or len(op) != arity[op[0]] or not all(
                    isinstance(x, int) and not isinstance(x, bool)
                    for x in op[1:3 if op[0] == "scan" else 2]):
                raise ValueError(f"bad op {op!r}")
        for op in ops:
            kind = op[0]
            if kind == "put":
                eng.put(op[1], op[2])
            elif kind == "delete":
                eng.delete(op[1])
            elif kind == "get":
                eng.get(op[1])
            elif kind == "scan":
                eng.scan(op[1], op[2])
            else:
                raise ValueError(f"unknown op {kind}")
            self.ops_applied += 1
        self.last_query = None
        return self.state()

    def run_workload(self, n, key_space, seed, **mix):
        if not 1 <= n <= 200_000:
            raise ValueError("n must be between 1 and 200000")
        return self.apply(generate(n, key_space, seed, **mix))

    def put_range(self, lo, hi, step=1, tag="v"):
        """Write keys lo, lo+step, ... <= hi (a burst of new data, e.g. into a hot range)."""
        if step < 1 or hi < lo or (hi - lo) // step > 50_000:
            raise ValueError("bad range")
        return self.apply([("put", k, f"{tag}{k}") for k in range(lo, hi + 1, step)])

    def get(self, key):
        before, cbefore = self.engine.io.snapshot(), self._cache_stats()
        value = self.engine.get(key)
        self.ops_applied += 1
        self.last_query = self._query_report("get", {"key": key}, value, before, cbefore)
        return self.state()

    def scan(self, lo, hi):
        before, cbefore = self.engine.io.snapshot(), self._cache_stats()
        rows = self.engine.scan(lo, hi)
        self.ops_applied += 1
        self.last_query = self._query_report("scan", {"lo": lo, "hi": hi}, rows, before, cbefore)
        return self.state()

    def flush(self):
        self.engine.flush()
        return self.state()

    # --------------------------------------------------------------- reports
    def _cache_stats(self):
        return dict(getattr(self.cache_obj, "stats", {}))

    def _query_report(self, kind, args, result, before, cbefore):
        after, cafter = self.engine.io.snapshot(), self._cache_stats()
        delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
        cdelta = {k: cafter[k] - cbefore.get(k, 0) for k in cafter
                  if cafter[k] != cbefore.get(k, 0)}
        return {
            "kind": kind, "args": args, "result": result,
            "blocks_read": list(self.engine.last_read_blocks),
            "io_delta": {k: v for k, v in delta.items() if v},
            "cache_delta": cdelta,
        }

    def cache_state(self):
        """Cache contents for the UI: groups (Group Cache), blocks (block cache) or ranges (Range Cache)."""
        c = self.cache_obj
        if c is None:
            return None
        out = {"name": self.cache_name, "capacity": c.capacity, "bytes": c.bytes,
               "stats": dict(c.stats), "groups": [], "maintenance": None}
        if hasattr(c, "groups"):
            gs = sorted(c.groups.values(), key=lambda g: (g.run.run_id, g.lb))
            out["groups"] = [{"id": g.gid, "run": g.run.run_id, "lb": g.lb, "ub": g.ub,
                              "n": g.n, "origin": g.origin, "hit": g.hit}
                             for g in gs[:MAX_GROUPS_SHOWN]]
            out["maintenance"] = dict(c.maintenance_report(), **{
                k: v for k, v in c.stats.items() if k.endswith(("flush_seed", "completed"))})
        elif hasattr(c, "lru") and hasattr(c, "live_runs"):
            for run_id, idx in list(c.lru)[:MAX_GROUPS_SHOWN]:
                run = c.live_runs.get(run_id)
                if run is not None and idx < len(run.blocks):
                    b = run.blocks[idx]
                    out["groups"].append({"id": f"{run_id}.{idx}", "run": run_id, "lb": b.min_key,
                                          "ub": b.max_key, "n": len(b.keys), "origin": "block",
                                          "hit": False})
        elif hasattr(c, "ranges"):
            out["groups"] = [{"id": r.rid, "run": None, "lb": r.lo, "ub": r.hi,
                              "n": len(r.keys), "origin": "range", "hit": False}
                             for r in list(c.ranges.values())[:MAX_GROUPS_SHOWN]]
        return out

    def state(self):
        eng = self.engine
        levels = []
        for i, lvl in enumerate(eng.levels[:LAYERS_SHOWN]):
            levels.append({
                "level": i,
                "capacity": None if i == 0 else eng.level_capacity(i),
                "runs": [{
                    "run_id": r.run_id, "seq": r.seq, "size": r.size,
                    "min_key": r.min_key, "max_key": r.max_key,
                    "blocks": [{"id": b.block_id, "min": b.min_key, "max": b.max_key,
                                "n": len(b.keys),
                                "tombstones": sum(v is None for v in b.values)}
                               for b in r.blocks],
                } for r in sorted(lvl, key=lambda r: -r.seq)],
            })
        return {
            "config": dict(asdict(self.cfg), cache=self.cache_name, cache_kb=self.cache_kb),
            "memtable": {"size": len(eng.memtable), "capacity": self.cfg.memtable_size},
            "levels": levels,
            "io": eng.io.snapshot(),
            "stats": dict(eng.stats, ops_applied=self.ops_applied),
            "last_query": self.last_query,
            "cache": self.cache_state(),
            "events": {"total": self.log.total, "recent": self.log.events[-60:]},
        }


# ------------------------------------------------------------------ benchmarks
BENCH_LIMITS = dict(keys=30_000, ops_total=60_000, seeds=5, caches=8)


def run_benchmark(caches, seeds, keys=10_000, warmup=5_000, ops=10_000, write_ratio=0.5,
                  scan_share=0.2, zipf=0.8, cache_frac=0.05, block_size=48, policy="leveling",
                  insert_share=0.5, seed_offset=0):
    """Small run_trace() comparison for the UI (demo scale, not for the paper)."""
    if not caches or len(caches) > BENCH_LIMITS["caches"]:
        raise ValueError(f"choose 1-{BENCH_LIMITS['caches']} caches")
    bad = [c for c in caches if c not in CACHES]
    if bad:
        raise ValueError(f"unknown caches {bad}")
    if not 1 <= seeds <= BENCH_LIMITS["seeds"]:
        raise ValueError(f"seeds must be 1-{BENCH_LIMITS['seeds']}")
    if not 1_000 <= keys <= BENCH_LIMITS["keys"] or warmup < 0 or ops < 100 \
            or warmup + ops > BENCH_LIMITS["ops_total"]:
        raise ValueError("keys must be 1000-30000 and warmup+ops at most 60000")
    if policy not in ("leveling", "tiering"):
        raise ValueError("policy must be leveling or tiering")
    rows = []
    for seed in range(seed_offset, seed_offset + seeds):
        for c in caches:
            r = run_trace(c, seed, keys=keys, warmup=warmup, ops=ops, cache_frac=cache_frac,
                          write_ratio=write_ratio, scan_share=scan_share, zipf=zipf,
                          block_size=block_size, policy=policy, insert_share=insert_share)
            row = {k: r[k] for k in ("cache", "seed", "queries", "query_reads",
                                     "reads_per_query", "compactions", "qreads_L0_share")}
            row |= {k: r[k] for k in ("meas_groups_created_flush_seed",
                                      "meas_groups_created_completed", "meas_case2_discarded",
                                      "maint_byte_frac", "maint_hit_frac") if k in r}
            rows.append({k: (None if v != v else v) for k, v in row.items()})   # NaN -> null
    by = {c: {r["seed"]: r["reads_per_query"] for r in rows if r["cache"] == c} for c in caches}
    summary, paired = {}, []
    for c in caches:
        xs = list(by[c].values())
        summary[c] = {"mean": sum(xs) / len(xs), "ci": ci95(xs), "n": len(xs)}
    for cand in caches:
        for base in caches:
            if cand == base:
                continue
            red = [100 * (1 - by[cand][s] / by[base][s]) for s in by[cand]]
            m = sum(red) / len(red)
            hw = ci95(red)
            paired.append({"cand": cand, "base": base, "reduction": m, "ci": hw,
                           "n": len(red), "worse_seeds": sum(x < 0 for x in red),
                           "significant": len(red) > 1 and abs(m) > hw})
    return {"rows": rows, "summary": summary, "paired": paired,
            "params": dict(keys=keys, warmup=warmup, ops=ops, write_ratio=write_ratio,
                           scan_share=scan_share, zipf=zipf, cache_frac=cache_frac,
                           block_size=block_size, policy=policy, insert_share=insert_share,
                           seeds=list(range(seed_offset, seed_offset + seeds))),
            "note": "Demo scale, few seeds: for exploration, not a paper result."}
