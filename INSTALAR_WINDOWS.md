# Instalação do MediaLivre no Windows

> **Para o utilizador final existe apenas um ficheiro:** `MediaLivre-Setup-0.14.1-win64.exe`. O `.bat` abaixo é usado somente na máquina que cria o instalador.

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
4. O setup EXE será criado em `dist\installer\MediaLivre-Setup-0.14.1-win64.exe` e copiado também para a raiz do projeto como `MediaLivre-Setup-0.14.1-win64.exe`.
5. Distribua somente esse ficheiro `.exe` e execute-o para instalar. A aplicação já leva consigo o runtime Python, FFmpeg, ffprobe, PySide6, yt-dlp, mutagen e os restantes recursos. A aplicação e os dados do agendador ficam em locais diferentes: a fila de downloads é preservada em `%LOCALAPPDATA%\MediaLivre` mesmo se a app for desinstalada.
6. O instalador cria por padrão um atalho no Ambiente de Trabalho e usa `medialivre.ico` no setup, no executável e no atalho; pode desmarcar essa opção durante a instalação.

FFmpeg, ffprobe e mutagen ficam incluídos no bundle do instalador. O utilizador final não precisa de os instalar separadamente para combinar streams, converter para MP3/MKV/AVI ou incorporar capas. Para áudio, a capa é embutida no quadrado do MP3 e o JPG temporário é removido; para vídeo, o programa guarda somente o ficheiro de vídeo.

## Publicar atualizações

O workflow `.github/workflows/windows-release.yml` cria o instalador na nuvem através de um runner Windows quando uma tag `vMAJOR.MINOR.PATCH` é enviada para o repositório. Por exemplo:

```bash
git tag v0.14.1
git push origin v0.14.1
```

O workflow publica o `.exe` e o respetivo SHA-256 na GitHub Release. O MediaLivre verifica diariamente as Releases de `WolfMan9601/MediaLivre` e marca o botão **Atualizações**. Ao clicar, pode escolher a versão desejada; quando existe instalador, a app descarrega-o, valida o SHA-256, inicia o setup com os parâmetros de atualização e fecha-se. Não é necessário localizar ou abrir o EXE manualmente. Releases sem instalador abrem apenas a sua página oficial.

## Se o PowerShell bloquear scripts

Não é necessário ativar a virtualenv. Os scripts `.bat` chamam diretamente `.venv\Scripts\python.exe`. Também pode executar a app com:

```bat
.venv\Scripts\python.exe medialivre.py
```

O instalador é produzido num Windows porque o PyInstaller e o compilador Inno Setup precisam de gerar artefactos Windows. A sessão Linux preparou e validou os scripts, mas não executou o `.exe` final.
