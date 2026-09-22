from dataclasses import dataclass


@dataclass(frozen=True)
class WorkloadConfig:
    name: str
    operation_count: int
    key_space_size: int
    point_read_ratio: float
    range_scan_ratio: float
    insert_ratio: float
    update_ratio: float
    delete_ratio: float
    scan_length_min: int
    scan_length_max: int
