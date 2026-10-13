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

## Number font

| File | Size (orig) | Usage |
|---|---|---|
| cg10171-10173 | 400x34 | Number font sheets (0-9) for in-game counters. AI upscale left a white fringe halo at edges (original edge is dark red 79,1,0); fixed by edge decontamination + removal of outer light-fringe pixels connected to the transparent boundary. Same recipe applies to other fringe-affected UI sprites. |

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

## AI fringe-removal recipes (established during verification)

The upscaler (2x-AnimeSharpV4) sometimes invents edge artifacts that are
absent in vanilla. Three confirmed artifact types and their fixes:

- **Alpha fill (light "halo" lines)** — semi-transparent white/light pixels
  added beyond the original alpha footprint (cg10249 battle turn gauge,
  cg10118 action gauge, balloons cg10251/253). Fix: NEAREST 2x, or keep AI
  RGB and clamp alpha to the original footprint (nearest-2x mask).
- **Dark border fill (opaque UI)** — thick black frame lines drawn on
  light button/bar edges (cg10079-81 button sheets, cg10052-10119 bars).
  Fix: **component-based revert** — label connected components of the
  "AI-darkened" mask (`ref_lum - ai_lum > 30` vs Lanczos-2x reference),
  revert components that touch the outer border OR are >=120 px (plus
  2px dilation) back to the Lanczos value. Glyph strokes are small
  components and stay AI, so text keeps the AI sharpness. A pixel-level
  revert must NOT be used: it leaves glyph edges as an AI/Lanczos
  patchwork and makes text visibly jagged.
- **Stroke thinning (baked text)** — AI lightens originally-dark glyph
  pixels, making baked-in text look thin/washed (cg10139 ForceFull panel,
  cg10138 exec button sheet). Fix: additionally revert components >=8px
  where `ai_lum - ref_lum > 30 AND ref_lum < 160` — restores stroke
  weight while keeping AI sharpness.
- **Killed white outlines** — AI also removes the light outline around
  baked text (cg10139 ※ notes). Restoring by copying Lanczos pixels
  gives jagged blocky edges; instead **lift AI luminance** toward the
  Lanczos value (`gain = (lum + lift) / lum` on RGB) with a
  gaussian-feathered weight where `ref_lum > 140` — smooth outline
  restoration with zero Lanczos texture pasted.
- **Baked-text panels** — for text-heavy document images the final recipe
  reverts whole TEXT REGIONS to Lanczos: detect orig dark glyph cores
  (lum<150, connected components 4..400px), dilate 6px, feather, and
  blend region -> Lanczos. Background/illustration stays AI. Applied to
  cg10139 (ForceFull panel incl. button+※notes), cg10138 (exec button
  sheet), cg10130/10131/12000 (sibling panels), cg10100/10101/10098,
  cg10371, cg10448 (turn-number sheet), cg10105, cg10110, cg10132,
  cg10051, cg10072/73, cg13306/21/36/39/50/75/90, cg13627/648,
  cg14851/52/55, cg50892, cg57011.
  - Refinement (v5, run-based): per scanline, maximal runs of dark
    (lum<130) or bright (lum>200) pixels >=40px long that come within
    ~15px of the text mask are reverted WHOLE — horizontally and
    vertically. This keeps ruled lines, bevels and button edges
    uniformly Lanczos even when the line pixels belong to a giant
    background component that component-labeling cannot isolate
    (cg10139's baked button bevels; cg10131's white inner bevel).
    Alpha is clamped to the orig 2x footprint. Applied to cg10139 and
    cg10130/10131/10101/12000/13336/10371/13306/13390/10448/13550/
    13648/13350/13627/10132/10110/10098/10105/13575/13321/50892/10051.
- **White fringe inside semi-transparent edges** (number fonts
  cg10171-173): keep AI RGB + original alpha geometry, decontaminate
  edge RGB by un-blending against the white backing, then remove
  connected light pixels outside the intended dark-red outline.

### Assets processed

- NEAREST 2x: cg10249, cg10296, cg10298
- Component-revert hybrid: cg10052, cg10058, cg10074, cg10075, cg10077,
  cg10079-81, cg10082-88, cg10094, cg10113, cg10114, cg10119
- Component-revert + alpha-extras removal: cg10001-03, cg10118, cg10121,
  cg10155-57, cg10192-95, cg10201, cg10221, cg10251/253, cg10261,
  cg10297, cg10383, cg10704, cg13393, cg13683, cg30022-25 (AJP), cg30088
- Same recipe, battle-UI band sweep (10150-10280): cg10151-53, cg10174-77,
  cg10180-89, cg10199, cg10200, cg10204, cg10224, cg10248, cg10252/254,
  cg10255-57, cg10279, plus cg10202/206/212/222/226 command panels
- Hybrid + alpha clamp: cg10126
- Unblended alpha + fringe removal: cg10171-73
