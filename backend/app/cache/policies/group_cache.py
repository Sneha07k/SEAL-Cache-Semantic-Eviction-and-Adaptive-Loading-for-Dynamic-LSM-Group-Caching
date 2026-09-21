from collections import OrderedDict

from ..coverage import compute_coverage
from ..group_store import GroupStore
from ..merge import merge_group_entries
from ..serialize import group_dict
from ..sizing import group_size
from ..types import KVGroup


class GroupCachePolicy:
    def __init__(self, capacity_bytes, rng):
        self.store = GroupStore(capacity_bytes)
        self.order = OrderedDict()
        self.decision_log = []
        self.rng = rng
        self.total_admissions = 0

    def find_covering(self, run_id, lo, hi):
        return compute_coverage(self.store.groups_for_run(run_id), lo, hi)

    def record_hit(self, groups):
        for g in groups:
            probability = 1.0 / max(len(g.entries), 1)
            if self.rng.random() < probability:
                self.order.move_to_end(g.id)

    def admit(self, run_id, level, lo, hi, entries, is_point):
        size = len(entries)
        if size == 0:
            return
        probability = 1.0 / max(size, 1)
        if self.rng.random() >= probability:
            return
        size_bytes = group_size(entries)
        self._evict_to_fit(size_bytes)
        gid = self.store.new_id()
        group = KVGroup(gid, run_id, level, lo, hi, entries, is_point, gid, size_bytes)
        self.store.add(group)
        self.order[gid] = True
        self.total_admissions += 1

    def _evict_to_fit(self, size_bytes):
        while not self.store.has_room(size_bytes) and self.order:
            victim_id, _ = self.order.popitem(last=False)
            self.store.remove(victim_id)

    def on_compaction(self, source_run_ids, new_run_id, new_level, new_run_entries):
        affected = []
        for run_id in source_run_ids:
            affected.extend(self.store.groups_for_run(run_id))
        for g in affected:
            self.store.remove(g.id)
            self.order.pop(g.id, None)
        for cluster in self._cluster_by_range(affected):
            self._reconcile_cluster(cluster, new_run_id, new_level, new_run_entries)

    def _cluster_by_range(self, groups):
        if not groups:
            return []
        groups = sorted(groups, key=lambda g: g.lo)
        clusters = [[groups[0]]]
        frontier = groups[0].hi
        for g in groups[1:]:
            if g.lo <= frontier:
                clusters[-1].append(g)
                frontier = max(frontier, g.hi)
            else:
                clusters.append([g])
                frontier = g.hi
        return clusters

    def _reconcile_cluster(self, cluster, new_run_id, new_level, new_run_entries):
        lo = min(g.lo for g in cluster)
        hi = max(g.hi for g in cluster)
        is_point = all(g.is_point for g in cluster)
        if is_point:
            key = lo
            if key in new_run_entries:
                entries = {key: new_run_entries[key]}
                self._reinstate(
                    cluster, new_run_id, new_level, lo, hi, entries, True, "keep"
                )
            else:
                self._log(
                    cluster, "evict", "point key no longer present after compaction"
                )
            return
        merged_entries = merge_group_entries(cluster)
        actual_keys = [k for k in new_run_entries if lo <= k <= hi]
        missing = [k for k in actual_keys if k not in merged_entries]
        if missing:
            self._log(
                cluster, "evict", f"{len(missing)} key(s) uncovered after compaction"
            )
            return
        entries = {k: new_run_entries[k] for k in actual_keys}
        if not entries:
            self._log(cluster, "evict", "no live keys remain in range")
            return
        decision = "rebuild" if len(cluster) > 1 else "keep"
        self._reinstate(
            cluster, new_run_id, new_level, lo, hi, entries, False, decision
        )

    def _reinstate(
        self,
        cluster,
        new_run_id,
        new_level,
        lo,
        hi,
        entries,
        is_point,
        decision,
        reason="coverage confirmed after compaction",
    ):
        size_bytes = group_size(entries)
        self._evict_to_fit(size_bytes)
        gid = self.store.new_id()
        group = KVGroup(
            gid, new_run_id, new_level, lo, hi, entries, is_point, gid, size_bytes
        )
        self.store.add(group)
        self.order[gid] = True
        self.order.move_to_end(gid, last=False)
        self._log(cluster, decision, reason)

    def _log(self, cluster, action, reason, trigger="compaction"):
        self.decision_log.append(
            {
                "action": action,
                "reason": reason,
                "trigger": trigger,
                "source_group_ids": [g.id for g in cluster],
                "range": [min(g.lo for g in cluster), max(g.hi for g in cluster)],
            }
        )

    def mechanism_stats(self):
        return {"total_admissions": self.total_admissions}

    def snapshot(self):
        return {
            "policy": "GroupCache",
            "capacity_bytes": self.store.capacity_bytes,
            "used_bytes": self.store.total_bytes,
            "groups": [group_dict(g) for g in self.store.groups.values()],
            "recent_decisions": self.decision_log[-30:],
        }
