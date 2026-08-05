from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QTableWidget, QWidget

from ..providers.tts import all_tts_voices


def set_combo_value(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index < 0:
        index = combo.findText(value)
    if index >= 0:
        combo.setCurrentIndex(index)
    elif combo.isEditable():
        combo.setEditText(value)


def configure_resizable_columns(table: QTableWidget, widths: list[int]) -> None:
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(72)
    header.setCascadingSectionResizes(False)
    for column_index in range(table.columnCount()):
        header.setSectionResizeMode(column_index, QHeaderView.ResizeMode.Interactive)
        if column_index < len(widths):
            table.setColumnWidth(column_index, widths[column_index])


def build_inline_row(*widgets: QWidget) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def format_timestamp(ms: int) -> str:
    total_ms = max(0, ms)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def timestamp_to_qtime(ms: int) -> QTime:
    total_ms = max(0, int(ms))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return QTime(hours % 24, minutes, seconds, milliseconds)


def qtime_to_timestamp(value: QTime) -> int:
    return max(0, value.msecsSinceStartOfDay())


def format_suggestion_reason(reason: str, details: str) -> str:
    if reason == "filler_word":
        return f"语气词：{details}" if details else "语气词"
    if reason == "long_pause":
        return f"长停顿：{details}" if details else "长停顿"
    if reason == "silent_range":
        return f"无声/无人声：{details}" if details else "无声/无人声"
    return details or reason


def format_suggestion_type(reason: str) -> str:
    if reason == "filler_word":
        return "口癖"
    if reason == "long_pause":
        return "停顿"
    if reason == "silent_range":
        return "无声/无人声"
    return "其他"


def suggestion_filter_matches(reason: str, filter_value: str) -> bool:
    normalized = str(filter_value or "").strip().lower()
    if normalized in {"", "all"}:
        return True
    return reason == normalized


def format_internal_status(status: str) -> str:
    status_map = {
        "pending": "待处理",
        "translated": "已翻译",
        "edited": "已编辑",
        "completed": "已完成",
        "failed": "失败",
        "generating": "生成中",
    }
    return status_map.get(status, status)


def format_voice_label(voice_id: str | None) -> str:
    normalized = (voice_id or "").strip()
    if not normalized:
        return "未指定"
    for voice in all_tts_voices():
        if voice.voice_id == normalized:
            return voice.label
    if normalized.startswith("system:"):
        return normalized.split(":", 1)[1].strip() or normalized
    return normalized


def segment_overlap_ms(start_ms: int, end_ms: int, suggestions: list[object]) -> int:
    """Total overlap of [start_ms, end_ms] with accepted suggestion ranges."""
    accepted_ranges = [
        (max(0, int(getattr(suggestion, "start_ms", 0))), max(0, int(getattr(suggestion, "end_ms", 0))))
        for suggestion in suggestions
        if bool(getattr(suggestion, "accepted", False))
    ]
    accepted_ranges = [(start, end) for start, end in accepted_ranges if end > start]
    if not accepted_ranges:
        return 0

    accepted_ranges.sort(key=lambda item: (item[0], item[1]))
    merged: list[tuple[int, int]] = []
    for range_start, range_end in accepted_ranges:
        if not merged or range_start > merged[-1][1]:
            merged.append((range_start, range_end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, range_end))

    overlap_ms = 0
    for range_start, range_end in merged:
        overlap_start = max(start_ms, range_start)
        overlap_end = min(end_ms, range_end)
        if overlap_end > overlap_start:
            overlap_ms += overlap_end - overlap_start
    return overlap_ms
