from collections import Counter


POINT_READ = "point_read"
SCAN_READ = "scan_read"
FLUSH_WRITE = "flush_write"
COMPACTION_READ = "compaction_read"
COMPACTION_WRITE = "compaction_write"


class IOCounter:
    def __init__(self):
        self.blocks = Counter()
        self.query_by_level = Counter()     

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
    
    def on_flush(self, new_run, entries):
        pass

    def on_compaction(self, inputs, outputs, merged):
        pass
