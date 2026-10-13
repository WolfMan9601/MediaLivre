# MediaLivre

Aplicação desktop de código aberto para gerir transferências de vídeo e áudio a partir de ligações HTTP(S), com uma interface simples de qualidade, pasta, progresso e cancelamento. Projeto original, inspirado apenas no fluxo geral de um gestor de downloads; não reutiliza código, marca, ativos ou binários do 4K Video Downloader.

> Utilize apenas conteúdo que possui ou cuja transferência está autorizada. O MediaLivre não contorna DRM, paywalls, autenticação ou outros controlos de acesso. Respeite os termos do serviço de origem e a legislação aplicável.

## Funcionalidades do protótipo

- Interface desktop Qt em português.
- Transferência de uma ligação HTTP(S), por predefinição; opção explícita para permitir listas.
- Escolha de qualidade: melhor disponível, 1080p, 720p ou 480p.
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

### Linux/macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python medialivre.py
```

Instale FFmpeg através do gestor de pacotes do sistema. Em ambiente sem display, a GUI não abre; os testes unitários podem correr sem iniciar a janela.

## Testes

```bash
python -m unittest discover -s tests -v
```

## Segurança e privacidade

- O aplicativo aceita apenas URLs absolutas `http://` e `https://`, não caminhos locais.
- Não inclui campos para cookies, credenciais, cabeçalhos personalizados, argumentos arbitrários ou scripts do utilizador.
- A dependência de extração comunica diretamente com a origem e pode contactar serviços necessários à resolução da ligação. Consulte a documentação e as políticas desses serviços.
- Não execute aplicações ou ligações em que não confia. A validação de URL não autentica a origem nem garante que o conteúdo é seguro.
- Não há qualquer garantia de que o programa possa descarregar um conteúdo, especialmente quando requer conta, está protegido, é restrito ou o serviço altera a sua interface.

## Licença

O código original deste projeto está sob a licença MIT (ver `LICENSE`). As dependências mantêm as respetivas licenças e avisos; esta licença não os substitui.
