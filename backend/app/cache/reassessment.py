def find_largest_covered_run(actual_keys, merged_entries):
    best_start, best_end, best_len = None, None, 0
    current_start, current_len = None, 0
    for key in actual_keys:
        if key in merged_entries:
            if current_start is None:
                current_start = key
            current_len += 1
            if current_len > best_len:
                best_len, best_start, best_end = current_len, current_start, key
        else:
            current_start, current_len = None, 0
    return best_start, best_end, best_len


def find_largest_untouched_run(sorted_keys, delta_keys):
    best_start, best_end, best_len = None, None, 0
    current_start, current_len = None, 0
    for key in sorted_keys:
        if key not in delta_keys:
            if current_start is None:
                current_start = key
            current_len += 1
            if current_len > best_len:
                best_len, best_start, best_end = current_len, current_start, key
        else:
            current_start, current_len = None, 0
    return best_start, best_end, best_len


def reassess_cluster(
    lo, hi, cluster_size, actual_keys, merged_entries, replace_threshold
):
    if not actual_keys:
        return "evict", None, None, "no live keys remain in range"
    missing = [k for k in actual_keys if k not in merged_entries]
    if not missing:
        decision = "rebuild" if cluster_size > 1 else "keep"
        return decision, lo, hi, "coverage confirmed after compaction"
    start, end, run_length = find_largest_covered_run(actual_keys, merged_entries)
    if run_length == 0:
        return "evict", None, None, "no coverage remains after compaction"
    coverage_ratio = run_length / len(actual_keys)
    if coverage_ratio >= replace_threshold:
        return (
            "replace",
            start,
            end,
            f"partial coverage ({coverage_ratio:.2f}) salvaged as narrower range",
        )
    return (
        "evict",
        None,
        None,
        f"{len(missing)} key(s) uncovered, salvageable coverage too low ({coverage_ratio:.2f})",
    )
