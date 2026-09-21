class Level: 
    def __init__(self, number, capacity, tiered): 
        self.number = number 
        self.capacity = capacity 
        self.tiered = tiered 
        self.runs = [] 
 
    def total_size(self): 
        return sum(run.size() for run in self.runs) 
 
    def is_over_capacity(self): 
        return self.total_size() > self.capacity 
 
    def add_run(self, sstable): 
        self.runs.append(sstable) 
 
    def clear(self): 
        self.runs = [] 
commit message
