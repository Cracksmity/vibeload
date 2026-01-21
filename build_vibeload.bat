@echo off
setlocal
cd /d "%~dp0"

REM Activar venv si existe (recomendado)
if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  echo [INFO] No encontre venv\. Se usara el Python global.
)

echo.
echo === Actualizando dependencias ===
python -m pip install -U pip
pip install -U yt-dlp PySide6 pyinstaller

echo.
echo === Rebuild EXE (PyInstaller) ===
pyinstaller --onefile --noconsole --icon=icono.ico vibeload_whatsapp.py

echo.
echo ✅ Listo. Tu exe actualizado esta en: dist\
pause
endlocal

