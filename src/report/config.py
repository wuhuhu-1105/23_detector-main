from __future__ import annotations

import argparse
from dataclasses import dataclass

from .types import ReportConfigData


@dataclass
class ReportConfig:
    sampling_start_s: float = 1.0
    sampling_end_s: float = 2.0
    gap_allow_sampling_s: float = 10.0
    people_grace_s: float = 1.5
    unblocked_alarm_s: float = 2.0
    gap_allow_unblocked_s: float = 0.5
    enable_min_sampling_duration: bool = False
    sampling_min_s: float = 180.0
    fps_assume: float = 25.0

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--enable-min-sampling-duration", action="store_true", default=False)
        parser.add_argument("--sampling-min-s", type=float, default=180.0)
        parser.add_argument("--people-grace-s", type=float, default=1.5)
        parser.add_argument("--unblocked-alarm-s", type=float, default=2.0)
        parser.add_argument("--gap-allow-unblocked-s", type=float, default=0.5)
        parser.add_argument("--sampling-start-s", type=float, default=1.0)
        parser.add_argument("--sampling-end-s", type=float, default=2.0)
        parser.add_argument("--gap-allow-sampling-s", type=float, default=10.0)
        parser.add_argument("--fps-assume", type=float, default=25.0)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "ReportConfig":
        return cls(
            sampling_start_s=float(args.sampling_start_s),
            sampling_end_s=float(args.sampling_end_s),
            gap_allow_sampling_s=float(args.gap_allow_sampling_s),
            people_grace_s=float(args.people_grace_s),
            unblocked_alarm_s=float(args.unblocked_alarm_s),
            gap_allow_unblocked_s=float(args.gap_allow_unblocked_s),
            enable_min_sampling_duration=bool(args.enable_min_sampling_duration),
            sampling_min_s=float(args.sampling_min_s),
            fps_assume=float(args.fps_assume),
        )

    def to_data(self) -> ReportConfigData:
        return ReportConfigData(
            sampling_start_s=self.sampling_start_s,
            sampling_end_s=self.sampling_end_s,
            gap_allow_sampling_s=self.gap_allow_sampling_s,
            people_grace_s=self.people_grace_s,
            unblocked_alarm_s=self.unblocked_alarm_s,
            gap_allow_unblocked_s=self.gap_allow_unblocked_s,
            enable_min_sampling_duration=self.enable_min_sampling_duration,
            sampling_min_s=self.sampling_min_s,
            fps_assume=self.fps_assume,
        )
