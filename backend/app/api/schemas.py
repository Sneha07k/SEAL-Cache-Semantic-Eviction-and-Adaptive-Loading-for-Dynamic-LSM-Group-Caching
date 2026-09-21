from typing import List
from pydantic import BaseModel

class PutRequest(BaseModel):
    key: str
    value: str

class DeleteRequest(BaseModel):
    key: str

class ResetRequest(BaseModel):
    memtable_capacity: int = 4
    base_level_capacity: int = 8
    size_ratio: int = 4
    num_levels: int = 4
    cache_capacity_bytes: int = 500
    seed: int = 1
    replace_threshold: float = 0.5
    max_deltas_per_group: int = 20
    eager_rebuild_pressure: float = 0.3
    eager_evict_pressure: float = 0.7
    eager_enabled: bool = True
    occupancy_gate: float = 0.6
    low_priority_multiplier: float = 0.5

class ExperimentRequest(BaseModel):
    workload_name: str
    memtable_capacity: int = 4
    base_level_capacity: int = 8
    size_ratio: int = 4
    num_levels: int = 4
    cache_capacity_bytes: int = 500
    seeds: List[int] = [1, 2, 3]
    replace_threshold: float = 0.5
    max_deltas_per_group: int = 20
    eager_rebuild_pressure: float = 0.3
    eager_evict_pressure: float = 0.7
    eager_enabled: bool = True
    occupancy_gate: float = 0.6
    low_priority_multiplier: float = 0.5
