"""VCut Studio - ProjectActions (MainWindow mixin).

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
from ...media import MediaProbeError, probe_media


class ProjectActionsMixin:
    """ProjectActions actions for the main window."""

    def new_project(self) -> None:
        if not self._require_idle_background("新建项目"):
            return
        if not self._confirm_project_switch("新建项目"):
            return
        project = Project.new("未命名项目")
        project.analysis_completed = False
        self.context.set_project(project)
        self._clear_proofread_snapshot()
        self._clear_task_progress()
        self.refresh_views()
        self.statusBar().showMessage("已新建空白项目。", 5000)

    def import_video(self) -> None:
        if not self._require_idle_background("导入其他视频"):
            return
        if not self._confirm_project_switch("导入视频"):
            return
        workspace_dir = self.context.settings.workspace.workspace_dir
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "导入视频",
            workspace_dir,
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;所有文件 (*.*)",
        )
        if not filename:
            return

        self._set_task_progress(15, "正在探测视频信息...", pump_events=True)
        try:
            probe = probe_media(filename, self.context.settings.media.ffmpeg_path)
        except MediaProbeError as exc:
            self._clear_task_progress()
            QMessageBox.critical(self, "导入视频失败", str(exc))
            return

        project = self.context.current_project
        project.name = Path(filename).stem
        project.video_path = filename
        project.audio_path = ""
        project.source_duration_ms = probe.media_info.duration_ms
        project.analysis_completed = False
        project.media_info = probe.media_info
        project.segments.clear()
        project.cut_suggestions.clear()
        project.exports.clear()
        self._clear_proofread_snapshot()
        self._mark_project_dirty()
        self._set_task_progress(55, "正在准备视频监看预览...", pump_events=True)
        self._resolve_preview_source_path(project)
        self._set_task_progress(65, "正在载入视频监看和音轨...", pump_events=True)
        self.refresh_views()
        self._set_task_progress(100, "视频导入完成。", pump_events=True)
        self._clear_task_progress()
        self.timeline_page.setFocus()

        if not probe.media_info.has_audio:
            QMessageBox.warning(
                self,
                "导入视频不含音频",
                "所选视频似乎没有音频流。在你换成包含人声的媒体之前，ASR 很可能无法正常工作。",
            )
        self.statusBar().showMessage(
            f"已导入视频：{filename}（{probe.media_info.duration_ms / 1000:.2f}s）",
            6000,
        )

    def open_project(self) -> None:
        if not self._require_idle_background("打开其他项目"):
            return
        if not self._confirm_project_switch("打开其他项目"):
            return
        workspace_dir = self.context.settings.workspace.workspace_dir
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开项目",
            workspace_dir,
            "VCut Studio 项目 (*.vcutproj)",
        )
        if not filename:
            return
        try:
            project = self.context.project_store.load(filename)
        except Exception as exc:
            QMessageBox.critical(self, "打开项目失败", str(exc))
            return
        self.context.set_project(project, Path(filename))
        self._clear_proofread_snapshot()
        self.refresh_views()
        self.statusBar().showMessage(f"已打开项目：{filename}", 5000)

    def save_project(self) -> bool:
        if not self._require_idle_background("保存项目"):
            return False
        if self.context.current_project_path is None:
            return self.save_project_as()
        return self._save_project_to_path(self.context.current_project_path, "已保存项目")

    def save_project_as(self) -> bool:
        if not self._require_idle_background("保存项目"):
            return False
        workspace_dir = self.context.settings.workspace.workspace_dir
        suggested_path = self.context.project_store.default_path(workspace_dir, self.context.current_project.name)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "项目另存为",
            str(suggested_path),
            "VCut Studio 项目 (*.vcutproj)",
        )
        if not filename:
            return False
        if not filename.endswith(".vcutproj"):
            filename = f"{filename}.vcutproj"
        return self._save_project_to_path(filename, "已保存项目")

    def _save_project_to_path(self, target_path: str | Path, success_message: str) -> bool:
        try:
            saved_path = self.context.project_store.save(self.context.current_project, target_path)
        except Exception as exc:
            QMessageBox.critical(self, "保存项目失败", str(exc))
            return False
        self._mark_project_saved(saved_path)
        self.refresh_views()
        self.statusBar().showMessage(f"{success_message}：{saved_path}", 5000)
        return True

    def _confirm_project_switch(self, action_text: str) -> bool:
        if not self.context.project_dirty:
            return True
        reply = QMessageBox.question(
            self,
            "项目尚未保存",
            f"当前项目有未保存修改。{action_text}前要先保存吗？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def _configure_autosave_timer(self) -> None:
        interval_minutes = max(1, int(self.context.settings.workspace.auto_save_minutes or 1))
        self._autosave_timer.start(interval_minutes * 60 * 1000)

    def _update_window_title(self) -> None:
        project_name = self.context.current_project.name or "未命名项目"
        dirty_suffix = " *" if self.context.project_dirty else ""
        self.setWindowTitle(f"VCut Studio - {project_name}{dirty_suffix}")

    def _mark_project_dirty(self) -> None:
        self.context.mark_project_dirty()
        self._update_window_title()

    def _mark_project_saved(self, path: Path | None = None) -> None:
        self.context.mark_project_saved(path)
        self._update_window_title()

    def _auto_save_project_snapshot(
        self,
        *,
        status_message: str | None = None,
        error_title: str | None = None,
        allow_during_background: bool = False,
    ) -> Path | None:
        if (self._background_job_in_progress() and not allow_during_background) or not self.context.project_dirty:
            return None
        project = self.context.current_project
        target_path = self.context.current_project_path
        if target_path is None:
            target_path = self.context.project_store.autosave_path(
                self.context.settings.workspace.workspace_dir,
                project.name,
                project.project_id,
            )
        try:
            saved_path = self.context.project_store.save(project, target_path)
        except Exception as exc:
            if error_title:
                QMessageBox.critical(self, error_title, str(exc))
            return None
        if self.context.current_project_path is not None:
            self._mark_project_saved(saved_path)
        if status_message:
            self.statusBar().showMessage(f"{status_message}：{saved_path}", 5000)
        return saved_path

