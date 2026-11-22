from bisect import bisect_left, bisect_right, insort
from collections import OrderedDict
from itertools import count

KV_META_BYTES = 77


class _Range:
    __slots__ = ("rid", "lo", "hi", "keys", "values")

    def __init__(self, rid, lo, hi, entries):
        self.rid, self.lo, self.hi = rid, lo, hi
        self.keys = [k for k, _ in entries]
        self.values = [v for _, v in entries]


class RangeCache:
    name = "range_cache"

    def __init__(self, capacity_bytes, key_bytes=8, value_bytes=256, seed=0):
        self.capacity = capacity_bytes
        self.kv_bytes = KV_META_BYTES + key_bytes + value_bytes
        self.ranges = {}               
        self.starts = []               
        self.lru = OrderedDict()       
        self.bytes = 0
        self._rids = count()
        self.stats = {"queries": 0, "hits": 0, "admitted": 0, "evicted": 0,
                      "write_through": 0}

    
    def _range_bytes(self, r):
        return max(len(r.keys), 1) * self.kv_bytes       

    def _containing(self, key):
        i = bisect_right(self.starts, (key, float("inf"))) - 1
        if i >= 0:
            r = self.ranges[self.starts[i][1]]
            if r.lo <= key <= r.hi:
                return r
        return None

    def _overlapping(self, lo, hi):
        i = max(bisect_right(self.starts, (lo, float("inf"))) - 1, 0)
        out = []
        while i < len(self.starts) and self.starts[i][0] <= hi:
            r = self.ranges[self.starts[i][1]]
            if r.hi >= lo:
                out.append(r)
            i += 1
        return out

    def _remove(self, r):
        del self.ranges[r.rid]
        self.starts.pop(bisect_left(self.starts, (r.lo, r.rid)))
        self.lru.pop(r.rid, None)
        self.bytes -= self._range_bytes(r)

   
    def lookup(self, lo, hi):
        self.stats["queries"] += 1
        r = self._containing(lo)
        if r is None or r.hi < hi:
            return None
        self.stats["hits"] += 1
        self.lru.move_to_end(r.rid)
        i, j = bisect_left(r.keys, lo), bisect_right(r.keys, hi)
        return list(zip(r.keys[i:j], r.values[i:j]))

    def admit(self, lo, hi, result):
        merged = dict(result)
        for r in self._overlapping(lo - 1, hi + 1):       
            lo, hi = min(lo, r.lo), max(hi, r.hi)
            for k, v in zip(r.keys, r.values):
                merged.setdefault(k, v)                   
            self._remove(r)
        r = _Range(next(self._rids), lo, hi, sorted(merged.items()))
        self.ranges[r.rid] = r
        insort(self.starts, (r.lo, r.rid))
        self.lru[r.rid] = None
        self.bytes += self._range_bytes(r)
        self.stats["admitted"] += 1
        while self.bytes > self.capacity and self.lru:
            rid = next(iter(self.lru))
            self._remove(self.ranges[rid])
            self.stats["evicted"] += 1

  
    def on_write(self, key, value):
        r = self._containing(key)
        if r is None:
            return
        self.stats["write_through"] += 1
        before = self._range_bytes(r)
        i = bisect_left(r.keys, key)
        present = i < len(r.keys) and r.keys[i] == key
        if value is None:
            if present:
                del r.keys[i], r.values[i]
        elif present:
            r.values[i] = value
        else:
            r.keys.insert(i, key)
            r.values.insert(i, value)
        self.bytes += self._range_bytes(r) - before
        while self.bytes > self.capacity and self.lru:
            rid = next(iter(self.lru))
            self._remove(self.ranges[rid])
            self.stats["evicted"] += 1

    def check_invariants(self, truth=None):
        assert self.starts == sorted(self.starts)
        prev_hi = None
        total = 0
        for lo, rid in self.starts:
            r = self.ranges[rid]
            assert r.lo == lo and r.keys == sorted(set(r.keys))
            assert all(r.lo <= k <= r.hi for k in r.keys)
            if prev_hi is not None:
                assert lo > prev_hi, "overlapping cached ranges"
            prev_hi = r.hi
            total += self._range_bytes(r)
            if truth is not None:
                assert list(zip(r.keys, r.values)) == truth(r.lo, r.hi), "stale range"
        assert total == self.bytes and self.bytes <= self.capacity
        assert set(self.lru) == set(self.ranges)
