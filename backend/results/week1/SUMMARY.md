# Week-1 go/no-go results (simulator, 50K keys, 40K measured ops after 20K warm-up, 3 seeds)

Metric: query block reads per query (lower is better). "+both" = naive flush seeding +
compaction completion, NO size-aware rule yet. Same byte budget (5% of data) for all caches.

| Setting | Write ratio | No cache | Group Cache | +both | +both vs GC |
|---|---|---|---|---|---|
| Default (20% scans, Zipf 0.8, leveling) | 0.0 | 1.701 | 1.395 | 1.395 | 0.0% |
| | 0.2 | 1.697 | 1.506 | 1.498 | 0.5% |
| | 0.5 | 1.627 | 1.467 | 1.439 | 1.9% |
| | 0.8 | 1.644 | 1.537 | 1.459 | 5.1% |
| Scan-heavy (60% scans, Zipf 0.99) | 0.3 | 3.431 | 2.573 | 2.565 | 0.3% |
| | 0.5 | 3.203 | 2.383 | 2.348 | 1.5% |
| | 0.8 | 3.380 | 2.632 | 2.521 | 4.2% |
| Tiering (default mix) | 0.3 | 1.775 | 1.599 | 1.583 | 1.0% |
| | 0.5 | 1.794 | 1.626 | 1.597 | 1.8% |
| | 0.8 | 2.222 | 2.091 | 2.019 | 3.4% |

Paired per-seed differences (default setting), +both vs GC: 0.0071±0.0028 (w=0.2),
0.0280±0.0098 (w=0.5), 0.0781±0.0086 (w=0.8) reads/query, 95% CI excludes zero for w>=0.2.
Flush seeding contributes most; compaction completion alone is small (1.1% at w=0.8).

Group Cache's run-level hit rate falls from 0.176 (read-only) to 0.051 (80% writes);
+both keeps it at 0.092. Of the read savings Group Cache loses between w=0 and w=0.8
(0.306 -> 0.107 reads/query), naive +both recovers 0.078, i.e. about 39%.

Caveats: small scale; 3 seeds; Group Cache's absolute benefit here (6-25% vs no cache)
cannot yet be compared with the paper, whose gains are reported against block/range caches
(baselines not built yet). Fidelity check is a week-2 prerequisite.
