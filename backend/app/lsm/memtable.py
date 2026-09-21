from .types import KeyValue 
 
 
class MemTable: 
    def __init__(self, capacity): 
        self.capacity = capacity 
        self.entries = {} 
 
    def put(self, key, value, seq): 
        self.entries[key] = KeyValue(key, value, seq, False) 
 
    def delete(self, key, seq): 
        self.entries[key] = KeyValue(key, None, seq, True) 
 
    def get(self, key): 
        return self.entries.get(key) 
 
    def scan(self, lo, hi): 
        return [kv for k, kv in self.entries.items() if lo <= k <= hi] 
 
    def is_full(self): 
        return len(self.entries) >= self.capacity 
 
    def sorted_items(self): 
        return sorted(self.entries.values(), key=lambda kv: kv.key) 
 
    def clear(self): 
        self.entries = {} 
commit message
