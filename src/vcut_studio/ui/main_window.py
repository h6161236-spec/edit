from __future__ import annotations

import importlib.util
from collections.abc import Callable

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..media import resolve_ffmpeg_path
from ..providers.tts import tts_provider_display_name, tts_provider_runtime_status
from ..runtime_assets import find_app_icon
from .pages import DubbingPage, ExportPage, SettingsPage, TimelinePage, TranslationPage
from .workers import (
    AnalysisWorker,
    ControllableWorker,
    DubbingWorker,
    ExportWorker,
    SourceProofreadWorker,
    TranslationTestWorker,
    TranslationWorker,
    VoicePreviewWorker,
)

try:  # pragma: no cover - Windows-only runtime path
    import winsound
except ImportError:  # pragma: no cover - non-Windows runtime path
    winsound = None


from .actions.dubbing_actions import DubbingActionsMixin
from .actions.export_actions import ExportActionsMixin
from .actions.analysis_actions import AnalysisActionsMixin
from .actions.project_actions import ProjectActionsMixin
from .actions.preview_actions import PreviewActionsMixin
from .actions.settings_actions import SettingsActionsMixin
from .actions.translation_actions import TranslationActionsMixin


class MainWindow(
    ProjectActionsMixin,
    PreviewActionsMixin,
    AnalysisActionsMixin,
    TranslationActionsMixin,
    DubbingActionsMixin,
    ExportActionsMixin,
    SettingsActionsMixin,
    QMainWindow,
):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.resize(1500, 960)
        self._apply_window_icon()
        self._apply_workspace_style()

        self.timeline_page = TimelinePage()
        self.translation_page = TranslationPage()
        self.dubbing_page = DubbingPage()
        self.export_page = ExportPage()
        self.settings_page = SettingsPage()
        self.analysis_busy = False
        self.translation_busy = False
        self.dubbing_busy = False
        self.export_busy = False
        self.analysis_thread: QThread | None = None
        self.analysis_worker: AnalysisWorker | None = None
        self.translation_thread: QThread | None = None
        self.translation_worker: TranslationWorker | TranslationTestWorker | SourceProofreadWorker | None = None
        self.dubbing_thread: QThread | None = None
        self.dubbing_worker: DubbingWorker | VoicePreviewWorker | None = None
        self.export_thread: QThread | None = None
        self.export_worker: ExportWorker | None = None
        self._active_dubbing_previous_statuses: dict[int, str] = {}
        self._last_proofread_snapshot: dict[int, dict[str, object]] = {}
        self._last_proofread_project_id: str | None = None
        self._pending_preview_source_message = ""
        self._active_background_worker: ControllableWorker | None = None
        self._preview_source_path = ""
        self._preview_proxy_cache: dict[str, str] = {}
        self._preview_proxy_failures: set[str] = set()
        self._waveform_cache: dict[str, list[float]] = {}
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._auto_save_project_snapshot)

        self.timeline_page.attach_workspace_panels(
            self.translation_page,
            self.dubbing_page,
        )
        self.setCentralWidget(self.timeline_page)
        self.setStatusBar(QStatusBar())
        self._build_status_controls()

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("设置")
        self.settings_dialog.resize(1080, 760)
        self.settings_dialog.setWindowIcon(self.windowIcon())
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.addWidget(self.settings_page)

        self.export_dialog = QDialog(self)
        self.export_dialog.setWindowTitle("导出视频")
        self.export_dialog.resize(840, 520)
        self.export_dialog.setWindowIcon(self.windowIcon())
        export_layout = QVBoxLayout(self.export_dialog)
        export_layout.setContentsMargins(12, 12, 12, 12)
        export_layout.addWidget(self.export_page)

        self.preview_audio_output = QAudioOutput(self)
        self.preview_audio_output.setVolume(1.0)
        self.preview_audio_output.setMuted(False)
        self.preview_player = QMediaPlayer(self)
        self.preview_player.setAudioOutput(self.preview_audio_output)
        self.preview_player.setVideoOutput(self.timeline_page.video_widget)
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self._sync_preview_audio_device)
        self._sync_preview_audio_device()
        self.timeline_page.set_preview_audio_state(100, False)

        self._create_menu()
        self._connect_signals()
        self.settings_page.load_settings(self.context.settings)
        self._configure_autosave_timer()
        self.refresh_views()

    def _apply_window_icon(self) -> None:
        icon_path = find_app_icon()
        if icon_path is not None:
            self.setWindowIcon(QIcon(str(icon_path)))

    def _apply_workspace_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QDialog, QMessageBox {
                background: #161a1f;
                color: #f3f4f6;
            }
            QMenuBar, QMenu, QStatusBar, QToolTip {
                background: #11151b;
                color: #f3f4f6;
                border: 1px solid #2b3440;
            }
            QTabWidget::pane {
                border: 1px solid #2c3440;
                border-radius: 10px;
                background: #1c222b;
                top: -1px;
            }
            QTabBar::tab {
                background: #11151b;
                color: #cbd5e1;
                border: 1px solid #2c3440;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 16px;
                margin-right: 6px;
            }
            QTabBar::tab:selected {
                background: #1c222b;
                color: #f8fafc;
            }
            QTabBar::tab:hover:!selected {
                background: #18202a;
            }
            QWidget {
                color: #e5e7eb;
            }
            QLabel {
                color: #e5e7eb;
            }
            QFrame#settingsHeaderCard,
            QFrame#settingsSidebar,
            QFrame#settingsContent {
                background: #1c222b;
                border: 1px solid #2c3440;
                border-radius: 12px;
            }
            QLabel#settingsHeaderTitle,
            QLabel#settingsSectionTitle {
                color: #f8fafc;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#settingsHeaderText,
            QLabel#settingsNavHint,
            QLabel#settingsSectionText {
                color: #94a3b8;
            }
            QLabel#settingsNavTitle {
                color: #f8fafc;
                font-weight: 700;
            }
            QGroupBox {
                border: 1px solid #2c3440;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 10px;
                background: #1c222b;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #f8fafc;
            }
            QPushButton {
                background: #273445;
                border: 1px solid #344255;
                border-radius: 8px;
                padding: 6px 12px;
                color: #f8fafc;
            }
            QPushButton:hover {
                background: #304259;
            }
            QPushButton:disabled {
                background: #202734;
                color: #6b7280;
                border-color: #2a3240;
            }
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: #11151b;
                border: 1px solid #2f3946;
                border-radius: 6px;
                padding: 4px 6px;
                selection-background-color: #0f766e;
                selection-color: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QAbstractItemView, QListView, QTableWidget, QTableView, QTreeView {
                background: #11151b;
                alternate-background-color: #18202a;
                border: 1px solid #2f3946;
                gridline-color: #27313d;
                selection-background-color: #0f766e;
                selection-color: #ffffff;
            }
            QListWidget#settingsNav {
                background: transparent;
                border: none;
                outline: none;
                padding: 2px 0;
            }
            QListWidget#settingsNav::item {
                border-radius: 8px;
                padding: 10px 12px;
                margin: 2px 0;
                color: #cbd5e1;
            }
            QListWidget#settingsNav::item:selected {
                background: #0f766e;
                color: #ffffff;
            }
            QListWidget#settingsNav::item:hover:!selected {
                background: #243140;
                color: #f8fafc;
            }
            QTableWidget {
                color: #e5e7eb;
            }
            QHeaderView::section {
                background: #202734;
                border: none;
                padding: 6px;
            }
            QScrollArea {
                border: none;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: #11151b;
                border: none;
                margin: 0;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #334155;
                border-radius: 6px;
                min-height: 28px;
                min-width: 28px;
            }
            QScrollBar::add-line, QScrollBar::sub-line,
            QScrollBar::add-page, QScrollBar::sub-page {
                background: none;
                border: none;
            }
            QProgressBar {
                border: 1px solid #2f3946;
                border-radius: 8px;
                text-align: center;
                background: #11151b;
            }
            QProgressBar::chunk {
                background: #0ea5a4;
                border-radius: 6px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #243140;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: #7dd3fc;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #3b4756;
                background: #11151b;
            }
            QCheckBox::indicator:checked {
                background: #0f766e;
                border-color: #14b8a6;
            }
            QSplitter::handle {
                background: #11151b;
            }
            QVideoWidget {
                background: #090c10;
                border-radius: 10px;
            }
            """
        )

    def _build_status_controls(self) -> None:
        control_container = QWidget(self)
        control_layout = QHBoxLayout(control_container)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)

        self.background_task_label = QLabel("后台任务：空闲")
        self.background_progress_bar = QProgressBar()
        self.background_progress_bar.setRange(0, 100)
        self.background_progress_bar.setValue(0)
        self.background_progress_bar.setFormat("等待开始")
        self.background_progress_bar.setVisible(False)
        self.background_progress_bar.setMinimumWidth(280)
        self.pause_task_button = QPushButton("暂停")
        self.resume_task_button = QPushButton("继续")
        self.cancel_task_button = QPushButton("终止")

        self.pause_task_button.clicked.connect(self.pause_active_task)
        self.resume_task_button.clicked.connect(self.resume_active_task)
        self.cancel_task_button.clicked.connect(self.cancel_active_task)

        control_layout.addWidget(self.background_task_label)
        control_layout.addWidget(self.background_progress_bar)
        control_layout.addWidget(self.pause_task_button)
        control_layout.addWidget(self.resume_task_button)
        control_layout.addWidget(self.cancel_task_button)

        self.statusBar().addPermanentWidget(control_container)

    def _create_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction("新建项目", self.new_project)
        file_menu.addAction("导入视频", self.import_video)
        file_menu.addAction("打开项目", self.open_project)
        file_menu.addAction("保存项目", self.save_project)
        file_menu.addAction("项目另存为", self.save_project_as)
        file_menu.addSeparator()
        file_menu.addAction("导出视频", self.show_export_dialog)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        tools_menu = self.menuBar().addMenu("工具")
        tools_menu.addAction("扫描依赖", self.scan_dependencies)
        tools_menu.addAction("识别字幕 / 分段", self.analyze_video)
        tools_menu.addAction("生成删除建议", self.generate_cut_suggestions_for_project)
        tools_menu.addSeparator()
        tools_menu.addAction("打开设置", self.show_settings_dialog)

    def _connect_signals(self) -> None:
        self.timeline_page.analyze_button.clicked.connect(self.analyze_video)
        self.timeline_page.generate_suggestions_requested.connect(self.generate_cut_suggestions_for_project)
        self.timeline_page.accept_selected_button.clicked.connect(self.accept_selected_suggestions)
        self.timeline_page.clear_selected_button.clicked.connect(self.clear_selected_suggestions)
        self.timeline_page.accept_all_button.clicked.connect(self.accept_all_suggestions)
        self.timeline_page.reject_all_button.clicked.connect(self.clear_suggestion_acceptance)
        self.timeline_page.suggestion_acceptance_changed.connect(self.set_suggestion_acceptance)
        self.timeline_page.suggestion_selection_changed.connect(self.locate_selected_suggestion)
        self.timeline_page.suggestion_range_apply_requested.connect(self.update_suggestion_range)
        self.timeline_page.segment_selection_changed.connect(self.locate_selected_segment)
        self.timeline_page.seek_requested.connect(self.seek_preview)
        self.timeline_page.play_requested.connect(self.play_preview)
        self.timeline_page.pause_requested.connect(self.pause_preview)
        self.timeline_page.stop_requested.connect(self.stop_preview)
        self.timeline_page.preview_volume_changed.connect(self.set_preview_volume)
        self.timeline_page.preview_mute_toggled.connect(self.set_preview_muted)
        self.translation_page.chinese_text_edited.connect(self.update_segment_chinese_text)
        self.translation_page.english_text_edited.connect(self.update_segment_english_text)
        self.translation_page.selection_changed.connect(self._refresh_interactive_state)
        self.translation_page.time_double_clicked.connect(self.preview_translation_time)
        self.translation_page.translate_all_button.clicked.connect(self.translate_all_segments)
        self.translation_page.translate_selected_button.clicked.connect(self.translate_selected_segments)
        self.translation_page.proofread_source_requested.connect(self.proofread_source_segments)
        self.translation_page.undo_proofread_requested.connect(self.undo_last_source_proofread)
        self.translation_page.import_source_subtitle_requested.connect(self.import_source_subtitles)
        self.translation_page.import_translation_subtitle_requested.connect(self.import_translation_subtitles)
        self.translation_page.export_subtitle_requested.connect(self.export_translation_subtitles)
        self.translation_page.save_requested.connect(self.save_project)
        self.translation_page.test_translation_button.clicked.connect(self.test_translation_config)
        self.dubbing_page.selection_changed.connect(self._refresh_interactive_state)
        self.dubbing_page.check_state_changed.connect(self.set_dub_row_checked)
        # [已注释] 仅应用音色按钮（与生成配音的自动应用功能重叠，暂时移除）。
        # self.dubbing_page.apply_voice_button.clicked.connect(self.apply_voice_to_selected_segments)
        self.dubbing_page.generate_button.clicked.connect(self.generate_selected_dubs)
        self.dubbing_page.preview_button.clicked.connect(self.preview_selected_voice)
        self.dubbing_page.stop_button.clicked.connect(self.stop_dub_playback)
        self.dubbing_page.check_selected_button.clicked.connect(self.check_selected_dub_rows)
        self.dubbing_page.uncheck_selected_button.clicked.connect(self.uncheck_selected_dub_rows)
        self.dubbing_page.check_all_button.clicked.connect(self.check_all_dub_rows)
        self.dubbing_page.uncheck_all_button.clicked.connect(self.uncheck_all_dub_rows)
        self.dubbing_page.play_generated_requested.connect(self.play_generated_dub)
        self.export_page.output_dir_browse_requested.connect(self.browse_export_output_dir)
        self.export_page.export_button.clicked.connect(self.start_export)
        self.settings_page.top_save_button.clicked.connect(self.save_settings)
        self.settings_page.top_reset_button.clicked.connect(self.reset_settings)
        self.settings_page.asr_runtime_check_requested.connect(self.show_asr_runtime_diagnostics)
        self.settings_page.asr_cache_dir_browse_requested.connect(self.browse_asr_cache_dir)
        self.settings_page.asr_local_model_dir_browse_requested.connect(self.browse_asr_local_model_dir)
        self.preview_player.positionChanged.connect(self._on_preview_position_changed)
        self.preview_player.durationChanged.connect(self._on_preview_duration_changed)
        self.preview_player.playbackStateChanged.connect(self._on_preview_playback_state_changed)









    def _set_task_progress(self, progress: int, message: str, *, pump_events: bool = False) -> None:
        clamped = max(0, min(int(progress), 100))
        self.background_progress_bar.setVisible(True)
        self.background_progress_bar.setValue(clamped)
        self.background_progress_bar.setFormat(f"{clamped}% | {message}")
        self.statusBar().showMessage(message, 0)
        if pump_events:
            QApplication.processEvents()

    def _clear_task_progress(self) -> None:
        self.background_progress_bar.setValue(0)
        self.background_progress_bar.setFormat("等待开始")
        self.background_progress_bar.setVisible(False)

    def _notify_task_finished(self, title: str, message: str) -> None:
        QApplication.alert(self)
        if winsound is not None:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass











    def _set_active_background_worker(self, worker: ControllableWorker | None) -> None:
        self._active_background_worker = worker

    def _start_background_job(
        self,
        worker: ControllableWorker,
        *,
        thread_attr: str,
        worker_attr: str,
        cleanup: Callable[[], None],
        status_message: str,
        finished: Callable[[object], None],
        progress: Callable[[int, str], None] | None = None,
        partial_results: Callable[[object], None] | None = None,
        cancelled: Callable[[str], None] | None = None,
        error: Callable[[str], None] | None = None,
    ) -> QThread:
        """Start a worker on a dedicated QThread with the standard lifecycle.

        Every background task in the app follows the same wiring: the worker
        runs on a dedicated thread, terminal signals (finished/cancelled/error)
        quit the thread and schedule the worker for deletion, and thread
        teardown clears the stored references. This helper centralizes that
        boilerplate so job start sites only declare their callbacks.
        """
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        terminal_signals: list[object] = []
        for signal_name, callback in (
            ("progress", progress),
            ("partial_results", partial_results),
            ("finished", finished),
            ("cancelled", cancelled),
            ("error", error),
        ):
            signal = getattr(worker, signal_name, None)
            if signal is None or callback is None:
                continue
            signal.connect(callback)
            if signal_name in {"finished", "cancelled", "error"}:
                terminal_signals.append(signal)
        if not terminal_signals:
            terminal_signals = [worker.finished]
        for signal in terminal_signals:
            signal.connect(thread.quit)
            signal.connect(worker.deleteLater)
        thread.finished.connect(cleanup)
        thread.finished.connect(thread.deleteLater)

        setattr(self, thread_attr, thread)
        setattr(self, worker_attr, worker)
        self._set_active_background_worker(worker)
        self._refresh_interactive_state()
        self.statusBar().showMessage(status_message, 0)
        thread.start()
        return thread

    def _current_background_task_label(self) -> str:
        if self._active_background_worker is None:
            return ""
        return self._active_background_worker.task_label

    def pause_active_task(self) -> None:
        worker = self._active_background_worker
        if worker is None:
            self.statusBar().showMessage("当前没有可暂停的后台任务。", 4000)
            return
        try:
            worker.request_pause()
        except Exception as exc:
            QMessageBox.warning(self, "暂停失败", str(exc))
            return
        self._refresh_interactive_state()
        self.statusBar().showMessage(f"{worker.task_label}已暂停。", 5000)

    def resume_active_task(self) -> None:
        worker = self._active_background_worker
        if worker is None:
            self.statusBar().showMessage("当前没有可继续的后台任务。", 4000)
            return
        try:
            worker.request_resume()
        except Exception as exc:
            QMessageBox.warning(self, "继续失败", str(exc))
            return
        self._refresh_interactive_state()
        self.statusBar().showMessage(f"{worker.task_label}已继续。", 5000)

    def cancel_active_task(self) -> None:
        worker = self._active_background_worker
        if worker is None:
            self.statusBar().showMessage("当前没有可终止的后台任务。", 4000)
            return
        try:
            worker.request_cancel()
        except Exception as exc:
            QMessageBox.warning(self, "终止失败", str(exc))
            return
        self._refresh_interactive_state()
        self.statusBar().showMessage(f"正在终止{worker.task_label}...", 0)

    def refresh_views(self) -> None:
        project = self.context.current_project
        self._update_window_title()
        self.timeline_page.load_project(project)
        self._sync_timeline_preview(project)
        self.translation_page.load_project(project, self.context.settings)
        self.dubbing_page.load_project(project, self.context.settings)
        self.export_page.load_project(project, self.context.settings)














    def _dependency_rows(self) -> list[tuple[str, str, str]]:
        ffmpeg_target = self.context.settings.media.ffmpeg_path or "ffmpeg"
        ffmpeg_path = resolve_ffmpeg_path(ffmpeg_target)
        ffmpeg_status = "已就绪" if ffmpeg_path else "缺失"
        ffmpeg_detail = ffmpeg_path or f"无法在 PATH 中找到“{ffmpeg_target}”"

        asr_available = importlib.util.find_spec("faster_whisper") is not None
        asr_status = "已就绪" if asr_available else "缺失"
        asr_detail = f"{self.context.settings.asr.model_name} / {self.context.settings.asr.device}"

        translation_ready = all(
            [
                self.context.settings.translation.base_url,
                self.context.settings.translation.model,
                self.context.settings.translation.api_key,
            ]
        )
        translation_status = "已配置" if translation_ready else "未配置"
        translation_detail = (
            f"{self.context.settings.translation.provider_type} / {self.context.settings.translation.model}"
        )

        tts_ready, tts_runtime_detail = tts_provider_runtime_status(self.context.settings.tts.provider_type)
        tts_status = "已就绪" if tts_ready else "缺失"
        tts_detail = (
            f"{tts_provider_display_name(self.context.settings.tts.provider_type)} / "
            f"默认音色：{self.context.settings.tts.default_voice or '未设置'} / {tts_runtime_detail}"
        )
        return [
            ("ffmpeg", ffmpeg_status, ffmpeg_detail),
            ("中文 ASR", asr_status, asr_detail),
            ("翻译模型", translation_status, translation_detail),
            ("英文配音", tts_status, tts_detail),
        ]








    # =================================================================
    # [已注释] 仅应用音色：只给选中片段指定音色、不生成配音。
    # 与“生成配音（自动应用当前音色）”功能重叠，暂时移除；
    # 恢复时取消本方法及 pages.py / 信号连接 / 状态刷新处的注释即可。
    # =================================================================
#     def apply_voice_to_selected_segments(self) -> None:
#         if not self._require_idle_background("调整配音音色"):
#             return
#         selected_rows = self._active_dubbing_rows()
#         if not selected_rows:
#             QMessageBox.information(
#                 self,
#                 "没有选中配音行",
#                 "请先勾选片段，或先在配音表中选中一行或多行。",
#             )
#             return
#         voice_id = self.dubbing_page.current_voice_id()
#         if not voice_id:
#             QMessageBox.information(
#                 self,
#                 "没有可用音色",
#                 "当前没有选中的英文音色。",
#             )
#             return
#
#         updated_count = apply_voice_to_segments(
#             self.context.current_project.segments,
#             selected_rows,
#             voice_id,
#             invalidate_segment_dub=self._invalidate_segment_dub,
#         )
#
#         if updated_count:
#             self._mark_project_dirty()
#         self.refresh_views()
#         if updated_count:
#             self.statusBar().showMessage(f"已为 {updated_count} 个片段应用当前音色。", 5000)
#         else:
#             self.statusBar().showMessage("所选片段已经使用当前音色。", 4000)
#
















































    def _background_job_in_progress(self) -> bool:
        return (
            self._analysis_in_progress()
            or self._translation_in_progress()
            or self._dubbing_in_progress()
            or self._export_in_progress()
        )

    def _require_idle_background(self, action_text: str) -> bool:
        if not self._background_job_in_progress():
            return True
        QMessageBox.information(
            self,
            "后台任务进行中",
            f"请等待当前后台任务完成后再{action_text}。",
        )
        return False

    def _refresh_interactive_state(self) -> None:
        background_busy = self._background_job_in_progress()
        project = self.context.current_project
        active_worker = self._active_background_worker if background_busy else None

        if active_worker is None:
            self.background_task_label.setText("后台任务：空闲")
            self.pause_task_button.setEnabled(False)
            self.resume_task_button.setEnabled(False)
            self.cancel_task_button.setEnabled(False)
        else:
            if active_worker.is_cancel_requested():
                state_text = "正在终止"
            elif active_worker.is_paused():
                state_text = "已暂停"
            else:
                state_text = "运行中"
            self.background_task_label.setText(
                f"后台任务：{active_worker.task_label}（{state_text}）"
            )
            self.pause_task_button.setEnabled(
                active_worker.supports_pause()
                and not active_worker.is_paused()
                and not active_worker.is_cancel_requested()
            )
            self.resume_task_button.setEnabled(
                active_worker.supports_pause()
                and active_worker.is_paused()
                and not active_worker.is_cancel_requested()
            )
            self.cancel_task_button.setEnabled(
                active_worker.supports_cancel()
                and not active_worker.is_cancel_requested()
            )

        self.settings_page.top_save_button.setEnabled(not background_busy)
        self.settings_page.top_reset_button.setEnabled(not background_busy)
        self.settings_page.asr_runtime_check_button.setEnabled(not background_busy)

        self.timeline_page.set_analysis_running(self._analysis_in_progress())
        self.timeline_page.set_preview_enabled(bool(project.video_path))
        if not self._analysis_in_progress():
            has_segments = bool(project.segments)
            has_suggestions = bool(project.cut_suggestions)
            selected_suggestion_rows = self.timeline_page.selected_suggestion_rows()
            self.timeline_page.analyze_button.setEnabled(bool(project.video_path) and not background_busy)
            self.timeline_page.generate_suggestions_button.setEnabled(has_segments and not background_busy)
            self.timeline_page.accept_selected_button.setEnabled(
                bool(selected_suggestion_rows) and not background_busy
            )
            self.timeline_page.clear_selected_button.setEnabled(
                bool(selected_suggestion_rows) and not background_busy
            )
            self.timeline_page.accept_all_button.setEnabled(has_suggestions and not background_busy)
            self.timeline_page.reject_all_button.setEnabled(has_suggestions and not background_busy)
            has_single_suggestion = len(selected_suggestion_rows) == 1
            self.timeline_page.suggestion_start_time_edit.setEnabled(has_single_suggestion and not background_busy)
            self.timeline_page.suggestion_end_time_edit.setEnabled(has_single_suggestion and not background_busy)
            self.timeline_page.use_current_as_start_button.setEnabled(has_single_suggestion and not background_busy)
            self.timeline_page.use_current_as_end_button.setEnabled(has_single_suggestion and not background_busy)
            self.timeline_page.apply_suggestion_range_button.setEnabled(has_single_suggestion and not background_busy)

        self.translation_page.set_translation_running(self._translation_in_progress())
        self.translation_page.set_proofread_undo_available(
            self._proofread_snapshot_has_live_changes() and not background_busy
        )
        if not self._translation_in_progress():
            has_segments = bool(project.segments)
            self.translation_page.translate_all_button.setEnabled(has_segments and not background_busy)
            selected_rows = self.translation_page.selected_rows()
            self.translation_page.translate_selected_button.setEnabled(bool(selected_rows) and not background_busy)
            self.translation_page.proofread_source_button.setEnabled(has_segments and not background_busy)
            self.translation_page.import_source_subtitle_button.setEnabled(not background_busy)
            self.translation_page.import_translation_subtitle_button.setEnabled(has_segments and not background_busy)
            self.translation_page.export_subtitle_button.setEnabled(has_segments and not background_busy)
            self.translation_page.save_button.setEnabled(not background_busy)
            self.translation_page.test_translation_button.setEnabled(not background_busy)

        self.dubbing_page.set_dubbing_running(self._dubbing_in_progress())
        self.dubbing_page.stop_button.setEnabled(winsound is not None)
        if not self._dubbing_in_progress():
            selected_rows = self._active_dubbing_rows()
            selected_table_rows = self.dubbing_page.selected_rows()
            has_segments = bool(project.segments)
            # self.dubbing_page.apply_voice_button.setEnabled(bool(selected_rows) and not background_busy)
            self.dubbing_page.generate_button.setEnabled(bool(selected_rows) and not background_busy)
            self.dubbing_page.preview_button.setEnabled(not background_busy)
            self.dubbing_page.check_selected_button.setEnabled(bool(selected_table_rows) and not background_busy)
            self.dubbing_page.uncheck_selected_button.setEnabled(bool(selected_table_rows) and not background_busy)
            self.dubbing_page.check_all_button.setEnabled(has_segments and not background_busy)
            self.dubbing_page.uncheck_all_button.setEnabled(has_segments and not background_busy)

        self.export_page.set_export_running(self._export_in_progress())
        if not self._export_in_progress():
            self.export_page.export_button.setEnabled(
                bool(project.video_path)
                and not self._analysis_in_progress()
                and not self._translation_in_progress()
                and not self._dubbing_in_progress()
                and not self._export_in_progress()
            )

































    def closeEvent(self, event: QCloseEvent) -> None:
        if self._background_job_in_progress():
            QMessageBox.information(
                self,
                "后台任务进行中",
                "请等待当前后台任务完成后再关闭应用。",
            )
            event.ignore()
            return
        if self.context.project_dirty:
            reply = QMessageBox.question(
                self,
                "项目尚未保存",
                "当前项目有未保存修改。关闭前要先保存吗？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.StandardButton.Save and not self.save_project():
                event.ignore()
                return
        super().closeEvent(event)
