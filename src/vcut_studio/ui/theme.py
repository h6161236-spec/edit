from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


THEME_MODES = {"system", "dark", "light"}


def normalize_theme_mode(value: object) -> str:
    normalized = str(value or "system").strip().lower()
    return normalized if normalized in THEME_MODES else "system"


def resolve_theme_mode(theme_mode: object, color_scheme: Qt.ColorScheme | None = None) -> str:
    normalized = normalize_theme_mode(theme_mode)
    if normalized in {"dark", "light"}:
        return normalized
    if color_scheme is None:
        app = QApplication.instance()
        color_scheme = app.styleHints().colorScheme() if app is not None else Qt.ColorScheme.Light
    return "dark" if color_scheme == Qt.ColorScheme.Dark else "light"


def application_palette(theme: str) -> QPalette:
    palette = QPalette()
    if theme == "light":
        colors = {
            QPalette.ColorRole.Window: "#EEF2F6",
            QPalette.ColorRole.WindowText: "#1E293B",
            QPalette.ColorRole.Base: "#FFFFFF",
            QPalette.ColorRole.AlternateBase: "#F5F7FA",
            QPalette.ColorRole.ToolTipBase: "#FFFFFF",
            QPalette.ColorRole.ToolTipText: "#0F172A",
            QPalette.ColorRole.Text: "#1E293B",
            QPalette.ColorRole.Button: "#E2E8F0",
            QPalette.ColorRole.ButtonText: "#0F172A",
            QPalette.ColorRole.BrightText: "#B91C1C",
            QPalette.ColorRole.Link: "#0284C7",
            QPalette.ColorRole.Highlight: "#0F766E",
            QPalette.ColorRole.HighlightedText: "#FFFFFF",
            QPalette.ColorRole.PlaceholderText: "#64748B",
        }
    else:
        colors = {
            QPalette.ColorRole.Window: "#161A1F",
            QPalette.ColorRole.WindowText: "#E5E7EB",
            QPalette.ColorRole.Base: "#11151B",
            QPalette.ColorRole.AlternateBase: "#18202A",
            QPalette.ColorRole.ToolTipBase: "#11151B",
            QPalette.ColorRole.ToolTipText: "#F8FAFC",
            QPalette.ColorRole.Text: "#E5E7EB",
            QPalette.ColorRole.Button: "#273445",
            QPalette.ColorRole.ButtonText: "#F3F4F6",
            QPalette.ColorRole.BrightText: "#FFFFFF",
            QPalette.ColorRole.Link: "#38BDF8",
            QPalette.ColorRole.Highlight: "#0F766E",
            QPalette.ColorRole.HighlightedText: "#FFFFFF",
            QPalette.ColorRole.PlaceholderText: "#7C8798",
        }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    return palette


def workspace_stylesheet(theme: str) -> str:
    if theme == "light":
        colors = {
            "window": "#EEF2F6",
            "chrome": "#FFFFFF",
            "panel": "#FFFFFF",
            "panel_hover": "#F1F5F9",
            "border": "#CBD5E1",
            "border_soft": "#D9E1EA",
            "text": "#1E293B",
            "strong": "#0F172A",
            "muted": "#475569",
            "input": "#FFFFFF",
            "button": "#E2E8F0",
            "button_hover": "#CBD5E1",
            "disabled": "#F1F5F9",
            "disabled_text": "#94A3B8",
            "alternate": "#F8FAFC",
            "header": "#E8EEF5",
            "scroll": "#94A3B8",
            "groove": "#D7E0EA",
            "handle": "#0284C7",
            "preview": "#D7DEE7",
        }
    else:
        colors = {
            "window": "#161A1F",
            "chrome": "#11151B",
            "panel": "#1C222B",
            "panel_hover": "#18202A",
            "border": "#2C3440",
            "border_soft": "#2F3946",
            "text": "#E5E7EB",
            "strong": "#F8FAFC",
            "muted": "#CBD5E1",
            "input": "#11151B",
            "button": "#273445",
            "button_hover": "#304259",
            "disabled": "#202734",
            "disabled_text": "#6B7280",
            "alternate": "#18202A",
            "header": "#202734",
            "scroll": "#334155",
            "groove": "#243140",
            "handle": "#7DD3FC",
            "preview": "#090C10",
        }

    return f"""
        QMainWindow, QDialog, QMessageBox {{
            background: {colors['window']};
            color: {colors['text']};
        }}
        QMenuBar, QMenu, QStatusBar, QToolTip {{
            background: {colors['chrome']};
            color: {colors['strong']};
            border: 1px solid {colors['border']};
        }}
        QTabWidget::pane {{
            border: 1px solid {colors['border']};
            border-radius: 10px;
            background: {colors['panel']};
            top: -1px;
        }}
        QTabBar::tab {{
            background: {colors['chrome']};
            color: {colors['muted']};
            border: 1px solid {colors['border']};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            padding: 8px 16px;
            margin-right: 6px;
        }}
        QTabBar::tab:selected {{ background: {colors['panel']}; color: {colors['strong']}; }}
        QTabBar::tab:hover:!selected {{ background: {colors['panel_hover']}; }}
        QWidget, QLabel {{ color: {colors['text']}; }}
        QFrame#settingsHeaderCard,
        QFrame#settingsSidebar,
        QFrame#settingsContent {{
            background: {colors['panel']};
            border: 1px solid {colors['border']};
            border-radius: 12px;
        }}
        QLabel#settingsHeaderTitle,
        QLabel#settingsSectionTitle {{
            color: {colors['strong']};
            font-size: 18px;
            font-weight: 700;
        }}
        QLabel#settingsNavTitle {{ color: {colors['strong']}; font-weight: 700; }}
        QGroupBox {{
            border: 1px solid {colors['border']};
            border-radius: 10px;
            margin-top: 12px;
            padding-top: 10px;
            background: {colors['panel']};
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: {colors['strong']};
        }}
        QPushButton {{
            background: {colors['button']};
            border: 1px solid {colors['border']};
            border-radius: 8px;
            padding: 6px 12px;
            color: {colors['strong']};
        }}
        QPushButton:hover {{ background: {colors['button_hover']}; }}
        QPushButton:disabled {{
            background: {colors['disabled']};
            color: {colors['disabled_text']};
            border-color: {colors['border_soft']};
        }}
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {colors['input']};
            border: 1px solid {colors['border_soft']};
            border-radius: 6px;
            padding: 4px 6px;
            selection-background-color: #0F766E;
            selection-color: #FFFFFF;
        }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QAbstractItemView, QListView, QTableWidget, QTableView, QTreeView {{
            background: {colors['input']};
            alternate-background-color: {colors['alternate']};
            border: 1px solid {colors['border_soft']};
            gridline-color: {colors['border_soft']};
            selection-background-color: #0F766E;
            selection-color: #FFFFFF;
        }}
        QListWidget#settingsNav {{
            background: transparent;
            border: none;
            outline: none;
            padding: 2px 0;
        }}
        QListWidget#settingsNav::item {{
            border-radius: 8px;
            padding: 10px 12px;
            margin: 2px 0;
            color: {colors['muted']};
        }}
        QListWidget#settingsNav::item:selected {{ background: #0F766E; color: #FFFFFF; }}
        QListWidget#settingsNav::item:hover:!selected {{
            background: {colors['panel_hover']};
            color: {colors['strong']};
        }}
        QTableWidget {{ color: {colors['text']}; }}
        QHeaderView::section {{ background: {colors['header']}; border: none; padding: 6px; }}
        QScrollArea {{ border: none; }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            background: {colors['chrome']};
            border: none;
            margin: 0;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: {colors['scroll']};
            border-radius: 6px;
            min-height: 28px;
            min-width: 28px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line,
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; }}
        QProgressBar {{
            border: 1px solid {colors['border_soft']};
            border-radius: 8px;
            text-align: center;
            background: {colors['input']};
        }}
        QProgressBar::chunk {{ background: #0EA5A4; border-radius: 6px; }}
        QSlider::groove:horizontal {{
            height: 6px;
            background: {colors['groove']};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            width: 14px;
            margin: -5px 0;
            border-radius: 7px;
            background: {colors['handle']};
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid {colors['border']};
            background: {colors['input']};
        }}
        QCheckBox::indicator:checked {{ background: #0F766E; border-color: #14B8A6; }}
        QSplitter::handle {{ background: {colors['chrome']}; }}
        QGraphicsView#videoPreviewView {{
            background: {colors['preview']};
            border: 1px solid {colors['border']};
            border-radius: 10px;
        }}
    """
