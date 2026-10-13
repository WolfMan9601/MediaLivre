# Instalação do MediaLivre no Windows

## Criar o instalador

O instalador Windows precisa de ser compilado no Windows. Nesta sessão Linux não é possível testar nem emitir um `.exe` instalador nativo.

1. Obtenha a pasta completa do projeto MediaLivre e instale Python **de 64 bits**.
2. Instale **Python 3.10+** para Windows e o **Inno Setup 6**.
3. Abra a pasta no Explorador e faça duplo clique em `create_installer_windows.bat`.
   - O script cria/usa `.venv` sem ativar `Activate.ps1`.
   - Instala dependências e compila o app através de PyInstaller.
   - Compila `installer_windows.iss` com Inno Setup.
4. O ficheiro final será `dist\installer\MediaLivre-Setup-0.4.0-win64.exe`.
5. Distribua esse ficheiro e execute-o para instalar. A aplicação e os dados do agendador ficam em locais diferentes: a fila de downloads é preservada em `%LOCALAPPDATA%\MediaLivre` mesmo se a app for desinstalada.

FFmpeg não é incluído no instalador. Para combinar streams e converter para MP3/MKV/AVI, instale FFmpeg separadamente e deixe `ffmpeg.exe` acessível pelo `PATH`.

## Se o PowerShell bloquear scripts

Não é necessário ativar a virtualenv. Os scripts `.bat` chamam diretamente `.venv\Scripts\python.exe`. Também pode executar a app com:

```bat
.venv\Scripts\python.exe medialivre.py
```

O instalador só foi preparado nesta entrega; tem de ser produzido num Windows com Inno Setup instalado.
