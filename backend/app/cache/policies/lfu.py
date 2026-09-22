from ..coverage import compute_coverage
from ..group_store import GroupStore
from ..serialize import group_dict
from ..sizing import group_size
from ..types import KVGroup


class LFUPolicy:
    def __init__(self, capacity_bytes):
        self.store = GroupStore(capacity_bytes)
        self.frequency = {}

    def find_covering(self, run_id, lo, hi):
        return compute_coverage(self.store.groups_for_run(run_id), lo, hi)

    def record_hit(self, groups):
        for g in groups:
            self.frequency[g.id] = self.frequency.get(g.id, 0) + 1

    def admit(self, run_id, level, lo, hi, entries, is_point):
        if not entries:
            return
        size_bytes = group_size(entries)
        self._evict_to_fit(size_bytes)
        gid = self.store.new_id()
        group = KVGroup(gid, run_id, level, lo, hi, entries, is_point, gid, size_bytes)
        self.store.add(group)
        self.frequency[gid] = 1

    def _evict_to_fit(self, size_bytes):
        while not self.store.has_room(size_bytes) and self.frequency:
            victim_id = min(self.frequency, key=lambda gid: (self.frequency[gid], gid))
            self.frequency.pop(victim_id, None)
            self.store.remove(victim_id)

    def on_compaction(self, source_run_ids, new_run_id, new_level, new_run_entries):
        for run_id in source_run_ids:
            for g in self.store.remove_run(run_id):
                self.frequency.pop(g.id, None)

    def snapshot(self):
        return {
            "policy": "LFU",
            "capacity_bytes": self.store.capacity_bytes,
            "used_bytes": self.store.total_bytes,
            "groups": [
                group_dict(g, {"frequency": self.frequency.get(g.id, 0)})
                for g in self.store.groups.values()
            ],
        }
