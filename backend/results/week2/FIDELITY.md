# Week-2 fidelity check: does our Group Cache reproduce its paper's trends?

Simulator: 50K keys, 8B keys / 256B values, size ratio 10, whole-level leveling,
cache = 5% of data unless stated, Zipf 0.8, scans 10-100 keys, 3 seeds, metric =
query block reads per query (lower is better). Ratios > 1 mean Group Cache is better.

## Reproduced (direction)
* 0% scans: Range Cache ~= Group Cache (0.99x), as the paper says (both act as KV caches).
* Group Cache beats Range Cache at every scan share (1.09-1.11x; 1.13-1.20x with 48-key blocks).
* Group Cache beats block cache when reads dominate (1.06x at 20% scans, 16-key blocks;
  1.11x with 48-key blocks); larger blocks widen the gap, as expected.
* Advantage over block cache shrinks as the scan share grows (paper: same direction).

## NOT reproduced
* Magnitude: paper reports up to 2-3x throughput vs block/range caches; we see at most
  1.1-1.3x fewer block reads. Plausible causes: CPU/iterator savings not modelled (we
  count I/O only), much smaller dataset and fewer levels, different level structure.
* Memory claim: paper says block cache needs ~4x memory to match Group Cache; here
  block cache at 10% (1.636) already beats Group Cache at 5% (1.715) -> ~1.5-2x, not 4x.
* WRITES (paper Fig. 11: Group Cache stays best, block cache suffers most):
  here Group Cache falls BEHIND block cache from ~50% writes:
  block/group = 1.06x (w=0), 1.01x (0.2), 0.99x (0.5), 0.97x (0.8)   [16-key blocks]
               1.11x (w=0), 1.03x (0.2), 0.99x (0.5), 0.95x (0.8)    [48-key blocks]

## Our mechanism (naive group+both) in the same write sweep
                block    group    group+both
 48-key, w=0.5  1.340    1.350    1.318
 48-key, w=0.8  1.356    1.422    1.340
 16-key, w=0.8  1.831    1.888    1.821
Naive ZIO restores Group Cache to (slightly better than) block-cache level under heavy
writes. Differences at w=0.5/0.8 are within overlapping CIs vs block; vs group they are
consistent across seeds (see week-1 paired analysis).

## Most likely cause of the write discrepancy (threat to validity)
Our engine merges WHOLE levels at each compaction, so every compaction rewrites all of L1
or L2 and invalidates every cached group in them. RocksDB/Dostoevsky compact one SST file
at a time, touching a small key range. This exaggerates invalidation and would also
EXAGGERATE our mechanism's benefit. Fix before any further claims: per-file (partial)
compaction in the engine, then rerun this check.
