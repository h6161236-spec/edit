# -*- coding: utf-8 -*-
"""Split MainWindow into responsibility-based mixins.

Generates:
  ui/actions/project_actions.py     ProjectActionsMixin
  ui/actions/preview_actions.py     PreviewActionsMixin
  ui/actions/analysis_actions.py    AnalysisActionsMixin
  ui/actions/translation_actions.py TranslationActionsMixin
  ui/actions/dubbing_actions.py     DubbingActionsMixin
  ui/actions/export_actions.py      ExportActionsMixin
  ui/actions/settings_actions.py    SettingsActionsMixin

and rewrites ui/main_window.py to compose them.
"""
import ast
import re
from pathlib import Path

SRC = Path('src/vcut_studio/ui/main_window.py')
OUT_DIR = Path('src/vcut_studio/ui/actions')

# 方法归属表：(方法名 -> mixin 名)
OWNERSHIP = {
    # ---- ProjectActionsMixin ----
    'new_project': 'ProjectActionsMixin',
    'import_video': 'ProjectActionsMixin',
    'open_project': 'ProjectActionsMixin',
    'save_project': 'ProjectActionsMixin',
    'save_project_as': 'ProjectActionsMixin',
    '_save_project_to_path': 'ProjectActionsMixin',
    '_confirm_project_switch': 'ProjectActionsMixin',
    '_configure_autosave_timer': 'ProjectActionsMixin',
    '_update_window_title': 'ProjectActionsMixin',
    '_mark_project_dirty': 'ProjectActionsMixin',
    '_mark_project_saved': 'ProjectActionsMixin',
    '_auto_save_project_snapshot': 'ProjectActionsMixin',
    # ---- PreviewActionsMixin ----
    '_sync_timeline_preview': 'PreviewActionsMixin',
    '_sync_preview_audio_device': 'PreviewActionsMixin',
    'set_preview_volume': 'PreviewActionsMixin',
    'set_preview_muted': 'PreviewActionsMixin',
    '_resolve_preview_source_path': 'PreviewActionsMixin',
    'play_preview': 'PreviewActionsMixin',
    'pause_preview': 'PreviewActionsMixin',
    'stop_preview': 'PreviewActionsMixin',
    'seek_preview': 'PreviewActionsMixin',
    '_on_preview_position_changed': 'PreviewActionsMixin',
    '_on_preview_duration_changed': 'PreviewActionsMixin',
    '_on_preview_playback_state_changed': 'PreviewActionsMixin',
    '_on_preview_error': 'PreviewActionsMixin',
    # ---- AnalysisActionsMixin ----
    'analyze_video': 'AnalysisActionsMixin',
    'generate_cut_suggestions_for_project': 'AnalysisActionsMixin',
    'accept_selected_suggestions': 'AnalysisActionsMixin',
    'clear_selected_suggestions': 'AnalysisActionsMixin',
    'accept_all_suggestions': 'AnalysisActionsMixin',
    'clear_suggestion_acceptance': 'AnalysisActionsMixin',
    'set_suggestion_acceptance': 'AnalysisActionsMixin',
    '_set_suggestion_rows_acceptance': 'AnalysisActionsMixin',
    'update_suggestion_range': 'AnalysisActionsMixin',
    'locate_selected_suggestion': 'AnalysisActionsMixin',
    'locate_selected_segment': 'AnalysisActionsMixin',
    '_analysis_in_progress': 'AnalysisActionsMixin',
    '_on_analysis_progress': 'AnalysisActionsMixin',
    '_on_analysis_finished': 'AnalysisActionsMixin',
    '_on_analysis_error': 'AnalysisActionsMixin',
    '_on_analysis_cancelled': 'AnalysisActionsMixin',
    '_cleanup_analysis_job': 'AnalysisActionsMixin',
    # ---- TranslationActionsMixin ----
    'translate_all_segments': 'TranslationActionsMixin',
    'translate_selected_segments': 'TranslationActionsMixin',
    'proofread_source_segments': 'TranslationActionsMixin',
    'undo_last_source_proofread': 'TranslationActionsMixin',
    'import_source_subtitles': 'TranslationActionsMixin',
    'import_translation_subtitles': 'TranslationActionsMixin',
    'export_translation_subtitles': 'TranslationActionsMixin',
    'test_translation_config': 'TranslationActionsMixin',
    'preview_translation_time': 'TranslationActionsMixin',
    'update_segment_english_text': 'TranslationActionsMixin',
    'update_segment_chinese_text': 'TranslationActionsMixin',
    '_choose_subtitle_file': 'TranslationActionsMixin',
    '_replace_project_segments_from_cues': 'TranslationActionsMixin',
    '_apply_translation_cues_to_segments': 'TranslationActionsMixin',
    '_translation_requests_for_rows': 'TranslationActionsMixin',
    '_start_translation_job': 'TranslationActionsMixin',
    '_start_source_proofread_job': 'TranslationActionsMixin',
    '_apply_source_corrections': 'TranslationActionsMixin',
    '_apply_translation_batch': 'TranslationActionsMixin',
    '_clear_proofread_snapshot': 'TranslationActionsMixin',
    '_has_proofread_undo_available': 'TranslationActionsMixin',
    '_segment_matches_proofread_snapshot': 'TranslationActionsMixin',
    '_proofread_snapshot_has_live_changes': 'TranslationActionsMixin',
    '_clear_proofread_snapshot_if_rows_touched': 'TranslationActionsMixin',
    '_on_source_proofread_partial_results': 'TranslationActionsMixin',
    '_on_source_proofread_finished': 'TranslationActionsMixin',
    '_on_translation_partial_results': 'TranslationActionsMixin',
    '_on_translation_progress': 'TranslationActionsMixin',
    '_on_translation_finished': 'TranslationActionsMixin',
    '_on_translation_test_finished': 'TranslationActionsMixin',
    '_on_translation_error': 'TranslationActionsMixin',
    '_on_translation_cancelled': 'TranslationActionsMixin',
    '_on_source_proofread_error': 'TranslationActionsMixin',
    '_on_source_proofread_cancelled': 'TranslationActionsMixin',
    '_cleanup_translation_job': 'TranslationActionsMixin',
    '_translation_in_progress': 'TranslationActionsMixin',
    # ---- DubbingActionsMixin ----
    'generate_selected_dubs': 'DubbingActionsMixin',
    'preview_selected_voice': 'DubbingActionsMixin',
    'stop_dub_playback': 'DubbingActionsMixin',
    'play_generated_dub': 'DubbingActionsMixin',
    '_active_dubbing_rows': 'DubbingActionsMixin',
    'set_dub_row_checked': 'DubbingActionsMixin',
    '_set_dub_rows_checked': 'DubbingActionsMixin',
    'check_selected_dub_rows': 'DubbingActionsMixin',
    'uncheck_selected_dub_rows': 'DubbingActionsMixin',
    'check_all_dub_rows': 'DubbingActionsMixin',
    'uncheck_all_dub_rows': 'DubbingActionsMixin',
    '_build_dubbing_job_settings': 'DubbingActionsMixin',
    '_tts_cache_signature': 'DubbingActionsMixin',
    '_invalidate_segment_dub': 'DubbingActionsMixin',
    '_invalidate_all_dubs': 'DubbingActionsMixin',
    '_play_audio_file': 'DubbingActionsMixin',
    '_stop_audio_playback': 'DubbingActionsMixin',
    '_dubbing_in_progress': 'DubbingActionsMixin',
    '_on_dubbing_progress': 'DubbingActionsMixin',
    '_on_dubbing_finished': 'DubbingActionsMixin',
    '_on_dubbing_preview_ready': 'DubbingActionsMixin',
    '_on_dubbing_error': 'DubbingActionsMixin',
    '_on_dubbing_cancelled': 'DubbingActionsMixin',
    '_cleanup_dubbing_job': 'DubbingActionsMixin',
    # ---- ExportActionsMixin ----
    'start_export': 'ExportActionsMixin',
    '_export_in_progress': 'ExportActionsMixin',
    '_on_export_progress': 'ExportActionsMixin',
    '_on_export_finished': 'ExportActionsMixin',
    '_on_export_error': 'ExportActionsMixin',
    '_on_export_cancelled': 'ExportActionsMixin',
    '_cleanup_export_job': 'ExportActionsMixin',
    # ---- SettingsActionsMixin ----
    'save_settings': 'SettingsActionsMixin',
    'reset_settings': 'SettingsActionsMixin',
    'scan_dependencies': 'SettingsActionsMixin',
    'show_settings_dialog': 'SettingsActionsMixin',
    'show_export_dialog': 'SettingsActionsMixin',
    'show_asr_runtime_diagnostics': 'SettingsActionsMixin',
    'browse_asr_cache_dir': 'SettingsActionsMixin',
    'browse_asr_local_model_dir': 'SettingsActionsMixin',
    'browse_export_output_dir': 'SettingsActionsMixin',
}

# 留在 MainWindow 的方法（核心/骨架/任务管理/状态刷新）
CORE_METHODS = {
    '__init__', '_apply_window_icon', '_apply_workspace_style', '_build_status_controls',
    '_create_menu', '_connect_signals',
    '_set_active_background_worker', '_start_background_job', '_current_background_task_label',
    'pause_active_task', 'resume_active_task', 'cancel_active_task',
    'refresh_views', '_set_task_progress', '_clear_task_progress', '_notify_task_finished',
    '_background_job_in_progress', '_require_idle_background', '_refresh_interactive_state',
    '_dependency_rows', 'closeEvent',
}

def main() -> None:
    src_text = SRC.read_text(encoding='utf-8')
    tree = ast.parse(src_text)
    main_window_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
            main_window_node = node
            break
    assert main_window_node is not None

    methods: dict[str, tuple[int, int]] = {}
    for item in main_window_node.body:
        if isinstance(item, ast.FunctionDef):
            methods[item.name] = (item.lineno, item.end_lineno)

    # 校验：归属表覆盖所有非核心方法，且无遗漏
    owned = set(OWNERSHIP)
    core = set(CORE_METHODS)
    all_names = set(methods)
    missing = all_names - owned - core
    assert not missing, f'未归属的方法: {sorted(missing)}'
    unused = owned - all_names
    assert not unused, f'归属表中不存在的方法: {sorted(unused)}'
    # 重名检查（同一方法不能出现在两个 mixin）
    assert len(owned) == len(all_names - core)

    lines = src_text.splitlines(keepends=True)

    def method_source(name: str) -> str:
        start, end = methods[name]
        block = ''.join(lines[start - 1:end])
        # 去掉 4 空格类体缩进
        dedented = ''.join(line[4:] if line.startswith('    ') else line for line in block.splitlines(keepends=True))
        return dedented

    mixin_methods: dict[str, list[str]] = {}
    for name, mixin in OWNERSHIP.items():
        mixin_methods.setdefault(mixin, []).append(name)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    file_names = {
        'ProjectActionsMixin': 'project_actions.py',
        'PreviewActionsMixin': 'preview_actions.py',
        'AnalysisActionsMixin': 'analysis_actions.py',
        'TranslationActionsMixin': 'translation_actions.py',
        'DubbingActionsMixin': 'dubbing_actions.py',
        'ExportActionsMixin': 'export_actions.py',
        'SettingsActionsMixin': 'settings_actions.py',
    }
    header_template = '''"""VCut Studio - {title} (MainWindow mixin).

Extracted from ui/main_window.py to keep the window class focused on
composition and shared state. Methods reference `self` attributes that are
created in MainWindow.__init__ (pages, context, threads, busy flags).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, QUrl
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..models import ExportJob, Project
from ..subtitles import SubtitleCueData, read_subtitle_file, write_subtitle_file
from ..providers.translation import TranslationRequest
from ..providers.tts import tts_provider_display_name, tts_provider_runtime_status
from .dubbing_logic import apply_voice_to_segments, pick_voice_preview_text
from .pages_formatting import format_voice_label


class {mixin}:
    """{title} actions for the main window."""
'''

    for mixin, names in mixin_methods.items():
        title = mixin.replace('Mixin', '')
        body_parts = [header_template.format(title=title, mixin=mixin)]
        for name in names:
            body_parts.append(method_source(name))
            body_parts.append('\n')
        (OUT_DIR / file_names[mixin]).write_text(''.join(body_parts), encoding='utf-8')
        print(f'{file_names[mixin]}: {len(names)} methods')

    # 从 MainWindow 中删除已归属的方法，改写类定义与 import
    new_src_lines = []
    skip_lines: set[int] = set()
    for name in OWNERSHIP:
        start, end = methods[name]
        skip_lines.update(range(start, end + 1))
        # 方法前的空行（通常 1-2 行）也跳过，保持整洁
        if start - 2 >= 1 and lines[start - 2].strip() == '':
            skip_lines.add(start - 2)
        if start - 1 >= 1 and lines[start - 1].strip() == '':
            skip_lines.add(start - 1)

    for idx, line in enumerate(lines, start=1):
        if idx not in skip_lines:
            new_src_lines.append(line)
    new_src = ''.join(new_src_lines)

    # 类定义：加入 mixin 继承
    old_class = 'class MainWindow(QMainWindow):'
    assert new_src.count(old_class) == 1
    mixin_imports = '\n'.join(
        f'from .actions.{file_names[m]} import {m}' for m in file_names
    )
    new_class = (
        'from .actions.dubbing_actions import DubbingActionsMixin\n'
        'from .actions.export_actions import ExportActionsMixin\n'
        'from .actions.analysis_actions import AnalysisActionsMixin\n'
        'from .actions.project_actions import ProjectActionsMixin\n'
        'from .actions.preview_actions import PreviewActionsMixin\n'
        'from .actions.settings_actions import SettingsActionsMixin\n'
        'from .actions.translation_actions import TranslationActionsMixin\n'
        '\n'
        '\n'
        'class MainWindow(\n'
        '    ProjectActionsMixin,\n'
        '    PreviewActionsMixin,\n'
        '    AnalysisActionsMixin,\n'
        '    TranslationActionsMixin,\n'
        '    DubbingActionsMixin,\n'
        '    ExportActionsMixin,\n'
        '    SettingsActionsMixin,\n'
        '    QMainWindow,\n'
        '):'
    )
    new_src = new_src.replace(old_class, new_class)
    SRC.write_text(new_src, encoding='utf-8')
    print('main_window.py rewritten')


if __name__ == '__main__':
    main()
