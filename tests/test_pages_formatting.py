from __future__ import annotations

import unittest

from vcut_studio.ui.pages_formatting import (
    format_internal_status,
    format_suggestion_reason,
    format_suggestion_type,
    format_timestamp,
    segment_overlap_ms,
    suggestion_filter_matches,
    timestamp_to_qtime,
)


class FormattingFunctionTests(unittest.TestCase):
    def test_format_timestamp(self) -> None:
        self.assertEqual(format_timestamp(0), "00:00:00.000")
        self.assertEqual(format_timestamp(3_654_321), "01:00:54.321")
        self.assertEqual(format_timestamp(-5), "00:00:00.000")

    def test_timestamp_to_qtime_round_trips(self) -> None:
        value = timestamp_to_qtime(3_654_321)
        self.assertEqual(value.hour(), 1)
        self.assertEqual(value.minute(), 0)
        self.assertEqual(value.second(), 54)
        self.assertEqual(value.msec(), 321)

    def test_format_suggestion_reason(self) -> None:
        self.assertEqual(format_suggestion_reason("filler_word", "嗯"), "语气词：嗯")
        self.assertEqual(format_suggestion_reason("long_pause", ""), "长停顿")
        self.assertEqual(format_suggestion_reason("unknown", "raw"), "raw")

    def test_format_suggestion_type(self) -> None:
        self.assertEqual(format_suggestion_type("filler_word"), "口癖")
        self.assertEqual(format_suggestion_type("long_pause"), "停顿")
        self.assertEqual(format_suggestion_type("silent_range"), "无声/无人声")
        self.assertEqual(format_suggestion_type("other"), "其他")

    def test_suggestion_filter_matches(self) -> None:
        self.assertTrue(suggestion_filter_matches("filler_word", ""))
        self.assertTrue(suggestion_filter_matches("filler_word", "all"))
        self.assertTrue(suggestion_filter_matches("filler_word", "filler_word"))
        self.assertFalse(suggestion_filter_matches("long_pause", "filler_word"))

    def test_format_internal_status(self) -> None:
        self.assertEqual(format_internal_status("pending"), "待处理")
        self.assertEqual(format_internal_status("generating"), "生成中")
        self.assertEqual(format_internal_status("weird"), "weird")

    def test_segment_overlap_ms_merges_adjacent_accepted_ranges(self) -> None:
        class Suggestion:
            def __init__(self, start_ms: int, end_ms: int, accepted: bool) -> None:
                self.start_ms = start_ms
                self.end_ms = end_ms
                self.accepted = accepted

        suggestions = [
            Suggestion(100, 300, True),
            Suggestion(280, 400, True),  # overlaps previous -> merged
            Suggestion(900, 1000, False),  # not accepted -> ignored
        ]
        # [100,400] overlaps [50,350] on [100,350] -> 250ms
        self.assertEqual(segment_overlap_ms(50, 350, suggestions), 250)
        self.assertEqual(segment_overlap_ms(0, 0, suggestions), 0)


if __name__ == "__main__":
    unittest.main()
