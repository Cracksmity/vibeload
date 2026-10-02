# 🎧 VibeLoader ✨

VibeLoader es una aplicación de escritorio para Windows, escrita en Python, para **descargar y comprimir videos y música**. Usa **yt-dlp** para descargar (YouTube, TikTok, Facebook, Instagram, X y más de 1.800 sitios) y **ffmpeg** para convertir.

Tiene dos vistas:

- **Modo simple** (predeterminado): pegar enlace → tocar un botón → listo. Pensado para quien no quiere pelearse con códecs.
- **Modo avanzado**: todos los modos, recortes por tiempo, tamaño máximo, subtítulos, cookies, cola de descargas y registro detallado.

---

## 🚀 Características

### Modo simple

Cuatro botones grandes:

| Botón | Resultado |
|---|---|
| **Descargar Música** | MP3 192 kbps con metadatos y portada. |
| **Descargar Video** | MP4 **hasta 1080p** en H.264 + AAC, sin recomprimir: se reproduce en cualquier TV, celular o reproductor. |
| **Descarga Directa** | MP4 **720p** H.264 + AAC, sin recodificar (cero carga para la CPU). |
| **Modo Auto** | MP4 para autoestéreos: H.264 **Baseline @ L3.1**, AAC 44.1 kHz, `+faststart`. |

Además: vista previa con miniatura, título, canal y duración; pegado automático desde el portapapeles; arrastrar y soltar enlaces; enlaces recientes; **historial**; y aviso con botón si falta ffmpeg o hay un yt-dlp nuevo.

### Modo avanzado

Los siete modos:

| Modo | Qué hace |
|---|---|
| `Modo WhatsApp (Base)` | H.264 Main@4.0 + AAC, lado largo ≤ 1280 (vertical 720×1280), ≤ 30 fps. Nombre: `id.mp4`. |
| `Modo Video Max` | Igual que "Descargar Video" (hasta 1080p, sin recomprimir). |
| `Modo Audio MP3` | MP3 192 kbps con portada. |
| `Modo Auto` | Perfil para autoestéreos (ver arriba). Nombre: título del video. |
| `Modo Descarga Directa` | 720p sin recodificar. |
| `Modo Cursos (H.265)` | HEVC 720p, CRF 28, AAC 96 kbps, etiqueta `hvc1`. ~40-50 % menos peso que H.264: ideal para cursos y tutoriales largos. |
| `Modo Tamaño Máximo` | Comprime a un **peso objetivo** (16 / 25 / 64 / 100 MB o el que escribas) con dos pasadas; la resolución se ajusta sola al bitrate. |

Y también:

- **Recorte** por tiempo (`MM:SS`, `HH:MM:SS`, `90s`, `1m30s`), validado contra la duración real. En los modos que convierten, el corte se hace en la misma pasada de ffmpeg (una sola codificación).
- **Codificador**: *Automático* usa la tarjeta de video (NVIDIA NVENC, Intel QuickSync o AMD AMF) si funciona de verdad (se prueba, no solo se lista). Si falla, reintenta con CPU. *Solo CPU* da archivos algo más chicos.
- **Copia sin recodificar**: si el video descargado ya cumple el perfil (por ejemplo 720p de YouTube para WhatsApp), solo se reempaqueta en segundos.
- **Cola de descargas**: mientras baja algo puedes seguir agregando enlaces. Pestaña *Cola* para quitar o vaciar. *Cancelar* detiene el actual y vacía la cola.
- **Listas de reproducción**: al usar un enlace de playlist se abre un diálogo para elegir los videos y el modo; se guardan en una subcarpeta con el nombre de la lista.
- **Subtítulos** (español / inglés): como `.srt` al lado del video o **incrustados** en el MP4.
- **Cookies del navegador** (Firefox recomendado; Chrome y Edge hay que cerrarlos antes): para videos con restricción de edad o cuando YouTube pide confirmar que no eres un bot.
- **Actualizar yt-dlp** con un botón, y búsqueda automática una vez al día (desactivable). Funciona también en el `.exe` sin recompilar.

### Calidad de vida

- Tema claro/oscuro, carpetas predeterminadas por modo, notificaciones de Windows al terminar.
- Errores traducidos a español claro (con la causa real cuando falla ffmpeg).
- Limpieza segura: solo se borran archivos temporales **creados por la propia descarga**; nunca archivos que ya tenías en la carpeta.
- Log con fecha y rotación en `%LOCALAPPDATA%\VibeLoader\vibeload.log`.

---

## 🧩 Tecnologías

- **Python 3.10+** y **PySide6** (Qt) para la interfaz.
- **yt-dlp** (con `yt-dlp-ejs` para los retos JavaScript de YouTube y `curl_cffi` para Facebook/Instagram).
- **ffmpeg / ffprobe** para convertir, recortar, unir pistas y analizar archivos.

---

## 📦 Requisitos

1. **Python 3.10 o superior** (solo para desarrollo; el `.exe` no lo necesita).
2. **ffmpeg y ffprobe**: si no los tienes, VibeLoader ofrece descargarlos (≈185 MB, build oficial de BtbN con SHA-256 verificado) a su propia carpeta, sin tocar el sistema. También puedes instalarlos tú y ponerlos en el `PATH`.
3. Opcional para YouTube: un runtime de JavaScript (**Deno** o **Node.js**) mejora la cantidad de formatos disponibles. Sin él, yt-dlp usa clientes alternativos.

---

## 🛠 Instalación (modo desarrollo)

```bash
git clone https://github.com/Cracksmity/vibeload
cd vibeload
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python vibeload_whatsapp.py
```

La primera vez se abre un asistente para elegir la carpeta de cada modo.

### Estructura

```
vibeload_whatsapp.py      punto de entrada
vibeloader/
  app.py                  arranque, splash, activa el yt-dlp actualizado
  config.py               constantes y presets
  ytdlp_core.py           descargas, metadatos, subtítulos (yt-dlp)
  ffmpeg_core.py          perfiles, plan copiar/recodificar, hardware, tamaño objetivo
  jobs.py                 Worker de la cola, metadatos y tareas de fondo
  updater.py              actualización de yt-dlp e instalación de ffmpeg
  tools.py · urls.py · utils.py · errors.py · logs.py · settings.py · history.py
  ui/                     vistas, diálogos y estilos
tests/                    pytest
assets/                   ícono y splash (originales en assets/source)
```

### Tests

```bash
python -m pytest
```

---

## 🧱 Generar el .exe

Doble clic en **`build_vibeload.bat`**. El script:

1. Actualiza las dependencias (`requirements-dev.txt`).
2. Corre los tests y **se detiene si algo falla**.
3. Registra la versión de yt-dlp empaquetada (para el actualizador).
4. Genera `dist\VibeLoader\VibeLoader.exe` con PyInstaller en modo **carpeta** (arranca rápido; no se descomprime en cada inicio).
5. Si tienes **Inno Setup** (`winget install JRSoftware.InnoSetup`), crea el instalador `dist\installer\VibeLoader-Setup-<versión>.exe`, que se instala por usuario sin pedir administrador.

El `.exe` no incluye ffmpeg: lo ofrece descargar la primera vez.

---

## 🐛 Problemas comunes

- **"YouTube pide confirmar que no eres un bot" / restricción de edad**: en el modo avanzado elige *Cookies del navegador* → Firefox (o cierra Chrome/Edge y elige ese).
- **Error 403 / "Unable to extract"**: YouTube cambió algo. Usa *Actualizar yt-dlp* y reinicia.
- **Falta ffmpeg**: usa el botón *Descargar ffmpeg*.
- **Modo Cursos falla con "Unknown encoder 'libx265'"**: tu ffmpeg no trae H.265. Usa el que descarga VibeLoader.
- **La conversión por tarjeta de video falla**: VibeLoader reintenta solo con CPU. Si quieres forzarlo, elige *Codificador → Solo CPU*.

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Consulta el archivo [LICENSE](LICENSE) para más detalles.

---

Hecho con Python, una hamburguesa y un toque de vaporwave 🍔🌅
