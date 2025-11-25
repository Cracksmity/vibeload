# 🎧 VibeLoader ✨

VibeLoader es una pequeña aplicación de escritorio para Windows escrita en Python que:

- Descarga videos usando **yt-dlp**.
- Convierte videos a un formato más **compatible con WhatsApp** usando **HandBrakeCLI**.
- Descarga **solo audio en MP3**, con:
  - Metadatos (título, artista, etc.).
  - Portada embebida (miniatura del video).
- Todo esto con una **interfaz gráfica** en **PySide6** y un toquecito *vaporwave* 😎.

---

## 🚀 Características

- **Interfaz gráfica (GUI)** con tema oscuro.

- Tres modos de descarga:
  
  1. `WhatsApp 720p`  
     
     - Descarga el video.
     - Lo convierte a H.264 + AAC vía HandBrakeCLI.
     - Deja solo el archivo final `*_whatsapp.mp4`, ideal para compartir por WhatsApp.
  
  2. `Máxima calidad (video)`  
     
     - Descarga el mejor video disponible (video + audio).
     - No recomprime ni convierte: conserva la mayor calidad posible.
  
  3. `Solo audio (MP3)`  
     
     - Descarga solo el audio.
     - Convierte a MP3 (usando ffmpeg a través de yt-dlp).
     - Descarga la miniatura, la convierte y la incrusta como **portada** en el MP3.
     - Limpia archivos temporales, dejando solo el `.mp3` final.

- Limpieza automática de archivos intermedios (miniaturas y audio original).

- Barra de progreso indeterminada mientras se ejecutan las tareas en segundo plano.

- Logs en tiempo real dentro de la ventana.

---

## 🧩 Tecnologías usadas

- **Python 3**
- PySide6 – GUI
- yt-dlp – descargas de video/audio
- HandBrakeCLI – conversión de video a MP4 compatible
- ffmpeg – conversión de audio y manejo de miniaturas (usado por yt-dlp)

---

## 📦 Requisitos

1. **Python 3.10+** (recomendado)

2. Paquetes de Python:
   
   ```bash
   pip install yt-dlp PySide6
   ```

3. **HandBrakeCLI** instalado y accesible en el `PATH`:
   
   - En Windows normalmente se instala junto con HandBrake o como binario separado.
   
   - Verifica en consola:
     
     ```bat
     HandBrakeCLI --version
     ```

4. **ffmpeg** y **ffprobe** en el `PATH` (para el modo MP3 con portada):
   
   ```bat
   ffmpeg -version
   ffprobe -version
   ```

---

## 🛠 Instalación (modo desarrollo)

1. Clonar el repositorio (ajusta TU_USUARIO y el nombre del repo si lo necesitas):
   
   ```bash
   git clone https://github.com/TU_USUARIO/vibeload.git
   cd vibeload
   ```

2. (Opcional pero recomendado) crear un entorno virtual:
   
   ```bash
   python -m venv venv
   venv\Scriptsctivate
   ```

3. Instalar dependencias:
   
   ```bash
   pip install yt-dlp PySide6
   ```

4. Verificar que `HandBrakeCLI`, `ffmpeg` y `ffprobe` funcionen en la consola.

---

## ▶️ Uso (desde Python)

Dentro de la carpeta del proyecto:

```bash
python vibeload_whatsapp.py
```

Se abrirá la ventana de VibeLoader:

1. **URL del video**: pega el enlace (YouTube, etc.).
2. **Carpeta de salida**: elige dónde quieres guardar los archivos.
3. **Modo**:
   - `WhatsApp 720p`
   - `Máxima calidad (video)`
   - `Solo audio (MP3)`
4. Clic en **“Descargar 🚀”** y espera a que el log indique que terminó.

---

## 🧱 Generar el .exe (PyInstaller)

El proyecto puede usar un script de ayuda `build_vibeload.bat` (opcional).

### 1. Instala PyInstaller

```bash
pip install pyinstaller
```

### 2. Generar el ejecutable

Ejemplo de comando:

```bash
pyinstaller --onefile --noconsole --icon=vibeload_icon.ico vibeload_whatsapp.py
```

- El ejecutable quedará en la carpeta `dist/` como algo tipo:
  
  ```text
  dist/vibeload_whatsapp.exe
  ```

> Nota: El `.exe` **no incluye** HandBrakeCLI ni ffmpeg; deben estar instalados en el sistema.

---

## 🧹 Archivos que NO se suben a Git

Ejemplo de `.gitignore` recomendado:

```gitignore
# Python
__pycache__/
*.pyc

# Entorno virtual
venv/
.env/

# PyInstaller
build/
dist/
*.spec

# PyCharm
.idea/
```

---

## 🐛 Problemas comunes

- **Error: `'HandBrakeCLI' no se reconoce como comando`**
  
  - No está instalado o no está en el `PATH`.
  - Solución: instalar HandBrakeCLI y agregar la carpeta donde está `HandBrakeCLI.exe` al PATH, o usar ruta absoluta en el código.

- **Error al convertir a MP3 / portada no se embebe**
  
  - Normalmente es por falta de `ffmpeg` o `ffprobe`.
  - Solución: instalar ffmpeg y asegurarte de que `ffmpeg -version` y `ffprobe -version` funcionen en la consola.

- **Se generan muchos archivos (webp, jpg, webm, m4a, etc.)**
  
  - El código ya incluye una limpieza básica para dejar solo el archivo final.
  - Si ves archivos sobrantes, probablemente fue en una versión anterior.

---

## 📝 To-Do / ideas futuras

- Barra de progreso más precisa (porcentaje real).
- Soporte para descargar playlists completas.
- Configuración guardada en un archivo (última carpeta usada, modo favorito, etc.).
- Soporte para otros presets (Telegram, Instagram Stories, etc.).

---

## 📄 Licencia

Este proyecto se distribuye bajo la licencia **MIT**.
Puedes modificar este texto si eliges otra licencia.

---

Hecho con Python, una hamburguesa y un toque de vaporwave 🍔🌅
