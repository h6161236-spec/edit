from __future__ import annotations

import unittest
from pathlib import Path

from vcut_studio.models import Project, Segment
from vcut_studio.ui.actions.project_actions import import_kind_for_path, project_has_active_content


class ProjectImportHelpersTests(unittest.TestCase):
    def test_import_kind_recognizes_project_and_video_files_case_insensitively(self) -> None:
        self.assertEqual(import_kind_for_path("demo.vcutproj"), "project")
        self.assertEqual(import_kind_for_path("DEMO.MP4"), "video")
        self.assertEqual(import_kind_for_path("clip.webm"), "video")
        self.assertIsNone(import_kind_for_path("notes.txt"))

    def test_active_project_detection_covers_saved_and_in_memory_work(self) -> None:
        project = Project.new("Demo")
        self.assertFalse(project_has_active_content(project, None))

        project.video_path = "demo.mp4"
        self.assertTrue(project_has_active_content(project, None))

        project.video_path = ""
        project.segments.append(Segment(segment_id="segment", start_ms=0, end_ms=1000))
        self.assertTrue(project_has_active_content(project, None))

        project.segments.clear()
        self.assertTrue(project_has_active_content(project, Path("demo.vcutproj")))


if __name__ == "__main__":
    unittest.main()
