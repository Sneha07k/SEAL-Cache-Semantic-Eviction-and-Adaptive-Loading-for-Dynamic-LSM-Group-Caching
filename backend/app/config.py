
from dataclasses import dataclass


@dataclass(frozen=True)
class LSMConfig:
    block_size: int = 16        
    memtable_size: int = 256    
    size_ratio: int = 10        
    l0_run_limit: int = 4       
    l1_capacity: int = 4096     
    policy: str = "leveling"    
    
    granularity: str = "file"
    file_size: int = 0           
  
    ideal_filters: bool = True

    def __post_init__(self):
        if self.policy not in ("leveling", "tiering"):
            raise ValueError(f"unknown policy {self.policy}")
        if self.granularity not in ("file", "level"):
            raise ValueError(f"unknown granularity {self.granularity}")
        if self.block_size < 1 or self.memtable_size < 1 or self.file_size < 0:
            raise ValueError("sizes must be positive")

    @property
    def sst_entries(self):
        return self.file_size or self.memtable_size
