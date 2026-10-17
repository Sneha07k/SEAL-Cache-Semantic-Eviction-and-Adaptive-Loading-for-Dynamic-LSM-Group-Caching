# Week-2 step 2: per-file compaction + fidelity re-check

Setup: 50K keys, 8B keys / 256B values, 48-key blocks unless noted, size ratio 10,
cache = 5% of data, Zipf 0.8, scans 10-100 keys, 3 seeds, metric = query block reads per
query (lower is better). Engine now compacts ONE file at a time (LevelDB/RocksDB style),
with trivial moves; whole-level merging is kept as `granularity="level"`.

## 1. Hypothesis "whole-level merging causes Group Cache's write problem": REJECTED
Per-file compaction gives almost the same write trend (block/group at 80% writes:
0.95x whole-level vs 0.96x per-file). Per-file compaction rewrites similar TOTAL data over
time; it only rewrites smaller slices at once.

## 2. Hypothesis "LRU-S admission re-warms too slowly under writes": REJECTED
Plain-LRU admission is worse at every write ratio (e.g. 1.558 vs 1.441 read-only,
1.490 vs 1.478 at 80% writes). LRU-S helps.

## 3. Write MIX matters (fidelity fix)
Paper Sec. 7.2: 50% of writes insert NEW keys, 50% are Zipf updates. Our earlier runs used
100% Zipf updates, which packs new L0 files with hot keys and favours the block cache.
With the paper's mix (results/week2b/write_b48_inserts.csv):

| writes | none  | block | range | group | group+both | block/group | range/group |
|--------|-------|-------|-------|-------|------------|-------------|-------------|
| 0.0    | 1.749 | 1.584 | 1.595 | 1.441 | 1.441      | 1.10x       | 1.11x       |
| 0.2    | 1.615 | 1.459 | 1.530 | 1.393 | 1.386      | 1.05x       | 1.10x       |
| 0.5    | 1.616 | 1.467 | 1.537 | 1.435 | 1.413      | 1.02x       | 1.07x       |
| 0.8    | 1.639 | 1.504 | 1.576 | 1.528 | 1.471      | 0.98x       | 1.03x       |

Now reproduced: Group Cache beats block cache up to 50% writes (CI excludes 0), and Range
Cache approaches Group Cache as writes grow (1.11x -> 1.03x), both as the paper reports.
Still NOT reproduced: at 80% writes Group Cache is 1.6% worse than block cache
(-0.024 ± 0.009 reads/query); magnitudes stay far below the paper's 2-3x (I/O-only metric,
small dataset). Memory claim: block cache needs ~2x (not 4x) memory to match Group Cache.

## 4. Our mechanism (naive group+both), paper's write mix, paired by seed
| writes | vs Group Cache          | vs block cache          |
|--------|-------------------------|-------------------------|
| 0.2    | +0.5%  (0.0068 ± 0.0033) | +5.0% (0.0728 ± 0.0279) |
| 0.5    | +1.5%  (0.0221 ± 0.0045) | +3.7% (0.0545 ± 0.0172) |
| 0.8    | +3.7%  (0.0564 ± 0.0139) | +2.2% (0.0323 ± 0.0105) |
All 95% CIs exclude zero. Flush seeding gives most of the gain; compaction completion alone
is small (+0.8% at 80% writes in the update-only mix).

Story supported so far: without zero-I/O maintenance, Group Cache loses its lead over the
block cache under heavy writes; with it, Group Cache stays best at every write ratio tested.
Effect sizes are small (0.5-3.7%) and come from a simulator at small scale.

## Next
1. Size-aware decision rule (decide per group whether to seed/complete) - can it raise the
   gain without hurting low-write workloads?
2. Final evaluation at larger scale with 10 seeds, the paper's write mix as default.
