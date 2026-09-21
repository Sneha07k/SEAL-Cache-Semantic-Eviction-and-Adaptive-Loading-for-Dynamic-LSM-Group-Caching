import time
from dataclasses import dataclass, field
from typing import List

from .types import OperationType


@dataclass
class WriteEvent:
    operation: OperationType
    key: str
    seq: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "type": "write",
            "operation": self.operation.value,
            "key": self.key,
            "seq": self.seq,
            "timestamp": self.timestamp,
        }


@dataclass
class FlushEvent:
    sstable_id: int
    entry_count: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "type": "flush",
            "sstable_id": self.sstable_id,
            "entry_count": self.entry_count,
            "timestamp": self.timestamp,
        }


@dataclass
class CompactionEvent:
    source_ids: List[int]
    new_sstable_id: int
    from_level: int
    to_level: int
    entry_count: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "type": "compaction",
            "source_ids": self.source_ids,
            "new_sstable_id": self.new_sstable_id,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "entry_count": self.entry_count,
            "timestamp": self.timestamp,
        }
