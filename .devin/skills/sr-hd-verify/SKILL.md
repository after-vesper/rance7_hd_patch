# SR HD Verify — in-game navigation & verification procedure

Procedures that have been verified to work for testing the HD patch in
Sengoku Rance (System4). Always start the game from `game/` as the working
directory, or `System40.ini` is not found and the game shows a startup error.

## Golden rule: never click blind

**Before every click, verify the cursor position.** Past failures were
almost always caused by estimating coordinates from a scaled screenshot
and clicking without verification. The workflow that eliminated misses:

1. `tools/gridshot.ps1` — captures the window, crops the 1600x1200 game
   canvas (origin +3,+67 inside the PNG), scales it 1/2 to 800x600, and
   overlays a coordinate grid labelled in CANVAS coordinates. Read the
   target's canvas coordinates directly off this image — the numbers you
   see are the values to pass to cclick/cmove.
2. `work/cmove.ps1 -X <x> -Y <y>` — moves the cursor to canvas coords
   WITHOUT clicking (uses the same ClientToScreen conversion as
   click.ps1; throws if the window rect cannot be obtained).
3. `tools/cursorcap.ps1` — captures the real screen around the cursor
   (the cursor IS visible, unlike PrintWindow captures). Confirm the
   pointer is on the intended target; if not, adjust and repeat 2-3.
4. `work/cclick.ps1 -X <x> -Y <y>` — only then click.
5. After the click, capture again (gridshot or cap) and confirm the
   expected screen appeared BEFORE issuing the next action. Never chain
   multiple blind clicks — one mis-timed click into a menu can trigger
   destructive flows (a stray drag once opened the "delete ALL save
   data" dialog).

If a miss happens anyway, diagnose WHY (wrong coordinate space? stale
screenshot? game still transitioning?) and fix the tool or this skill —
do not just retry.

## Tools

- `tools/gridshot.ps1` — canvas-cropped screenshot with coordinate grid.
- `work/cmove.ps1` / `tools/cursorcap.ps1` — hover & cursor verification.
- `tools/cap.ps1 work/shot.png` — capture the game window (1606x1270).
  `-Keys "down,enter"` sends keys before capturing.
- **`work/cclick.ps1 -X <x> -Y <y>` — PREFERRED click tool: pass GAME
  CANVAS coordinates (0-800/0-600 vanilla, 0-1600/0-1200 HD). It adds the
  window frame offset (+3,+67 — measured via ClientToScreen) internally
  and calls click.ps1.**
  Use `-Scale` to multiply coords first.
- Screenshot images are displayed scaled (~0.637). To get canvas coords
  from a displayed image pixel: `canvas = displayed_px * 1.568 - (3,70)`.
  Better: measure the PNG file directly with PIL, then subtract (3,70).
- `work/click.ps1 -X <x> -Y <y>` — click at **PNG/WINDOW coordinates**
  (the same coordinate space as the captured shot.png). The script
  internally subtracts the titlebar+menu offset (~67px) itself, so always
  pass the position read directly from the screenshot — NOT client coords.
- IMPORTANT: screenshots returned by the read tool may be scaled down for
  display (e.g. shown as ~1034px wide). Multiply displayed coordinates by
  (1606 / displayed_width) to get real PNG coordinates before clicking.
- `work/drag.ps1` uses the same PNG/window coordinate space.
- `work/drag.ps1 -X1 <x> -Y1 <y> -X2 <x> -Y2 <y>` — drag (for save books
  and officer drag & drop).
- `work/holdctrl.ps1` — hold Ctrl to fast-skip ADV text.

## Reaching the battle formation screen (攻撃戦 隊列設定)

`はじめから` goes straight into the tutorial battle and SKIPS the formation
screen — always use the `つづきから` route below. NOTE: once `はじめから` is
chosen there is no way back to the title (the mode-select dialog cannot be
cancelled), so never click it by mistake.

1. Launch: `Start-Process game/Rance7.exe -WorkingDirectory game`
2. Wait ~14s for boot, then click anywhere (canvas 800,600) twice with
   ~5s gaps to pass the warning screens — do NOT click faster, rapid
   clicks misfire into wrong menus.
3. Title menu (canvas coords): `つづきから` = **(810, 998)**;
   `はじめから` = ~(810, 900) — never click it (cannot be cancelled).
4. LOAD screen: drag book `349` at PNG **(1000, 240)** → LOAD window PNG
   **(255, 290)** (use drag.ps1, which takes PNG coords).
5. Confirm dialog `はい` = canvas **(800, 660)** — the dialog has
   はい/いいえ buttons stacked; verify with cmove+cursorcap first, or
   simply press Enter (`cap.ps1 -Keys "enter"`) which is safest.
6. Map: the battleable enemy region is **アマゾン** (north of 南アフリカ,
   adjacent to own territory). 南アフリカ is NOT attackable.
   アマゾン ≈ canvas **(140, 880)** (verified by cmove+cursorcap — the
   teal region just north of the red 南アフリカ blob). Click it, then
   click the action menu item `合戦：魔軍と合戦（攻め込む）` ≈ canvas
   **(310, 28)** (verified).
7. Attack prep screen (攻撃戦): formation slots left, officer list right.
   - Drag an officer: ランス row PNG **(830, 295)** → slot PNG **(545, 915)**
     (canvas 827,228 → 542,848). IMPORTANT: the grab must start on the
     row's RIGHT side (部隊人数/行動 columns around PNG x830), NOT on the
     name column (~PNG x415) — grabbing the name does nothing. Also
     `cdrag.ps1` (canvas coords) has failed repeatedly even with
     cursor-verified endpoints; use `drag.ps1` (PNG coords) for this
     drag — it is the only variant that has actually placed an officer.
   - `斥候` (scout selection) button = canvas **(540, 585)** (verified
     via cursorcap; an earlier recorded value (522,668) was a
     display-scaled coordinate and missed below the button)
   - `決定` = canvas **(667, 610)** (button row at the bottom of the
     formation panel, right of 斥候; verified via cursorcap highlight).
     Click proceeds to the `対` screen, then click again for 合戦本編.

## Reaching the tutorial battle (はじめから route)

Only for checking the battle screen itself (no formation screen):
`はじめから` (810, ~900) → `通常モード` → `ゲームを始める` → hold Ctrl to
skip the prologue ADV → tutorial battle starts directly.

## Rebuild / deploy AIN

```powershell
python tools/ain_adv_patch.py game/Rance7.ain.orig work/Rance7_test.ain
# expected: "patched N, skipped 0"
# close the game before overwriting:
Get-Process Rance7 | Stop-Process -Force
Copy-Item work/Rance7_test.ain game/Rance7.ain -Force
```

## Vanilla navigation (verified working, PNG coords)

Vanilla content renders in the top-left 800x600 of the window; click.ps1
still takes PNG coords of the 1606x1270 window, so buttons are where they
appear in the screenshot.

1. Launch `game/Rance7.exe` (working dir `game/`), wait ~14s, click
   (800,600) twice ~5s apart to pass the warning screens.
2. Title menu `つづきから` = PNG **(408, 540)**.
   (`はじめから` is directly above at ~(408,488) — do NOT click it; it
   cannot be cancelled.)
3. LOAD screen: drag book `349` PNG **(502,142)** → LOAD window PNG
   **(128,158)**.
4. `はい` = PNG **(800, 696)** → national map loads.
5. On the map do NOT click the bottom-left buttons (`ターン終了` is at
   ~(65,265) PNG). The enemy region (red, bottom-left of the map itself)
   is around PNG **(53,330)** / **(40,455)**.
6. If the `ターンを終了しますか？` dialog appears, `いいえ` is at PNG
   **(675*1.55≈1050, 905)** — i.e. scale displayed coords ×1.553 to PNG.
7. Action menu `合戦：魔軍と合戦（攻め込む）` is the TOP item ≈ PNG
   **(400, 165)**. Picking `建設：次の合戦の準備` by mistake opens the
   参加武将選択（事前準備）screen instead — that is NOT the formation
   screen; close it with `閉` and re-pick the top item.
8. On the attack prep screen `斥候` ≈ PNG **(260, 402)** (half of the HD
   coords since canvas is 800x600).
9. Vanilla formation drag-and-drop was NOT automated reliably (the
   800x600 slot targets are small and every scripted drag/click missed).
   For vanilla reference shots, place officers manually or capture only
   screens before placement.

## Vanilla reference capture

To compare with the unpatched layout, swap BOTH the ain AND the GM ald —
swapping only the ain leaves HD-patched CGs under vanilla layout (or vice
versa: vanilla ALDs + patched ain gave a broken title with 1x logo and
truncated buttons). `*.hd_cur` files are the current HD builds,
`*.orig` the pristine ones (note `*.bak` files are NOT pristine):

```powershell
Copy-Item game/Rance7.ain game/Rance7.ain.hd_cur -Force
Copy-Item game/Rance7GM.ald game/Rance7GM.ald.hd_cur -Force
Copy-Item game/Rance7.ain.orig game/Rance7.ain -Force
Copy-Item game/Rance7GM.ald.orig game/Rance7GM.ald -Force
# ... capture ...
# restore afterwards
```

Vanilla content renders in the top-left 800x600 of the client; all click
coordinates above are for the HD build — halve them for vanilla navigation.

## Asset patching rules (do not forget)

- Always extract QNTs from `*.orig` archives, never from live/patched ones
  (re-upscaling an already-2x CG causes 4x — this happened before).
- After applying, run `tools/hd_audit.py`-style check: same/2x/4x counts;
  4x must be 0. Manifest of upscaled CGs: `work/upscaled.json`.
- `game/` contents are gitignored; tools/ needs `git add -f`.
