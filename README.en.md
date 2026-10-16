# Sengoku Rance HD Patch

**[日本語版 README (Japanese)](README.md)** / **[简体中文版 README (Chinese)](README.zh.md)**

A patch that raises the fixed 800×600 display of the Steam release of **Sengoku Rance (Rance 7)** to **1600×1200**. It doubles the drawing coordinates and layout, and also regenerates the in-game image assets at 2x via AI upscaling.

> **⚠️ This is an unofficial fan-made patch. It is not affiliated with or endorsed by AliceSoft or the publisher.**
> **Use this patch entirely at your own risk. The author accepts no responsibility for any damage or malfunction caused by installing it.**

## Features

- **1600×1200 logical resolution** — doubles coordinate/layout constants inside `Rance7.ain` (the game executable is never modified)
- **HD image assets** — ~6,600 images (CGs, character sprites, UI, battle screens, maps) upscaled 2x by AI and repacked into the archives
- **HD logo animation** — `AliceLogo*.alk` and `DLL\AliceLogo*.dll` are made resolution-aware where present
- **HD OP/ED movies** — `movie\*.alm` files are upscaled 2x and re-encoded (640×480 → 1280×960)
- **Generated at install time** — HD assets are produced from your own game data during installation; the package is only ~120 MB
- **Automatic variant detection** — detects the state of your install and applies the appropriate patch
- **Safe by design** — a timestamped backup is created before anything is modified; failures leave the originals untouched

## Requirements

- **Sengoku Rance on Steam** (vanilla / JP patch applied / Simplified Chinese build / English (Kagura) build / other unofficial patches)
- **DirectML-capable GPU recommended** — works without one, but the first asset generation takes considerably longer
- **~9 GB of free space** — working area and backup (the working area is deleted automatically when done)

## Supported variants

The patch can be installed on any of the following (order does not matter):

- Vanilla (untouched Steam install)
- JP patch applied
- Simplified Chinese build
- English (Kagura) build
- Other unofficial patches are auto-detected as long as their AIN changes do not overlap

> **Combining with other patches**: apply other patches BEFORE the HD patch. If you apply another patch after HD and the display breaks, restore once with `Uninstall.cmd`, then install again.

## Installation

1. Download `SengokuRance_HDPatch.zip` from the [releases page](https://github.com/after-vesper/rance7_hd_patch/releases/latest) and extract it anywhere
2. Close the game, then double-click `Install.cmd` in the extracted folder — your Steam game folder is detected automatically
3. If the game folder is under `Program Files`, a UAC prompt for administrator rights appears
4. AI generation of the HD assets and OP/ED movies begins (~10 minutes on a DirectML-capable GPU)
5. When "HD patch installed." appears, you are done

For non-Steam installs you will be asked to enter the path. You can also specify it directly from PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File Install.ps1 -GameDir "D:\Games\SengokuRance"
```

> The installer refuses to run while the game is running. Please close the game first.

### Files that are modified

- `Rance7.ain` — coordinate/layout constants doubled
- `Rance7GM.ald` / `Rance7GA.ald` — image data repacked in HD (if an archive would exceed 2 GB, assets are automatically moved to the GA side)
  - On the zh build, `Rance7GA.ald` / `Rance7GB.ald` are used instead (`Rance7GM.ald` is left untouched)
- `AliceLogo*.alk` / `DLL\AliceLogo*.dll` — logo animation upscaled (when present)
- `DLL\PlayMovie.dll` — on the en build only, a 16-byte patch disables VMR-7 so the rebuilt movie player can render HD movies via VMR-9/EVR
- `movie\*.alm` — OP/ED movies upscaled (all that exist)
- `System40.ini` — `ViewWidth` / `ViewHeight` set to 1600×1200

Every original file is saved to `backup\hd_<timestamp>\` before being replaced.
A `hd_cache` folder holding generated assets is also created (see below).

## Uninstall

Double-click `Uninstall.cmd` and choose the backup to restore (the latest is the default).

It restores `Rance7.ain`, `System40.ini`, `Rance7*.ald`, the logo files, movies, and `PlayMovie.dll` from the newest backup. Save data is never touched.
Once every restored file verifies, the used backup folder is deleted automatically (other backups are kept).
Finally you are asked whether to delete `hd_cache` (the generated-asset cache, ~3.5 GB). Keeping it lets a future install skip the generation step.

## About the cache

`hd_cache` is a cache of generated assets and movies (~3.5 GB) created inside the game folder.

- Reinstalling or updating the patch skips the AI generation step, making it much faster
- It is still reused after a Steam reinstall of the game (same path)
- It is invalidated automatically when the model or asset sources change, so stale output can never leak in

## Updating to a new version

1. Run `Uninstall.cmd` to revert the current patch (keeping `hd_cache` is fine)
2. Run `Install.cmd` from the new version

## Notes

- **Steam release only** (vanilla / JP patch / Simplified Chinese / English builds supported)
- Without a DirectML-capable GPU the first generation runs on CPU and takes a while
- The installer never modifies the game executable (`Rance7.exe`)
- Antivirus software may flag the scripts or bundled tools as false positives; add an exclusion if needed
- **Use entirely at your own risk.** The author accepts no responsibility for any issues caused by this patch (including save-data corruption or game malfunctions). Backing up your save data beforehand is recommended

## License

- The upscaling model AnimeJaNai HD v3 Sharp1 UltraCompact is **CC BY-NC-SA 4.0** — see [installer/LICENSES/model.txt](installer/LICENSES/model.txt)
- alice-tools (bundled binary) is GPL — see [installer/LICENSES/alice-tools.txt](installer/LICENSES/alice-tools.txt)
- ffmpeg (bundled binary, used only for movie upscaling) is GPL — see [installer/LICENSES/ffmpeg.txt](installer/LICENSES/ffmpeg.txt)
