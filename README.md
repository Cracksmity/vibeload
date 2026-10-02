# 🎧 VibeLoader ✨

VibeLoader es una aplicación de escritorio para Windows escrita en Python con dos vistas:

- **Modo simple** (predeterminado): pegar enlace → elegir Música, Video, Auto o Cursos → descargar. Pensado para quien quiera bajar cosas sin pelearse con códecs.
- **Modo avanzado**: la GUI clásica con presets, recortes por tiempo, carpeta de salida y log detallado.

Internamente usa **yt-dlp** para descargar y **ffmpeg** para convertir. La música se guarda en MP3 con metadatos y portada embebida.

---

## 🚀 Características

- **Interfaz gráfica (PySide6)** con tema claro/oscuro y botones grandes accesibles.

- **Modo simple** (recomendado para uso diario): cuatro botones en cuadrícula 2×2:
  - **Descargar Música** → MP3 192 kbps con metadatos y portada.
  - **Descargar Video** → MP4 hasta 1080p (sin recompresión, calidad original).
  - **Modo Auto** → MP4 720p H.264 **Baseline @ L3.1**, AAC LC 128 kbps a 44.1 kHz, `+faststart`. Pensado para autoestéreos y reproductores antiguos donde códecs nuevos o resoluciones altas dan problemas. El archivo final se llama con el **título del video y espacios** (caracteres no válidos en Windows se quitan); si ya existía otro archivo con el mismo nombre, se añade el **id del video** entre corchetes: `Mi canción favorita [dQw4w9WgXcQ].mp4`.
  - **Modo Cursos** → MP4 720p **H.265 (HEVC)** con máxima compresión para videos largos (p. ej. tutoriales con texto en pantalla). Mismo esquema de nombres que Modo Auto. Carpeta predeterminada: `Videos\VibeLoader\Cursos`.

- **Modo avanzado**, con cinco presets:
  - `WhatsApp 720p` → recompresión H.264 Main@L4.0 + AAC, máx. 1280×720, 30 fps, yuv420p, +faststart. El archivo final se guarda solo con el **id del video** (por ejemplo `dQw4w9WgXcQ.mp4`), sin sufijo `_whatsapp`.
  - `Máxima calidad (video)` → mejor calidad disponible, sin recomprimir.
  - `Solo audio (MP3)` → MP3 192 kbps con portada embebida.
  - `Modo Auto (autoestéreo)` → mismo perfil que el botón Auto del modo simple.
  - `Modo Cursos Avanzado` → recompresión **H.265** (`libx265`), escala a 720p (`scale=-2:720`), CRF 28, 30 fps, AAC 96 kbps, `+faststart`, etiqueta `hvc1` para mejor compatibilidad en MP4. Requiere **ffmpeg compilado con libx265**. Mismo esquema de nombres que Modo Auto.
  - Recorte opcional por tiempo (`MM:SS`, `HH:MM:SS`, `90s`, `1m30s`).

- **Calidad de vida**:
  - Detección automática de URL en el portapapeles al activar la ventana.
  - Vista previa con miniatura, título, canal y duración antes de descargar.
  - Drag & drop de URLs sobre la ventana.
  - Lista de **enlaces recientes** (últimos 5).
  - Botón **Abrir carpeta** y **Abrir archivo** al terminar.
  - **Notificaciones del sistema** cuando la descarga termina y la ventana no está enfocada.
  - **Botón cancelar** durante descarga o conversión.
  - **Errores amigables**: traduce los mensajes técnicos comunes a español plano.
  - **Tema claro/oscuro** persistido entre sesiones.
  - **Carpetas predeterminadas** por modo, configurables en la primera ejecución.
  - Auto-actualización opcional de yt-dlp en segundo plano (deshabilitada por defecto).

- Logs detallados en `%LOCALAPPDATA%\VibeLoader\vibeload.log`.

---

## 🧩 Tecnologías usadas

- **Python 3**
- PySide6 – GUI
- yt-dlp – descargas de video/audio
- ffmpeg / ffprobe – conversión de video (WhatsApp, Auto, Cursos), audio MP3 y miniaturas (usado por yt-dlp)

---

## 📦 Requisitos

1. **Python 3.10+** (recomendado)

2. Paquetes de Python (recomendado usar el archivo del repo):
   
   ```bash
   pip install -r requirements.txt
   ```

3. **ffmpeg** y **ffprobe** en el `PATH` (obligatorio para todos los modos). **Modo Cursos Avanzado** además requiere soporte **libx265** en tu build de ffmpeg (`ffmpeg -encoders | findstr x265` en Windows).
   
   ```bat
   ffmpeg -version
   ffprobe -version
   ```

---

## 🛠 Instalación (modo desarrollo)

1. Clonar el repositorio:
   
   ```bash
   git clone https://github.com/Cracksmity/vibeload
   cd vibeload
   ```

2. (Opcional pero recomendado) crear un entorno virtual:
   
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. Instalar dependencias:
   
   ```bash
   pip install -r requirements.txt
   ```

4. Verificar que `ffmpeg` y `ffprobe` funcionen en la consola.

---

## ▶️ Uso (desde Python)

Dentro de la carpeta del proyecto:

```bash
python vibeload_whatsapp.py
```

La primera vez se abre un asistente para configurar las carpetas predeterminadas (Música, Video, WhatsApp, Auto y Cursos). Luego, en el **modo simple** basta con:

1. Pegar el enlace (o esperar a que VibeLoader lo detecte del portapapeles).
2. Tocar uno de los cuatro botones:
   - **Descargar Música** (MP3 con portada)
   - **Descargar Video** (MP4 hasta 1080p)
   - **Modo Auto** (MP4 720p compatible con autoestéreos)
   - **Modo Cursos** (MP4 720p H.265 comprimido para videos largos)
3. Cuando termine, usar **Abrir carpeta** o **Abrir archivo**.

El **modo avanzado** se abre desde el botón superior derecho y expone los cinco presets, recortes por tiempo, carpeta de salida personalizada y log detallado.

---

## 🧱 Generar el .exe (PyInstaller)

El proyecto incluye `build_vibeload.bat`. **Para generar el .exe con icono:** abre la carpeta del proyecto en el Explorador de archivos, haz doble clic en `build_vibeload.bat` (o ejecútalo desde `cmd` en esa carpeta). El script actualiza dependencias, instala PyInstaller si hace falta, y deja el ejecutable en `dist\`. Necesitas **Python y ffmpeg** instalados como en desarrollo; el `.exe` no empaqueta ffmpeg.

### 1. Instala PyInstaller

```bash
pip install pyinstaller
```

### 2. Generar el ejecutable

Ejemplo de comando:

```bash
pyinstaller --onefile --noconsole --icon=icono.ico --add-data "icono.ico;." vibeload_whatsapp.py
```

- El ejecutable quedará en la carpeta `dist/` como algo tipo:
  
  ```text
  dist/vibeload_whatsapp.exe
  ```

> Nota: El `.exe` **no incluye** ffmpeg; debe estar instalado y en el `PATH`.

---

## 🐛 Problemas comunes

- **Error al convertir a MP3 / portada no se embebe**
  
  - Normalmente es por falta de `ffmpeg` o `ffprobe`.
  - Solución: instalar ffmpeg y asegurarte de que `ffmpeg -version` y `ffprobe -version` funcionen en la consola.

- **Modo Cursos falla con «Unknown encoder 'libx265'»**
  
  - Tu instalación de ffmpeg no incluye el códec H.265.
  - Solución: instalar una build de ffmpeg con `libx265` habilitado (p. ej. builds de gyan.dev o BtbN en Windows).

- **Se generan muchos archivos (webp, jpg, webm, m4a, etc.)**
  
  - El código ya incluye una limpieza básica para dejar solo el archivo final.
  - Si ves archivos sobrantes, probablemente fue en una versión anterior.

---

## 📝 To-Do / ideas futuras

- Soporte para descargar playlists completas.
- Más presets compatibles (Telegram, Instagram Stories, etc.).
- Tests automatizados con pytest para los helpers (`parse_time`, `friendly`, `looks_like_supported_url`).

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Consulta el archivo [LICENSE](LICENSE) para más detalles.

---

Hecho con Python, una hamburguesa y un toque de vaporwave 🍔🌅
