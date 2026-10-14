# Provision the installer runtime from scratch:
#   installer\runtime  - embeddable Python 3.10 + numpy/Pillow/scipy/ORT-DML
#   installer\bin      - alice.exe (alice-tools release)
#
# Usage: powershell -File ci\provision_runtime.ps1
# Requires: python 3.10 with pip on PATH (CI: actions/setup-python).
param(
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

$PyVer   = '3.10.11'
$PyUrl   = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
$AliceUrl = 'https://github.com/nunuhara/alice-tools/releases/download/0.13.0/alice-tools-0.13.0.zip'

$rtDir  = Join-Path $Root 'installer\runtime'
$binDir = Join-Path $Root 'installer\bin'
New-Item -ItemType Directory -Force $rtDir, $binDir | Out-Null

$tmp = Join-Path $env:TEMP ('hd_prov_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $tmp | Out-Null
try {
    if (-not (Test-Path (Join-Path $rtDir 'python.exe'))) {
        Write-Host "==> downloading python-$PyVer-embed-amd64.zip"
        $zip = Join-Path $tmp 'python.zip'
        Invoke-WebRequest -Uri $PyUrl -OutFile $zip
        Expand-Archive -Force $zip $rtDir
        # enable site-packages in the embeddable distro
        Set-Content (Join-Path $rtDir 'python310._pth') @(
            'python310.zip', '.', 'Lib\site-packages', 'import site')
    }

    $sitePkgs = Join-Path $rtDir 'Lib\site-packages'
    New-Item -ItemType Directory -Force $sitePkgs | Out-Null
    Write-Host "==> pip install -> Lib\site-packages"
    & $Python -m pip install --quiet --no-deps `
        --target $sitePkgs `
        'numpy==2.2.6' 'pillow==12.3.0' 'scipy==1.15.3' `
        'onnxruntime-directml==1.23.0'
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

    if (-not (Test-Path (Join-Path $binDir 'alice.exe'))) {
        Write-Host '==> downloading alice-tools 0.13.0'
        $azip = Join-Path $tmp 'alice.zip'
        Invoke-WebRequest -Uri $AliceUrl -OutFile $azip
        $adir = Join-Path $tmp 'alice'
        Expand-Archive -Force $azip $adir
        $exe = Get-ChildItem $adir -Recurse -Filter alice.exe |
               Select-Object -First 1
        if (-not $exe) { throw 'alice.exe not found in archive' }
        Copy-Item $exe.FullName (Join-Path $binDir 'alice.exe')
    }

    # smoke test: the runtime must import our dependencies
    & (Join-Path $rtDir 'python.exe') -c `
        'import numpy, PIL, onnxruntime; from scipy.ndimage import binary_dilation; print("runtime OK")'
    if ($LASTEXITCODE -ne 0) { throw 'runtime smoke test failed' }
    Write-Host '==> provisioned' $rtDir
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
