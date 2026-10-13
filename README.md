# MediaLivre

Aplicação desktop de código aberto para gerir transferências de vídeo e áudio a partir de ligações HTTP(S), com uma interface simples de qualidade, pasta, progresso e cancelamento. Projeto original, inspirado apenas no fluxo geral de um gestor de downloads; não reutiliza código, marca, ativos ou binários do 4K Video Downloader.

> Utilize apenas conteúdo que possui ou cuja transferência está autorizada. O MediaLivre não contorna DRM, paywalls, autenticação ou outros controlos de acesso. Respeite os termos do serviço de origem e a legislação aplicável.

## Funcionalidades do protótipo

- Interface desktop Qt em português.
- Layout com rolagem vertical adaptável a ecrãs pequenos, evitando que os controlos fiquem cortados.
- Transferência individual ou, com opção explícita, playlists e URLs de canais reconhecidas pelo yt-dlp.
- Escolha de qualidade: melhor disponível, 1080p, 720p ou 480p.
- Escolha do contêiner de vídeo: automático, MP4, MKV ou AVI.
- Extração opcional de áudio MP3 (requer FFmpeg).
- Pasta de destino, progresso global e progresso separado do vídeo atual em playlists/canais, log e cancelamento.
- Agendamentos únicos persistidos em SQLite, com estado, opções e cancelamento de tarefas pendentes.
- Execução do trabalho numa thread separada para manter a interface responsiva.
- Não tem contas, gestão de cookies, armazenamento de credenciais ou telemetria própria.

O suporte real depende das capacidades e alterações dos sites suportados pela dependência `yt-dlp`. O programa não promete compatibilidade permanente com qualquer serviço.

## Agendamento

Escolha o URL e as opções, selecione data/hora local e clique **Agendar este download**. A fila é gravada em `%LOCALAPPDATA%/MediaLivre/scheduled-downloads.sqlite3` no Windows (ou na pasta de dados do utilizador em Linux/macOS), não junto ao executável. Assim, executar a mesma cópia por `run_windows.bat` ou por `dist/MediaLivre/MediaLivre.exe` usa a mesma fila.

O agendador verifica a fila enquanto o MediaLivre está aberto, executa um download de cada vez e regista estados. Se o app estiver fechado na hora marcada, o trabalho vencido inicia na próxima abertura; **o app não acorda o computador nem executa tarefas enquanto está totalmente fechado**. Se um processo terminar abruptamente durante um download, o registo fica como falhado, sem repetição automática para evitar duplicados; reveja o ficheiro parcial antes de criar outro agendamento. Para execução com o app fechado, teria de configurar uma tarefa do Windows Task Scheduler separada.

A base guarda o URL e as opções do trabalho localmente sem encriptação própria. Evite agendar URLs assinados ou com tokens de acesso temporários; o diretório é restrito ao utilizador em sistemas POSIX e fica no perfil do utilizador em Windows.

## Requisitos

- Python 3.10 ou posterior.
- FFmpeg instalado e acessível no `PATH` para combinar faixas de áudio/vídeo ou extrair MP3.
- Dependências Python indicadas em `requirements.txt`.

## Executar a partir do código

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python medialivre.py
```

Se a política do PowerShell impedir a ativação, use diretamente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe medialivre.py
```

Instale FFmpeg separadamente e confirme que `ffmpeg.exe` está no `PATH` para áudio/combinação de streams.

Na lista **Formato do vídeo**, MP4 restringe a seleção a streams compatíveis com MP4; MKV converte/remuxa para Matroska; AVI usa vídeo Xvid e áudio MP3, quando os encoders FFmpeg necessários estão disponíveis. MKV/AVI e MP3 precisam de FFmpeg. A conversão AVI reencoda vídeo e áudio, pode demorar mais e pode reduzir a qualidade; MKV/MP4 tentam preservar os streams quando possível.

Para gerar o instalador Windows a partir de uma máquina Windows, instale o Python 3.10+ de 64 bits e o Inno Setup 6 e execute `create_installer_windows.bat`. O script compila com PyInstaller e em seguida usa `installer_windows.iss`; o instalador final ficará em `dist\installer\MediaLivre-Setup-0.4.0-win64.exe`. FFmpeg continua a ser instalado separadamente. Este build Windows não foi executado nem verificado neste ambiente Linux. Consulte [`INSTALAR_WINDOWS.md`](INSTALAR_WINDOWS.md).

Se apenas precisar de compilar a aplicação, execute `build_windows.bat`; cria `dist\MediaLivre\MediaLivre.exe` com os ficheiros de runtime adjacentes.

Para compilar manualmente no PowerShell, a partir da pasta do projeto:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name MediaLivre --collect-all yt_dlp --collect-all PySide6 --hidden-import download_scheduler medialivre.py
```

O comando padrão acima cria `dist\MediaLivre\MediaLivre.exe` e uma pasta de dependências. Para experimentar um único ficheiro (arranque inicial mais lento e maior probabilidade de alertas heurísticos do antivírus), adicione `--onefile`; o resultado passa para `dist\MediaLivre.exe`. Teste o executável num Windows limpo e instale FFmpeg separadamente no `PATH` para conversões/combinação de streams.

### Linux/macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python medialivre.py
```

Instale FFmpeg através do gestor de pacotes do sistema. Em ambiente sem display, a GUI não abre; os testes unitários podem correr sem iniciar a janela.

## Testar uma transferência

1. Instale Python, as dependências do projeto e FFmpeg conforme acima.
2. Inicie `python medialivre.py` (ou `run_windows.bat` no Windows).
3. Cole uma ligação HTTP(S) a um vídeo que criou, possui ou tem autorização para transferir. Comece com **Melhor disponível** e **Automático**; depois teste MP4, MKV e AVI separadamente.
4. Para uma playlist ou URL de canal compatível com yt-dlp, marque **Transferir playlists e canais completos** antes de iniciar. A interface mostra o progresso geral e, separadamente, o índice, o nome e o progresso do item atual. Uma playlist/canal pode conter muitos itens e ocupar muito espaço.
5. Confira o log e os ficheiros na pasta escolhida. Teste também **Cancelar**. A extração depende do suporte atual do yt-dlp ao serviço; não use com conteúdos sem autorização.

Também pode fazer um teste de integração isolado na sua própria máquina com um ficheiro de vídeo local seu: sirva-o apenas em `127.0.0.1` por HTTP e cole a URL local no MediaLivre. O teste exercita a transferência sem consultar um site externo. Um vídeo de teste pode ser gerado com FFmpeg:

```bash
ffmpeg -f lavfi -i color=c=blue:s=320x240:d=3 -f lavfi -i sine=frequency=440:duration=3 \
  -c:v mpeg4 -q:v 5 -c:a aac -shortest exemplo.mp4
python -m http.server 8765 --bind 127.0.0.1
```

Numa segunda janela, cole `http://127.0.0.1:8765/exemplo.mp4`. Pare o servidor depois do teste. A conversão depende da build local de FFmpeg e dos codecs instalados; o teste local não verifica suporte a sites de terceiros.

## Testes

```bash
python -m unittest discover -s tests -v
```

Além dos testes unitários, isto executa um teste de integração com um vídeo sintético servido apenas em `127.0.0.1`, verificando a transferência e o contêiner resultante MP4/MKV/AVI. O teste de integração é ignorado automaticamente se `ffmpeg` ou `ffprobe` não estiverem no `PATH`.

Os testes também usam uma base SQLite temporária para validar persistência, datas com fuso, reclamação de trabalho vencido, cancelamento e conclusão, sem tocar na fila real do utilizador.

## Segurança e privacidade

- O aplicativo aceita apenas URLs absolutas `http://` e `https://`, não caminhos locais.
- Não inclui campos para cookies, credenciais, cabeçalhos personalizados, argumentos arbitrários ou scripts do utilizador.
- A dependência de extração comunica diretamente com a origem e pode contactar serviços necessários à resolução da ligação. Consulte a documentação e as políticas desses serviços.
- Não execute aplicações ou ligações em que não confia. A validação de URL não autentica a origem nem garante que o conteúdo é seguro.
- Não há qualquer garantia de que o programa possa descarregar um conteúdo, especialmente quando requer conta, está protegido, é restrito ou o serviço altera a sua interface.

## Licença

O código original deste projeto está sob a licença MIT (ver `LICENSE`). As dependências mantêm as respetivas licenças e avisos; esta licença não os substitui.
