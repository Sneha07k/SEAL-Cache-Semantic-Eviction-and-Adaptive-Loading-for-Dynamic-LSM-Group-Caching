def find_affected_groups(store, key):
    return [g for g in store.groups.values() if g.lo <= key <= g.hi]
