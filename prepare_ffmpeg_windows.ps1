$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root 'third_party\ffmpeg\bin'
$ffmpegExe = Join-Path $target 'ffmpeg.exe'
$ffprobeExe = Join-Path $target 'ffprobe.exe'

if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
    Write-Host "FFmpeg já preparado em $target"
    exit 0
}

$url = $env:MEDIALIVRE_FFMPEG_URL
if ([string]::IsNullOrWhiteSpace($url)) {
    # Windows essentials build; the final setup embeds the binaries, so the end user
    # does not need Python, pip, yt-dlp or a separate FFmpeg installation.
    $url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
}

$temp = Join-Path $env:TEMP ('medialivre-ffmpeg-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $temp 'ffmpeg.zip'
$extract = Join-Path $temp 'extract'
New-Item -ItemType Directory -Force -Path $temp, $extract, $target | Out-Null

try {
    Write-Host "A descarregar FFmpeg para preparar o instalador..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $foundFfmpeg = Get-ChildItem -Path $extract -Filter 'ffmpeg.exe' -File -Recurse | Select-Object -First 1
    $foundFfprobe = Get-ChildItem -Path $extract -Filter 'ffprobe.exe' -File -Recurse | Select-Object -First 1
    if ($null -eq $foundFfmpeg -or $null -eq $foundFfprobe) {
        throw 'O arquivo FFmpeg descarregado não contém ffmpeg.exe e ffprobe.exe.'
    }
    Copy-Item $foundFfmpeg.FullName $ffmpegExe -Force
    Copy-Item $foundFfprobe.FullName $ffprobeExe -Force

    $licenseDir = Join-Path $root 'third_party\ffmpeg\licenses'
    New-Item -ItemType Directory -Force -Path $licenseDir | Out-Null
    Get-ChildItem -Path $extract -File -Recurse -Include 'LICENSE*','COPYING*' | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $licenseDir $_.Name) -Force -ErrorAction SilentlyContinue
    }
    Write-Host 'FFmpeg e ffprobe preparados com sucesso.'
}
finally {
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}
