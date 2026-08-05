"""VCut Studio - AnalysisActions (MainWindow mixin).

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
from ...cutting import generate_cut_suggestions
from ...settings import AppSettings
from ..workers import AnalysisResult, AnalysisWorker


class AnalysisActionsMixin:
    """AnalysisActions actions for the main window."""

    def analyze_video(self) -> None:
        if not self._require_idle_background("执行字幕识别"):
            return
        project = self.context.current_project
        if not project.video_path:
            QMessageBox.information(
                self,
                "没有源视频",
                "请先导入源视频，再执行中文 ASR 分析。",
            )
            return

        worker = AnalysisWorker(
            media_path=project.video_path,
            asr_settings=self.context.settings.asr,
            default_voice=self.context.settings.tts.default_voice,
        )
        self._start_background_job(
            worker,
            thread_attr="analysis_thread",
            worker_attr="analysis_worker",
            cleanup=self._cleanup_analysis_job,
            status_message="已加入字幕识别队列...",
            progress=self._on_analysis_progress,
            finished=self._on_analysis_finished,
            cancelled=self._on_analysis_cancelled,
            error=self._on_analysis_error,
        )
        self.analysis_busy = True

    def generate_cut_suggestions_for_project(self) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        project = self.context.current_project
        if not project.segments and not project.analysis_completed:
            QMessageBox.information(
                self,
                "还没有识别分段",
                "请先执行“识别字幕 / 分段”，再生成删除建议。",
            )
            return

        total_duration_ms = int(
            project.source_duration_ms
            or project.media_info.duration_ms
            or max((segment.end_ms for segment in project.segments), default=0)
        )
        project.cut_suggestions = generate_cut_suggestions(
            project.segments,
            self.context.settings.cutting,
            total_duration_ms=total_duration_ms,
        )
        self._mark_project_dirty()
        self.refresh_views()
        self.timeline_page.show_workspace_tab("建议删除")
        self.statusBar().showMessage(
            f"已生成 {len(project.cut_suggestions)} 条删除建议。翻译功能不受影响，可以单独继续。",
            6000,
        )

    def accept_selected_suggestions(self) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        selected_rows = self.timeline_page.selected_suggestion_rows()
        if not selected_rows:
            self.statusBar().showMessage("请先选中要勾选的删除建议。", 4000)
            return
        self._set_suggestion_rows_acceptance(selected_rows, True)
        self.statusBar().showMessage(f"已勾选 {len(selected_rows)} 条删除建议。", 5000)

    def clear_selected_suggestions(self) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        selected_rows = self.timeline_page.selected_suggestion_rows()
        if not selected_rows:
            self.statusBar().showMessage("请先选中要取消的删除建议。", 4000)
            return
        self._set_suggestion_rows_acceptance(selected_rows, False)
        self.statusBar().showMessage(f"已取消 {len(selected_rows)} 条删除建议的勾选。", 5000)

    def accept_all_suggestions(self) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        if not self.context.current_project.cut_suggestions:
            self.statusBar().showMessage("当前没有可接受的剪辑建议。", 4000)
            return
        self._set_suggestion_rows_acceptance(
            list(range(len(self.context.current_project.cut_suggestions))),
            True,
        )
        self.statusBar().showMessage(
            f"已接受 {len(self.context.current_project.cut_suggestions)} 条剪辑建议。",
            5000,
        )

    def clear_suggestion_acceptance(self) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        if not self.context.current_project.cut_suggestions:
            self.statusBar().showMessage("当前没有可清空的剪辑建议。", 4000)
            return
        self._set_suggestion_rows_acceptance(
            list(range(len(self.context.current_project.cut_suggestions))),
            False,
        )
        self.statusBar().showMessage("已清空剪辑建议的接受标记。", 5000)

    def set_suggestion_acceptance(self, row: int, accepted: bool) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        suggestions = self.context.current_project.cut_suggestions
        if row < 0 or row >= len(suggestions):
            return
        suggestions[row].accepted = accepted
        self._mark_project_dirty()
        self.refresh_views()
        state = "已接受" if accepted else "已取消"
        self.statusBar().showMessage(f"第 {row + 1} 条建议{state}。", 4000)

    def _set_suggestion_rows_acceptance(self, rows: list[int], accepted: bool) -> None:
        suggestions = self.context.current_project.cut_suggestions
        changed = False
        for row in rows:
            if 0 <= row < len(suggestions) and suggestions[row].accepted != accepted:
                suggestions[row].accepted = accepted
                changed = True
        if changed:
            self._mark_project_dirty()
            self.refresh_views()

    def update_suggestion_range(self, row: int, start_ms: int, end_ms: int) -> None:
        if self._background_job_in_progress():
            self.statusBar().showMessage("请先等待当前后台任务完成。", 4000)
            return
        suggestions = self.context.current_project.cut_suggestions
        if not (0 <= row < len(suggestions)):
            return
        total_duration_ms = max(
            0,
            int(
                self.context.current_project.source_duration_ms
                or self.context.current_project.media_info.duration_ms
                or 0
            ),
        )
        if total_duration_ms > 0:
            start_ms = min(max(0, start_ms), total_duration_ms)
            end_ms = min(max(0, end_ms), total_duration_ms)
        if end_ms <= start_ms:
            QMessageBox.information(self, "范围时间无效", "结束时间必须大于开始时间。")
            return
        suggestion = suggestions[row]
        suggestion.start_ms = start_ms
        suggestion.end_ms = end_ms
        self._mark_project_dirty()
        self.refresh_views()
        self.timeline_page.show_workspace_tab("建议删除")
        self.timeline_page.set_selected_suggestion_range(row, start_ms, end_ms)
        self.timeline_page.set_focus_range(start_ms, end_ms)
        self.seek_preview(start_ms)
        self.statusBar().showMessage(f"已更新第 {row + 1} 条建议的范围时间。", 5000)

    def locate_selected_suggestion(self, rows: list[int]) -> None:
        if not rows:
            selected_segments = self.timeline_page.selected_segment_rows()
            if selected_segments:
                self.locate_selected_segment(selected_segments)
            else:
                self.timeline_page.set_focus_range(None, None)
                self.timeline_page.clear_selected_suggestion_range()
            return
        suggestions = self.context.current_project.cut_suggestions
        row = rows[0]
        if not (0 <= row < len(suggestions)):
            return
        suggestion = suggestions[row]
        self.timeline_page.set_selected_suggestion_range(row, suggestion.start_ms, suggestion.end_ms)
        self.timeline_page.set_focus_range(suggestion.start_ms, suggestion.end_ms)
        self.seek_preview(suggestion.start_ms)

    def locate_selected_segment(self, rows: list[int]) -> None:
        if not rows:
            if not self.timeline_page.selected_suggestion_rows():
                self.timeline_page.set_focus_range(None, None)
            return
        segments = self.context.current_project.segments
        row = rows[0]
        if not (0 <= row < len(segments)):
            return
        segment = segments[row]
        self.timeline_page.set_focus_range(segment.start_ms, segment.end_ms)
        self.seek_preview(segment.start_ms)

    def _analysis_in_progress(self) -> bool:
        return self.analysis_busy

    def _on_analysis_progress(self, progress: int, message: str) -> None:
        self.statusBar().showMessage(message, 0)
        self.timeline_page.set_analysis_progress(progress, message)
        self._set_task_progress(progress, message)

    def _on_analysis_finished(self, result: AnalysisResult) -> None:
        project = self.context.current_project
        project.segments = result.segments
        project.analysis_completed = True
        project.cut_suggestions = []
        self._clear_proofread_snapshot()
        self._mark_project_dirty()
        self.analysis_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self.refresh_views()
        self.timeline_page.show_workspace_tab("识别")
        self.timeline_page.segments_table.setFocus()
        self._clear_task_progress()
        if result.summary.segment_count > 0:
            message = (
                f"字幕识别已完成：共生成 {result.summary.segment_count} 个分段。\n"
                f"本次视频平均置信度参考值：{result.summary.average_confidence:.2f}\n"
            )
            if result.summary.filtered_segment_count > 0:
                message += f"已按最低置信度过滤 {result.summary.filtered_segment_count} 个低质量分段。\n"
            message += "参考：0.85 以上通常较稳，0.70-0.85 建议抽查，低于 0.70 建议重试或提高阈值。"
        else:
            message = (
                "字幕识别已完成，但没有检测到可用语音分段。\n"
                f"本次视频平均置信度参考值：{result.summary.average_confidence:.2f}\n"
                "如果视频前后是长时间空白，现在可以直接生成无声/无人声删除建议。"
            )
        self.statusBar().showMessage(message, 8000)
        self._notify_task_finished("字幕识别完成", message)

    def _on_analysis_error(self, message: str) -> None:
        self.analysis_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        QMessageBox.critical(self, "字幕识别失败", message)
        self.statusBar().showMessage("字幕识别失败。", 8000)

    def _on_analysis_cancelled(self, message: str) -> None:
        self.analysis_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        self.statusBar().showMessage(message or "已终止字幕识别任务。", 8000)

    def _cleanup_analysis_job(self) -> None:
        self.analysis_thread = None
        self.analysis_worker = None

