def format_key(index, key_space_size):
    width = len(str(max(key_space_size - 1, 0)))
    return f"k{index:0{width}d}"


def choose_operation_type(config, rng):
    r = rng.random()
    cumulative = 0.0
    for name, ratio in (
        ("point_read", config.point_read_ratio),
        ("range_scan", config.range_scan_ratio),
        ("insert", config.insert_ratio),
        ("update", config.update_ratio),
        ("delete", config.delete_ratio),
    ):
        cumulative += ratio
        if r < cumulative:
            return name
    return "point_read"


def generate_trace(config, rng):
    keys = [format_key(i, config.key_space_size) for i in range(config.key_space_size)]
    live_keys = set()
    operations = []
    for _ in range(config.operation_count):
        op_type = choose_operation_type(config, rng)
        if op_type == "insert":
            key = rng.choice(keys)
            value = f"v{rng.randint(0, 1000000)}"
            operations.append({"type": "put", "key": key, "value": value})
            live_keys.add(key)
        elif op_type == "update":
            candidates = list(live_keys) if live_keys else keys
            key = rng.choice(candidates)
            value = f"v{rng.randint(0, 1000000)}"
            operations.append({"type": "put", "key": key, "value": value})
            live_keys.add(key)
        elif op_type == "delete":
            candidates = list(live_keys) if live_keys else keys
            key = rng.choice(candidates)
            operations.append({"type": "delete", "key": key})
            live_keys.discard(key)
        elif op_type == "range_scan":
            lo_index = rng.randint(0, config.key_space_size - 1)
            length = rng.randint(config.scan_length_min, config.scan_length_max)
            hi_index = min(lo_index + length, config.key_space_size - 1)
            operations.append(
                {"type": "scan", "lo": keys[lo_index], "hi": keys[hi_index]}
            )
        else:
            key = rng.choice(keys)
            operations.append({"type": "get", "key": key})
    return operations
