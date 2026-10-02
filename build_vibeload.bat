@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

REM Activar venv si existe (recomendado)
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else (
  echo [INFO] No encontre .venv\. Se usara el Python global.
)

echo.
echo === Actualizando dependencias ===
python -m pip install -U pip || goto :error
python -m pip install -U -r requirements-dev.txt || goto :error

echo.
echo === Tests ===
python -m pytest -q || goto :error

echo.
echo === Info de build ===
python scripts\write_build_info.py || goto :error
for /f "delims=" %%v in ('python -c "from vibeloader.config import APP_VERSION; print(APP_VERSION)"') do set APPVER=%%v

echo.
echo === PyInstaller (carpeta, arranque rapido) ===
REM --onedir: no se descomprime en cada inicio como --onefile.
REM --splash: PyInstaller muestra la imagen mientras carga Python y Qt.
REM yt_dlp_ejs trae los scripts JS para los retos de YouTube (datos, no solo .py).
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name VibeLoader ^
  --icon assets\icono.ico ^
  --splash assets\splash.png ^
  --add-data "assets\icono.ico;assets" ^
  --add-data "assets\splash.png;assets" ^
  --collect-all curl_cffi ^
  --collect-all yt_dlp_ejs ^
  --collect-submodules yt_dlp ^
  vibeload_whatsapp.py || goto :error

echo.
echo === Quitar partes de Qt que no se usan ===
python scripts\slim_dist.py dist\VibeLoader || goto :error

echo.
echo === Instalador (Inno Setup) ===
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
  "%ISCC%" /Qp /DMyAppVersion=%APPVER% installer.iss || goto :error
  echo Instalador: dist\installer\VibeLoader-Setup-%APPVER%.exe
) else (
  echo [INFO] Inno Setup no esta instalado: se omite el instalador.
  echo        Instalalo con:  winget install JRSoftware.InnoSetup
)

echo.
echo Listo. La app esta en dist\VibeLoader\VibeLoader.exe
pause
endlocal
exit /b 0

:error
echo.
echo [ERROR] El build fallo. Revisa los mensajes de arriba.
pause
endlocal
exit /b 1
