from __future__ import annotations

from collections import Counter, deque
from typing import Deque, Dict, Set

from src.core.config import PeopleSmootherConfig
from src.core.types import PeopleRaw, PeopleStable


class PeopleSmoother:
    def __init__(self, cfg: PeopleSmootherConfig) -> None:
        self.cfg = cfg
        self._last_seen: Dict[int, int] = {}
        self._hits: Dict[int, int] = {}
        self._history: Deque[int] = deque(maxlen=cfg.window_size)
        self._vote_window: Deque[int] = deque(maxlen=25)
        self._frame_index = 0
        self._stable_count = 0
        self._candidate_count = None
        self._candidate_hits = 0
        self._last_debug: Dict[int, Dict[str, int]] = {}
        self._last_active_ids: Set[int] = set()
        self._p2 = 0.0
        self._p_other = 0.0
        self._out_counter = 0
        self._back_counter = 0

    def update(self, raw: PeopleRaw) -> PeopleStable:
        self._frame_index += 1
        for tid in raw.active_ids:
            self._last_seen[tid] = self._frame_index
            self._hits[tid] = self._hits.get(tid, 0) + 1

        active_ids: Set[int] = set()
        active_ids_for_count: Set[int] = set()
        self._last_debug = {}
        for tid, last_seen in list(self._last_seen.items()):
            age = self._frame_index - last_seen
            hits = self._hits.get(tid, 0)
            if age <= self.cfg.max_id_age:
                active_ids.add(tid)
                is_counted = age <= self.cfg.active_id_age and hits >= self.cfg.min_track_hits
                if is_counted:
                    active_ids_for_count.add(tid)
            else:
                del self._last_seen[tid]
                self._hits.pop(tid, None)
                age = self.cfg.max_id_age + 1
                hits = 0
                is_counted = False
            self._last_debug[tid] = {"age": age, "hits": hits, "counted": int(is_counted)}

        self._last_active_ids = set(active_ids_for_count)
        count_raw = len(active_ids_for_count)
        self._history.append(count_raw)
        stable = self._apply_visual_vote(count_raw)
        people_ok = stable == self.cfg.expected_people
        return PeopleStable(people_count_stable=stable, people_ok=people_ok)

    def _mode_with_recent_tiebreak(self) -> int:
        if not self._history:
            return 0
        counter = Counter(self._history)
        max_freq = max(counter.values())
        candidates = {val for val, freq in counter.items() if freq == max_freq}
        for val in reversed(self._history):
            if val in candidates:
                return val
        return self._history[-1]

    def _apply_switch_debounce(self, target: int) -> int:
        if self._stable_count == 0:
            self._stable_count = target
            return target

        if target == self._stable_count:
            self._candidate_count = None
            self._candidate_hits = 0
            return self._stable_count

        if self._candidate_count != target:
            self._candidate_count = target
            self._candidate_hits = 1
        else:
            self._candidate_hits += 1

        threshold = self.cfg.min_stable
        if self._stable_count == self.cfg.expected_people and target != self.cfg.expected_people:
            threshold = max(threshold, self.cfg.hold)

        if self._candidate_hits >= threshold:
            self._stable_count = target
            self._candidate_count = None
            self._candidate_hits = 0
        return self._stable_count

    def _apply_visual_vote(self, obs_count: int) -> int:
        vote_window_n = 25
        p_accept_2 = 0.60
        p_accept_other = 0.80
        hold_out = 20
        hold_back = 8

        self._vote_window.append(obs_count)
        if not self._vote_window:
            return self._stable_count or obs_count

        counter = Counter(self._vote_window)
        total = len(self._vote_window)
        count_2 = counter.get(self.cfg.expected_people, 0)
        self._p2 = count_2 / total
        self._p_other = 1.0 - self._p2

        candidate = self._stable_count or obs_count
        if self._p2 >= p_accept_2:
            candidate = self.cfg.expected_people
        elif self._p_other >= p_accept_other:
            non2 = {k: v for k, v in counter.items() if k != self.cfg.expected_people}
            if non2:
                candidate = max(non2.items(), key=lambda kv: (kv[1], kv[0]))[0]
        self._candidate_count = candidate

        if self._stable_count == 0:
            self._stable_count = candidate
            return self._stable_count

        if candidate == self._stable_count:
            self._out_counter = 0
            self._back_counter = 0
            return self._stable_count

        if self._stable_count == self.cfg.expected_people and candidate != self.cfg.expected_people:
            self._out_counter += 1
            self._back_counter = 0
            if self._out_counter >= hold_out:
                self._stable_count = candidate
                self._out_counter = 0
            return self._stable_count

        if self._stable_count != self.cfg.expected_people and candidate == self.cfg.expected_people:
            self._back_counter += 1
            self._out_counter = 0
            if self._back_counter >= hold_back:
                self._stable_count = candidate
                self._back_counter = 0
            return self._stable_count

        self._out_counter = 0
        self._back_counter = 0
        self._stable_count = candidate
        return self._stable_count

    def debug_string(self, max_ids: int = 8) -> str:
        info = f"p2={self._p2:.2f} p_other={self._p_other:.2f} cand={self._candidate_count} stable={self._stable_count} out={self._out_counter} back={self._back_counter}"
        if not self._last_debug:
            return f"{info} | IDs: none"
        parts = []
        for tid in sorted(self._last_debug.keys())[:max_ids]:
            info = self._last_debug[tid]
            mark = "*" if info["counted"] else ""
            parts.append(f"{tid}({info['age']}/{info['hits']}){mark}")
        more = " ..." if len(self._last_debug) > max_ids else ""
        return f"{info} | IDs: {', '.join(parts)}{more}"

    def active_ids(self) -> Set[int]:
        return set(self._last_active_ids)
