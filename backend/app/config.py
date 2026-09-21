from dataclasses import dataclass


@dataclass
class LSMConfig:
    memtable_capacity: int = 4
    base_level_capacity: int = 8
    size_ratio: int = 4
    num_levels: int = 4
