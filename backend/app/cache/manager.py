from .detector import find_affected_groups
from .policies.app_aware import AppAwarePolicy
from .policies.group_cache import GroupCachePolicy
from .policies.lfu import LFUPolicy
from .policies.lru import LRUPolicy
from .policies.seal_combined import SealCombinedPolicy
from .policies.seal_core import SealCorePolicy
from .policies.semantic_aware import SemanticAwarePolicy
from .reader import CacheReader
from .types import CachedEntry


class CacheManager:
    def __init__(
        self,
        engine,
        capacity_bytes,
        rng_provider,
        replace_threshold=0.5,
        max_deltas_per_group=20,
        eager_rebuild_pressure=0.3,
        eager_evict_pressure=0.7,
        eager_enabled=False,
        occupancy_gate=0.6,
        low_priority_multiplier=0.5,
    ):
        self.engine = engine
        self.capacity_bytes = capacity_bytes
        self.readers = {
            "lru": CacheReader(LRUPolicy(capacity_bytes)),
            "lfu": CacheReader(LFUPolicy(capacity_bytes)),
            "group_cache": CacheReader(GroupCachePolicy(capacity_bytes, rng_provider.stream("group_cache"))),
            "seal_core": CacheReader(
                SealCorePolicy(
                    capacity_bytes,
                    rng_provider.stream("seal_core"),
                    replace_threshold,
                    max_deltas_per_group,
                    eager_rebuild_pressure,
                    eager_evict_pressure,
                    eager_enabled,
                )
            ),
            "app_aware": CacheReader(
                AppAwarePolicy(
                    capacity_bytes,
                    rng_provider.stream("app_aware"),
                    replace_threshold,
                    max_deltas_per_group,
                    eager_rebuild_pressure,
                    eager_evict_pressure,
                    eager_enabled,
                    occupancy_gate,
                )
            ),
            "semantic_aware": CacheReader(
                SemanticAwarePolicy(
                    capacity_bytes,
                    rng_provider.stream("semantic_aware"),
                    replace_threshold,
                    max_deltas_per_group,
                    eager_rebuild_pressure,
                    eager_evict_pressure,
                    eager_enabled,
                    low_priority_multiplier,
                )
            ),
            "seal_combined": CacheReader(
                SealCombinedPolicy(
                    capacity_bytes,
                    rng_provider.stream("seal_combined"),
                    replace_threshold,
                    max_deltas_per_group,
                    eager_rebuild_pressure,
                    eager_evict_pressure,
                    eager_enabled,
                    occupancy_gate,
                    low_priority_multiplier,
                )
            ),
        }
        self.affected_log = []
        self.compaction_log = []
        engine.add_write_listener(self._on_write)
        engine.add_compaction_listener(self._on_compaction)

    def read_point(self, engine, key):
        results = {}
        for name, reader in self.readers.items():
            value, stats = reader.read_point(engine, key)
            results[name] = {"value": value, "stats": stats}
        return results

    def read_range(self, engine, lo, hi):
        results = {}
        for name, reader in self.readers.items():
            values, stats = reader.read_range(engine, lo, hi)
            results[name] = {"values": values, "stats": stats}
        return results

    def _on_write(self, operation_type, key, seq):
        for name, reader in self.readers.items():
            policy = reader.policy
            affected = find_affected_groups(policy.store, key)
            record_delta = getattr(policy, "record_delta", None)
            reassess = getattr(policy, "maybe_eager_reassess", None)
            for group in affected:
                self.affected_log.append({
                    "policy": name,
                    "group_id": group.id,
                    "range": [group.lo, group.hi],
                    "key": key,
                    "operation": operation_type,
                })
                if record_delta is not None:
                    record_delta(group.id, key, operation_type, seq)
            if reassess is not None:
                for group in affected:
                    reassess(group.id, self.engine)
        if len(self.affected_log) > 200:
            self.affected_log = self.affected_log[-200:]

    def _on_compaction(self, source_ids, new_sstable, from_level, to_level):
        entries = {kv.key: CachedEntry(kv.value, kv.seq, kv.tombstone) for kv in new_sstable.entries}
        before_lengths = {
            name: len(self.readers[name].policy.decision_log)
            for name in ("group_cache", "seal_core")
        }
        for reader in self.readers.values():
            reader.on_compaction(source_ids, new_sstable.id, to_level, entries)
        group_cache_new = self.readers["group_cache"].policy.decision_log[before_lengths["group_cache"]:]
        seal_core_new = self.readers["seal_core"].policy.decision_log[before_lengths["seal_core"]:]
        if group_cache_new or seal_core_new:
            self.compaction_log.append({
                "source_ids": source_ids,
                "new_run_id": new_sstable.id,
                "to_level": to_level,
                "group_cache_decisions": group_cache_new,
                "seal_core_decisions": seal_core_new,
            })
        if len(self.compaction_log) > 100:
            self.compaction_log = self.compaction_log[-100:]

    def snapshot(self):
        return {name: reader.snapshot() for name, reader in self.readers.items()}

    def affected_snapshot(self):
        return self.affected_log[-30:]

    def compaction_snapshot(self):
        return self.compaction_log[-30:]
