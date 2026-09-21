# SEAL-Cache Simulator - Milestone 1 (50% Milestone)

## Architecture Overview
This package contains the complete 50% milestone:
1. Backend: Leveled LSM-tree storage engine, multi-policy caching (LRU, LFU, SEAL-Core), workload trace generator, and experiment runner.
2. Frontend: Dedicated React dashboard visualizing the Memtable, SSTable levels, cache hit inspection, and benchmark execution.

## System Overview

<img width="3812" height="5062" alt="seal_cache_architecture (1)" src="https://github.com/user-attachments/assets/6464a26f-7ad3-4324-8e8b-aaae4635209a" />

---

## Entity Relationship (ER) Diagram

The following ER diagram illustrates the core domain entities across the LSM storage engine, the adaptive SEAL-Cache layer, and the workload evaluation framework:

```mermaid
erDiagram
    %% Storage & LSM Entities
    RECORD {
        string key PK
        string value
        bigint timestamp
        boolean is_tombstone
    }

    MEMTABLE {
        uuid memtable_id PK
        int current_size
        int max_capacity
        string status
    }

    SSTABLE {
        uuid file_id PK
        int level_number
        string min_key
        string max_key
        int size_bytes
    }

    LSM_TREE {
        uuid tree_id PK
        int max_levels
        int memtable_threshold
    }

    %% Caching Entities
    CACHE_STORE {
        uuid cache_id PK
        string policy_type
        int max_capacity
        int current_usage
    }

    CACHE_GROUP {
        uuid group_id PK
        uuid cache_id FK
        string semantic_tag
        float utility_score
        string lifecycle_state
        int access_count
        int invalidation_count
    }

    CACHED_RECORD {
        uuid entry_id PK
        uuid group_id FK
        string key FK
        int position_index
    }

    REASSESSMENT_TASK {
        uuid task_id PK
        uuid group_id FK
        float degradation_score
        string recommended_action
        datetime evaluated_at
    }

    %% Workload & Evaluation Entities
    WORKLOAD_REQUEST {
        uuid request_id PK
        string operation_type
        string target_key
        string key_range_end
        datetime timestamp
    }

    EXPERIMENT_RUN {
        uuid run_id PK
        string cache_policy
        int total_requests
        float hit_ratio
        int disk_reads
        float avg_latency_ms
    }

    %% Relationships
    MEMTABLE }|--|| LSM_TREE : "belongs to"
    MEMTABLE ||--o{ RECORD : "buffers"
    SSTABLE ||--|{ RECORD : "persists"
    SSTABLE }|--|| LSM_TREE : "indexed within"

    CACHE_STORE ||--o{ CACHE_GROUP : "manages"
    CACHE_GROUP ||--|{ CACHED_RECORD : "contains"
    RECORD ||--o{ CACHED_RECORD : "referenced by"
    CACHE_GROUP ||--o{ REASSESSMENT_TASK : "evaluates via"

    WORKLOAD_REQUEST }|--|| CACHE_STORE : "interacts with"
    EXPERIMENT_RUN ||--o{ WORKLOAD_REQUEST : "executes"
```

### Entity Descriptions
- **RECORD**: Represents raw key-value entries with version timestamps and deletion tombstones.
- **MEMTABLE**: In-memory mutable write buffer before data flushes to persistent SSTable files.
- **SSTABLE**: Immutable on-disk sorted string table files organized into hierarchical levels.
- **LSM_TREE**: Orchestrates the storage engine, managing MemTables, level compaction, and lookups.
- **CACHE_STORE**: The caching subsystem supporting Traditional, Group, and SEAL-Cache eviction strategies.
- **CACHE_GROUP**: Logical groupings of related keys annotated with utility scores and dynamic lifecycle states (`VALID`, `REASSESS`, `EVICTED`).
- **CACHED_RECORD**: Association entity linking underlying records to their respective cached group.
- **REASSESSMENT_TASK**: Triggered when compaction or update activity invalidates group cohesion, evaluating whether to keep, rebuild, or evict.
- **WORKLOAD_REQUEST**: Read, write, or range-scan queries driving system execution.
- **EXPERIMENT_RUN**: Records evaluation benchmarks across cache policies (hit ratio, disk I/O, latency).

## How to Run

### Step 1: Start Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run.py
```
Backend runs at: http://localhost:8000
Swagger Docs at: http://localhost:8000/docs

### Step 2: Start Frontend
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at: http://localhost:5173
