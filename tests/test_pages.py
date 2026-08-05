from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vcut_studio.models import Project, Segment
from vcut_studio.settings import AppSettings
from vcut_studio.ui.pages import TimelinePage


class TimelinePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_subtitles_share_the_video_graphics_scene(self) -> None:
        page = TimelinePage()
        project = Project(
            project_id="project",
            name="Demo",
            segments=[
                Segment(
                    segment_id="segment",
                    start_ms=1_000,
                    end_ms=2_000,
                    zh_text="中文字幕",
                    en_text="English subtitle",
                )
            ],
        )
        settings = AppSettings()
        settings.export.subtitle_mode = "bilingual"

        page.load_project(project, settings)
        page.set_preview_position(1_500, 3_000)

        self.assertIs(page.video_item.scene(), page.video_scene)
        self.assertIs(page.preview_chinese_subtitle_item.scene(), page.video_scene)
        self.assertIs(page.preview_english_subtitle_item.scene(), page.video_scene)
        self.assertGreater(page.preview_chinese_subtitle_item.zValue(), page.video_item.zValue())
        self.assertGreater(page.preview_english_subtitle_item.zValue(), page.video_item.zValue())
        self.assertEqual(page.preview_chinese_subtitle_item.toPlainText(), "中文字幕")
        self.assertEqual(page.preview_english_subtitle_item.toPlainText(), "English subtitle")
        self.assertTrue(page.preview_chinese_subtitle_item.isVisible())
        self.assertTrue(page.preview_english_subtitle_item.isVisible())

    def test_play_pause_uses_one_toggle_button(self) -> None:
        page = TimelinePage()
        page.set_preview_enabled(True)

        page.set_preview_playing(True)
        self.assertEqual(page.play_pause_button.text(), "暂停")
        self.assertTrue(page.play_pause_button.isEnabled())

        page.set_preview_playing(False)
        self.assertEqual(page.play_pause_button.text(), "播放")
        self.assertTrue(page.play_pause_button.isEnabled())

    def test_light_theme_updates_video_letterbox_and_waveform(self) -> None:
        page = TimelinePage()

        page.set_theme("light")

        self.assertEqual(page.video_scene.backgroundBrush().color().name().upper(), "#D7DEE7")
        self.assertEqual(page.audio_track_widget._theme, "light")


if __name__ == "__main__":
    unittest.main()
