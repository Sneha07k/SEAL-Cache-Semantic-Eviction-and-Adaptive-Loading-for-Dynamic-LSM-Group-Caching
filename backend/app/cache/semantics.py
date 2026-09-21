import hashlib

CRITICAL_BUCKET_CEILING = 10
LOW_PRIORITY_BUCKET_FLOOR = 80


def classify_key(key):
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < CRITICAL_BUCKET_CEILING:
        return "critical"
    if bucket >= LOW_PRIORITY_BUCKET_FLOOR:
        return "low_priority"
    return "normal"


def classify_group(keys):
    classes = [classify_key(key) for key in keys]
    if not classes:
        return "normal"
    if "critical" in classes:
        return "critical"
    if all(c == "low_priority" for c in classes):
        return "low_priority"
    return "normal"
