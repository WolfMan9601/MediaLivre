@echo off
setlocal
cd /d "%~dp0"

call build_windows.bat
if errorlevel 1 exit /b 1

set "ISCC_EXE="
for /f "delims=" %%F in ('where ISCC.exe 2^>nul') do if not defined ISCC_EXE set "ISCC_EXE=%%~fF"
for %%F in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
  "%ProgramFiles%\Inno Setup 7\ISCC.exe"
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
  "%LOCALAPPDATA%\MediaLivre\tools\InnoSetup\ISCC.exe"
) do if not defined ISCC_EXE if exist "%%~F" set "ISCC_EXE=%%~F"

if not defined ISCC_EXE (
  echo.
  echo Inno Setup nao foi encontrado. A instalar automaticamente numa pasta local...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_innosetup_windows.ps1"
  if errorlevel 1 (
    echo Nao foi possivel instalar automaticamente o compilador Inno Setup.
    echo Verifique a Internet e execute novamente este ficheiro.
    exit /b 2
  )
  for /r "%LOCALAPPDATA%\MediaLivre\tools\InnoSetup" %%F in (ISCC.exe) do if not defined ISCC_EXE set "ISCC_EXE=%%~fF"
)

if not defined ISCC_EXE (
  echo O compilador ISCC.exe continua indisponivel.
  exit /b 2
)

echo A compilar o instalador com: %ISCC_EXE%
"%ISCC_EXE%" installer_windows.iss
if errorlevel 1 exit /b 1

echo.
set "SETUP_EXE=dist\installer\MediaLivre-Setup-0.13.1-win64.exe"
if not exist "%SETUP_EXE%" (
  echo O Inno Setup terminou, mas o ficheiro EXE final nao foi encontrado.
  exit /b 1
)
copy /Y "%SETUP_EXE%" "MediaLivre-Setup-0.13.1-win64.exe" >nul
if errorlevel 1 exit /b 1
echo Instalador EXE criado em:
echo   %SETUP_EXE%
echo   MediaLivre-Setup-0.13.1-win64.exe
