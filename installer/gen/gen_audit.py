# -*- coding: utf-8 -*-
"""Generation audit: regenerate every payload in installer/data from the
user's own ald sources and compare with the shipped bytes.

Per payload:
  vanilla/ -> NEAREST 2x of vanilla source (same as export_payload.py)
  shared|jp -> AI pipeline (ForgeNeo reproduction: BGR, tile 256/16,
               round8 resize, center crop-paste) + alpha (Lanczos 2x);
               NEAREST alpha is also compared for HYB detection.

Output: per-file match metrics (exact / psnr / mae / alpha mae) to JSON.
Mismatches = assets with undocumented post-processing or manual edits.

Usage:
    python work/gen_audit.py                 # all files (slow)
    python work/gen_audit.py --sample 200    # stratified estimate
    python work/gen_audit.py --only cg13314  # single file debug
"""

import argparse
import json
import math
import mmap
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import ald  # noqa: E402
import qnt_fast  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import onnxruntime as ort  # noqa: E402

MODEL = os.environ.get(
    'GEN_MODEL',
    os.path.join(ROOT, 'work/_spike/2x-AnimeSharpV4_Fast_RCAN_PU.onnx'))
OUT = os.path.join(ROOT, 'work/gen_audit_report.json')

SRC = {
    ('jp', 'GM'): 'jp/backup/hd_20261013_210614/Rance7GM.ald',
    ('jp', 'GA'): 'jp/backup/hd_20261013_210614/Rance7GA.ald',
    ('vanilla', 'GM'): 'vanilla/backup/hd_20261013_210235/Rance7GM.ald',
    ('vanilla', 'GA'): 'vanilla/backup/hd_20261013_210235/Rance7GA.ald',
}
DATA = os.environ.get('GEN_DATA', os.path.join(ROOT, 'installer/data'))
TILE, OV = 256, 16

_sess = None


def sess():
    global _sess
    if _sess is None:
        # Tiny per-tile ops gain nothing from ORT's default thread pools
        # (one pool per session, sized to the core count); with N worker
        # processes each spawning its own session that becomes a thread
        # storm. Keep them minimal.
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        _sess = ort.InferenceSession(
            MODEL, sess_options=so,
            providers=['DmlExecutionProvider', 'CPUExecutionProvider'])
    return _sess


def open_ald(path):
    f = open(path, 'rb')
    data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    return f, data


def entry_map(data):
    return {e[3]: (e[0], e[1], e[2]) for e in ald.list_entries(data) if e[3]}


def load_sources():
    """Open source ALDs. With GEN_SRC_DIR set, loads that directory's
    Rance7GM/GA.ald under the GEN_ASSET_SET key (install-time mode:
    the user's backed-up pristine archives are the only source)."""
    src_dir = os.environ.get('GEN_SRC_DIR')
    if src_dir:
        aset = os.environ.get('GEN_ASSET_SET', 'jp')
        src = {}
        for arch in ('GM', 'GA'):
            p = os.path.join(src_dir, 'Rance7%s.ald' % arch)
            if os.path.exists(p):
                src[(aset, arch)] = p
    else:
        src = {k: os.path.join(ROOT, p) for k, p in SRC.items()}
    alds = {}
    for k, p in src.items():
        f, data = open_ald(p)
        alds[k] = (f, data, entry_map(data))
    return alds


def src_payload(alds, name, variants):
    order = []
    for v in variants:
        order += [(v, 'GM'), (v, 'GA')]
    for k in order:
        if k in alds and name in alds[k][2]:
            _, data, m = alds[k]
            pos, hs, ds = m[name]
            return bytes(data[pos + hs:pos + hs + ds]), '%s/%s' % k
    return None, None


def to_img(payload):
    w, h, ch, px = qnt_fast.decode(payload)
    return Image.frombytes('RGBA' if ch == 4 else 'RGB', (w, h), px,
                           'raw', 'BGRA' if ch == 4 else 'BGR')


def infer_tile(arr, inp, s):
    a = np.asarray(arr, dtype=np.float32) / 255.0
    a = np.transpose(a[:, :, ::-1], (2, 0, 1))[None].astype(np.float16)
    out = s.run(None, {inp: a})[0][0]
    o = np.transpose(out, (1, 2, 0))[:, :, ::-1].copy()
    return Image.fromarray(np.clip(o * 255, 0, 255).astype(np.uint8), 'RGB')


def split_grid(image, tile_w, tile_h, overlap):
    """Verbatim port of modules.images.split_grid (ForgeNeo)."""
    w, h = image.size
    non_overlap_width = tile_w - overlap
    non_overlap_height = tile_h - overlap
    cols = math.ceil((w - overlap) / non_overlap_width)
    rows = math.ceil((h - overlap) / non_overlap_height)
    dx = (w - tile_w) / (cols - 1) if cols > 1 else 0
    dy = (h - tile_h) / (rows - 1) if rows > 1 else 0
    tiles = []
    for row in range(rows):
        row_images = []
        y = int(row * dy)
        if y + tile_h >= h:
            y = h - tile_h
        for col in range(cols):
            x = int(col * dx)
            if x + tile_w >= w:
                x = w - tile_w
            tile = image.crop((x, y, x + tile_w, y + tile_h))
            row_images.append([x, tile_w, tile])
        tiles.append([y, tile_h, row_images])
    return tiles


def combine_grid(tiles, tile_w, tile_h, image_w, image_h, overlap):
    """Verbatim port of modules.images.combine_grid (ForgeNeo)."""
    def make_mask_image(r):
        r = r * 255 / overlap
        r = r.astype(np.uint8)
        return Image.fromarray(r, "L")
    mask_w = make_mask_image(np.arange(overlap, dtype=np.float32)
                             .reshape((1, overlap)).repeat(tile_h, axis=0))
    mask_h = make_mask_image(np.arange(overlap, dtype=np.float32)
                             .reshape((overlap, 1)).repeat(image_w, axis=1))
    combined_image = Image.new("RGB", (image_w, image_h))
    for y, h, row in tiles:
        combined_row = Image.new("RGB", (image_w, h))
        for x, w, tile in row:
            if x == 0:
                combined_row.paste(tile, (0, 0))
                continue
            combined_row.paste(tile.crop((0, 0, overlap, h)), (x, 0),
                               mask=mask_w)
            combined_row.paste(tile.crop((overlap, 0, w, h)),
                               (x + overlap, 0))
        if y == 0:
            combined_image.paste(combined_row, (0, 0))
            continue
        combined_image.paste(
            combined_row.crop((0, 0, combined_row.width, overlap)),
            (0, y), mask=mask_h)
        combined_image.paste(
            combined_row.crop((0, overlap, combined_row.width, h)),
            (0, y + overlap))
    return combined_image


def model_up(im, batch=1):
    """Faithful reproduction of ForgeNeo upscale_with_model_cpu path.

    batch > 1 runs tiles through the ONNX session in batches (the model
    has dynamic batch dims; all tiles are 256x256 after split_grid's
    black padding). Output is identical to batch=1 apart from fp16
    scheduling noise.
    """
    w, h = im.size
    s = sess()
    inp = s.get_inputs()[0].name
    tiles = split_grid(im, TILE, TILE, OV)
    flat = [(ri, ci, t) for ri, (y, th, row) in enumerate(tiles)
            for ci, (x, tw, t) in enumerate(row)]
    if not flat:
        # ForgeNeo crashes here (scale_factor unbound -> HTTP 500), so
        # shipped bytes for sub-overlap images (<16px in a dimension)
        # came from another tool. Clean path: infer the whole image
        # directly; the ONNX pads internally. Crop to the 2x target.
        ut = infer_tile(np.asarray(im.convert('RGB')), inp, s)
        return ut.crop((0, 0, w * 2, h * 2)) if ut.size != (w * 2, h * 2)\
            else ut
    outs = {}
    for i in range(0, len(flat), batch):
        chunk = flat[i:i + batch]
        arrs = [np.asarray(t[2].convert('RGB'), np.float32) / 255.0
                for t in chunk]
        a = np.stack([np.transpose(x[:, :, ::-1], (2, 0, 1))
                      for x in arrs]).astype(np.float16)
        res = s.run(None, {inp: a})[0]
        for (ri, ci, _), o in zip(chunk, res):
            o = np.transpose(o, (1, 2, 0))[:, :, ::-1].copy()
            outs[(ri, ci)] = Image.fromarray(
                np.clip(o * 255, 0, 255).astype(np.uint8), 'RGB')
    newtiles = []
    scale_factor = 2
    for ri, (y, th, row) in enumerate(tiles):
        newrow = []
        for ci, (x, tw, tile) in enumerate(row):
            newrow.append([x * scale_factor, tw * scale_factor,
                           outs[(ri, ci)]])
        newtiles.append([y * scale_factor, th * scale_factor, newrow])
    return combine_grid(newtiles, TILE * scale_factor, TILE * scale_factor,
                        w * scale_factor, h * scale_factor, OV * scale_factor)


def forge_up(si):
    """Upscaler.upscale (round8) + postprocess (center crop-paste)."""
    W, H = si.size
    TW, TH = W * 2, H * 2
    out = model_up(si.convert('RGB'))
    dw = round(W * 2 / 8) * 8
    dh = round(H * 2 / 8) * 8
    if out.size != (dw, dh):
        out = out.resize((dw, dh), Image.LANCZOS)
    if (dw, dh) != (TW, TH):
        canvas = Image.new('RGB', (TW, TH))
        canvas.paste(out, (TW // 2 - dw // 2, TH // 2 - dh // 2))
        out = canvas
    return out


def nearest2x(si, want_alpha):
    mode = 'RGBA' if si.mode == 'RGBA' or want_alpha else 'RGB'
    return si.convert(mode).resize((si.width * 2, si.height * 2),
                                   Image.NEAREST)


def lanczos2x(si, want_alpha):
    mode = 'RGBA' if si.mode == 'RGBA' or want_alpha else 'RGB'
    return si.convert(mode).resize((si.width * 2, si.height * 2),
                                   Image.LANCZOS)


def metrics(a, b):
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    if x.shape != y.shape:
        return None
    mse = np.mean((x - y) ** 2)
    return {'psnr': 99.0 if mse == 0 else round(10 * np.log10(255 ** 2 / mse), 2),
            'mae': round(float(np.mean(np.abs(x - y))), 3),
            'exact': bool(np.array_equal(x, y))}


def audit_one(name, payload_path, alds):
    dst = open(payload_path, 'rb').read()
    variant = payload_path.split(os.sep)[-2]
    di = to_img(dst)
    want_alpha = di.mode == 'RGBA'

    if variant == 'vanilla':
        src, at = src_payload(alds, name, ['vanilla'])
        if src is None:
            return {'name': name, 'variant': variant, 'err': 'no src'}
        si = to_img(src)
        gen = nearest2x(si, want_alpha)
        r = metrics(gen.convert(di.mode), di)
        if r is None:
            return {'name': name, 'variant': variant, 'err': 'size mismatch'}
        r.update(name=name, variant=variant, recipe='nearest', src=at)
        return r

    if variant == 'jp':
        src, at = src_payload(alds, name, ['jp'])
    else:
        src, at = src_payload(alds, name, ['jp', 'vanilla'])
    if src is None:
        return {'name': name, 'variant': variant, 'err': 'no src'}
    si = to_img(src)

    for rname, fn in (('nearest', nearest2x), ('lanczos', lanczos2x)):
        g = fn(si, want_alpha)
        r = metrics(g.convert(di.mode), di)
        if r and r['psnr'] > 45:
            r.update(name=name, variant=variant, recipe=rname, src=at)
            return r

    rgb_ai = forge_up(si)
    if want_alpha and si.mode == 'RGBA':
        sa = si.getchannel('A')
        a_lan = sa.resize(di.size, Image.LANCZOS)
        a_nea = sa.resize(di.size, Image.NEAREST)
        da = np.asarray(di.getchannel('A'), dtype=np.int32)
        r = metrics(rgb_ai, di.convert('RGB'))
        if r is None:
            return {'name': name, 'variant': variant, 'err': 'size mismatch'}
        # Visible-region metrics: RGB under transparent pixels is not
        # rendered, so weight the comparison by shipped alpha (dilated
        # slightly to include anti-aliased edges).
        from scipy.ndimage import binary_dilation
        vis = binary_dilation(da > 0, iterations=2)
        if vis.any():
            xd = np.asarray(rgb_ai, np.float64)
            yd = np.asarray(di.convert('RGB'), np.float64)
            mse_v = float(np.mean((xd[vis] - yd[vis]) ** 2))
            r['psnr_vis'] = (99.0 if mse_v == 0
                             else round(10 * np.log10(255 ** 2 / mse_v), 2))
            r['mae_vis'] = round(float(np.mean(np.abs(xd[vis] - yd[vis]))), 3)
        r.update(name=name, variant=variant, recipe='ai',
                 alpha_lanczos_mae=round(float(np.abs(
                     np.asarray(a_lan, np.int32) - da).mean()), 3),
                 alpha_nearest_mae=round(float(np.abs(
                     np.asarray(a_nea, np.int32) - da).mean()), 3), src=at)
        return r

    r = metrics(rgb_ai.convert(di.mode), di)
    if r is None:
        return {'name': name, 'variant': variant, 'err': 'size mismatch'}
    r.update(name=name, variant=variant, recipe='ai', src=at)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=0)
    ap.add_argument('--only', default=None)
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--shard', default=None,
                    help='i,n -> audit jobs where index%%n==i')
    args = ap.parse_args()

    alds = load_sources()
    jobs = []
    for arch in ('GM', 'GA'):
        for var in ('shared', 'jp', 'vanilla'):
            d = os.path.join(DATA, arch, var)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith('.qnt'):
                    jobs.append((fn, os.path.join(d, fn), arch))
    if args.only:
        jobs = [j for j in jobs if j[0].startswith(args.only)]
    elif args.sample:
        import random
        random.Random(1).shuffle(jobs)
        jobs = jobs[:args.sample]
    if args.shard:
        i, nsh = (int(x) for x in args.shard.split(','))
        jobs = [j for k, j in enumerate(jobs) if k % nsh == i]
    print(f'{len(jobs)} files to audit')

    # resume: reuse rows already present in args.out
    done = {}
    if os.path.exists(args.out):
        try:
            for r in json.load(open(args.out, encoding='utf-8')):
                done[(r.get('arch'), r.get('variant'),
                      r.get('name'))] = r
        except Exception:
            pass

    report = list(done.values())
    n = 0
    for name, path, arch in jobs:
        var = path.split(os.sep)[-2]
        if (arch, var, name) in done:
            continue
        try:
            r = audit_one(name, path, alds)
        except Exception as e:
            r = {'name': name, 'err': repr(e)}
        r.setdefault('variant', var)
        r.setdefault('arch', arch)
        report.append(r)
        n += 1
        if n % 50 == 0:
            json.dump(report, open(args.out, 'w'), ensure_ascii=False,
                      indent=1)
            ok = sum(1 for x in report
                     if x.get('psnr_vis', x.get('psnr', 0)) > 40)
            print(f'{len(report)}/{len(jobs)} audited, psnr>40: {ok}',
                  flush=True)

    json.dump(report, open(args.out, 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    buck = Counter()
    for r in report:
        if 'err' in r:
            buck['err'] += 1
            continue
        p = r.get('psnr_vis', r.get('psnr', 0))
        if r.get('exact'):
            buck['exact'] += 1
        elif p > 45:
            buck['psnr>45'] += 1
        elif p > 35:
            buck['psnr35-45'] += 1
        else:
            buck['low'] += 1
    print(dict(buck), '->', args.out)


if __name__ == '__main__':
    main()
