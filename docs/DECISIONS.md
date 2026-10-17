# Decisions and rationale (handoff from the claude.ai planning conversation)

This file records WHY the project is shaped the way it is. Numbers come from
`backend/results/*/SUMMARY.md`; re-check them there before quoting.

## 1. From SEAL-Cache to this project

Phase 1 ("SEAL-Cache") had a Python LSM simulator, KVGroups, delta tracking/suppression,
compaction "reconciliation" with keep/rebuild/replace thresholds (0.30/0.70), a 1/size
admission rule, "semantic"/"app-aware" policies, and a hit-rate comparison vs LRU/LFU.

A literature review (14 uploaded papers + targeted searches) found that almost every SEAL
idea was already published:
* range/result caching: Range Cache (ICDE'24), OmniCache (HPCC'24), SRockDB (SMC'23);
* KV groups + size-aware caching: Group Cache (PACMMOD/SIGMOD'26) -- nearly identical
  terminology and intuition to SEAL's KVGroups; its LRU-S admits with prob 1/size, which is
  exactly SEAL's 1/size rule;
* write-through fine-grained caches: Dual-grained caches (HPCC'19), HaLSM (ICCD'22);
* compaction-aware cache retention: LSbM (ICDCS'17), HaLSM's Prefetcher, BlockDB (ICDE'22),
  SAS-Cache (MSST'24), Leaper (VLDB'20).
Also a conceptual flaw: a cache holding VALUES cannot be made stale by compaction
(compaction moves data, it does not change it), so SEAL's compaction reconciliation solved a
non-problem; only physically addressed caches (blocks) or per-run caches are invalidated.

Retired: delta suppression, reconciliation thresholds, semantic/app-aware policies,
"coherence score", LRU/LFU key caches as main baselines. Kept: the "don't throw the cache
away at compaction" instinct, the simulator idea, multi-seed runner, deterministic RNG.

## 2. The gap we target (documented by the strongest prior work itself)

Group Cache (Wang, Zhang, Qiu, Yuan, Zhang; doi 10.1145/3786661; ACM DL lists publication
7 April 2026). Key facts we rely on:
* KV group = keys a query needs from ONE block; caching it saves exactly one I/O (Sec. 3).
* Per-sorted-run skip lists; hit only if groups fully cover the query range in that run.
* LRU-S policy; AdaptSize and Cliffhanger did NOT beat LRU-S (p.47:14).
* Compaction (Sec. 4.2): Case 1 keep (rebuilt), Case 2 DISCARD.
* Authors: completing Case-2 groups "might be beneficial" (p.47:9); fetching the uncovered
  part if <50% is suggested but unevaluated (p.47:10).
* Under writes, Range Cache approaches Group Cache because Range Cache inserts new writes
  into cached ranges while Group Cache does not cache new data until queried, and because
  compactions invalidate groups (p.47:16, Fig. 11).
* Setup: Dostoevsky/RocksDB, 200M KVs, 8B keys, 256B values, SNARF range filters 14 bpk,
  cache 5% of data, lazy leveling default, 20% scans of 10-100 keys, Zipf 0.8; write
  experiments use 50% inserts + 50% Zipf updates (Sec. 7.2). Claims up to 3x throughput vs
  block/range caches; block cache needs ~4x space to match.
* Memory formulas (p.47:8): Range Cache 77 B metadata per KV; Group Cache (77 + 2|key|)/G + 1
  per KV; block cache 92 B per block.
* No code link found in the paper.

Our mechanism: ZERO-I/O KV-GROUP MAINTENANCE
* Flush seeding: when the MemTable is flushed, build KV groups in the new L0 run for every
  range currently cached anywhere, from the flushed entries (already in memory).
* Compaction completion: instead of discarding Case-2 groups, rebuild them complete from
  the compaction's merged stream (already in memory).
Neither needs any extra disk read.

## 3. Novelty position (be precise -- reviewers will check)
* NOT new in general: doing cache work during compaction exists -- HotRAP (ATC'25) piggybacks
  hot records on compactions; SAS-Cache prefetches newly generated blocks after compaction;
  Sarkar et al. VLDB'21 observe compactions warm the block cache; LSbM evaluates
  "incremental warming up" and shows it can backfire (LSbM Fig. 8c); HaLSM's Prefetcher.
  All of these work at BLOCK or record level.
* Range Cache's write-through is close in spirit to flush seeding, but for whole query
  results, at write time, not per-run groups at flush time.
* New (as far as searches up to Oct 2026 found): flush-time seeding and compaction-time
  completion of per-run KV groups, i.e. closing the two weaknesses Group Cache documents.
  The authors SUGGESTED completion but never built/evaluated it; their suggestion involves
  fetching (I/O); ours uses data already in memory.
* Safe claim: "first design and evaluation of zero-I/O KV-group maintenance during flush and
  compaction". Never claim "nobody thought of completing groups".
* Re-check Google Scholar "Cited by" for Group Cache before submission.
* AdCache (Ye, Liu, Luo; EDBT'26; code github.com/qingshanlanshan/AdCache-LSM): RL-based
  split of memory between block cache and Range Cache + partial scan admission; does not use
  KV groups, does nothing at flush/compaction. Related, not overlapping. Independently finds
  block cache best in read-heavy and Range Cache better in write-heavy phases. AdCache had to
  reimplement Range Cache too (not open source) -- precedent for our reimplementation.

## 4. Engine and experiment decisions (and why)
* Simulator, not RocksDB: one-month timeline, 4 students. Consequence: claims are about
  disk-block reads only; no latency/throughput claims. RocksDB port = future work.
* Ideal filters (zero false positives) for both point and range lookups: Group Cache itself
  assumes range filters skip irrelevant runs (p.47:5 fn.1). State it.
* Integer keys (block ownership uses min_{i+1} - 1).
* Per-file leveled compaction (LevelDB-style, round-robin file pick, trivial moves) is the
  default; whole-level merging kept as `granularity="level"`.
* Main metric: query block reads per query. Hit rates only as secondary.
* Equal byte budgets incl. metadata for all caches (paper's formulas).
* Range Cache model: full-coverage hits only, write-through, LRU over ranges, 77 B/KV.
* Block cache: blocks of deleted runs dropped immediately (favourable to the baseline;
  real RocksDB keeps them as garbage until LRU eviction).
* Group Cache deviations: no group splitting (Sec. 6.1), no per-KV promotion counters,
  single-threaded, tombstones cached like values.

## 5. Hypotheses tested and what happened
1. Week-1 go/no-go (update-only writes, whole-level merges): naive mechanism saved 3-5% reads
   vs Group Cache at 80% writes, recovered ~39% of the benefit Group Cache loses under
   writes. -> conditional GO (small effect).
2. Fidelity check: Group Cache beats Range Cache everywhere and block cache in read-heavy
   settings (directions match); magnitudes far smaller than paper (I/O-only metric, small
   data, fewer levels); under writes Group Cache fell BEHIND block cache (paper: opposite).
3. "Whole-level merging exaggerates invalidation" -> REJECTED: per-file compaction gave the
   same write trend. (Per-file rewrites similar total data; only smaller slices at once.)
4. "LRU-S re-warms too slowly under writes" -> REJECTED: plain-LRU admission is worse
   everywhere.
5. "Our write mix differs from the paper's" -> mostly CONFIRMED: with 50% inserts the paper's
   trends reproduce up to 50% writes. At 80% writes Group Cache is still ~1.6% worse than
   block cache (not reproduced; report as limitation/finding).
   => ALWAYS use insert_share=0.5 for write experiments.
6. Decision rule (pre-registered criterion, tuned seeds 0-2, validated seeds 3-5):
   naive (always install, inherit recency) > LRU-S-consistent > hot-only > tail placement.
   Filtering only hurts: maintained groups are built only for already-cached ranges, so
   they are pre-filtered for hotness. => The paper claims NO decision rule.
   Held-out result (48-key blocks, paper write mix): zio-naive vs Group Cache
   +0.6/+1.4/+3.9%, vs block +4.5/+3.9/+2.3%, vs Range Cache +8.9/+8.2/+6.8% at 20/50/80%
   writes; all paired 95% CIs exclude 0. Flush seeding gives most of the gain; compaction
   completion alone is small.

## 6. What the paper may and may not claim
May (once week-3 results confirm on fresh seeds):
* Group Cache's advantage over a block cache shrinks under writes and is lost at high write
  ratios (in our simulator); zero-I/O maintenance keeps Group Cache best at every write
  ratio tested.
* Maintenance costs zero extra disk reads (by construction) -- but MEASURE its CPU work and
  memory occupancy (week 3).
* Filtering maintained groups by size/hotness is unnecessary/harmful in tested settings.
Must not:
* Any latency/throughput claim; any "Nx faster" claim.
* "Novel idea of using compaction for caching" (prior work exists).
* Generalise beyond tested workloads/scales; hide that Group Cache's paper magnitudes did not
  reproduce; hide the 80%-writes discrepancy.
* Use seeds 0-5 for headline numbers (they were used for tuning/validation).

## 7. Threats to validity (for the paper)
Simulator, I/O-only metric; small scale (50K keys, ~3 levels); ideal filters; integer keys;
synthetic Zipf workloads (LinkBench/Assoc_2ry-like mixes only approximated); reimplemented
baselines (Group Cache code not public, Range Cache code not public); single-threaded;
partial fidelity to Group Cache's reported magnitudes.

## 8. Paper plan (week 4)
Working title: "Zero-I/O Maintenance of KV-Group Caches in LSM-Trees".
Sections: Intro (Group Cache loses under writes) -> Background (LSM, block/range/group
caches) -> Motivation measurement (benefit lost under writes, Case-2 discards, cold L0) ->
Design (flush seeding, compaction completion, correctness argument: groups rebuilt from
immutable runs' own data) -> Methodology (simulator, fidelity check, budgets, seeds) ->
Results (write sweep headline; scan share, cache size, skew, policy, block size; overheads;
ablation seed vs complete; decision-rule negative result) -> Related work -> Limitations ->
Conclusion. Target: mid-tier conference or workshop; search venues ~5-6 weeks out.

## 9. Team (Phase 2 roles proposed)
Tanishka: engine/compaction + overhead accounting. Sneha: Group Cache/mechanism + paper lead.
Simran: baselines + correctness tests. Shruti: workloads, runner, statistics, plots.

## 10. Verification status of the UI stack
Verified 2026-10-17: `npm install` and `vite build` succeed; the FastAPI app is covered by
`tests/test_api.py` (TestClient) and a live uvicorn run; the Benchmark, Paper results and Twin Lab
tabs were driven end to end in headless Chrome (no console errors; scenario step results matched
direct engine runs). Not covered by committed tests: the browser drive itself (a throwaway
puppeteer script outside the repo), keyboard/screen-reader behaviour beyond basic ARIA, and
non-Chromium browsers. UI design rules: results are only ever read from the experiment CSVs or
produced by run_trace (demo scale, labelled as such); the retired SEAL-Cache ideas (coherence
score, delta suppression, reconciliation) are deliberately absent from the UI.

## 11. Week 3 (in progress): protocol and interim findings
Source of truth: `backend/results/week3/` (tables are generated by
`analysis/summarize_week3.py`; do not hand-copy numbers).

**PROTOCOL FLAW FOUND AND FIXED (2026-10-17).** `run_trace` generated the warm-up trace
(seed+1000) and the measured trace (seed) with different hot-key permutations (top-100 hot keys
shared: 0/100; only ~11-12% of measured ops touched any key seen in warm-up), so caches were
never warm on the measured hot set; all weeks 1-3 numbers up to this point share the flaw
(weeks 1-2 not re-checked). Fix: `generate(..., perm_seed=seed)` pins one hot set for both
traces (now 82-86/100 shared; the op streams still differ); legacy behaviour is the default
(`perm_seed=None`) and `tests/test_service.py` guards it. Everything below in this section
that was measured BEFORE the fix is archived in `results/week3/mismatched_warmup/` and is
sensitivity data only ("warm-up on a different hot set"), NOT headline. Its numbers are kept
here for the record and must be re-measured with the corrected protocol (calibration on seeds
100-102 first, then all sweeps on seeds 6-15). Do not quote them in the paper.

Corrected-protocol calibration (seeds 100-102, 200K keys, w=0.5, 40K measured ops; files
`results/week3/calibrate_warmup*.csv`): rule "<1% change when doubling warm-up, both group and
zio-naive" fixed beforehand. With inserts: NOT met (group +1.9/+2.7/+3.1%, zio-naive
+2.1/+2.8/+3.4% per doubling 20K->160K; block cache drifts the same). Update-only diagnostic:
met at 40K (+0.3/+0.4% for 40K->80K). Chosen protocol (per the fallback fixed in advance):
40K warm-up + 40K measured, plus a 160K-warm-up robustness row at w=0.5. zio-vs-group gain,
3 seeds only: 3.6/3.5/3.4/3.1% at 20/40/80/160K (paper mix); 5.2/4.9/4.8% (update-only).
CORRECTION to the explanation above: the drift is not only insert growth. Update-only also
drifts +1.9% from 20K to 40K and then flattens, which suggests tree fill (levels reaching their
state) early on, with insert growth adding to it later. Still an inference; tree state was not
measured. Mismatching the hot set changed the numbers only modestly (e.g. group at 20K warm-up
1.367 -> 1.345; zio gain 3.9 -> 3.6%).

(The text below describes the MISMATCHED-warm-up run.)

Protocol (chosen on calibration seeds 100-102, so headline seeds 6-15 stay fresh):
200K keys (4 levels: reads reach L3 in every run), 40K warm-up + 40K measured ops, 48-key
blocks, cache = 5% of the INITIAL data, paper write mix (insert-share 0.5), per-file leveling.
* Warm-up calibration: the pre-registered rule (<1% change when doubling warm-up) was NOT met
  under the paper mix: reads/query rise 1.4/2.4/3.3% per doubling for every cache incl. block.
  An update-only diagnostic (no inserts) converges by 40K -> the drift is most likely database
  growth from inserts (only inferred, tree size not measured). Insert ops bound the growth:
  <= ~4/10/16% of the 200K keys at 20/50/80% writes by the end of the measured window (seeds
  6-8; upper bound, random odd keys may collide). So there is no steady state with inserts;
  absolute numbers depend on warm-up and window lengths. State this as a threat to validity.
  The zio-vs-group gain was 3.6-3.9% across warm-ups 20K-160K (3 seeds) -> not sensitive to it.
* Re-running the write sweep reproduced the first run exactly (280/280 rows, identical
  reads_per_query); only intended column changes differed.

Write sweep, seeds 6-15, paired per seed, % fewer query block reads, 95% CI (all exclude 0
unless noted):
| writes | zio-naive vs group | vs block | vs range | group vs block |
|--------|--------------------|----------|----------|----------------|
| 0.2    | +1.15 +-0.20       | +5.86    | +9.69    | +4.77          |
| 0.5    | +3.38 +-0.18       | +4.55    | +8.74    | +1.21          |
| 0.8    | +6.20 +-0.24       | +2.83    | +6.77    | -3.60 (10/10 seeds worse) |
At w=0 zio-naive == group (no writes). Larger than the 50K-key validation (+0.6/+1.4/+3.9);
that validation was not a prediction for 200K, so do not present it as confirmation.

ABLATION (changes the framing; see open decision below):
* group+seed vs group: +1.06 / +3.38 / +5.61%.  group+complete vs group: +0.10 (CI includes
  0) / +0.56 / +1.44%.
* zio-naive vs group+seed (what completion adds on top of seeding): +0.09 (CI incl. 0) /
  0.00 (CI incl. 0) / +0.62%; at w<=0.5 worse than seeding alone in 4-5 of 10 seeds.
=> Flush seeding does essentially all of the work; completion is marginal and only measurable
at 80% writes. Do NOT describe the mechanism as two equally valuable halves.
* Seeding removes ~14/34/38% of Group Cache's L0 reads (means, not paired) at 20/50/80%.

Overhead (zio-naive, end-of-run snapshot, means; descriptive): maintained groups hold
23/18/39% of cache bytes and 73/76/86% of them are never hit (hit-share 27/24/14%; biased
down for late-created groups). In-memory copying ~220 KVs per flush (seeding) and ~950 KVs per
compaction (completion) at w<=0.5; zero extra disk reads by construction. Report as-is.
L0 runs account for 7.7-11.1% of Group Cache's query reads (11.5-12.5% with no cache).

OPEN DECISION (team): frame the contribution as "flush-time seeding of KV groups" with
compaction completion as a minor, write-heavy-only addition (recommended by the data so far),
or keep the two-part framing. Decide after the scan/size/zipf/tiering/block-16 sweeps.
Also still to verify: whether the ablation pattern holds in those sweeps.
