from ..semantics import classify_group
from .seal_core import SealCorePolicy


class SemanticAwarePolicy(SealCorePolicy):
    def __init__(
        self,
        capacity_bytes,
        rng,
        replace_threshold=0.5,
        max_deltas_per_group=20,
        eager_rebuild_pressure=0.3,
        eager_evict_pressure=0.7,
        eager_enabled=True,
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
        self.low_priority_multiplier = low_priority_multiplier

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
        base["policy"] = "SemanticAware"
        for entry in base["groups"]:
            entry["priority_class"] = classify_group(entry["keys"])
        return base
