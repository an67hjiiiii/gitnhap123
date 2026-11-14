"""In-process per-user sliding-window limits; correct for one process only."""

import math
import os
from collections import deque
from threading import RLock
import time


class SlidingWindowRateLimiter:
    def __init__(self, clock=time.monotonic, window_seconds=60):
        self.clock = clock
        self.window_seconds = window_seconds
        self._entries = {}
        self._lock = RLock()

    def allow(self, user_id, bucket, limit):
        if limit == 0:
            return True, 0
        now = self.clock()
        key = (str(user_id), bucket)
        with self._lock:
            for old_key, timestamps in list(self._entries.items()):
                while timestamps and now - timestamps[0] >= self.window_seconds:
                    timestamps.popleft()
                if not timestamps:
                    del self._entries[old_key]
            timestamps = self._entries.setdefault(key, deque())
            while timestamps and now - timestamps[0] >= self.window_seconds:
                timestamps.popleft()
            if len(timestamps) >= limit:
                return False, max(1, math.ceil(self.window_seconds - (now - timestamps[0])))
            timestamps.append(now)
            return True, 0


review_rate_limiter = SlidingWindowRateLimiter()


def configured_limit(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(0, value)
