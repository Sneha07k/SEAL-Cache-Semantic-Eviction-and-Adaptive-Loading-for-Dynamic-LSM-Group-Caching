from .merge import merge_group_entries
from .types import CachedEntry


class CacheReader:
    def __init__(self, policy):
        self.policy = policy

    def _resolve(self, used):
        resolver = getattr(self.policy, "resolve_entries", None)
        if resolver is not None:
            return resolver(used)
        return merge_group_entries(used), []

    def read_point(self, engine, key):
        mem_hit = engine.memtable.get(key)
        if mem_hit is not None:
            value = None if mem_hit.tombstone else mem_hit.value
            return value, {"hits": 0, "misses": 0, "delta_suppressions": 0}
        hits = 0
        misses = 0
        delta_suppressions = 0
        for level in engine.levels:
            level_candidates = []
            for run in level.runs:
                if not run.overlaps(key, key):
                    continue
                covered, used = self.policy.find_covering(run.id, key, key)
                if covered:
                    hits += 1
                    self.policy.record_hit(used)
                    resolved, suppressed = self._resolve(used)
                    delta_suppressions += len(suppressed)
                    entry = resolved.get(key)
                    if entry is not None:
                        level_candidates.append(entry)
                    continue
                misses += 1
                hit = run.get(key)
                if hit is not None:
                    entry = CachedEntry(hit.value, hit.seq, hit.tombstone)
                    level_candidates.append(entry)
                    self.policy.admit(
                        run.id, level.number, key, key, {key: entry}, True
                    )
            if level_candidates:
                best = max(level_candidates, key=lambda e: e.seq)
                value = None if best.tombstone else best.value
                return value, {
                    "hits": hits,
                    "misses": misses,
                    "delta_suppressions": delta_suppressions,
                }
        return None, {
            "hits": hits,
            "misses": misses,
            "delta_suppressions": delta_suppressions,
        }

    def read_range(self, engine, lo, hi):
        latest = {}
        for kv in engine.memtable.scan(lo, hi):
            latest[kv.key] = CachedEntry(kv.value, kv.seq, kv.tombstone)
        hits = 0
        misses = 0
        delta_suppressions = 0
        for level in engine.levels:
            for run in level.runs:
                if not run.overlaps(lo, hi):
                    continue
                covered, used = self.policy.find_covering(run.id, lo, hi)
                if covered:
                    hits += 1
                    self.policy.record_hit(used)
                    resolved, suppressed = self._resolve(used)
                    delta_suppressions += len(suppressed)
                    for k, entry in resolved.items():
                        if lo <= k <= hi:
                            existing = latest.get(k)
                            if existing is None or entry.seq > existing.seq:
                                latest[k] = entry
                    continue
                misses += 1
                fetched = run.scan(lo, hi)
                entries = {
                    kv.key: CachedEntry(kv.value, kv.seq, kv.tombstone)
                    for kv in fetched
                }
                for k, entry in entries.items():
                    existing = latest.get(k)
                    if existing is None or entry.seq > existing.seq:
                        latest[k] = entry
                self.policy.admit(run.id, level.number, lo, hi, entries, False)
        result = {k: e.value for k, e in latest.items() if not e.tombstone}
        return dict(sorted(result.items())), {
            "hits": hits,
            "misses": misses,
            "delta_suppressions": delta_suppressions,
        }

    def on_compaction(self, source_run_ids, new_run_id, new_level, new_run_entries):
        self.policy.on_compaction(
            source_run_ids, new_run_id, new_level, new_run_entries
        )

    def snapshot(self):
        return self.policy.snapshot()
