<#
.SYNOPSIS
    One-command setup for Siesta on Windows.

.DESCRIPTION
    Installs a portable Ollama runtime (no admin rights, no system service),
    pulls the three open-weight models Siesta uses, creates a virtualenv and
    writes the local config.

    Everything lands in your user profile:
        $env:USERPROFILE\.ollama\dist      the runtime
        $env:USERPROFILE\.ollama\models    the model weights
        $env:USERPROFILE\.siesta           your data, digests and database
        $env:USERPROFILE\Siesta-Inbox      the folder Siesta watches

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1
    powershell -ExecutionPolicy Bypass -File setup.ps1 -SkipModels
#>
[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$SkipOllama,
    [string]$Python = "python",
    [string]$VisionModel = "qwen2.5vl:3b",
    [string]$TextModel = "qwen2.5:3b-instruct",
    [string]$EmbedModel = "nomic-embed-text"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Dist      = Join-Path $env:USERPROFILE ".ollama\dist"
$ZipUrl    = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
$Home      = Join-Path $env:USERPROFILE ".siesta"
$Inbox     = Join-Path $env:USERPROFILE "Siesta-Inbox"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Write-Ok($message)   { Write-Host "    ok  $message" -ForegroundColor Green }
function Write-Info($message) { Write-Host "    ..  $message" -ForegroundColor DarkGray }

# --------------------------------------------------------------------------- #
Write-Step "Checking Python"
try {
    $version = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if (-not $version) { throw "not found" }
    Write-Ok "Python $version"
} catch {
    Write-Host "    Python 3.10+ is required." -ForegroundColor Red
    Write-Host "    Install it from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
    exit 1
}

# --------------------------------------------------------------------------- #
$OllamaExe = $null
if (-not $SkipOllama) {
    Write-Step "Locating Ollama"

    $onPath = Get-Command ollama -ErrorAction SilentlyContinue
    if ($onPath) {
        $OllamaExe = $onPath.Source
        Write-Ok "found on PATH: $OllamaExe"
    } elseif (Test-Path (Join-Path $Dist "ollama.exe")) {
        $OllamaExe = Join-Path $Dist "ollama.exe"
        Write-Ok "found portable install: $OllamaExe"
    } else {
        Write-Info "downloading the portable runtime (~1.4 GB, no admin needed)..."
        $zip = Join-Path $env:TEMP "ollama-windows-amd64.zip"
        & curl.exe -L --retry 3 --retry-delay 5 -C - -o $zip $ZipUrl
        if ($LASTEXITCODE -ne 0) { Write-Host "download failed" -ForegroundColor Red; exit 1 }

        Write-Info "extracting..."
        New-Item -ItemType Directory -Force -Path $Dist | Out-Null
        Expand-Archive -Path $zip -DestinationPath $Dist -Force
        $OllamaExe = Join-Path $Dist "ollama.exe"
        if (-not (Test-Path $OllamaExe)) {
            Write-Host "ollama.exe not found after extraction" -ForegroundColor Red
            exit 1
        }
        Write-Ok "installed to $Dist"
    }

    $env:Path = "$Dist;$env:Path"

    Write-Step "Starting the Ollama server"
    $running = $false
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
        $running = $true
        Write-Ok "already running on http://127.0.0.1:11434"
    } catch {
        Write-Info "starting ollama serve in the background..."
        Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            try {
                Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
                $running = $true
                break
            } catch { }
        }
        if ($running) { Write-Ok "server is up" }
        else { Write-Host "    could not start the server; try running 'ollama serve' yourself" -ForegroundColor Yellow }
    }

    if ($running -and -not $SkipModels) {
        Write-Step "Pulling open-weight models"
        foreach ($model in @($VisionModel, $TextModel, $EmbedModel)) {
            Write-Info "$model ..."
            & $OllamaExe pull $model
        }
        Write-Ok "models ready"
    }
}

# --------------------------------------------------------------------------- #
Write-Step "Setting up the Python environment"
$Venv = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
    Write-Ok "created .venv"
} else {
    Write-Ok ".venv already exists"
}
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet -e ".[dev]"
Write-Ok "installed siesta (editable) + dev extras"

# --------------------------------------------------------------------------- #
Write-Step "Configuring Siesta"
New-Item -ItemType Directory -Force -Path $Home, $Inbox | Out-Null
$config = @{
    watch_dir    = $Inbox
    vision_model = $VisionModel
    text_model   = $TextModel
    embed_model  = $EmbedModel
} | ConvertTo-Json
Set-Content -Path (Join-Path $Home "config.json") -Value $config -Encoding UTF8
Write-Ok "config written to $(Join-Path $Home 'config.json')"

# --------------------------------------------------------------------------- #
Write-Host ""
Write-Host "Siesta is ready." -ForegroundColor Green
Write-Host ""
Write-Host "  1. Drop a photo in  $Inbox"
Write-Host "  2. Run a pass:      .\.venv\Scripts\python.exe -m siesta scan"
Write-Host "  3. Or the web UI:   .\.venv\Scripts\python.exe -m siesta serve"
Write-Host ""
Write-Host "Everything runs on this machine. No API key, no account, no network call." -ForegroundColor DarkGray
