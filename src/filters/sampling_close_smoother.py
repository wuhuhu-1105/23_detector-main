from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Set

from src.core.config import TagHysteresis, TagsSmootherConfig
from src.core.types import TagsRaw, TagsStable


@dataclass
class _TagState:
    active: bool = False
    on_count: int = 0
    off_count: int = 0
    conf_max: float = 0.0


class SamplingCloseSmoother:
    def __init__(self, cfg: TagsSmootherConfig) -> None:
        self.cfg = cfg
        self._state: Dict[str, _TagState] = {
            tag: _TagState() for tag in cfg.thresholds.keys()
        }
        self._last_debug = {
            "close_raw": False,
            "sampling_raw": False,
            "close_on": 0,
            "close_off": 0,
            "sampling_on": 0,
            "sampling_off": 0,
            "close_conf": 0.0,
            "sampling_conf": 0.0,
        }

    def update(self, raw: TagsRaw) -> TagsStable:
        observed = raw.tags
        for tag, thresholds in self.cfg.thresholds.items():
            state = self._state[tag]
            if tag in observed:
                state.on_count += 1
                state.off_count = 0
            else:
                state.off_count += 1
                state.on_count = 0
            state.conf_max = raw.conf_by_tag.get(tag, 0.0)

            if not state.active and state.on_count >= thresholds.on_count:
                state.active = True
            if state.active and state.off_count >= thresholds.off_count:
                state.active = False

        tags = {tag for tag, state in self._state.items() if state.active}
        self._last_debug = {
            "close_raw": "close" in observed,
            "sampling_raw": "sampling" in observed,
            "close_on": self._state["close"].on_count,
            "close_off": self._state["close"].off_count,
            "sampling_on": self._state["sampling"].on_count,
            "sampling_off": self._state["sampling"].off_count,
            "close_conf": self._state["close"].conf_max,
            "sampling_conf": self._state["sampling"].conf_max,
        }
        return TagsStable(tags=tags)

    def debug_string(self) -> str:
        d = self._last_debug
        return (
            "C raw(close/sampling)="
            f"{int(d['close_raw'])}/{int(d['sampling_raw'])} "
            f"on={d['close_on']}/{d['sampling_on']} "
            f"off={d['close_off']}/{d['sampling_off']} "
            f"conf={d['close_conf']:.2f}/{d['sampling_conf']:.2f}"
        )

    def debug_info(self) -> Dict[str, float]:
        return dict(self._last_debug)
