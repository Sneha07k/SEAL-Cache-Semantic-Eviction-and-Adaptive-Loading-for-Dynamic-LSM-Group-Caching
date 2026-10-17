"""Deterministic synthetic workloads.

Keys are drawn uniformly or from a Zipf distribution (hot keys get most accesses).
Week 3 adds presets modelled on LinkBench / Assoc_2ry mixes.
"""
import bisect
import itertools
import random


class ZipfSampler:
    """Draws integers in [0, n) with P(i) proportional to 1/(i+1)^theta."""

    def __init__(self, n, theta, rng, perm_seed=None):
        self.rng = rng
        weights = [1.0 / (i + 1) ** theta for i in range(n)]
        self.cdf = list(itertools.accumulate(weights))
        self.total = self.cdf[-1]
        # Scatter hot ranks over the key space so hot keys are not all adjacent.
        # perm_seed fixes WHICH keys are hot independently of the op stream, so a warm-up
        # trace and a measured trace can share one hot set. None = draw from the op rng
        # (legacy behaviour: every trace seed gets its own hot set).
        self.perm = list(range(n))
        (rng if perm_seed is None else random.Random(perm_seed)).shuffle(self.perm)

    def __call__(self):
        rank = bisect.bisect_left(self.cdf, self.rng.random() * self.total)
        return self.perm[min(rank, len(self.perm) - 1)]


def generate(n, key_space, seed, write_ratio=0.3, delete_ratio=0.05, scan_ratio=0.2,
             scan_len=(10, 100), zipf_theta=0.0, perm_seed=None):
    """Return a list of ops: ("put", k, v) | ("delete", k) | ("get", k) | ("scan", lo, hi).

    write_ratio covers puts; deletes and scans are separate shares; the rest are gets.
    zipf_theta = 0 gives uniform keys; 0.8-0.99 gives realistic skew.
    """
    if write_ratio + delete_ratio + scan_ratio > 1:
        raise ValueError("ratios sum to more than 1")
    rng = random.Random(seed)
    pick = ZipfSampler(key_space, zipf_theta, rng, perm_seed) if zipf_theta > 0 else (
        lambda: rng.randrange(key_space))
    ops = []
    for i in range(n):
        r, k = rng.random(), pick()
        if r < write_ratio:
            ops.append(("put", k, f"v{seed}-{i}"))
        elif r < write_ratio + delete_ratio:
            ops.append(("delete", k))
        elif r < write_ratio + delete_ratio + scan_ratio:
            ops.append(("scan", k, k + rng.randint(*scan_len) - 1))
        else:
            ops.append(("get", k))
    return ops
