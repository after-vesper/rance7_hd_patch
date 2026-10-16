# Generation-at-install pipeline (experimental)

Goal: shrink the distributed patch (~2.7 GB of shipped payloads) by
regenerating HD assets from the user's own game resources at install
time. The installer then contains only the inference model, a small
runtime, recipe metadata, and a handful of exception payloads.

Acceptance policy (agreed): *equivalent visual quality*, not bit
identity. Final judgement is a manual in-game visual pass; assets that
cannot be regenerated acceptably ship as small exception payloads.

## Why a clean pipeline, not Forge-faithful

The archived assets were produced by ForgeNeo (`Upscaler.upscale` +
`extra-single-image` API). Faithful reproduction (kept in
`work/gen_audit.py` for auditing) requires reproducing three quirks:

1. output resampled to `round(w*2/8)*8` (Lanczos), then
2. center-pasted onto the target canvas — leaving **real black bands**
   on 83.7% of all assets (any source whose 2x dims are not mod-8), and
3. 256px tiles with 16px ramp blending; images smaller than the tile
   get negative crop coords → black-padded model input.

For production generation, `work/gen_recipes.py` uses `BASE_MODE='clean'`
= `model_up()` alone (exact 2x, no resample, no black bands). This is
strictly better than the shipped assets while staying visually
equivalent everywhere else.

## Components (all under work/, gitignored scratch)

| file | role |
|---|---|
| `work/gen_audit.py` | source ALD access, ONNX session (DML+CPU), `split_grid`/`combine_grid` verbatim ports, `model_up` (clean, batched), `forge_up` (quirks, for auditing), `metrics`/`audit_one` |
| `work/gen_recipes.py` | post-process recipes: `nearest`, `ai`, `ai_nearest_alpha`, `ai_alpha_clamp`, `padded_ai`, `component_revert`, `component_revert_aex`, `hybrid_clamp`, `baked_text`, `unblended_fringe`, `manual` |
| `work/recipe_manifest.json` | per-payload recipe assignment (`{arch}/{variant}/{name}.QNT` → recipe), built by `work/build_recipe_manifest.py` from `docs/cg_map.md` + `work/_fix_alpha.py` lists |
| `work/gen_payload.py` | generation driver: payload → recipe → source decode → PNG + manifest.json for `tools/hdpatch.py repack` |
| `work/gen_compare.py` | side-by-side sheets (generated vs shipped, checkerboard alpha) → `work/review/` for visual triage |
| `work/classify_audit.py` | classifies `gen_audit_full.json` rows vs manifest (exact/match/near/known_recipe/unexplained/error) |

## Source selection rules (verified)

- `installer/data/*/vanilla/*` payloads → vanilla source ALD
- `installer/data/*/jp/*` payloads → jp source ALD
- `installer/data/*/shared/*` payloads → either; the 485 sources that
  differ between jp and vanilla map **exclusively** to jp/vanilla
  variants, never to shared. Shared sources are identical in both.
- Sources always come from pristine archives (`*.orig` / `backup/`),
  never from an already-patched install (would double-upscale).

## Inference

- Model: AnimeJaNai HD V3 Sharp1 UltraCompact (425k) fp16 ONNX
  (~600 KB, dynamic batch+dims) — the same model used for the OP/ED
  movie upscale. License CC BY-NC-SA 4.0 — OK for a free
  non-commercial patch with credit; never for a paid product.
  Earlier rev used AnimeJaNai V2 SuperUltraCompact (100k, ~94 KB):
  equivalent in-game quality at ~1.5-2x the throughput; the 425k model
  was adopted for quality since whole-frame inference keeps the
  pipeline fast regardless.
- Runtime: onnxruntime + DirectML (GPU) or CPU. Deterministic; CPU and
  DML outputs differ only at fp16 rounding level.
- Whole-frame first (2026-10-15): the model's dynamic HxW lets any
  input under `WHOLE_MAX_SIDE`/`WHOLE_MAX_PX` (2048 px / 4 MP) run as a
  single inference via `gen_audit.infer_*` — every payload qualifies
  (largest source is 800x1200), so the 256px tile grid is now only a
  fallback for oversized inputs. Whole-frame vs tiled on the dev
  machine: 800x1200 in 140 ms vs 476 ms, 1600x600 in 125 ms vs 503 ms,
  and the ~34,000 tile batch collapses to ~6,600 single inferences.
  Post-processing runs in fp32 throughout — numpy fp16 elementwise math
  is software-emulated and cost more than the inference itself.
  The same inference core backs `gen_ring.py`/`gen_fast.py` (assets),
  `gen_alk.py` (logo frames via `model_up`) and `work/upscale_alm.py`
  (OP/ED movies via `infer_planes`).
- Tile fallback: inputs above the cap still use `split_grid` 256x256
  tiles; `model_up(batch=N)` batches them, N calibrated at startup
  (4/8/16) per machine.

### Architecture (gen_ring.py, current)

Each worker process owns whole jobs end-to-end and keeps its own ONNX
session — no tile data crosses process boundaries:

```
worker: decode source -> infer on local session (whole-frame;
        256px tile grid only above the 2048px/4MP cap)
        -> recipe postproc -> encode QNT/AJP -> write
```

Key decisions, all measured on the dev machine:

- **Per-worker sessions, no central GPU queue.** A single-session +
  IPC design starved at ~55 tiles/s because the main process had to
  transpose/clip/astype/pickle every tile serially. In-process GPU
  submission avoids that entirely.
- **Concurrency is bounded on both sides.** Worker count scales with
  CPU cores (decode/encode dominate: ~200-300 ms CPU vs ~15-50 ms GPU
  per whole-frame job), while a cross-process semaphore caps
  simultaneous DirectML runs at 4 — beyond that, concurrent
  dynamic-shape sessions degrade sharply even though the same sessions
  idle harmlessly.
- **Serial workers (FIN_THREADS=0).** Per-process finisher threads
  contend on the GIL: threaded finish ran ~3x slower than finishing
  inline. Parallelism comes from process count, not threads.
- **PENDING_MAX=8** in-flight jobs per worker caps fp16/raw buffers;
  12 workers x 24 slots previously exhausted host commit memory
  (`bad allocation` / `MemoryError` storms). An inference semaphore +
  single retry absorbs transient DML allocation failures.
- **NumPy QNT codec** (`qnt_fast.py`): vectorized encode and a
  wavefront-vectorized decode (~5x vs the pure-Python `qnt.decode`,
  byte-identical on 60 mixed-shape fixtures). zlib level is tunable
  via `GEN_QNT_LEVEL` (default 3); an experimental pigz-style
  parallel-deflate path exists but loses to serial on many-core hosts
  (thread oversubscription) — keep it for low-core machines.
- **ORT session threads clamped** in `gen_audit.py` so 20 sessions
  don't each spawn a logical-core-sized thread pool.

### Performance history (dev machine: 24 cores, 8 GB VRAM, RTX 3070 Ti)

| approach | wall time | note |
|---|---|---|
| single process (`gen_payload.py`) | ~2 h | CPU-bound; GPU ~18% |
| 4-shard / 8-worker pool | ~85 min | 16 workers OOM: 16 ORT sessions exhaust VRAM |
| `gen_ring.py` v1 (serial finisher, RCAN) | 48 min | GPU 12.1 tiles/s — starved by per-worker serial reassemble+save |
| `gen_ring.py` central-session + IPC (suc_v2) | ~25 min | GPU 53 tiles/s — main-process per-tile postproc is the wall |
| `gen_ring.py` per-worker sessions (suc_v2) | ~7 min (600-file subset 15-18/s) | GPU ~257 tiles/s aggregate; serial workers + batched u8 + zlib lv3 |
| full install run (6,612 payloads, suc_v2) | ~2-3 min generate | cache-hit re-install ~45 s |
| whole-frame + 425k model (2026-10-15) | ~21-22 jobs/s steady state | CPU-bound: decode+qnt encode ~250-350 ms/job across workers; GPU no longer the wall (whole-frame ≈15-50 ms/job). Same-shape batching of jobs was tried and reverted — with CPU the bottleneck it only added queueing overhead |

## Known gap classes (audit categories)

- `manual` (3 assets: cg10132, cg10701 jp+vanilla) — hand-edited; ship
  as exception payloads (~3.2 MB total).
- Small unexplained residuals — a handful of tiny sprites whose shipped
  bytes match neither ONNX nor any local model output (made with an
  unidentified tool/version). Visually near-identical; user triage.
- AJP payloads (161) — same recipes apply; repack re-encodes JPEG q95
  with PM alpha mask, so they are never bit-exact anyway.

## Post-review recipe corrections (user triage round 1)

User visual review of `work/review/` sheets surfaced real bugs; all fixed
by evidence-based reassignment (best-of-4 recipe score per asset):

- `padded_ai` alpha bug: RGB model output was wrapped with `convert('RGBA')`,
  stamping alpha=255 everywhere — soft edges and semi-transparent borders
  were lost. Fixed: restore source alpha resized 2x (Lanczos) onto AI RGB.
- `padded_ai` was over-assigned: of the 85 tagged assets, measured output
  shows only ~26 were actually padded (the cg10551-569 series scores ~56 dB).
  The rest were plain `ai` (33), `lanczos` (22), or `nearest` (4) —
  per-asset best recipe is now assigned from measured scores.
- `cg10178/179/10078` (tiny sprites from an unidentified tool): `lanczos`
  is the closest available recipe and visually near-identical.
- Tiny-sprite black output (`cg10196-198`): `model_up` now falls back to
  whole-image inference when `split_grid` yields no tiles (<16px edges).
- `cg10013` green fringe / `cg10217` thick border / `cg10505` yellow ring:
  all resolved by the alpha fix + recipe reassignment.
- Remaining different-tool candidates (best recipe still <20 dB):
  cg10013, cg10041-45, cg10159-170, cg10207/215/219/221/227, cg12505 —
  kept on best-effort recipes pending in-game check; all are tiny so
  exception payloads would cost <100 KB total.

## Installer integration (implemented)

Release tree (`ci/build_release.py` → `release/SengokuRance_HDPatch/`,
~248 MB uncompressed vs 2.7 GB shipped):

| dir | contents |
|---|---|
| `runtime/` | embeddable Python 3.10 + numpy/Pillow/scipy(trimmed)/onnxruntime-directml (~190 MB) |
| `gen/` | generation scripts + `model.onnx` (~94 KB) + `recipe_manifest.json` + `alk_recipes.json` |
| `data/` | `manifest.json` + `hd_sites.json` only — zero binary payloads |
| `HdPatch.cs`, `Install.ps1`, `bin/` | unchanged patch engine + alice.exe |

Install flow (Install.ps1):
1. `gen_ring.py --emit-qnt` on the embedded runtime — generates
   shared+assetSet payloads as final QNT/AJP bytes from the user's
   backed-up archives (runs before any file is modified; a failure
   leaves the install untouched).
2. `gen_alk.py` regenerates `AliceLogo3.alk` from the user's backed-up
   original: each of the 80 non-empty QNT entries is decoded, upscaled
   2x with its audited recipe (`gen/alk_recipes.json`: ai/padded_ai/
   lanczos/nearest), re-encoded, and repacked as ALK0. Empty
   (size=0, "same as next") entries are preserved verbatim.
   `DLL\AliceLogo3.dll` is likewise produced at install time: the
   shipped binary equals the user's original plugin with two
   800x600->1600x1200 constants patched (8 bytes at 0x1312/0x131c/
   0x20d2c/0x20d30), so the installer byte-patches the backed-up DLL
   (byte-identical to the previously shipped file).
3. AIN patch, then `RepackAld` consumes `data/` (exceptions) + gen dirs.
4. `manifest.json` file copies prefer generated output over `data/files/`
   (this is how the generated AliceLogo3.alk and patched DLL land in
   the game dir).
5. The ~2.5 GB intermediate dir is deleted after repack.

`gen_ring.py` install-mode env/args: `--src-dir` (backup ALDs),
`--asset-set`, `--model`, `--manifest`, `--data`, `--emit-qnt`.
Self-tuning per machine: batch-size calibration, auto worker count
(scaled for the serial-worker design, capped by available commit
memory), CPU-provider warning. Env knobs: `GEN_QNT_LEVEL` (zlib
level, default 3), `GEN_FIN_THREADS` (per-worker finisher threads,
default 0 = serial), `GEN_STATS` (per-stage timing summary).

## Status

- [x] Forge pipeline fully reproduced (verified bit-exact vs live API)
- [x] recipe manifest covers all 7,098 payloads
- [x] repack round-trip verified bit-exact (PNG→QNT→ALD→decode)
- [x] generation driver + visual triage sheets working
- [x] full audit classification (6,937 payloads; 98%+ explained/equivalent)
- [x] user triage round 1 → padded alpha fix + 62 recipe reassignments
- [x] full payload generation (7,098 assets) + repack into game ALDs
- [x] repack_gen.py validated byte-identical vs shipped C# RepackAld
- [x] smoke test: game boots to main map, UI/CG render correctly
- [x] `work/gen_ring.py`: single-session GPU + multi-process
  producer/consumer pipeline; full run 48 min with 0 errors
- [ ] in-game visual triage → final exception list
- [x] installer packaging (embedded python runtime; release tree builds
  and generates standalone)
- [x] AliceLogo3.alk install-time regeneration (80 entries, per-entry
  audited recipes; verified vs shipped archive + in-game logo playback)
- [ ] end-to-end install dry-run on a pristine copy of the game

## Deployment notes (dev build)

- `work/repack_gen.py` is a faithful Python port of `HdPatch.RepackAld`
  including the moved GM->GA link-row redirect. Validated byte-identical
  against the shipped C# implementation for both archives.
- Quirk replicated: Install.ps1's `@(0, $gaOrig.Count + $i)` array-
  concatenates instead of adding, so all 694 moved rows point at the
  first appended GA entry. Verified harmless in practice (the rows are
  never consulted), kept for byte parity.
  (Fixed in v2.2: the zh build's redirect rows ARE consulted, so both
  paths now write the real appended index.)
- Generated build replaces `game/Rance7GM.ald` (1.98 GB, under the
  0x80000000 limit) and `game/Rance7GA.ald` (1.10 GB, 794 entries =
  100 orig + 694 appended). Pre-swap copies kept as `*.ald.pre_gen`.
- Install.ps1 additionally rebalances at install time: after generation it
  projects the resulting GM size; if it would exceed ~0x7F000000 the largest
  GM payloads are moved into the GA payload dirs before repacking, and the
  existing moved-row logic redirects their link rows. The GM slots keep the
  original 1x data (dead weight, never consulted), so net shrink =
  generated_size - original_size per moved file. A post-repack assertion
  aborts the install if either volume still ends at/above 0x80000000.
  Needed because higher-frequency models (e.g. AnimeJaNai suc_v2) compress
  worse and can push GM past the engine's signed int32 seek boundary.

## zh (Simplified Chinese) build support

The MangaGamer zh build has a reversed archive layout. `Rance7GA.ald`
is the live CG archive and carries the authoritative link table
(fn 0..64084, zero-based: row index = numeric name - 1, pointing at
GA itself for CG and at disk 1 = GB for the cg045xx set).
`Rance7GB.ald` holds the 100 cg045xx entries (en-GA equivalent, footer
still self-declares disk 0). `Rance7GM.ald` is a dormant en-heritage
duplicate — a magenta-marker swap test confirmed it is not read at
boot/title/gallery/staff screens, so it is left untouched (operational
assumption based on tested paths, not a proof for every late-game path).

- Generation: `--asset-set zh` enumerates every entry of the live
  backup archives (GA+GB) instead of the recipe-manifest key set —
  this also covers zh-only screens (cg59001/59002 warning text) that
  have no recipe entry; they fall back to the `ai` recipe. Recipes for
  shared names are resolved with vanilla > shared > jp preference.
- QNT v1: zh GA holds 173 v1 payloads (v2 identical algorithm — the
  version check in qnt.py/qnt_fast.py now accepts both).
- Format dispatch is by magic bytes, not extension: 13 zh `.AJP`
  entries actually contain QNT data.
- Repack: GA and GB only; `noAppend` keeps each archive's entry set
  fixed. GA payloads would exceed the 0x80000000 seek ceiling, so the
  largest staged payloads are moved to GB (appended) and GA's link
  table gets redirect rows (fn -> disk 1, appended GB index), mirroring
  the jp GM->GA mechanism. GB is repacked first so append order is
  deterministic (ordinal name sort, same as RepackAld's `added` list).
- Footer count: the NL footer stores the packer's entry count, which
  for zh GA counts the duplicated `cg59001.QNT` name once; RepackAld
  now preserves `original_count + added` rather than `files.Count`.
- AliceLogo2.alk (46 entries, ALK0, all image frames QNT v2) is
  regenerated by the same generic gen_alk.py path; `AliceLogo2.dll`
  gets the same two 800x600->1600x1200 constant pairs at
  0x11b8/0x11c2 (code) and 0x1cbd4/0x1cbd8 (data).
- Movies: `movie/*.alm` are glob-enumerated, which also picks up the
  zh-only `Rance7ED.alm`.
- AIN: zh sha256 BF84072AAD157812... resolves 2943/2944 sites with the
  shared hd_sites.json (71 ambiguous / 13 missing-func sites skipped,
  same class of known gaps as vanilla).
- Uninstall restores whatever the timestamped backup actually contains
  (recursive), so zh-specific files (GB, AliceLogo2.*, ED.alm) roll
  back without a hardcoded list.

## English (Kagura Steam) edition

AIN sha256 `A6B3693708144241...` — Kagura's localisation recompiled the
message/UI functions, so the shared jp site set is not used. Instead
`installer/data/hd_sites_en.json` (produced by `tools/en_export_sites.py`,
which re-anchors every jp site inside the en function bodies via
opcode-sequence alignment) resolves ~3190 sites with zero relaxed
fallbacks; the remaining unmappable sites are listed in
`work/en_review.json` for manual review. Sites unique to the en build
(no jp counterpart — e.g. `tagBattleNumberCollection`, the
`tagBattleBar@setTransparency` fade) plus constants swallowed by the
array-index guard are added as manual entries in `en_export_sites.py`. Asset sources come from the `vanilla` manifest set —
en GM's contents are byte-identical to zh's all-ages CG set.

There is no AliceLogo plugin in the en build; those steps skip
naturally. Movies use the same glob path, but the rebuilt
`DLL/PlayMovie.dll` cannot render MPEG-1 wider than ~1184 px — the
installer zeroes its VMR-7 CLSID so the graph falls back to VMR-9/EVR
(see docs/movie_upscale.md). If the pattern is absent the movies are
capped via `gen_movie.py --max-width 1152` instead. The en sys-data
file is `SaveData/Rance7_Sys.ASD` (the OP prolog flag lives there;
`戦国ランス_Sys.ASD` also exists).
