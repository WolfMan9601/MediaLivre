@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || exit /b 1
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name MediaLivre --collect-all yt_dlp --collect-all PySide6 --hidden-import download_scheduler medialivre.py
if errorlevel 1 exit /b 1
echo Build concluido: dist\MediaLivre\MediaLivre.exe
echo FFmpeg deve ser instalado separadamente para combinar faixas e extrair MP3.
