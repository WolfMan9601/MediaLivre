# Instalação do MediaLivre no Windows

## Criar o instalador

O instalador Windows precisa de ser compilado no Windows. Nesta sessão Linux não é possível testar nem emitir um `.exe` instalador nativo.

1. Obtenha a pasta completa do projeto MediaLivre e instale Python **de 64 bits**.
2. Instale **Python 3.10+ de 64 bits** para compilar. O utilizador final não precisa de Python e o Inno Setup também não precisa de ser instalado manualmente.
3. Abra a pasta no Explorador e faça duplo clique em `create_installer_windows.bat`.
   - O script cria/usa `.venv` sem ativar `Activate.ps1`.
   - Descarrega automaticamente `ffmpeg.exe` e `ffprobe.exe` para `third_party\ffmpeg`.
   - Instala dependências e compila o app através de PyInstaller.
   - Se necessário, baixa automaticamente o compilador oficial Inno Setup para `%LOCALAPPDATA%\MediaLivre\tools\InnoSetup`.
   - Compila `installer_windows.iss` com esse compilador.
4. O ficheiro final será `dist\installer\MediaLivre-Setup-0.5.0-win64.exe`.
5. Distribua esse ficheiro e execute-o para instalar. A aplicação e os dados do agendador ficam em locais diferentes: a fila de downloads é preservada em `%LOCALAPPDATA%\MediaLivre` mesmo se a app for desinstalada.
6. O instalador cria por padrão um atalho no Ambiente de Trabalho e usa `medialivre.ico` no setup, no executável e no atalho; pode desmarcar essa opção durante a instalação.

FFmpeg e ffprobe ficam incluídos no bundle do instalador. O utilizador final não precisa de os instalar separadamente para combinar streams ou converter para MP3/MKV/AVI.

## Se o PowerShell bloquear scripts

Não é necessário ativar a virtualenv. Os scripts `.bat` chamam diretamente `.venv\Scripts\python.exe`. Também pode executar a app com:

```bat
.venv\Scripts\python.exe medialivre.py
```

O instalador é produzido num Windows porque o PyInstaller e o compilador Inno Setup precisam de gerar artefactos Windows. A sessão Linux preparou e validou os scripts, mas não executou o `.exe` final.
