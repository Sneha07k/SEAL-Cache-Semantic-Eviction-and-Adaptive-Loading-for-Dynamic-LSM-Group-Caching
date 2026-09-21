def entry_size(key, entry):
    key_bytes = len(key.encode("utf-8"))
    value_bytes = len(entry.value.encode("utf-8")) if entry.value is not None else 0
    return key_bytes + value_bytes


def group_size(entries):
    return sum(entry_size(k, v) for k, v in entries.items())
