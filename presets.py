from .config import WorkloadConfig

READ_HEAVY = WorkloadConfig(
    name="read_heavy",
    operation_count=500,
    key_space_size=200,
    point_read_ratio=0.7,
    range_scan_ratio=0.1,
    insert_ratio=0.1,
    update_ratio=0.1,
    delete_ratio=0.0,
    scan_length_min=2,
    scan_length_max=10,
)

RANGE_SCAN_HEAVY = WorkloadConfig(
    name="range_scan_heavy",
    operation_count=500,
    key_space_size=200,
    point_read_ratio=0.2,
    range_scan_ratio=0.6,
    insert_ratio=0.1,
    update_ratio=0.1,
    delete_ratio=0.0,
    scan_length_min=5,
    scan_length_max=30,
)

MIXED = WorkloadConfig(
    name="mixed",
    operation_count=500,
    key_space_size=200,
    point_read_ratio=0.4,
    range_scan_ratio=0.2,
    insert_ratio=0.2,
    update_ratio=0.15,
    delete_ratio=0.05,
    scan_length_min=3,
    scan_length_max=15,
)

UPDATE_INTENSIVE = WorkloadConfig(
    name="update_intensive",
    operation_count=500,
    key_space_size=200,
    point_read_ratio=0.2,
    range_scan_ratio=0.1,
    insert_ratio=0.2,
    update_ratio=0.4,
    delete_ratio=0.1,
    scan_length_min=2,
    scan_length_max=10,
)

PRESETS = {
    "read_heavy": READ_HEAVY,
    "range_scan_heavy": RANGE_SCAN_HEAVY,
    "mixed": MIXED,
    "update_intensive": UPDATE_INTENSIVE,
}
