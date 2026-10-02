"""Log a archivo en %LOCALAPPDATA%/VibeLoader."""
import os

LOG_FILE_PATH = None


def ensure_log_path():
    global LOG_FILE_PATH
    if LOG_FILE_PATH:
        return LOG_FILE_PATH
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(base, "VibeLoader")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = base
    LOG_FILE_PATH = os.path.join(log_dir, "vibeload.log")
    return LOG_FILE_PATH


def append_log_file(line: str):
    try:
        with open(ensure_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
