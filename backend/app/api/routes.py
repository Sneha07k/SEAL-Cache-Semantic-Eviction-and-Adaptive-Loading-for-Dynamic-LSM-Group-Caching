from fastapi import APIRouter

from ..cache.manager import CacheManager
from ..config import LSMConfig
from ..experiments.config_hash import config_hash
from ..experiments.runner import run_experiment
from ..lsm.engine import LSMEngine
from ..rng import RNGProvider
from ..workload.presets import PRESETS
from .schemas import (
    DeleteRequest,
    ExperimentRequest,
    PutRequest,
    ResetRequest,
)

router = APIRouter()

engine = LSMEngine(LSMConfig())
rng_provider = RNGProvider(1)
cache_manager = CacheManager(
    engine, 500, rng_provider, 0.5, 20, 0.3, 0.7, False, 0.6, 0.5
)


@router.post("/reset")
def reset(request: ResetRequest):
    global engine, cache_manager, rng_provider
    config = LSMConfig(
        memtable_capacity=request.memtable_capacity,
        base_level_capacity=request.base_level_capacity,
        size_ratio=request.size_ratio,
        num_levels=request.num_levels,
    )
    engine = LSMEngine(config)
    rng_provider = RNGProvider(request.seed)
    cache_manager = CacheManager(
        engine,
        request.cache_capacity_bytes,
        rng_provider,
        request.replace_threshold,
        request.max_deltas_per_group,
        request.eager_rebuild_pressure,
        request.eager_evict_pressure,
        request.eager_enabled,
        request.occupancy_gate,
        request.low_priority_multiplier,
    )
    return engine.state()


@router.post("/put")
def put(request: PutRequest):
    engine.put(request.key, request.value)
    return engine.state()


@router.post("/delete")
def delete(request: DeleteRequest):
    engine.delete(request.key)
    return engine.state()


@router.get("/get/{key}")
def get(key: str):
    return {"key": key, "value": engine.get(key)}


@router.get("/scan")
def scan(lo: str, hi: str):
    return engine.scan(lo, hi)


@router.get("/state")
def state():
    return engine.state()


@router.get("/config")
def config():
    return engine.config.__dict__


@router.get("/cache/get/{key}")
def cache_get(key: str):
    return cache_manager.read_point(engine, key)


@router.get("/cache/scan")
def cache_scan(lo: str, hi: str):
    return cache_manager.read_range(engine, lo, hi)


@router.get("/cache/state")
def cache_state():
    return cache_manager.snapshot()


@router.get("/cache/affected")
def cache_affected():
    return cache_manager.affected_snapshot()


@router.get("/cache/compactions")
def cache_compactions():
    return cache_manager.compaction_snapshot()


@router.get("/workloads")
def list_workloads():
    return {name: workload.__dict__ for name, workload in PRESETS.items()}


@router.post("/experiment/run")
def run_experiment_endpoint(request: ExperimentRequest):
    if request.workload_name not in PRESETS:
        return {"error": f"unknown workload '{request.workload_name}'"}
    workload_config = PRESETS[request.workload_name]
    lsm_config = LSMConfig(
        memtable_capacity=request.memtable_capacity,
        base_level_capacity=request.base_level_capacity,
        size_ratio=request.size_ratio,
        num_levels=request.num_levels,
    )
    result = run_experiment(
        workload_config,
        lsm_config,
        request.cache_capacity_bytes,
        request.seeds,
        request.replace_threshold,
        request.max_deltas_per_group,
        request.eager_rebuild_pressure,
        request.eager_evict_pressure,
        request.eager_enabled,
        request.occupancy_gate,
        request.low_priority_multiplier,
    )
    result["config_hash"] = config_hash(
        workload_config,
        lsm_config,
        request.cache_capacity_bytes,
        request.seeds,
        request.replace_threshold,
        request.max_deltas_per_group,
        request.eager_rebuild_pressure,
        request.eager_evict_pressure,
        request.eager_enabled,
        request.occupancy_gate,
        request.low_priority_multiplier,
    )
    return result


@router.get("/experiments")
def list_experiments_endpoint():
    return []


@router.get("/experiments/{experiment_id}")
def get_experiment_endpoint(experiment_id: str):
    return {}


@router.get("/experiments/{experiment_id}/seeds")
def get_experiment_seeds_endpoint(experiment_id: str):
    return []


@router.get("/experiments/{experiment_id}/events")
def get_experiment_events_endpoint(experiment_id: str):
    return []
