def merge_group_entries(groups):
    merged = {}
    for g in groups:
        merged.update(g.entries)
    return merged
