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
python -m pip install -r requirements.txt
python -m pip install -U pyinstaller

echo.
echo === Rebuild EXE (PyInstaller) ===
python -m pyinstaller --onefile --noconsole --icon=icono.ico --add-data "icono.ico;." --add-data "splash_screen.png;." --collect-all curl_cffi --collect-binaries curl_cffi vibeload_whatsapp.py

echo.
echo ✅ Listo. Tu exe actualizado esta en: dist\
pause
endlocal

