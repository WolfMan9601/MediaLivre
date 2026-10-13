@echo off
setlocal
cd /d "%~dp0"

call build_windows.bat
if errorlevel 1 exit /b 1

set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_EXE%" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_EXE%" set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not exist "%ISCC_EXE%" (
  echo.
  echo A aplicacao foi compilada, mas o Inno Setup 6 nao foi encontrado.
  echo Instale o Inno Setup 6 para Windows e volte a executar este ficheiro.
  echo Projeto do instalador: installer_windows.iss
  exit /b 2
)

"%ISCC_EXE%" installer_windows.iss
if errorlevel 1 exit /b 1

echo.
echo Instalador criado em dist\installer\MediaLivre-Setup-0.4.0-win64.exe
