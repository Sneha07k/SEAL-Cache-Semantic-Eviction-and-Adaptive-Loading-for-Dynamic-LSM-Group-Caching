
import random
from bisect import bisect_left, bisect_right

from ..lsm.io import LSMObserver
from .group_cache import KVGroup, _merge_intervals, _subtract, _slice

META_BYTES = 77    


class SimpleGroupCache(LSMObserver):
    name = "group_cache"

    def __init__(self, capacity_bytes, key_bytes=8, value_bytes=256, seed=0,
                 seed_on_flush=False, complete_on_compaction=False):
        self.capacity = capacity_bytes
        self.key_bytes, self.value_bytes = key_bytes, value_bytes
        self.rng = random.Random(seed)            
       
        self.seed_on_flush = seed_on_flush
        self.complete_on_compaction = complete_on_compaction

        self.groups = {}      
        self.by_run = {}      
        self.live_runs = {}   
        self.bytes = 0        
        self.clock = 0        
        self.next_gid = 0
        self.stats = {"run_probes": 0, "run_hits": 0, "admitted": 0, "rejected": 0,
                      "evicted": 0, "case1_kept": 0, "case2_discarded": 0,
                      "case2_completed": 0, "flush_seeded": 0}

    
    def group_bytes(self, n):
        return META_BYTES + 2 * self.key_bytes + n * (self.key_bytes + self.value_bytes + 1)

    def _now(self):
        self.clock += 1
        return self.clock

    def _add(self, run, lb, ub, entries, ts, origin):
        g = KVGroup(self.next_gid, run, lb, ub, entries, ts, origin)
        self.next_gid += 1
        self.groups[g.gid] = g
        self.by_run.setdefault(run.run_id, []).append(g)
        self.bytes += self.group_bytes(g.n)

    def _remove(self, g):
        del self.groups[g.gid]
        self.by_run[g.run.run_id].remove(g)
        if not self.by_run[g.run.run_id]:
            del self.by_run[g.run.run_id]
        self.bytes -= self.group_bytes(g.n)

    def _groups_in(self, run, lo, hi):
        found = [g for g in self.by_run.get(run.run_id, []) if g.lb <= hi and g.ub >= lo]
        return sorted(found, key=lambda g: g.lb)

    def _admit_prob(self, n):
        return 1.0 / max(n, 1)                 

    def _evict_to_fit(self):
        while self.bytes > self.capacity and self.groups:
            oldest = min(self.groups.values(), key=lambda g: (g.ts, g.gid))
            self._remove(oldest)
            self.stats["evicted"] += 1

  
    def lookup(self, run, lo, hi):
        self.stats["run_probes"] += 1
        groups = self._groups_in(run, lo, hi)
        served = []
        for g in groups:
            g.hit = True
            served.extend(g.entries_in(lo, hi))
        
        uncovered = _subtract(lo, hi, _merge_intervals((g.lb, g.ub) for g in groups))
        uncovered = [(a, b) for a, b in uncovered if run.has_keys_in(a, b)]
        if not uncovered:
            self.stats["run_hits"] += 1           
        if groups:
            ts = self._now()
            for g in groups:                      
                if self.rng.random() < self._admit_prob(g.n):
                    g.ts = ts
        return served, uncovered

    def admit(self, run, block_index, lo, hi):
        olo, ohi = run.owned_interval(block_index)
        lb = lo if olo is None else max(lo, olo)
        ub = hi if ohi is None else min(hi, ohi)
        block = run.blocks[block_index]
        entries = block.entries_in(lb, ub)
        if not entries:
            return
       
        if self.rng.random() >= self._admit_prob(len(entries)):
            self.stats["rejected"] += 1
            return
        
        for g in self._groups_in(run, lb - 1, ub + 1):
            if run.owner_index(g.lb) == block_index:
                lb, ub = min(lb, g.lb), max(ub, g.ub)
                self._remove(g)
        self._add(run, lb, ub, block.entries_in(lb, ub), self._now(), "query")
        self.stats["admitted"] += 1
        self._evict_to_fit()

    
    def on_flush(self, new_run, entries):
        self.live_runs[new_run.run_id] = new_run
        if not self.seed_on_flush or not self.groups:
            return                               
        
        ranges = []
        for g in sorted(self.groups.values(), key=lambda g: g.lb):
            if ranges and g.lb <= ranges[-1][1] + 1:
                ranges[-1][1] = max(ranges[-1][1], g.ub)
                ranges[-1][2] = max(ranges[-1][2], g.ts)
            else:
                ranges.append([g.lb, g.ub, g.ts])
       
        keys = [k for k, _ in entries]
        for lo, hi, ts in ranges:
            if bisect_right(keys, hi) > bisect_left(keys, lo):
                self.stats["flush_seeded"] += self._install(new_run, lo, hi, entries, ts,
                                                            "flush_seed")
        self._evict_to_fit()

   
    def on_compaction(self, inputs, outputs, merged):
        old = []
        for run in inputs:
            self.live_runs.pop(run.run_id, None)
            old.extend(self.by_run.get(run.run_id, []))
        for g in list(old):
            self._remove(g)
        for out in outputs:
            self.live_runs[out.run_id] = out
        if not outputs or not old:
            return
      
        old.sort(key=lambda g: g.lb)
        comps = [[old[0]]]
        for g in old[1:]:
            if g.lb <= max(x.ub for x in comps[-1]) + 1:
                comps[-1].append(g)
            else:
                comps.append([g])
       
        for comp in comps:
            L, U = min(g.lb for g in comp), max(g.ub for g in comp)
            cached_keys = {k for g in comp for k in g.keys}
            out_keys = [k for k, _ in _slice(merged, L, U)]
            ts = min(g.ts for g in comp)
            if all(k in cached_keys for k in out_keys):
                origin = "case1"                 
                self.stats["case1_kept"] += 1
            elif self.complete_on_compaction:
                origin = "completed"            
                self.stats["case2_completed"] += 1
            else:
                self.stats["case2_discarded"] += 1   
                continue
           
            for out in outputs:
                if out.max_key >= L and out.min_key <= U:
                    self._install(out, L, U, list(out.entries()), ts, origin)
        self._evict_to_fit()

    def _install(self, run, L, U, entries, ts, origin):
        made = 0
        i = run.owner_index(L)
        while i < len(run.blocks):
            olo, ohi = run.owned_interval(i)
            if olo is not None and olo > U:
                break
            lb = L if olo is None else max(L, olo)
            ub = U if ohi is None else min(U, ohi)
            part = _slice(entries, lb, ub)
            if part:
                self._add(run, lb, ub, part, ts, origin)
                made += 1
            i += 1
        return made


    def check_invariants(self):
        total = 0
        for run_id, groups in self.by_run.items():
            assert run_id in self.live_runs, "group cached for a run that no longer exists"
            for g in groups:
                block = g.run.owner_index(g.lb)
                assert g.run.owner_index(g.ub) == block, "group crosses a block boundary"
                truth = g.run.blocks[block].entries_in(g.lb, g.ub)
                assert list(zip(g.keys, g.values)) == truth, "group differs from its run"
                total += self.group_bytes(g.n)
        assert total == self.bytes and self.bytes <= self.capacity
