"""Week-1 tests for the LSM engine. Run:  python -m tests.test_engine   (or: pytest)"""
from app.config import LSMConfig
from app.lsm.engine import LSMEngine
from app.lsm.io import (LSMObserver, SCAN_READ, POINT_READ, COMPACTION_READ, FLUSH_WRITE,
                        COMPACTION_WRITE)
from app.correctness.reference import random_ops, run_differential

# Small sizes force many flushes and multi-level compactions in few operations.
SMALL = dict(block_size=4, memtable_size=16, size_ratio=3, l0_run_limit=2, l1_capacity=48)


def _configs():
    for policy, gran in (("leveling", "file"), ("leveling", "level"), ("tiering", "file")):
        for ideal in (True, False):
            yield LSMConfig(policy=policy, granularity=gran, ideal_filters=ideal, **SMALL)


def test_differential_random():
    """Engine must match the reference dict on many random sequences."""
    for cfg in _configs():
        for seed in range(15):
            eng = LSMEngine(cfg)
            run_differential(eng, random_ops(3000, key_space=300, seed=seed), check_every=97)
            eng.check_invariants()
            assert len(eng.levels) >= 3, "test should exercise deep compactions"


def test_delete_then_reinsert():
    eng = LSMEngine(LSMConfig(**SMALL))
    for k in range(200):
        eng.put(k, "a")
    for k in range(0, 200, 2):
        eng.delete(k)
    for _ in range(300):                       # push data through compactions
        eng.put(1000, "filler")
        eng.put(1001, "filler")
    eng.flush()
    assert eng.get(10) is None and eng.get(11) == "a"
    eng.put(10, "b")
    eng.flush()
    assert eng.get(10) == "b"
    assert [k for k, _ in eng.scan(8, 13)] == [9, 10, 11, 13]


def test_tombstones_gone_from_bottom_level():
    cfg = LSMConfig(**SMALL)
    eng = LSMEngine(cfg)
    for k in range(400):
        eng.put(k, "x")
    for k in range(400):
        eng.delete(k)
    eng.flush()
    for _ in range(40):                        # force everything to the bottom
        for k in range(1000, 1016):
            eng.put(k, "y")
    eng.flush()
    deepest = [lvl for lvl in eng.levels if lvl][-1]
    assert all(v is not None for f in deepest for _, v in f.entries()), "bottom holds tombstones"
    assert eng.scan(0, 399) == []


def test_file_granularity_rewrites_small_slices():
    """Per-file compaction rewrites a small key slice per compaction; whole-level merges
    rewrite entire levels at once. (Total rewrite volume over time is similar.)"""
    from app.workload.generator import generate

    class Biggest(LSMObserver):
        def __init__(self):
            self.max_blocks = 0

        def on_compaction(self, inputs, outputs, merged):
            self.max_blocks = max(self.max_blocks, sum(len(o.blocks) for o in outputs))

    biggest = {}
    for gran in ("file", "level"):
        eng = LSMEngine(LSMConfig(block_size=8, memtable_size=64, size_ratio=4,
                                  l0_run_limit=2, l1_capacity=256, granularity=gran))
        rec = Biggest()
        eng.observers.append(rec)
        for op in generate(20000, 2000, 1, write_ratio=1.0, scan_ratio=0.0, delete_ratio=0.0):
            eng.put(op[1], op[2])
        eng.check_invariants()
        biggest[gran] = rec.max_blocks
    assert biggest["file"] * 2 < biggest["level"], biggest


def test_trivial_move_keeps_file_identity():
    eng = LSMEngine(LSMConfig(block_size=4, memtable_size=8, size_ratio=2, l0_run_limit=1,
                              l1_capacity=8))
    for k in range(0, 400):                    # sequential keys: files never overlap below
        eng.put(k, k)
    eng.check_invariants()
    assert eng.stats["trivial_moves"] > 0


def test_scan_io_counts_one_per_block_touched():
    cfg = LSMConfig(block_size=4, memtable_size=1000, l0_run_limit=10)
    eng = LSMEngine(cfg)
    for k in range(20):
        eng.put(k, k)
    eng.flush()                                 # one run: blocks [0-3][4-7]...[16-19]
    before = eng.io.blocks[SCAN_READ]
    eng.scan(2, 9)                              # touches blocks [0-3],[4-7],[8-11]
    assert eng.io.blocks[SCAN_READ] - before == 3
    before = eng.io.blocks[POINT_READ]
    eng.get(5); eng.get(999)                    # present -> 1 I/O, absent -> 0 (ideal filter)
    assert eng.io.blocks[POINT_READ] - before == 1
    assert eng.io.blocks[FLUSH_WRITE] == 5


def test_observers_see_flush_and_compaction_data():
    class Recorder(LSMObserver):
        def __init__(self):
            self.flushes, self.compactions = [], []

        def on_flush(self, new_run, entries):
            self.flushes.append((new_run, entries))

        def on_compaction(self, inputs, outputs, merged):
            self.compactions.append((inputs, outputs, merged))

    eng = LSMEngine(LSMConfig(**SMALL))
    rec = Recorder()
    eng.observers.append(rec)
    for k in range(500):
        eng.put(k % 120, k)
    assert rec.flushes and rec.compactions
    for inputs, outputs, merged in rec.compactions:
        assert merged == [e for o in outputs for e in o.entries()], "merged != outputs"
        assert all(r not in [x for lvl in eng.levels for x in lvl] for r in inputs)
    # Compaction reads = blocks of all inputs.
    total_in = sum(len(r.blocks) for inputs, _, _ in rec.compactions for r in inputs)
    assert eng.io.blocks[COMPACTION_READ] == total_in


if __name__ == "__main__":
    import sys
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
