from __future__ import annotations

from typing import Optional, Set

from src.core.config import StateEngineConfig
from src.core.types import StateResult


class StateEngine5:
    def __init__(self, cfg: StateEngineConfig) -> None:
        self.cfg = cfg
        self._stable: Optional[str] = None
        self._pending: Optional[str] = None
        self._pending_count = 0

    def compute(self, tags: Set[str]) -> StateResult:
        state_raw, reason = self._classify(tags)
        state_5class = self._debounce(state_raw)
        return StateResult(state_raw=state_raw, state_5class=state_5class, reason=reason)

    def _classify(self, tags: Set[str]) -> tuple[str, str]:
        if "blocking" in tags and "no_blocking" in tags:
            tags = set(tags)
            tags.discard("blocking")

        if "close" in tags:
            return "CLOSE", "close"

        if "no_blocking" in tags:
            if "sampling" in tags:
                return "OPEN_DANGER", "no_blocking+sampling"
            return "OPEN_VIOLATION", "no_blocking+no_sampling"

        if "blocking" in tags:
            if "sampling" in tags:
                return "OPEN_NORMAL_SAMPLING", "blocking+sampling"
            return "OPEN_NORMAL_IDLE", "blocking+no_sampling"

        return "OPEN_UNKNOWN", "open_missing_blocking"

    def _debounce(self, state_raw: str) -> str:
        if self.cfg.debounce_k <= 1:
            self._stable = state_raw
            return state_raw

        if self._stable is None:
            self._stable = state_raw
            return state_raw

        if state_raw == self._stable:
            self._pending = None
            self._pending_count = 0
            return self._stable

        if state_raw != self._pending:
            self._pending = state_raw
            self._pending_count = 1
            return self._stable

        self._pending_count += 1
        if self._pending_count >= self.cfg.debounce_k:
            self._stable = state_raw
            self._pending = None
            self._pending_count = 0
        return self._stable
