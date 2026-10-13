#requires -Version 5.1
<#
.SYNOPSIS
    Build the release zips (installer + payload) and attach them to the
    GitHub release for the given tag.

.DESCRIPTION
    The tag-triggered GitHub Actions workflow creates the release entry;
    the asset payload is too large for the repo, so this script packages
    installer/ locally.

    GitHub release assets are limited to 2 GB each, so the output is two
    files that overlay each other when extracted into the same folder:
      dist\rance7_hd_patch_<ver>.zip        installer + data (except GA)
      dist\rance7_hd_patch_<ver>_ga.zip     installer\data\GA only

.EXAMPLE
    tools\package.ps1            # uses the newest v* tag
    tools\package.ps1 v1.0.0
    tools\package.ps1 v1.0.0 -NoUpload   # zips only, no upload
#>
param(
    [string]$Version,
    [switch]$NoUpload
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not $Version) {
    $Version = git describe --tags --abbrev=0 --match 'v*' 2>$null
    if (-not $Version) { throw "no v* tag found; pass -Version explicitly" }
}
$Version = $Version.Trim()
Write-Host "Packaging $Version"

if (-not (Test-Path 'installer\data')) {
    throw "installer\data missing - build the payload first"
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Write-Zip($zipPath, $files, $extra) {
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    $fs  = [IO.File]::Open($zipPath, 'Create')
    $arc = New-Object IO.Compression.ZipArchive($fs, 'Create')
    try {
        $i = 0
        foreach ($f in $files) {
            $i++
            if ($i % 500 -eq 0) {
                Write-Host "  $i / $($files.Count) files"
            }
            $rel = $f.FullName.Substring($root.Length + 1) -replace '/', '\'
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $arc, $f.FullName, $rel) | Out-Null
        }
        foreach ($e in $extra) {
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $arc, $e[0], $e[1]) | Out-Null
        }
    } finally {
        $arc.Dispose(); $fs.Close()
    }
    $mb = [math]::Round((Get-Item $zipPath).Length / 1MB)
    Write-Host "wrote $zipPath ($mb MB)"
}

New-Item -ItemType Directory -Force "$root\dist" | Out-Null
$mainZip = "$root\dist\rance7_hd_patch_$Version.zip"
$gaZip   = "$root\dist\rance7_hd_patch_${Version}_ga.zip"

$all  = Get-ChildItem installer -Recurse -File
$ga   = @($all | Where-Object { $_.FullName -like '*installer\data\GA\*' })
$rest = @($all | Where-Object { $_.FullName -notlike '*installer\data\GA\*' })

Write-Zip $mainZip $rest @(, @("$root\README.md", 'README.md'))
Write-Zip $gaZip   $ga   @()

if (-not $NoUpload) {
    gh release upload $Version $mainZip $gaZip --clobber
    if ($LASTEXITCODE -ne 0) { throw "gh release upload failed" }
    Write-Host "uploaded to release $Version"
}
