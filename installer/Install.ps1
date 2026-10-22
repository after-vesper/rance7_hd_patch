#requires -Version 5.1
<#
.SYNOPSIS
    Sengoku Rance HD patch installer - plain Windows, no extra tools needed.
.DESCRIPTION
    Applies the 1600x1200 HD patch to a Sengoku Rance (Steam) install:
      * Rance7.ain   - anchor-based coordinate/layout doubling
      * Rance7GM.ald / Rance7GA.ald - HD asset payload repack
        (zh build: Rance7GA.ald / Rance7GB.ald - its GM is dormant)
      * AliceLogo*.alk / DLL\AliceLogo*.dll - HD logo animation
      * movie\*.alm - HD OP/ED movies
      * System40.ini - ViewWidth/ViewHeight -> 1600x1200
    Compatible with vanilla, JP-patched, zh and unofficial-patch
    installs, in any application order. Creates a timestamped backup
    under backup\hd_* before touching anything.
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File Install.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File Install.ps1 -GameDir D:\Games\SengokuRance
#>
param(
    [string]$GameDir,
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# The ja/zh UI strings are emitted from both PowerShell (UTF-16 console
# API, always fine) and the embedded python (byte-oriented stdout which
# encodes via the console codepage: cp932/cp936 cannot represent the
# other language's characters and would crash on print). Force UTF-8
# on both sides so mixed output renders in any console.
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'

# UI language: provisional guess from the OS culture, then confirmed by
# the game build once the directory is known (zh ships Rance7GB.ald;
# the en/Kagura build is identified by its ain hash). L() picks the
# string for the active language.
$script:LANG = switch ((Get-Culture).TwoLetterISOLanguageName) {
    'zh' { 'zh' }; 'en' { 'en' }; default { 'ja' } }
function L([string]$ja, [string]$zh, [string]$en = $ja) {
    if ($script:LANG -eq 'zh') { $zh }
    elseif ($script:LANG -eq 'en') { $en }
    else { $ja }
}

function Fail([string]$msg) {
    Write-Host ""
    Write-Host (L "  エラー: $msg" "  错误: $msg" "  Error: $msg") `
        -ForegroundColor Red
    # drop generation intermediates if the directory was created
    if ($genDir -and (Test-Path $genDir)) {
        Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
    }
    if ($Elevated) {
        Read-Host (L "Enterキーを押して閉じてください" "按 Enter 键关闭" `
                      "Press Enter to close") | Out-Null
    }
    exit 1
}

function Sha256([string]$p) { (Get-FileHash -Algorithm SHA256 $p).Hash }

# Build detection for the UI language: the zh build ships Rance7GB.ald;
# the en (Kagura) build is identified by its stock ain hash. Once the
# ain is HD-patched its hash no longer matches stock, so the state file
# written at install time carries the original hash.
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

# Locate the game via Steam: registry -> libraryfolders.vdf ->
# appmanifest_<appid>.acf (installdir is authoritative).
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
        # current format: "path"  "C:\\Steam"
        foreach ($m in [regex]::Matches($raw, '"path"\s+"((?:[^"\\]|\\.)+)"')) {
            $libs += $m.Groups[1].Value -replace '\\\\', '\'
        }
        # legacy format: "1"  "D:\\SteamLibrary"
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

# ---------- prerequisites ----------

$aliceExe = Join-Path $Root 'bin\alice.exe'
$csPath   = Join-Path $Root 'HdPatch.cs'
$dataDir  = Join-Path $Root 'data'
$manifest = Join-Path $dataDir 'manifest.json'
$sites    = Join-Path $dataDir 'hd_sites.json'
foreach ($req in @($aliceExe, $csPath, $manifest, $sites)) {
    if (-not (Test-Path $req)) {
        Fail (L "インストーラーのファイルが不足しています: $req" `
                "安装程序文件缺失: $req" `
                "Missing installer file: $req")
    }
}

# ---------- locate the game ----------

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
        Write-Host ""
    } else {
        Write-Host (L "  Steamからの自動検出に失敗しました。" `
                      "  Steam 自动检测失败。" `
                      "  Steam auto-detection failed.") -ForegroundColor Yellow
        $GameDir = Read-Host (L "  戦国ランスのインストールフォルダを入力してください（Rance7.exe がある場所）" `
                                "  请输入战国兰斯的安装文件夹（Rance7.exe 所在位置）" `
                                "  Enter the Sengoku Rance install folder (where Rance7.exe is)")
    }
}
$GameDir = $GameDir.Trim().Trim('"').TrimEnd('\', '/')

# the game build decides both the archive layout and the UI language
# for the rest of the run (zh ships Rance7GB.ald; en is its ain hash)
$l = Get-GameLang $GameDir
if ($l) { $script:LANG = $l }
$env:GEN_LANG = $script:LANG   # the python gen scripts read this

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host (L "   戦国ランス HDパッチ インストーラー" `
              "   战国兰斯 HD 补丁安装程序" `
              "   Sengoku Rance HD Patch Installer") -ForegroundColor Cyan
Write-Host (L "   （アリスソフト非公式のファン制作パッチです）" `
              "   （AliceSoft 非官方同人补丁）" `
              "   (unofficial fan-made patch - not affiliated with AliceSoft)") `
    -ForegroundColor Cyan
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
              '-GameDir', "`"$GameDir`"", '-Elevated')
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit 0
}
$ainPath = Join-Path $GameDir 'Rance7.ain'
$iniPath = Join-Path $GameDir 'System40.ini'
if (-not (Test-Path $ainPath)) {
    Fail (L "Rance7.ain が見つかりません: '$GameDir'" `
            "找不到 Rance7.ain: '$GameDir'" `
            "Rance7.ain not found: '$GameDir'")
}
if (-not (Test-Path $iniPath)) {
    Fail (L "System40.ini が見つかりません: '$GameDir'" `
            "找不到 System40.ini: '$GameDir'" `
            "System40.ini not found: '$GameDir'")
}

if (Get-Process -Name Rance7 -ErrorAction SilentlyContinue) {
    Fail (L "Rance7.exe が起動中です。先にゲームを閉じてください。" `
            "Rance7.exe 正在运行。请先关闭游戏。" `
            "Rance7.exe is running. Please close the game first.")
}

# ---------- interrupted / already-installed guard ----------
#
# hd_patch.state is written just before the first file replacement and
# stays until Uninstall.ps1 removes it. If a previous run died after the
# repack began, the game archives may already be HD - backing those up
# and regenerating from them would double-upscale the assets, so refuse
# and make the user restore first.
$statePath = Join-Path $GameDir 'hd_patch.state'
if (Test-Path $statePath) {
    $prev = (Get-Content $statePath -Raw -ErrorAction SilentlyContinue)
    if ($prev -match 'in-progress') {
        Fail (L ("前回のインストールがファイル置き換えの途中で中断しています。`n" +
                 "先に Uninstall.cmd でバックアップから復旧してから、やり直してください。") `
                ("上次安装在文件替换过程中被中断。`n" +
                 "请先运行 Uninstall.cmd 从备份恢复，然后再重试。") `
                ("The previous install was interrupted during file replacement.`n" +
                 "Run Uninstall.cmd to restore the backup first, then retry."))
    }
    # a Steam reinstall leaves hd_patch.state behind while restoring
    # pristine files - detect it via System40.ini before refusing.
    # ('in-progress' above is handled first: the ini is written last,
    # so an interrupted run would look pristine here yet still need a
    # restore to avoid double-upscaling already-HD archives)
    $iniNow = [Text.Encoding]::GetEncoding(932).GetString(
        [IO.File]::ReadAllBytes($iniPath))
    if ($iniNow -notmatch '(?m)^ViewWidth\s*=\s*1600') {
        Write-Host (L "  状態ファイルは残っていますが、ゲームファイルは素の状態です" `
                      "  状态文件仍然存在，但游戏文件为原始状态" `
                      "  State file remains but game files are pristine") `
            -ForegroundColor Yellow
        Write-Host (L "  （Steam再インストール等で上書きされたようです）。続行します。" `
                      "  （可能被 Steam 重装覆盖了）。继续执行。" `
                      "  (a Steam reinstall seems to have overwritten them). Continuing.") `
            -ForegroundColor Yellow
        Remove-Item -Force $statePath -ErrorAction SilentlyContinue
    } else {
        Fail (L ("このゲームには既にHDパッチが適用済みです。`n" +
                 "元に戻したい場合は先に Uninstall.cmd を実行してください。") `
                ("此游戏已应用 HD 补丁。`n" +
                 "如需还原请先运行 Uninstall.cmd。") `
                ("The HD patch is already installed on this game.`n" +
                 "To revert, run Uninstall.cmd first."))
    }
}

# Stale intermediates from an interrupted generation run (never reached
# the modification phase, so the game files are still pristine).
Get-ChildItem $GameDir -Directory -Filter 'hd_gen_*' `
    -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $GameDir -File -Filter '*.hdtmp' `
    -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# ---------- variant detection ----------

$ainHash = (Sha256 $ainPath).Substring(0, 16)
$knownAin = @{
    'B4459F0637F7E1B0' = (L '通常版（Steam・未改造）' '普通版（Steam·未修改）' 'vanilla (Steam, unmodified)')
    '7CB8B11941A14007' = (L 'JPパッチ適用済み' '已应用 JP 补丁' 'JP patch applied')
    'BF84072AAD157812' = (L '中国語版（簡体字）' '简体中文版' 'Simplified Chinese')
    'A6B3693708144241' = (L '英語版（Kagura/Steam）' '英文版（Kagura/Steam）' 'English (Kagura/Steam)')
    'A24F5433C3CFA130' = (L '英語版＋アダルトパッチ適用済み' '英文版＋成人补丁已应用' 'English (Kagura/Steam) + adult patch')
}
$variant = $knownAin[$ainHash]
if (-not $variant) { $variant = (L "改造済み/非公式パッチ版 (ain hash $ainHash)" `
                                  "改造済み/非官方补丁版 (ain hash $ainHash)" `
                                  "modified/unofficial patch (ain hash $ainHash)") }
$isEn = Test-EnAinHash $ainHash
if ($isEn) {
    # the en build rewrote its message-UI functions during localization;
    # it needs the en-anchored site set produced by tools/en_export_sites.py
    $sitesEn = Join-Path $dataDir 'hd_sites_en.json'
    if (-not (Test-Path $sitesEn)) {
        Fail (L "インストーラーのファイルが不足しています: $sitesEn" `
                "安装程序文件缺失: $sitesEn" `
                "Missing installer file: $sitesEn")
    }
    $sites = $sitesEn
}

# Archive layouts differ by language build:
#   jp/en: Rance7GM.ald is the live CG archive, Rance7GA.ald holds the
#          cg045xx set and receives payloads moved out of GM
#   zh   : Rance7GA.ald is the live CG archive and Rance7GB.ald holds
#          cg045xx; Rance7GM.ald is a dormant duplicate (verified by
#          runtime test - the game boots and renders without it)
$gmPath = Join-Path $GameDir 'Rance7GM.ald'
$gaPath = Join-Path $GameDir 'Rance7GA.ald'
$gbPath = Join-Path $GameDir 'Rance7GB.ald'
$isZh = Test-Path $gbPath
if ($isZh) {
    if (-not (Test-Path $gaPath)) {
        Fail (L "Rance7GA.ald が見つかりません" "找不到 Rance7GA.ald" `
                "Rance7GA.ald not found")
    }
} else {
    if (-not (Test-Path $gmPath)) {
        Fail (L "Rance7GM.ald が見つかりません" "找不到 Rance7GM.ald" `
                "Rance7GM.ald not found")
    }
    if (-not (Test-Path $gaPath)) {
        Fail (L "Rance7GA.ald が見つかりません" "找不到 Rance7GA.ald" `
                "Rance7GA.ald not found")
    }
}

# The JP patch rewrites the GM archive (R18 CGs); vanilla payloads are
# derived from the censored sources so the asset set must match the base.
if ($isZh) {
    $assetSet = 'zh'
} else {
    $gmHash = (Sha256 $gmPath).Substring(0, 12)
    if ($gmHash -eq '27D55DF49209') { $assetSet = 'jp' }
    elseif ($gmHash -eq '0B20D110235A') { $assetSet = 'vanilla' }
    elseif ($gmHash -eq '885D68EE73E8') { $assetSet = 'vanilla' }  # en build:
        # its GM content is the same all-ages set as the zh/vanilla line
    elseif ($gmHash -eq '8F09183896E6') { $assetSet = 'jp' }       # en + adult
        # patch: its GM carries the R18 set, which the jp payloads cover
    else { $assetSet = 'jp' }   # modified/unknown ald: jp assets were built on jp base
}

# 'jp' payloads are the R18 CG set; on an en install they are pulled in
# by the adult patch, so show a name users recognize instead of 'jp'.
$assetSetDisp = if ($isEn -and $assetSet -eq 'jp') { 'adult' }
                else { $assetSet }

Write-Host ""
Write-Host ((L "  対象         : " "  目标         : " `
               "  Target       : ") + $GameDir)
Write-Host ((L "  AINバリアント: " "  AIN版本      : " `
               "  AIN variant  : ") + $variant)
Write-Host ((L "  素材セット   : " "  素材集       : " `
               "  Asset set    : ") + $assetSetDisp)
Write-Host ""

# ---------- free space check (repack needs orig + new archive) ----------

# orig archives + new archives + generated intermediates + persistent
# payload cache (~2.5 GB each) + movie originals (backed up) and the
# ~1.4x larger HD re-encodes staged next to them
if ($isZh) {
    $need = (Get-Item $gaPath).Length + (Get-Item $gbPath).Length + 8GB
} else {
    $need = (Get-Item $gmPath).Length + (Get-Item $gaPath).Length + 8GB
}
foreach ($mv in (Get-ChildItem (Join-Path $GameDir 'movie') -Filter '*.alm' -File -ErrorAction SilentlyContinue)) {
    $need += $mv.Length * 2
}
$drive = (Get-Item $GameDir).PSDrive
$free = (Get-PSDrive $drive.Name).Free
if ($free -lt $need) {
    Fail ((L "ドライブ {0}: の空き容量が足りません - 必要 ~{1:N1} GB / 空き {2:N1} GB" `
             "驱动器 {0}: 可用空间不足 - 需要 ~{1:N1} GB / 可用 {2:N1} GB" `
             "Not enough free space on drive {0}: - need ~{1:N1} GB / free {2:N1} GB") -f
          $drive.Name, ($need / 1GB), ($free / 1GB))
}

# ---------- backup ----------

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$bakDir = Join-Path $GameDir "backup\hd_$stamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $bakDir 'DLL') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $bakDir 'movie') | Out-Null

# whatever AliceLogo*/movie files exist get backed up; the zh build
# carries AliceLogo2.* and an extra Rance7ED.alm instead
$protected = @('Rance7.ain', 'System40.ini')
if ($isZh) { $protected += @('Rance7GA.ald', 'Rance7GB.ald') }
else       { $protected += @('Rance7GM.ald', 'Rance7GA.ald') }
foreach ($f in $protected) {
    $src = Join-Path $GameDir $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $bakDir $f) }
}
$looseFiles = @()
$looseFiles += Get-ChildItem $GameDir -Filter 'AliceLogo*.alk' -File -ErrorAction SilentlyContinue
$looseFiles += Get-ChildItem (Join-Path $GameDir 'DLL') -Filter 'AliceLogo*.dll' -File -ErrorAction SilentlyContinue
$looseFiles += Get-ChildItem (Join-Path $GameDir 'movie') -Filter '*.alm' -File -ErrorAction SilentlyContinue
# en build: PlayMovie.dll gets the VMR-7 renderer disabled (see below)
if ($isEn) {
    $looseFiles += Get-Item (Join-Path $GameDir 'DLL\PlayMovie.dll') -ErrorAction SilentlyContinue
}
foreach ($f in $looseFiles) {
    $rel = $f.FullName.Substring($GameDir.Length).TrimStart('\', '/')
    $dst = Join-Path $bakDir $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $f.FullName $dst
}
Write-Host ((L "  バックアップ: " "  备份: " "  Backup: ") + $bakDir)

# ---------- compile patch engine ----------

Add-Type -TypeDefinition (Get-Content $csPath -Raw) `
         -ReferencedAssemblies 'System.Web.Extensions'
$log = { param($m) Write-Host "  $m" }

# repack progress bar (in-place); suppressed when output is redirected
$isRedir = [Console]::IsOutputRedirected
$repackProg = [Action[long,long]]{
    param($done, $total)
    if ($isRedir) { return }
    $frac = if ($total -gt 0) {
        [Math]::Min(1.0, $done / [double]$total)
    } else { 0.0 }
    $fill = [int]($frac * 28)
    # note: "-f" inside a method-call argument list would parse the
    # operand commas as argument separators - build the string first
    $line = "[{0}{1}] {2,6:N0}/{3:N0} MB {4,5:F1}%  " -f
        ('#' * $fill), ('-' * (28 - $fill)),
        ($done / 1MB), ($total / 1MB), ($frac * 100)
    [Console]::Write("`r" + $line)
}
$clearBar = {
    if (-not $isRedir) { [Console]::Write("`r" + (' ' * 76) + "`r") }
}

# ---------- HD asset generation (embedded python + onnxruntime/DML) ----------
#
# The installer ships the inference model + recipe manifest instead of
# 2.7 GB of derived images. Assets are upscaled from the user's own
# (just backed up, still pristine) game archives. Runs BEFORE any file
# is modified so a failure leaves the install untouched.

$pyExe   = Join-Path $Root 'runtime\python.exe'
$genDir  = Join-Path $GameDir "hd_gen_$stamp"
$cacheDir = Join-Path $GameDir 'hd_cache'
$expect  = @{}
if (-not (Test-Path $pyExe)) {
    Fail (L "インストーラーのファイルが不足しています: $pyExe" `
            "安装程序文件缺失: $pyExe" `
            "Missing installer file: $pyExe")
}

Write-Host ""
Write-Host (L "[1/5] HD素材の生成 - ゲーム内画像をAIで2倍化 ..." `
              "[1/5] 生成 HD 素材 - 用 AI 将游戏图像放大两倍 ..." `
              "[1/5] Generating HD assets - upscaling game images 2x with AI ...") `
    -ForegroundColor Cyan
Write-Host (L "      DirectML対応GPUなら数分。再インストール時は生成済み素材を再利用します" `
              "      使用 DirectML 兼容 GPU 约需几分钟。重装时会复用已生成素材" `
              "      A few minutes on a DirectML-capable GPU. Reinstalls reuse cached assets")
$pyArgs = @(
    (Join-Path $Root 'gen\gen_ring.py'),
    '--emit-qnt',
    '--asset-set', $assetSet,
    '--src-dir',   $bakDir,
    '--out',       $genDir,
    '--cache-dir', $cacheDir,
    '--model',     (Join-Path $Root 'gen\model.onnx'),
    '--manifest',  (Join-Path $Root 'gen\recipe_manifest.json')
)
& $pyExe $pyArgs
if ($LASTEXITCODE -ne 0) {
    Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
    Fail (L "アセット生成に失敗しました - ゲームファイルは無傷です（バックアップ: $bakDir）" `
            "素材生成失败 - 游戏文件未受影响（备份: $bakDir）" `
            "Asset generation failed - game files are untouched (backup: $bakDir)")
}
# sanity: count generated payloads vs expectation (manual assets excluded)
$recipes = Get-Content (Join-Path $Root 'gen\recipe_manifest.json') -Raw |
           ConvertFrom-Json
if ($isZh) {
    # zh generates every entry of the live archives (GA + GB); recipes
    # come from the vanilla/shared recipe map as in gen_ring
    $zhRecipes = @{}
    foreach ($p in $recipes.PSObject.Properties) {
        $parts = $p.Name -split '/'
        $rank = 9
        if ($parts[1] -eq 'vanilla') { $rank = 0 }
        elseif ($parts[1] -eq 'shared') { $rank = 1 }
        if (-not $zhRecipes.ContainsKey($parts[2]) -or
            $rank -lt $zhRecipes[$parts[2]].Rank) {
            $zhRecipes[$parts[2]] = @{ Rank = $rank; Recipe = $p.Value.recipe }
        }
    }
    $zhNames = [Collections.Generic.HashSet[string]]::new()
    foreach ($a in @('Rance7GA.ald', 'Rance7GB.ald')) {
        foreach ($n in [HdPatch]::ListAldNames((Join-Path $bakDir $a))) {
            [void]$zhNames.Add($n)
        }
    }
    $want = 0
    foreach ($n in $zhNames) {
        if (-not $zhRecipes.ContainsKey($n) -or
            $zhRecipes[$n].Recipe -ne 'manual') { $want++ }
    }
    $got = 0
    foreach ($arch in @('GA', 'GB')) {
        $d = Join-Path $genDir "$arch\zh"
        if (Test-Path $d) {
            $got += @(Get-ChildItem $d -File |
                      Where-Object { $_.Extension -ne '.json' }).Count
        }
    }
} else {
    $want = 0
    foreach ($p in $recipes.PSObject.Properties) {
        $parts = $p.Name -split '/'
        if (($parts[1] -eq 'shared' -or $parts[1] -eq $assetSet) -and
            $p.Value.recipe -ne 'manual') { $want++ }
    }
    $got = 0
    foreach ($s in @('shared', $assetSet)) {
        foreach ($arch in @('GM', 'GA')) {
            $d = Join-Path $genDir "$arch\$s"
            if (Test-Path $d) {
                $got += @(Get-ChildItem $d -File |
                          Where-Object { $_.Extension -ne '.json' }).Count
            }
        }
    }
}
if ($got -lt $want) {
    Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
    Fail (L ("アセット生成が途中で止まりました（$got/$want）- ゲームファイルは無傷です`n" +
             "再実行すると生成済み分はキャッシュから再利用されます") `
            ("素材生成中途停止（$got/$want）- 游戏文件未受影响`n" +
             "重新运行将复用已生成的缓存素材") `
            ("Asset generation stopped early ($got/$want) - game files are untouched`n" +
             "Re-running reuses the cached assets"))
}
Write-Host (L "  マニフェスト照合OK（$got / $want 件）" `
              "  清单校验通过（$got / $want 项）" `
              "  Manifest check OK ($got / $want items)") -ForegroundColor DarkGray

# AliceLogo*.alk only exists on builds with the logo plugin (jp:
# AliceLogo3.alk, zh: AliceLogo2.alk); vanilla Steam installs carry
# neither, so every step below is conditional on the backup.
foreach ($alkSrc in (Get-ChildItem $bakDir -Filter 'AliceLogo*.alk' -File -ErrorAction SilentlyContinue)) {
    $alkGen = Join-Path $genDir ('files\' + $alkSrc.Name)
    # decode each entry from the backed-up original, upscale 2x,
    # repack the ALK container (whole-output cache keyed on src bytes)
    & $pyExe (Join-Path $Root 'gen\gen_alk.py') `
        --src $alkSrc.FullName --dst $alkGen --cache-dir $cacheDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $alkGen)) {
        Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
        Fail (L "$($alkSrc.Name) の生成に失敗しました - ゲームファイルは無傷です（バックアップ: $bakDir）" `
                "$($alkSrc.Name) 生成失败 - 游戏文件未受影响（备份: $bakDir）" `
                "$($alkSrc.Name) generation failed - game files are untouched (backup: $bakDir)")
    }
}

# DLL\AliceLogo*.dll: the shipped binary is just the user's original
# plugin with two 800x600 -> 1600x1200 constant pairs patched (16 bytes
# total). Patch the backed-up copy instead of shipping the binary.
$dllOffsets = @{
    'AliceLogo3.dll' = @(
        @(0x1312,  0x0320, 0x0640), @(0x131c,  0x0258, 0x04b0),
        @(0x20d2c, 0x0320, 0x0640), @(0x20d30, 0x0258, 0x04b0))
    'AliceLogo2.dll' = @(
        @(0x11b8,  0x0320, 0x0640), @(0x11c2,  0x0258, 0x04b0),
        @(0x1cbd4, 0x0320, 0x0640), @(0x1cbd8, 0x0258, 0x04b0))
}
foreach ($dllSrc in (Get-ChildItem (Join-Path $bakDir 'DLL') -Filter 'AliceLogo*.dll' -File -ErrorAction SilentlyContinue)) {
    $dllOut = Join-Path $genDir ('files\DLL\' + $dllSrc.Name)
    $patch = $dllOffsets[$dllSrc.Name]
    if (-not $patch) {
        Write-Host (L "  $($dllSrc.Name) のパッチ位置が不明のためスキップ" `
                      "  $($dllSrc.Name) 补丁位置未知，跳过" `
                      "  Skipping $($dllSrc.Name) - patch offsets unknown") `
            -ForegroundColor Yellow
        continue
    }
    $dllBytes = [IO.File]::ReadAllBytes($dllSrc.FullName)
    $dllChanged = 0
    foreach ($p in $patch) {
        $o = $p[0]
        $cur = [BitConverter]::ToInt32($dllBytes, $o)
        if ($cur -eq $p[1]) {
            $v = $p[2]
            $dllBytes[$o]   = $v -band 0xff
            $dllBytes[$o+1] = ($v -shr 8)  -band 0xff
            $dllBytes[$o+2] = ($v -shr 16) -band 0xff
            $dllBytes[$o+3] = ($v -shr 24) -band 0xff
            $dllChanged++
        } elseif ($cur -ne $p[2]) {
            Write-Host ((L ("  ! $($dllSrc.Name) が想定と異なります（0x{0:x}）- " +
                            "その箇所はパッチしません（ロゴは低解像度のままの可能性）") `
                           ("  ! $($dllSrc.Name) 与预期不符（0x{0:x}）- " +
                            "该处不修补（Logo 可能保持低分辨率）") `
                           ("  ! $($dllSrc.Name) differs from expected (0x{0:x}) - " +
                            "leaving it unpatched (logo may stay low-res)")) -f $o) `
                -ForegroundColor Yellow
        }
    }
    New-Item -Force -ItemType Directory (Split-Path $dllOut) | Out-Null
    [IO.File]::WriteAllBytes($dllOut, $dllBytes)
    Write-Host (L "  $($dllSrc.Name) に $dllChanged 箇所パッチ（800x600 -> 1600x1200）" `
                  "  $($dllSrc.Name) 已修补 $dllChanged 处（800x600 -> 1600x1200）" `
                  "  Patched $dllChanged spots in $($dllSrc.Name) (800x600 -> 1600x1200)")
}

# en build only: PlayMovie.dll (Kagura's rebuilt player) creates the
# first available renderer in VMR-7 -> VMR-9 -> EVR order. VMR-7's
# windowless path cannot display MPEG-1 wider than ~1184 px (74 MBs):
# audio plays but the video stays black. Zeroing the VMR-7 CLSID makes
# its CoCreateInstance fail so the code falls through to VMR-9/EVR,
# which render 1280x960 fine (verified). If the pattern is absent the
# DLL is left untouched and movies fall back to a capped width below.
$enMoviePatched = $false
$pmBak = Join-Path $bakDir 'DLL\PlayMovie.dll'
if ($isEn -and (Test-Path $pmBak)) {
    $pmBytes = [IO.File]::ReadAllBytes($pmBak)
    # raw bytes of CLSID_VideoMixingRenderer {B87BEB7B-8D29-423F-AE4D-6582C10175AC}
    $vmr7 = [byte[]](0x7b,0xeb,0x7b,0xb8,0x29,0x8d,0x3f,0x42,
                     0xae,0x4d,0x65,0x82,0xc1,0x01,0x75,0xac)
    $hits = @()
    for ($i = 0; $i -le $pmBytes.Length - 16; $i++) {
        $m = $true
        for ($j = 0; $j -lt 16; $j++) {
            if ($pmBytes[$i + $j] -ne $vmr7[$j]) { $m = $false; break }
        }
        if ($m) { $hits += $i }
    }
    if ($hits.Count -eq 1) {
        for ($j = 0; $j -lt 16; $j++) { $pmBytes[$hits[0] + $j] = 0 }
        $pmOut = Join-Path $genDir 'files\DLL\PlayMovie.dll'
        New-Item -Force -ItemType Directory (Split-Path $pmOut) | Out-Null
        [IO.File]::WriteAllBytes($pmOut, $pmBytes)
        $enMoviePatched = $true
        Write-Host (L "  PlayMovie.dll にパッチ（VMR-7無効化 -> VMR-9/EVRでHDムービー再生）" `
                      "  已修补 PlayMovie.dll（禁用 VMR-7 -> 经 VMR-9/EVR 播放 HD 影片）" `
                      "  Patched PlayMovie.dll (VMR-7 disabled -> HD movies play via VMR-9/EVR)")
    } else {
        Write-Host (L "  ! PlayMovie.dll のパターンが想定と異なります（$($hits.Count)箇所）- ムービーは1152px幅に制限します" `
                      "  ! PlayMovie.dll 的模式与预期不符（$($hits.Count)处）- 影片将限制为1152px宽" `
                      "  ! PlayMovie.dll pattern unexpected ($($hits.Count) matches) - movies capped at 1152px wide") `
            -ForegroundColor Yellow
    }
}

# movie/*.alm: regenerate the OP/ED at 1280x960 from the backed-up
# originals (MPEG-1 video + MP2 audio program stream, same profile as
# the source so the stock DirectShow path plays it). Optional: needs
# the bundled ffmpeg; a failure leaves the original SD movies in place.
$ffmpegExe = Join-Path $Root 'bin\ffmpeg.exe'
$movSrcDir = Join-Path $bakDir 'movie'
$movOutDir = Join-Path $genDir 'files\movie'
if ((Test-Path $movSrcDir) -and
    @(Get-ChildItem $movSrcDir -Filter '*.alm' -ErrorAction SilentlyContinue).Count -gt 0) {
    if (Test-Path $ffmpegExe) {
        Write-Host (L "  OP/EDムービーをHD化しています（数分かかります） ..." `
                      "  正在高清化 OP/ED 影片（需要几分钟） ..." `
                      "  Upscaling OP/ED movies to HD (takes a few minutes) ...")
        # The Kagura/English build's rebuilt PlayMovie.dll fails to render
        # MPEG-1 wider than ~1184 px (black video, audio ok). When the
        # VMR-7-disable patch above could not be applied, cap the movie
        # width at 1152 px as a safe fallback.
        $movArgs = @((Join-Path $Root 'gen\gen_movie.py'),
            '--src-dir', $bakDir, '--dst-dir', $movOutDir,
            '--ffmpeg', $ffmpegExe, '--cache-dir', $cacheDir)
        if ($isEn -and -not $enMoviePatched) { $movArgs += @('--max-width', '1152') }
        & $pyExe @movArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host (L "  ! ムービー生成に失敗しました - 元のムービーのまま続行します" `
                          "  ! 影片生成失败 - 继续使用原影片" `
                          "  ! Movie generation failed - continuing with the original movies") `
                -ForegroundColor Yellow
            Remove-Item -Recurse -Force $movOutDir -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host (L "  bin\ffmpeg.exe が無いためムービーHD化をスキップ" `
                      "  缺少 bin\ffmpeg.exe，跳过影片高清化" `
                      "  bin\ffmpeg.exe missing - skipping movie upscaling") `
            -ForegroundColor Yellow
    }
} else {
    Write-Host (L "  movie/*.alm は存在しないためスキップ" "  没有 movie/*.alm，跳过" `
                  "  No movie/*.alm found - skipping")
}

# ---------- AIN patch ----------

# From here on the game's own files get replaced; mark in-progress so an
# interrupted run cannot be mistaken for a clean state on re-run. The
# original ain hash is recorded so the (hash-based) build/language
# detection still works while the patched file is in place.
[IO.File]::WriteAllText($statePath, "in-progress; backup=$bakDir; ain=$ainHash")

Write-Host ""
Write-Host (L "[2/5] Rance7.ain - パッチを適用します ..." `
              "[2/5] Rance7.ain - 应用补丁 ..." `
              "[2/5] Rance7.ain - applying patch ...") -ForegroundColor Cyan
$tmpAin = Join-Path $GameDir 'Rance7.ain.hdtmp'
try {
    $r = [HdPatch]::ApplyAinPatch($ainPath, $tmpAin, $sites, $aliceExe,
                                  [Action[string]]$log)
} catch {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail (L ("AINパッチに失敗しました: $($_.Exception.Message)`n元のファイルは無傷です（バックアップ: $bakDir）") `
            ("AIN 补丁失败: $($_.Exception.Message)`n原文件未受影响（备份: $bakDir）") `
            ("AIN patch failed: $($_.Exception.Message)`nOriginal file untouched (backup: $bakDir)"))
}
Write-Host ((L "  パッチ箇所: {0} 件を適用（適用済 {1} / 代替適用 {2} / スキップ {3} / 対象外関数 {4}）" `
               "  补丁位置: 已应用 {0} 处（已应用 {1} / 替代应用 {2} / 跳过 {3} / 无此函数 {4}）" `
               "  Patch sites: {0} applied (already {1} / fallback {2} / skipped {3} / func absent {4})") -f
            $r.Ok, $r.AlreadyPatched, $r.Relaxed, $r.Ambiguous, $r.MissingFunc)
if ($r.Writes -eq 0 -and $r.AlreadyPatched -eq 0) {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail (L ("パッチ対象が見つかりませんでした - このAINには適用できません。`n詳細:`n  $($r.Problems -join "`n  ")") `
            ("未找到补丁目标 - 无法应用于此 AIN。`n详情:`n  $($r.Problems -join "`n  ")") `
            ("No patch sites found - cannot apply to this AIN.`nDetails:`n  $($r.Problems -join "`n  ")"))
}
if ($r.Ambiguous -gt 0 -or $r.MissingFunc -gt 0) {
    Write-Host (L "  ※スキップは主にゲームバージョン間の差異によるもので、動作上の問題ではありません:" `
                  "  ※跳过的部分主要是游戏版本间的差异，并非故障:" `
                  "  Skipped sites are mostly build differences between game versions, not a malfunction:") -ForegroundColor DarkGray
    $r.Problems | Select-Object -First 8 | ForEach-Object { Write-Host "    ! $_" }
}
# sanity check the produced AIN parses
$verifyJam = Join-Path $env:TEMP ("hd_verify_" + [guid]::NewGuid().ToString('N') + '.jam')
& $aliceExe ain dump -C -o $verifyJam $tmpAin 2>$null | Out-Null
$ok = ($LASTEXITCODE -eq 0)
Remove-Item $verifyJam -ErrorAction SilentlyContinue
if (-not $ok) {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail (L "パッチ後のAINが検証を通りませんでした - 中止します（元のファイルは無傷です）" `
            "补丁后的 AIN 未通过验证 - 中止（原文件未受影响）" `
            "Patched AIN failed verification - aborting (original untouched)")
}
Move-Item -Force $tmpAin $ainPath
Write-Host (L "  Rance7.ain -> HD化完了" "  Rance7.ain -> HD 化完成" `
              "  Rance7.ain -> HD patch applied")

# ---------- asset payload ----------

$mj = Get-Content $manifest -Raw | ConvertFrom-Json

function Repack-Archive([string]$aldPath, [string]$arcName, [string]$dir, [int]$disk,
                        [Collections.Generic.Dictionary[int,int[]]]$extraRows = $null,
                        [bool]$noAppend = $false, [bool]$genOnly = $false) {
    # shipped payloads (manual exceptions) first; generated payloads last
    # (generated wins on name collision, though there should be none).
    # zh skips shipped payloads entirely: the jp/vanilla manual payloads
    # carry jp-specific content that must not enter the zh archives.
    $dirs = @()
    if (-not $genOnly) {
        foreach ($s in @('shared', $assetSet)) {
            $src = Join-Path $dataDir ("$dir\" + $s)
            if (Test-Path $src) { $dirs += $src }
        }
    }
    foreach ($s in @('shared', $assetSet)) {
        $src = Join-Path $genDir ("$dir\" + $s)
        if (Test-Path $src) { $dirs += $src }
    }
    if ($dirs.Count -eq 0) {
        Fail (L "$arcName 用の素材が見つかりません" "找不到用于 $arcName 的素材" `
                "No assets found for $arcName")
    }
    Write-Host ((L "  {0}: 格納する素材 {1} ファイル" "  {0}: 打包素材 {1} 个文件" `
                   "  {0}: storing {1} asset files") -f $arcName,
                (($dirs | ForEach-Object { (Get-ChildItem $_).Count }) |
                 Measure-Object -Sum).Sum)
    $tmpAld = "$aldPath.hdtmp"
    try {
        $res = [HdPatch]::RepackAld($aldPath, $tmpAld, [string[]]$dirs,
                                    $disk, [Action[string]]$log,
                                    $extraRows, $repackProg, $noAppend)
    } catch {
        Remove-Item $tmpAld -ErrorAction SilentlyContinue
        Fail (L "$arcName の再梱包に失敗: $($_.Exception.Message) - 元のアーカイブは無傷です" `
                "$arcName 重新打包失败: $($_.Exception.Message) - 原存档未受影响" `
                "Failed to repack ${arcName}: $($_.Exception.Message) - original archive untouched")
    }
    & $clearBar
    Move-Item -Force $tmpAld $aldPath
    Write-Host ((L "  {0}: 計{1}件（上書き {2} / 追加 {3}）" "  {0}: 共{1}项（覆盖 {2} / 新增 {3}）" `
                   "  {0}: {1} total (overwrote {2} / added {3})") -f
                $arcName, $res[0], $res[1], $res[2])
}

$AldSeekLimit = 0x80000000L
$AldTarget    = 0x7F000000L   # stop ~33 MB under the hard limit

if ($isZh) {
    # zh build: GA is the live CG archive, GB carries the cg045xx set
    # and GM is dormant (untouched). HD payloads can push GA past the
    # signed 32-bit seek ceiling; overflow payloads then move into GB
    # (same live archive family, ~2 GB headroom) and GA's link table -
    # the authoritative one in this build - gets redirect rows pointing
    # at the appended GB entries, mirroring the jp GM->GA mechanism.
    $gaOrigSz = [HdPatch]::AldEntrySizes((Join-Path $bakDir 'Rance7GA.ald'))
    $gbOrigNm = [HdPatch]::ListAldNames((Join-Path $bakDir 'Rance7GB.ald'))
    $gbOrigSet = [Collections.Generic.HashSet[string]]::new(
        [string[]]$gbOrigNm)

    # projected GA size ~= originals not overridden + staged payloads
    # + ~176 B per entry of header/alignment padding
    $gaPl = @{}
    $gaStage = Join-Path $genDir 'GA\zh'
    if (Test-Path $gaStage) {
        foreach ($f in (Get-ChildItem $gaStage -File |
                       Where-Object { $_.Extension -ne '.json' })) {
            $gaPl[$f.Name] = $f.Length
        }
    }
    $gaProj = 0L
    foreach ($kv in $gaOrigSz.GetEnumerator()) {
        if (-not $gaPl.ContainsKey($kv.Key)) { $gaProj += $kv.Value }
    }
    foreach ($f in ($gaPl.Keys)) { $gaProj += $gaPl[$f] }
    $gaProj += 176L * ($gaOrigSz.Count + 64)
    Write-Host ""
    Write-Host ((L "  アーカイブ容量確認: Rance7GA.ald の完成予想は {0:N0} MB" `
                   "  存档容量确认: Rance7GA.ald 预计大小 {0:N0} MB" `
                   "  Archive size check: Rance7GA.ald projected at {0:N0} MB") -f ($gaProj / 1MB))

    $zhRows = $null
    if ($gaProj -gt $AldTarget) {
        # biggest payloads first; moved names append to GB in the
        # ordinal order RepackAld uses, so their GB indexes (and the
        # redirect rows pointing at them) are known up front
        $moved = [Collections.Generic.List[string]]::new()
        $movedBytes = 0L
        $names = $gaPl.Keys | Sort-Object { $gaPl[$_] } -Descending
        foreach ($nm in $names) {
            if ($gaProj -le $AldTarget) { break }
            if ($gbOrigSet.Contains($nm)) { continue }  # name already in
                # GB: moving it there would never be seen as an addition
            $dstDir = Join-Path $genDir 'GB\zh'
            New-Item -Force -ItemType Directory $dstDir | Out-Null
            Move-Item -Force (Join-Path $gaStage $nm) `
                (Join-Path $dstDir $nm)
            $moved.Add($nm)
            $orig = 0L
            if ($gaOrigSz.ContainsKey($nm)) { $orig = $gaOrigSz[$nm] }
            $gaProj -= ($gaPl[$nm] - $orig)
            $movedBytes += $gaPl[$nm]
        }
        Write-Host ((L "  サイズ調整: 大きい素材 {0} 件をGAからGBへ移動（{1:N0} MB）→ GAは約{2:N0} MBに" `
                       "  容量调整: 将 {0} 个大型素材从GA移至GB（{1:N0} MB）→ GA约{2:N0} MB" `
                       "  Rebalancing: moving {0} large assets GA->GB ({1:N0} MB) -> GA ~{2:N0} MB") -f
                    $moved.Count, ($movedBytes / 1MB), ($gaProj / 1MB))
        if ($gaProj -gt $AldTarget) {
            Write-Host (L ("  ! 警告: それでもGAが安全圏を超える見込みです - " +
                           "2GB以降の素材が表示されない可能性があります") `
                          ("  ! 警告: GA 仍预计超过安全范围 - " +
                           "2GB 之后的素材可能无法显示") `
                          ("  ! Warning: GA still projected over the safe limit - " +
                           "assets past 2GB may not display")) `
                -ForegroundColor Yellow
        }
        if ($moved.Count -gt 0) {
            $sorted = $moved.ToArray()
            [Array]::Sort($sorted, [StringComparer]::Ordinal)
            $zhRows = New-Object 'Collections.Generic.Dictionary[int,int[]]'
            for ($i = 0; $i -lt $sorted.Count; $i++) {
                $digits = [int]([regex]::Match(
                    [IO.Path]::GetFileNameWithoutExtension($sorted[$i]),
                    '\d+').Value)
                # fileNumber -> {disk 1 (GB), appended GB files index};
                # parenthesize: @(a, x + i) would parse as @(a, x) + i
                $zhRows[$digits - 1] = [int[]]@(1, ($gbOrigNm.Count + $i))
            }
            Write-Host ((L "  GBへのリンク振替: {0} 行" "  向GB的链接转移: {0} 行" `
                           "  Link rows redirected to GB: {0}") -f $zhRows.Count)
        }
    }

    # GB first: its appended entries land at the indexes computed above
    Write-Host ""
    Write-Host (L "[3/5] Rance7GB.ald - HD素材を格納します ..." `
                  "[3/5] Rance7GB.ald - 写入 HD 素材 ..." `
                  "[3/5] Rance7GB.ald - storing HD assets ...") -ForegroundColor Cyan
    Repack-Archive $gbPath 'Rance7GB.ald' 'GB' $mj.archives.'Rance7GB.ald'.disk $null $false $true
    Write-Host ""
    Write-Host (L "[4/5] Rance7GA.ald - HD素材を格納します（約1〜2GB） ..." `
                  "[4/5] Rance7GA.ald - 写入 HD 素材（约1〜2GB） ..." `
                  "[4/5] Rance7GA.ald - storing HD assets (~1-2 GB) ...") -ForegroundColor Cyan
    Repack-Archive $gaPath 'Rance7GA.ald' 'GA' $mj.archives.'Rance7GA.ald'.disk $zhRows $true $true
} else {

# ---------- archive size rebalance ----------
# The engine seeks into .ald volumes via a signed 32-bit byte offset, so
# entries starting at/above 0x80000000 are unreachable (they silently
# render nothing). Generated payloads can push Rance7GM.ald past the
# limit; when the projection exceeds the threshold below, the biggest
# payloads are moved into the GA payload dirs before repacking. GA has
# plenty of headroom and the link-table redirect further down is computed
# from whatever the GA dirs contain, so no other step needs to know.
$gmOrigSz = [HdPatch]::AldEntrySizes((Join-Path $bakDir 'Rance7GM.ald'))
$gaOrigNm = [Collections.Generic.HashSet[string]]::new(
    [string[]]([HdPatch]::ListAldNames((Join-Path $bakDir 'Rance7GA.ald'))))

$gmPl = @{}   # name -> total payload bytes staged for GM
foreach ($s in @('shared', $assetSet)) {
    foreach ($base in @($genDir, $dataDir)) {
        $d = Join-Path $base "GM\$s"
        if (-not (Test-Path $d)) { continue }
        foreach ($f in (Get-ChildItem $d -File |
                       Where-Object { $_.Extension -ne '.json' })) {
            if (-not $gmPl.ContainsKey($f.Name)) { $gmPl[$f.Name] = 0L }
            $gmPl[$f.Name] += $f.Length   # shared+variant override same slot
        }
    }
}
# projected GM size ~= originals not overridden + staged payloads
# + ~176 B per entry of entry header/alignment padding
$gmProj = 0L
foreach ($kv in $gmOrigSz.GetEnumerator()) {
    if (-not $gmPl.ContainsKey($kv.Key)) { $gmProj += $kv.Value }
}
foreach ($f in ($gmPl.Keys)) { $gmProj += $gmPl[$f] }
$gmProj += 176L * ($gmOrigSz.Count + 64)
Write-Host ""
Write-Host ((L "  アーカイブ容量確認: Rance7GM.ald の完成予想は {0:N0} MB" `
               "  存档容量確認: Rance7GM.ald 预计大小 {0:N0} MB" `
               "  Archive size check: Rance7GM.ald projected at {0:N0} MB") -f ($gmProj / 1MB))

if ($gmProj -gt $AldTarget) {
    # biggest payloads first; move every staged copy of the name
    # (shared/variant) so no GM dir retains a payload for it
    # name -> staged files (a name may sit in both shared and variant dirs)
    $byName = @{}
    foreach ($s in @('shared', $assetSet)) {
        foreach ($base in @($genDir, $dataDir)) {
            $d = Join-Path $base "GM\$s"
            if (-not (Test-Path $d)) { continue }
            foreach ($f in (Get-ChildItem $d -File |
                           Where-Object { $_.Extension -ne '.json' })) {
                if (-not $byName.ContainsKey($f.Name)) {
                    $byName[$f.Name] = @{
                        Size = 0L; Files = [Collections.Generic.List[object]]::new() }
                }
                $byName[$f.Name].Size += $f.Length
                $byName[$f.Name].Files.Add(
                    @{ File = $f; Var = $s; Base = $base })
            }
        }
    }
    # biggest payloads first; move every staged copy of the name
    # (shared/variant) so no GM dir retains a payload for it
    $moved = 0
    $movedBytes = 0L
    $names = $byName.Keys | Sort-Object { $byName[$_].Size } -Descending
    foreach ($nm in $names) {
        if ($gmProj -le $AldTarget) { break }
        if ($gaOrigNm.Contains($nm)) { continue }  # GA override would
            # keep the GM link row -> GM slot must stay authoritative
        foreach ($o in $byName[$nm].Files) {
            $dstDir = Join-Path $o.Base ("GA\" + $o.Var)
            New-Item -Force -ItemType Directory $dstDir | Out-Null
            Move-Item -Force $o.File.FullName (Join-Path $dstDir $o.File.Name)
        }
        $orig = 0L
        if ($gmOrigSz.ContainsKey($nm)) { $orig = $gmOrigSz[$nm] }
        $gmProj -= ($byName[$nm].Size - $orig)
        $moved++
        $movedBytes += $byName[$nm].Size
    }
    Write-Host ((L "  サイズ調整: 大きい素材 {0} 件をGMからGAへ移動（{1:N0} MB）→ GMは約{2:N0} MBに" `
                   "  容量调整: 将 {0} 个大型素材从GM移至GA（{1:N0} MB）→ GM约{2:N0} MB" `
                   "  Rebalancing: moving {0} large assets GM->GA ({1:N0} MB) -> GM ~{2:N0} MB") -f
                $moved, ($movedBytes / 1MB), ($gmProj / 1MB))
    if ($gmProj -gt $AldTarget) {
        Write-Host (L ("  ! 警告: それでもGMが安全圏を超える見込みです - " +
                       "2GB以降の素材が表示されない可能性があります") `
                      ("  ! 警告: GM 仍预计超过安全范围 - " +
                       "2GB 之后的素材可能无法显示") `
                      ("  ! Warning: GM still projected over the safe limit - " +
                       "assets past 2GB may not display")) `
            -ForegroundColor Yellow
    }
}

# GA must be repacked first: 694 CG entries were relocated GM -> GA in the
# HD set, so every archive's global link table must point the moved file
# numbers at their new GA positions.
Write-Host ""
Write-Host (L "[3/5] Rance7GA.ald - HD素材を格納します ..." `
              "[3/5] Rance7GA.ald - 写入 HD 素材 ..." `
              "[3/5] Rance7GA.ald - storing HD assets ...") -ForegroundColor Cyan
Repack-Archive $gaPath 'Rance7GA.ald' 'GA' $mj.archives.'Rance7GA.ald'.disk

# Compute the moved-file link rows: names now in GA payloads that the
# user's GA did not contain (they resolve to the appended GA entries).
$gaOrig = [HdPatch]::ListAldNames((Join-Path $bakDir 'Rance7GA.ald'))
$gaOrigSet = [Collections.Generic.HashSet[string]]::new([string[]]$gaOrig)
$gaPayload = @()
foreach ($s in @('shared', $assetSet)) {
    foreach ($base in @($dataDir, $genDir)) {
        $p = Join-Path $base "GA\$s"
        if (Test-Path $p) {
            $gaPayload += (Get-ChildItem $p -File |
                Where-Object { $_.Extension -ne '.json' }).Name
        }
    }
}
$gaPayload = $gaPayload | Select-Object -Unique
$movedNames = $gaPayload | Where-Object { -not $gaOrigSet.Contains($_) } |
              Sort-Object
$movedRows = New-Object 'Collections.Generic.Dictionary[int,int[]]'
for ($i = 0; $i -lt $movedNames.Count; $i++) {
    $digits = [int]([regex]::Match([IO.Path]::GetFileNameWithoutExtension($movedNames[$i]), '\d+').Value)
    $movedRows[$digits - 1] = [int[]]@(0, ($gaOrig.Count + $i))
}
Write-Host ((L "  GAへのリンク振替: {0} 行" "  向GA的链接转移: {0} 行" `
               "  Link rows redirected to GA: {0}") -f $movedRows.Count)

Write-Host ""
Write-Host (L "[4/5] Rance7GM.ald - HD素材を格納します（約1〜2GB） ..." `
              "[4/5] Rance7GM.ald - 写入 HD 素材（约1〜2GB） ..." `
              "[4/5] Rance7GM.ald - storing HD assets (~1-2 GB) ...") -ForegroundColor Cyan
Repack-Archive $gmPath 'Rance7GM.ald' 'GM' $mj.archives.'Rance7GM.ald'.disk $movedRows

# hard ceiling check: the engine's signed 32-bit seek cannot reach
# entries at/above 0x80000000, so an oversized volume means invisible
# assets - warn loudly rather than leave a silently broken install
foreach ($ald in @($gaPath, $gmPath)) {
    $sz = (Get-Item $ald).Length
    if ($sz -ge $AldSeekLimit) {
        Write-Host ((L ("  ! 警告: {0} が {1:N0} バイト - エンジンの2GB読み取り" +
                        "上限を超えています。末尾の素材が表示されません。" +
                        " Uninstall.cmd で戻してからご報告ください。") `
                       ("  ! 警告: {0} 已达 {1:N0} 字节 - 超过引擎的2GB读取" +
                        "上限，末尾素材将无法显示。" +
                        " 请用 Uninstall.cmd 还原并报告。") `
                       ("  ! Warning: {0} is {1:N0} bytes - over the engine's" +
                        " 2GB seek limit. Trailing assets will not display." +
                        " Revert with Uninstall.cmd and report this.")) -f
                    (Split-Path $ald -Leaf), $sz) -ForegroundColor Red
    }
}
} # end of jp/en repack branch

if ($isZh) {
    # same signed 32-bit seek ceiling for the zh repacked pair
    foreach ($ald in @($gaPath, $gbPath)) {
        $sz = (Get-Item $ald).Length
        if ($sz -ge $AldSeekLimit) {
            Write-Host ((L ("  ! 警告: {0} が {1:N0} バイト - エンジンの2GB読み取り" +
                            "上限を超えています。末尾の素材が表示されません。" +
                            " Uninstall.cmd で戻してからご報告ください。") `
                           ("  ! 警告: {0} 已达 {1:N0} 字节 - 超过引擎的2GB读取" +
                            "上限，末尾素材将无法显示。" +
                            " 请用 Uninstall.cmd 还原并报告。") `
                           ("  ! Warning: {0} is {1:N0} bytes - over the engine's" +
                            " 2GB seek limit. Trailing assets will not display." +
                            " Revert with Uninstall.cmd and report this.")) -f
                        (Split-Path $ald -Leaf), $sz) -ForegroundColor Red
        }
    }
}

# NOTE: Rance7BA.ald / Rance7WA.ald link tables must stay byte-identical.
# Their rows map BGM/SE file numbers to entries inside the SAME archive -
# writing CG redirect rows here collides with sound file numbers and
# breaks audio (verified: wrong hover SE + Music_Prepare failure).

foreach ($f in $mj.files) {
    # generated files (e.g. AliceLogo3.alk) win over any shipped copy
    $src = Join-Path $genDir ($f.src -replace '/', '\')
    if (-not (Test-Path $src)) {
        $src = Join-Path $dataDir ($f.src -replace '/', '\')
    }
    if (-not (Test-Path $src)) {
        # payload not generated AND the file is not part of this
        # install (e.g. AliceLogo3.* on vanilla) - nothing to do
        if (-not (Test-Path (Join-Path $GameDir $f.dst))) {
            Write-Host (L "  $($f.dst) -> スキップ（この環境には存在しないファイル）" `
                          "  $($f.dst) -> 跳过（此环境不存在的文件）" `
                          "  $($f.dst) -> skipped (not present in this install)")
            continue
        }
        Fail (L "素材が見つかりません: $($f.src)" "找不到素材: $($f.src)" `
                "Asset not found: $($f.src)")
    }
    $dst = Join-Path $GameDir $f.dst
    Copy-Item -Force $src $dst
    Write-Host (L "  $($f.dst) -> 差し替え完了" "  $($f.dst) -> 替换完成" `
                  "  $($f.dst) -> replaced")
}

# generated PlayMovie.dll (en VMR-7 disable) lands next to the original
$pmGen = Join-Path $genDir 'files\DLL\PlayMovie.dll'
if (Test-Path $pmGen) {
    Copy-Item -Force $pmGen (Join-Path $GameDir 'DLL\PlayMovie.dll')
    Write-Host (L "  DLL\PlayMovie.dll -> パッチ適用完了" "  DLL\PlayMovie.dll -> 补丁应用完成" `
                  "  DLL\PlayMovie.dll -> patch applied")
}

# generated movies land next to the originals (absent when generation
# was skipped - the originals then stay untouched)
$movGenDir = Join-Path $genDir 'files\movie'
if (Test-Path $movGenDir) {
    foreach ($f in (Get-ChildItem $movGenDir -File -Filter '*.alm')) {
        Copy-Item -Force $f.FullName (Join-Path $GameDir ('movie\' + $f.Name))
        Write-Host (L "  movie\$($f.Name) -> HD化完了" "  movie\$($f.Name) -> HD 化完成" `
                      "  movie\$($f.Name) -> HD done")
    }
}

# ---------- System40.ini ----------

Write-Host ""
Write-Host (L "[5/5] System40.ini - 表示を1600x1200に設定します ..." `
              "[5/5] System40.ini - 设置分辨率为1600x1200 ..." `
              "[5/5] System40.ini - setting display to 1600x1200 ...") -ForegroundColor Cyan
# read/write as raw bytes via cp932 so no encoding conversion can corrupt
# unrelated settings
$enc932 = [Text.Encoding]::GetEncoding(932)
$ini = $enc932.GetString([IO.File]::ReadAllBytes($iniPath))
$ini = $ini -replace '(?m)^(ViewWidth)\s*=\s*\d+',  "`$1`t= 1600"
$ini = $ini -replace '(?m)^(ViewHeight)\s*=\s*\d+', "`$1`t= 1200"
[IO.File]::WriteAllBytes($iniPath, $enc932.GetBytes($ini))

# generated payloads are baked into the archives now; drop the ~2-3 GB
# intermediate directory
Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
[IO.File]::WriteAllText($statePath, "installed; backup=$bakDir; ain=$ainHash")

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host (L "   HDパッチの適用が完了しました。" "   HD 补丁安装完成。" `
              "   HD patch installed.") -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host ((L "  バックアップ: " "  备份: " "  Backup: ") + $bakDir)
Write-Host (L "  元に戻したいときは Uninstall.cmd を実行してください。" `
              "  如需还原请运行 Uninstall.cmd。" `
              "  To revert, run Uninstall.cmd.")
if ($Elevated) {
    Read-Host (L "Enterキーを押して閉じてください" "按 Enter 键关闭" `
                  "Press Enter to close") | Out-Null
}
