from .seal_core import SealCorePolicy


class AppAwarePolicy(SealCorePolicy):
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

    def snapshot(self):
        base = super().snapshot()
        base["policy"] = "AppAware"
        return base
