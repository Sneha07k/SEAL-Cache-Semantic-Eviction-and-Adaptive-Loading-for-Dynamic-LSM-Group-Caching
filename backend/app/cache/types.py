from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class CachedEntry:
    value: str
    seq: int
    tombstone: bool


@dataclass
class KVGroup:
    id: int
    run_id: int
    level: int
    lo: str
    hi: str
    entries: Dict[str, CachedEntry]
    is_point: bool
    created_at: int
    size_bytes: int
