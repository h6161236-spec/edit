"""VCut Studio - SettingsActions (MainWindow mixin).

Extracted from ui/main_window.py to keep the window class focused on
composition and shared state. Methods reference `self` attributes that are
created in MainWindow.__init__ (pages, context, threads, busy flags).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, QUrl
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ...models import ExportJob, Project
from ...subtitles import SubtitleCueData, read_subtitle_file, write_subtitle_file
from ...providers.translation import TranslationRequest
from ...providers.tts import tts_provider_display_name, tts_provider_runtime_status
from ..dubbing_logic import apply_voice_to_segments, pick_voice_preview_text
from ..pages_formatting import format_voice_label
from ...asr import collect_asr_runtime_diagnostics
from ...settings import AppSettings


class SettingsActionsMixin:
    """SettingsActions actions for the main window."""

    def save_settings(self) -> None:
        if not self._require_idle_background("保存设置"):
            return
        previous_tts_signature = self._tts_cache_signature(self.context.settings)
        try:
            new_settings = self.settings_page.build_settings()
            settings_path = self.context.settings_store.save(new_settings)
        except Exception as exc:
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        self.context.settings = new_settings
        self._apply_workspace_style()
        self._configure_autosave_timer()
        if self._tts_cache_signature(new_settings) != previous_tts_signature:
            self._invalidate_all_dubs()
        self.refresh_views()
        self.statusBar().showMessage(f"已保存设置：{settings_path}", 5000)

    def reset_settings(self) -> None:
        if not self._require_idle_background("恢复默认设置"):
            return
        self.context.settings = AppSettings()
        self._apply_workspace_style()
        self._configure_autosave_timer()
        self._invalidate_all_dubs()
        self.settings_page.load_settings(self.context.settings)
        self.refresh_views()
        self.statusBar().showMessage("已将设置表单恢复为默认值。", 5000)

    def scan_dependencies(self) -> None:
        rows = self._dependency_rows()
        summary = "\n".join(f"{name}：{status} | {detail}" for name, status, detail in rows)
        QMessageBox.information(self, "依赖状态", summary)
        self.statusBar().showMessage("依赖扫描完成。", 5000)

    def show_settings_dialog(self) -> None:
        self.settings_page.load_settings(self.context.settings)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def show_export_dialog(self) -> None:
        self.export_page.load_project(self.context.current_project, self.context.settings)
        self._refresh_interactive_state()
        self.export_dialog.show()
        self.export_dialog.raise_()
        self.export_dialog.activateWindow()

    def show_asr_runtime_diagnostics(self) -> None:
        requested_device = str(
            self.settings_page.asr_device_combo.currentData() or self.settings_page.asr_device_combo.currentText()
        )
        diagnostics = collect_asr_runtime_diagnostics(requested_device)

        nvidia_text = "未安装或不可用"
        if diagnostics.nvidia_smi_available:
            nvidia_text = "；".join(diagnostics.nvidia_gpu_names) if diagnostics.nvidia_gpu_names else "可用，但未读取到显卡名称"

        if diagnostics.gpu_ready:
            recommendation = "GPU 环境可用，可以选择 CUDA 或自动。"
        elif diagnostics.cuda_device_count <= 0:
            recommendation = "当前未检测到可用 CUDA 设备，建议先使用 CPU。"
        elif diagnostics.missing_cuda_libraries:
            recommendation = (
                "检测到显卡，但缺少 CUDA 运行库："
                + ", ".join(diagnostics.missing_cuda_libraries)
                + "。当前建议使用 CPU，或安装对应 CUDA 12 / cuDNN 9 运行库。"
            )
        else:
            recommendation = "CUDA 环境状态未知，建议先用 CPU 做识别。"

        message = "\n".join(
            [
                f"当前设备设置：{diagnostics.requested_device}",
                f"模型缓存目录：{self.settings_page.asr_cache_dir_edit.text().strip() or '默认缓存目录'}",
                f"本地模型目录：{self.settings_page.asr_local_model_dir_edit.text().strip() or '未指定'}",
                f"仅本地加载：{'是' if self.settings_page.asr_local_files_only_checkbox.isChecked() else '否'}",
                f"faster-whisper：{diagnostics.faster_whisper_version}",
                f"ctranslate2：{diagnostics.ctranslate2_version}",
                f"nvidia-smi：{nvidia_text}",
                f"CUDA 设备数：{diagnostics.cuda_device_count}",
                "cuBLAS/cuDNN："
                + (
                    "已就绪"
                    if not diagnostics.missing_cuda_libraries
                    else "缺少 " + ", ".join(diagnostics.missing_cuda_libraries)
                ),
                "",
                recommendation,
            ]
        )
        QMessageBox.information(self, "GPU 环境检测", message)
        self.statusBar().showMessage("GPU 环境检测完成。", 5000)

    def browse_asr_cache_dir(self) -> None:
        initial_dir = (
            self.settings_page.asr_cache_dir_edit.text().strip()
            or self.context.settings.asr.model_cache_dir
            or self.context.settings.workspace.workspace_dir
        )
        directory = QFileDialog.getExistingDirectory(self, "选择 ASR 模型缓存目录", initial_dir)
        if directory:
            self.settings_page.asr_cache_dir_edit.setText(directory)

    def browse_asr_local_model_dir(self) -> None:
        initial_dir = (
            self.settings_page.asr_local_model_dir_edit.text().strip()
            or self.context.settings.asr.local_model_dir
            or self.context.settings.asr.model_cache_dir
            or self.context.settings.workspace.workspace_dir
        )
        directory = QFileDialog.getExistingDirectory(self, "选择本地 ASR 模型目录", initial_dir)
        if directory:
            self.settings_page.asr_local_model_dir_edit.setText(directory)

    def browse_export_output_dir(self) -> None:
        initial_dir = (
            self.export_page.output_dir_edit.text().strip()
            or self.context.settings.media.default_output_dir
            or self.context.settings.workspace.workspace_dir
        )
        directory = QFileDialog.getExistingDirectory(self, "选择导出目录", initial_dir)
        if directory:
            self.export_page.output_dir_edit.setText(directory)
