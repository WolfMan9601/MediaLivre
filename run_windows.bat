@echo off
setlocal
cd /d "%~dp0"
call prepare_ffmpeg_windows.bat
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
".venv\Scripts\python.exe" medialivre.py
