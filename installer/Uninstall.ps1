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

# UI language: provisional guess from the OS culture, then confirmed by
# the game build once the directory is known. L() picks the string for
# the active language.
$script:LANG = switch ((Get-Culture).TwoLetterISOLanguageName) {
    'zh' { 'zh' }; 'en' { 'en' }; default { 'ja' } }
function L([string]$ja, [string]$zh, [string]$en = $ja) {
    if ($script:LANG -eq 'zh') { $zh }
    elseif ($script:LANG -eq 'en') { $en }
    else { $ja }
}
function Sha256([string]$p) { (Get-FileHash -Algorithm SHA256 $p).Hash }

# Same build detection as Install.ps1: zh ships Rance7GB.ald; en
# (Kagura) is its ain hash. The installed ain is patched so its hash
# differs - the state file recorded at install time carries the
# original. Failing both, the chosen backup's own ain is hashed later.
$script:EnAinHashes = @('A6B3693708144241',  # Kagura/Steam (all-ages)
                        'A24F5433C3CFA130')  # Kagura/Steam + adult patch
function Test-EnAinHash([string]$h) {
    return $script:EnAinHashes -contains $h.ToUpper()
}
function Get-GameLang([string]$dir) {
    if (Test-Path (Join-Path $dir 'Rance7GB.ald')) { return 'zh' }
    $st = Join-Path $dir 'hd_patch.state'
    if (Test-Path $st) {
        $s = Get-Content $st -Raw -ErrorAction SilentlyContinue
        if ($s -match 'ain=([0-9A-Fa-f]+)') {
            return $(if (Test-EnAinHash $Matches[1]) { 'en' }
                     else { 'ja' })
        }
        # state files from before the ain= field existed: the recorded
        # backup still holds the pristine original ain
        if ($s -match 'backup=([^;\r\n]+)') {
            $ba = Join-Path $Matches[1] 'Rance7.ain'
            if ((Test-Path $ba) -and
                (Test-EnAinHash ((Sha256 $ba).Substring(0, 16)))) {
                return 'en'
            }
        }
    }
    $a = Join-Path $dir 'Rance7.ain'
    if ((Test-Path $a) -and
        (Test-EnAinHash ((Sha256 $a).Substring(0, 16)))) { return 'en' }
    return $null   # unknown build - keep the OS-culture guess
}

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
        # once the dir is known the build decides the UI language
        # (updates the OS-culture guess above when conclusive)
        $l = Get-GameLang $GameDir
        if ($l) { $script:LANG = $l }
        Write-Host (L "  Steamインストール先を検出: $GameDir" `
                      "  已检测到 Steam 安装目录: $GameDir" `
                      "  Detected Steam install: $GameDir") -ForegroundColor Green
    } else {
        $GameDir = Read-Host (L "  戦国ランスのインストールフォルダを入力してください" `
                                "  请输入战国兰斯的安装文件夹" `
                                "  Enter the Sengoku Rance install folder")
    }
}
$GameDir = $GameDir.Trim().Trim('"').TrimEnd('\', '/')

# the game build decides the UI language for the rest of the run
$l = Get-GameLang $GameDir
if ($l) { $script:LANG = $l }

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host (L "   戦国ランス HDパッチ アンインストーラー" `
              "   战国兰斯 HD 补丁卸载程序" `
              "   Sengoku Rance HD Patch Uninstaller") -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

# Writing under Program Files requires elevation; relaunch elevated if needed.
$probe = Join-Path $GameDir (".hd_write_test_" + [guid]::NewGuid().ToString('N'))
try {
    [IO.File]::WriteAllText($probe, 'x'); Remove-Item $probe -Force
} catch {
    Write-Host (L "  書き込み権限が足りません。管理者権限でやり直します..." `
                  "  写入权限不足，将以管理员权限重试..." `
                  "  Insufficient write permission. Retrying as administrator...") `
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
    Write-Host (L "  エラー: Rance7.ain が見つかりません: '$GameDir'" `
                  "  错误: 找不到 Rance7.ain: '$GameDir'" `
                  "  Error: Rance7.ain not found: '$GameDir'") -ForegroundColor Red
    exit 1
}
if (Get-Process -Name Rance7 -ErrorAction SilentlyContinue) {
    Write-Host (L "  エラー: Rance7.exe が起動中です。先にゲームを閉じてください。" `
                  "  错误: Rance7.exe 正在运行。请先关闭游戏。" `
                  "  Error: Rance7.exe is running. Please close the game first.") `
        -ForegroundColor Red
    exit 1
}

if (-not $BackupDir) {
    $backs = Get-ChildItem (Join-Path $GameDir 'backup') -Directory -Filter 'hd_*' -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending
    if (-not $backs) {
        Write-Host (L "  エラー: backup\hd_* のバックアップが見つかりません。" `
                      "  错误: 找不到 backup\hd_* 备份。" `
                      "  Error: no backup\hd_* backups found.") `
            -ForegroundColor Red
        exit 1
    }
    Write-Host (L "  見つかったバックアップ:" "  找到的备份:" `
                  "  Backups found:")
    for ($i = 0; $i -lt $backs.Count; $i++) {
        Write-Host ("    [{0}] {1}" -f $i, $backs[$i].Name)
    }
    $sel = Read-Host (L "  復元する番号を入力（未入力 = 0 = 最新）" `
                        "  请输入要恢复的编号（留空 = 0 = 最新）" `
                        "  Enter the number to restore (empty = 0 = latest)")
    if ($sel -eq '') { $sel = '0' }
    $BackupDir = $backs[[int]$sel].FullName
}

if (-not (Test-Path (Join-Path $BackupDir 'Rance7.ain'))) {
    Write-Host (L "  エラー: '$BackupDir' はHDパッチのバックアップではないようです。" `
                  "  错误: '$BackupDir' 似乎不是 HD 补丁的备份。" `
                  "  Error: '$BackupDir' does not look like an HD patch backup.") `
        -ForegroundColor Red
    exit 1
}

# last resort for en detection when the state file is absent (e.g. a
# manually moved install): the backup holds the pristine original ain
if ($script:LANG -eq 'ja' -and
    (Test-EnAinHash ((Sha256 (Join-Path $BackupDir 'Rance7.ain')).Substring(0, 16)))) {
    $script:LANG = 'en'
}

# restore every file the backup holds (the set varies by build: jp/en
# carry Rance7GM+GA and AliceLogo3.*, zh carries GA+GB, AliceLogo2.* and
# an extra movie). Backup layout mirrors game-relative paths.
$restored = @()
Get-ChildItem $BackupDir -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($BackupDir.Length).TrimStart('\', '/')
    $dst = Join-Path $GameDir $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) |
        Out-Null
    Copy-Item -Force $_.FullName $dst
    $restored += ,@($_.FullName, $dst, $rel)
    Write-Host ((L "  復元: " "  恢复: " "  Restored: ") + $rel)
}

# Delete the used backup only after every restored file verifies.
$bad = @()
foreach ($r in $restored) {
    if ((Get-FileHash $r[1]).Hash -ne (Get-FileHash $r[0]).Hash) {
        $bad += $r[2]
    }
}
if ($bad) {
    Write-Host (L "  警告: 復元の検証に失敗しました: $($bad -join ', ')" `
                  "  警告: 恢复校验失败: $($bad -join ', ')" `
                  "  Warning: restore verification failed: $($bad -join ', ')") `
        -ForegroundColor Yellow
    Write-Host (L "  念のためバックアップ '$BackupDir' は残してあります。" `
                  "  为安全起见已保留备份 '$BackupDir'。" `
                  "  Keeping the backup '$BackupDir' just in case.") -ForegroundColor Yellow
} else {
    Remove-Item -Recurse -Force $BackupDir
    Write-Host (L "  検証OK。使用済みバックアップを削除しました: '$BackupDir'" `
                  "  校验通过。已删除使用过的备份: '$BackupDir'" `
                  "  Verified. Deleted the used backup: '$BackupDir'") -ForegroundColor DarkGray
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
    $ans = Read-Host ((L ("  HD素材キャッシュ 'hd_cache'（{0} GB）を削除しますか？ " +
                          "残すと次回インストールでAI生成工程をスキップできます [y/N]") `
                         ("  是否删除 HD 素材缓存 'hd_cache'（{0} GB）？" +
                          "保留后下次安装可跳过 AI 生成步骤 [y/N]") `
                         ("  Delete the HD asset cache 'hd_cache' ({0} GB)? " +
                          "Keeping it skips AI generation on the next install [y/N]")) -f $sz)
    if ($ans -match '^(y|yes)$') {
        Remove-Item -Recurse -Force $cacheDir -ErrorAction SilentlyContinue
        if (Test-Path $cacheDir) {
            Write-Host (L "  警告: '$cacheDir' を完全に削除できませんでした。" `
                          "  警告: 无法完全删除 '$cacheDir'。" `
                          "  Warning: could not fully delete '$cacheDir'.") `
                -ForegroundColor Yellow
        } else {
            Write-Host (L "  hd_cache を削除しました" "  已删除 hd_cache" `
                          "  hd_cache deleted") `
                -ForegroundColor DarkGray
        }
    } else {
        Write-Host (L "  hd_cache を残しました（次回インストールで生成を再利用します）" `
                      "  已保留 hd_cache（下次安装时将复用生成结果）" `
                      "  hd_cache kept (generation results are reused next install)") `
            -ForegroundColor DarkGray
    }
}
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host (L "   バックアップから復元しました。" "   已从备份恢复。" `
              "   Restored from backup.") -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
