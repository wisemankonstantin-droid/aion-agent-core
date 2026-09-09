import os
import time
from collections import OrderedDict, deque
from threading import Lock

_WINDOW_SECONDS = 60.0
_JOIN_LIMIT = max(1, int(os.getenv("AION_JOIN_RATE_PER_MINUTE", "60")))
_MCP_LIMIT = max(1, int(os.getenv("AION_MCP_RATE_PER_MINUTE", "600")))
_join_events = deque()
_mcp_events = deque()
_join_lock = Lock()
_mcp_lock = Lock()
_EVIDENCE_LIMIT = max(1, int(os.getenv("AION_EVIDENCE_RATE_PER_MINUTE", "20")))
_EVIDENCE_AGENT_BUCKETS = 1024
_evidence_events = OrderedDict()
_evidence_lock = Lock()


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


def allow_evidence_submission(agent_id: int, now: float | None = None) -> bool:
    """Bounded process-local per-agent intake guard for the single-instance MVP."""

    current = time.monotonic() if now is None else now
    cutoff = current - _WINDOW_SECONDS
    with _evidence_lock:
        events = _evidence_events.pop(agent_id, deque())
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= _EVIDENCE_LIMIT:
            _evidence_events[agent_id] = events
            return False
        events.append(current)
        _evidence_events[agent_id] = events
        while len(_evidence_events) > _EVIDENCE_AGENT_BUCKETS:
            _evidence_events.popitem(last=False)
        return True


def configured_evidence_limit() -> int:
    return _EVIDENCE_LIMIT
