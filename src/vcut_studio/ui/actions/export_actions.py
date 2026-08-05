"""VCut Studio - ExportActions (MainWindow mixin).

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
from ...settings import AppSettings
from ..workers import ExportResult, ExportWorker


class ExportActionsMixin:
    """ExportActions actions for the main window."""

    def start_export(self) -> None:
        if not self._require_idle_background("开始导出"):
            return

        project = self.context.current_project
        if not project.video_path:
            QMessageBox.information(
                self,
                "没有源视频",
                "请先导入源视频，再开始导出。",
            )
            return

        output_dir = self.export_page.output_dir_edit.text().strip() or self.context.settings.media.default_output_dir
        export_type = str(self.export_page.export_type_combo.currentData() or "clean_zh")
        subtitle_mode = str(self.export_page.subtitle_mode_combo.currentData() or "en")
        output_container = self.export_page.output_container_combo.currentText().strip() or "mp4"
        if self.context.project_dirty:
            snapshot_path = self._auto_save_project_snapshot(
                status_message="导出前已保存工程快照",
                error_title="导出前保存工程失败",
            )
            if snapshot_path is None:
                return
        self.context.settings.export.subtitle_mode = subtitle_mode
        job_settings = AppSettings.from_dict(self.context.settings.to_dict())
        if export_type in {"en_dub", "en_dub_subtitle"}:
            job_settings = self._build_dubbing_job_settings()

        worker = ExportWorker(
            project=project,
            settings=job_settings,
            export_type=export_type,
            output_dir=output_dir,
            output_container=output_container,
            burn_subtitles=self.export_page.burn_subtitles_checkbox.isChecked(),
            export_sidecar_srt=self.export_page.sidecar_srt_checkbox.isChecked(),
            subtitle_mode=subtitle_mode,
        )
        self._start_background_job(
            worker,
            thread_attr="export_thread",
            worker_attr="export_worker",
            cleanup=self._cleanup_export_job,
            status_message="已加入导出队列...",
            progress=self._on_export_progress,
            finished=self._on_export_finished,
            cancelled=self._on_export_cancelled,
            error=self._on_export_error,
        )
        self.export_busy = True

    def _export_in_progress(self) -> bool:
        return self.export_busy

    def _on_export_progress(self, progress: int, message: str) -> None:
        self.statusBar().showMessage(message, 0)
        self.export_page.set_export_progress(progress, message)
        self._set_task_progress(progress, message)

    def _on_export_finished(self, result: ExportResult) -> None:
        self.export_busy = False
        self._set_active_background_worker(None)
        self.context.current_project.exports.append(
            ExportJob(
                export_id=uuid4().hex,
                export_type=result.export_type,
                output_path=str(result.plan.output_path),
                status="completed",
            )
        )
        self._mark_project_dirty()
        self._refresh_interactive_state()
        self.refresh_views()
        self.export_page.export_button.setFocus()
        self._clear_task_progress()
        QMessageBox.information(
            self,
            "导出完成",
            f"视频已经导出完成。\n\n输出文件：\n{result.plan.output_path}",
        )
        self.statusBar().showMessage(
            f"导出完成：{result.plan.output_path}",
            10000,
        )

    def _on_export_error(self, message: str) -> None:
        self.export_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        QMessageBox.critical(self, "导出失败", message)
        self.statusBar().showMessage("导出失败。", 8000)

    def _on_export_cancelled(self, message: str) -> None:
        self.export_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        self.statusBar().showMessage(message or "已终止导出任务。", 8000)

    def _cleanup_export_job(self) -> None:
        self.export_thread = None
        self.export_worker = None

