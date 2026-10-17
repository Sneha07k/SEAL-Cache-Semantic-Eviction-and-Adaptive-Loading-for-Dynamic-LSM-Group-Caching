"""Disk I/O accounting and observer hooks.

Every block read or written is counted, by cause. This is the paper's main cost metric.
Observers (caches) are told about flushes and compactions together with the data that
was in memory at that moment -- the raw material for zero-I/O cache maintenance.
"""
from collections import Counter

# Causes of block I/O
POINT_READ = "point_read"
SCAN_READ = "scan_read"
FLUSH_WRITE = "flush_write"
COMPACTION_READ = "compaction_read"
COMPACTION_WRITE = "compaction_write"


class IOCounter:
    def __init__(self):
        self.blocks = Counter()
        self.query_by_level = Counter()      # query block reads by the level of the run read

    def add(self, cause, n=1, level=None):
        assert n >= 0
        self.blocks[cause] += n
        if level is not None and cause in (POINT_READ, SCAN_READ):
            self.query_by_level[level] += n

    @property
    def query_reads(self):
        return self.blocks[POINT_READ] + self.blocks[SCAN_READ]

    def snapshot(self):
        return dict(self.blocks)

    def level_snapshot(self):
        return dict(self.query_by_level)


class LSMObserver:
    """Override what you need. Default methods do nothing.

    on_flush(new_run, entries)        entries = sorted (key, value) list flushed from the
                                      MemTable; already in memory, so using it costs no I/O.
    on_compaction(inputs, outputs, merged)
                                      inputs = runs/files being deleted; outputs = list of new
                                      runs/files (empty if everything was dropped); merged =
                                      sorted (key, value) stream the compaction produced
                                      (in memory, no I/O). Trivial moves (a file moved down a
                                      level unchanged) do NOT call this: the file and its
                                      run_id survive, so cached state stays valid.
    """

    def on_flush(self, new_run, entries):
        pass

    def on_compaction(self, inputs, outputs, merged):
        pass
