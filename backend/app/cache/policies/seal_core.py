from ..delta_tracker import DeltaTracker
from ..merge import merge_group_entries
from ..reassessment import find_largest_untouched_run, reassess_cluster
from ..sizing import group_size
from ..types import CachedEntry, KVGroup
from .group_cache import GroupCachePolicy


class SealCorePolicy(GroupCachePolicy):
    def __init__(
        self,
        capacity_bytes,
        rng,
        replace_threshold=0.5,
        max_deltas_per_group=20,
        eager_rebuild_pressure=0.3,
        eager_evict_pressure=0.7,
        eager_enabled=True,
    ):
        super().__init__(capacity_bytes, rng)
        self.replace_threshold = replace_threshold
        self.deltas = DeltaTracker(max_deltas_per_group)
        self.eager_rebuild_pressure = eager_rebuild_pressure
        self.eager_evict_pressure = eager_evict_pressure
        self.eager_enabled = eager_enabled

    def resolve_entries(self, groups):
        merged = merge_group_entries(groups)
        suppressed = []
        for g in groups:
            for key in self.deltas.get(g.id):
                if key in merged:
                    merged.pop(key)
                    suppressed.append(key)
        return merged, suppressed

    def record_delta(self, group_id, key, operation, seq):
        if not self.eager_enabled:
            return
        self.deltas.record(group_id, key, operation, seq)

    def maybe_eager_reassess(self, group_id, engine):
        if not self.eager_enabled:
            return None
        group = self.store.groups.get(group_id)
        if group is None:
            self.deltas.clear_group(group_id)
            return None
        delta_count = self.deltas.count(group_id)
        if delta_count == 0:
            return None
        if group.is_point:
            return self._eager_rebuild(group, engine)
        rebuild_threshold, evict_threshold = self._pressure_thresholds(group)
        pressure = delta_count / max(len(group.entries), 1)
        if pressure < rebuild_threshold:
            return None
        if pressure < evict_threshold:
            return self._eager_rebuild(group, engine)
        return self._eager_replace_or_evict(group)

    def _pressure_thresholds(self, group):
        return self.eager_rebuild_pressure, self.eager_evict_pressure

    def _eager_rebuild(self, group, engine):
        deltas = self.deltas.get(group.id)
        refreshed_keys = list(deltas.keys())
        for key in refreshed_keys:
            entry = engine.get_entry(key)
            if entry is not None:
                group.entries[key] = CachedEntry(
                    entry.value, entry.seq, entry.tombstone
                )
            else:
                group.entries.pop(key, None)
        self.deltas.clear_keys(group.id, refreshed_keys)
        if not group.entries:
            self.store.remove(group.id)
            self.order.pop(group.id, None)
            self._log(
                [group], "evict", "eager rebuild left no live keys", trigger="eager"
            )
            return "evict"
        self.store.resize(group.id, group_size(group.entries))
        self._log(
            [group],
            "rebuild",
            f"eager rebuild refreshed {len(refreshed_keys)} delta-affected key(s)",
            trigger="eager",
        )
        return "rebuild"

    def _eager_replace_or_evict(self, group):
        delta_keys = set(self.deltas.get(group.id).keys())
        sorted_keys = sorted(group.entries.keys())
        start, end, run_length = find_largest_untouched_run(sorted_keys, delta_keys)
        self.store.remove(group.id)
        self.order.pop(group.id, None)
        self.deltas.clear_group(group.id)
        if (
            run_length == 0
            or run_length / max(len(sorted_keys), 1) < self.replace_threshold
        ):
            self._log(
                [group],
                "evict",
                "delta pressure critical, insufficient untouched coverage",
                trigger="eager",
            )
            return "evict"
        narrowed_entries = {k: v for k, v in group.entries.items() if start <= k <= end}
        new_size = group_size(narrowed_entries)
        new_gid = self.store.new_id()
        new_group = KVGroup(
            new_gid,
            group.run_id,
            group.level,
            start,
            end,
            narrowed_entries,
            group.is_point,
            new_gid,
            new_size,
        )
        self.store.add(new_group)
        self.order[new_gid] = True
        self.order.move_to_end(new_gid, last=False)
        self._log(
            [group],
            "replace",
            f"delta pressure high, narrowed range to [{start},{end}]",
            trigger="eager",
        )
        return "replace"

    def on_compaction(self, source_run_ids, new_run_id, new_level, new_run_entries):
        affected_ids = []
        for run_id in source_run_ids:
            affected_ids.extend(g.id for g in self.store.groups_for_run(run_id))
        super().on_compaction(source_run_ids, new_run_id, new_level, new_run_entries)
        for gid in affected_ids:
            self.deltas.clear_group(gid)

    def _reconcile_cluster(self, cluster, new_run_id, new_level, new_run_entries):
        lo = min(g.lo for g in cluster)
        hi = max(g.hi for g in cluster)
        is_point = all(g.is_point for g in cluster)
        if is_point:
            key = lo
            if key in new_run_entries:
                entries = {key: new_run_entries[key]}
                self._reinstate(
                    cluster,
                    new_run_id,
                    new_level,
                    lo,
                    hi,
                    entries,
                    True,
                    "keep",
                    "point key still present after compaction",
                )
            else:
                self._log(
                    cluster, "evict", "point key no longer present after compaction"
                )
            return
        merged_entries = merge_group_entries(cluster)
        actual_keys = sorted(k for k in new_run_entries if lo <= k <= hi)
        decision, new_lo, new_hi, reason = reassess_cluster(
            lo, hi, len(cluster), actual_keys, merged_entries, self.replace_threshold
        )
        if decision == "evict":
            self._log(cluster, "evict", reason)
            return
        entries = {k: new_run_entries[k] for k in actual_keys if new_lo <= k <= new_hi}
        self._reinstate(
            cluster,
            new_run_id,
            new_level,
            new_lo,
            new_hi,
            entries,
            False,
            decision,
            reason,
        )

    def snapshot(self):
        base = super().snapshot()
        base["policy"] = "SealCore"
        for entry in base["groups"]:
            delta_count = self.deltas.count(entry["id"])
            group_size_count = len(entry["keys"])
            entry["delta_count"] = delta_count
            entry["delta_pressure"] = delta_count / max(group_size_count, 1)
        return base

    def mechanism_stats(self):
        base = super().mechanism_stats()
        base["total_deltas_recorded"] = self.deltas.total_recorded
        return base
