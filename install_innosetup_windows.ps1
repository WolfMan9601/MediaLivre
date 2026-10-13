$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = Join-Path $env:LOCALAPPDATA 'MediaLivre\tools\InnoSetup'
$existing = Get-ChildItem -Path $installDir -Filter 'ISCC.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    Write-Host "Inno Setup já está disponível em $($existing.FullName)"
    exit 0
}

$temp = Join-Path $env:TEMP ('medialivre-inno-' + [guid]::NewGuid().ToString('N'))
$installer = Join-Path $temp 'innosetup.exe'
New-Item -ItemType Directory -Force -Path $temp, $installDir | Out-Null

try {
    Write-Host 'A obter o compilador Inno Setup oficial...'
    $headers = @{ 'User-Agent' = 'MediaLivre-installer-bootstrap' }
    $release = Invoke-RestMethod -Headers $headers -Uri 'https://api.github.com/repos/jrsoftware/issrc/releases/latest'
    $asset = $release.assets | Where-Object { $_.name -match '^innosetup-.*-x64\.exe$' } | Select-Object -First 1
    if ($null -eq $asset) {
        throw 'Não foi encontrado um instalador x64 oficial do Inno Setup.'
    }
    Invoke-WebRequest -Headers $headers -Uri $asset.browser_download_url -OutFile $installer -UseBasicParsing
    Write-Host "A instalar o compilador local em $installDir..."
    $args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=`"$installDir`"")
    $process = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "O instalador do Inno Setup terminou com o código $($process.ExitCode)."
    }
    $iscc = Get-ChildItem -Path $installDir -Filter 'ISCC.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $iscc) {
        throw "A instalação terminou, mas ISCC.exe não foi encontrado em $installDir."
    }
    Write-Host "Inno Setup pronto: $($iscc.FullName)"
}
finally {
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}
