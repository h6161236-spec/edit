"""VCut Studio - PreviewActions (MainWindow mixin).

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
from PySide6.QtMultimedia import QMediaDevices, QMediaPlayer
from ...media import build_preview_proxy_media, extract_audio_waveform, preview_proxy_required


class PreviewActionsMixin:
    """PreviewActions actions for the main window."""

    def _sync_timeline_preview(self, project: Project) -> None:
        video_path = str(project.video_path or "").strip()
        duration_ms = int(project.source_duration_ms or project.media_info.duration_ms or 0)
        self.timeline_page.set_preview_enabled(bool(video_path))
        self.timeline_page.set_waveform_data(duration_ms, [])
        self.timeline_page.set_focus_range(None, None)

        if not video_path:
            self.preview_player.stop()
            self.preview_player.setSource(QUrl())
            self._preview_source_path = ""
            self.timeline_page.set_preview_position(0, 0)
            return

        preview_source_path = self._resolve_preview_source_path(project)
        if preview_source_path != self._preview_source_path:
            self.preview_player.stop()
            self.preview_player.setSource(QUrl.fromLocalFile(preview_source_path))
            self._preview_source_path = preview_source_path

        waveform_points = self._waveform_cache.get(video_path)
        if waveform_points is None and project.media_info.has_audio:
            try:
                waveform_points = extract_audio_waveform(
                    video_path,
                    self.context.settings.media.ffmpeg_path,
                )
            except Exception:
                waveform_points = []
            self._waveform_cache[video_path] = waveform_points

        self.timeline_page.set_waveform_data(duration_ms, waveform_points or [])
        self.timeline_page.set_preview_position(self.preview_player.position(), duration_ms)

    def _sync_preview_audio_device(self) -> None:
        try:
            device = QMediaDevices.defaultAudioOutput()
            if not device.isNull():
                self.preview_audio_output.setDevice(device)
        except Exception:
            pass
        self.timeline_page.set_preview_audio_state(
            round(self.preview_audio_output.volume() * 100),
            self.preview_audio_output.isMuted(),
        )

    def set_preview_volume(self, value: int) -> None:
        clamped = max(0, min(int(value), 100))
        self.preview_audio_output.setVolume(clamped / 100.0)
        if clamped > 0 and self.preview_audio_output.isMuted():
            self.preview_audio_output.setMuted(False)
        self.timeline_page.set_preview_audio_state(clamped, self.preview_audio_output.isMuted())

    def set_preview_muted(self, muted: bool) -> None:
        self.preview_audio_output.setMuted(bool(muted))
        self.timeline_page.set_preview_audio_state(
            round(self.preview_audio_output.volume() * 100),
            self.preview_audio_output.isMuted(),
        )

    def _resolve_preview_source_path(self, project: Project) -> str:
        source_path = str(project.video_path or "").strip()
        if not source_path:
            return ""
        cached_proxy_path = self._preview_proxy_cache.get(source_path)
        if cached_proxy_path and Path(cached_proxy_path).exists():
            return cached_proxy_path
        if source_path in self._preview_proxy_failures:
            return source_path
        if not preview_proxy_required(source_path, project.media_info):
            return source_path

        try:
            preview_path = build_preview_proxy_media(
                source_path,
                project.media_info,
                self.context.settings.media.ffmpeg_path,
                Path(self.context.settings.workspace.temp_dir) / "preview_media",
            )
        except Exception as exc:
            self._preview_proxy_failures.add(source_path)
            self.statusBar().showMessage(f"监看预览兼容处理失败，已继续使用原视频：{exc}", 8000)
            return source_path

        self._preview_proxy_cache[source_path] = str(preview_path)
        self._preview_proxy_failures.discard(source_path)
        self.statusBar().showMessage(
            f"已为视频监看切换到兼容预览源：{Path(preview_path).name}",
            5000,
        )
        return str(preview_path)

    def play_preview(self) -> None:
        if not self.context.current_project.video_path:
            self.statusBar().showMessage("请先导入视频。", 4000)
            return
        self.preview_player.play()

    def pause_preview(self) -> None:
        if self.preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.preview_player.pause()
        else:
            self.preview_player.play()

    def stop_preview(self) -> None:
        self.preview_player.stop()
        self.timeline_page.set_preview_position(0, self.preview_player.duration())

    def seek_preview(self, position_ms: int) -> None:
        if not self.context.current_project.video_path:
            return
        self.preview_player.setPosition(max(0, int(position_ms)))

    def _on_preview_position_changed(self, position_ms: int) -> None:
        self.timeline_page.set_preview_position(position_ms, self.preview_player.duration())

    def _on_preview_duration_changed(self, duration_ms: int) -> None:
        self.timeline_page.set_preview_position(self.preview_player.position(), duration_ms)

    def _on_preview_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.timeline_page.set_preview_playing(state == QMediaPlayer.PlaybackState.PlayingState)

    def _on_preview_error(self, _error: object, error_text: str) -> None:
        if error_text:
            self.statusBar().showMessage(f"视频监看不可用：{error_text}", 8000)

