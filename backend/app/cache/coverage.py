def compute_coverage(candidates, lo, hi):
    overlapping = [g for g in candidates if not (hi < g.lo or lo > g.hi)]
    if not overlapping:
        return False, []
    overlapping.sort(key=lambda g: g.lo)
    frontier = lo
    used = []
    for g in overlapping:
        if g.lo > frontier:
            return False, used
        used.append(g)
        if g.hi > frontier:
            frontier = g.hi
        if frontier >= hi:
            return True, used
    return frontier >= hi, used
