"""Log a archivo en %LOCALAPPDATA%/VibeLoader/vibeload.log (con rotación).

Se guarda con hora y nivel; al pasar de 1 MB rota a vibeload.log.1 … .3,
así el archivo no crece sin límite.
"""
import logging
import logging.handlers
import os
import threading
import traceback

from .tools import app_data_dir

LOG_FILE_PATH = None
_logger = None
_lock = threading.Lock()


def ensure_log_path():
    global LOG_FILE_PATH
    if LOG_FILE_PATH is None:
        LOG_FILE_PATH = os.path.join(app_data_dir(), "vibeload.log")
    return LOG_FILE_PATH


def get_logger() -> logging.Logger:
    global _logger
    with _lock:
        if _logger is not None:
            return _logger
        lg = logging.getLogger("vibeloader")
        lg.setLevel(logging.INFO)
        lg.propagate = False
        try:
            handler = logging.handlers.RotatingFileHandler(
                ensure_log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
            lg.addHandler(handler)
        except OSError:
            lg.addHandler(logging.NullHandler())
        _logger = lg
        return lg


def append_log_file(line: str):
    get_logger().info(line)


def log_exception(context: str = ""):
    """Registra el traceback completo de la excepción en curso."""
    tb = traceback.format_exc()
    get_logger().error((context + "\n" if context else "") + tb.rstrip())
