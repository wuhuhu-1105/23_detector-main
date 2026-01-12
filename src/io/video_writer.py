from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2


@dataclass
class VideoWriterState:
    writer: Optional[cv2.VideoWriter] = None
    codec: Optional[str] = None
    size: Optional[Tuple[int, int]] = None
    fps_used: Optional[float] = None
    saved_frames: int = 0
    open_failed: bool = False


def _codec_candidates(path: str) -> list[str]:
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".avi":
        return ["MJPG", "XVID"]
    if ext == ".mp4":
        return ["mp4v", "avc1", "H264"]
    return ["mp4v", "MJPG", "XVID", "avc1", "H264"]


def open_writer(path: str, fps: float, size: Tuple[int, int]) -> Optional[Tuple[cv2.VideoWriter, str]]:
    for code in _codec_candidates(path):
        fourcc = cv2.VideoWriter_fourcc(*code)
        writer = cv2.VideoWriter(path, fourcc, fps, size)
        if writer.isOpened():
            return writer, code
    return None


class VideoWriterManager:
    def __init__(
        self,
        save_path: Optional[str],
        save_fps: Optional[float],
        save_size: Optional[Tuple[int, int]],
        fps_assume: float,
        source_fps: Optional[float],
        source_size: Optional[Tuple[int, int]],
    ) -> None:
        self._save_path = save_path
        self._save_fps = save_fps
        self._save_size = save_size
        self._fps_assume = fps_assume
        self._source_fps = source_fps
        self._source_size = source_size
        self._state = VideoWriterState()

    def write(self, frame) -> None:
        if not self._save_path:
            return
        if self._state.open_failed:
            return

        if self._state.writer is None:
            out_fps = self._save_fps or self._source_fps or self._fps_assume
            out_size = self._save_size or self._source_size or (frame.shape[1], frame.shape[0])
            result = open_writer(self._save_path, out_fps, out_size)
            if result is None:
                self._state.open_failed = True
                print(
                    f"Failed to open VideoWriter for {self._save_path}. "
                    "Tried codecs based on file extension; video will not be saved.",
                    file=sys.stderr,
                )
                return
            writer, codec = result
            self._state.writer = writer
            self._state.codec = codec
            self._state.size = out_size
            self._state.fps_used = out_fps

        if self._state.size and (frame.shape[1], frame.shape[0]) != self._state.size:
            frame = cv2.resize(frame, self._state.size)

        if self._state.writer is not None:
            self._state.writer.write(frame)
            self._state.saved_frames += 1

    def close(self) -> Optional[str]:
        if self._state.writer is None:
            return None

        self._state.writer.release()
        if self._state.codec:
            size_used = self._state.size or self._source_size
            return (
                f"Saved demo video: {self._save_path} frames={self._state.saved_frames} "
                f"fps={self._state.fps_used} size={size_used} codec={self._state.codec}"
            )
        return None


# Integration notes for app_legacy.py (do not change behavior):
# - Create manager after computing save_size/source_fps/source_size:
#   mgr = VideoWriterManager(args.save_video, args.save_fps, save_size, args.fps_assume, source_fps, source_size)
# - In the main loop, where legacy writes video frames:
#   mgr.write(frame)
# - After the loop (where legacy releases writer and prints message):
#   msg = mgr.close(); if msg: print(msg)
