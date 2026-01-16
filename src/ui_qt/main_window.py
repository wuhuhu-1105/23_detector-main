# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QSplitter,
    QMessageBox,
)

from src.core.types import FrameOutput
from src.core.paths import get_outputs_root
from src.runtime.serialization import to_jsonable
from src.report import write_snapshot_docx
from src.runtime.qt_adapter import draw_detections, output_to_status
from src.ui_qt.state_view_spec import StatusDTO

UI_TITLE_CN = "\u5e9f\u6c14AI\u68c0\u6d4b"

STATE_ROWS = [
    ("hole", "\u91c7\u6837\u5b54"),
    ("blocking", "\u5c01\u5835"),
    ("no_blocking", "\u672a\u5c01\u5835"),
    ("sampling_state", "\u91c7\u6837\u72b6\u6001"),
]


class MainWindow(QMainWindow):
    export_requested = pyqtSignal()
    finished = pyqtSignal(str)

    def __init__(
        self,
        debug: bool = False,
        worker: Optional[object] = None,
        display_fps: float = 15.0,
        rt_smooth: float = 0.2,
        target_ratio: float = 1.0,
        no_overlay: bool = False,
    ) -> None:
        super().__init__()
        self._debug = debug
        self._finished_emitted = False
        self._paused = False
        self._worker = worker
        self._display_fps = max(1.0, float(display_fps))
        self._no_overlay = bool(no_overlay)
        self._latest_bgr: Optional[np.ndarray] = None
        self._latest_meta: Optional[FrameOutput] = None
        self._latest_status: Optional[StatusDTO] = None
        self._latest_seq = 0
        self._rendered_seq = -1
        self._snapshot_log = []
        self._snapshot_last_key: Optional[tuple] = None
        self._display_tick_count = 0
        self._display_tick_t0 = time.perf_counter()
        self._display_fps_est = 0.0
        self._rt_last_wall: Optional[float] = None
        self._rt_last_video: Optional[float] = None
        self._rt_ratio_ema: Optional[float] = None
        self._rt_smooth = min(max(float(rt_smooth), 0.0), 1.0)
        self._target_ratio = float(target_ratio)
        self.setWindowTitle(UI_TITLE_CN)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        central.setLayout(main_layout)

        self._video_label = QLabel()
        self._video_label.setObjectName("VideoLabel")
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setScaledContents(False)
        self._video_label.setMinimumSize(640, 360)

        video_container = QWidget()
        video_container.setObjectName("VideoContainer")
        video_layout = QVBoxLayout()
        video_layout.setContentsMargins(6, 6, 6, 6)
        video_layout.setSpacing(0)
        video_layout.addWidget(self._video_label)
        video_container.setLayout(video_layout)

        self._title_label = QLabel(UI_TITLE_CN)
        self._title_label.setObjectName("TitleLabel")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        self._title_label.setFont(title_font)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setFixedHeight(48)

        self._state_label = QLabel("State: -")
        self._state_label.setObjectName("StateLabel")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        state_font = QFont()
        state_font.setPointSize(11)
        state_font.setBold(True)
        self._state_label.setFont(state_font)
        self._state_label.setFixedHeight(28)

        self._duration_label = QLabel("Duration: 0.00s")
        self._duration_label.setObjectName("DurationLabel")
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        duration_font = QFont()
        duration_font.setPointSize(11)
        duration_font.setBold(True)
        self._duration_label.setFont(duration_font)
        self._duration_label.setFixedHeight(28)

        self._fps_label = QLabel("Infer FPS: -")
        self._fps_label.setObjectName("FpsLabel")
        self._fps_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        fps_font = QFont()
        fps_font.setPointSize(11)
        fps_font.setBold(True)
        self._fps_label.setFont(fps_font)
        self._fps_label.setFixedHeight(28)

        self._display_fps_label = QLabel("Display FPS: -")
        self._display_fps_label.setObjectName("DisplayFpsLabel")
        self._display_fps_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        display_fps_font = QFont()
        display_fps_font.setPointSize(11)
        display_fps_font.setBold(True)
        self._display_fps_label.setFont(display_fps_font)
        self._display_fps_label.setFixedHeight(28)

        self._rt_ratio_label = QLabel("RealTime Ratio: -")
        self._rt_ratio_label.setObjectName("RealTimeRatioLabel")
        self._rt_ratio_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rt_font = QFont()
        rt_font.setPointSize(11)
        rt_font.setBold(True)
        self._rt_ratio_label.setFont(rt_font)
        self._rt_ratio_label.setFixedHeight(28)

        self._target_ratio_label = QLabel(f"Target Ratio: {self._target_ratio:.2f}x")
        self._target_ratio_label.setObjectName("TargetRatioLabel")
        self._target_ratio_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        tr_font = QFont()
        tr_font.setPointSize(11)
        tr_font.setBold(True)
        self._target_ratio_label.setFont(tr_font)
        self._target_ratio_label.setFixedHeight(28)

        self._table = QTableWidget(len(STATE_ROWS), 4)
        self._table.setObjectName("StatusTable")
        self._table.setHorizontalHeaderLabels(["\u5e8f\u53f7", "\u72b6\u6001", "\u5224\u5b9a", "\u8017\u65f6(s)"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setWordWrap(False)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setRowCount(len(STATE_ROWS))
        self._table.setColumnCount(4)
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self._table.horizontalHeader().setFixedHeight(44)
        self._table.verticalHeader().setDefaultSectionSize(50)
        self._init_table_rows()
        self._apply_table_column_widths()
        self._fit_table_height()
        self._row_timers = {key: {"label": "-", "start_t": None, "last_dur": None} for key, _ in STATE_ROWS}

        self._people_widget = QWidget()
        self._people_widget.setObjectName("PeopleCard")
        people_layout = QHBoxLayout()
        people_layout.setContentsMargins(8, 8, 8, 8)
        people_layout.setSpacing(10)
        self._people_widget.setLayout(people_layout)

        people_title = QLabel("\u4eba\u6570")
        people_title.setObjectName("PeopleLabel")
        people_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        people_title_font = QFont()
        people_title_font.setPointSize(12)
        people_title.setFont(people_title_font)

        self._people_value = QLabel("0")
        self._people_value.setObjectName("PeopleValue")
        self._people_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        people_value_font = QFont("Consolas", 28, QFont.Weight.Bold)
        self._people_value.setFont(people_value_font)

        people_layout.addWidget(people_title, 1)
        people_layout.addWidget(self._people_value, 2)
        self._people_widget.setMinimumHeight(90)
        self._people_widget.setMaximumHeight(130)

        self._pause_btn = QPushButton("\u6682\u505c")
        self._pause_btn.setObjectName("PauseButton")
        self._pause_btn.setFixedHeight(42)
        self._pause_btn.clicked.connect(self._toggle_pause)

        self._export_btn = QPushButton("\u62a5\u544a\u5bfc\u51fa")
        self._export_btn.setObjectName("ExportButton")
        self._export_btn.setFixedHeight(42)
        self._export_btn.clicked.connect(self._on_export)

        self._button_row = QWidget()
        self._button_row.setObjectName("ButtonRow")
        button_layout = QVBoxLayout()
        button_layout.setContentsMargins(12, 8, 12, 8)
        button_layout.setSpacing(12)
        button_layout.addWidget(self._export_btn)
        button_layout.addWidget(self._pause_btn)
        self._button_row.setLayout(button_layout)
        self._button_row.setFixedHeight(112)

        self._log = QPlainTextEdit()
        self._log.setObjectName("LogWidget")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2)
        self._log.setPlaceholderText("\u7cfb\u7edf\u65e5\u5fd7")

        self._log_container = QWidget()
        self._log_container.setObjectName("LogContainer")
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(12, 10, 12, 10)
        log_layout.setSpacing(6)
        log_layout.addWidget(self._log)
        self._log_container.setLayout(log_layout)
        self._log_container.setMinimumHeight(70)
        self._log_container.setMaximumHeight(120)

        panel_container = QWidget()
        panel_container.setObjectName("PanelContainer")
        panel_container.setMinimumWidth(360)
        panel_container.setMaximumWidth(460)
        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(10)

        bottom_container = QWidget()
        bottom_container.setObjectName("BottomContainer")
        bottom_layout = QVBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(self._people_widget, stretch=2)
        bottom_layout.addWidget(self._button_row, stretch=2)
        bottom_layout.addWidget(self._log_container, stretch=1)
        bottom_container.setLayout(bottom_layout)
        bottom_container.setMinimumHeight(260)

        panel_layout.addWidget(self._title_label, stretch=0)
        panel_layout.addWidget(self._state_label, stretch=0)
        panel_layout.addWidget(self._duration_label, stretch=0)
        panel_layout.addWidget(self._fps_label, stretch=0)
        panel_layout.addWidget(self._display_fps_label, stretch=0)
        panel_layout.addWidget(self._rt_ratio_label, stretch=0)
        panel_layout.addWidget(self._target_ratio_label, stretch=0)
        panel_layout.addWidget(self._table, stretch=7)
        panel_layout.addWidget(bottom_container, stretch=3)
        panel_container.setLayout(panel_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("MainSplitter")
        splitter.addWidget(video_container)
        splitter.addWidget(panel_container)
        splitter.setSizes([1000, 300])
        main_layout.addWidget(splitter)

        self._bottom_container = bottom_container
        self._apply_styles()

        if worker is not None and hasattr(worker, "export_report"):
            self.export_requested.connect(worker.export_report)

        self._display_timer = QTimer(self)
        self._display_timer.setInterval(int(1000.0 / self._display_fps))
        self._display_timer.timeout.connect(self.render_latest)
        self._display_timer.start()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #0B1220;
                color: #E5E7EB;
            }
            QSplitter::handle {
                background-color: rgba(0, 229, 255, 80);
                width: 1px;
            }
            QWidget#PanelContainer {
                background-color: #0F1B2D;
                border: 1px solid #1E3357;
                border-radius: 14px;
            }
            QWidget#VideoContainer {
                background-color: #050A12;
                border: 1px solid rgba(0, 229, 255, 80);
                border-radius: 12px;
            }
            QLabel#TitleLabel {
                color: #E5E7EB;
                border-bottom: 1px solid #00E5FF;
            }
            QLabel#StateLabel {
                color: #00E5FF;
            }
            QLabel#DurationLabel {
                color: #C7D2FE;
            }
            QLabel#FpsLabel {
                color: #C7D2FE;
            }
            QLabel#DisplayFpsLabel {
                color: #C7D2FE;
            }
            QLabel#RealTimeRatioLabel {
                color: #C7D2FE;
            }
            QLabel#TargetRatioLabel {
                color: #C7D2FE;
            }
            QTableWidget#StatusTable {
                background-color: #0F1B2D;
                gridline-color: #1E3357;
                color: #C7D2FE;
                border: 1px solid #1E3357;
                border-radius: 12px;
            }
            QHeaderView::section {
                background-color: #0B1220;
                color: #E5E7EB;
                border: none;
                padding: 10px;
            }
            QWidget#PeopleCard, QWidget#ButtonRow, QWidget#LogContainer {
                background-color: #0F1B2D;
                border: 1px solid #1E3357;
                border-radius: 14px;
            }
            QLabel#PeopleLabel {
                color: #C7D2FE;
            }
            QLabel#PeopleValue {
                background-color: #050A12;
                border: 1px solid #1E3357;
                border-radius: 10px;
                padding: 6px 8px;
            }
            QPushButton#PauseButton, QPushButton#ExportButton {
                background-color: #0B1220;
                color: #E5E7EB;
                border: 1px solid #1E3357;
                border-radius: 14px;
                padding: 6px 10px;
            }
            QPushButton#PauseButton:hover, QPushButton#ExportButton:hover {
                border: 1px solid #00E5FF;
            }
            QPlainTextEdit#LogWidget {
                background-color: #050A12;
                color: #C7D2FE;
                border: 1px solid #1E3357;
                border-radius: 10px;
                font-family: Consolas, 'Courier New', monospace;
            }
            QScrollBar:vertical {
                background: #0B1220;
                width: 8px;
                margin: 0px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #1E3357;
                border-radius: 4px;
                min-height: 18px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            """
        )

    def _init_table_rows(self) -> None:
        for idx, (state_key, _) in enumerate(STATE_ROWS, start=1):
            row = idx - 1
            title_text = self._chip_text_for_state(state_key)
            items = [
                QTableWidgetItem(str(idx)),
                QTableWidgetItem(title_text),
                QTableWidgetItem(""),
                QTableWidgetItem(""),
            ]
            for item in items:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.TextAlignmentRole, int(Qt.AlignmentFlag.AlignCenter))
                item.setFont(QFont("Segoe UI", 10))
            items[1].setFont(QFont("Segoe UI", 10))
            chip_fg, chip_bg = self._chip_colors_for_state(state_key)
            items[1].setForeground(QBrush(chip_fg))
            items[1].setBackground(QBrush(chip_bg))
            self._table.setItem(row, 0, items[0])
            self._table.setItem(row, 1, items[1])
            self._table.setItem(row, 2, items[2])
            self._table.setItem(row, 3, items[3])

        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(10)
        for col in range(self._table.columnCount()):
            item = self._table.horizontalHeaderItem(col)
            if item is not None:
                item.setFont(header_font)

    def _chip_text_for_state(self, state_key: str) -> str:
        for key, label in STATE_ROWS:
            if key == state_key:
                return label
        return state_key

    def _chip_colors_for_state(self, state_key: str) -> Tuple[QColor, QColor]:
        return QColor(200, 200, 200), QColor(60, 60, 60)

    def _apply_table_column_widths(self) -> None:
        total = self._table.viewport().width()
        if total <= 0:
            return
        widths = [int(total * 0.15), int(total * 0.40), int(total * 0.25), int(total * 0.20)]
        for idx, width in enumerate(widths):
            self._table.setColumnWidth(idx, width)

    def _fit_table_height(self) -> None:
        header_h = self._table.horizontalHeader().height()
        row_h = self._table.verticalHeader().defaultSectionSize()
        total = header_h + row_h * self._table.rowCount() + 4
        self._table.setFixedHeight(total)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_table_column_widths()
        if hasattr(self, "_bottom_container") and self._bottom_container is not None:
            self._bottom_container.setMaximumHeight(16777215)

    def append_log(self, text: str) -> None:
        self._log.appendPlainText(text)
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def _on_export(self) -> None:
        path, error = self._export_snapshot()
        if error:
            self.append_log(f"Export: {error}")
        elif path:
            self.append_log(f"Export: snapshot saved -> {path}")
        else:
            self.append_log("Export: no frame data yet.")

    def _export_snapshot(self) -> Tuple[Optional[str], Optional[str]]:
        if self._latest_meta is None:
            return None, None
        status = output_to_status(self._latest_meta)
        payload = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "frame_index": status.frame_index,
            "state_raw": status.state_raw,
            "state_5class": status.state_5class,
            "state_cn": status.state_cn,
            "duration_s": status.duration_s,
            "video_t_s": status.video_t_s,
            "tags_c_set": status.tags_c_set,
            "tags_d_set": status.tags_d_set,
            "people_count": status.people_count,
            "people_ok": status.people_ok,
            "people_alarm": status.people_alarm,
            "fps": status.fps,
            "target_ratio": status.target_ratio,
            "range_start": self._snapshot_log[0]["timestamp"] if self._snapshot_log else None,
            "range_end": time.strftime("%Y-%m-%d %H:%M:%S"),
            "entries": list(self._snapshot_log),
        }
        payload = to_jsonable(payload)
        out_root = get_outputs_root()
        out_dir = os.path.join(out_root, "snapshots")
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(out_dir, f"snapshot_{stamp}.docx")
        path = base
        suffix = 1
        while os.path.exists(path):
            path = os.path.join(out_dir, f"snapshot_{stamp}_{suffix}.docx")
            suffix += 1
        try:
            write_snapshot_docx(payload, path)
        except Exception as exc:
            return None, f"failed to write docx: {exc}"
        return path, None

    def _maybe_log_snapshot(self, status: StatusDTO) -> None:
        tags_c = tuple(sorted(status.tags_c_set or []))
        tags_d = tuple(sorted(status.tags_d_set or []))
        key = (
            status.state_5class,
            status.people_count,
            tags_c,
            tags_d,
        )
        if self._snapshot_last_key == key and self._snapshot_log:
            return
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "frame_index": status.frame_index,
            "video_t_s": status.video_t_s,
            "state_5class": status.state_5class,
            "state_cn": status.state_cn,
            "people_count": status.people_count,
            "people_alarm": status.people_alarm,
            "tags_c_set": list(tags_c),
            "tags_d_set": list(tags_d),
            "fps": status.fps,
            "target_ratio": status.target_ratio,
        }
        self._snapshot_log.append(entry)
        self._snapshot_last_key = key

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause_btn.setText("\u7ee7\u7eed" if self._paused else "\u6682\u505c")
        self._pause_btn.setProperty("paused", self._paused)
        self._pause_btn.style().unpolish(self._pause_btn)
        self._pause_btn.style().polish(self._pause_btn)
        if self._worker is not None and hasattr(self._worker, "set_paused"):
            self._worker.set_paused(self._paused)

    @pyqtSlot(object, object)
    def on_frame(self, frame_bgr: object, meta: object) -> None:
        if self._paused:
            return
        self._latest_bgr = frame_bgr
        self._latest_meta = meta
        self._latest_seq = getattr(meta, "frame_index", self._latest_seq + 1)

    def _update_rt_ratio(self, status: StatusDTO) -> None:
        video_now = status.video_t_s
        if video_now is None:
            return
        wall_now = time.perf_counter()
        if self._rt_last_wall is not None and self._rt_last_video is not None:
            d_wall = wall_now - self._rt_last_wall
            d_video = video_now - self._rt_last_video
            if d_wall > 0.05 and d_video >= 0.0:
                ratio = d_video / d_wall
                if self._rt_ratio_ema is None:
                    self._rt_ratio_ema = ratio
                else:
                    a = self._rt_smooth
                    self._rt_ratio_ema = a * ratio + (1.0 - a) * self._rt_ratio_ema

        self._rt_last_wall = wall_now
        self._rt_last_video = video_now
        if self._rt_ratio_ema is None:
            self._rt_ratio_label.setText("RealTime Ratio: -")
        else:
            self._rt_ratio_label.setText(f"RealTime Ratio: {self._rt_ratio_ema:.2f}x")

    def render_latest(self) -> None:
        self._display_tick_count += 1
        now = time.perf_counter()
        dt = now - self._display_tick_t0
        if dt >= 1.0:
            self._display_fps_est = self._display_tick_count / dt
            self._display_tick_count = 0
            self._display_tick_t0 = now
            self._display_fps_label.setText(f"Display FPS: {self._display_fps_est:.2f}")

        if self._latest_meta is not None:
            status = output_to_status(self._latest_meta)
            self._latest_status = status
            self._maybe_log_snapshot(status)
            self._update_status_table(status)
            self._update_people(status)
            self._update_state_label(status)
            self._update_rt_ratio(status)

        if self._latest_bgr is None:
            return
        if self._rendered_seq == self._latest_seq:
            return

        frame_bgr = self._latest_bgr
        if not self._no_overlay and self._latest_meta is not None:
            frame_bgr = draw_detections(frame_bgr, self._latest_meta.detections)
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb = np.ascontiguousarray(frame_rgb)
        h, w = frame_rgb.shape[:2]
        qimg = QImage(frame_rgb.data, w, h, frame_rgb.strides[0], QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(qimg)
        target = self._video_label.size()
        if not target.isEmpty() and pixmap.size() != target:
            pixmap = pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.FastTransformation,
            )
        self._video_label.setPixmap(pixmap)
        self._rendered_seq = self._latest_seq

    @pyqtSlot(str)
    def on_worker_error(self, message: str) -> None:
        self.append_log(f"Error: {message}")
        self._state_label.setText("State: ERROR")
        QMessageBox.critical(self, "Video Error", message)
        self._emit_finished("error")

    def closeEvent(self, event) -> None:
        if self._worker is not None and hasattr(self._worker, "requestInterruption"):
            self._worker.requestInterruption()
            if hasattr(self._worker, "wait"):
                self._worker.wait(300)
        self._emit_finished("user_close")
        super().closeEvent(event)

    def notify_finished(self, reason: str) -> None:
        self._emit_finished(reason)

    def _emit_finished(self, reason: str) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit(reason)

    def _update_state_label(self, status: StatusDTO) -> None:
        state_text = status.state_5class or "-"
        duration = status.duration_s if status.duration_s is not None else 0.0
        self._state_label.setText(f"State: {state_text}")
        self._duration_label.setText(f"Duration: {duration:.2f}s")
        if status.fps is None:
            self._fps_label.setText("Infer FPS: -")
        else:
            self._fps_label.setText(f"Infer FPS: {status.fps:.2f}")
        if status.target_ratio is not None:
            self._target_ratio_label.setText(f"Target Ratio: {status.target_ratio:.2f}x")

    def _update_people(self, status: StatusDTO) -> None:
        people_count = status.people_count
        people_alarm = bool(status.people_alarm)
        self._people_value.setText(str(people_count))
        color = "#FF4D4F" if people_alarm else "#20E3B2"
        self._people_value.setStyleSheet(f"color: {color};")

    def _derive_row_label(self, row_key: str, status: StatusDTO) -> str:
        current_state = status.state_5class
        tags_c = status.tags_c_set or set()
        tags_d = status.tags_d_set or set()
        if row_key == "hole":
            return "\u5173\u95ed" if current_state == "CLOSE" else "\u5f00\u542f"
        if row_key == "blocking":
            return "\u5c01\u5835\u4e2d" if "blocking" in tags_d else "-"
        if row_key == "no_blocking":
            return "\u672a\u5c01\u5835\u4e2d" if "no_blocking" in tags_d else "-"
        if row_key == "sampling_state":
            if "sampling" not in tags_c:
                return "-"
            if "blocking" in tags_d:
                return "\u6b63\u5728\u91c7\u6837"
            if "no_blocking" in tags_d:
                return "\u672a\u5c01\u5835\u91c7\u6837"
            return "\u91c7\u6837\u4e2d"
        return "-"

    def _update_status_table(self, status: StatusDTO) -> None:
        current_state = status.state_5class
        is_bad = current_state in ("OPEN_DANGER", "OPEN_VIOLATION")
        active_bg = QColor(74, 24, 32) if is_bad else QColor(18, 58, 42)
        indicator = QColor(255, 77, 79) if is_bad else QColor(32, 227, 178)
        video_t = status.video_t_s
        for row, (row_key, row_title) in enumerate(STATE_ROWS):
            label = self._derive_row_label(row_key, status)
            timer = self._row_timers.get(row_key)
            if timer is not None:
                prev_label = timer["label"]
                if label != prev_label:
                    if prev_label not in (None, "-") and video_t is not None and timer["start_t"] is not None:
                        timer["last_dur"] = max(0.0, video_t - timer["start_t"])
                    timer["label"] = label
                    if label != "-" and video_t is not None:
                        timer["start_t"] = video_t
                    else:
                        timer["start_t"] = None
            is_current = label != "-"

            title_item = self._table.item(row, 1)
            if title_item is not None:
                title_item.setText(row_title)

            judge_item = self._table.item(row, 2)
            time_item = self._table.item(row, 3)
            if judge_item is not None:
                judge_item.setText(label)
                if is_current:
                    judge_item.setForeground(QBrush(QColor(0, 229, 255)))
                    judge_item.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            if time_item is not None:
                if label == "-":
                    time_item.setText("-")
                elif video_t is None or (timer is not None and timer.get("start_t") is None):
                    time_item.setText("N/A")
                else:
                    start_t = timer.get("start_t") if timer is not None else None
                    time_item.setText(f"{max(0.0, video_t - start_t):.1f}" if start_t is not None else "N/A")
                if is_current:
                    time_item.setForeground(QBrush(QColor(0, 229, 255)))
                    time_item.setFont(QFont("Consolas", 10, QFont.Weight.Bold))

            if is_current:
                for col in range(self._table.columnCount()):
                    item = self._table.item(row, col)
                    if item is not None:
                        item.setBackground(active_bg)
                        if col == 0:
                            item.setForeground(QBrush(indicator))
            else:
                for col in range(self._table.columnCount()):
                    item = self._table.item(row, col)
                    if item is not None:
                        item.setBackground(QBrush(QColor(15, 27, 45)))
                        if col == 0:
                            item.setForeground(QBrush(QColor(120, 120, 120)))
