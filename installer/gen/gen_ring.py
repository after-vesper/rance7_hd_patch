# -*- coding: utf-8 -*-
"""Ring-buffer pipelined payload generator (multiprocess).

One GPU session lives in the main process and stays saturated at
batch<=16. Worker processes own whole jobs end-to-end:

  worker main loop : decode source -> build model input -> split tiles
                     -> push tile requests to req_q
  worker consumer thread : collect results from its own res_q, when a
                     job is complete reassemble + apply recipe + save
                     PNG -> notify manifest entry via mft_q

Backpressure comes from bounded queues; each worker also caps the number
of in-flight jobs (PENDING_MAX) so source images don't pile up.

Tile transport uses mp.Queue (pickled bytes) rather than shared memory:
~0.4MB/tile at <=30 tiles/s is ~12MB/s, far below pipe capacity, so the
simpler transport does not limit the GPU.
"""

import argparse
import json
import math
import multiprocessing as mp
import os
import sys
import threading
import time
from queue import Empty

import numpy as np
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# embedded-python layout: sibling modules live next to this script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'work'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import gen_audit as ga  # noqa: E402
import gen_recipes as gr  # noqa: E402
import gen_fast as gf  # noqa: E402
import ajp  # noqa: E402
import qnt_fast  # noqa: E402
import gen_payload as gp  # noqa: E402

TILE, OV = ga.TILE, ga.OV
BATCH = 16            # default; calibrated at startup for the local GPU
REQ_MAX = 512         # ~200MB of fp16 tiles in flight, max
RES_MAX = 384         # ~300MB of outputs buffered per worker, max
PENDING_MAX = 24      # jobs in flight per worker
FIN_THREADS = 4       # reassemble+save threads per worker process
BATCH_CANDIDATES = (4, 8, 16)

NO_GPU = {'nearest', 'lanczos', 'manual'}

# ---------------------------------------------------------------- worker

_w = None  # per-worker state


class _W:
    pass


def _worker_main(wid, job_q, req_q, res_q, mft_q, out_dir, emit_qnt):
    global _w
    _w = _W()
    _w.emit_qnt = emit_qnt
    _w.alds = ga.load_sources()
    _w.res_q = res_q
    _w.mft_q = mft_q
    _w.req_q = req_q
    _w.out_dir = out_dir
    _w.wid = wid
    _w.seq = 0
    _w.pending = {}
    _w.slots = threading.Semaphore(PENDING_MAX)
    _w.done = threading.Event()
    _w.fin = ThreadPoolExecutor(FIN_THREADS)

    ct = threading.Thread(target=_consumer, daemon=True)
    ct.start()
    while True:
        spec = job_q.get()
        if spec is None:
            break
        try:
            _start_job(spec)
        except Exception as e:
            arch, var, fn, rec, order = spec
            mft_q.put(('ERR', '%s/%s/%s [%s]: %s'
                       % (arch, var, fn, rec, e)))
    # all my tiles are queued; tell the gpu loop, then wait for drain
    req_q.put(('END', wid))
    _w.done.wait()
    ct.join()
    _w.fin.shutdown(wait=True)


def _start_job(spec):
    arch, var, fn, rec, order = spec
    src, at = ga.src_payload(_w.alds, fn, order)
    if src is None:
        raise FileNotFoundError('no source for %s' % fn)
    if rec == 'manual':
        return  # exception payloads are placed separately
    si = ajp.decode_rgba(src) if fn.lower().endswith('.ajp') \
        else ga.to_img(src)
    if rec in NO_GPU:
        out = gr.apply(rec, si)
        _save_and_report(spec, at, out, src)
        return
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
    _w.slots.acquire()
    seq = _w.seq
    _w.seq += 1
    if not any(row[2] for row in tiles):
        # sub-overlap: single native-size inference (raw HWC RGB)
        _w.pending[seq] = {'si': si, 'recipe': rec, 'name': fn,
                           'arch': arch, 'var': var, 'src': at,
                           'srcbytes': src,
                           'outs': {}, 'left': 1,
                           'W': W2 * 2, 'H': H2 * 2,
                           'native': (W2, H2)}
        _w.req_q.put((_w.wid, seq, 0, 'N', W2, H2,
                      np.asarray(inp_im).tobytes()))
        return
    meta_tiles, items = gf.prepare_tiles(inp_im)
    _w.pending[seq] = {'si': si, 'recipe': rec, 'name': fn,
                       'arch': arch, 'var': var, 'src': at,
                       'srcbytes': src,
                       'tiles': meta_tiles, 'outs': {},
                       'left': len(items), 'W': W2 * 2, 'H': H2 * 2,
                       'native': None}
    for i, arr in items:
        _w.req_q.put((_w.wid, seq, i, 'T', arr.tobytes()))


def _consumer():
    while True:
        item = _w.res_q.get()
        if item is None:
            _w.done.set()
            return
        if item[0] == 'ERR':
            seq, msg = item[1], item[2]
            j = _w.pending.pop(seq, None)
            if j is not None:
                _w.mft_q.put(('ERR', '%s/%s/%s: %s'
                              % (j['arch'], j['var'], j['name'], msg)))
                _w.slots.release()
            continue
        (wid, seq), tid, kind = item[0], item[1], item[2]
        j = _w.pending.get(seq)
        if j is None:
            continue
        if kind == 'N':
            w2, h2, buf = item[3], item[4], item[5]
            arr = np.frombuffer(buf, np.uint8).reshape(h2, w2, 3)
        else:
            arr = np.frombuffer(item[3], np.uint8).reshape(
                TILE * 2, TILE * 2, 3)
        j['outs'][tid] = arr
        j['left'] -= 1
        if j['left'] == 0:
            _w.pending.pop(seq)
            _w.fin.submit(_finish_safe, seq, j)


def _finish_safe(seq, j):
    try:
        _finish(seq, j)
    except Exception as e:
        _w.mft_q.put(('ERR', '%s/%s/%s: %s'
                      % (j['arch'], j['var'], j['name'], e)))
    finally:
        _w.slots.release()


def _finish(seq, j):
    if j['native'] is not None:
        w, h = j['native']
        rgb = Image.fromarray(j['outs'][0]).crop((0, 0, w * 2, h * 2))
    else:
        ims = {i: Image.fromarray(a) for i, a in j['outs'].items()}
        rgb = gf.combine(j['tiles'], ims, j['W'], j['H'])
    out = gr.apply(j['recipe'], j['si'], rgb=rgb)
    _save_and_report((j['arch'], j['var'], j['name'], j['recipe'], None),
                     j['src'], out, j.get('srcbytes'))


def _save_and_report(spec, src, out, src_bytes=None):
    """Write the finished asset. Default: PNG intermediate; with
    --emit-qnt write the final payload bytes (QNT/AJP) directly so the
    repack phase degenerates to a byte copy."""
    arch, var, fn, rec, _ = spec
    d = os.path.join(_w.out_dir, arch, var)
    os.makedirs(d, exist_ok=True)
    if _w.emit_qnt:
        if fn.lower().endswith('.ajp'):
            import io
            _, _, _, asec = ajp.decode(src_bytes)
            buf = io.BytesIO()
            out.convert('RGB').save(buf, 'JPEG', quality=95)
            alpha = out.getchannel('A').tobytes() if asec is not None \
                else None
            blob = ajp.encode(out.width, out.height, buf.getvalue(),
                              alpha, src_bytes)
        else:
            blob = qnt_fast.encode_pil(
                out, out.mode in ('RGBA', 'LA', 'PA'), level=6)
        with open(os.path.join(d, fn), 'wb') as f:
            f.write(blob)
    else:
        out.save(os.path.join(d, fn[:-4] + '.png'))
    _w.mft_q.put(('%s/%s' % (arch, var), fn,
                  {'x': 0, 'y': 0,
                   'bpp': 32 if out.mode == 'RGBA' else 24,
                   'recipe': rec, 'src': src}))


# ------------------------------------------------------------------- gpu


def calibrate_batch(s, inp):
    """Measure inference throughput at each candidate batch size and
    return the fastest stable size. Adapts to whatever GPU (or CPU
    fallback) the machine has; DML collapses above ~16 on weaker GPUs,
    so candidates stay small."""
    global BATCH
    rng = np.random.RandomState(0)
    best_n, best_t = 1, 0.0
    for n in BATCH_CANDIDATES:
        a = rng.rand(n, 3, TILE, TILE).astype(np.float16)
        try:
            s.run(None, {inp: a})  # warmup / capability probe
            t0 = time.time()
            for _ in range(3):
                s.run(None, {inp: a})
            per = (time.time() - t0) / (3 * n)
        except Exception:
            continue  # size unsupported on this device
        if best_t == 0.0 or per < best_t:
            best_n, best_t = n, per
    BATCH = best_n
    prov = s.get_providers()[0] if s.get_providers() else '?'
    rate = 1.0 / best_t if best_t else 0.0
    print('gpu calibration: provider=%s batch=%d (%.1f tiles/s)%s'
          % (prov, best_n, rate,
             '' if best_t else ' [provider probe failed]'), flush=True)
    if rate and rate < 3.0:
        print('WARNING: inference is very slow (CPU-only path?); '
              'full generation may take hours on this machine',
              flush=True)
    return BATCH


def gpu_loop(req_q, res_qs, n_workers):
    """Single ONNX session; batch tile requests, route results back."""
    s = ga.sess()
    inp = s.get_inputs()[0].name
    calibrate_batch(s, inp)
    ends = 0
    n_in = n_out = 0
    t0 = time.time()
    while True:
        try:
            first = req_q.get(timeout=0.05)
        except Empty:
            first = None
        batch = []
        if first is not None:
            batch.append(first)
        while len(batch) < BATCH:
            try:
                it = req_q.get_nowait()
            except Empty:
                break
            batch.append(it)
        if not batch:
            if ends >= n_workers:
                break
            continue
        tiles = [b for b in batch if b[0] != 'END']
        ends += sum(1 for b in batch if b[0] == 'END')
        if tiles:
            _run_batch(tiles, res_qs, s, inp)
            n_in += len(tiles)
        if ends >= n_workers and req_q.empty():
            break
    for q in res_qs:
        q.put(None)
    print('gpu: %d tiles in %.1fs (%.1f tiles/s)'
          % (n_in, time.time() - t0, n_in / (time.time() - t0)),
          flush=True)


def _run_batch(tiles, res_qs, s, inp):
    singles = [b for b in tiles if b[3] == 'N']
    normal = [b for b in tiles if b[3] == 'T']
    if normal:
        try:
            a = np.stack([np.frombuffer(b[4], np.float16)
                          .reshape(3, TILE, TILE) for b in normal])
            res = s.run(None, {inp: a})[0]
        except Exception as e:
            for b in normal:
                res_qs[b[0]].put(('ERR', b[1], str(e)))
            res = None
        if res is not None:
            for b, o in zip(normal, res):
                o = np.transpose(o, (1, 2, 0))[:, :, ::-1].copy()
                u8 = np.clip(o * 255, 0, 255).astype(np.uint8)
                res_qs[b[0]].put(((b[0], b[1]), b[2], 'T',
                                  u8.tobytes()))
    for b in singles:
        wid, seq, tid, _, w, h, buf = b
        try:
            arr = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            o = np.asarray(ga.infer_tile(arr, inp, s))
            res_qs[wid].put(((wid, seq), tid, 'N', o.shape[1],
                             o.shape[0], o.tobytes()))
        except Exception as e:
            res_qs[wid].put(('ERR', seq, str(e)))


# ------------------------------------------------------------------ main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'work',
                                                  'gen_png'))
    ap.add_argument('--only', default=None)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--skip-existing', action='store_true')
    ap.add_argument('--workers', type=int, default=0,
                    help='0 = auto (half of logical cores, 4..16)')
    ap.add_argument('--emit-qnt', action='store_true',
                    help='write final QNT/AJP payload bytes instead of '
                         'PNG intermediates (repack becomes a raw copy)')
    ap.add_argument('--src-dir', default=None,
                    help='directory with pristine Rance7GM/GA.ald sources')
    ap.add_argument('--asset-set', choices=('jp', 'vanilla'),
                    default=None,
                    help='generate only shared + this variant payloads')
    ap.add_argument('--model', default=None, help='ONNX model path')
    ap.add_argument('--manifest', default=None,
                    help='recipe manifest json path')
    ap.add_argument('--data', default=None,
                    help='installer payload dir used to enumerate names')
    args = ap.parse_args()
    if args.workers <= 0:
        args.workers = max(4, min(16, (os.cpu_count() or 8) // 2))
    # export install-mode settings before spawning workers (spawned
    # processes re-import modules and pick these up from the env)
    if args.model:
        os.environ['GEN_MODEL'] = os.path.abspath(args.model)
        ga.MODEL = os.environ['GEN_MODEL']
    if args.src_dir:
        os.environ['GEN_SRC_DIR'] = os.path.abspath(args.src_dir)
    if args.asset_set:
        os.environ['GEN_ASSET_SET'] = args.asset_set
    if args.manifest:
        os.environ['GEN_MANIFEST'] = os.path.abspath(args.manifest)
        gp.MANIFEST = os.environ['GEN_MANIFEST']
    if args.data:
        os.environ['GEN_DATA'] = os.path.abspath(args.data)
        gp.DATA = os.environ['GEN_DATA']
    print('workers=%d' % args.workers, flush=True)

    mani = gp.load_manifest()
    order_map = {'vanilla': ['vanilla', 'jp'], 'jp': ['jp', 'vanilla'],
                 'shared': ['jp', 'vanilla']}
    if args.manifest:
        # install-mode: the shipped payload dirs are not present, so
        # payload names come from the manifest keys themselves
        entries = []
        for key, info in sorted(mani.items()):
            arch, var, fn = key.split('/', 2)
            if args.only and not fn.startswith(args.only):
                continue
            entries.append((arch, var, fn, None))
    else:
        entries = gp.iter_payloads(only=args.only)
    specs = []
    for arch, var, fn, path in entries:
        if args.asset_set and var not in ('shared', args.asset_set):
            continue
        if args.skip_existing and (
                os.path.exists(os.path.join(args.out, arch, var,
                                            fn[:-4] + '.png'))
                or os.path.exists(os.path.join(args.out, arch, var,
                                               fn))):
            continue
        rec = mani.get('%s/%s/%s' % (arch, var, fn), {}).get('recipe',
                                                             'ai')
        specs.append((arch, var, fn, rec, order_map[var]))
    if args.limit:
        specs = specs[:args.limit]
    print('%d payloads to generate' % len(specs), flush=True)

    ctx = mp.get_context('spawn')
    job_q = ctx.Queue()
    req_q = ctx.Queue(maxsize=REQ_MAX)
    mft_q = ctx.Queue()
    res_qs = [ctx.Queue(maxsize=RES_MAX) for _ in range(args.workers)]
    for s_ in specs:
        job_q.put(s_)
    for _ in range(args.workers):
        job_q.put(None)

    meta = {}
    n_done = n_err = 0
    expect = len(specs)

    def drain_mft():
        nonlocal n_done, n_err
        while True:
            m = mft_q.get()
            if m is None:
                return
            if m[0] == 'ERR':
                print(m[1], flush=True)
                n_err += 1
            else:
                sub, fn, info = m
                meta.setdefault(sub, {})[fn] = info
                n_done += 1
                if (n_done + n_err) % 200 == 0:
                    print('%d/%d done (%d err)'
                          % (n_done, expect, n_err), flush=True)

    dt = threading.Thread(target=drain_mft, daemon=True)
    dt.start()

    procs = [ctx.Process(target=_worker_main,
                         args=(i, job_q, req_q, res_qs[i], mft_q,
                               args.out, args.emit_qnt))
             for i in range(args.workers)]
    for p in procs:
        p.start()
    gpu_loop(req_q, res_qs, args.workers)
    for p in procs:
        p.join()
    mft_q.put(None)
    dt.join()

    for sub, m in meta.items():
        d = os.path.join(args.out, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'manifest.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    print('done: %d generated, %d errors -> %s'
          % (n_done, n_err, args.out))


if __name__ == '__main__':
    main()
