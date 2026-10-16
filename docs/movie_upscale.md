# Movie upscale feasibility (OP / ED)

Investigated 2026-10-15. Conclusion: **feasible, verified on the real
engine**. Both movies can be replaced with AI-upscaled re-encodes without
any ain/DLL changes.

## File format

`game/movie/` contains:

| File | Size | Content |
|---|---|---|
| `Rance7OP.alm` | 177 MB | OP, 2:50.59 |
| `Staff.alm` | 149 MB | ED (staff roll), 2:23.16 |

`.alm` is a plain **MPEG-PS** container with an AliceSoft extension:

- Video: `mpeg1video`, 640x480, 29.97 fps, ~8000 kbps
- Audio: `mp2`, 48000 Hz stereo, 192 kbps
- Stream IDs 0x1e0 / 0x1c0, VCD-style pack+padding layout
  (reproduced by `ffmpeg -f vcd`)

## Playback path

`ムービー再生` (FUNC 4504) -> `PlayMovie` HLL (`DLL/PlayMovie.dll`) ->
DirectShow. Disassembly of PlayMovie.dll shows:

- `CoCreateInstance` (Filter Graph), `RenderFile` on the `movie\*.alm` path
- `IVideoWindow::put_Owner` = game window, then `GetClientRect` +
  `IVideoWindow::SetWindowPosition` -> **video is always stretched to fill
  the client area regardless of its native resolution**
- xsystem4 implements the same HLL via pl_mpeg (MPEG-1 only) and also
  stretches the frame to the view.

Because the renderer scales anyway, raising the encoded resolution is a
pure asset change.

## Verified compatibility matrix (real `Rance7.exe`)

| Encode | Result |
|---|---|
| mpeg1video 1280x960 @12Mbps + mp2 copy, `-f vcd` | **plays, full-screen** |
| h264/aac in .mp4 renamed to .alm | `Load` fails (Sys42VM error dialog) |
| mpeg2video 1280x960 + mp2, `-f dvd` | audio plays, video black |

So the shipped encode must stay **mpeg1video + mp2 in MPEG-PS**.
MPEG-1 accepts arbitrary frame sizes, so 1280x960 (2x) works; 1600x1200
is also divisible by 16 and should work (untested).

## Pilot results (2026-10-15)

Segment OP 60s-80s (character cards), 602 frames:

- First encode (`-q:v` VBR, `-bf 2`, no VBV) **stuttered and tore
  in-game**. Root cause found in the original stream's sequence header:
  the stock video is CBR 8 Mbps, VBV ~304 KB, GOP16 of only I/P frames
  (IPPPP..., **no B-frames**). The old DirectShow MPEG decoder cannot
  keep up with bursty VBR + B-frame reordering.
- Re-encoding with the original's profile — CBR, `-bufsize`, `-g 16`,
  `-bf 0` — at 1280x960 **plays perfectly smooth, no tearing**
  (user-verified in-game).
- Original sequence header: w=640 h=480 fps_code=4 (29.97) bitrate 8.0M
  vbv=152×16Kbit (304KB) GOP `IP`*16.

## Production run (2026-10-15)

`work/upscale_alm.py` streams decode → ONNX whole-frame 2x → encode with
no intermediate PNGs. The inference itself is the shared
`gen_audit.infer_planes` core — the same code path that upscales ALD
assets and `AliceLogo3.alk` frames, so all three upscale workloads run
on one mechanism:

- Model input accepts dynamic H×W — feeding the whole 640x480 frame is
  **~23x faster than 256px tiling** and pixel-identical (max diff 1).
  Model inference ~15 ms/frame (65 fps) on ORT DirectML.
- numpy postprocess must be fp32 (fp16 elementwise math is CPU-emulated,
  ~80 ms → ~11 ms). Output written as planar `gbrp` (no transpose).
- Effective throughput **~32 fps** → OP 5113 frames in 160 s,
  ED 4290 frames in 128 s.
- Command: `python work/upscale_alm.py src.alm out.alm` (12 Mbps CBR,
  `-bufsize 3600k`, GOP16, no B-frames, `-f vcd`, mp2 audio copied).
- Results: `Rance7OP_hd.alm` 252 MB / `Staff_hd.alm` 198 MB
  (originals 177/149 MB). Both verified playing in `Rance7.exe`
  (OP autostart test; ED verified by swapping it in as Rance7OP.alm).

## Installer integration (2026-10-15)

Movies follow the same generation-at-install philosophy as the ALD/ALK
payloads — nothing derived is shipped; each user's own originals are
regenerated during `Install.ps1`:

- `installer/gen/gen_movie.py` — reads `backup\hd_*\movie\*.alm` (the
  timestamped originals) and writes HD copies into the temp generation
  dir (`hd_gen_*\files\movie\`), which `Install.ps1` then copies into
  `game\movie\`. Runs before any game file is replaced, so a failure is
  non-fatal: the originals simply stay in place (warn + continue).
- `installer/bin/ffmpeg.exe` — static build provisioned by
  `ci/provision_runtime.ps1` from the `imageio-ffmpeg==0.5.1` wheel
  (ffmpeg 4.2.2, ~64 MB). Verified to contain mpeg1video encoder, mp2
  codec, and the `vcd` muxer the profile requires. Missing binary →
  movies are skipped, install continues.
- Encode profile is identical to the verified run: mpeg1video
  1280x960, 29.97 fps (probed per source), 12 Mbps CBR, `-bufsize 3600k`,
  GOP16, no B-frames, mp2 copied, `-f vcd`.
- Whole-output cache in `hd_cache` (key = gen version + model sha +
  source sha) so re-installs skip the ~5 min generation.
- `Uninstall.ps1` restores `movie\Rance7OP.alm` and `movie\Staff.alm`
  from the selected backup with the same hash verification as the other
  files; backups made by older installer versions (no `movie\` dir) are
  handled by the existing `Test-Path` guard.
- Movies are deliberately NOT listed in `data\manifest.json`: they are
  optional payloads, and the manifest copy loop hard-fails on a missing
  source. The dedicated copy block in `Install.ps1` only installs what
  generation produced.

## Production pipeline (proposal)

1. `ffmpeg -i movie\Rance7OP.alm frames/%06d.png` (~5100 frames OP,
   ~4300 frames ED)
2. Upscale each frame 2x with the existing models
   (`work/_models/*.onnx` / `tools/forge_upscale.py` API path)
3. Re-encode:
   `ffmpeg -framerate 30000/1001 -i hd/%06d.png -i orig.alm -map 0:v -map 1:a \
    -c:v mpeg1video -b:v <TBD> -maxrate ... -bufsize ... -c:a copy -f vcd out.alm`
4. Verify: `ffprobe` (mpeg1video, 1280x960, 29.97, mp2 48k stereo),
   then in-game playback test.

Bitrate trade-off: the source is 8 Mbps at 640x480. AI-upscaled anime
content at 1280x960 needs roughly 8-14 Mbps; a 2-pass or `-q:v` VBR
encode should be tuned by eyeballing short segments. Expect each movie
to land in the ~150-300 MB range (the original two total 326 MB).

## English (Kagura) build — VMR-7 width limit

The Kagura Steam release ships a **rebuilt** `DLL/PlayMovie.dll`
(128 KB, "PlayMovieNew") unlike the stock 49 KB player. It creates the
first available renderer in `VMR-7 -> VMR-9 -> EVR` order and connects
the video pin with `RenderEx(AM_RENDEREX_RENDERTOEXISTINGRENDERERS)`.

Observed on Windows 11 (verified 2026-10-15 by binary bisection):

| Encode | Result |
|---|---|
| mpeg1video 1152x864 / 1184x888, `-f vcd` | plays, full-screen |
| mpeg1video 1192x894 and wider | audio only, black video |
| original 640x480 re-encoded (same profile) | plays |
| wmv2+wmav2 `.asf` renamed to .alm, 1280x960 | plays but raises a "Playback error." dialog mid-play |

So the VMR-7 windowless path silently fails to present frames wider
than **~1184 px** (74 macroblocks); height and total MB count don't
matter. The system MPEG-1 decoder itself is fine (Windows Media Player
plays the same 1280x960 file via EVR).

**Fix shipped in the installer:** zero the VMR-7 CLSID
(`B87BEB7B-8D29-423F-AE4D-6582C10175AC`, found by byte-pattern, must
occur exactly once) inside the backed-up `DLL\PlayMovie.dll`. Its
`CoCreateInstance` then fails and the player falls through to VMR-9,
which renders 1280x960 correctly. If the pattern is missing (different
PlayMovie build), `gen_movie.py --max-width 1152` caps the encode as a
safe fallback. The DLL is backed up and restored by Uninstall like any
other patched file.

## How to trigger playback for testing

- OP auto-plays at startup when the `ＯＰ見た` flag (in
  `SaveData/戦国ランス_Sys.ASD`) is unset. Temporarily move the file aside,
  launch, capture, restore. The game recreates a stub on exit — always
  restore the backup afterwards.
- ED/OP can also be replayed from the mansion CG gallery
  (`tagCgMode@execCg`, nCgNo 99991 = OP, 99992 = ED).
- xsystem4 plays the same file via pl_mpeg; useful for a quick decode
  sanity check but not a substitute for the real engine.
