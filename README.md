# MediaLivre

Aplicação desktop de código aberto para gerir transferências de vídeo e áudio a partir de ligações HTTP(S), com uma interface simples de qualidade, pasta, progresso e cancelamento. Projeto original, inspirado apenas no fluxo geral de um gestor de downloads; não reutiliza código, marca, ativos ou binários do 4K Video Downloader.

> Utilize apenas conteúdo que possui ou cuja transferência está autorizada. O MediaLivre não contorna DRM, paywalls, autenticação ou outros controlos de acesso. Respeite os termos do serviço de origem e a legislação aplicável.

## Funcionalidades do protótipo

- Interface desktop Qt em português.
- Transferência de uma ligação HTTP(S), por predefinição; opção explícita para permitir listas.
- Escolha de qualidade: melhor disponível, 1080p, 720p ou 480p.
- Escolha do contêiner de vídeo: automático, MP4, MKV ou AVI.
- Extração opcional de áudio MP3 (requer FFmpeg).
- Pasta de destino, indicador de progresso, log e cancelamento.
- Execução do trabalho numa thread separada para manter a interface responsiva.
- Não tem contas, gestão de cookies, armazenamento de credenciais ou telemetria própria.

O suporte real depende das capacidades e alterações dos sites suportados pela dependência `yt-dlp`. O programa não promete compatibilidade permanente com qualquer serviço.

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

Para gerar uma pasta executável Windows a partir de uma máquina Windows, execute `build_windows.bat`. O artefacto será criado em `dist\MediaLivre\MediaLivre.exe`; FFmpeg continua a ser instalado separadamente. O script de build ainda não foi executado neste ambiente Linux.

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
4. Confira o progresso/log e o ficheiro na pasta escolhida. Teste também **Cancelar** e, se apropriado, a opção de lista de reprodução.

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

## Segurança e privacidade

- O aplicativo aceita apenas URLs absolutas `http://` e `https://`, não caminhos locais.
- Não inclui campos para cookies, credenciais, cabeçalhos personalizados, argumentos arbitrários ou scripts do utilizador.
- A dependência de extração comunica diretamente com a origem e pode contactar serviços necessários à resolução da ligação. Consulte a documentação e as políticas desses serviços.
- Não execute aplicações ou ligações em que não confia. A validação de URL não autentica a origem nem garante que o conteúdo é seguro.
- Não há qualquer garantia de que o programa possa descarregar um conteúdo, especialmente quando requer conta, está protegido, é restrito ou o serviço altera a sua interface.

## Licença

O código original deste projeto está sob a licença MIT (ver `LICENSE`). As dependências mantêm as respetivas licenças e avisos; esta licença não os substitui.
