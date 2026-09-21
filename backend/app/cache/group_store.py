import itertools


class GroupStore:
    def __init__(self, capacity_bytes):
        self.capacity_bytes = capacity_bytes
        self.groups = {}
        self.run_index = {}
        self.total_bytes = 0
        self._id_counter = itertools.count(1)

    def new_id(self):
        return next(self._id_counter)

    def groups_for_run(self, run_id):
        return [self.groups[gid] for gid in self.run_index.get(run_id, [])]

    def add(self, group):
        self.groups[group.id] = group
        self.run_index.setdefault(group.run_id, []).append(group.id)
        self.total_bytes += group.size_bytes

    def remove(self, group_id):
        group = self.groups.pop(group_id, None)
        if group is None:
            return None
        ids = self.run_index.get(group.run_id, [])
        if group.id in ids:
            ids.remove(group.id)
        self.total_bytes -= group.size_bytes
        return group

    def remove_run(self, run_id):
        ids = list(self.run_index.get(run_id, []))
        removed = [self.remove(gid) for gid in ids]
        self.run_index.pop(run_id, None)
        return removed

    def resize(self, group_id, new_size_bytes):
        group = self.groups.get(group_id)
        if group is None:
            return
        self.total_bytes += new_size_bytes - group.size_bytes
        group.size_bytes = new_size_bytes

    def has_room(self, size_bytes):
        return self.total_bytes + size_bytes <= self.capacity_bytes
