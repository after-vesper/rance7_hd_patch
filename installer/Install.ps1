#requires -Version 5.1
<#
.SYNOPSIS
    Sengoku Rance HD patch installer - plain Windows, no extra tools needed.
.DESCRIPTION
    Applies the 1600x1200 HD patch to a Sengoku Rance (Steam) install:
      * Rance7.ain   - anchor-based coordinate/layout doubling
      * Rance7GM.ald / Rance7GA.ald - HD asset payload repack
      * AliceLogo3.alk / DLL\AliceLogo3.dll - HD logo animation
      * System40.ini - ViewWidth/ViewHeight -> 1600x1200
    Compatible with vanilla, JP-patched and unofficial-patch installs,
    in any application order. Creates a timestamped backup
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

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "   戦国ランス HDパッチ インストーラー" -ForegroundColor Cyan
Write-Host "   （アリスソフト非公式のファン制作パッチです）" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "  エラー: $msg" -ForegroundColor Red
    # drop generation intermediates if the directory was created
    if ($genDir -and (Test-Path $genDir)) {
        Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
    }
    if ($Elevated) { Read-Host "Enterキーを押して閉じてください" | Out-Null }
    exit 1
}

function Sha256([string]$p) { (Get-FileHash -Algorithm SHA256 $p).Hash }

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
    if (-not (Test-Path $req)) { Fail "インストーラーのファイルが不足しています: $req" }
}

# ---------- locate the game ----------

if (-not $GameDir) {
    $GameDir = Find-SteamGame '3867170'
    if ($GameDir) {
        Write-Host "  Steamインストール先を検出: $GameDir" -ForegroundColor Green
        Write-Host ""
    } else {
        Write-Host "  Steamからの自動検出に失敗しました。" -ForegroundColor Yellow
        $GameDir = Read-Host "  戦国ランスのインストールフォルダを入力してください（Rance7.exe がある場所）"
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
              '-GameDir', "`"$GameDir`"", '-Elevated')
    Start-Process powershell -Verb RunAs -ArgumentList $args
    exit 0
}
$ainPath = Join-Path $GameDir 'Rance7.ain'
$iniPath = Join-Path $GameDir 'System40.ini'
if (-not (Test-Path $ainPath)) { Fail "Rance7.ain が見つかりません: '$GameDir'" }
if (-not (Test-Path $iniPath)) { Fail "System40.ini が見つかりません: '$GameDir'" }

if (Get-Process -Name Rance7 -ErrorAction SilentlyContinue) {
    Fail "Rance7.exe が起動中です。先にゲームを閉じてください。"
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
        Fail ("前回のインストールがファイル置き換えの途中で中断しています。`n" +
              "先に Uninstall.cmd でバックアップから復旧してから、やり直してください。")
    }
    # a Steam reinstall leaves hd_patch.state behind while restoring
    # pristine files - detect it via System40.ini before refusing.
    # ('in-progress' above is handled first: the ini is written last,
    # so an interrupted run would look pristine here yet still need a
    # restore to avoid double-upscaling already-HD archives)
    $iniNow = [Text.Encoding]::GetEncoding(932).GetString(
        [IO.File]::ReadAllBytes($iniPath))
    if ($iniNow -notmatch '(?m)^ViewWidth\s*=\s*1600') {
        Write-Host "  状態ファイルは残っていますが、ゲームファイルは素の状態です" `
            -ForegroundColor Yellow
        Write-Host "  （Steam再インストール等で上書きされたようです）。続行します。" `
            -ForegroundColor Yellow
        Remove-Item -Force $statePath -ErrorAction SilentlyContinue
    } else {
        Fail ("このゲームには既にHDパッチが適用済みです。`n" +
              "元に戻したい場合は先に Uninstall.cmd を実行してください。")
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
    'B4459F0637F7E1B0' = '通常版（Steam・未改造）'
    '7CB8B11941A14007' = 'JPパッチ適用済み'
}
$variant = $knownAin[$ainHash]
if (-not $variant) { $variant = "改造済み/非公式パッチ版 (ain hash $ainHash)" }

$gmPath = Join-Path $GameDir 'Rance7GM.ald'
$gaPath = Join-Path $GameDir 'Rance7GA.ald'
if (-not (Test-Path $gmPath)) { Fail "Rance7GM.ald が見つかりません" }
if (-not (Test-Path $gaPath)) { Fail "Rance7GA.ald が見つかりません" }

# The JP patch rewrites the GM archive (R18 CGs); vanilla payloads are
# derived from the censored sources so the asset set must match the base.
$gmHash = (Sha256 $gmPath).Substring(0, 12)
if ($gmHash -eq '27D55DF49209') { $assetSet = 'jp' }
elseif ($gmHash -eq '0B20D110235A') { $assetSet = 'vanilla' }
else { $assetSet = 'jp' }   # modified/unknown ald: jp assets were built on jp base

Write-Host ""
Write-Host "  対象         : $GameDir"
Write-Host "  AINバリアント: $variant"
Write-Host "  素材セット   : $assetSet"
Write-Host ""

# ---------- free space check (repack needs orig + new archive) ----------

# orig archives + new archives + generated intermediates + persistent
# payload cache (~2.5 GB each)
$need = (Get-Item $gmPath).Length + (Get-Item $gaPath).Length + 8GB
$drive = (Get-Item $GameDir).PSDrive
$free = (Get-PSDrive $drive.Name).Free
if ($free -lt $need) {
    Fail ("ドライブ {0}: の空き容量が足りません - 必要 ~{1:N1} GB / 空き {2:N1} GB" -f
          $drive.Name, ($need / 1GB), ($free / 1GB))
}

# ---------- backup ----------

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$bakDir = Join-Path $GameDir "backup\hd_$stamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $bakDir 'DLL') | Out-Null

$looseSrc = @(
    @{ g = 'AliceLogo3.alk';        b = 'AliceLogo3.alk' },
    @{ g = 'DLL\AliceLogo3.dll';    b = 'DLL\AliceLogo3.dll' }
)
$protected = @('Rance7.ain', 'Rance7GM.ald', 'Rance7GA.ald', 'System40.ini')
foreach ($f in $protected) {
    $src = Join-Path $GameDir $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $bakDir $f) }
}
foreach ($l in $looseSrc) {
    $src = Join-Path $GameDir $l.g
    if (Test-Path $src) { Copy-Item $src (Join-Path $bakDir $l.b) }
}
Write-Host "  バックアップ: $bakDir"

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
if (-not (Test-Path $pyExe)) { Fail "インストーラーのファイルが不足しています: $pyExe" }

Write-Host ""
Write-Host "[1/5] HD素材の生成 - ゲーム内画像をAIで2倍化 ..." -ForegroundColor Cyan
Write-Host "      DirectML対応GPUなら数分。再インストール時は生成済み素材を再利用します"
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
    Fail "アセット生成に失敗しました - ゲームファイルは無傷です（バックアップ: $bakDir）"
}
# sanity: count generated payloads vs manifest (manual assets excluded)
$recipes = Get-Content (Join-Path $Root 'gen\recipe_manifest.json') -Raw |
           ConvertFrom-Json
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
if ($got -lt $want) {
    Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
    Fail "アセット生成が途中で止まりました（$got/$want）- ゲームファイルは無傷です"
}
Write-Host "  マニフェスト照合OK（$got / $want 件）" -ForegroundColor DarkGray

# AliceLogo3.* only exists when the JP patch installed the newer logo
# plugin; vanilla Steam installs carry AliceLogo2.dll instead and have
# no .alk at all, so every step below is conditional on the backup.
$alkSrc = Join-Path $bakDir 'AliceLogo3.alk'
$alkGen = Join-Path $genDir 'files\AliceLogo3.alk'
if (Test-Path $alkSrc) {
    # decode each entry from the backed-up original, upscale 2x,
    # repack the ALK container (whole-output cache keyed on src bytes)
    & $pyExe (Join-Path $Root 'gen\gen_alk.py') `
        --src $alkSrc --dst $alkGen --cache-dir $cacheDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $alkGen)) {
        Remove-Item -Recurse -Force $genDir -ErrorAction SilentlyContinue
        Fail "AliceLogo3.alk の生成に失敗しました - ゲームファイルは無傷です（バックアップ: $bakDir）"
    }
} else {
    Write-Host "  AliceLogo3.alk は存在しないためスキップ"
}

# DLL\AliceLogo3.dll: the shipped binary is just the user's original
# plugin with two 800x600 -> 1600x1200 constants patched (8 bytes
# total). Patch the backed-up copy instead of shipping the binary.
$dllSrc = Join-Path $bakDir 'DLL\AliceLogo3.dll'
$dllOut = Join-Path $genDir 'files\DLL\AliceLogo3.dll'
if (Test-Path $dllSrc) {
$dllBytes = [IO.File]::ReadAllBytes($dllSrc)
$dllPatch = @(
    @(0x1312,  0x0320, 0x0640), @(0x131c,  0x0258, 0x04b0),
    @(0x20d2c, 0x0320, 0x0640), @(0x20d30, 0x0258, 0x04b0)
)
$dllChanged = 0
foreach ($p in $dllPatch) {
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
        Write-Host (("  ! AliceLogo3.dll が想定と異なります（0x{0:x}）- " +
                     "パッチせずスキップします（ロゴは低解像度のままの可能性）") -f $o) `
            -ForegroundColor Yellow
    }
}
New-Item -Force -ItemType Directory (Split-Path $dllOut) | Out-Null
[IO.File]::WriteAllBytes($dllOut, $dllBytes)
Write-Host "  AliceLogo3.dll に $dllChanged 箇所パッチ（800x600 -> 1600x1200）"
} else {
    Write-Host "  DLL\AliceLogo3.dll は存在しないためスキップ"
}

# ---------- AIN patch ----------

# From here on the game's own files get replaced; mark in-progress so an
# interrupted run cannot be mistaken for a clean state on re-run.
[IO.File]::WriteAllText($statePath, "in-progress; backup=$bakDir")

Write-Host ""
Write-Host "[2/5] Rance7.ain - パッチを適用します ..." -ForegroundColor Cyan
$tmpAin = Join-Path $GameDir 'Rance7.ain.hdtmp'
try {
    $r = [HdPatch]::ApplyAinPatch($ainPath, $tmpAin, $sites, $aliceExe,
                                  [Action[string]]$log)
} catch {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail "AINパッチに失敗しました: $($_.Exception.Message)`n元のファイルは無傷です（バックアップ: $bakDir）"
}
Write-Host ("  パッチ箇所: {0} 件を解決（適用済 {1} / 緩和 {2} / 曖昧 {3} / 関数欠落 {4}）" -f
            $r.Ok, $r.AlreadyPatched, $r.Relaxed, $r.Ambiguous, $r.MissingFunc)
if ($r.Writes -eq 0 -and $r.AlreadyPatched -eq 0) {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail "パッチ対象が見つかりませんでした - このAINには適用できません。`n詳細:`n  $($r.Problems -join "`n  ")"
}
if ($r.Ambiguous -gt 0 -or $r.MissingFunc -gt 0) {
    Write-Host "  注意: 一部の箇所に軽微な問題があります（処理は続行）:" -ForegroundColor Yellow
    $r.Problems | Select-Object -First 8 | ForEach-Object { Write-Host "    ! $_" }
}
# sanity check the produced AIN parses
$verifyJam = Join-Path $env:TEMP ("hd_verify_" + [guid]::NewGuid().ToString('N') + '.jam')
& $aliceExe ain dump -C -o $verifyJam $tmpAin 2>$null | Out-Null
$ok = ($LASTEXITCODE -eq 0)
Remove-Item $verifyJam -ErrorAction SilentlyContinue
if (-not $ok) {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail "パッチ後のAINが検証を通りませんでした - 中止します（元のファイルは無傷です）"
}
Move-Item -Force $tmpAin $ainPath
Write-Host "  Rance7.ain -> HD化完了"

# ---------- asset payload ----------

$mj = Get-Content $manifest -Raw | ConvertFrom-Json

function Repack-Archive([string]$aldPath, [string]$arcName, [string]$dir, [int]$disk,
                        [Collections.Generic.Dictionary[int,int[]]]$extraRows = $null) {
    # shipped payloads (manual exceptions) first; generated payloads last
    # (generated wins on name collision, though there should be none)
    $dirs = @()
    foreach ($s in @('shared', $assetSet)) {
        $src = Join-Path $dataDir ("$dir\" + $s)
        if (Test-Path $src) { $dirs += $src }
    }
    foreach ($s in @('shared', $assetSet)) {
        $src = Join-Path $genDir ("$dir\" + $s)
        if (Test-Path $src) { $dirs += $src }
    }
    if ($dirs.Count -eq 0) { Fail "$arcName 用の素材が見つかりません" }
    Write-Host ("  {0}: 格納する素材 {1} ファイル" -f $arcName,
                (($dirs | ForEach-Object { (Get-ChildItem $_).Count }) |
                 Measure-Object -Sum).Sum)
    $tmpAld = "$aldPath.hdtmp"
    try {
        $res = [HdPatch]::RepackAld($aldPath, $tmpAld, [string[]]$dirs,
                                    $disk, [Action[string]]$log,
                                    $extraRows, $repackProg)
    } catch {
        Remove-Item $tmpAld -ErrorAction SilentlyContinue
        Fail "$arcName の再梱包に失敗: $($_.Exception.Message) - 元のアーカイブは無傷です"
    }
    & $clearBar
    Move-Item -Force $tmpAld $aldPath
    Write-Host ("  {0}: 計{1}件（上書き {2} / 追加 {3}）" -f
                $arcName, $res[0], $res[1], $res[2])
}

# ---------- archive size rebalance ----------
# The engine seeks into .ald volumes via a signed 32-bit byte offset, so
# entries starting at/above 0x80000000 are unreachable (they silently
# render nothing). Generated payloads can push Rance7GM.ald past the
# limit; when the projection exceeds the threshold below, the biggest
# payloads are moved into the GA payload dirs before repacking. GA has
# plenty of headroom and the link-table redirect further down is computed
# from whatever the GA dirs contain, so no other step needs to know.
$AldSeekLimit = 0x80000000L
$AldTarget    = 0x7F000000L   # stop ~33 MB under the hard limit
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
Write-Host ("  アーカイブ容量確認: Rance7GM.ald の完成予想は {0:N0} MB" -f ($gmProj / 1MB))

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
    Write-Host ("  サイズ調整: 大きい素材 {0} 件をGMからGAへ移動（{1:N0} MB）→ GMは約{2:N0} MBに" -f $moved, ($movedBytes / 1MB), ($gmProj / 1MB))
    if ($gmProj -gt $AldTarget) {
        Write-Host ("  ! 警告: それでもGMが安全圏を超える見込みです - " +
                    "2GB以降の素材が表示されない可能性があります") `
            -ForegroundColor Yellow
    }
}

# GA must be repacked first: 694 CG entries were relocated GM -> GA in the
# HD set, so every archive's global link table must point the moved file
# numbers at their new GA positions.
Write-Host ""
Write-Host "[3/5] Rance7GA.ald - HD素材を格納します ..." -ForegroundColor Cyan
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
    $movedRows[$digits - 1] = [int[]]@(0, $gaOrig.Count + $i)
}
Write-Host ("  GAへのリンク振替: {0} 行" -f $movedRows.Count)

Write-Host ""
Write-Host "[4/5] Rance7GM.ald - HD素材を格納します（約1〜2GB） ..." -ForegroundColor Cyan
Repack-Archive $gmPath 'Rance7GM.ald' 'GM' $mj.archives.'Rance7GM.ald'.disk $movedRows

# hard ceiling check: the engine's signed 32-bit seek cannot reach
# entries at/above 0x80000000, so an oversized volume means invisible
# assets - warn loudly rather than leave a silently broken install
foreach ($ald in @($gaPath, $gmPath)) {
    $sz = (Get-Item $ald).Length
    if ($sz -ge $AldSeekLimit) {
        Write-Host ("  ! 警告: {0} が {1:N0} バイト - エンジンの2GB読み取り" +
                    "上限を超えています。末尾の素材が表示されません。" +
                    " Uninstall.cmd で戻してからご報告ください。" -f
                    (Split-Path $ald -Leaf), $sz) -ForegroundColor Red
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
            Write-Host "  $($f.dst) -> スキップ（この環境には存在しないファイル）"
            continue
        }
        Fail "素材が見つかりません: $($f.src)"
    }
    $dst = Join-Path $GameDir $f.dst
    Copy-Item -Force $src $dst
    Write-Host "  $($f.dst) -> 差し替え完了"
}

# ---------- System40.ini ----------

Write-Host ""
Write-Host "[5/5] System40.ini - 表示を1600x1200に設定します ..." -ForegroundColor Cyan
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
[IO.File]::WriteAllText($statePath, "installed; backup=$bakDir")

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host "   HDパッチの適用が完了しました。" -ForegroundColor Green
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  バックアップ: $bakDir"
Write-Host "  元に戻したいときは Uninstall.cmd を実行してください。"
if ($Elevated) { Read-Host "Enterキーを押して閉じてください" | Out-Null }
