"""HTTP layer (needs fastapi + httpx). Run: python -m tests.test_api"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TREE = dict(block_size=8, memtable_size=32, size_ratio=4, l0_run_limit=2, l1_capacity=128)


def test_meta_and_two_sessions_are_independent():
    m = client.get("/api/meta").json()
    assert "zio-naive" in m["caches"] and m["sessions"] == ["A", "B"]
    for sid, cache in (("A", "group"), ("B", "zio-naive")):
        r = client.post(f"/api/reset?sid={sid}", json=dict(TREE, cache=cache, cache_kb=32))
        assert r.status_code == 200 and r.json()["config"]["cache"] == cache
    client.post("/api/put_range?sid=A", json={"lo": 0, "hi": 99})
    a, b = client.get("/api/state?sid=A").json(), client.get("/api/state?sid=B").json()
    assert a["stats"]["ops_applied"] == 100 and b["stats"]["ops_applied"] == 0


def test_queries_and_errors():
    client.post("/api/reset?sid=A", json=dict(TREE, cache="block", cache_kb=16))
    client.post("/api/put_range?sid=A", json={"lo": 0, "hi": 199})
    s = client.post("/api/scan?sid=A", json={"lo": 10, "hi": 20}).json()
    assert s["last_query"]["kind"] == "scan" and len(s["last_query"]["result"]) == 11
    g = client.post("/api/get?sid=A", json={"key": 5}).json()
    assert g["last_query"]["result"] == "v5"
    assert client.post("/api/reset?sid=A", json=dict(TREE, cache="nope")).status_code == 422
    assert client.get("/api/state?sid=Z").status_code == 422
    assert client.post("/api/put_range?sid=A", json={"lo": 9, "hi": 1}).status_code == 400
    assert client.post("/api/workload?sid=B", json={"n": 300, "key_space": 100, "seed": 1,
                                                    "zipf_theta": 0.8, "perm_seed": 4}).status_code == 200


def test_ops_batch_and_validation():
    client.post("/api/reset?sid=A", json=dict(TREE, cache="group", cache_kb=16))
    ok = client.post("/api/ops?sid=A", json={"ops": [["put", 1, "a"], ["put", 2, "b"],
                                                      ["scan", 1, 2], ["get", 1], ["delete", 2]]})
    assert ok.status_code == 200 and ok.json()["stats"]["ops_applied"] == 5
    for bad in ([["put", 1]], [["nuke", 1]], [["scan", "a", 2]], [["get", 1, 2]], [["put", True, "x"]]):
        assert client.post("/api/ops?sid=A", json={"ops": bad}).status_code == 400, bad
    before = client.get("/api/state?sid=A").json()["stats"]["ops_applied"]
    assert client.post("/api/ops?sid=A", json={"ops": [["put", 9, "x"], ["nuke", 1]]}).status_code == 400
    assert client.get("/api/state?sid=A").json()["stats"]["ops_applied"] == before   # nothing applied
    assert client.post("/api/ops?sid=A", json={"ops": []}).status_code == 422
    assert client.post("/api/ops?sid=A", json={"ops": [["get", 1]] * 5001}).status_code == 422


def test_benchmark_endpoint_and_limits():
    ok = client.post("/api/benchmark", json=dict(caches=["group", "zio-naive"], seeds=2,
                                                 keys=2000, warmup=500, ops=1500))
    assert ok.status_code == 200 and len(ok.json()["rows"]) == 4
    assert client.post("/api/benchmark", json=dict(caches=["group"], keys=10**7)).status_code == 422
    assert client.post("/api/benchmark", json=dict(caches=["nope"], keys=2000)).status_code == 400


def test_results_endpoints_reject_traversal():
    lst = client.get("/api/results")
    assert lst.status_code == 200 and isinstance(lst.json(), list)
    for bad in ("..%2Fapp%2Fmain.py", "nope.csv", "week3/%2e%2e/%2e%2e/app/config.csv"):
        assert client.get(f"/api/results/{bad}").status_code in (400, 404)
    for item in lst.json()[:3]:
        r = client.get(f"/api/results/{item['name']}")
        assert r.status_code == 200 and r.json()["series"]


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
