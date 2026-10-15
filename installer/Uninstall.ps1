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

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "   戦国ランス HDパッチ アンインストーラー" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

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
        Write-Host "  Steamインストール先を検出: $GameDir" -ForegroundColor Green
    } else {
        $GameDir = Read-Host "  戦国ランスのインストールフォルダを入力してください"
    }
}
$GameDir = $GameDir.Trim().Trim('"').TrimEnd('\', '/')

# Writing under Program Files requires elevation; relaunch elevated if needed.
$probe = Join-Path $GameDir (".hd_write_test_" + [guid]::NewGuid().ToString('N'))
try {
    [IO.File]::WriteAllText($probe, 'x'); Remove-Item $probe -Force
} catch {
    Write-Host "  書き込み権限が足りません。管理者権限でやり直します..." `
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
    Write-Host "  エラー: Rance7.ain が見つかりません: '$GameDir'" -ForegroundColor Red
    exit 1
}
if (Get-Process -Name Rance7 -ErrorAction SilentlyContinue) {
    Write-Host "  エラー: Rance7.exe が起動中です。先にゲームを閉じてください。" `
        -ForegroundColor Red
    exit 1
}

if (-not $BackupDir) {
    $backs = Get-ChildItem (Join-Path $GameDir 'backup') -Directory -Filter 'hd_*' -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending
    if (-not $backs) {
        Write-Host "  エラー: backup\hd_* のバックアップが見つかりません。" `
            -ForegroundColor Red
        exit 1
    }
    Write-Host "  見つかったバックアップ:"
    for ($i = 0; $i -lt $backs.Count; $i++) {
        Write-Host ("    [{0}] {1}" -f $i, $backs[$i].Name)
    }
    $sel = Read-Host "  復元する番号を入力（未入力 = 0 = 最新）"
    if ($sel -eq '') { $sel = '0' }
    $BackupDir = $backs[[int]$sel].FullName
}

if (-not (Test-Path (Join-Path $BackupDir 'Rance7.ain'))) {
    Write-Host "  エラー: '$BackupDir' はHDパッチのバックアップではないようです。" `
        -ForegroundColor Red
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
        Write-Host "  復元: $f"
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
    Write-Host "  警告: 復元の検証に失敗しました: $($bad -join ', ')" `
        -ForegroundColor Yellow
    Write-Host "  念のためバックアップ '$BackupDir' は残してあります。" -ForegroundColor Yellow
} else {
    Remove-Item -Recurse -Force $BackupDir
    Write-Host "  検証OK。使用済みバックアップを削除しました: '$BackupDir'" -ForegroundColor DarkGray
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
    $ans = Read-Host ("  HDキャッシュ 'hd_cache'（{0} GB）を削除しますか？ " +
                      "残すと再インストールが一瞬です [y/N]" -f $sz)
    if ($ans -match '^(y|yes)$') {
        Remove-Item -Recurse -Force $cacheDir -ErrorAction SilentlyContinue
        if (Test-Path $cacheDir) {
            Write-Host "  警告: '$cacheDir' を完全に削除できませんでした。" `
                -ForegroundColor Yellow
        } else {
            Write-Host "  hd_cache を削除しました" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  hd_cache は残しました（再インストール時に再利用されます）" `
            -ForegroundColor DarkGray
    }
}
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host "   バックアップから復元しました。" -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
