from ..semantics import classify_group
from .seal_core import SealCorePolicy


class SealCombinedPolicy(SealCorePolicy):
    def __init__(
        self,
        capacity_bytes,
        rng,
        replace_threshold=0.5,
        max_deltas_per_group=20,
        eager_rebuild_pressure=0.3,
        eager_evict_pressure=0.7,
        eager_enabled=True,
        occupancy_gate=0.6,
        low_priority_multiplier=0.5,
    ):
        super().__init__(
            capacity_bytes,
            rng,
            replace_threshold,
            max_deltas_per_group,
            eager_rebuild_pressure,
            eager_evict_pressure,
            eager_enabled,
        )
        self.occupancy_gate = occupancy_gate
        self.low_priority_multiplier = low_priority_multiplier

    def maybe_eager_reassess(self, group_id, engine):
        if not self.eager_enabled:
            return None
        occupancy = (
            self.store.total_bytes / self.store.capacity_bytes
            if self.store.capacity_bytes
            else 0.0
        )
        if occupancy > self.occupancy_gate:
            return None
        return super().maybe_eager_reassess(group_id, engine)

    def _pressure_thresholds(self, group):
        priority_class = classify_group(group.entries.keys())
        if priority_class == "critical":
            return 1.0, 1.0
        multiplier = (
            self.low_priority_multiplier if priority_class == "low_priority" else 1.0
        )
        rebuild = min(self.eager_rebuild_pressure * multiplier, 1.0)
        evict = min(self.eager_evict_pressure * multiplier, 1.0)
        return rebuild, evict

    def snapshot(self):
        base = super().snapshot()
        base["policy"] = "SealCombined"
        for entry in base["groups"]:
            entry["priority_class"] = classify_group(entry["keys"])
        return base
