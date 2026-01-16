from __future__ import annotations

import json
import os
import shutil
import sys
import time
from typing import Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMessageBox,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QCheckBox,
    QProgressBar,
    QComboBox,
)

from src.app_qt import create_detector_window
from src.core.device import resolve_device
from src.core.paths import get_best_dir
from src.export_runner import ExportRunner
from src.launcher_settings import LauncherSettings, load_settings_with_meta, save_settings
from src.report.export_core import (
    default_output_root,
    ensure_outdir,
    get_total_frames,
    next_reports_dir,
    report_data_dir,
)


def _debug_text(tag: str, text: str) -> None:
    preview = text[:20]
    print(f"[TEXT] {tag} type={type(text)} repr={repr(text)} preview={preview!r}")


def _set_text(widget, text: str, tag: str) -> None:
    _debug_text(tag, text)
    widget.setText(text)


def _add_combo_items(combo: QComboBox, items: list[str], tag: str) -> None:
    for item in items:
        _debug_text(f"{tag}.item", item)
        combo.addItem(item)


class HomePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.settings_btn = QPushButton()
        _set_text(self.settings_btn, "设置/适配", "Home.settings_btn")
        self.refresh_btn = QPushButton()
        _set_text(self.refresh_btn, "重新检测", "Home.refresh_btn")

        top_layout.addStretch(1)
        top_layout.addWidget(self.settings_btn)
        top_layout.addWidget(self.refresh_btn)

        self.status_label = QLabel()
        _set_text(self.status_label, "模型状态：检测中...", "Home.status_label")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        device_row = QWidget()
        device_layout = QHBoxLayout(device_row)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(8)

        self.device_label = QLabel()
        _set_text(self.device_label, "设备选择：", "Home.device_label")
        self.device_combo = QComboBox()
        _add_combo_items(self.device_combo, ["auto", "cpu", "gpu"], "Home.device_combo")

        self.device_status = QLabel()
        _set_text(self.device_status, "CUDA：- | 最终使用：-", "Home.device_status")
        self.device_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.device_info = QLabel()
        _set_text(self.device_info, "GPU?- | Torch?-", "Home.device_info")
        self.device_info.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.config_summary = QLabel()
        _set_text(self.config_summary, "当前配置：-", "Home.config_summary")
        self.config_summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        device_layout.addWidget(self.device_label)
        device_layout.addWidget(self.device_combo)
        device_layout.addStretch(1)

        self.realtime_btn = QPushButton()
        _set_text(self.realtime_btn, "实时检测", "Home.realtime_btn")
        self.report_btn = QPushButton()
        _set_text(self.report_btn, "报告导出", "Home.report_btn")

        layout.addWidget(top_row)
        layout.addWidget(self.status_label)
        layout.addWidget(device_row)
        layout.addWidget(self.device_status)
        layout.addWidget(self.device_info)
        layout.addWidget(self.config_summary)
        layout.addWidget(self.realtime_btn)
        layout.addWidget(self.report_btn)

    def set_ready(self, ready: bool) -> None:
        if ready:
            _set_text(self.status_label, "模型已就绪", "Home.status_label")
        else:
            _set_text(self.status_label, "模型缺失", "Home.status_label")
        self.realtime_btn.setEnabled(ready)
        self.report_btn.setEnabled(ready)


class VideoPickerPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.path_label = QLabel()
        _set_text(self.path_label, "未选择视频", "Picker.path_label")
        self.path_label.setWordWrap(True)
        self.pick_btn = QPushButton()
        _set_text(self.pick_btn, "选择视频", "Picker.pick_btn")
        self.start_btn = QPushButton()
        _set_text(self.start_btn, "开始", "Picker.start_btn")
        self.start_btn.setEnabled(False)
        self.back_btn = QPushButton()
        _set_text(self.back_btn, "返回", "Picker.back_btn")

        layout.addWidget(self.path_label)
        layout.addWidget(self.pick_btn)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.back_btn)

    def set_path(self, path: Optional[str]) -> None:
        if path:
            _set_text(self.path_label, path, "Picker.path_label")
            self.start_btn.setEnabled(True)
        else:
            _set_text(self.path_label, "未选择视频", "Picker.path_label")
            self.start_btn.setEnabled(False)


class ExportConfirmPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.video_label = QLabel("")
        self.video_label.setWordWrap(True)
        self.overlay_check = QCheckBox()
        _set_text(self.overlay_check, "导出 overlay mp4", "ExportConfirm.overlay_check")
        self.overlay_check.setChecked(True)
        self.pdf_check = QCheckBox()
        _set_text(self.pdf_check, "导出 PDF（Word→PDF）", "ExportConfirm.pdf_check")
        self.pdf_check.setChecked(False)
        self.pdf_hint = QLabel()
        _set_text(self.pdf_hint, "", "ExportConfirm.pdf_hint")
        self.pdf_hint.setWordWrap(True)
        self.outputs_label = QLabel("")
        self.outputs_label.setWordWrap(True)
        self.device_label = QLabel()
        _set_text(self.device_label, "使用设备：-", "ExportConfirm.device")
        self.estimate_label = QLabel()
        _set_text(self.estimate_label, "预计总耗时：--", "ExportConfirm.estimate")
        self.remaining_label = QLabel()
        _set_text(self.remaining_label, "预计剩余：--", "ExportConfirm.remaining")
        self.start_btn = QPushButton()
        _set_text(self.start_btn, "确认开始导出", "ExportConfirm.start")
        self.start_btn.setEnabled(True)

        layout.addWidget(self.video_label)
        layout.addWidget(self.overlay_check)
        layout.addWidget(self.pdf_check)
        layout.addWidget(self.pdf_hint)
        layout.addWidget(self.outputs_label)
        layout.addWidget(self.device_label)
        layout.addWidget(self.estimate_label)
        layout.addWidget(self.remaining_label)
        layout.addWidget(self.start_btn)

    def update_video(self, path: str) -> None:
        _set_text(self.video_label, f"输入视频：{path}", "ExportConfirm.video")

    def update_outputs(self, reports_dir: str) -> None:
        _set_text(self.outputs_label, f"输出目录：{reports_dir}", "ExportConfirm.outputs")

    def update_device(self, resolved_device: str) -> None:
        _set_text(self.device_label, f"使用设备：{resolved_device}", "ExportConfirm.device")

    def update_estimate(self, total_text: str) -> None:
        _set_text(self.estimate_label, f"预计总耗时：{total_text}", "ExportConfirm.estimate")
        _set_text(self.remaining_label, "预计剩余：--", "ExportConfirm.remaining")


    def set_pdf_enabled(self, enabled: bool, reason: str = "") -> None:
        self.pdf_check.setEnabled(enabled)
        if not enabled:
            self.pdf_check.setChecked(False)
        if enabled:
            _set_text(self.pdf_hint, "", "ExportConfirm.pdf_hint")
        else:
            if not reason:
                reason = "PDF disabled: install Microsoft Word (docx2pdf) or LibreOffice."
            _set_text(self.pdf_hint, reason, "ExportConfirm.pdf_hint")

class SettingsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel()
        _set_text(title, "设置/适配", "Settings.title")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        self.back_btn = QPushButton()
        _set_text(self.back_btn, "返回", "Settings.back_btn")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.back_btn)

        self.device_combo = QComboBox()
        _add_combo_items(self.device_combo, ["auto", "cpu", "gpu"], "Settings.device_combo")
        self.device_hint = QLabel()
        _set_text(self.device_hint, "设备选择：Auto / GPU / CPU", "Settings.device_hint")
        self.realtime_combo = QComboBox()
        _add_combo_items(self.realtime_combo, ["Balanced", "Quality"], "Settings.realtime_combo")
        self.offline_combo = QComboBox()
        _add_combo_items(self.offline_combo, ["High"], "Settings.offline_combo")
        self.estimate_hint = QLabel()
        _set_text(self.estimate_hint, "估时说明：按设备分桶 fps + PDF 固定加时", "Settings.estimate_hint")
        self.save_btn = QPushButton()
        _set_text(self.save_btn, "保存设置", "Settings.save_btn")

        realtime_label = QLabel()
        _set_text(realtime_label, "运行模式默认值（实时检测）", "Settings.realtime_label")
        device_label = QLabel()
        _set_text(device_label, "设备选择", "Settings.device_label")
        offline_label = QLabel()
        _set_text(offline_label, "离线质量档", "Settings.offline_label")
        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 8, 0, 0)
        save_layout.addStretch(1)
        save_layout.addWidget(self.save_btn)

        layout.addWidget(header_row)
        layout.addSpacing(8)
        layout.addWidget(realtime_label)
        layout.addWidget(self.realtime_combo)
        layout.addSpacing(4)
        layout.addWidget(device_label)
        layout.addWidget(self.device_combo)
        layout.addWidget(self.device_hint)
        layout.addSpacing(4)
        layout.addWidget(offline_label)
        layout.addWidget(self.offline_combo)
        layout.addWidget(self.estimate_hint)
        layout.addStretch(1)
        layout.addWidget(save_row)


class ExportProgressPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.status_label = QLabel()
        _set_text(self.status_label, "导出中...", "ExportProgress.status")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.detail_label = QLabel()
        _set_text(self.detail_label, "frame 0/? | fps -- | ETA --", "ExportProgress.detail")
        self.elapsed_label = QLabel()
        _set_text(self.elapsed_label, "已耗时：00:00:00", "ExportProgress.elapsed")
        self.reports_label = QLabel("")
        self.reports_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.reports_label)

    def set_reports_dir(self, reports_dir: str) -> None:
        _set_text(self.reports_label, f"输出目录：{reports_dir}", "ExportProgress.reports")


class RealtimePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.focus_btn = QPushButton()
        _set_text(self.focus_btn, "切到检测窗口", "Realtime.focus_btn")
        self.close_btn = QPushButton()
        _set_text(self.close_btn, "关闭检测窗口", "Realtime.close_btn")
        self.back_btn = QPushButton()
        _set_text(self.back_btn, "返回", "Realtime.back_btn")
        layout.addWidget(self.path_label)
        layout.addWidget(self.focus_btn)
        layout.addWidget(self.close_btn)
        layout.addWidget(self.back_btn)

    def set_path(self, path: str) -> None:
        _set_text(self.path_label, f"当前视频：{path}", "Realtime.path")


class LauncherWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Launcher")
        self._selected_video: Optional[str] = None
        self._detector_window = None
        self._mode: str = "realtime"
        self._export_runner: Optional[ExportRunner] = None
        self._export_start_t: Optional[float] = None
        self._export_dirs: Optional[Tuple[str, str, str]] = None
        self._device_mode: str = "auto"
        self._resolved_device: str = "cpu"
        self._cuda_available: Optional[bool] = None
        self._cuda_reason: str = ""
        outputs_root = default_output_root()
        self._settings, downgraded = load_settings_with_meta(outputs_root)

        print(f"settings file encoding check ok: {repr('离线质量档')}")

        if downgraded:
            self._settings.offline_quality = "High"
            log_path = os.path.join(outputs_root, "export.log")
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{ts}] settings_downgrade: Ultra -> High\n")
            except OSError:
                pass

        self._stack = QStackedWidget()
        self._home = HomePage()
        self._picker = VideoPickerPage()
        self._realtime = RealtimePage()
        self._export_confirm = ExportConfirmPage()
        self._export_progress = ExportProgressPage()
        self._settings_page = SettingsPage()

        self._stack.addWidget(self._home)
        self._stack.addWidget(self._picker)
        self._stack.addWidget(self._realtime)
        self._stack.addWidget(self._export_confirm)
        self._stack.addWidget(self._export_progress)
        self._stack.addWidget(self._settings_page)
        self.setCentralWidget(self._stack)

        self._home.realtime_btn.clicked.connect(self._go_picker_realtime)
        self._home.report_btn.clicked.connect(self._go_picker_export)
        self._home.settings_btn.clicked.connect(self._go_settings)
        self._home.refresh_btn.clicked.connect(self._refresh_model_status)
        self._home.device_combo.currentTextChanged.connect(self._on_device_mode_changed)
        self._picker.pick_btn.clicked.connect(self._pick_video)
        self._picker.start_btn.clicked.connect(self._start_realtime)
        self._picker.back_btn.clicked.connect(self._go_home)
        self._realtime.focus_btn.clicked.connect(self._focus_detector)
        self._realtime.close_btn.clicked.connect(self._close_detector)
        self._realtime.back_btn.clicked.connect(self._return_from_realtime)
        self._export_confirm.overlay_check.stateChanged.connect(self._update_confirm_state)
        self._export_confirm.pdf_check.stateChanged.connect(self._update_confirm_state)
        self._export_confirm.start_btn.clicked.connect(self._start_export)
        self._settings_page.save_btn.clicked.connect(self._save_settings)
        self._settings_page.back_btn.clicked.connect(self._go_home)

        self._apply_settings()
        self._refresh_model_status()
        self._update_device_status()
        if downgraded:
            QMessageBox.information(self, "提示", "当前版本不提供 Ultra，已降级为 High。")

    def _refresh_model_status(self) -> None:
        best_dir = get_best_dir()
        ready = os.path.isdir(best_dir) and any(os.scandir(best_dir))
        self._home.set_ready(ready)

    def _apply_settings(self) -> None:
        self._device_mode = self._settings.device_mode
        self._home.device_combo.setCurrentText(self._device_mode)
        self._settings_page.device_combo.setCurrentText(self._device_mode)
        self._settings_page.offline_combo.setCurrentText("High")
        self._settings_page.realtime_combo.setCurrentText(self._settings.realtime_mode)
        _set_text(
            self._home.config_summary,
            f"当前配置：设备 {self._device_mode} / 离线 {self._settings.offline_quality}",
            "Home.config_summary",
        )

    def _update_settings_ui(self) -> None:
        cuda_ok = self._cuda_available
        gpu_index = self._settings_page.device_combo.findText("gpu")
        if gpu_index >= 0:
            model = self._settings_page.device_combo.model()
            item = model.item(gpu_index)
            if item is not None:
                item.setEnabled(bool(cuda_ok))
        hint = "CUDA 不可用，GPU 已禁用" if not cuda_ok else "CUDA 可用"
        _set_text(self._settings_page.device_hint, hint, "Settings.device_hint")

    def _go_home(self) -> None:
        self._stack.setCurrentWidget(self._home)
        self._refresh_model_status()
        self._update_device_status()

    def _go_picker(self) -> None:
        self._stack.setCurrentWidget(self._picker)

    def _go_picker_realtime(self) -> None:
        self._mode = "realtime"
        self._go_picker()

    def _go_picker_export(self) -> None:
        self._mode = "export"
        self._go_picker()

    def _go_settings(self) -> None:
        self._stack.setCurrentWidget(self._settings_page)
        self._update_settings_ui()

    def _go_realtime(self, path: str) -> None:
        self._realtime.set_path(path)
        self._stack.setCurrentWidget(self._realtime)

    def _pick_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频",
            "",
            "Video files (*.mp4 *.avi);;All files (*.*)",
        )
        self._selected_video = path or None
        self._picker.set_path(self._selected_video)

    def _on_device_mode_changed(self, mode: str) -> None:
        self._device_mode = mode
        self._settings.device_mode = mode
        self._settings_page.device_combo.setCurrentText(mode)
        self._update_device_status()

    def _update_device_status(self) -> None:
        resolved, cuda_ok, reason = resolve_device(self._device_mode)
        self._resolved_device = resolved
        self._cuda_available = cuda_ok
        self._cuda_reason = reason
        status = "可用" if cuda_ok else "不可用"
        final_text = "GPU" if resolved == "cuda" else "CPU"
        _set_text(self._home.device_status, f"CUDA：{status} | 最终使用：{final_text}", "Home.device_status")
        _set_text(self._home.device_info, self._build_gpu_info(cuda_ok), "Home.device_info")
        auto_tier = self._auto_tier_text()
        _set_text(
            self._home.config_summary,
            f"当前配置：设备 {self._device_mode} / 离线 {self._settings.offline_quality} | Auto 档位：{auto_tier}",
            "Home.config_summary",
        )

    def _build_gpu_info(self, cuda_ok: bool) -> str:
        try:
            import torch
        except Exception:
            return "GPU 不可用 | Torch 缺失"
        if not cuda_ok:
            return f"GPU 不可用 | Torch {torch.__version__}"
        try:
            name = torch.cuda.get_device_name(0)
            total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return f"GPU {name} ({total_gb:.1f}GB) | Torch {torch.__version__}"
        except Exception:
            return f"GPU 读取失败 | Torch {torch.__version__}"

    def _auto_tier_text(self) -> str:
        if self._device_mode != "auto":
            return "-"
        outputs_root = default_output_root()
        fps = self._load_last_export_fps(outputs_root, self._resolved_device)
        if fps is None:
            return "Med(默认)"
        if fps >= 12.0:
            return "High(>=12fps)"
        if fps >= 8.0:
            return "Med(>=8fps)"
        return "Low(<8fps)"

    def _resolve_device_for_run(self) -> str:
        resolved, cuda_ok, reason = resolve_device(self._device_mode)
        self._resolved_device = resolved
        self._cuda_available = cuda_ok
        self._cuda_reason = reason
        if self._device_mode == "gpu" and not cuda_ok:
            QMessageBox.warning(self, "CUDA 不可用", "CUDA 不可用，将回退 CPU。")
        return resolved

    def _start_realtime(self) -> None:
        if not self._selected_video:
            QMessageBox.warning(self, "提示", "请先选择视频。")
            return
        if self._mode == "export":
            self._go_export_confirm(self._selected_video)
            return
        self._go_realtime(self._selected_video)
        device = self._resolve_device_for_run()
        self._open_detector_window(self._selected_video, device=device)

    def _open_detector_window(self, path: str, device: Optional[str] = None) -> None:
        if self._detector_window is not None:
            self._detector_window.close()
            self._detector_window = None
        try:
            win = create_detector_window(path, device=device)
        except Exception as exc:
            QMessageBox.critical(self, "错误", str(exc))
            self._go_home()
            return
        win.finished.connect(self._on_detector_finished)
        win.show()
        self._detector_window = win

    def _focus_detector(self) -> None:
        if self._detector_window is None:
            return
        self._detector_window.raise_()
        self._detector_window.activateWindow()

    def _close_detector(self) -> None:
        if self._detector_window is None:
            self._go_home()
            return
        self._detector_window.close()
        self._detector_window = None
        self._go_home()

    def _return_from_realtime(self) -> None:
        if self._detector_window is not None:
            self._detector_window.close()
            self._detector_window = None
        self._go_home()

    def _on_detector_finished(self, reason: str) -> None:
        self._detector_window = None
        if reason == "eof":
            box = QMessageBox(self)
            box.setWindowTitle("播放完成")
            box.setText("已播放到视频末尾。")
            home_btn = QPushButton("返回主页")
            repick_btn = QPushButton("重新选择视频")
            box.addButton(home_btn, QMessageBox.ButtonRole.AcceptRole)
            box.addButton(repick_btn, QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == repick_btn:
                self._go_picker()
            else:
                self._go_home()
        elif reason == "user_close":
            self._go_home()
        else:
            QMessageBox.critical(self, "错误", "播放异常退出。")
            self._go_home()

    def _prepare_export_dirs(self) -> Tuple[str, str, str]:
        outputs_root = default_output_root()
        reports_dir = next_reports_dir(outputs_root)
        report_dir = report_data_dir(reports_dir)
        ensure_outdir(outputs_root)
        ensure_outdir(reports_dir)
        ensure_outdir(report_dir)
        return outputs_root, reports_dir, report_dir

    def _go_export_confirm(self, path: str) -> None:
        self._selected_video = path
        if self._export_dirs is None:
            self._export_dirs = self._prepare_export_dirs()
        _, reports_dir, _ = self._export_dirs
        self._export_confirm.update_video(path)
        self._export_confirm.update_outputs(reports_dir)
        device = self._resolve_device_for_run()
        self._export_confirm.update_device(device)
        pdf_ok, pdf_reason = self._detect_pdf_support()
        self._export_confirm.set_pdf_enabled(pdf_ok, pdf_reason)
        self._update_confirm_estimate()
        self._stack.setCurrentWidget(self._export_confirm)
        self._update_confirm_state()

    def _load_last_export_fps(self, outputs_root: str, resolved_device: str) -> Optional[float]:
        stats_path = os.path.join(outputs_root, "export_stats.json")
        try:
            if not os.path.exists(stats_path) or os.path.getsize(stats_path) == 0:
                return None
            with open(stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = "last_export_fps_gpu" if resolved_device == "cuda" else "last_export_fps_cpu"
            value = data.get(key)
            return float(value) if value else None
        except Exception:
            return None

    def _format_minutes_range(self, low_s: float, high_s: float) -> str:
        low_m = max(0.0, low_s / 60.0)
        high_m = max(0.0, high_s / 60.0)
        return f"约 {low_m:.1f}-{high_m:.1f} 分钟"

    def _update_confirm_estimate(self) -> None:
        if not self._export_dirs or not self._selected_video:
            self._export_confirm.update_estimate("--")
            return
        outputs_root, _, _ = self._export_dirs
        total_frames = get_total_frames(self._selected_video)
        if total_frames <= 0:
            self._export_confirm.update_estimate("--")
            return
        resolved = self._resolved_device
        last_fps = self._load_last_export_fps(outputs_root, resolved)
        if last_fps is None or last_fps <= 0:
            if resolved == "cuda":
                fps_low, fps_high = 12.0, 20.0
            else:
                fps_low, fps_high = 6.0, 10.0
        else:
            fps_low = last_fps * 0.7
            fps_high = last_fps * 1.3
        base_low = total_frames / max(fps_high, 1e-6)
        base_high = total_frames / max(fps_low, 1e-6)
        if self._export_confirm.pdf_check.isChecked():
            base_low += 10.0
            base_high += 30.0
        self._export_confirm.update_estimate(self._format_minutes_range(base_low, base_high))

    def _detect_pdf_support(self) -> Tuple[bool, str]:
        try:
            import docx2pdf  # noqa: F401
            return True, ""
        except Exception:
            pass
        soffice = shutil.which("soffice") or shutil.which("soffice.exe")
        if soffice:
            return True, ""
        reason = "PDF disabled: install Microsoft Word (docx2pdf) or LibreOffice."
        return False, reason

    def _update_confirm_state(self) -> None:
        any_checked = self._export_confirm.overlay_check.isChecked() or self._export_confirm.pdf_check.isChecked()
        self._export_confirm.start_btn.setEnabled(any_checked)
        self._update_confirm_estimate()

    def _start_export(self) -> None:
        if not self._selected_video or not self._export_dirs:
            QMessageBox.warning(self, "提示", "请先选择视频。")
            return
        if not (
            self._export_confirm.overlay_check.isChecked() or self._export_confirm.pdf_check.isChecked()
        ):
            QMessageBox.warning(self, "提示", "请至少选择一种导出项。")
            return
        outputs_root, reports_dir, report_dir = self._export_dirs
        self._export_progress.set_reports_dir(reports_dir)
        self._stack.setCurrentWidget(self._export_progress)
        self._export_start_t = time.perf_counter()

        from src.cli.report_gen import _build_parser, _ensure_runtime_defaults

        parser = _build_parser()
        args = parser.parse_args(["--source", self._selected_video])
        _ensure_runtime_defaults(args)

        resolved_device = self._resolve_device_for_run()
        args.device = resolved_device
        setattr(args, "device_mode", self._device_mode)
        setattr(args, "cuda_available", self._cuda_available)
        setattr(args, "cuda_reason", self._cuda_reason)
        args.export_video = self._export_confirm.overlay_check.isChecked()
        export_pdf = self._export_confirm.pdf_check.isChecked()
        export_docx = True

        log_path = os.path.join(outputs_root, "export.log")
        self._export_runner = ExportRunner(
            args,
            outputs_root=outputs_root,
            reports_dir=reports_dir,
            report_dir=report_dir,
            export_overlay=args.export_video,
            export_pdf=export_pdf,
            export_docx=export_docx,
            log_path=log_path,
        )
        self._export_runner.progress.connect(self._on_export_progress)
        self._export_runner.completed.connect(self._on_export_completed)
        self._export_runner.failed.connect(self._on_export_failed)
        self._export_runner.start()

    def _format_elapsed(self) -> str:
        if self._export_start_t is None:
            return "00:00:00"
        elapsed = int(time.perf_counter() - self._export_start_t)
        mm, ss = divmod(elapsed, 60)
        hh, mm = divmod(mm, 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def _on_export_progress(self, done: int, total: int, fps: float, eta: Optional[float], stage: str) -> None:
        if stage == "pdf":
            self._export_progress.progress_bar.setRange(0, 0)
            _set_text(self._export_progress.status_label, "正在生成 PDF...", "ExportProgress.status")
            _set_text(self._export_progress.detail_label, "ETA --", "ExportProgress.detail")
        else:
            if total > 0:
                self._export_progress.progress_bar.setRange(0, total)
                self._export_progress.progress_bar.setValue(done)
                pct = (done / total) * 100.0
                eta_text = "--" if eta is None else self._format_eta(eta)
                _set_text(
                    self._export_progress.detail_label,
                    f"frame {done}/{total} | {fps:.2f} fps | ETA {eta_text} | {pct:.1f}%",
                    "ExportProgress.detail",
                )
            else:
                self._export_progress.progress_bar.setRange(0, 0)
                _set_text(
                    self._export_progress.detail_label,
                    f"frame {done}/? | {fps:.2f} fps | ETA --",
                    "ExportProgress.detail",
                )
        _set_text(self._export_progress.elapsed_label, f"已耗时：{self._format_elapsed()}", "ExportProgress.elapsed")

    def _format_eta(self, eta: float) -> str:
        eta = max(0, int(eta))
        mm, ss = divmod(eta, 60)
        hh, mm = divmod(mm, 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def _on_export_completed(self, info: dict) -> None:
        reports_dir = info.get("reports_dir") or (self._export_dirs[1] if self._export_dirs else "")
        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setText("导出完成。是否打开输出文件夹？")
        open_btn = QPushButton("打开输出文件夹")
        home_btn = QPushButton("返回主页")
        box.addButton(open_btn, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(home_btn, QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == open_btn:
            os.startfile(reports_dir)
        self._export_runner = None
        self._export_dirs = None
        self._go_home()

    def _on_export_failed(self, error_msg: str, log_path: str) -> None:
        QMessageBox.critical(self, "导出失败", f"{error_msg}\n日志：{log_path}")
        self._export_runner = None
        self._export_dirs = None
        self._go_home()

    def _save_settings(self) -> None:
        self._settings.device_mode = self._settings_page.device_combo.currentText()
        self._settings.offline_quality = "High"
        self._settings.realtime_mode = self._settings_page.realtime_combo.currentText()
        save_settings(self._settings, default_output_root())
        self._apply_settings()
        self._go_home()

    def closeEvent(self, event) -> None:
        if self._export_runner is not None and self._export_runner.isRunning():
            reply = QMessageBox.question(
                self,
                "导出进行中",
                "导出进行中，确认退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self._export_dirs:
                outputs_root = self._export_dirs[0]
                log_path = os.path.join(outputs_root, "export.log")
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        ts = time.strftime("%Y-%m-%d %H:%M:%S")
                        f.write(f"[{ts}] aborted_by_user\n")
                except OSError:
                    pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    families = set(QFontDatabase.families())
    for name in ("Microsoft YaHei", "SimSun", "PingFang SC", "Noto Sans CJK SC"):
        if name in families:
            app.setFont(QFont(name))
            break
    window = LauncherWindow()
    window.resize(720, 520)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
