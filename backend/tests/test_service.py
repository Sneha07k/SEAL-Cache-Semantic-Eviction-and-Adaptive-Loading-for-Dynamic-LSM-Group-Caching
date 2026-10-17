"""Tests for the service layer and workload generator. Run: python -m tests.test_service"""
import json
from collections import Counter

from app.service import Session
from app.workload.generator import generate
from app.correctness.reference import run_differential
from app.lsm.engine import LSMEngine
from app.config import LSMConfig

SMALL = dict(block_size=4, memtable_size=16, size_ratio=3, l0_run_limit=2, l1_capacity=48)


def test_generator_is_deterministic_and_respects_mix():
    a = generate(5000, 500, seed=7, write_ratio=0.5, delete_ratio=0.0, scan_ratio=0.25)
    b = generate(5000, 500, seed=7, write_ratio=0.5, delete_ratio=0.0, scan_ratio=0.25)
    assert a == b
    kinds = Counter(op[0] for op in a)
    assert abs(kinds["put"] / 5000 - 0.5) < 0.03
    assert abs(kinds["scan"] / 5000 - 0.25) < 0.03
    assert kinds["delete"] == 0


def test_zipf_is_skewed():
    ops = generate(20000, 1000, seed=1, write_ratio=0, delete_ratio=0, scan_ratio=0,
                   zipf_theta=0.99)
    top = Counter(op[1] for op in ops).most_common(10)
    assert sum(c for _, c in top) / 20000 > 0.2      # top 1% of keys get >20% of accesses


def _hot(ops, top=100):
    return {k for k, _ in Counter(o[1] for o in ops).most_common(top)}


def test_shared_hot_set_between_warmup_and_measured_trace():
    """Different trace seeds give different hot sets unless perm_seed pins them (a warm-up
    on a different hot set does not warm the cache for the measured phase)."""
    kw = dict(write_ratio=0.0, delete_ratio=0.0, scan_ratio=0.0, zipf_theta=0.8)
    legacy = len(_hot(generate(20_000, 50_000, 1006, **kw)) & _hot(generate(20_000, 50_000, 6, **kw)))
    shared = len(_hot(generate(20_000, 50_000, 1006, perm_seed=6, **kw))
                 & _hot(generate(20_000, 50_000, 6, perm_seed=6, **kw)))
    assert legacy <= 10 and shared >= 60, (legacy, shared)
    a = generate(500, 1000, 3, zipf_theta=0.8, perm_seed=9)
    assert a == generate(500, 1000, 3, zipf_theta=0.8, perm_seed=9)       # deterministic
    assert a != generate(500, 1000, 4, zipf_theta=0.8, perm_seed=9)       # op stream differs
    from app.experiments.common import run_trace
    kw2 = dict(keys=3000, warmup=1500, ops=1500, write_ratio=0.2, block_size=16)
    r, r2 = run_trace("group", 6, **kw2), run_trace("group", 6, **kw2)
    same = lambda x, y: x == y or (x != x and y != y)          # NaN (undefined) == NaN
    assert all(same(r[k], r2[k]) for k in r)


SMALL_TREE = dict(block_size=8, memtable_size=32, size_ratio=4, l0_run_limit=2, l1_capacity=128)


def _hot_scenario(s):
    """Load data, make a range hot with short scans, then write new keys into it."""
    s.put_range(0, 399)
    for i in range(200):
        lo = 100 + (i % 20) * 2
        s.scan(lo, lo + 2)
    s.put_range(101, 199, step=2)                  # 50 new keys inside the hot range
    return s.flush()


def test_session_cache_inspector_and_event_log():
    a = Session(cache="group", **SMALL_TREE)
    b = Session(cache="zio-naive", **SMALL_TREE)
    sa, sb = _hot_scenario(a), _hot_scenario(b)
    json.dumps(sa), json.dumps(sb)                 # JSON-safe
    shape = lambda st: [[(r["min_key"], r["max_key"], r["size"]) for r in lv["runs"]]
                        for lv in st["levels"]]               # ids differ across sessions
    assert shape(sa) == shape(sb), "identical ops must give identical trees"
    assert sa["cache"]["name"] == "group" and sa["cache"]["groups"]
    assert sa["cache"]["bytes"] <= sa["cache"]["capacity"]
    for st in (sa, sb):
        kinds = {e["kind"] for e in st["events"]["recent"]}
        assert {"flush", "compaction"} <= kinds
        assert st["events"]["total"] >= len(st["events"]["recent"])
    # only our mechanism seeds groups at flush time
    assert sb["cache"]["maintenance"]["groups_created_flush_seed"] > 0
    assert sa["cache"]["maintenance"]["groups_created_flush_seed"] == 0
    # (a later compaction may already have rebuilt seeded groups as "case1", so resident
    # origins are not asserted; the event log and counters carry the provenance)
    assert not any(g["origin"] in ("flush_seed", "completed") for g in sa["cache"]["groups"])
    assert sum(e["cache"].get("groups_created_flush_seed", 0) for e in sb["events"]["recent"])         == sb["cache"]["maintenance"]["groups_created_flush_seed"]
    assert any(e["cache"].get("flush_seeded") for e in sb["events"]["recent"])
    q = b.scan(100, 102)["last_query"]
    assert "cache_delta" in q and q["kind"] == "scan"


def _raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ValueError:
        return True
    return False


def test_session_all_caches_work_and_bad_cache_rejected():
    from app.service import UI_CACHES
    for name in UI_CACHES:
        s = Session(cache=name, **SMALL_TREE)
        st = _hot_scenario(s)
        json.dumps(st)
        assert (st["cache"] is None) == (name == "none")
        if name in ("block", "range"):
            assert st["cache"]["groups"] and st["cache"]["groups"][0]["origin"] in ("block", "range")
        # a cache must never change answers: same scan result as an uncached engine
        ref = Session(cache="none", **SMALL_TREE)
        _hot_scenario(ref)
        assert s.scan(90, 210)["last_query"]["result"] == ref.scan(90, 210)["last_query"]["result"]
    assert _raises(Session, cache="nope")
    assert _raises(Session, cache="group", cache_kb=0)


def test_benchmark_runs_experiment_machinery_and_enforces_limits():
    from app.service import run_benchmark
    out = run_benchmark(["none", "group", "zio-naive"], seeds=2, keys=2000, warmup=1000,
                        ops=2000, write_ratio=0.5)
    assert len(out["rows"]) == 6 and set(out["summary"]) == {"none", "group", "zio-naive"}
    assert all(r["reads_per_query"] > 0 for r in out["rows"])
    p = next(x for x in out["paired"] if x["cand"] == "zio-naive" and x["base"] == "none")
    assert p["n"] == 2 and "significant" in p
    json.dumps(out)
    assert _raises(run_benchmark, ["group"], seeds=1, keys=10**6)
    assert _raises(run_benchmark, ["group"], seeds=99)
    assert _raises(run_benchmark, ["bogus"], seeds=1)
    assert _raises(run_benchmark, [], seeds=1)


def test_results_view_aggregates_and_rejects_bad_paths():
    import csv, tempfile
    from pathlib import Path
    from app import results_view as rv
    rows = []
    for w in (0.2, 0.5):
        for seed in (6, 7, 8):
            rows.append(dict(cache="group", seed=seed, write_ratio=w, block_size=48,
                             policy="leveling", reads_per_query=1.0 + w + seed * 0.01))
            rows.append(dict(cache="block", seed=seed, write_ratio=w, block_size=48,
                             policy="leveling", reads_per_query=1.1 + w + seed * 0.01))
    old = rv.RESULTS_DIR
    with tempfile.TemporaryDirectory() as d:
        rv.RESULTS_DIR = Path(d)
        try:
            (Path(d) / "sub").mkdir()
            with (Path(d) / "sub" / "t.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            (Path(d) / "other.csv").write_text("a,b\n1,2\n")           # not an experiment CSV
            lst = rv.list_results()
            assert [x["name"] for x in lst] == ["sub/t.csv"] and lst[0]["param"] == "write_ratio"
            r = rv.load_result("sub/t.csv")
            assert r["xs"] == [0.2, 0.5] and r["caches"] == ["block", "group"]
            pt = r["paired"]["group|block"][0]
            assert pt["n"] == 3 and pt["reduction"] > 0 and pt["worse_seeds"] == 0
            assert r["paired"]["block|group"][0]["reduction"] < 0
            assert abs(r["series"]["group"][0]["mean"] - 1.27) < 1e-9
            for bad in ("../x.csv", "sub/../../x.csv", "/etc/passwd.csv", "sub/t.txt", "nope.csv"):
                assert _raises(rv.load_result, bad), bad
            assert _raises(rv.load_result, "other.csv")
        finally:
            rv.RESULTS_DIR = old


def test_engine_correct_on_generated_skewed_workloads():
    for seed in range(5):
        ops = generate(3000, 300, seed=seed, write_ratio=0.5, delete_ratio=0.1,
                       scan_ratio=0.2, zipf_theta=0.9, scan_len=(1, 40))
        run_differential(LSMEngine(LSMConfig(**SMALL)), ops, check_every=101)


def test_session_state_is_json_and_reports_queries():
    s = Session(**SMALL)
    s.apply([("put", k, f"v{k}") for k in range(100)])
    st = s.scan(10, 30)
    json.dumps(st)                                   # must be serialisable for the API
    q = st["last_query"]
    assert [k for k, _ in q["result"]] == list(range(10, 31))
    assert len(q["blocks_read"]) == q["io_delta"].get("scan_read", 0) > 0
    all_blocks = {b["id"] for lvl in st["levels"] for r in lvl["runs"] for b in r["blocks"]}
    assert set(q["blocks_read"]) <= all_blocks       # highlighted blocks exist in the view
    st = s.get(5)
    assert st["last_query"]["result"] == "v5"


def test_session_rejects_bad_input():
    s = Session(**SMALL)
    for bad in (lambda: s.reset(nonsense=1), lambda: s.apply([("explode", 1)]),
                lambda: s.run_workload(0, 10, 1)):
        try:
            bad()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


if __name__ == "__main__":
    import sys
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
