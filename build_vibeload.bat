@echo off
setlocal

REM Ir a la carpeta donde está este .bat (y el .py)
cd /d "%~dp0"

echo ===========================
echo   Build VibeLoader ✨
echo ===========================
echo.

REM Si usas entorno virtual, descomenta la siguiente línea:
REM call "%~dp0venv\Scripts\activate.bat"

REM Si NO quieres icono, usa esta:
pyinstaller --onefile --noconsole vibeload_whatsapp.py

REM Si ya tienes un icono .ico, usa esta en su lugar:
REM pyinstaller --onefile --noconsole --icon=vibeload_256.ico vibeload_whatsapp.py

echo.
echo Build terminado. Revisa la carpeta "dist".
echo.
pause
endlocal
