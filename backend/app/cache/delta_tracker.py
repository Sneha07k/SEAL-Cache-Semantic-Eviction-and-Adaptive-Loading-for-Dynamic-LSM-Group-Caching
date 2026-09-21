from dataclasses import dataclass


@dataclass(frozen=True)
class Delta:
    key: str
    operation: str
    seq: int


class DeltaTracker:
    def __init__(self, max_deltas_per_group=20):
        self.max_deltas_per_group = max_deltas_per_group
        self.deltas_by_group = {}
        self.total_recorded = 0

    def record(self, group_id, key, operation, seq):
        self.total_recorded += 1
        deltas = self.deltas_by_group.setdefault(group_id, {})
        existing = deltas.get(key)
        if existing is None or seq > existing.seq:
            deltas[key] = Delta(key, operation, seq)
        if len(deltas) > self.max_deltas_per_group:
            oldest_key = min(deltas, key=lambda k: deltas[k].seq)
            if oldest_key != key:
                deltas.pop(oldest_key, None)

    def get(self, group_id):
        return self.deltas_by_group.get(group_id, {})

    def count(self, group_id):
        return len(self.deltas_by_group.get(group_id, {}))

    def clear_group(self, group_id):
        self.deltas_by_group.pop(group_id, None)

    def clear_keys(self, group_id, keys):
        deltas = self.deltas_by_group.get(group_id)
        if not deltas:
            return
        for key in keys:
            deltas.pop(key, None)
        if not deltas:
            self.deltas_by_group.pop(group_id, None)
