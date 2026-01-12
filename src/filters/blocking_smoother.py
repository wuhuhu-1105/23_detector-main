from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Set

from src.core.config import TagsSmootherConfig
from src.core.types import TagsRaw, TagsStable


@dataclass
class _TagState:
    active: bool = False
    on_count: int = 0
    off_count: int = 0


class BlockingSmoother:
    def __init__(self, cfg: TagsSmootherConfig) -> None:
        self.cfg = cfg
        self._state: Dict[str, _TagState] = {
            tag: _TagState() for tag in cfg.thresholds.keys()
        }
        self._last_active: Set[str] = set()
        self._last_debug = {
            "blocking_raw": False,
            "no_blocking_raw": False,
            "blocking_on": 0,
            "blocking_off": 0,
            "no_blocking_on": 0,
            "no_blocking_off": 0,
            "blocking_conf": 0.0,
            "no_blocking_conf": 0.0,
        }

    def update(self, raw: TagsRaw) -> TagsStable:
        observed = set(raw.tags)
        raw_blocking = "blocking" in raw.tags
        raw_no_blocking = "no_blocking" in raw.tags
        if "blocking" in observed and "no_blocking" in observed:
            observed.discard("blocking")

        for tag, thresholds in self.cfg.thresholds.items():
            state = self._state[tag]
            if tag in observed:
                state.on_count += 1
                state.off_count = 0
            else:
                state.off_count += 1
                state.on_count = 0

            if not state.active and state.on_count >= thresholds.on_count:
                state.active = True
            if state.active and state.off_count >= thresholds.off_count:
                state.active = False

        tags = {tag for tag, state in self._state.items() if state.active}
        if self.cfg.force_one_of and not (tags & self.cfg.force_one_of):
            tags = set(self._last_active)
        if tags:
            self._last_active = set(tags)
        self._last_debug = {
            "blocking_raw": raw_blocking,
            "no_blocking_raw": raw_no_blocking,
            "blocking_on": self._state["blocking"].on_count,
            "blocking_off": self._state["blocking"].off_count,
            "no_blocking_on": self._state["no_blocking"].on_count,
            "no_blocking_off": self._state["no_blocking"].off_count,
            "blocking_conf": raw.conf_by_tag.get("blocking", 0.0),
            "no_blocking_conf": raw.conf_by_tag.get("no_blocking", 0.0),
        }
        return TagsStable(tags=tags)

    def debug_info(self) -> Dict[str, float]:
        return dict(self._last_debug)
