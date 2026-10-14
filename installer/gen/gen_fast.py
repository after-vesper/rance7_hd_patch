# -*- coding: utf-8 -*-
"""Pipelined payload generator: keeps the GPU inference thread saturated.

Pipeline:
  producer threads  : decode source QNT/AJP, build model input image
                      (source or padded canvas), split into tiles,
                      preprocess to fp16 CHW -> tile queue
  gpu thread        : batch up to 16 tiles (DML sweet spot; >32 collapses),
                      run ONNX session, push results
  finisher threads  : combine_grid -> recipe postproc -> write PNG

Non-AI recipes (nearest/lanczos/manual) bypass the GPU entirely.
"""

import argparse
import json
import math
import os
import struct
import sys
import threading
import time
from queue import Queue, Empty, Full
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'work'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import gen_audit as ga  # noqa: E402
import gen_recipes as gr  # noqa: E402
import ajp  # noqa: E402

TILE, OV = ga.TILE, ga.OV
BATCH = 16            # DML throughput peaks ~29 tiles/s at batch 8-16
INQ_MAX = 256
N_PRODUCERS = 6
N_FINISHERS = 4

NO_GPU = {'nearest', 'lanczos', 'manual'}

# job states live here; guarded by results_lock
jobs = {}
results_lock = threading.Lock()
tile_q = Queue(maxsize=INQ_MAX)
done_q = Queue()


def prepare_tiles(im):
    """numpy fast-path equivalent of split_grid + fp16 preprocessing.

    Returns (tiles_meta, list of (flat_idx, fp16 array)).
    tiles_meta = [[y, th, [[x, tw], ...]], ...] matching split_grid layout.
    Out-of-bounds regions are black (PIL crop pad semantics).
    """
    w, h = im.size
    src = np.asarray(im.convert('RGB'))
    non = TILE - OV
    cols = math.ceil((w - OV) / non)
    rows = math.ceil((h - OV) / non)
    dx = (w - TILE) / (cols - 1) if cols > 1 else 0
    dy = (h - TILE) / (rows - 1) if rows > 1 else 0
    coords = []
    for row in range(rows):
        y = int(row * dy)
        if y + TILE >= h:
            y = h - TILE
        for col in range(cols):
            x = int(col * dx)
            if x + TILE >= w:
                x = w - TILE
            coords.append((x, y))
    # pad the source once so every tile is a plain slice (OOB -> black)
    x0 = min(0, min(c[0] for c in coords))
    y0 = min(0, min(c[1] for c in coords))
    x1 = max(w, max(c[0] + TILE for c in coords))
    y1 = max(h, max(c[1] + TILE for c in coords))
    big = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    big[-y0:h - y0, -x0:w - x0] = src
    tiles_meta = {}
    items = []
    for i, (x, y) in enumerate(coords):
        t = big[y - y0:y - y0 + TILE, x - x0:x - x0 + TILE]
        arr = np.transpose(
            t[:, :, ::-1].astype(np.float32) / 255.0,
            (2, 0, 1)).astype(np.float16)
        items.append((i, arr))
        tiles_meta[i] = (x, y)
    return tiles_meta, items


def combine(tiles_meta, outs, w, h):
    """PIL combine_grid equivalent with precomputed coords."""
    TW, TH = TILE * 2, TILE * 2
    ov2 = OV * 2
    mask_w = Image.fromarray(
        (np.arange(ov2, dtype=np.float32).reshape(1, ov2)
         .repeat(TH, axis=0) * 255 / ov2).astype(np.uint8), 'L')
    mask_h = Image.fromarray(
        (np.arange(ov2, dtype=np.float32).reshape(ov2, 1)
         .repeat(w, axis=1) * 255 / ov2).astype(np.uint8), 'L')
    combined = Image.new('RGB', (w, h))
    # group tile indices by row (tiles_meta: flat_idx -> (x, y) source px)
    rows = {}
    for i, (x, y) in tiles_meta.items():
        rows.setdefault(y * 2, []).append((x * 2, i))
    for y, cols in sorted(rows.items()):
        cols.sort()
        rowimg = Image.new('RGB', (w, TH))  # full tile height, like orig
        for x, i in cols:
            tile = outs[i]
            if x == 0:
                rowimg.paste(tile, (0, 0))
                continue
            rowimg.paste(tile.crop((0, 0, ov2, TH)), (x, 0), mask=mask_w)
            rowimg.paste(tile.crop((ov2, 0, TW, TH)), (x + ov2, 0))
        if y == 0:
            combined.paste(rowimg, (0, 0))
            continue
        combined.paste(rowimg.crop((0, 0, w, ov2)), (0, y), mask=mask_h)
        combined.paste(rowimg.crop((0, ov2, w, TH)), (0, y + ov2))
    return combined


def gpu_worker():
    s = ga.sess()
    inp = s.get_inputs()[0].name
    while True:
        try:
            first = tile_q.get(timeout=2)
        except Empty:
            continue
        batch = [] if first is None else [first]
        while len(batch) < BATCH:
            try:
                it = tile_q.get_nowait()
            except Empty:
                break
            if it is None:
                tile_q.put(None)  # keep terminator for future callers
                batch_term = True
                break
            batch.append(it)
        if first is None or not batch:
            done_q.put(None)
            return
        # odd-size jobs run alone (native dims, sub-overlap fallback)
        singles = [b for b in batch if b[3] is not None]
        batched = [b for b in batch if b[3] is None]
        if batched:
            a = np.stack([b[2] for b in batched])
            res = s.run(None, {inp: a})[0]
            for (jid, ti, _, _), o in zip(batched, res):
                o = np.transpose(o, (1, 2, 0))[:, :, ::-1].copy()
                done_q.put((jid, ti, np.clip(o * 255, 0, 255)
                            .astype(np.uint8)))
        for jid, ti, arr, dims in singles:
            o = ga.infer_tile(arr, inp, s)
            done_q.put((jid, ti, np.asarray(o)))


def _finish_err(fut):
    if fut.exception() is not None:
        import traceback
        traceback.print_exception(fut.exception())


def finish_job(jid, out_dir, meta):
    j = jobs[jid]
    si, meta_tiles, outs = j['si'], j['tiles'], j['outs']
    name, rec = j['name'], j['recipe']
    if j['native'] is not None:
        w, h = j['native']
        arr = outs[0]
        rgb = Image.fromarray(arr).crop((0, 0, w * 2, h * 2))
    else:
        ims = {i: Image.fromarray(a) for i, a in outs.items()}
        rgb = combine(meta_tiles, ims, j['W'], j['H'])
    out = gr.apply(rec, si, rgb=rgb)
    png = os.path.join(out_dir, j['arch'], j['var'],
                       j['name'][:-4] + '.png')
    os.makedirs(os.path.dirname(png), exist_ok=True)
    out.save(png)
    meta['%s/%s' % (j['arch'], j['var'])][name] = {
        'x': 0, 'y': 0, 'bpp': 32 if out.mode == 'RGBA' else 24,
        'recipe': rec, 'src': j['src']}
    jobs.pop(jid)


def dispatcher(fin_pool, out_dir, meta, stats):
    while True:
        item = done_q.get()
        if item is None:
            return
        jid, ti, arr = item[0], item[1], item[2]
        j = jobs.get(jid)
        j['outs'][ti] = arr
        j['left'] -= 1
        if j['left'] == 0:
            fut = fin_pool.submit(finish_job, jid, out_dir, meta)
            fut.add_done_callback(_finish_err)
            stats[0] += 1
            if stats[0] % 200 == 0:
                print('finished %d' % stats[0], flush=True)


def producer(job_specs, out_dir, meta, stats):
    for jid, spec in job_specs:
        arch, var, fn, rec, order = spec
        try:
            src, at = ga.src_payload(alds_g, fn, order)
            if src is None:
                raise FileNotFoundError(fn)
            si = ajp.decode_rgba(src) if fn.lower().endswith('.ajp') \
                else ga.to_img(src)
            if rec in NO_GPU:
                out = gr.apply(rec, si)
                png = os.path.join(out_dir, arch, var, fn[:-4] + '.png')
                os.makedirs(os.path.dirname(png), exist_ok=True)
                out.save(png)
                meta['%s/%s' % (arch, var)][fn] = {
                    'x': 0, 'y': 0,
                    'bpp': 32 if out.mode == 'RGBA' else 24,
                    'recipe': rec, 'src': at}
                stats[1] += 1
                continue
            # build model input image (padded_ai uses a canvas)
            inp_im = si.convert('RGB')
            if rec == 'padded_ai':
                w, h = si.size
                cw, ch = (96, 96) if (w <= 96 and h <= 96) else (
                    max(w + 16, 128), max(h + 32, 128))
                cw, ch = max(cw, w), max(ch, h)
                cv = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
                cv.paste(si.convert('RGBA'), ((cw - w) // 2, (ch - h) // 2))
                inp_im = cv.convert('RGB')
            W2, H2 = inp_im.size
            tiles = ga.split_grid(inp_im, TILE, TILE, OV)
            if not any(row[2] for row in tiles):
                # sub-overlap: single native-size inference (raw HWC RGB)
                arr = np.asarray(inp_im)
                jobs[jid] = {'si': si, 'recipe': rec, 'name': fn,
                             'arch': arch, 'var': var, 'src': at,
                             'tiles': {0: (0, 0)}, 'outs': {}, 'left': 1,
                             'W': W2 * 2, 'H': H2 * 2,
                             'native': (W2, H2)}
                tile_q.put((jid, 0, arr, (W2, H2)))
                continue
            meta_tiles, items = prepare_tiles(inp_im)
            with results_lock:
                jobs[jid] = {'si': si, 'recipe': rec, 'name': fn,
                             'arch': arch, 'var': var, 'src': at,
                             'tiles': meta_tiles, 'outs': {},
                             'left': len(items), 'W': W2 * 2, 'H': H2 * 2,
                             'native': None}
            for i, arr in items:
                tile_q.put((jid, i, arr, None))
        except Exception as e:
            print('ERR %s/%s/%s: %s' % (arch, var, fn, e), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'gen_png'))
    ap.add_argument('--only', default=None)
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    global alds_g
    alds_g = ga.load_sources()
    mani = json.load(open(os.path.join(ROOT, 'work',
                                       'recipe_manifest.json'),
                          encoding='utf-8'))

    specs = []
    jid = 0
    for arch, var, fn, path in __import__('gen_payload').iter_payloads(
            only=args.only):
        key = '%s/%s/%s' % (arch, var, fn)
        rec = mani.get(key, {}).get('recipe', 'ai')
        order = ['vanilla'] if var == 'vanilla' else ['jp']
        if var == 'shared':
            order = ['jp', 'vanilla']
        specs.append((jid, (arch, var, fn, rec, order)))
        jid += 1
    if args.limit:
        specs = specs[:args.limit]
    print('%d payloads' % len(specs), flush=True)

    meta = {('%s/%s' % (a, v)): {} for a in ('GM', 'GA')
            for v in ('shared', 'jp', 'vanilla')}
    stats = [0, 0]
    fin_pool = ThreadPoolExecutor(N_FINISHERS)
    prod_pool = ThreadPoolExecutor(N_PRODUCERS)
    gt = threading.Thread(target=gpu_worker, daemon=True)
    gt.start()
    dt = threading.Thread(target=dispatcher,
                          args=(fin_pool, args.out, meta, stats),
                          daemon=True)
    dt.start()
    chunk = math.ceil(len(specs) / N_PRODUCERS)
    prods = [prod_pool.submit(producer,
                              specs[i * chunk:(i + 1) * chunk],
                              args.out, meta, stats)
             for i in range(N_PRODUCERS)]
    for p in prods:
        p.result()
    tile_q.put(None)
    dt.join()
    fin_pool.shutdown(wait=True)
    for sub, m in meta.items():
        if not m:
            continue
        d = os.path.join(args.out, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'manifest.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    print('done: %d via GPU, %d direct' % (stats[0], stats[1]))


if __name__ == '__main__':
    main()
