"""Genera vibeloader/_build_info.py con la versión de yt-dlp que se empaqueta.

El actualizador del .exe la usa para saber si la copia descargada en
%LOCALAPPDATA% es más nueva que la embebida. Lo llama build_vibeload.bat.
"""
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

import yt_dlp.version  # noqa: E402

from vibeloader.config import APP_VERSION  # noqa: E402

path = os.path.join(root, "vibeloader", "_build_info.py")
with open(path, "w", encoding="utf-8") as f:
    f.write('"""Generado por scripts/write_build_info.py al compilar. No editar."""\n')
    f.write(f"YTDLP_VERSION = {yt_dlp.version.__version__!r}\n")
    f.write(f"APP_VERSION = {APP_VERSION!r}\n")
print(f"VibeLoader {APP_VERSION} con yt-dlp {yt_dlp.version.__version__}")
