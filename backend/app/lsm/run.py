from bisect import bisect_left, bisect_right
from itertools import count

TOMBSTONE = None
_block_ids = count()
_run_ids = count()


class Block:
    __slots__ = ("block_id", "keys", "values")

    def __init__(self, keys, values):
        assert keys and len(keys) == len(values)
        self.block_id = next(_block_ids)
        self.keys = keys
        self.values = values

    @property
    def min_key(self):
        return self.keys[0]

    @property
    def max_key(self):
        return self.keys[-1]

    def entries_in(self, lo, hi):
        i, j = bisect_left(self.keys, lo), bisect_right(self.keys, hi)
        return list(zip(self.keys[i:j], self.values[i:j]))

    def get(self, key):
        i = bisect_left(self.keys, key)
        if i < len(self.keys) and self.keys[i] == key:
            return True, self.values[i]
        return False, None


class Run:
    __slots__ = ("run_id", "seq", "blocks", "_max_keys", "_min_keys", "size", "level")

    def __init__(self, entries, block_size, seq):
        assert entries, "empty runs are not created"
        self.run_id = next(_run_ids)
        self.seq = seq
        self.blocks = []
        for i in range(0, len(entries), block_size):
            chunk = entries[i:i + block_size]
            self.blocks.append(Block([k for k, _ in chunk], [v for _, v in chunk]))
        self._max_keys = [b.max_key for b in self.blocks]
        self._min_keys = [b.min_key for b in self.blocks]
        self.size = len(entries)
        self.level = None            

    @property
    def min_key(self):
        return self.blocks[0].min_key

    @property
    def max_key(self):
        return self.blocks[-1].max_key

    def find_block(self, key):
        i = bisect_left(self._max_keys, key)
        if i < len(self.blocks) and self.blocks[i].min_key <= key:
            return self.blocks[i]
        return None

    def blocks_with_keys_in(self, lo, hi):
        out = []
        i = bisect_left(self._max_keys, lo)
        while i < len(self.blocks) and self.blocks[i].min_key <= hi:
            if self.blocks[i].entries_in(lo, hi):
                out.append(self.blocks[i])
            i += 1
        return out

    def owner_index(self, key):
        return max(bisect_right(self._min_keys, key) - 1, 0)

    def owned_interval(self, i):
        lo = None if i == 0 else self._min_keys[i]
        hi = None if i == len(self.blocks) - 1 else self._min_keys[i + 1] - 1
        return lo, hi

    def has_keys_in(self, lo, hi):
        i = bisect_left(self._max_keys, lo)
        while i < len(self.blocks) and self.blocks[i].min_key <= hi:
            if self.blocks[i].entries_in(lo, hi):
                return True
            i += 1
        return False

    def entries(self):
        for b in self.blocks:
            yield from zip(b.keys, b.values)

    def __repr__(self):
        return f"Run(id={self.run_id}, seq={self.seq}, size={self.size}, blocks={len(self.blocks)})"
