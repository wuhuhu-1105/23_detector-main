from __future__ import annotations

import argparse
import json
import os
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional, Tuple

import cv2

from src.core.config import AppConfig
from src.core.paths import get_outputs_root
from src.report import ReportConfig, build_report, write_report_docx, write_report_json, write_report_pdf
from src.report.video_export import export_overlay_video, write_frames_meta_jsonl
from src.runtime.config_overrides import apply_cli_overrides
from src.runtime.network_guard import enforce_no_network
from src.runtime.pipeline import iter_frame_outputs
from src.runtime.serialization import to_jsonable
from src.runtime.source_utils import validate_source
try:
    from tqdm import tqdm
except Exception:
    tqdm = None

ProgressCallback = Callable[[int, int, float, Optional[float], str], None]


def default_output_root() -> str:
    return get_outputs_root()


def next_reports_dir(root: str) -> str:
    stamp = time.strftime("%m%d")
    idx = 1
    while True:
        name = f"reports_{stamp}_{idx:02d}"
        path = os.path.join(root, name)
        if not os.path.exists(path):
            return path
        idx += 1


def report_data_dir(reports_dir: str) -> str:
    return os.path.join(reports_dir, "report")


def ensure_outdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    test_path = os.path.join(path, ".write_test")
    try:
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
    finally:
        if os.path.exists(test_path):
            os.remove(test_path)


def get_total_frames(source: str) -> int:
    cap = cv2.VideoCapture(source)
    try:
        if not cap.isOpened():
            return 0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return total if total > 0 else 0
    finally:
        cap.release()


def _payload_from_output(output) -> dict:
    det_payload = {k: [asdict(b) for b in v] for k, v in output.detections.items()}
    return {
        "frame_index": output.frame_index,
        "timestamp_ms": output.timestamp_ms,
        "fps": output.fps,
        "state": output.state,
        "state_duration_sec": output.state_duration_sec,
        "detections": det_payload,
        "metrics": output.metrics,
    }


def _write_run_jsonl(frame_outputs: list, path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for output in frame_outputs:
            payload = to_jsonable(_payload_from_output(output))
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return path


class _ProgressTracker:
    def __init__(
        self,
        total_frames: int,
        callback: Callable[[int, int, float, Optional[float], str], None],
        *,
        every_frames: int = 5,
        min_interval_s: float = 0.2,
    ) -> None:
        self.total_frames = total_frames
        self.callback = callback
        self.every_frames = every_frames
        self.min_interval_s = min_interval_s
        self.done = 0
        self._last_emit_t = 0.0
        self._last_emit_frames = 0
        self._samples = deque(maxlen=20)
        self._last_fps = 0.0

    def update(self, inc: int = 1, stage: str = "video") -> None:
        self.done += inc
        now = time.perf_counter()
        if (self.done - self._last_emit_frames) < self.every_frames and (
            now - self._last_emit_t
        ) < self.min_interval_s:
            return
        self._samples.append((now, self.done))
        fps = self._compute_fps()
        if fps > 0:
            self._last_fps = fps
        eta = None
        if self.total_frames > 0 and fps > 0:
            eta = max(0.0, (self.total_frames - self.done) / fps)
        self.callback(self.done, self.total_frames, fps, eta, stage)
        self._last_emit_t = now
        self._last_emit_frames = self.done

    def _compute_fps(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        t0, f0 = self._samples[0]
        t1, f1 = self._samples[-1]
        dt = t1 - t0
        if dt <= 1e-6:
            return 0.0
        return (f1 - f0) / dt

    @property
    def last_fps(self) -> float:
        return self._last_fps


class _CheckpointLogger:
    def __init__(self, total_frames: int, log_fn: Callable[[str], None]) -> None:
        self.total_frames = total_frames
        self.log_fn = log_fn
        self.next_percent = 5
        self.next_frame = 200

    def update(self, done_frames: int) -> None:
        if self.total_frames > 0:
            pct = (done_frames / self.total_frames) * 100.0
            while pct >= self.next_percent:
                self.log_fn(f"[PROGRESS] {self.next_percent}% ({done_frames}/{self.total_frames})")
                self.next_percent += 5
        while done_frames >= self.next_frame:
            self.log_fn(f"[PROGRESS] {done_frames} frames")
            self.next_frame += 200


def run_export(
    args,
    *,
    outputs_root: str,
    reports_dir: str,
    report_dir: str,
    export_overlay: bool,
    export_docx: bool,
    export_pdf: bool,
    progress_cb: Optional[ProgressCallback] = None,
    use_tqdm: bool = True,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Tuple[int, dict]:
    def _log(message: str) -> None:
        if log_fn:
            log_fn(message)

    try:
        validate_source(args.source)
    except FileNotFoundError as exc:
        _log(f"[PATH] {exc}")
        return 2, {}
    except RuntimeError as exc:
        _log(f"[VIDEO] {exc}")
        return 3, {}

    report_cfg = ReportConfig.from_args(args)
    app_cfg = AppConfig()
    if args.device is None:
        args.device = "cpu"
    app_cfg.enable_b = True
    app_cfg.enable_c = True
    app_cfg.enable_d = True
    app_cfg.enable_e = True
    apply_cli_overrides(app_cfg, args)
    try:
        enforce_no_network(app_cfg, allow_network=args.allow_network)
    except FileNotFoundError as exc:
        _log(f"[DEPENDENCY] {exc}")
        return 5, {}

    stem = Path(args.source).stem
    json_path = os.path.join(report_dir, f"report_{stem}.json")
    docx_path = os.path.join(reports_dir, f"report_{stem}.docx")
    pdf_path = os.path.join(reports_dir, f"report_{stem}.pdf")
    run_path = os.path.join(report_dir, f"run_{stem}.jsonl")
    meta_path = os.path.join(report_dir, f"frames_meta_{stem}.jsonl")
    video_out = args.video_out or os.path.join(reports_dir, f"overlay_{stem}.mp4")

    frame_total = get_total_frames(args.source)
    total_frames = frame_total
    if export_overlay and frame_total > 0:
        total_frames = frame_total * 2

    if progress_cb:
        progress_cb(0, total_frames, 0.0, None, "video")
    progress_tracker = _ProgressTracker(total_frames, progress_cb) if progress_cb else None
    checkpoint_logger = _CheckpointLogger(total_frames, _log)

    device_mode = getattr(args, "device_mode", "auto")
    resolved_device = getattr(args, "device", "cpu")
    cuda_available = getattr(args, "cuda_available", None)
    cuda_reason = getattr(args, "cuda_reason", "")
    _log(f"source: {args.source}")
    _log(f"outputs_root: {os.path.abspath(outputs_root)}")
    _log(f"reports_dir: {os.path.abspath(reports_dir)}")
    _log(f"report_dir: {os.path.abspath(report_dir)}")
    _log(
        f"device_mode={device_mode} resolved_device={resolved_device} "
        f"cuda_available={cuda_available} reason={cuda_reason}"
    )

    try:
        pipeline_args = argparse.Namespace(
            fps_assume=report_cfg.fps_assume,
            start_sec=None,
            end_sec=None,
            infer_every=1,
            device=args.device,
            half=args.half,
        )
        setattr(pipeline_args, "_model_info_printed", True)
        frame_outputs = []
        pipeline_bar = None
        if use_tqdm and tqdm is not None:
            pipeline_bar = tqdm(total=frame_total or None, desc="Running pipeline", unit="frame")
        for output in iter_frame_outputs(pipeline_args, app_cfg, args.source):
            frame_outputs.append(output)
            if pipeline_bar is not None:
                pipeline_bar.update(1)
            if progress_tracker is not None:
                progress_tracker.update(1, stage="video")
                checkpoint_logger.update(progress_tracker.done)
        if pipeline_bar is not None:
            pipeline_bar.close()
    except Exception as exc:
        _log(f"[PIPELINE] {exc}")
        return 4, {}

    report = build_report(frame_outputs, report_cfg, args.source)

    if export_pdf and not export_docx:
        export_docx = True

    progress = None
    if use_tqdm and export_docx and tqdm is not None:
        progress = tqdm(total=100, desc="Generating report", unit="%")
    try:
        write_report_json(report, json_path)
    except OSError as exc:
        if progress is not None:
            progress.close()
        _log(f"[PATH] Failed to write report.json: {exc}")
        return 2, {}
    if progress is not None:
        progress.update(10.0)

    try:
        if export_docx:
            write_report_docx(report, docx_path, progress=progress)
        if export_pdf:
            if progress_cb:
                progress_cb(total_frames, total_frames, 0.0, None, "pdf")
            write_report_pdf(report, docx_path, pdf_path)
    except ImportError as exc:
        _log(f"[DEPENDENCY] {exc}")
        return 5, {}
    except OSError as exc:
        _log(f"[PATH] {exc}")
        return 2, {}
    except Exception as exc:
        _log(f"[PIPELINE] {exc}")
        return 4, {}
    finally:
        if progress is not None:
            progress.close()

    try:
        _write_run_jsonl(frame_outputs, run_path)
    except OSError as exc:
        _log(f"[PATH] Failed to write run.jsonl: {exc}")
        return 2, {}

    outputs = [json_path, run_path]
    if export_docx:
        outputs.append(docx_path)
    if export_pdf:
        outputs.append(pdf_path)
    if export_overlay:
        if use_tqdm and tqdm is None:
            _log("[DEPENDENCY] tqdm is required for video export progress display. Install it via: pip install tqdm")
            return 5, {}
        try:
            write_frames_meta_jsonl(frame_outputs, meta_path, report_cfg.fps_assume)
            video_bar = None
            if use_tqdm and tqdm is not None:
                video_bar = tqdm(total=frame_total or None, desc="Exporting video", unit="frame")

            def _on_export_frame() -> None:
                if progress_tracker is not None:
                    progress_tracker.update(1, stage="video")
                    checkpoint_logger.update(progress_tracker.done)

            out_path, elapsed = export_overlay_video(
                args.source,
                report,
                meta_path,
                video_out,
                fps_assume=report_cfg.fps_assume,
                no_boxes=args.no_boxes,
                progress=video_bar,
                on_frame=_on_export_frame if progress_tracker is not None else None,
            )
            if video_bar is not None:
                video_bar.close()
            outputs.append(out_path)
            _log(f"Video export completed in {elapsed:.1f}s")
            try:
                os.remove(meta_path)
            except OSError:
                pass
        except ImportError as exc:
            _log(f"[DEPENDENCY] {exc}")
            return 5, {}
        except Exception as exc:
            _log(f"[VIDEO] {exc}")
            return 3, {}

    _log("Report generation completed.")
    if export_docx:
        _log(f"docx: {os.path.abspath(docx_path)}")
    _log(f"mp4: {os.path.abspath(video_out)}")
    _log(f"jsonl: {os.path.abspath(run_path)}")
    _log(f"json: {os.path.abspath(json_path)}")
    if export_pdf:
        _log(f"pdf: {os.path.abspath(pdf_path)}")
    for path in outputs:
        _log(f"- {path}")

    info = {
        "outputs_root": os.path.abspath(outputs_root),
        "reports_dir": os.path.abspath(reports_dir),
        "report_dir": os.path.abspath(report_dir),
        "docx": os.path.abspath(docx_path) if export_docx else None,
        "mp4": os.path.abspath(video_out),
        "jsonl": os.path.abspath(run_path),
        "json": os.path.abspath(json_path),
        "pdf": os.path.abspath(pdf_path) if export_pdf else None,
        "last_fps": progress_tracker.last_fps if progress_tracker is not None else None,
        "exit_code": 0,
    }
    return 0, info
