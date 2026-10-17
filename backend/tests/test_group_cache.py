"""Group Cache correctness. Run: python -m tests.test_group_cache"""
from app.config import LSMConfig
from app.lsm.engine import LSMEngine
from app.lsm.run import Run
from app.cache.group_cache import GroupCache, _subtract, _merge_intervals
from app.correctness.reference import run_differential
from app.workload.generator import generate

SMALL = dict(block_size=4, memtable_size=16, size_ratio=3, l0_run_limit=2, l1_capacity=48)
BOTH = dict(complete_on_compaction=True, seed_on_flush=True)
VARIANTS = [dict(), dict(complete_on_compaction=True), dict(seed_on_flush=True), BOTH,
            dict(BOTH, zio_rule="lrus"), dict(BOTH, zio_rule="hot", zio_priority="tail")]


class CheckedEngine(LSMEngine):
    """Checks cache invariants too whenever the differential harness checks the engine."""
    def check_invariants(self):
        super().check_invariants()
        self.cache.check_invariants()


def test_interval_helpers():
    assert _merge_intervals([(5, 9), (1, 4), (20, 30), (25, 26)]) == [(1, 9), (20, 30)]
    assert _subtract(0, 100, [(10, 20), (30, 40)]) == [(0, 9), (21, 29), (41, 100)]
    assert _subtract(10, 20, [(0, 50)]) == []
    assert _subtract(10, 20, []) == [(10, 20)]


def test_cache_never_changes_answers():
    """With any variant and any capacity, results must equal the reference."""
    for variant in VARIANTS:
        for cap in (600, 3000, 50_000):
            for seed in range(6):
                for policy, gran in (("leveling", "file"), ("leveling", "level"),
                                     ("tiering", "file")):
                    eng = CheckedEngine(LSMConfig(policy=policy, granularity=gran, **SMALL))
                    eng.attach_cache(GroupCache(cap, seed=seed, **variant))
                    ops = generate(2500, 250, seed, write_ratio=0.4, delete_ratio=0.1,
                                   scan_ratio=0.3, scan_len=(1, 30), zipf_theta=0.9)
                    run_differential(eng, ops, check_every=53)
                    eng.check_invariants()


def test_cache_saves_reads_on_repeated_scans():
    eng = LSMEngine(LSMConfig(block_size=8, memtable_size=64, l0_run_limit=4))
    eng.attach_cache(GroupCache(10**9, seed=0))
    for k in range(200):
        eng.put(k, k)
    eng.flush()
    first = eng.io.query_reads
    eng.scan(10, 12)                           # 3 keys -> admitted w.p. 1/3; repeat
    for _ in range(30):
        eng.scan(10, 12)
    assert eng.io.query_reads - first < 31, "a repeated short scan should become a hit"
    assert eng.cache.stats["run_hits"] > 0


def _fig5_cache(complete):
    """Paper Fig. 5, case 2: group {10,31} for scan(5,40); other run has 12,21,27."""
    c = GroupCache(10**9, seed=0, complete_on_compaction=complete)
    a = Run([(10, "a"), (31, "a"), (44, "a")], block_size=8, seq=2)
    b = Run([(12, "b"), (21, "b"), (27, "b")], block_size=8, seq=1)
    c.live_runs = {a.run_id: a, b.run_id: b}
    c._add(a, 5, 40, [(10, "a"), (31, "a")], ts=1, origin="query")
    c._add(a, 44, 44, [(44, "a")], ts=2, origin="query")      # a point group
    merged = sorted(list(a.entries()) + list(b.entries()))
    out = Run(merged, block_size=8, seq=2)
    c.on_compaction([a, b], [out], merged)
    c.check_invariants()
    return c, out


def test_fig5_case2_baseline_discards_but_keeps_point_group():
    c, out = _fig5_cache(complete=False)
    assert c.stats["case2_discarded"] == 1
    keys = sorted(k for g in c.groups.values() for k in g.keys)
    assert keys == [44], keys


def test_fig5_case2_completed_by_zio():
    c, out = _fig5_cache(complete=True)
    assert c.stats["case2_completed"] == 1
    keys = sorted(k for g in c.groups.values() for k in g.keys)
    assert keys == [10, 12, 21, 27, 31, 44], keys
    served, uncovered = c.lookup(out, 5, 40)
    assert uncovered == [] and [k for k, _ in served] == [10, 12, 21, 27, 31]


def test_fig5_case1_merges_groups_from_two_runs():
    c = GroupCache(10**9, seed=0)
    a = Run([(10, "a"), (31, "a")], block_size=8, seq=2)
    b = Run([(22, "b")], block_size=8, seq=1)
    c.live_runs = {a.run_id: a, b.run_id: b}
    c._add(a, 5, 40, [(10, "a"), (31, "a")], ts=5, origin="query")
    c._add(b, 5, 40, [(22, "b")], ts=3, origin="query")
    merged = sorted(list(a.entries()) + list(b.entries()))
    out = Run(merged, block_size=8, seq=2)
    c.on_compaction([a, b], [out], merged)
    assert c.stats["case1_kept"] == 1
    (g,) = c.groups.values()
    assert g.keys == [10, 22, 31] and g.ts == 3     # takes the position nearest the tail


def test_decision_rules_filter_and_place_groups():
    """lrus/hot install fewer groups than naive; tail placement puts them first in line."""
    counts = {}
    for rule in ("naive", "lrus", "hot"):
        eng = CheckedEngine(LSMConfig(**SMALL))
        eng.attach_cache(GroupCache(10**7, seed=3, zio_rule=rule, **BOTH))
        for op in generate(4000, 400, 5, write_ratio=0.5, scan_ratio=0.4, scan_len=(5, 60),
                           zipf_theta=0.9):
            getattr(eng, op[0])(*op[1:])
        eng.check_invariants()
        st = eng.cache.stats
        counts[rule] = st["flush_seeded"] + st["case2_completed"]
        if rule != "naive":
            assert st["zio_skipped"] > 0
    assert counts["naive"] > counts["lrus"] >= counts["hot"] > 0, counts

    c = GroupCache(10**7, seed=0, seed_on_flush=True, zio_priority="tail")
    from app.lsm.run import Run
    old = Run([(5, "x")], block_size=4, seq=1)
    c.live_runs = {old.run_id: old}
    c._add(old, 0, 10, [(5, "x")], ts=50, origin="query")
    new = Run([(6, "y")], block_size=4, seq=2)
    c.on_flush(new, [(6, "y")])
    seeded = [g for g in c.groups.values() if g.origin == "flush_seed"]
    assert seeded and all(g.ts < 50 for g in seeded), "tail placement must be oldest"


def test_capacity_respected_and_groups_within_blocks():
    eng = CheckedEngine(LSMConfig(**SMALL))
    eng.attach_cache(GroupCache(2000, seed=1, complete_on_compaction=True, seed_on_flush=True))
    for op in generate(4000, 400, 3, write_ratio=0.5, scan_ratio=0.4, scan_len=(5, 60)):
        getattr(eng, op[0])(*op[1:])
    eng.check_invariants()
    assert eng.cache.bytes <= 2000


def _sizes(c, *ns):
    return sum(c.group_bytes(n) for n in ns)


def test_overhead_flush_seed_counts():
    c = GroupCache(10**7, seed=0, seed_on_flush=True)
    old = Run([(5, "x")], block_size=4, seq=1)
    c.live_runs = {old.run_id: old}
    c._add(old, 0, 10, [(5, "x")], ts=50, origin="query")
    new = Run([(6, "y"), (8, "z")], block_size=4, seq=2)
    c.on_flush(new, list(new.entries()))
    st = c.stats
    assert st["groups_created_flush_seed"] == 1 and st["kv_copied_flush_seed"] == 2
    assert st["maint_groups_flush_seed"] == 1
    assert st["maint_bytes_flush_seed"] == _sizes(c, 2)
    assert st["groups_created_completed"] == st["kv_copied_completed"] == 0
    assert c.maintenance_report()["resident_unused_flush_seed"] == 1
    c.lookup(new, 6, 8)
    rep = c.maintenance_report()
    assert rep["resident_hit_flush_seed"] == 1 and rep["resident_unused_flush_seed"] == 0
    c.check_invariants()


def test_overhead_completion_counts_only_our_groups():
    c, out = _fig5_cache(complete=True)
    st = c.stats
    # Component [5,40] is Case 2 -> one completed group of 5 KVs; point group [44] is Case 1
    # (Group Cache's own rebuild) and must NOT be counted as ours.
    assert st["groups_created_completed"] == 1 and st["kv_copied_completed"] == 5
    assert st["maint_bytes_completed"] == _sizes(c, 5)
    assert st["groups_created_flush_seed"] == st["kv_copied_flush_seed"] == 0
    c.check_invariants()
    base, _ = _fig5_cache(complete=False)
    assert all(v == 0 for k, v in base.stats.items()
               if k.endswith(("flush_seed", "completed")) and k != "case2_completed")


def test_overhead_group_fate_evicted_and_retired():
    # Eviction: A (hit, promoted to newest) vs B (never hit); capacity holds two groups.
    run = Run([(5, "x"), (15, "x"), (25, "x"), (35, "x")], block_size=1, seq=1)
    c = GroupCache(2 * GroupCache(1).group_bytes(1), seed=0)
    c.live_runs = {run.run_id: run}
    # (negative timestamps: lookup() stamps hits from the cache clock, which starts at 1)
    c._add(run, 5, 5, [(5, "x")], ts=-5, origin="flush_seed")     # A
    c._add(run, 15, 15, [(15, "x")], ts=-4, origin="flush_seed")  # B
    c.lookup(run, 5, 5)                                           # A hit; touched (n=1 -> p=1)
    c._add(run, 25, 25, [(25, "x")], ts=10, origin="query")
    c._evict_to_fit()                                             # evicts B (unused)
    st = c.stats
    assert st["evicted_unused_flush_seed"] == 1 and st["evicted_hit_flush_seed"] == 0
    c._add(run, 35, 35, [(35, "x")], ts=11, origin="query")
    c._evict_to_fit()                                             # evicts A (hit)
    assert st["evicted_hit_flush_seed"] == 1 and st["maint_groups_flush_seed"] == 0
    assert st["maint_bytes_flush_seed"] == 0
    c.check_invariants()

    # Retirement: a Case-1 compaction replaces the group with Group Cache's own (not ours).
    for hit in (False, True):
        a = Run([(10, "a"), (31, "a")], block_size=8, seq=2)
        c = GroupCache(10**9, seed=0)
        c.live_runs = {a.run_id: a}
        c._add(a, 5, 40, [(10, "a"), (31, "a")], ts=3, origin="flush_seed")
        if hit:
            c.lookup(a, 5, 40)
        merged = list(a.entries())
        c.on_compaction([a], [Run(merged, block_size=8, seq=3)], merged)
        key = "retired_hit_flush_seed" if hit else "retired_unused_flush_seed"
        assert c.stats[key] == 1 and c.stats["maint_groups_flush_seed"] == 0
        assert c.stats["groups_created_flush_seed"] == 1       # the rebuilt group is "case1"
        c.check_invariants()


def test_overhead_conservation_under_workload_and_plain_group_is_zero():
    eng = CheckedEngine(LSMConfig(**SMALL))
    eng.attach_cache(GroupCache(3000, seed=1, **BOTH))
    for op in generate(4000, 400, 3, write_ratio=0.5, scan_ratio=0.4, scan_len=(5, 60),
                       zipf_theta=0.9):
        getattr(eng, op[0])(*op[1:])
    eng.check_invariants()                      # includes the created == fates + resident check
    st = eng.cache.stats
    assert st["groups_created_flush_seed"] > 0 and st["groups_created_completed"] > 0
    assert st["kv_copied_flush_seed"] >= st["groups_created_flush_seed"]
    assert st["evicted_unused_flush_seed"] + st["evicted_hit_flush_seed"] > 0

    eng = CheckedEngine(LSMConfig(**SMALL))
    eng.attach_cache(GroupCache(3000, seed=1))
    for op in generate(2000, 400, 3, write_ratio=0.5, scan_ratio=0.4, scan_len=(5, 60)):
        getattr(eng, op[0])(*op[1:])
    assert all(v == 0 for k, v in eng.cache.stats.items()
               if k.endswith(("flush_seed", "completed")) and k != "case2_completed")


def test_run_trace_overhead_columns():
    from app.experiments.common import run_trace
    kw = dict(keys=2000, warmup=1000, ops=2000, write_ratio=0.5, insert_share=0.5,
              block_size=16, cache_frac=0.1)
    z = run_trace("zio-naive", 0, **kw)
    assert 0 <= z["maint_byte_frac"] <= 1 and 0 <= z["maint_hit_frac"] <= 1
    for o in ("flush_seed", "completed"):
        assert 0 <= z[f"meas_groups_created_{o}"] <= z[f"stat_groups_created_{o}"]
        assert z[f"meas_kv_copied_{o}"] <= z[f"stat_kv_copied_{o}"]
    assert z["meas_flushes"] > 0 and z["stat_groups_created_flush_seed"] > 0
    assert 0 <= z["meas_case2_completed"] <= z["stat_case2_completed"]
    g = run_trace("group", 0, **kw)
    assert g["maint_byte_frac"] == 0 and g["meas_groups_created_flush_seed"] == 0
    assert 0 <= g["meas_case2_discarded"] <= g["stat_case2_discarded"]
    assert "maint_byte_frac" not in run_trace("block", 0, **kw)


def test_query_reads_attributed_to_levels():
    from app.cache.block_cache import BlockCache
    from app.experiments.common import run_trace
    for make in (lambda: None, lambda: GroupCache(3000, seed=1, **BOTH),
                 lambda: BlockCache(3000, seed=1)):
        for policy, gran in (("leveling", "file"), ("leveling", "level"), ("tiering", "file")):
            eng = LSMEngine(LSMConfig(policy=policy, granularity=gran, **SMALL))
            if make() is not None:
                eng.attach_cache(make())
            for op in generate(3000, 300, 4, write_ratio=0.4, scan_ratio=0.3, scan_len=(3, 40),
                               zipf_theta=0.9):
                getattr(eng, op[0])(*op[1:])
            assert eng.io.query_reads > 0
            assert sum(eng.io.query_by_level.values()) == eng.io.query_reads
    r = run_trace("group", 0, keys=2000, warmup=500, ops=1500, write_ratio=0.5,
                  insert_share=0.5, block_size=16)
    assert r["qreads_L0_share"] == r["qreads_L0"] / r["query_reads"]
    assert sum(r[f"qreads_L{i}"] for i in range(8)) == r["query_reads"]


if __name__ == "__main__":
    import sys
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
