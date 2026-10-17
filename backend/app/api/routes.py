"""REST API over service.py. Sessions A and B (?sid=) let the UI compare two caches."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import results_view
from ..service import UI_CACHES, Session, run_benchmark

router = APIRouter(prefix="/api")
_DEFAULT = dict(block_size=8, memtable_size=64, size_ratio=4, l0_run_limit=3, l1_capacity=256)
sessions = {"A": Session(cache="group", **_DEFAULT), "B": Session(cache="zio-naive", **_DEFAULT)}
SID = Query("A", pattern="^[AB]$", description="engine session")
CACHE_PATTERN = "^(" + "|".join(c.replace("+", r"\+") for c in UI_CACHES) + ")$"


class ConfigIn(BaseModel):
    block_size: int = Field(8, ge=1, le=256)
    memtable_size: int = Field(64, ge=1, le=100_000)
    size_ratio: int = Field(4, ge=2, le=20)
    l0_run_limit: int = Field(3, ge=1, le=64)
    l1_capacity: int = Field(256, ge=1)
    policy: str = Field("leveling", pattern="^(leveling|tiering)$")
    granularity: str = Field("file", pattern="^(file|level)$")
    ideal_filters: bool = True
    cache: str = Field("none", pattern=CACHE_PATTERN)
    cache_kb: int = Field(32, ge=1, le=4096)


class WorkloadIn(BaseModel):
    n: int = Field(1000, ge=1, le=200_000)
    key_space: int = Field(1000, ge=1)
    seed: int = 42
    write_ratio: float = Field(0.3, ge=0, le=1)
    delete_ratio: float = Field(0.05, ge=0, le=1)
    scan_ratio: float = Field(0.2, ge=0, le=1)
    zipf_theta: float = Field(0.0, ge=0, le=2)
    perm_seed: Optional[int] = None


class KeyIn(BaseModel):
    key: int


class PutIn(BaseModel):
    key: int
    value: str = Field(..., min_length=1, max_length=200)


class PutRangeIn(BaseModel):
    lo: int
    hi: int
    step: int = Field(1, ge=1)
    tag: str = Field("v", max_length=20)


class RangeIn(BaseModel):
    lo: int
    hi: int


class OpsIn(BaseModel):
    """A batch of operations, e.g. [["scan", 100, 103], ["put", 5, "x"], ["get", 7]]."""
    ops: list[list] = Field(..., min_length=1, max_length=5000)


class BenchIn(BaseModel):
    caches: list[str]
    seeds: int = Field(2, ge=1, le=5)
    keys: int = Field(10_000, ge=1_000, le=30_000)
    warmup: int = Field(5_000, ge=0, le=60_000)
    ops: int = Field(10_000, ge=100, le=60_000)
    write_ratio: float = Field(0.5, ge=0, le=0.95)
    scan_share: float = Field(0.2, ge=0, le=1)
    zipf: float = Field(0.8, ge=0.1, le=1.5)
    cache_frac: float = Field(0.05, ge=0.005, le=0.5)
    block_size: int = Field(48, ge=4, le=128)
    policy: str = Field("leveling", pattern="^(leveling|tiering)$")
    insert_share: float = Field(0.5, ge=0, le=1)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/meta")
def meta():
    return {"caches": UI_CACHES, "sessions": sorted(sessions)}


@router.get("/state")
def state(sid: str = SID):
    return sessions[sid].state()


@router.post("/reset")
def reset(cfg: Optional[ConfigIn] = None, sid: str = SID):
    return _call(sessions[sid].reset, **(cfg or ConfigIn()).model_dump())


@router.post("/workload")
def workload(w: WorkloadIn, sid: str = SID):
    d = w.model_dump()
    perm = d.pop("perm_seed")
    if perm is not None:                       # pin the hot-key set (see workload.generator)
        d["perm_seed"] = perm
    return _call(sessions[sid].run_workload, d.pop("n"), d.pop("key_space"), d.pop("seed"), **d)


@router.post("/put")
def put(p: PutIn, sid: str = SID):
    return _call(sessions[sid].apply, [("put", p.key, p.value)])


@router.post("/put_range")
def put_range(p: PutRangeIn, sid: str = SID):
    return _call(sessions[sid].put_range, p.lo, p.hi, p.step, p.tag)


@router.post("/delete")
def delete(k: KeyIn, sid: str = SID):
    return _call(sessions[sid].apply, [("delete", k.key)])


@router.post("/get")
def get(k: KeyIn, sid: str = SID):
    return _call(sessions[sid].get, k.key)


@router.post("/scan")
def scan(r: RangeIn, sid: str = SID):
    return _call(sessions[sid].scan, r.lo, r.hi)


@router.post("/flush")
def flush(sid: str = SID):
    return sessions[sid].flush()


@router.post("/ops")
def ops(o: OpsIn, sid: str = SID):
    return _call(sessions[sid].apply, [tuple(op) for op in o.ops])


@router.post("/benchmark")
def benchmark(b: BenchIn):
    return _call(run_benchmark, **b.model_dump())


@router.get("/results")
def results():
    return results_view.list_results()


@router.get("/results/{name:path}")
def result(name: str):
    return _call(results_view.load_result, name)
