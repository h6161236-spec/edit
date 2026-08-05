"""VCut Studio - DubbingActions (MainWindow mixin).

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
from ..workers import DubbingJobResult, DubbingWorker, VoicePreviewResult, VoicePreviewWorker

try:  # pragma: no cover - Windows-only runtime path
    import winsound
except ImportError:  # pragma: no cover - non-Windows runtime path
    winsound = None


class DubbingActionsMixin:
    """DubbingActions actions for the main window."""

    def generate_selected_dubs(self) -> None:
        if not self._require_idle_background("生成配音"):
            return
        selected_rows = self._active_dubbing_rows()
        if not selected_rows:
            QMessageBox.information(
                self,
                "没有选中配音行",
                "请先勾选片段，或先在配音表中选中一行或多行。",
            )
            return

        active_rows: list[int] = []
        for row_index in selected_rows:
            if 0 <= row_index < len(self.context.current_project.segments):
                segment = self.context.current_project.segments[row_index]
                if segment.en_text.strip():
                    active_rows.append(row_index)
        if not active_rows:
            QMessageBox.information(
                self,
                "没有可生成内容",
                "所选片段中没有可用于配音的英文文本。",
            )
            return

        selected_voice = self.dubbing_page.current_voice_id()
        if not selected_voice:
            QMessageBox.information(
                self,
                "没有可用音色",
                "当前没有选中的英文音色。",
            )
            return

        # The dubbing worker records the actual voice used on each segment, so
        # generating implicitly re-applies the currently selected voice. When
        # some segments were previously assigned a different voice, ask first
        # instead of silently overriding the user's earlier choice.
        mismatched_rows = [
            row_index
            for row_index in active_rows
            if str(getattr(self.context.current_project.segments[row_index], "voice_id", None) or "").strip()
            and str(self.context.current_project.segments[row_index].voice_id).strip() != selected_voice
        ]
        apply_voice = True
        if mismatched_rows:
            voice_label = format_voice_label(selected_voice)
            answer = QMessageBox.question(
                self,
                "音色确认",
                f"有 {len(mismatched_rows)} 个片段已指定其他音色。\n\n"
                f"是否统一改用当前音色“{voice_label}”生成配音？\n"
                "选择“否”将保留这些片段原有的音色生成。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            apply_voice = answer == QMessageBox.StandardButton.Yes

        updated_voice_count = 0
        if apply_voice:
            updated_voice_count = apply_voice_to_segments(
                self.context.current_project.segments,
                active_rows,
                selected_voice,
                invalidate_segment_dub=None,
            )
            if updated_voice_count:
                self._mark_project_dirty()

        self._active_dubbing_previous_statuses = {
            row_index: self.context.current_project.segments[row_index].tts_status
            for row_index in active_rows
        }
        selected_rate = self.dubbing_page.rate_spin.value()
        job_settings = self._build_dubbing_job_settings(
            selected_voice=selected_voice,
            rate=selected_rate,
        )
        for row_index in active_rows:
            self.context.current_project.segments[row_index].tts_status = "generating"
        self.refresh_views()

        worker = DubbingWorker(
            project=self.context.current_project,
            settings=job_settings,
            row_indices=active_rows,
        )
        self._start_background_job(
            worker,
            thread_attr="dubbing_thread",
            worker_attr="dubbing_worker",
            cleanup=self._cleanup_dubbing_job,
            status_message=(
                "已加入配音生成队列..."
                if not apply_voice
                else "已自动应用当前音色，并加入配音生成队列..."
            ),
            progress=self._on_dubbing_progress,
            finished=self._on_dubbing_finished,
            cancelled=self._on_dubbing_cancelled,
            error=self._on_dubbing_error,
        )
        self.dubbing_busy = True

    def preview_selected_voice(self) -> None:
        if not self._require_idle_background("试听音色"):
            return
        voice_id = self.dubbing_page.current_voice_id()
        if not voice_id:
            QMessageBox.information(
                self,
                "没有可用音色",
                "当前没有选中的英文音色。",
            )
            return

        try:
            preview_text, preview_source_message = pick_voice_preview_text(
                self.context.current_project.segments,
                self.dubbing_page.selected_rows(),
                self.context.settings.tts.preview_text,
            )
        except ValueError as exc:
            QMessageBox.information(self, "没有可试听文本", str(exc))
            return

        self._pending_preview_source_message = preview_source_message
        worker = VoicePreviewWorker(
            settings=self._build_dubbing_job_settings(),
            voice_id=voice_id,
            preview_text=preview_text,
        )
        self._start_background_job(
            worker,
            thread_attr="dubbing_thread",
            worker_attr="dubbing_worker",
            cleanup=self._cleanup_dubbing_job,
            status_message=f"{preview_source_message} 已加入音色试听队列...",
            progress=self._on_dubbing_progress,
            finished=self._on_dubbing_preview_ready,
            cancelled=self._on_dubbing_cancelled,
            error=self._on_dubbing_error,
        )
        self.dubbing_busy = True

    def stop_dub_playback(self) -> None:
        if winsound is None:
            QMessageBox.information(
                self,
                "当前环境不支持播放",
                "当前系统环境不支持内置音频播放。",
            )
            return
        self._stop_audio_playback()
        self.statusBar().showMessage("已停止当前音频播放。", 4000)

    def play_generated_dub(self, row: int) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        if not (0 <= row < len(self.context.current_project.segments)):
            return
        segment = self.context.current_project.segments[row]
        audio_path = str(segment.dub_audio_path or "").strip()
        if not audio_path:
            QMessageBox.information(
                self,
                "没有已生成配音",
                "请先为该片段生成配音，再进行试听。",
            )
            return
        if not Path(audio_path).exists():
            QMessageBox.warning(
                self,
                "配音文件不存在",
                "记录中的配音文件已经不存在，将把该片段状态重置为待处理。",
            )
            self._invalidate_segment_dub(segment)
            self.refresh_views()
            return
        self._play_audio_file(audio_path)
        self.statusBar().showMessage(f"正在播放第 {row + 1} 个片段的配音。", 5000)

    def _active_dubbing_rows(self) -> list[int]:
        checked_rows = self.dubbing_page.checked_rows()
        if checked_rows:
            return checked_rows
        return self.dubbing_page.selected_rows()

    def set_dub_row_checked(self, row: int, checked: bool) -> None:
        segments = self.context.current_project.segments
        if row < 0 or row >= len(segments):
            return
        if segments[row].dub_selected == checked:
            return
        segments[row].dub_selected = checked
        self._mark_project_dirty()
        self.refresh_views()

    def _set_dub_rows_checked(self, rows: list[int], checked: bool) -> int:
        segments = self.context.current_project.segments
        changed_count = 0
        for row in rows:
            if 0 <= row < len(segments) and segments[row].dub_selected != checked:
                segments[row].dub_selected = checked
                changed_count += 1
        if changed_count:
            self._mark_project_dirty()
            self.refresh_views()
        return changed_count

    def check_selected_dub_rows(self) -> None:
        changed_count = self._set_dub_rows_checked(self.dubbing_page.selected_rows(), True)
        if changed_count:
            self.statusBar().showMessage(f"已勾选 {changed_count} 个配音片段。", 4000)

    def uncheck_selected_dub_rows(self) -> None:
        changed_count = self._set_dub_rows_checked(self.dubbing_page.selected_rows(), False)
        if changed_count:
            self.statusBar().showMessage(f"已取消 {changed_count} 个配音片段的勾选。", 4000)

    def check_all_dub_rows(self) -> None:
        changed_count = self._set_dub_rows_checked(
            list(range(len(self.context.current_project.segments))),
            True,
        )
        if changed_count:
            self.statusBar().showMessage(f"已全部勾选 {changed_count} 个配音片段。", 4000)

    def uncheck_all_dub_rows(self) -> None:
        changed_count = self._set_dub_rows_checked(
            list(range(len(self.context.current_project.segments))),
            False,
        )
        if changed_count:
            self.statusBar().showMessage("已清空配音片段勾选。", 4000)

    def _build_dubbing_job_settings(
        self,
        selected_voice: str | None = None,
        rate: float | None = None,
    ) -> AppSettings:
        # Build a job-local copy of the settings so UI choices never mutate the
        # global settings (which would silently change the app-wide default
        # voice/rate for the user).
        selected_voice = (
            selected_voice
            if selected_voice is not None
            else self.dubbing_page.current_voice_id()
        )
        job_settings = AppSettings.from_dict(self.context.settings.to_dict())
        if selected_voice:
            job_settings.tts.default_voice = selected_voice
        job_settings.tts.rate = (
            self.dubbing_page.rate_spin.value()
            if rate is None
            else float(rate)
        )
        return job_settings

    def _tts_cache_signature(self, settings: AppSettings) -> tuple[str, float]:
        return (
            settings.tts.provider_type,
            round(float(settings.tts.rate), 3),
        )

    def _invalidate_segment_dub(self, segment: object) -> None:
        setattr(segment, "tts_status", "pending")
        setattr(segment, "dub_audio_path", None)
        setattr(segment, "dub_text", "")
        setattr(segment, "dub_voice_id", None)
        setattr(segment, "dub_rate", None)

    def _invalidate_all_dubs(self) -> None:
        for segment in self.context.current_project.segments:
            self._invalidate_segment_dub(segment)

    def _play_audio_file(self, path: str) -> None:
        if winsound is None:
            QMessageBox.information(
                self,
                "当前环境不支持播放",
                "当前系统环境不支持内置音频播放。",
            )
            return
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)

    def _stop_audio_playback(self) -> None:
        if winsound is None:
            return
        winsound.PlaySound(None, 0)

    def _dubbing_in_progress(self) -> bool:
        return self.dubbing_busy

    def _on_dubbing_progress(self, progress: int, message: str) -> None:
        self.statusBar().showMessage(message, 0)
        self.dubbing_page.set_dubbing_progress(progress, message)
        self._set_task_progress(progress, message)

    def _on_dubbing_finished(self, result: DubbingJobResult) -> None:
        updated_count = 0
        updated_rows: set[int] = set()
        for item in result.items:
            if 0 <= item.row_index < len(self.context.current_project.segments):
                segment = self.context.current_project.segments[item.row_index]
                segment.voice_id = item.voice_id
                segment.tts_status = "completed"
                segment.dub_audio_path = item.output_path
                segment.dub_text = item.text
                segment.dub_voice_id = item.voice_id
                segment.dub_rate = item.rate
                updated_count += 1
                updated_rows.add(item.row_index)
        for row_index, previous_status in self._active_dubbing_previous_statuses.items():
            if row_index in updated_rows:
                continue
            if 0 <= row_index < len(self.context.current_project.segments):
                self.context.current_project.segments[row_index].tts_status = previous_status
        self._active_dubbing_previous_statuses = {}
        if updated_count:
            self._mark_project_dirty()
        self.dubbing_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self.refresh_views()
        self.dubbing_page.dubbing_table.setFocus()
        self._clear_task_progress()
        self.statusBar().showMessage(f"配音生成完成：已更新 {updated_count} 个片段。", 8000)
        self._notify_task_finished(
            "配音生成完成",
            f"英文配音已经生成完成。\n\n已更新片段数：{updated_count}",
        )

    def _on_dubbing_preview_ready(self, result: VoicePreviewResult) -> None:
        self.dubbing_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        self._play_audio_file(result.output_path)
        preview_source_message = self._pending_preview_source_message
        self._pending_preview_source_message = ""
        if preview_source_message:
            self.statusBar().showMessage(f"{preview_source_message} 音色试听已开始播放。", 6000)
        else:
            self.statusBar().showMessage("音色试听已开始播放。", 6000)

    def _on_dubbing_error(self, message: str) -> None:
        for row_index, previous_status in self._active_dubbing_previous_statuses.items():
            if 0 <= row_index < len(self.context.current_project.segments):
                self.context.current_project.segments[row_index].tts_status = previous_status
        self._active_dubbing_previous_statuses = {}
        self._pending_preview_source_message = ""
        self.dubbing_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self.refresh_views()
        self._clear_task_progress()
        QMessageBox.critical(self, "配音失败", message)
        self.statusBar().showMessage("配音任务失败。", 8000)

    def _on_dubbing_cancelled(self, message: str) -> None:
        for row_index, previous_status in self._active_dubbing_previous_statuses.items():
            if 0 <= row_index < len(self.context.current_project.segments):
                self.context.current_project.segments[row_index].tts_status = previous_status
        self._active_dubbing_previous_statuses = {}
        self._pending_preview_source_message = ""
        self.dubbing_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self.refresh_views()
        self._clear_task_progress()
        self.statusBar().showMessage(message or "已终止配音任务。", 8000)

    def _cleanup_dubbing_job(self) -> None:
        self.dubbing_thread = None
        self.dubbing_worker = None

