from app.config import LSMConfig
from app.lsm.engine import LSMEngine
from app.cache.groupcache import SimpleGroupCache

# A tiny tree so flushes and compactions happen quickly.
CFG = LSMConfig(block_size=8, memtable_size=16, l0_run_limit=2, l1_capacity=160)
HOT = (40, 50)                     # the range our "users" keep scanning


def reads(eng, n=10):
    before = eng.io.query_reads
    for _ in range(n):
        eng.scan(*HOT)
    return eng.io.query_reads - before


def scenario(name, **switches):
    eng = LSMEngine(CFG)
    cache = SimpleGroupCache(10**6, seed=0, **switches)
    eng.attach_cache(cache)
    out = [name]

    for k in range(0, 200, 2):                     # 1. load 100 keys: 0, 2, ..., 198
        eng.put(k, f"v{k}")
    eng.flush()
    reads(eng, 30)                                  # 2. warm up: hot range gets cached
    out.append(reads(eng))

    for k in (41, 43, 45, 47):                      # 3. insert NEW keys into the hot range
        eng.put(k, "new")
    for k in range(501, 525, 2):                    #    plus other writes to fill the MemTable
        eng.put(k, "x")
    out.append(reads(eng))                          #    -> flush: a new L0 run is created

    eng.put(49, "new")                              # 4. one more NEW key in the hot range, then
    for k in range(601, 700, 2):                    #    enough writes to flush AND compact
        eng.put(k, "y")                             #    before anyone queries again
    out.append(reads(eng))

    st = cache.stats
    out.append(f"seeded={st['flush_seeded']} kept={st['case1_kept']} "
               f"discarded={st['case2_discarded']} completed={st['case2_completed']}")
    cache.check_invariants()
    return out


rows = [scenario("Group Cache (baseline)"),
        scenario("+ flush seeding only", seed_on_flush=True),
        scenario("+ compaction completion only", complete_on_compaction=True),
        scenario("+ both (our mechanism)", seed_on_flush=True, complete_on_compaction=True)]

print(f"Disk reads for 10 x scan{HOT}   (lower is better)\n")
print(f"{'':30}{'warm':>6}{'after flush':>13}{'after compaction':>18}   cache events")
for name, warm, flush, comp, events in rows:
    print(f"{name:30}{warm:>6}{flush:>13}{comp:>18}   {events}")
