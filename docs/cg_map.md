# CG Asset Map (Rance7GM / Rance7GA)

Reverse-lookup table: CG file number -> what it is / where it is used.
Updated as assets are identified. Columns: file name, size (original),
volume (ALD file), usage.

IMPORTANT: **CG ID (AIN code) = filename number - 1**. The ALD link table is
indexed by the AIN CG ID: entry at index N points to file `cg(N+1)`.
E.g. `CG_IS_EXIST(64990)` in the code resolves file `cg64991.QNT`.

## Startup sequence (RunLogos / ShowWarningScreen / ShowCompanyLogo)

| CG ID (AIN) | File | Size (orig) | Usage |
|---|---|---|---|
| 64990 (0xfdde) | cg64991.QNT | 800x600 | Warning screen ("注意文") |
| 64991 (0xfddf) | cg64992.QNT | 800x600 | Company logo 1 (non-AliceSoft) |
| 64992 (0xfde0) | cg64993.QNT | 800x600 | Company logo 2 (non-AliceSoft) |
| ? | cg64990.QNT | 800x600 | Black/aux image preceding the warning set |
| ? | cg09998.QNT | 800x600 | Dark/background image near startup |
| ? | cg09999.QNT | 800x600 | Blood splatter graphic (warning screen related) |
| (AliceLogo3.alk) | - | - | AliceSoft logo movie via AliceLogo3.dll (separate file) |

## Title screen

| CG ID (AIN) | File | Size (orig) | Usage |
|---|---|---|---|
| 10707 | cg10708.QNT | 52x26 | Title screen logo |
| 10081 | cg10082.QNT | 84x20 | Close button |
| 10700 | cg10701.QNT | 800x568 | CG-mode background panel frame |
| 10701-10706 | cg10702-10707 | small | CG-mode UI parts (dots, icons, scroll parts) |

## CG mode

| File | Size (orig) | Usage |
|---|---|---|
| cg61001-61961 | 160x120 | CG-mode thumbnails (first half, 53 files) |
| cg62001-64003 | 160x120 | CG-mode thumbnails (second half, 51 files) |

## Music mode

| CG ID (AIN) | File | Size (orig) | Usage |
|---|---|---|---|
| 10710 | cg10711.QNT | 800x568 | Music mode panel frame |
| 10711 | cg10712.QNT | 616x306 | Music mode center panel |
| 10712 | cg10713.QNT | 385x6 | Playback bar surface |
| 10713-10716 | cg10714-10717 | small | Music mode control buttons (play/stop/prev/next) |

## Event / dungeon

| File | Size (orig) | Usage |
|---|---|---|
| cg00001-039xx | 800x600 | Event CGs and standing sprites (~498 files) |
| cg09000-09721 | 568x312 | Event scene cut-ins / dungeon visuals (~130 files) |
| cg06000-06018 | ~800x600 | Event CGs |

## Battle

| File | Size (orig) | Usage |
|---|---|---|
| cg41xxx | various | Battle unit face/portrait images (~600 files) |
| cg45xxx-57xxx | various | Battle/game CGs |
| cg49000-49074 | 152x78 | Battle effect sprites (~60 files) |

## Event cut-in effects

| CG ID (AIN) | File | Size (orig) | Usage |
|---|---|---|---|
| 1053 | cg01054.QNT | 216x871 | シィル氷づけ vertical cut-in (織田／美樹保護 = CG-mode #6). Slides vertically; fixed X=510 -> 1020 in `tagSill@cutIn1`. |
| 1054 | cg01055.QNT | 739x227 | シィル氷づけ horizontal cut-in. Slides horizontally; fixed Y=245 -> 490 in `tagSill@cutIn2`. |

## Main map / territory selection

| File | Size (orig) | Usage |
|---|---|---|
| cg10296 | 800x600, 32 colors | Territory color mask for region hit-testing. **NEAREST-upscaled, never AI/Lanczos** — color values must be preserved exactly or territory selection breaks. |
| cg10298 | 800x600, 4 colors | Companion map mask (same treatment as cg10296) |
| cg10299 | 800x600, 777 colors | Map overlay (AI-upscaled) |
| cg10300 | 800x600, ~303k colors | Main map artwork (AI-upscaled) |
| cg10301-10xxx | small | Map-related unit/castle icons |

## Text / UI misc

| File | Size (orig) | Usage |
|---|---|---|
| cg60004-60007 | 24x24 | Text-advance wait icons (tagWaitIconManager) |

## Archive layout notes

- `Rance7GA.ald` = volume A (disk 0): master link table + the 694 upscaled
  files (current layout). The link table (CG ID -> (disk, 1-based position))
  lives here and is what the engine consults.
- `Rance7GM.ald` = volume M (disk 12): main CG storage.
- Volume letter = last char of filename before .ald (A=0, B=1, ..., M=12).
- Link table `ptr` field = 1-based position within that volume's file list
  (stored value = position + 1; decoded disk = byte0 - 1).
- Link table index = AIN CG ID = filename number - 1. Every existing file
  has an entry; unmapped entries correspond to numbering gaps only.
- Engine appears to fail reading file offsets beyond 2GB (signed int32 seek).
  Keep every volume below 0x80000000 bytes.
- Multi-volume: the engine opens same-family volumes by letter. The
  "Dai Sengoku Rance" mod ships `Rance7GB.ald`/`Rance7WB.ald` (letter B,
  disk 1), proving additional volumes work. Current layout avoids needing a
  new letter by keeping upscaled files in GA (disk 0).
