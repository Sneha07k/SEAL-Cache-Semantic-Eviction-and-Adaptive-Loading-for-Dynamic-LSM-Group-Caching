# LSM cache testbed (zero-I/O KV-group maintenance)

Research testbed for comparing LSM-tree caches (block, Range Cache, Group Cache)
and our zero-I/O KV-group maintenance mechanism. See `CLAUDE.md` (status, rules) and `docs/DECISIONS.md` (rationale).

## Run
Backend (Python 3.11+):

    cd backend
    pip install -r requirements.txt
    python -m tests.test_engine && python -m tests.test_service && python -m tests.test_group_cache  # 17 tests
    python -m app.experiments.motivation                         # go/no-go experiment (~2-3 min)
    python run.py                                                 # API on :8000, docs at /docs

Frontend (Node 18+), in a second terminal:

    cd frontend
    npm install
    npm run dev                                                   # http://localhost:5173

## Structure
    backend/
      app/
        lsm/          block-level LSM engine, I/O accounting, flush/compaction hooks
        correctness/  reference model + differential testing
        workload/     deterministic uniform/Zipf workload generator
        cache/        (week 2) cache designs
        experiments/  (weeks 1-3) motivation measurement and sweeps
        api/          FastAPI routes
        service.py    session logic used by the API
      tests/
    frontend/
      src/components/ Strata (levels on a key axis), Controls, QueryReport

Experiment numbers for the paper come from `backend/app/experiments`, never from the UI.
