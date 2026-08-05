from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def default_log_dir() -> Path:
    base_dir = os.environ.get("LOCALAPPDATA")
    if base_dir:
        return Path(base_dir) / "VCutStudio" / "logs"
    return Path(tempfile.gettempdir()) / "VCutStudio" / "logs"


def _resolve_log_level(level_name: str) -> int:
    normalized = str(level_name or "").strip().upper()
    return _LOG_LEVELS.get(normalized, logging.INFO)


def configure_logging(
    level: str = "INFO",
    log_dir: str | Path | None = None,
) -> Path | None:
    """Configure the root logger with a console handler and a rotating file handler.

    Returns the resolved log file path, or None when the file handler could not
    be created (e.g. unwritable log directory).
    """
    resolved_level = _resolve_log_level(level)
    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler) for handler in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root_logger.addHandler(console_handler)

    log_file_path: Path | None = None
    if not any(isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers):
        try:
            log_dir_path = Path(log_dir) if log_dir is not None else default_log_dir()
            log_dir_path.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir_path / "vcut.log"
            file_handler = RotatingFileHandler(
                str(log_file_path),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
            root_logger.addHandler(file_handler)
        except OSError:
            log_file_path = None

    # Qt (PySide6) writes warnings/errors through qWarning/qCritical; route them
    # into our log file too so production issues are not lost.
    try:
        from PySide6 import QtCore  # noqa: PLC0415

        _install_qt_message_handler(QtCore)
    except Exception:
        pass

    return log_file_path


def _install_qt_message_handler(qtcore_module: object) -> None:
    qt_logger = logging.getLogger("qt")

    def _message_handler(mode: object, context: object, message: str) -> None:
        level = logging.DEBUG
        mode_name = str(mode)
        if "Warning" in mode_name:
            level = logging.WARNING
        elif "Critical" in mode_name or "Fatal" in mode_name:
            level = logging.ERROR
        qt_logger.log(level, "%s", message)

    try:
        qInstallMessageHandler = getattr(qtcore_module, "qInstallMessageHandler")  # noqa: N806
        qInstallMessageHandler(_message_handler)
    except Exception:
        pass


def install_excepthook() -> None:
    """Route uncaught exceptions (main thread and worker threads) to the logger."""
    logger = logging.getLogger("vcut_studio.uncaught")

    def _handle_exception(exc_type: type[BaseException], exc: BaseException, traceback_obj: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, traceback_obj)  # type: ignore[arg-type]
            return
        logger.critical("未捕获异常", exc_info=(exc_type, exc, traceback_obj))

    def _handle_thread_exception(args: object) -> None:
        exc_type = getattr(args, "exc_type", None)
        exc = getattr(args, "exc_value", None)
        traceback_obj = getattr(args, "exc_traceback", None)
        if exc_type is None or exc is None:
            return
        if issubclass(exc_type, KeyboardInterrupt):
            return
        thread_name = getattr(args, "thread", None)
        logger.critical("线程未捕获异常（%s）", thread_name, exc_info=(exc_type, exc, traceback_obj))

    sys.excepthook = _handle_exception
    threading.excepthook = _handle_thread_exception
