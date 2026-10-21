# MediaLivre

Aplicação desktop de código aberto para gerir transferências de vídeo e áudio a partir de ligações HTTP(S), com uma interface simples de qualidade, pasta, progresso e cancelamento. Projeto original, inspirado apenas no fluxo geral de um gestor de downloads; não reutiliza código, marca, ativos ou binários do 4K Video Downloader.

> Utilize apenas conteúdo que possui ou cuja transferência está autorizada. O MediaLivre não contorna DRM, paywalls, autenticação ou outros controlos de acesso. Respeite os termos do serviço de origem e a legislação aplicável.

## Funcionalidades do protótipo

- Interface desktop Qt em português.
- Layout com rolagem vertical adaptável a ecrãs pequenos, evitando que os controlos fiquem cortados.
- Transferência individual, playlists e URLs de canais reconhecidas pelo yt-dlp; URLs de coleções são detetadas automaticamente.
- Seleção de itens antes de baixar uma playlist/canal, com botões para selecionar todos ou limpar a seleção.
- Botão **Saltar item** para ignorar somente a música/vídeo atual e continuar com os itens seguintes; **Cancelar** continua reservado para parar toda a fila.
- URLs individuais de TikTok, Instagram e outras fontes suportadas pelo yt-dlp. Perfis públicos suportados podem ser tratados como coleções quando o extrator disponibilizar os itens.
- URLs diretas HTTP(S) de ficheiros ou streams públicos também podem ser tentadas quando o serviço as fornece e a transferência é autorizada.
- Escolha de qualidade: melhor disponível, 1080p, 720p ou 480p.
- Escolha do contêiner de vídeo: automático, MP4, MKV ou AVI.
- Extração opcional de áudio MP3 e conversões usando FFmpeg/ffprobe preparados automaticamente no build Windows.
- Quando **Extrair apenas áudio (MP3)** está ativo, a capa é baixada temporariamente, incorporada no quadrado/arte do MP3 e removida como ficheiro separado. Para vídeos, nenhuma miniatura JPG é guardada: fica somente o ficheiro de vídeo.
- Pasta de destino, progresso global e progresso separado do vídeo atual em playlists/canais, log e cancelamento.
- Agendamentos únicos persistidos em SQLite, com estado, opções e cancelamento de tarefas pendentes.
- Execução do trabalho numa thread separada para manter a interface responsiva.
- Não tem contas próprias nem telemetria, nem recolhe cookies ou credenciais do utilizador.
- Consulta diariamente as GitHub Releases de `WolfMan9601/MediaLivre` em segundo plano e marca o botão **Atualizações** quando existe uma versão mais recente. A pessoa abre o botão, escolhe uma Release com instalador e checksum, e a app descarrega, valida o SHA-256, inicia o instalador silencioso e fecha-se; o próprio setup substitui os ficheiros e relança o MediaLivre automaticamente.

O suporte real depende das capacidades e alterações dos sites suportados pela dependência `yt-dlp`. Se uma página só for reconhecida pelo extrator genérico, o MediaLivre informa que não existe um extrator específico em vez de fingir que o problema é de MP4/FFmpeg. Nessa situação, use o download oficial ou uma URL direta do ficheiro/stream que tenha autorização para transferir. Conteúdo privado, expirado, limitado por idade ou sujeito a autenticação pode não estar disponível. O programa não promete compatibilidade permanente com qualquer serviço.

## Agendamento

Escolha o URL e as opções, selecione data/hora local e clique **Agendar este download**. A fila é gravada em `%LOCALAPPDATA%/MediaLivre/scheduled-downloads.sqlite3` no Windows (ou na pasta de dados do utilizador em Linux/macOS), não junto ao executável. Assim, executar a mesma cópia por `run_windows.bat` ou por `dist/MediaLivre/MediaLivre.exe` usa a mesma fila.

O agendador verifica a fila enquanto o MediaLivre está aberto, executa um download de cada vez e regista estados. Se o app estiver fechado na hora marcada, o trabalho vencido inicia na próxima abertura; **o app não acorda o computador nem executa tarefas enquanto está totalmente fechado**. Se um processo terminar abruptamente durante um download, o registo fica como falhado, sem repetição automática para evitar duplicados; reveja o ficheiro parcial antes de criar outro agendamento. Para execução com o app fechado, teria de configurar uma tarefa do Windows Task Scheduler separada.

A base guarda o URL e as opções do trabalho localmente sem encriptação própria. Evite agendar URLs assinados ou com tokens de acesso temporários; o diretório é restrito ao utilizador em sistemas POSIX e fica no perfil do utilizador em Windows.

## Requisitos

- Python 3.10 ou posterior.
- FFmpeg acessível no `PATH` para executar a partir do código em Linux/macOS. No fluxo Windows, `run_windows.bat` e `build_windows.bat` descarregam e preparam automaticamente `ffmpeg.exe` e `ffprobe.exe` no bundle.
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

Ao executar pelo `run_windows.bat`, o script `prepare_ffmpeg_windows.bat` descarrega automaticamente uma build Windows de FFmpeg, sem ativar `Activate.ps1`. A versão compilada usa primeiro os binários incluídos no próprio diretório da aplicação.

Na lista **Formato do vídeo**, MP4 seleciona preferencialmente vídeo H.264/AVC com áudio M4A/AAC para compatibilidade com o Windows. Se só houver outro codec MP4 com vídeo, o programa mantém a faixa de vídeo e recodifica o resultado para H.264/AAC, em vez de produzir um MP4 que toca apenas áudio. MKV converte/remuxa para Matroska; AVI usa vídeo Xvid e áudio MP3, quando os encoders FFmpeg necessários estão disponíveis. MKV/AVI e MP3 precisam de FFmpeg. A conversão MP4/AVI reencoda vídeo e áudio, pode demorar mais e pode reduzir a qualidade; MKV tenta preservar os streams quando possível.

Para gerar o instalador Windows, instale apenas o Python 3.10+ de 64 bits e execute `create_installer_windows.bat` na máquina de compilação. Se o Inno Setup não estiver instalado, o script baixa automaticamente o compilador oficial mais recente para `%LOCALAPPDATA%\MediaLivre\tools\InnoSetup`, sem exigir `Activate.ps1` nem instalação manual. Em seguida prepara FFmpeg/ffprobe, compila com PyInstaller e usa `installer_windows.iss`. O resultado distribuível desta versão é um único `MediaLivre-Setup-0.13.1-win64.exe`, criado em `dist\installer` e copiado também para a raiz do projeto. O utilizador final executa somente esse EXE: ele já contém o runtime Python, PySide6, yt-dlp, mutagen, FFmpeg, ffprobe e o ícone, e cria o atalho do Ambiente de Trabalho por predefinição. Este build Windows não foi executado nem verificado neste ambiente Linux. Consulte [`INSTALAR_WINDOWS.md`](INSTALAR_WINDOWS.md).

### Atualizações e GitHub Actions

O ficheiro `.github/workflows/windows-release.yml` compila automaticamente o instalador num runner Windows sempre que uma tag `vMAJOR.MINOR.PATCH` é enviada para o GitHub. O workflow atualiza a versão, prepara Python e FFmpeg, executa o build, gera o SHA-256 e publica `MediaLivre-Setup-{versão}-win64.exe` como asset da GitHub Release. Para lançar uma nova versão:

```bash
git tag v0.13.1
git push origin v0.13.1
```

O aplicativo consulta `https://api.github.com/repos/WolfMan9601/MediaLivre/releases?per_page=50` no máximo uma vez por dia. O botão **Atualizações** permite consultar manualmente a lista e escolher uma versão específica. A atualização automática só é disponibilizada quando a Release contém o instalador EXE e o respetivo checksum SHA-256: o MediaLivre descarrega-o em segundo plano, valida-o, inicia o setup com os parâmetros de atualização e fecha a aplicação; não é necessário localizar ou abrir o EXE manualmente. Releases incompletas abrem apenas a página oficial. Sem Internet ou sem uma Release disponível, o MediaLivre continua a funcionar normalmente.

Se apenas precisar de compilar a aplicação, execute `build_windows.bat`; cria `dist\MediaLivre\MediaLivre.exe` com os ficheiros de runtime e a pasta `ffmpeg` adjacentes.

Para compilar manualmente no PowerShell, a partir da pasta do projeto:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name MediaLivre --icon assets\medialivre.ico --add-data "assets;assets" --collect-all yt_dlp --collect-all PySide6 --hidden-import download_scheduler --hidden-import mutagen medialivre.py
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
3. Cole uma ligação HTTP(S) a um vídeo que criou, possui ou tem autorização para transferir. Comece com **Melhor disponível** e **Automático**; depois teste MP4, MKV e AVI separadamente. Para áudio, marque **Extrair apenas áudio (MP3)**; o controlo **Incorporar capa no MP3 (sem imagem JPG separada)** fica disponível e vem ativado. O JPG é temporário e é removido depois de a capa ser gravada no MP3. Com vídeo, a miniatura/capa não é guardada separadamente. Se o log indicar **sem extrator específico**, a página não é suportada pelo yt-dlp instalado; procure no serviço o link oficial ou uma URL direta autorizada.
4. Para uma playlist, URL de canal ou perfil público compatível com yt-dlp, a caixa **Transferir playlists e canais completos** já vem marcada. Ao iniciar, o programa lê os itens e abre uma lista para desmarcar músicas ou vídeos. Também pode usar **Escolher itens** antes de iniciar, ou **Selecionar todos/Limpar seleção** dentro da janela. Desmarque a caixa se quiser tratar uma URL com lista como item individual.
5. Durante uma fila com vários itens, use **Saltar item** para ignorar somente o item atual e continuar com o seguinte. Use **Cancelar** para interromper toda a fila. Confira o log e os ficheiros na pasta escolhida. A extração depende do suporte atual do yt-dlp ao serviço; não use com conteúdos sem autorização.
6. Para TikTok e Instagram, cole uma URL individual pública. Perfis ou coleções públicas suportadas podem abrir a seleção de itens. Conteúdo privado, expirado, limitado por idade ou que exige sessão pode não ser acessível sem autenticação; o MediaLivre não contorna esses controlos.

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
- Não inclui campos para cookies, credenciais, cabeçalhos personalizados, argumentos arbitrários ou scripts do utilizador, nem envia credenciais para um servidor próprio. Também não adiciona scrapers específicos para páginas de filmes, DRM, paywalls ou áreas autenticadas.
- A dependência de extração comunica diretamente com a origem e pode contactar serviços necessários à resolução da ligação. Consulte a documentação e as políticas desses serviços.
- Não execute aplicações ou ligações em que não confia. A validação de URL não autentica a origem nem garante que o conteúdo é seguro.
- Não há qualquer garantia de que o programa possa descarregar um conteúdo, especialmente quando requer conta, está protegido, é restrito ou o serviço altera a sua interface.

## Licença

O código original deste projeto está sob a licença MIT (ver `LICENSE`). As dependências mantêm as respetivas licenças e avisos; esta licença não os substitui.
