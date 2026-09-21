import itertools

from .events import CompactionEvent, FlushEvent, WriteEvent
from .level import Level
from .memtable import MemTable
from .sstable import SSTable
from .types import OperationType


class LSMEngine:
    def __init__(self, config):
        self.config = config
        self.seq_counter = itertools.count(1)
        self.memtable = MemTable(config.memtable_capacity)
        self.levels = [
            Level(
                number=i,
                capacity=config.base_level_capacity * (config.size_ratio ** i),
                tiered=(i == 0),
            )
            for i in range(config.num_levels)
        ]
        self.events = []
        self.compaction_listeners = []
        self.write_listeners = []

    def add_compaction_listener(self, listener):
        self.compaction_listeners.append(listener)

    def add_write_listener(self, listener):
        self.write_listeners.append(listener)

    def next_seq(self):
        return next(self.seq_counter)

    def put(self, key, value):
        seq = self.next_seq()
        self.memtable.put(key, value, seq)
        self.events.append(WriteEvent(OperationType.PUT, key, seq))
        for listener in self.write_listeners:
            listener("PUT", key, seq)
        self._maybe_flush()

    def delete(self, key):
        seq = self.next_seq()
        self.memtable.delete(key, seq)
        self.events.append(WriteEvent(OperationType.DELETE, key, seq))
        for listener in self.write_listeners:
            listener("DELETE", key, seq)
        self._maybe_flush()

    def get(self, key):
        entry = self.get_entry(key)
        if entry is None:
            return None
        return None if entry.tombstone else entry.value

    def get_entry(self, key):
        mem_hit = self.memtable.get(key)
        if mem_hit is not None:
            return mem_hit
        for level in self.levels:
            candidates = []
            for run in level.runs:
                if run.overlaps(key, key):
                    hit = run.get(key)
                    if hit is not None:
                        candidates.append(hit)
            if candidates:
                return max(candidates, key=lambda kv: kv.seq)
        return None

    def scan(self, lo, hi):
        latest = {}
        for kv in self.memtable.scan(lo, hi):
            latest[kv.key] = kv
        for level in self.levels:
            for run in level.runs:
                if run.overlaps(lo, hi):
                    for kv in run.scan(lo, hi):
                        existing = latest.get(kv.key)
                        if existing is None or kv.seq > existing.seq:
                            latest[kv.key] = kv
        result = {k: kv.value for k, kv in latest.items() if not kv.tombstone}
        return dict(sorted(result.items()))

    def find_run(self, run_id):
        for level in self.levels:
            for run in level.runs:
                if run.id == run_id:
                    return run
        return None

    def _maybe_flush(self):
        if not self.memtable.is_full():
            return
        entries = self.memtable.sorted_items()
        sstable = SSTable(entries, level=0)
        self.levels[0].add_run(sstable)
        self.memtable.clear()
        self.events.append(FlushEvent(sstable.id, len(entries)))
        self._maybe_compact(0)

    def _maybe_compact(self, level_number):
        level = self.levels[level_number]
        if not level.is_over_capacity():
            return
        if level_number + 1 >= len(self.levels):
            return
        next_level = self.levels[level_number + 1]
        is_last_level = (level_number + 1 == len(self.levels) - 1)
        source_runs = level.runs + next_level.runs
        merged = self._merge_runs(source_runs, is_last_level)
        source_ids = [run.id for run in source_runs]
        level.clear()
        next_level.clear()
        new_sstable = SSTable(merged, level=level_number + 1)
        next_level.add_run(new_sstable)
        self.events.append(
            CompactionEvent(
                source_ids=source_ids,
                new_sstable_id=new_sstable.id,
                from_level=level_number,
                to_level=level_number + 1,
                entry_count=len(merged),
            )
        )
        for listener in self.compaction_listeners:
            listener(source_ids, new_sstable, level_number, level_number + 1)
        self._maybe_compact(level_number + 1)

    def _merge_runs(self, runs, is_last_level):
        latest = {}
        for run in runs:
            for kv in run.entries:
                existing = latest.get(kv.key)
                if existing is None or kv.seq > existing.seq:
                    latest[kv.key] = kv
        if is_last_level:
            return [kv for kv in latest.values() if not kv.tombstone]
        return list(latest.values())

    def state(self):
        return {
            "config": self.config.__dict__,
            "memtable": [kv.__dict__ for kv in self.memtable.sorted_items()],
            "levels": [
                {
                    "number": level.number,
                    "capacity": level.capacity,
                    "tiered": level.tiered,
                    "total_size": level.total_size(),
                    "runs": [
                        {
                            "id": run.id,
                            "lower_bound": run.lower_bound,
                            "upper_bound": run.upper_bound,
                            "size": run.size(),
                            "entries": [kv.__dict__ for kv in run.entries],
                        }
                        for run in level.runs
                    ],
                }
                for level in self.levels
            ],
            "events": [event.to_dict() for event in self.events[-50:]],
        }
