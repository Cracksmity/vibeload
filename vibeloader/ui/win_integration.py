"""Integración con Windows: barra de título del color del tema y progreso en la barra de tareas.

Todo es opcional: fuera de Windows, o si una llamada falla, no hace nada.
Qt 6 ya no trae QtWinExtras, así que ITaskbarList3 se usa por COM con ctypes.
"""
import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# DwmSetWindowAttribute
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_CAPTION_COLOR = 35  # Windows 11
_DWMWA_TEXT_COLOR = 36  # Windows 11


def _colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)  # COLORREF = 0x00BBGGRR


def style_title_bar(hwnd: int, dark: bool, caption: str | None = None, text: str | None = None):
    """Barra de título oscura/clara y, en Windows 11, del mismo color que el fondo."""
    if not IS_WINDOWS or not hwnd:
        return
    try:
        dwm = ctypes.windll.dwmapi
        set_attr = dwm.DwmSetWindowAttribute
        set_attr.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        val = wintypes.BOOL(1 if dark else 0)
        set_attr(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val))
        if caption:
            c = wintypes.DWORD(_colorref(caption))
            set_attr(hwnd, _DWMWA_CAPTION_COLOR, ctypes.byref(c), ctypes.sizeof(c))
        if text:
            c = wintypes.DWORD(_colorref(text))
            set_attr(hwnd, _DWMWA_TEXT_COLOR, ctypes.byref(c), ctypes.sizeof(c))
    except Exception:
        pass


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(text, ctypes.byref(self))


_CLSID_TASKBARLIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
_IID_ITASKBARLIST3 = "{ea1afb91-9e28-4b86-90e9-9e9f8a5eefaf}"
_CLSCTX_INPROC_SERVER = 1

TBPF_NOPROGRESS = 0
TBPF_INDETERMINATE = 1
TBPF_NORMAL = 2
TBPF_ERROR = 4
TBPF_PAUSED = 8


class TaskbarProgress:
    """Barra de progreso en el botón de la barra de tareas (ITaskbarList3)."""

    # Índices en la vtable: IUnknown (0-2), ITaskbarList (3-7), ITaskbarList2 (8),
    # ITaskbarList3: SetProgressValue (9), SetProgressState (10).
    _HRINIT, _SET_VALUE, _SET_STATE = 3, 9, 10

    def __init__(self):
        self._ptr = None
        if not IS_WINDOWS:
            return
        try:
            ole32 = ctypes.oledll.ole32
            try:
                ole32.CoInitialize(None)  # ya inicializado por Qt: devuelve S_FALSE
            except OSError:
                pass
            ptr = ctypes.c_void_p()
            ole32.CoCreateInstance(
                ctypes.byref(_GUID(_CLSID_TASKBARLIST)),
                None,
                _CLSCTX_INPROC_SERVER,
                ctypes.byref(_GUID(_IID_ITASKBARLIST3)),
                ctypes.byref(ptr),
            )
            self._ptr = ptr
            self._call(self._HRINIT, ctypes.HRESULT)
        except Exception:
            self._ptr = None

    def _call(self, index, restype, *args):
        vtable = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        argtypes = [ctypes.c_void_p] + [type(a) for a in args]
        fn = ctypes.WINFUNCTYPE(restype, *argtypes)(vtable[index])
        return fn(self._ptr, *args)

    def set_state(self, hwnd: int, state: int):
        if not self._ptr or not hwnd:
            return
        try:
            self._call(self._SET_STATE, ctypes.HRESULT, wintypes.HWND(hwnd), ctypes.c_int(state))
        except Exception:
            pass

    def set_value(self, hwnd: int, done: int, total: int = 100):
        if not self._ptr or not hwnd:
            return
        try:
            self._call(self._SET_VALUE, ctypes.HRESULT, wintypes.HWND(hwnd), ctypes.c_ulonglong(done), ctypes.c_ulonglong(total))
        except Exception:
            pass
