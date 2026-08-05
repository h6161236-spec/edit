"""VCut Studio - TranslationActions (MainWindow mixin).

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
from ...models import Segment
from ..workers import (
    SourceProofreadWorker,
    TranslationJobResult,
    TranslationTestWorker,
    TranslationWorker,
)


class TranslationActionsMixin:
    """TranslationActions actions for the main window."""

    def translate_all_segments(self) -> None:
        if not self.context.current_project.segments:
            QMessageBox.information(
                self,
                "没有转写分段",
                "请先执行 ASR 分析，再翻译片段。",
            )
            return
        row_requests = self._translation_requests_for_rows(
            range(len(self.context.current_project.segments)),
            skip_completed=True,
        )
        if not row_requests:
            QMessageBox.information(
                self,
                "无需继续翻译",
                "当前全部片段都已有英文结果。你可以直接导出，或手动选中需要重译的片段。",
            )
            return
        self._start_translation_job(row_requests, "已加入全部片段翻译队列...")

    def translate_selected_segments(self) -> None:
        selected_rows = self.translation_page.selected_rows()
        if not selected_rows:
            QMessageBox.information(
                self,
                "没有选中翻译行",
                "请先在翻译表中选中一行或多行。",
            )
            return
        row_requests = self._translation_requests_for_rows(selected_rows)
        self._start_translation_job(row_requests, "已加入所选片段翻译队列...")

    def proofread_source_segments(self) -> None:
        if not self._require_idle_background("校正文稿"):
            return
        if not self.context.current_project.segments:
            QMessageBox.information(
                self,
                "没有中文字幕可校正",
                "请先执行 ASR 分析或导入中文字幕，再进行文稿校正。",
            )
            return
        selected_rows = self.translation_page.selected_rows()
        target_rows = selected_rows if selected_rows else list(range(len(self.context.current_project.segments)))
        row_requests = self._translation_requests_for_rows(target_rows)
        if not row_requests:
            QMessageBox.information(
                self,
                "没有可校正内容",
                "当前选中范围里没有可校正的中文字幕。",
            )
            return

        self._clear_proofread_snapshot()
        self._last_proofread_snapshot = {
            row_index: {
                "zh_text": self.context.current_project.segments[row_index].zh_text,
                "en_text": self.context.current_project.segments[row_index].en_text,
                "translation_status": self.context.current_project.segments[row_index].translation_status,
                "tts_status": self.context.current_project.segments[row_index].tts_status,
                "dub_audio_path": self.context.current_project.segments[row_index].dub_audio_path,
                "dub_text": self.context.current_project.segments[row_index].dub_text,
                "dub_voice_id": self.context.current_project.segments[row_index].dub_voice_id,
                "dub_rate": self.context.current_project.segments[row_index].dub_rate,
            }
            for row_index, _request_item in row_requests
            if 0 <= row_index < len(self.context.current_project.segments)
        }
        self._last_proofread_project_id = self.context.current_project.project_id
        self._refresh_interactive_state()
        queued_message = (
            "已加入所选中文字幕校正队列..."
            if selected_rows
            else "已加入全部中文字幕校正队列..."
        )
        self._start_source_proofread_job(row_requests, queued_message)

    def undo_last_source_proofread(self) -> None:
        if not self._require_idle_background("撤销文稿校正"):
            return
        if not self._proofread_snapshot_has_live_changes():
            QMessageBox.information(
                self,
                "没有可恢复内容",
                "当前没有可恢复的上一次文稿校正结果。",
            )
            return

        restored_count = 0
        for row_index, snapshot in self._last_proofread_snapshot.items():
            if not (0 <= row_index < len(self.context.current_project.segments)):
                continue
            segment = self.context.current_project.segments[row_index]
            if self._segment_matches_proofread_snapshot(segment, snapshot):
                continue
            segment.zh_text = str(snapshot.get("zh_text", ""))
            segment.en_text = str(snapshot.get("en_text", ""))
            segment.translation_status = str(snapshot.get("translation_status", "pending"))
            segment.tts_status = str(snapshot.get("tts_status", "pending"))
            segment.dub_audio_path = snapshot.get("dub_audio_path")
            segment.dub_text = str(snapshot.get("dub_text", ""))
            segment.dub_voice_id = snapshot.get("dub_voice_id")
            segment.dub_rate = snapshot.get("dub_rate")
            self.translation_page.update_row_texts(
                row_index,
                zh_text=segment.zh_text,
                en_text=segment.en_text,
            )
            restored_count += 1

        self._clear_proofread_snapshot()
        if restored_count:
            self._mark_project_dirty()
            self._auto_save_project_snapshot()
            self.refresh_views()
            self.translation_page.translation_table.setFocus()
        self._refresh_interactive_state()
        self.statusBar().showMessage(f"已恢复 {restored_count} 条文稿到校正前状态。", 5000)

    def import_source_subtitles(self) -> None:
        if not self._require_idle_background("导入源字幕"):
            return

        subtitle_path = self._choose_subtitle_file("导入中文字幕")
        if not subtitle_path:
            return

        try:
            cues = read_subtitle_file(subtitle_path)
        except Exception as exc:
            QMessageBox.critical(self, "字幕导入失败", str(exc))
            return
        if not cues:
            QMessageBox.information(self, "没有可导入内容", "字幕文件里没有可用的字幕条目。")
            return

        imported_count = self._replace_project_segments_from_cues(cues)
        self._mark_project_dirty()
        self.timeline_page.show_workspace_tab("翻译")
        self.refresh_views()
        self.translation_page.translation_table.setFocus()
        self.statusBar().showMessage(
            f"已导入 {imported_count} 条中文字幕，并重建翻译分段。",
            6000,
        )

    def import_translation_subtitles(self) -> None:
        if not self._require_idle_background("导入翻译字幕"):
            return
        if not self.context.current_project.segments:
            QMessageBox.information(
                self,
                "还没有分段",
                "请先导入视频并识别字幕，或先导入中文字幕，再导入英文字幕。",
            )
            return

        subtitle_path = self._choose_subtitle_file("导入英文字幕")
        if not subtitle_path:
            return

        try:
            cues = read_subtitle_file(subtitle_path)
        except Exception as exc:
            QMessageBox.critical(self, "字幕导入失败", str(exc))
            return
        if not cues:
            QMessageBox.information(self, "没有可导入内容", "字幕文件里没有可用的字幕条目。")
            return

        updated_count = self._apply_translation_cues_to_segments(cues)
        if updated_count:
            self._mark_project_dirty()
        self.timeline_page.show_workspace_tab("翻译")
        self.refresh_views()
        self.translation_page.translation_table.setFocus()
        self.statusBar().showMessage(
            f"已导入 {updated_count} 条英文字幕到翻译表。",
            6000,
        )

    def export_translation_subtitles(self) -> None:
        if not self._require_idle_background("导出字幕"):
            return
        if not self.context.current_project.segments:
            QMessageBox.information(
                self,
                "没有可导出内容",
                "当前还没有可导出的分段字幕。",
            )
            return

        output_dir = self.context.settings.media.default_output_dir or self.context.settings.workspace.workspace_dir
        default_name = f"{self.context.current_project.name or 'vcut_subtitles'}.srt"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前字幕",
            str(Path(output_dir) / default_name),
            "SRT 字幕 (*.srt);;WebVTT 字幕 (*.vtt)",
        )
        if not output_path:
            return

        prefer_english = any(segment.en_text.strip() for segment in self.context.current_project.segments)
        cues: list[SubtitleCueData] = []
        for cue_index, segment in enumerate(self.context.current_project.segments, start=1):
            text = segment.en_text.strip() if prefer_english else segment.zh_text.strip()
            if not text:
                text = segment.zh_text.strip() if prefer_english else segment.en_text.strip()
            if not text:
                continue
            cues.append(
                SubtitleCueData(
                    index=cue_index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=text,
                )
            )
        if not cues:
            QMessageBox.information(
                self,
                "没有可导出内容",
                "当前分段里还没有可导出的字幕文本。",
            )
            return

        try:
            saved_path = write_subtitle_file(cues, output_path)
        except Exception as exc:
            QMessageBox.critical(self, "字幕导出失败", str(exc))
            return

        self.statusBar().showMessage(f"字幕已导出：{saved_path}", 6000)

    def test_translation_config(self) -> None:
        if not self._require_idle_background("测试翻译配置"):
            return

        worker = TranslationTestWorker(self.context.settings)
        self._start_background_job(
            worker,
            thread_attr="translation_thread",
            worker_attr="translation_worker",
            cleanup=self._cleanup_translation_job,
            status_message="已加入翻译配置测试队列...",
            progress=self._on_translation_progress,
            finished=self._on_translation_test_finished,
            error=self._on_translation_error,
        )
        self.translation_busy = True

    def preview_translation_time(self, row: int, column: int) -> None:
        segments = self.context.current_project.segments
        if not (0 <= row < len(segments)):
            return
        if not self.context.current_project.video_path:
            self.statusBar().showMessage("当前项目还没有源视频，无法跳转预览。", 4000)
            return
        segment = segments[row]
        position_ms = segment.start_ms if column == 1 else segment.end_ms
        self.timeline_page.set_focus_range(segment.start_ms, segment.end_ms)
        self.seek_preview(position_ms)
        self.statusBar().showMessage(
            f"已跳转到第 {row + 1} 个分段的{'开始' if column == 1 else '结束'}时间。",
            3000,
        )

    def update_segment_english_text(self, row: int, text: str) -> None:
        segments = self.context.current_project.segments
        if row < 0 or row >= len(segments):
            return
        segments[row].en_text = text.strip()
        segments[row].translation_status = "edited" if text.strip() else "pending"
        self._invalidate_segment_dub(segments[row])
        self._clear_proofread_snapshot_if_rows_touched([row])
        self._mark_project_dirty()
        self.timeline_page.load_project(self.context.current_project)
        self.dubbing_page.load_project(self.context.current_project, self.context.settings)
        self.export_page.load_project(self.context.current_project, self.context.settings)
        self._refresh_interactive_state()
        self.statusBar().showMessage(f"已更新第 {row + 1} 个分段的英文文本。", 3000)

    def update_segment_chinese_text(self, row: int, text: str) -> None:
        segments = self.context.current_project.segments
        if row < 0 or row >= len(segments):
            return
        normalized_text = text.strip()
        segment = segments[row]
        previous_text = segment.zh_text.strip()
        if normalized_text == previous_text:
            return

        segment.zh_text = normalized_text
        segment.translation_status = "pending"
        segment.en_text = ""
        self._invalidate_segment_dub(segment)
        self._clear_proofread_snapshot_if_rows_touched([row])
        self._mark_project_dirty()

        self.translation_page.clear_english_text(row)

        self.timeline_page.load_project(self.context.current_project)
        self.dubbing_page.load_project(self.context.current_project, self.context.settings)
        self.export_page.load_project(self.context.current_project, self.context.settings)
        self._refresh_interactive_state()
        self.statusBar().showMessage(f"已更新第 {row + 1} 个分段的中文文本，并清空旧翻译。", 4000)

    def _choose_subtitle_file(self, title: str) -> str:
        workspace_dir = self.context.settings.workspace.workspace_dir
        filename, _ = QFileDialog.getOpenFileName(
            self,
            title,
            workspace_dir,
            "字幕文件 (*.srt *.vtt);;SRT 字幕 (*.srt);;WebVTT 字幕 (*.vtt);;所有文件 (*.*)",
        )
        return filename

    def _replace_project_segments_from_cues(self, cues: list[SubtitleCueData]) -> int:
        project = self.context.current_project
        existing_segments = list(project.segments)
        default_voice = self.context.settings.tts.default_voice or None
        rebuilt_segments: list[Segment] = []
        for cue_index, cue in enumerate(sorted(cues, key=lambda item: (item.start_ms, item.end_ms))):
            previous_segment = existing_segments[cue_index] if cue_index < len(existing_segments) else None
            rebuilt_segments.append(
                Segment(
                    segment_id=previous_segment.segment_id if previous_segment is not None else uuid4().hex,
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    zh_text=cue.text.strip(),
                    en_text="",
                    keep=True,
                    dub_selected=previous_segment.dub_selected if previous_segment is not None else False,
                    translation_status="pending",
                    tts_status="pending",
                    voice_id=(
                        previous_segment.voice_id
                        if previous_segment is not None and previous_segment.voice_id
                        else default_voice
                    ),
                )
            )
        project.segments = rebuilt_segments
        project.cut_suggestions = []
        self._clear_proofread_snapshot()

        latest_end_ms = max((cue.end_ms for cue in cues), default=0)
        if not project.video_path and latest_end_ms > 0:
            project.source_duration_ms = max(project.source_duration_ms, latest_end_ms)
            if project.media_info.duration_ms <= 0:
                project.media_info.duration_ms = project.source_duration_ms
        return len(rebuilt_segments)

    def _apply_translation_cues_to_segments(self, cues: list[SubtitleCueData]) -> int:
        segments = self.context.current_project.segments
        segment_rows = sorted(
            range(len(segments)),
            key=lambda row_index: (segments[row_index].start_ms, segments[row_index].end_ms),
        )
        ordered_cues = sorted(cues, key=lambda item: (item.start_ms, item.end_ms))
        updated_count = 0
        updated_rows: set[int] = set()

        for row_index, cue in zip(segment_rows, ordered_cues):
            segment = segments[row_index]
            new_text = cue.text.strip()
            if segment.en_text.strip() == new_text and segment.translation_status == "edited":
                continue
            segment.en_text = new_text
            segment.translation_status = "edited" if new_text else "pending"
            self._invalidate_segment_dub(segment)
            updated_count += 1
            updated_rows.add(row_index)

        if updated_rows:
            self._clear_proofread_snapshot_if_rows_touched(updated_rows)

        return updated_count

    def _translation_requests_for_rows(
        self,
        rows: range | list[int],
        *,
        skip_completed: bool = False,
    ) -> list[tuple[int, TranslationRequest]]:
        requests: list[tuple[int, TranslationRequest]] = []
        for row_index in rows:
            if not (0 <= row_index < len(self.context.current_project.segments)):
                continue
            segment = self.context.current_project.segments[row_index]
            source_text = segment.zh_text.strip()
            if not source_text:
                continue
            if skip_completed and segment.en_text.strip():
                continue
            requests.append(
                (
                    row_index,
                    TranslationRequest(
                        segment_id=segment.segment_id,
                        source_text=source_text,
                    ),
                )
            )
        return requests

    def _start_translation_job(
        self,
        row_requests: list[tuple[int, TranslationRequest]],
        queued_message: str,
    ) -> None:
        if not self._require_idle_background("翻译"):
            return
        if not row_requests:
            QMessageBox.information(
                self,
                "没有可翻译内容",
                "所选行中没有可翻译的中文文本。",
            )
            return

        worker = TranslationWorker(self.context.settings, row_requests)
        self._start_background_job(
            worker,
            thread_attr="translation_thread",
            worker_attr="translation_worker",
            cleanup=self._cleanup_translation_job,
            status_message=queued_message,
            progress=self._on_translation_progress,
            partial_results=self._on_translation_partial_results,
            finished=self._on_translation_finished,
            cancelled=self._on_translation_cancelled,
            error=self._on_translation_error,
        )
        self.translation_busy = True

    def _start_source_proofread_job(
        self,
        row_requests: list[tuple[int, TranslationRequest]],
        queued_message: str,
    ) -> None:
        if not self._require_idle_background("校正文稿"):
            return
        if not row_requests:
            QMessageBox.information(
                self,
                "没有可校正内容",
                "当前没有可校正的中文字幕。",
            )
            return

        worker = SourceProofreadWorker(self.context.settings, row_requests)
        self._start_background_job(
            worker,
            thread_attr="translation_thread",
            worker_attr="translation_worker",
            cleanup=self._cleanup_translation_job,
            status_message=queued_message,
            progress=self._on_translation_progress,
            partial_results=self._on_source_proofread_partial_results,
            finished=self._on_source_proofread_finished,
            cancelled=self._on_source_proofread_cancelled,
            error=self._on_source_proofread_error,
        )
        self.translation_busy = True

    def _apply_source_corrections(self, items: list[tuple[int, str]]) -> int:
        changed_count = 0
        for row_index, corrected_text in items:
            if not (0 <= row_index < len(self.context.current_project.segments)):
                continue
            normalized_text = corrected_text.strip()
            segment = self.context.current_project.segments[row_index]
            if segment.zh_text.strip() == normalized_text:
                continue
            segment.zh_text = normalized_text
            segment.en_text = ""
            segment.translation_status = "pending"
            self._invalidate_segment_dub(segment)
            self.translation_page.update_row_texts(row_index, zh_text=normalized_text, en_text="")
            changed_count += 1
        if changed_count:
            self._mark_project_dirty()
            self._auto_save_project_snapshot(allow_during_background=True)
            self.refresh_views()
        return changed_count

    def _apply_translation_batch(self, items: list[tuple[int, object]]) -> int:
        updated_count = 0
        updated_rows: set[int] = set()
        for row_index, translation_result in items:
            if not (0 <= row_index < len(self.context.current_project.segments)):
                continue
            translated_text = str(getattr(translation_result, "translated_text", "")).strip()
            if not translated_text:
                continue
            segment = self.context.current_project.segments[row_index]
            if segment.en_text.strip() == translated_text and segment.translation_status == "translated":
                continue
            segment.en_text = translated_text
            segment.translation_status = "translated"
            self._invalidate_segment_dub(segment)
            self.translation_page.update_row_texts(row_index, en_text=translated_text)
            updated_count += 1
            updated_rows.add(row_index)
        if updated_count:
            self._clear_proofread_snapshot_if_rows_touched(updated_rows)
            self._mark_project_dirty()
            self._auto_save_project_snapshot(allow_during_background=True)
            self.refresh_views()
        return updated_count

    def _clear_proofread_snapshot(self) -> None:
        self._last_proofread_snapshot = {}
        self._last_proofread_project_id = None

    def _has_proofread_undo_available(self) -> bool:
        return (
            bool(self._last_proofread_snapshot)
            and self._last_proofread_project_id == self.context.current_project.project_id
        )

    def _segment_matches_proofread_snapshot(self, segment: Segment, snapshot: dict[str, object]) -> bool:
        return (
            segment.zh_text == str(snapshot.get("zh_text", ""))
            and segment.en_text == str(snapshot.get("en_text", ""))
            and segment.translation_status == str(snapshot.get("translation_status", "pending"))
            and segment.tts_status == str(snapshot.get("tts_status", "pending"))
            and segment.dub_audio_path == snapshot.get("dub_audio_path")
            and segment.dub_text == str(snapshot.get("dub_text", ""))
            and segment.dub_voice_id == snapshot.get("dub_voice_id")
            and segment.dub_rate == snapshot.get("dub_rate")
        )

    def _proofread_snapshot_has_live_changes(self) -> bool:
        if not self._has_proofread_undo_available():
            return False
        for row_index, snapshot in self._last_proofread_snapshot.items():
            if not (0 <= row_index < len(self.context.current_project.segments)):
                continue
            segment = self.context.current_project.segments[row_index]
            if not self._segment_matches_proofread_snapshot(segment, snapshot):
                return True
        return False

    def _clear_proofread_snapshot_if_rows_touched(self, rows: list[int] | set[int]) -> None:
        if not self._has_proofread_undo_available():
            return
        if any(row in self._last_proofread_snapshot for row in rows):
            self._clear_proofread_snapshot()

    def _on_source_proofread_partial_results(self, items: object) -> None:
        changed_count = self._apply_source_corrections(list(items))
        if changed_count:
            self.statusBar().showMessage(f"已保存 {changed_count} 条文稿校正结果。", 3000)

    def _on_source_proofread_finished(self, corrected_count: int) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self.refresh_views()
        self.translation_page.translation_table.setFocus()
        self._clear_task_progress()
        self.statusBar().showMessage(
            f"中文字幕校正完成：已处理 {corrected_count} 个分段。",
            8000,
        )
        self._notify_task_finished(
            "中文字幕校正完成",
            f"中文字幕校正已经完成。\n\n已处理分段数：{corrected_count}",
        )

    def _on_translation_partial_results(self, items: object) -> None:
        updated_count = self._apply_translation_batch(list(items))
        if updated_count:
            self.statusBar().showMessage(f"已保存 {updated_count} 条翻译结果。", 3000)

    def _on_translation_progress(self, progress: int, message: str) -> None:
        self.statusBar().showMessage(message, 0)
        self.translation_page.set_translation_progress(progress, message)
        self._set_task_progress(progress, message)

    def _on_translation_finished(self, result: TranslationJobResult) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self.refresh_views()
        self.translation_page.translation_table.setFocus()
        self._clear_task_progress()
        self.statusBar().showMessage(
            f"翻译完成：已更新 {len(result.items)} 个分段。",
            8000,
        )
        self._notify_task_finished(
            "翻译完成",
            f"英文翻译已经完成。\n\n已更新分段数：{len(result.items)}",
        )

    def _on_translation_test_finished(self, sample: str) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        QMessageBox.information(
            self,
            "翻译配置正常",
            f"连接测试成功。\n\n示例翻译：\n{sample}",
        )
        self.statusBar().showMessage("翻译提供方连接测试成功。", 8000)

    def _on_translation_error(self, message: str) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        QMessageBox.critical(self, "翻译失败", message)
        self.statusBar().showMessage("翻译任务失败。", 8000)

    def _on_translation_cancelled(self, message: str) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        self.statusBar().showMessage(message or "已终止翻译任务。", 8000)

    def _on_source_proofread_error(self, message: str) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        QMessageBox.critical(self, "文稿校正失败", message)
        self.statusBar().showMessage("文稿校正任务失败。", 8000)

    def _on_source_proofread_cancelled(self, message: str) -> None:
        self.translation_busy = False
        self._set_active_background_worker(None)
        self._refresh_interactive_state()
        self._clear_task_progress()
        self.statusBar().showMessage(message or "已终止文稿校正任务。", 8000)

    def _cleanup_translation_job(self) -> None:
        self.translation_thread = None
        self.translation_worker = None

    def _translation_in_progress(self) -> bool:
        return self.translation_busy

