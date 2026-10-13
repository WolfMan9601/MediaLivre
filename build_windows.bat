@echo off
setlocal
cd /d "%~dp0"

call prepare_ffmpeg_windows.bat
if errorlevel 1 exit /b 1

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || exit /b 1
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name MediaLivre --icon "assets\medialivre.ico" --add-data "assets;assets" --collect-all yt_dlp --collect-all PySide6 --hidden-import download_scheduler medialivre.py
if errorlevel 1 exit /b 1
xcopy /E /I /Y "third_party\ffmpeg" "dist\MediaLivre\ffmpeg" >nul
if errorlevel 1 exit /b 1
copy /Y "assets\medialivre.ico" "dist\MediaLivre\medialivre.ico" >nul
if errorlevel 1 exit /b 1
echo Build concluido: dist\MediaLivre\MediaLivre.exe
echo FFmpeg e ffprobe foram incluidos no bundle para combinar faixas e extrair MP3.
