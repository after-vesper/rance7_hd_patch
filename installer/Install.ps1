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
    Compatible with vanilla, JP-patched, NationalExpansion and JP+NE
    installs, in any application order. Creates a timestamped backup
    under backup\hd_* before touching anything.
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File Install.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File Install.ps1 -GameDir D:\Games\SengokuRance
#>
param(
    [string]$GameDir
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Sha256([string]$p) { (Get-FileHash -Algorithm SHA256 $p).Hash }

# ---------- prerequisites ----------

$aliceExe = Join-Path $Root 'bin\alice.exe'
$csPath   = Join-Path $Root 'HdPatch.cs'
$dataDir  = Join-Path $Root 'data'
$manifest = Join-Path $dataDir 'manifest.json'
$sites    = Join-Path $dataDir 'hd_sites.json'
foreach ($req in @($aliceExe, $csPath, $manifest, $sites)) {
    if (-not (Test-Path $req)) { Fail "missing installer file: $req" }
}

# ---------- locate the game ----------

if (-not $GameDir) {
    Write-Host "Sengoku Rance HD patch installer" -ForegroundColor Cyan
    Write-Host ""
    $GameDir = Read-Host "Path to the Sengoku Rance install folder (contains Rance7.exe)"
}
$GameDir = $GameDir.Trim().Trim('"').TrimEnd('\', '/')
$ainPath = Join-Path $GameDir 'Rance7.ain'
$iniPath = Join-Path $GameDir 'System40.ini'
if (-not (Test-Path $ainPath)) { Fail "Rance7.ain not found in '$GameDir'" }
if (-not (Test-Path $iniPath)) { Fail "System40.ini not found in '$GameDir'" }

if (Get-Process -Name Rance7 -ErrorAction SilentlyContinue) {
    Fail "Rance7.exe is running - close the game first."
}

# ---------- variant detection ----------

$ainHash = (Sha256 $ainPath).Substring(0, 16)
$knownAin = @{
    'B4459F0637F7E1B0' = 'vanilla (Steam, unmodified)'
    '7CB8B11941A14007' = 'JP patch applied'
    '090D9FD001997022' = 'NationalExpansion applied'
    '7BF70D33BAC35CE1' = 'JP + NationalExpansion'
}
$variant = $knownAin[$ainHash]
if (-not $variant) { $variant = "unknown (ain hash $ainHash)" }

$gmPath = Join-Path $GameDir 'Rance7GM.ald'
$gaPath = Join-Path $GameDir 'Rance7GA.ald'
if (-not (Test-Path $gmPath)) { Fail "Rance7GM.ald not found" }
if (-not (Test-Path $gaPath)) { Fail "Rance7GA.ald not found" }

# The JP patch rewrites the GM archive (R18 CGs); vanilla payloads are
# derived from the censored sources so the asset set must match the base.
$gmHash = (Sha256 $gmPath).Substring(0, 12)
if ($gmHash -eq '27D55DF49209') { $assetSet = 'jp' }
elseif ($gmHash -eq '0B20D110235A') { $assetSet = 'vanilla' }
else { $assetSet = 'jp' }   # modified/unknown ald: jp assets were built on jp base

Write-Host ""
Write-Host "Target     : $GameDir"
Write-Host "AIN variant: $variant"
Write-Host "Asset set  : $assetSet"
Write-Host ""

# ---------- free space check (repack needs orig + new archive) ----------

$need = (Get-Item $gmPath).Length + (Get-Item $gaPath).Length + 3GB
$drive = (Get-Item $GameDir).PSDrive
$free = (Get-PSDrive $drive.Name).Free
if ($free -lt $need) {
    Fail ("not enough free space on drive {0}: need ~{1:N1} GB, have {2:N1} GB" -f
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
Write-Host "Backup     : $bakDir"

# ---------- compile patch engine ----------

Add-Type -TypeDefinition (Get-Content $csPath -Raw) `
         -ReferencedAssemblies 'System.Web.Extensions'
$log = { param($m) Write-Host "  $m" }

# ---------- AIN patch ----------

Write-Host ""
Write-Host "[1/4] Patching Rance7.ain (anchor resolution) ..."
$tmpAin = Join-Path $GameDir 'Rance7.ain.hdtmp'
try {
    $r = [HdPatch]::ApplyAinPatch($ainPath, $tmpAin, $sites, $aliceExe,
                                  [Action[string]]$log)
} catch {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail "AIN patch failed: $($_.Exception.Message)`nOriginal files untouched (backup: $bakDir)"
}
Write-Host ("  sites: resolved={0} already={1} relaxed={2} ambiguous={3} missing_funcs={4}" -f
            $r.Ok, $r.AlreadyPatched, $r.Relaxed, $r.Ambiguous, $r.MissingFunc)
if ($r.Writes -eq 0 -and $r.AlreadyPatched -eq 0) {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail "no patch sites resolved - this AIN is not compatible.`nProblems:`n  $($r.Problems -join "`n  ")"
}
if ($r.Ambiguous -gt 0 -or $r.MissingFunc -gt 0) {
    Write-Host "  (non-fatal problems; first few:)" -ForegroundColor Yellow
    $r.Problems | Select-Object -First 8 | ForEach-Object { Write-Host "    ! $_" }
}
# sanity check the produced AIN parses
$verifyJam = Join-Path $env:TEMP ("hd_verify_" + [guid]::NewGuid().ToString('N') + '.jam')
& $aliceExe ain dump -C -o $verifyJam $tmpAin 2>$null | Out-Null
$ok = ($LASTEXITCODE -eq 0)
Remove-Item $verifyJam -ErrorAction SilentlyContinue
if (-not $ok) {
    Remove-Item $tmpAin -ErrorAction SilentlyContinue
    Fail "patched AIN failed alice-tools validation - aborted, original untouched"
}
Move-Item -Force $tmpAin $ainPath
Write-Host "  Rance7.ain -> HD patched"

# ---------- asset payload ----------

$mj = Get-Content $manifest -Raw | ConvertFrom-Json

function Repack-Archive([string]$aldPath, [string]$arcName, [string]$dir, [int]$disk,
                        [Collections.Generic.Dictionary[int,int[]]]$extraRows = $null) {
    $dirs = @()
    foreach ($s in @('shared', $assetSet)) {
        $src = Join-Path $dataDir ("$dir\" + $s)
        if (Test-Path $src) { $dirs += $src }
    }
    if ($dirs.Count -eq 0) { Fail "no payload set found for $arcName" }
    Write-Host ("  {0}: {1} payload files" -f $arcName,
                (($dirs | ForEach-Object { (Get-ChildItem $_).Count }) |
                 Measure-Object -Sum).Sum)
    $tmpAld = "$aldPath.hdtmp"
    try {
        $res = [HdPatch]::RepackAld($aldPath, $tmpAld, [string[]]$dirs,
                                    $disk, [Action[string]]$log, $extraRows)
    } catch {
        Remove-Item $tmpAld -ErrorAction SilentlyContinue
        Fail "repack of $arcName failed: $($_.Exception.Message) - original archive untouched"
    }
    Move-Item -Force $tmpAld $aldPath
    Write-Host ("  {0}: {1} files ({2} overridden, {3} added)" -f
                $arcName, $res[0], $res[1], $res[2])
}

# GA must be repacked first: 694 CG entries were relocated GM -> GA in the
# HD set, so every archive's global link table must point the moved file
# numbers at their new GA positions.
Write-Host ""
Write-Host "[2/4] Rance7GA.ald - applying HD assets ..."
Repack-Archive $gaPath 'Rance7GA.ald' 'GA' $mj.archives.'Rance7GA.ald'.disk

# Compute the moved-file link rows: names now in GA payloads that the
# user's GA did not contain (they resolve to the appended GA entries).
$gaOrig = [HdPatch]::ListAldNames((Join-Path $bakDir 'Rance7GA.ald'))
$gaOrigSet = [Collections.Generic.HashSet[string]]::new([string[]]$gaOrig)
$gaPayload = @()
foreach ($s in @('shared', $assetSet)) {
    $p = Join-Path $dataDir "GA\$s"
    if (Test-Path $p) { $gaPayload += (Get-ChildItem $p).Name }
}
$movedNames = $gaPayload | Where-Object { -not $gaOrigSet.Contains($_) } |
              Sort-Object
$movedRows = New-Object 'Collections.Generic.Dictionary[int,int[]]'
for ($i = 0; $i -lt $movedNames.Count; $i++) {
    $digits = [int]([regex]::Match([IO.Path]::GetFileNameWithoutExtension($movedNames[$i]), '\d+').Value)
    $movedRows[$digits - 1] = [int[]]@(0, $gaOrig.Count + $i)
}
Write-Host ("  link rows redirected to GA: {0}" -f $movedRows.Count)

Write-Host ""
Write-Host "[3/4] Rance7GM.ald - applying HD assets (this copies ~1-2 GB) ..."
Repack-Archive $gmPath 'Rance7GM.ald' 'GM' $mj.archives.'Rance7GM.ald'.disk $movedRows

# keep the remaining archives' link tables consistent (GM copies of the
# relocated entries remain but are shadowed by the GA redirect)
foreach ($extra in @('Rance7BA.ald', 'Rance7WA.ald')) {
    $xp = Join-Path $GameDir $extra
    if (Test-Path $xp) {
        Copy-Item $xp (Join-Path $bakDir $extra) -Force
        $n = [HdPatch]::PatchLinkRows($xp, $movedRows)
        Write-Host "  $extra : $n link rows updated"
    }
}

foreach ($f in $mj.files) {
    $src = Join-Path $dataDir ($f.src -replace '/', '\')
    $dst = Join-Path $GameDir $f.dst
    Copy-Item -Force $src $dst
    Write-Host "  $($f.dst) -> replaced"
}

# ---------- System40.ini ----------

Write-Host ""
Write-Host "[4/4] System40.ini - 1600x1200 ..."
# read/write as raw bytes via cp932 so no encoding conversion can corrupt
# unrelated settings
$enc932 = [Text.Encoding]::GetEncoding(932)
$ini = $enc932.GetString([IO.File]::ReadAllBytes($iniPath))
$ini = $ini -replace '(?m)^(ViewWidth)\s*=\s*\d+',  "`$1`t= 1600"
$ini = $ini -replace '(?m)^(ViewHeight)\s*=\s*\d+', "`$1`t= 1200"
[IO.File]::WriteAllBytes($iniPath, $enc932.GetBytes($ini))

Write-Host ""
Write-Host "=== HD patch applied ===" -ForegroundColor Green
Write-Host "Backup: $bakDir"
Write-Host "To revert, run Uninstall.ps1 and pick this backup folder."
