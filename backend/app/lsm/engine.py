"""A block-level LSM-tree simulator.

What it models (and counts as disk I/O):
  * point reads and scans read whole blocks, one I/O per block;
  * flushes write the MemTable as a new L0 run;
  * compactions read every input block and write every output block.
Leveling granularity (config.granularity):
  * "file"  (default, LevelDB/RocksDB style): levels >= 1 hold non-overlapping SST files;
    a compaction merges ONE file with the next level's overlapping files, picked
    round-robin over the key space; a file overlapping nothing is moved down (no I/O).
  * "level": whole levels are merged (kept for comparison; exaggerates rewrites).
Tiering always merges all runs of a level into one run appended to the next level.
Recency is by POSITION, as in real LSM-trees: L0 runs newest-first, then L1, L2, ...
What it does NOT model: concurrency, timing/latency, crash recovery (WAL), L0->L0.
Keys must be mutually comparable integers. A value of None means "deleted".
"""
from bisect import bisect_left, bisect_right

from .run import Run, TOMBSTONE
from .io import (IOCounter, LSMObserver, POINT_READ, SCAN_READ, FLUSH_WRITE,
                 COMPACTION_READ, COMPACTION_WRITE)
from ..config import LSMConfig


class LSMEngine:
    def __init__(self, config: LSMConfig = LSMConfig()):
        self.cfg = config
        self.memtable = {}            # key -> value (None = tombstone)
        self.levels = [[]]            # levels[i] = list of runs/files; levels[0] = L0
        self.io = IOCounter()
        self.observers: list[LSMObserver] = []
        self._next_seq = 0
        self._compact_ptr = {}        # level -> last key compacted (round-robin picking)
        self.stats = {"flushes": 0, "compactions": 0, "trivial_moves": 0}
        self.last_read_blocks = []    # block ids read by the most recent get/scan (for the UI)
        self.cache = None             # optional run-level cache (see attach_cache)
        self.query_cache = None       # optional query-level cache (see attach_query_cache)

    @property
    def _files_mode(self):
        return self.cfg.policy == "leveling" and self.cfg.granularity == "file"

    # ------------------------------------------------------------- caches
    def attach_cache(self, cache):
        """Attach a run-level cache (lookup(run, lo, hi), admit(run, block_index, lo, hi),
        plus observer hooks). Must be attached to an empty engine."""
        if not self.cfg.ideal_filters:
            raise ValueError("run-level caches assume ideal filters (as Group Cache does)")
        if self.levels != [[]] or self.memtable or self.query_cache is not None:
            raise ValueError("attach one cache to an empty engine")
        self.cache = cache
        self.observers.append(cache)

    def attach_query_cache(self, qcache):
        """Attach a query-result cache (e.g. RangeCache): consulted before any run is
        touched, updated write-through on every put/delete."""
        if self.levels != [[]] or self.memtable or self.cache is not None:
            raise ValueError("attach one cache to an empty engine")
        self.query_cache = qcache

    # ------------------------------------------------------------------ writes
    def put(self, key, value):
        if value is TOMBSTONE:
            raise ValueError("use delete() to remove a key")
        self._write(key, value)

    def delete(self, key):
        self._write(key, TOMBSTONE)

    def _write(self, key, value):
        if self.query_cache is not None:
            self.query_cache.on_write(key, value)
        self.memtable[key] = value
        if len(self.memtable) >= self.cfg.memtable_size:
            self.flush()

    def flush(self):
        if not self.memtable:
            return
        entries = sorted(self.memtable.items())
        run = Run(entries, self.cfg.block_size, self._new_seq())
        self.memtable = {}
        run.level = 0
        self.levels[0].append(run)
        self.io.add(FLUSH_WRITE, len(run.blocks))
        self.stats["flushes"] += 1
        for ob in self.observers:
            ob.on_flush(run, entries)
        self._maybe_compact()

    def _new_seq(self):
        self._next_seq += 1
        return self._next_seq

    # ------------------------------------------------------------- compaction
    def level_capacity(self, i):
        """Entries allowed in level i >= 1."""
        return self.cfg.l1_capacity * self.cfg.size_ratio ** (i - 1)

    def _level_size(self, i):
        return sum(r.size for r in self.levels[i])

    def _needs_compaction(self, i):
        runs = self.levels[i]
        if i == 0:
            return len(runs) > self.cfg.l0_run_limit
        if self.cfg.policy == "tiering":
            return len(runs) > self.cfg.size_ratio
        return self._level_size(i) > self.level_capacity(i)

    def _maybe_compact(self):
        i = 0
        while i < len(self.levels):
            while self._needs_compaction(i):
                self._compact_level(i)
            i += 1

    def _ensure_level(self, i):
        while len(self.levels) <= i:
            self.levels.append([])

    def _compact_level(self, i):
        self._ensure_level(i + 1)
        if self.cfg.policy == "tiering":
            inputs = list(self.levels[i])
            self.levels[i] = []
            self._merge_into(inputs, i + 1, as_files=False)
        elif not self._files_mode:
            inputs = self.levels[i] + self.levels[i + 1]
            self.levels[i], self.levels[i + 1] = [], []
            self._merge_into(inputs, i + 1, as_files=False)
        elif i == 0:
            # All L0 runs (they overlap each other) + overlapping L1 files.
            upper = list(self.levels[0])
            lo, hi = min(r.min_key for r in upper), max(r.max_key for r in upper)
            lower = self._overlapping_files(1, lo, hi)
            self.levels[0] = []
            self._remove_files(1, lower)
            self._merge_into(upper + lower, 1, as_files=True)
        else:
            f = self._pick_file(i)
            lower = self._overlapping_files(i + 1, f.min_key, f.max_key)
            self._remove_files(i, [f])
            self._compact_ptr[i] = f.max_key
            if not lower:                               # trivial move: no rewrite, no I/O
                self._insert_files(i + 1, [f])
                self.stats["trivial_moves"] += 1
                return
            self._remove_files(i + 1, lower)
            self._merge_into([f] + lower, i + 1, as_files=True)
        self.stats["compactions"] += 1

    def _pick_file(self, i):
        """Round-robin over the key space (LevelDB's compact pointer)."""
        files = self.levels[i]
        ptr = self._compact_ptr.get(i)
        if ptr is not None:
            for f in files:
                if f.min_key > ptr:
                    return f
        return files[0]

    def _overlapping_files(self, i, lo, hi):
        files = self.levels[i] if i < len(self.levels) else []
        return [f for f in files if f.min_key <= hi and f.max_key >= lo]

    def _remove_files(self, i, files):
        ids = {id(f) for f in files}
        self.levels[i] = [f for f in self.levels[i] if id(f) not in ids]

    def _insert_files(self, i, files):
        for f in files:
            f.level = i
        self.levels[i] = sorted(self.levels[i] + files, key=lambda f: f.min_key)

    def _merge_into(self, inputs, target, as_files):
        """Merge input runs into `target` level. Reads/writes are counted as I/O.

        Inputs are ordered by recency: lower level index = newer; within a level, higher
        seq = newer. Tombstones are dropped only if no older data outside the inputs could
        hold the same keys (no remaining run at the target level or deeper overlaps).
        """
        lo, hi = min(r.min_key for r in inputs), max(r.max_key for r in inputs)
        older = [r for lvl in self.levels[target:] for r in lvl
                 if r.min_key <= hi and r.max_key >= lo]
        drop_tombstones = not older

        merged = {}
        # Oldest first so newer values overwrite: deeper level = older; within a level,
        # lower seq = older (L0 / tiering runs overlap; leveled files never do).
        for run in sorted(inputs, key=lambda r: (-r.level, r.seq)):
            self.io.add(COMPACTION_READ, len(run.blocks))
            merged.update(run.entries())               # newer runs applied last
        items = sorted(merged.items())
        if drop_tombstones:
            items = [(k, v) for k, v in items if v is not TOMBSTONE]

        outputs = []
        if items:
            seq = max(r.seq for r in inputs)
            if as_files:
                n = self.cfg.sst_entries
                outputs = [Run(items[j:j + n], self.cfg.block_size, seq)
                           for j in range(0, len(items), n)]
                self._insert_files(target, outputs)
            else:
                outputs = [Run(items, self.cfg.block_size, seq)]
                outputs[0].level = target
                self.levels[target].append(outputs[0])
        for out in outputs:
            self.io.add(COMPACTION_WRITE, len(out.blocks))
        for ob in self.observers:
            ob.on_compaction(inputs, outputs, items)

    # ------------------------------------------------------------------ reads
    def runs_newest_first(self):
        """All runs/files in recency order: L0 newest first, then L1, L2, ..."""
        out = sorted(self.levels[0], key=lambda r: -r.seq)
        for lvl in self.levels[1:]:
            out.extend(sorted(lvl, key=lambda r: -r.seq))
        return out

    def _candidate_runs_for_key(self, key):
        for run in sorted(self.levels[0], key=lambda r: -r.seq):
            yield run
        for lvl in self.levels[1:]:
            if self._files_mode:
                i = bisect_right([f.min_key for f in lvl], key) - 1
                if i >= 0 and lvl[i].max_key >= key:
                    yield lvl[i]
            else:
                yield from sorted(lvl, key=lambda r: -r.seq)

    def get(self, key):
        """Latest value for key, or None if absent/deleted."""
        self.last_read_blocks = []
        if key in self.memtable:
            return self.memtable[key]
        if self.query_cache is not None:
            hit = self.query_cache.lookup(key, key)
            if hit is not None:
                return hit[0][1] if hit else None
            value = self._get_from_runs(key)
            if value is not None:
                self.query_cache.admit(key, key, [(key, value)])
            return value
        return self._get_from_runs(key)

    def _get_from_runs(self, key):
        for run in self._candidate_runs_for_key(key):
            block = run.find_block(key)
            if block is None:
                continue
            found, value = block.get(key)
            if self.cache is not None:
                if not found:
                    continue                        # ideal filter: run lacks the key
                served, uncovered = self.cache.lookup(run, key, key)
                if not uncovered:
                    return served[0][1]             # served from cache, no I/O
                self.io.add(POINT_READ, level=run.level)
                self.last_read_blocks.append(block.block_id)
                self.cache.admit(run, run.owner_index(key), key, key)
                return value
            if found or not self.cfg.ideal_filters:
                self.io.add(POINT_READ, level=run.level)
                self.last_read_blocks.append(block.block_id)
            if found:
                return value
        return None

    def scan(self, lo, hi):
        """All live (key, value) with lo <= key <= hi, sorted by key."""
        self.last_read_blocks = []
        if lo > hi:
            return []
        if self.query_cache is not None:
            hit = self.query_cache.lookup(lo, hi)
            if hit is not None:
                return hit
            rows = self._scan_runs(lo, hi)
            self.query_cache.admit(lo, hi, rows)
            return rows
        return self._scan_runs(lo, hi)

    def _scan_runs(self, lo, hi):
        result = {}
        for run in reversed(self.runs_newest_first()):     # oldest first; newer overwrite
            if run.max_key < lo or run.min_key > hi:
                continue
            if self.cache is not None:
                if not run.has_keys_in(lo, hi):     # ideal range filter: skip run
                    continue
                served, uncovered = self.cache.lookup(run, lo, hi)
                result.update(served)
                read = {}
                for a, b in uncovered:
                    for blk in run.blocks_with_keys_in(a, b):
                        read[blk.block_id] = blk
                self.io.add(SCAN_READ, len(read), level=run.level)
                self.last_read_blocks.extend(read)
                for blk in read.values():
                    result.update(blk.entries_in(lo, hi))
                for blk in read.values():
                    self.cache.admit(run, run.owner_index(blk.min_key), lo, hi)
                continue
            if self.cfg.ideal_filters:
                blocks = run.blocks_with_keys_in(lo, hi)
            else:
                blocks = [b for b in run.blocks if b.min_key <= hi and b.max_key >= lo]
            self.io.add(SCAN_READ, len(blocks), level=run.level)
            self.last_read_blocks.extend(b.block_id for b in blocks)
            for b in blocks:
                result.update(b.entries_in(lo, hi))
        for k, v in self.memtable.items():
            if lo <= k <= hi:
                result[k] = v
        return sorted((k, v) for k, v in result.items() if v is not TOMBSTONE)

    # ------------------------------------------------------------- invariants
    def check_invariants(self):
        """Raise AssertionError if the structure is inconsistent."""
        ids = set()
        for i, lvl in enumerate(self.levels):
            if i >= 1 and self.cfg.policy == "leveling":
                if self._files_mode:
                    for a, b in zip(lvl, lvl[1:]):
                        assert a.max_key < b.min_key, f"L{i} files overlap or unsorted"
                    assert all(f.size <= self.cfg.sst_entries for f in lvl)
                else:
                    assert len(lvl) <= 1, f"leveling: L{i} has {len(lvl)} runs"
            for run in lvl:
                assert id(run) not in ids, "run appears twice"
                ids.add(id(run))
                keys = [k for k, _ in run.entries()]
                assert keys == sorted(set(keys)), f"{run} not strictly sorted"
                assert all(1 <= len(b.keys) <= self.cfg.block_size for b in run.blocks)
                assert run.size == len(keys)
                assert run.level == i, f"{run} records level {run.level}, sits in L{i}"
