# Project context for Claude Code

Graphic Era team project (OSDBMS-V-2026-T082): Sneha Kuriyal (lead), Tanishka Gupta,
Simran Arya, Shruti Rana. Goal: a mid-tier conference/workshop paper. Weeks 1-2 are done;
week 3 = final evaluation, week 4 = paper.

READ FIRST: docs/DECISIONS.md (why everything is the way it is) and
backend/results/week2c/SUMMARY.md (latest validated numbers).
Be critical and evidence-driven. Never invent results, numbers or citations.

## The research in one paragraph
Group Cache (Wang et al., PACMMOD/SIGMOD 2026, doi 10.1145/3786661) caches per-run "KV
groups" and beats block/range caches, but it discards groups that compaction leaves
incomplete (Case 2) and does not cache newly flushed data until queried. Our mechanism,
ZERO-I/O KV-GROUP MAINTENANCE, seeds groups in new L0 runs at flush time and completes
Case-2 groups at compaction time, using data already in memory (no extra disk reads).
Validated so far (held-out seeds 3-5, paper's write mix): vs Group Cache +0.6/+1.4/+3.9%
fewer query block reads at 20/50/80% writes; Group Cache alone loses to the block cache at
80% writes, with our mechanism it is best at every write ratio tested.
The paper claims the mechanism, NOT a decision rule (filtering was tested and only hurt).

## Hard rules
* Metric = query block reads per query (engine.io). Hit rate is secondary.
* Every cache must pass the differential tests (correctness/reference.py) before benchmarks.
* Equal BYTE budgets incl. metadata for all caches.
* Write experiments: ALWAYS --insert-share 0.5 (paper Sec. 7.2 mix).
* Headline numbers: fresh seeds only (6 and up). Seeds 0-5 were used for tuning/validation.
* Paired per-seed comparisons with 95% CIs; report losses and non-significant results.
* No latency/throughput claims from the simulator. No "Nx faster".
* Results come from backend/app/experiments, never from the UI.
* Keep the simulator core stdlib-only; deterministic seeds.

## Week 3: final evaluation (to do)
1. Scale up: try --keys 200000 (check runtime; levels should reach >= 4); keep 48-key blocks
   as default, 16 as sensitivity.
2. Ten fresh seeds (6-15). Caches: none, block, range, group, zio-naive, plus ablations
   group+seed, group+complete.
3. Sweeps (paper write mix): write ratio 0/0.2/0.5/0.8; scan share 0.2/0.5/0.8 at w=0.5;
   cache size 1/5/10/20% at w=0.5; Zipf 0.6/0.8/0.99 at w=0.5; leveling vs tiering;
   block size 16/48.
4. Overhead accounting (NEW code needed): per flush/compaction, count KVs copied into
   groups and groups created by our mechanism (CPU-work proxy); fraction of cache bytes held
   by maintained groups; how many maintained groups are ever hit before eviction.
5. Motivation figure: Group Cache benefit vs no-cache as writes grow; Case-2 discards per
   compaction; share of query reads that hit uncached new L0 runs.
6. analysis/ scripts to produce every paper figure from CSVs (pandas + matplotlib).
7. Re-run all 24 tests after any change.

## Layout
backend/app/config.py                LSMConfig (block_size, memtable_size, size_ratio, policy,
                                     granularity file|level, file_size, ideal_filters)
backend/app/lsm/run.py               Block, Run (immutable; owner_index/owned_interval helpers)
backend/app/lsm/io.py                IOCounter (block I/O by cause), LSMObserver hooks:
                                     on_flush(run, entries), on_compaction(inputs, outputs, merged)
backend/app/lsm/engine.py            LSMEngine: per-file leveling / whole-level / tiering;
                                     attach_cache (run-level), attach_query_cache (Range Cache)
backend/app/cache/group_cache.py     GroupCache: faithful baseline + our mechanism flags
                                     (complete_on_compaction, seed_on_flush, zio_rule,
                                     zio_priority, admission); deviations in docstring
backend/app/cache/block_cache.py     RocksDB-style LRU block cache baseline
backend/app/cache/range_cache.py     Range Cache baseline (write-through, full-coverage hits)
backend/app/correctness/reference.py ReferenceKV + run_differential
backend/app/workload/generator.py    deterministic uniform/Zipf workloads
backend/app/experiments/common.py    CACHES registry + run_trace() (identical traces);
                                     with_inserts() = paper write mix
backend/app/experiments/fidelity.py  sweeps: --sweep write|scan|size --insert-share 0.5
                                     --block-size 48 --seeds N --seed-offset K --values a,b
                                     --caches none,block,range,group,zio-naive
backend/app/experiments/motivation.py week-1 go/no-go (update-only mix; historical)
backend/app/service.py               Session (engine + optional cache + flush/compaction EventLog +
                                     cache inspector) and run_benchmark() (calls run_trace)
backend/app/results_view.py          read-only CSV aggregation for the UI (same ci95 as the runners)
backend/app/api/routes.py, main.py, run.py   FastAPI backend (port 8000); two sessions A/B (?sid=)
backend/results/week1|week2|week2b|week2c       CSVs + SUMMARY.md per step
frontend/                            React + Vite "LSM Cache Lab": Benchmark (demo-scale runs via the
                                     experiment code), Paper results (reads backend/results CSVs),
                                     Twin Lab (two engines, same ops, cache inspector, scenarios).
                                     The UI never computes results. API proxy target: API_TARGET env.
docs/DECISIONS.md                    decision log, novelty position, claims, threats, paper plan

## How to run
tests:       cd backend && python -m tests.test_engine && python -m tests.test_service
             && python -m tests.test_group_cache && python -m tests.test_baselines
             && python -m tests.test_api   (40 tests; test_api needs fastapi + httpx)
experiment:  cd backend && python -m app.experiments.fidelity --sweep write --insert-share 0.5
             --block-size 48 --seeds 10 --seed-offset 6 --caches none,block,range,group,zio-naive
backend UI:  cd backend && pip install -r requirements.txt && python run.py
frontend:    cd frontend && npm install && npm run dev   (http://localhost:5173)
Verified 2026-10-17: FastAPI routes (tests/test_api.py + live server), `npm install`, `vite build`,
and the three UI tabs driven end to end in headless Chrome. Restart `python run.py` after pulling
backend changes (an old server on :8000 returns 404 for the new routes).
PROTOCOL: warm-up and measured traces share one hot set (generate(perm_seed=seed)); see
DECISIONS.md §11. Results in backend/results/week3/mismatched_warmup/ are sensitivity data only.
