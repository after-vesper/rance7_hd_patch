#requires -Version 5.1
<#
.SYNOPSIS
    Restore the most recent HD-patch backup created by Install.ps1.
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File Uninstall.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File Uninstall.ps1 -GameDir D:\Games\SengokuRance -BackupDir D:\Games\SengokuRance\backup\hd_20250101_120000
#>
param(
    [string]$GameDir,
    [string]$BackupDir
)

$ErrorActionPreference = 'Stop'

if (-not $GameDir) {
    $GameDir = Read-Host "Path to the Sengoku Rance install folder"
}
$GameDir = $GameDir.Trim().Trim('"').TrimEnd('\', '/')
if (-not (Test-Path (Join-Path $GameDir 'Rance7.ain'))) {
    Write-Host "ERROR: Rance7.ain not found in '$GameDir'" -ForegroundColor Red
    exit 1
}
if (Get-Process -Name Rance7 -ErrorAction SilentlyContinue) {
    Write-Host "ERROR: Rance7.exe is running - close the game first." -ForegroundColor Red
    exit 1
}

if (-not $BackupDir) {
    $backs = Get-ChildItem (Join-Path $GameDir 'backup') -Directory -Filter 'hd_*' -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending
    if (-not $backs) {
        Write-Host "ERROR: no backup\hd_* folder found." -ForegroundColor Red
        exit 1
    }
    Write-Host "Available backups:"
    for ($i = 0; $i -lt $backs.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f $i, $backs[$i].Name)
    }
    $sel = Read-Host "Backup index to restore (default 0 = newest)"
    if ($sel -eq '') { $sel = '0' }
    $BackupDir = $backs[[int]$sel].FullName
}

if (-not (Test-Path (Join-Path $BackupDir 'Rance7.ain'))) {
    Write-Host "ERROR: '$BackupDir' does not look like an HD patch backup." -ForegroundColor Red
    exit 1
}

$files = @('Rance7.ain', 'Rance7GM.ald', 'Rance7GA.ald', 'Rance7BA.ald',
           'Rance7WA.ald', 'System40.ini', 'AliceLogo3.alk',
           'DLL\AliceLogo3.dll')
foreach ($f in $files) {
    $src = Join-Path $BackupDir $f
    $dst = Join-Path $GameDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src $dst
        Write-Host "restored $f"
    }
}
Write-Host ""
Write-Host "=== Restored from $BackupDir ===" -ForegroundColor Green
