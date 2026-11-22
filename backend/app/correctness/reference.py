import random


class ReferenceKV:
    def __init__(self):
        self.data = {}

    def put(self, key, value):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)

    def get(self, key):
        return self.data.get(key)

    def scan(self, lo, hi):
        return sorted((k, v) for k, v in self.data.items() if lo <= k <= hi)


def random_ops(n, key_space, seed, p_put=0.45, p_delete=0.1, p_get=0.25, max_scan=40):
    rng = random.Random(seed)
    ops = []
    for i in range(n):
        r = rng.random()
        k = rng.randrange(key_space)
        if r < p_put:
            ops.append(("put", k, f"v{i}"))
        elif r < p_put + p_delete:
            ops.append(("delete", k))
        elif r < p_put + p_delete + p_get:
            ops.append(("get", k))
        else:
            ops.append(("scan", k, k + rng.randrange(max_scan)))
    return ops


def run_differential(system, ops, check_every=0):
    ref = ReferenceKV()
    for i, op in enumerate(ops):
        kind = op[0]
        if kind == "put":
            system.put(op[1], op[2]); ref.put(op[1], op[2])
        elif kind == "delete":
            system.delete(op[1]); ref.delete(op[1])
        elif kind == "get":
            got, want = system.get(op[1]), ref.get(op[1])
            assert got == want, f"op {i} {op}: got {got!r}, want {want!r}"
        elif kind == "scan":
            got, want = system.scan(op[1], op[2]), ref.scan(op[1], op[2])
            assert got == want, f"op {i} {op}: scan mismatch\n got  {got}\n want {want}"
        if check_every and i % check_every == 0 and hasattr(system, "check_invariants"):
            system.check_invariants()
   
    keys = set(ref.data)
    touched = {op[1] for op in ops if op[0] in ("put", "delete")}
    for k in touched:            
        assert system.get(k) == ref.get(k), f"final get({k}) mismatch"
    for k in keys:
        assert system.get(k) == ref.get(k), f"final get({k}) mismatch"
    if keys:
        lo, hi = min(keys), max(keys)
        assert system.scan(lo, hi) == ref.scan(lo, hi), "final full scan mismatch"
    return ref
