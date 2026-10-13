#requires -Version 5.1
<#
.SYNOPSIS
    Build the release zip (installer + payload) and attach it to the
    GitHub release for the given tag.

.DESCRIPTION
    The tag-triggered GitHub Actions workflow creates the release entry;
    the asset payload is too large for the repo, so this script packages
    installer/ locally and uploads dist\rance7_hd_patch_<ver>.zip.

.EXAMPLE
    tools\package.ps1            # uses the newest v* tag
    tools\package.ps1 v1.0.0
    tools\package.ps1 v1.0.0 -NoUpload   # zip only, no upload
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

$zip = Join-Path $root "dist\rance7_hd_patch_$Version.zip"
New-Item -ItemType Directory -Force "$root\dist" | Out-Null
if (Test-Path $zip) { Remove-Item $zip -Force }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fs  = [IO.File]::Open($zip, 'Create')
$arc = New-Object IO.Compression.ZipArchive($fs, 'Create')
try {
    # installer/ keeps its folder name inside the zip; README.md at root.
    $files = Get-ChildItem installer -Recurse -File
    $i = 0
    foreach ($f in $files) {
        $i++
        if ($i % 500 -eq 0) { Write-Host "  $i / $($files.Count) files" }
        $rel = $f.FullName.Substring($root.Length + 1) -replace '/', '\'
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $arc, $f.FullName, $rel) | Out-Null
    }
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $arc, "$root\README.md", 'README.md') | Out-Null
} finally {
    $arc.Dispose(); $fs.Close()
}
$mb = [math]::Round((Get-Item $zip).Length / 1MB)
Write-Host "wrote $zip ($mb MB)"

if (-not $NoUpload) {
    gh release upload $Version $zip --clobber
    Write-Host "uploaded to release $Version"
}
