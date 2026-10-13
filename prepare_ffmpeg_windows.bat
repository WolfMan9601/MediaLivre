@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_ffmpeg_windows.ps1"
if errorlevel 1 (
  echo Nao foi possivel preparar o FFmpeg automaticamente.
  echo Verifique a ligacao a Internet e tente novamente.
  exit /b 1
)
exit /b 0
