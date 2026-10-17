"""Block cache baseline (RocksDB-style LRU over data blocks).

Uses the same run-level interface as GroupCache (lookup / admit / observer hooks), so the
engine treats both identically.

Modelling choices (state in the paper):
  * Memory per cached block: 92 bytes metadata (Group Cache paper, p.47:8) plus
    n * (|key| + |value|) for its n entries.
  * Every block read is admitted (plain LRU, as RocksDB's default LRUCache).
  * On compaction, blocks of the deleted input runs are dropped at once. Real RocksDB
    leaves them as unreachable garbage until LRU evicts them, so dropping them is the
    FAVOURABLE choice for this baseline (it frees memory immediately).
"""
from collections import OrderedDict

from ..lsm.io import LSMObserver

BLOCK_META_BYTES = 92


class BlockCache(LSMObserver):
    name = "block_cache"

    def __init__(self, capacity_bytes, key_bytes=8, value_bytes=256, seed=0):
        self.capacity = capacity_bytes
        self.key_bytes, self.value_bytes = key_bytes, value_bytes
        self.lru = OrderedDict()                   # (run_id, block_index) -> bytes
        self.bytes = 0
        self.live_runs = {}
        self.stats = {"run_probes": 0, "run_hits": 0, "admitted": 0, "evicted": 0,
                      "invalidated": 0}

    def block_bytes(self, block):
        return BLOCK_META_BYTES + len(block.keys) * (self.key_bytes + self.value_bytes)

    def lookup(self, run, lo, hi):
        self.stats["run_probes"] += 1
        served, uncovered = [], []
        for blk in run.blocks_with_keys_in(lo, hi):      # in-memory index, no I/O
            bi = run.owner_index(blk.min_key)
            if (run.run_id, bi) in self.lru:
                self.lru.move_to_end((run.run_id, bi))
                served.extend(blk.entries_in(lo, hi))
            else:
                olo, ohi = run.owned_interval(bi)
                a = lo if olo is None else max(lo, olo)
                b = hi if ohi is None else min(hi, ohi)
                uncovered.append((a, b))
        if not uncovered:
            self.stats["run_hits"] += 1
        return served, uncovered

    def admit(self, run, block_index, lo, hi):
        key = (run.run_id, block_index)
        if key in self.lru:
            self.lru.move_to_end(key)
            return
        size = self.block_bytes(run.blocks[block_index])
        self.lru[key] = size
        self.bytes += size
        self.stats["admitted"] += 1
        while self.bytes > self.capacity and self.lru:
            _, b = self.lru.popitem(last=False)
            self.bytes -= b
            self.stats["evicted"] += 1

    def on_flush(self, new_run, entries):
        self.live_runs[new_run.run_id] = new_run

    def on_compaction(self, inputs, outputs, merged):
        dead = {r.run_id for r in inputs}
        for r in inputs:
            self.live_runs.pop(r.run_id, None)
        for key in [k for k in self.lru if k[0] in dead]:
            self.bytes -= self.lru.pop(key)
            self.stats["invalidated"] += 1
        for out in outputs:
            self.live_runs[out.run_id] = out

    def check_invariants(self):
        assert self.bytes == sum(self.lru.values())
        assert self.bytes <= self.capacity
        for run_id, bi in self.lru:
            assert run_id in self.live_runs, "cached block of a deleted run"
            assert 0 <= bi < len(self.live_runs[run_id].blocks)
