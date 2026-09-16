$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

Set-Location -LiteralPath $PSScriptRoot

$runtimeRoot = Join-Path $env:LOCALAPPDATA "Monash ED Downloader\runtime"
$uvInstallDir = Join-Path $runtimeRoot "uv-bin"
$userEnvironment = Join-Path $runtimeRoot "environment"
$pythonInstallDir = Join-Path $runtimeRoot "python"
$uvCacheDir = Join-Path $env:LOCALAPPDATA "Monash ED Downloader\Cache\uv"
$uvVersion = "0.12.13"
$uvExecutable = Join-Path $uvInstallDir "uv.exe"
$installer = $null

try {
    if (-not (Test-Path -LiteralPath $uvExecutable -PathType Leaf)) {
        Write-Host "First launch: preparing an isolated ED Downloader environment."
        Write-Host "Python, uv, and developer tools do not need to be installed manually."
        Write-Host ""

        New-Item -ItemType Directory -Force -Path $uvInstallDir | Out-Null
        New-Item -ItemType Directory -Force -Path $userEnvironment | Out-Null
        New-Item -ItemType Directory -Force -Path $pythonInstallDir | Out-Null
        New-Item -ItemType Directory -Force -Path $uvCacheDir | Out-Null

        $installer = Join-Path ([System.IO.Path]::GetTempPath()) (
            "monash-ed-uv-{0}.ps1" -f [System.Guid]::NewGuid().ToString("N")
        )
        Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "https://astral.sh/uv/$uvVersion/install.ps1" `
            -OutFile $installer

        $env:UV_UNMANAGED_INSTALL = $uvInstallDir
        $env:UV_NO_MODIFY_PATH = "1"
        & $installer
        if (-not (Test-Path -LiteralPath $uvExecutable -PathType Leaf)) {
            throw "uv was installed, but uv.exe was not found."
        }
    }

    $env:UV_PROJECT_ENVIRONMENT = $userEnvironment
    $env:UV_PYTHON_INSTALL_DIR = $pythonInstallDir
    $env:UV_CACHE_DIR = $uvCacheDir

    & $uvExecutable run --managed-python --no-dev --frozen ed-downloader menu
    exit $LASTEXITCODE
}
catch {
    Write-Host ""
    Write-Host "ED Downloader could not start:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Check the internet connection, then double-click the launcher again."
    exit 1
}
finally {
    if ($installer -and (Test-Path -LiteralPath $installer)) {
        Remove-Item -LiteralPath $installer -Force
    }
}
