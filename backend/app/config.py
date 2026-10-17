"""Engine configuration. All sizes are counted in KV entries unless stated."""
from dataclasses import dataclass


@dataclass(frozen=True)
class LSMConfig:
    block_size: int = 16          # KVs per data block (one block = one disk I/O)
    memtable_size: int = 256      # entries before the MemTable is flushed to L0
    size_ratio: int = 10          # T: each level is T times larger than the previous
    l0_run_limit: int = 4         # L0 runs allowed before compacting into L1
    l1_capacity: int = 4096       # entries allowed in L1 (Li = l1_capacity * T^(i-1))
    policy: str = "leveling"      # "leveling" or "tiering"
    # Leveling granularity. "file" (default, like LevelDB/RocksDB): levels >= 1 hold many
    # non-overlapping SST files; a compaction merges ONE file with the next level's
    # overlapping files (or moves it down if nothing overlaps). "level": merge whole levels
    # (simpler, but rewrites far more data and invalidates far more cache).
    granularity: str = "file"
    file_size: int = 0            # entries per SST file; 0 = memtable_size
    # Filter model. True = ideal filters (zero false positives): a run is probed only
    # if it really holds the key / a key in the range. Group Cache assumes this for
    # scans (range filters, p.47:5 footnote 1). State this assumption in the paper.
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
