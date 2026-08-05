from __future__ import annotations

import unittest

from PySide6.QtCore import Qt

from vcut_studio.ui.theme import normalize_theme_mode, resolve_theme_mode, workspace_stylesheet


class ThemeTests(unittest.TestCase):
    def test_theme_mode_normalization(self) -> None:
        self.assertEqual(normalize_theme_mode("LIGHT"), "light")
        self.assertEqual(normalize_theme_mode("dark"), "dark")
        self.assertEqual(normalize_theme_mode("unknown"), "system")

    def test_system_theme_follows_qt_color_scheme(self) -> None:
        self.assertEqual(resolve_theme_mode("system", Qt.ColorScheme.Dark), "dark")
        self.assertEqual(resolve_theme_mode("system", Qt.ColorScheme.Light), "light")
        self.assertEqual(resolve_theme_mode("light", Qt.ColorScheme.Dark), "light")

    def test_light_stylesheet_updates_video_preview_background(self) -> None:
        stylesheet = workspace_stylesheet("light")

        self.assertIn("QGraphicsView#videoPreviewView", stylesheet)
        self.assertIn("#D7DEE7", stylesheet)


if __name__ == "__main__":
    unittest.main()
