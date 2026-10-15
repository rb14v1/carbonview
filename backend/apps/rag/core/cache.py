import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    """Small thread-safe TTL cache for hot-path RAG reuse."""

    def __init__(self, *, maxsize: int = 256, ttl_secs: float = 300.0):
        self.maxsize = max(1, int(maxsize))
        self.ttl_secs = max(1.0, float(ttl_secs))
        self._lock = threading.Lock()
        self._values: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        now = time.monotonic()
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._values.pop(key, None)
                return None
            self._values.move_to_end(key)
            return value

    def set(self, key: K, value: V) -> None:
        expires_at = time.monotonic() + self.ttl_secs
        with self._lock:
            self._values.pop(key, None)
            self._values[key] = (expires_at, value)
            self._prune_locked()

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires_at, _) in self._values.items() if expires_at <= now]
        for key in expired:
            self._values.pop(key, None)
        while len(self._values) > self.maxsize:
            self._values.popitem(last=False)
