param(
    [string]$Version = "1.0.10",
    [switch]$SkipAppBuild,
    [switch]$SkipChrome,
    [switch]$SkipPortable,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $Root "build"
$DistRoot = Join-Path $Root "dist"
$ReleaseRoot = Join-Path $Root "release"
$AppDist = Join-Path $DistRoot "ProspectaFlow"
$Cache = Join-Path $PSScriptRoot "cache"

function Assert-LastExitCode([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action falhou com código $LASTEXITCODE."
    }
}

function Resolve-Iscc {
    $Command = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    foreach ($Candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if ($Candidate -and (Test-Path $Candidate)) { return $Candidate }
    }
    return $null
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot, $ReleaseRoot, $Cache | Out-Null

if (-not $SkipAppBuild) {
    Write-Host "Instalando dependências de build..."
    python -m pip install -r (Join-Path $Root "requirements-build.txt")
    Assert-LastExitCode "Instalação das dependências Python"

    Write-Host "Preparando gateway do WhatsApp..."
    Push-Location (Join-Path $Root "whatsapp_gateway")
    try {
        npm ci --omit=dev
        Assert-LastExitCode "Instalação das dependências Node"
    } finally {
        Pop-Location
    }

    Remove-Item -Recurse -Force (Join-Path $BuildRoot "pyinstaller") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $AppDist -ErrorAction SilentlyContinue

    Write-Host "Gerando aplicativo Python..."
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --workpath (Join-Path $BuildRoot "pyinstaller") `
        --distpath $DistRoot `
        (Join-Path $PSScriptRoot "ProspectaFlow.spec")
    Assert-LastExitCode "Empacotamento Python"

    $GatewayTarget = Join-Path $AppDist "whatsapp_gateway"
    New-Item -ItemType Directory -Force -Path $GatewayTarget | Out-Null
    Copy-Item (Join-Path $Root "whatsapp_gateway\server.js") $GatewayTarget
    Copy-Item (Join-Path $Root "whatsapp_gateway\package.json") $GatewayTarget
    Copy-Item (Join-Path $Root "whatsapp_gateway\package-lock.json") $GatewayTarget
    Copy-Item -Recurse (Join-Path $Root "whatsapp_gateway\node_modules") $GatewayTarget

    $NodeTarget = Join-Path $AppDist "runtime\node"
    New-Item -ItemType Directory -Force -Path $NodeTarget | Out-Null
    $NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
    Copy-Item $NodeExe (Join-Path $NodeTarget "node.exe")
} elseif (-not (Test-Path (Join-Path $AppDist "ProspectaFlow.exe"))) {
    throw "Pacote anterior não encontrado para -SkipAppBuild."
}

if (-not $SkipChrome) {
    Write-Host "Baixando Chrome for Testing e ChromeDriver..."
    $ManifestPath = Join-Path $Cache "chrome-manifest.json"
    curl.exe -fL --connect-timeout 15 --max-time 120 `
        "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" `
        -o $ManifestPath
    Assert-LastExitCode "Download do manifesto do Chrome"
    $Manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
    $Stable = $Manifest.channels.Stable
    $ChromeUrl = ($Stable.downloads.chrome | Where-Object platform -eq "win64").url
    $DriverUrl = ($Stable.downloads.chromedriver | Where-Object platform -eq "win64").url
    if (-not $ChromeUrl -or -not $DriverUrl) {
        throw "Downloads win64 do Chrome não foram encontrados."
    }

    $ChromeZip = Join-Path $Cache "chrome-win64.zip"
    $DriverZip = Join-Path $Cache "chromedriver-win64.zip"
    curl.exe -fL --connect-timeout 15 --max-time 900 $ChromeUrl -o $ChromeZip
    Assert-LastExitCode "Download do Chrome"
    curl.exe -fL --connect-timeout 15 --max-time 300 $DriverUrl -o $DriverZip
    Assert-LastExitCode "Download do ChromeDriver"

    $ChromeExtract = Join-Path $Cache "chrome"
    $DriverExtract = Join-Path $Cache "chromedriver"
    Remove-Item -Recurse -Force $ChromeExtract, $DriverExtract -ErrorAction SilentlyContinue
    Expand-Archive $ChromeZip $ChromeExtract
    Expand-Archive $DriverZip $DriverExtract
    Copy-Item -Recurse `
        (Join-Path $ChromeExtract "chrome-win64") `
        (Join-Path $AppDist "runtime\chrome")
    New-Item -ItemType Directory -Force `
        -Path (Join-Path $AppDist "runtime\chromedriver") | Out-Null
    Copy-Item `
        (Join-Path $DriverExtract "chromedriver-win64\chromedriver.exe") `
        (Join-Path $AppDist "runtime\chromedriver\chromedriver.exe")
}

Set-Content `
    -Path (Join-Path $AppDist "version.txt") `
    -Value $Version `
    -Encoding ascii

if (-not $SkipPortable) {
    $PortableZip = Join-Path $ReleaseRoot "ProspectaFlow-$Version-portable.zip"
    Remove-Item $PortableZip -ErrorAction SilentlyContinue
    $Tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
    if ($Tar) {
        Push-Location $AppDist
        try {
            & $Tar.Source -a -c -f $PortableZip *
            Assert-LastExitCode "Geração do pacote portátil"
        } finally {
            Pop-Location
        }
    } else {
        Compress-Archive -Path (Join-Path $AppDist "*") -DestinationPath $PortableZip
    }
}

if (-not $SkipInstaller) {
    $Iscc = Resolve-Iscc
    if (-not $Iscc) {
        throw "Inno Setup 6 não encontrado. Instale-o ou use -SkipInstaller."
    }
    Write-Host "Gerando instalador..."
    & $Iscc `
        "/DMyAppVersion=$Version" `
        "/O$ReleaseRoot" `
        (Join-Path $PSScriptRoot "ProspectaFlow.iss")
    Assert-LastExitCode "Geração do instalador"

    $Installer = Join-Path $ReleaseRoot "ProspectaFlowSetup.exe"
    $Hash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    $Metadata = [ordered]@{
        version = $Version
        url = "https://github.com/JeanVitorio/prospecta-flow-robot/releases/download/v$Version/ProspectaFlowSetup.exe"
        sha256 = $Hash
        required = $false
    }
    $Metadata | ConvertTo-Json | Set-Content `
        (Join-Path $ReleaseRoot "version.json") -Encoding utf8
}

Write-Host "Pacote concluído em: $ReleaseRoot"
