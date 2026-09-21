import hashlib
import random


class RNGProvider:
    def __init__(self, seed):
        self.seed = seed
        self._streams = {}

    def stream(self, name):
        if name not in self._streams:
            digest = hashlib.sha256(f"{self.seed}:{name}".encode("utf-8")).hexdigest()
            stream_seed = int(digest[:16], 16)
            self._streams[name] = random.Random(stream_seed)
        return self._streams[name]
