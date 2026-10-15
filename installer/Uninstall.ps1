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
    [string]$BackupDir,
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'

# Same Steam auto-detection as Install.ps1.
function Find-SteamGame([string]$appId) {
    $steam = (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam' `
              -ErrorAction SilentlyContinue).InstallPath
    if (-not $steam) {
        $steam = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' `
                  -ErrorAction SilentlyContinue).SteamPath
    }
    if (-not $steam -or -not (Test-Path $steam)) { return $null }
    $libs = @($steam)
    $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
        $raw = Get-Content $vdf -Raw
        foreach ($m in [regex]::Matches($raw, '"path"\s+"((?:[^"\\]|\\.)+)"')) {
            $libs += $m.Groups[1].Value -replace '\\\\', '\'
        }
        foreach ($m in [regex]::Matches($raw,
                '(?m)^\s*"\d+"\s+"((?:[^"\\]|\\.)+)"')) {
            $libs += $m.Groups[1].Value -replace '\\\\', '\'
        }
    }
    foreach ($lib in ($libs | Select-Object -Unique)) {
        $acf = Join-Path $lib "steamapps\appmanifest_$appId.acf"
        if (Test-Path $acf) {
            $m = [regex]::Match((Get-Content $acf -Raw),
                 '"installdir"\s+"([^"]+)"')
            if ($m.Success) {
                $dir = Join-Path $lib ('steamapps\common\' + $m.Groups[1].Value)
                if (Test-Path (Join-Path $dir 'Rance7.exe')) { return $dir }
            }
        }
        $dir = Join-Path $lib 'steamapps\common\Sengoku Rance'
        if (Test-Path (Join-Path $dir 'Rance7.exe')) { return $dir }
    }
    return $null
}

if (-not $GameDir) {
    $GameDir = Find-SteamGame '3867170'
    if ($GameDir) {
        Write-Host "Detected install: $GameDir" -ForegroundColor Green
    } else {
        $GameDir = Read-Host "Path to the Sengoku Rance install folder"
    }
}
$GameDir = $GameDir.Trim().Trim('"').TrimEnd('\', '/')

# Writing under Program Files requires elevation; relaunch elevated if needed.
$probe = Join-Path $GameDir (".hd_write_test_" + [guid]::NewGuid().ToString('N'))
try {
    [IO.File]::WriteAllText($probe, 'x'); Remove-Item $probe -Force
} catch {
    Write-Host "No write access to '$GameDir' - requesting administrator rights..." `
        -ForegroundColor Yellow
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass',
              '-File', "`"$PSCommandPath`"",
              '-GameDir', "`"$GameDir`"")
    if ($BackupDir) { $args += @('-BackupDir', "`"$BackupDir`"") }
    $args += '-Elevated'
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit 0
}

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
$restored = @()
foreach ($f in $files) {
    $src = Join-Path $BackupDir $f
    $dst = Join-Path $GameDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src $dst
        $restored += ,@($src, $dst, $f)
        Write-Host "restored $f"
    }
}

# Delete the used backup only after every restored file verifies.
$bad = @()
foreach ($r in $restored) {
    if ((Get-FileHash $r[1]).Hash -ne (Get-FileHash $r[0]).Hash) {
        $bad += $r[2]
    }
}
if ($bad) {
    Write-Host "WARNING: verification failed for: $($bad -join ', ')" `
        -ForegroundColor Yellow
    Write-Host "Backup '$BackupDir' was kept." -ForegroundColor Yellow
} else {
    Remove-Item -Recurse -Force $BackupDir
    Write-Host "Verified; removed used backup '$BackupDir'." -ForegroundColor DarkGray
    # originals verified: clear the install-state marker so Install.ps1
    # can run again
    Remove-Item -Force (Join-Path $GameDir 'hd_patch.state') `
        -ErrorAction SilentlyContinue
}

# leftover generation intermediates / temp archives are safe to drop
Get-ChildItem $GameDir -Directory -Filter 'hd_gen_*' `
    -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $GameDir -File -Filter '*.hdtmp' `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# the payload cache (~2-3 GB) survives restores on purpose; offer to
# remove it since Steam's uninstall won't clean it either
$cacheDir = Join-Path $GameDir 'hd_cache'
if (Test-Path $cacheDir) {
    $sz = [math]::Round(
        ((Get-ChildItem $cacheDir -Recurse -File -ErrorAction SilentlyContinue |
          Measure-Object Length -Sum).Sum / 1GB), 1)
    $ans = Read-Host ("Delete the payload cache 'hd_cache' ({0} GB)? " +
                      "Keeping it makes re-installs much faster [y/N]" -f $sz)
    if ($ans -match '^(y|yes)$') {
        Remove-Item -Recurse -Force $cacheDir -ErrorAction SilentlyContinue
        if (Test-Path $cacheDir) {
            Write-Host "WARNING: could not fully remove '$cacheDir'." `
                -ForegroundColor Yellow
        } else {
            Write-Host "removed hd_cache" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "kept hd_cache (re-install will reuse it)" `
            -ForegroundColor DarkGray
    }
}
Write-Host ""
Write-Host "=== Restored from backup ===" -ForegroundColor Green
