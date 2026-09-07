import os
import time
from collections import deque
from threading import Lock

_WINDOW_SECONDS = 60.0
_JOIN_LIMIT = max(1, int(os.getenv("AION_JOIN_RATE_PER_MINUTE", "60")))
_MCP_LIMIT = max(1, int(os.getenv("AION_MCP_RATE_PER_MINUTE", "600")))
_join_events = deque()
_mcp_events = deque()
_join_lock = Lock()
_mcp_lock = Lock()


def _allow(events: deque, lock: Lock, limit: int) -> bool:
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    with lock:
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True


def allow_join() -> bool:
    """Process-local safety valve against accidental or abusive join floods."""
    return _allow(_join_events, _join_lock, _JOIN_LIMIT)


def allow_mcp_request() -> bool:
    """Process-local MCP abuse guard for the single-instance MVP."""
    return _allow(_mcp_events, _mcp_lock, _MCP_LIMIT)


def configured_join_limit() -> int:
    return _JOIN_LIMIT


def configured_mcp_limit() -> int:
    return _MCP_LIMIT
