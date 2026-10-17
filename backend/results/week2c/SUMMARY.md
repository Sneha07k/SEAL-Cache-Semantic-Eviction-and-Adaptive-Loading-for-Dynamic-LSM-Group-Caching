# Week-2 step 3: decision rule for seeded / completed groups

Setup: paper's write mix (50% inserts, 50% Zipf-0.8 updates), 48-key blocks, per-file
leveling, cache 5% of data, 20% of reads are scans of 10-100 keys, 50K keys.
Selection criterion fixed BEFORE looking at results: best mean gain vs Group Cache over
20/50/80% writes, never worse than Group Cache. Tuned on seeds 0-2, validated on 3-5.

## Rules compared (all = flush seeding + compaction completion)
naive  : always install;  lrus : LRU-S-consistent (seed w.p. 1/n, grown group w.p. n_old/n_new)
hot    : lrus, only if source group in newest 25% of cache
placement: inherit source recency  vs  tail (evicted first unless hit)

## Tuning (seeds 0-2): gain in query block reads vs Group Cache
| rule              | w=0.2 | w=0.5 | w=0.8 | mean  |
|-------------------|-------|-------|-------|-------|
| naive (inherit)   | +0.5% | +1.5% | +3.7% | +1.91% |
| lrus  (inherit)   | +0.4% | +1.1% | +3.1% | +1.52% |
| hot   (inherit)   | +0.1% | +0.6% | +1.6% | +0.73% |
| any rule, tail    | +0.0-0.1% | +0.1-0.2% | +0.4-0.7% | +0.20-0.35% |
At w=0 all variants equal Group Cache (no writes, nothing to maintain).
=> Filtering and low-priority placement only REDUCE the benefit. Groups our mechanism builds
are as useful as query-admitted ones: they are only built for ranges already cached, so they
are pre-filtered for hotness. Selected: naive (inherit).

## Validation on held-out seeds 3-5 (paired, 95% CI; * = CI excludes 0)
| writes | naive vs Group Cache | naive vs block | naive vs Range Cache | Group vs block |
|--------|----------------------|----------------|----------------------|----------------|
| 0.2    | +0.6% *              | +4.5% *        | +8.9% *              | +4.0% *        |
| 0.5    | +1.4% *              | +3.9% *        | +8.2% *              | +2.5% *        |
| 0.8    | +3.9% *              | +2.3% *        | +6.8% *              | -1.7% (worse)  |
Replicates tuning closely. Group Cache alone loses to the block cache at 80% writes;
with zero-I/O maintenance it is best at every write ratio tested.

## Implication for the paper
The contribution is zero-I/O KV-group maintenance itself (flush seeding + compaction
completion), with the negative result that size-/hotness-based filtering of maintained
groups is unnecessary and harmful in these settings. Do not claim a decision rule.
