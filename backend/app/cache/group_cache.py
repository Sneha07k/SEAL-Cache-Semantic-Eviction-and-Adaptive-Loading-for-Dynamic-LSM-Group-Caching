import heapq
import random
from bisect import bisect_left, bisect_right
from itertools import count

from ..lsm.io import LSMObserver

META_BYTES = 77
MAINT_ORIGINS = ("flush_seed", "completed")     


class KVGroup:
    __slots__ = ("gid", "run", "lb", "ub", "keys", "values", "ts", "origin", "hit")

    def __init__(self, gid, run, lb, ub, entries, ts, origin):
        self.gid, self.run, self.lb, self.ub, self.ts, self.origin = gid, run, lb, ub, ts, origin
        self.hit = False        
        self.keys = [k for k, _ in entries]
        self.values = [v for _, v in entries]

    @property
    def n(self):
        return len(self.keys)

    def entries_in(self, lo, hi):
        i, j = bisect_left(self.keys, lo), bisect_right(self.keys, hi)
        return list(zip(self.keys[i:j], self.values[i:j]))


def _merge_intervals(intervals):
    out = []
    for lo, hi in sorted(intervals):
        if out and lo <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [tuple(x) for x in out]


def _subtract(lo, hi, covered):
    gaps, cur = [], lo
    for a, b in covered:
        if b < cur:
            continue
        if a > hi:
            break
        if a > cur:
            gaps.append((cur, a - 1))
        cur = max(cur, b + 1)
        if cur > hi:
            break
    if cur <= hi:
        gaps.append((cur, hi))
    return gaps


def _slice(entries, lo, hi):
    keys = [k for k, _ in entries]
    return entries[bisect_left(keys, lo):bisect_right(keys, hi)]


class GroupCache(LSMObserver):
    name = "group_cache"

    def __init__(self, capacity_bytes, key_bytes=8, value_bytes=256, seed=0,
                 complete_on_compaction=False, seed_on_flush=False, admission="lru-s",
                 zio_rule="naive", zio_priority="inherit", hot_frac=0.25):
        self.capacity = capacity_bytes
        self.key_bytes, self.value_bytes = key_bytes, value_bytes
        self.rng = random.Random(seed)
        self.complete_on_compaction = complete_on_compaction
        self.seed_on_flush = seed_on_flush
        if admission not in ("lru-s", "always"):
            raise ValueError(admission)
        self.admission = admission        
     
        if zio_rule not in ("naive", "lrus", "hot") or zio_priority not in ("inherit", "tail"):
            raise ValueError((zio_rule, zio_priority))
        self.zio_rule, self.zio_priority, self.hot_frac = zio_rule, zio_priority, hot_frac
        self.groups = {}       
        self.by_run = {}         
        self.bytes = 0
        self._clock = count(1)
        self._gids = count()
        self._heap = []          
        self.live_runs = {}      
        self.stats = {"run_probes": 0, "run_hits": 0, "admitted": 0, "rejected": 0,
                      "evicted": 0, "case1_kept": 0, "case2_discarded": 0,
                      "case2_completed": 0, "flush_seeded": 0, "zio_skipped": 0}
       
        for o in MAINT_ORIGINS:
            for k in ("groups_created", "kv_copied", "maint_groups", "maint_bytes",
                      "evicted_hit", "evicted_unused", "retired_hit", "retired_unused"):
                self.stats[f"{k}_{o}"] = 0

    
    def maintenance_report(self):
        out = {f"resident_{s}_{o}": 0 for o in MAINT_ORIGINS for s in ("hit", "unused")}
        for g in self.groups.values():
            if g.origin in MAINT_ORIGINS:
                out[f"resident_{'hit' if g.hit else 'unused'}_{g.origin}"] += 1
        return out

    def group_bytes(self, n):
        return META_BYTES + 2 * self.key_bytes + n * (self.key_bytes + self.value_bytes + 1)

    def _now(self):
        return next(self._clock)

    def _add(self, run, lb, ub, entries, ts, origin):
        g = KVGroup(next(self._gids), run, lb, ub, entries, ts, origin)
        self.groups[g.gid] = g
        lst = self.by_run.setdefault(run.run_id, [])
        lst.insert(bisect_left(lst, (lb, g.gid)), (lb, g.gid))
        self.bytes += self.group_bytes(g.n)
        heapq.heappush(self._heap, (ts, g.gid))
        if origin in MAINT_ORIGINS:
            st = self.stats
            st[f"groups_created_{origin}"] += 1
            st[f"kv_copied_{origin}"] += g.n
            st[f"maint_groups_{origin}"] += 1
            st[f"maint_bytes_{origin}"] += self.group_bytes(g.n)
        return g

    def _remove(self, g, reason="retired"):
        del self.groups[g.gid]
        lst = self.by_run[g.run.run_id]
        lst.pop(bisect_left(lst, (g.lb, g.gid)))
        if not lst:
            del self.by_run[g.run.run_id]
        self.bytes -= self.group_bytes(g.n)
        if g.origin in MAINT_ORIGINS:
            st = self.stats
            st[f"maint_groups_{g.origin}"] -= 1
            st[f"maint_bytes_{g.origin}"] -= self.group_bytes(g.n)
            st[f"{reason}_{'hit' if g.hit else 'unused'}_{g.origin}"] += 1

    def _touch(self, g, ts):
        g.ts = ts
        heapq.heappush(self._heap, (ts, g.gid))
        if len(self._heap) > 4 * len(self.groups) + 1024:      # drop stale entries
            self._heap = [(x.ts, x.gid) for x in self.groups.values()]
            heapq.heapify(self._heap)

    def _evict_to_fit(self):
        while self.bytes > self.capacity and self._heap:
            ts, gid = heapq.heappop(self._heap)
            g = self.groups.get(gid)
            if g is None or g.ts != ts:
                continue               
            self._remove(g, "evicted")
            self.stats["evicted"] += 1
        if not self.groups:
            self._heap = []

    def _admit_prob(self, n):
        if self.admission == "always":
            return 1.0
        return 1.0 / max(n, 1)                

   
    def _overlapping(self, run, lo, hi):
        lst = self.by_run.get(run.run_id)
        if not lst:
            return []
      
        i = max(bisect_right(lst, (lo, float("inf"))) - 1, 0)
        out = []
        while i < len(lst) and lst[i][0] <= hi:
            g = self.groups[lst[i][1]]
            if g.ub >= lo:
                out.append(g)
            i += 1
        return out

    def lookup(self, run, lo, hi):
        self.stats["run_probes"] += 1
        groups = self._overlapping(run, lo, hi)
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
                    self._touch(g, ts)
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
       
        for g in self._overlapping(run, lb - 1, ub + 1):
            if run.owner_index(g.lb) == block_index:
                lb, ub = min(lb, g.lb), max(ub, g.ub)
                self._remove(g)
        self._add(run, lb, ub, block.entries_in(lb, ub), self._now(), "query")
        self.stats["admitted"] += 1
        self._evict_to_fit()

    
    def _hot_cutoff(self):
       
        if not self.groups:
            return None
        ts = sorted(g.ts for g in self.groups.values())
        return ts[min(int(len(ts) * (1 - self.hot_frac)), len(ts) - 1)]

    def _zio_decide(self, n_new, n_old, source_ts, cutoff, hot_ts=None):
       
        hot_ts = source_ts if hot_ts is None else hot_ts
        if self.zio_rule == "hot" and cutoff is not None and hot_ts < cutoff:
            return None
        if self.zio_rule in ("lrus", "hot"):
            p = (n_old / n_new) if n_old else (1.0 / max(n_new, 1))
            if self.rng.random() >= min(p, 1.0):
                return None
        if self.zio_priority == "tail":
            low = min((g.ts for g in self.groups.values()), default=1)
            return low - 1
        return source_ts

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
        cutoff = self._hot_cutoff() if self.zio_rule == "hot" else None
        keys = [k for k, _ in entries]
        for lo, hi, src_ts in ranges:
            n_new = bisect_right(keys, hi) - bisect_left(keys, lo)
            if n_new == 0:
                continue
            ts = self._zio_decide(n_new, 0, src_ts, cutoff)
            if ts is None:
                self.stats["zio_skipped"] += 1
                continue
            self.stats["flush_seeded"] += self._install(new_run, lo, hi, entries, ts,
                                                        "flush_seed")
        self._evict_to_fit()

    def on_compaction(self, inputs, outputs, merged):
        members = []
        for run in inputs:
            self.live_runs.pop(run.run_id, None)
            for _, gid in list(self.by_run.get(run.run_id, [])):
                members.append(self.groups[gid])
        for g in members:
            self._remove(g)
        for out in outputs:
            self.live_runs[out.run_id] = out
        if not outputs or not members:
            return
        out_entries = {o.run_id: list(o.entries()) for o in outputs}
        # Connected components of member ranges (overlapping or adjacent).
        members.sort(key=lambda g: g.lb)
        comps, cur = [], [members[0]]
        hi = members[0].ub
        for g in members[1:]:
            if g.lb <= hi + 1:
                cur.append(g)
                hi = max(hi, g.ub)
            else:
                comps.append(cur)
                cur, hi = [g], g.ub
        comps.append(cur)

        cutoff = self._hot_cutoff() if self.zio_rule == "hot" else None
        for comp in comps:
            L, U = min(g.lb for g in comp), max(g.ub for g in comp)
            cached_keys = {k for g in comp for k in g.keys}
            out_keys = [k for k, _ in _slice(merged, L, U)]
            ts = min(g.ts for g in comp)            
            if all(k in cached_keys for k in out_keys):
                origin = "case1"
                self.stats["case1_kept"] += 1
            elif self.complete_on_compaction:
                ts = self._zio_decide(len(out_keys), len(cached_keys), ts, cutoff,
                                      hot_ts=max(g.ts for g in comp))
                if ts is None:
                    self.stats["case2_discarded"] += 1
                    self.stats["zio_skipped"] += 1
                    continue
                origin = "completed"
                self.stats["case2_completed"] += 1
            else:
                self.stats["case2_discarded"] += 1
                continue
            for out in outputs:                      
                if out.max_key >= L and out.min_key <= U:
                    self._install(out, L, U, out_entries[out.run_id], ts, origin)
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
        for run_id, lst in self.by_run.items():
            assert run_id in self.live_runs, "group cached for a run that no longer exists"
            assert lst == sorted(lst)
            prev_ub = None
            for lb, gid in lst:
                g = self.groups[gid]
                assert g.lb == lb and g.run.run_id == run_id
                if prev_ub is not None:
                    assert lb > prev_ub, "overlapping groups in one run"
                prev_ub = g.ub
                bi = g.run.owner_index(g.lb)
                assert g.run.owner_index(g.ub) == bi, "group crosses a block boundary"
                truth = g.run.blocks[bi].entries_in(g.lb, g.ub)
                assert list(zip(g.keys, g.values)) == truth, "group differs from its run"
                total += self.group_bytes(g.n)
        assert total == self.bytes, f"byte accounting drift {total} != {self.bytes}"
        assert self.bytes <= self.capacity
        st = self.stats
        for o in MAINT_ORIGINS:
            live = [g for g in self.groups.values() if g.origin == o]
            assert st[f"maint_groups_{o}"] == len(live), f"resident count drift ({o})"
            assert st[f"maint_bytes_{o}"] == sum(self.group_bytes(g.n) for g in live), \
                f"maintained byte drift ({o})"
            ended = sum(st[f"{k}_{o}"] for k in
                        ("evicted_hit", "evicted_unused", "retired_hit", "retired_unused"))
            assert st[f"groups_created_{o}"] == ended + len(live), f"group fate leak ({o})"
