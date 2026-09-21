def group_dict(group, extra=None):
    data = {
        "id": group.id,
        "run_id": group.run_id,
        "level": group.level,
        "lo": group.lo,
        "hi": group.hi,
        "is_point": group.is_point,
        "size_bytes": group.size_bytes,
        "keys": sorted(group.entries.keys()),
    }
    if extra is not None:
        data.update(extra)
    return data
