"""Historial de descargas (persistido en QSettings como JSON)."""
import json
import time

HISTORY_KEY = "history_v1"
HISTORY_LIMIT = 100


def load_history(settings) -> list:
    raw = settings.value(HISTORY_KEY, "")
    if not raw:
        return []
    try:
        data = json.loads(str(raw))
    except ValueError:
        return []
    return [e for e in data if isinstance(e, dict) and e.get("path")] if isinstance(data, list) else []


def save_history(settings, entries: list):
    settings.setValue(HISTORY_KEY, json.dumps(entries[:HISTORY_LIMIT], ensure_ascii=False))


def add_history(settings, *, title: str, path: str, preset: str, url: str) -> list:
    entries = load_history(settings)
    entries.insert(
        0,
        {"ts": time.time(), "title": title or "", "path": path, "preset": preset, "url": url},
    )
    save_history(settings, entries)
    return entries[:HISTORY_LIMIT]


def clear_history(settings):
    settings.remove(HISTORY_KEY)
