import itertools

_id_counter = itertools.count(1)


class SSTable:
    def __init__(self, entries, level):
        self.id = next(_id_counter)
        self.level = level
        self.entries = sorted(entries, key=lambda kv: kv.key)
        self.lower_bound = self.entries[0].key if self.entries else None
        self.upper_bound = self.entries[-1].key if self.entries else None

    def overlaps(self, lo, hi):
        if not self.entries:
            return False
        return not (hi < self.lower_bound or lo > self.upper_bound)

    def get(self, key):
        lo, hi = 0, len(self.entries) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.entries[mid].key == key:
                return self.entries[mid]
            if self.entries[mid].key < key:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def scan(self, lo, hi):
        return [kv for kv in self.entries if lo <= kv.key <= hi]

    def size(self):
        return len(self.entries)
