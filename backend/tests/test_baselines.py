"""Block cache and Range Cache correctness. Run: python -m tests.test_baselines"""
from app.config import LSMConfig
from app.lsm.engine import LSMEngine
from app.cache.block_cache import BlockCache
from app.cache.range_cache import RangeCache
from app.correctness.reference import ReferenceKV, run_differential
from app.workload.generator import generate

SMALL = dict(block_size=4, memtable_size=16, size_ratio=3, l0_run_limit=2, l1_capacity=48)


class CheckedEngine(LSMEngine):
    def check_invariants(self):
        super().check_invariants()
        (self.cache or self.query_cache).check_invariants()


def _ops(seed):
    return generate(2500, 250, seed, write_ratio=0.4, delete_ratio=0.1, scan_ratio=0.3,
                    scan_len=(1, 30), zipf_theta=0.9)


def test_block_cache_never_changes_answers():
    for cap in (500, 3000, 10**7):
        for seed in range(6):
            for policy, gran in (("leveling", "file"), ("leveling", "level"),
                                 ("tiering", "file")):
                eng = CheckedEngine(LSMConfig(policy=policy, granularity=gran, **SMALL))
                eng.attach_cache(BlockCache(cap))
                run_differential(eng, _ops(seed), check_every=61)
                eng.check_invariants()


def test_range_cache_never_changes_answers():
    for cap in (500, 3000, 10**7):
        for seed in range(6):
            eng = CheckedEngine(LSMConfig(**SMALL))
            eng.attach_query_cache(RangeCache(cap))
            run_differential(eng, _ops(seed), check_every=61)


def test_range_cache_contents_match_truth_under_writes():
    """Every cached range must equal the live data at all times (write-through works)."""
    for seed in range(4):
        eng = LSMEngine(LSMConfig(**SMALL))
        rc = RangeCache(10**7)
        eng.attach_query_cache(rc)
        ref = ReferenceKV()
        for i, op in enumerate(_ops(seed)):
            getattr(eng, op[0])(*op[1:])
            if op[0] in ("put", "delete"):
                getattr(ref, op[0])(*op[1:])
            if i % 37 == 0:
                rc.check_invariants(truth=ref.scan)
        rc.check_invariants(truth=ref.scan)
        assert rc.stats["hits"] > 0 and rc.stats["write_through"] > 0


def test_block_cache_invalidated_by_compaction_but_range_cache_not():
    cfg = LSMConfig(block_size=4, memtable_size=8, size_ratio=3, l0_run_limit=1, l1_capacity=24)
    eb, er = LSMEngine(cfg), LSMEngine(cfg)
    bc, rc = BlockCache(10**7), RangeCache(10**7)
    eb.attach_cache(bc); er.attach_query_cache(rc)
    for e in (eb, er):
        for k in range(8):
            e.put(k, k)                      # one flush -> one L0 run
        e.scan(0, 7); e.scan(0, 7)           # second scan should hit
    assert bc.stats["run_hits"] >= 1 and rc.stats["hits"] >= 1
    for e in (eb, er):
        for k in range(100, 116):
            e.put(k, k)                      # flushes + compaction of the cached run
    assert bc.stats["invalidated"] > 0
    rb, rr = eb.io.query_reads, er.io.query_reads
    eb.scan(0, 7); er.scan(0, 7)
    assert eb.io.query_reads > rb, "block cache must re-read after compaction"
    assert er.io.query_reads == rr, "range cache survives compaction"


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
