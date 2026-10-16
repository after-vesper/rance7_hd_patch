# -*- coding: utf-8 -*-
"""Pipelined payload generator (multiprocess, per-worker GPU sessions).

Each worker process owns whole jobs end-to-end and holds its own ONNX
session, so no tile data crosses process boundaries:

  worker main loop : decode source -> build model input -> split tiles
                     -> infer tiles on the local session -> combine tiles
                     -> recipe postproc -> encode payload -> write file
                     -> notify manifest entry via mft_q

Workers run serially by default (FIN_THREADS=0): per-process finisher
threads contend on the GIL and were ~3x slower than letting each worker
complete its job inline. Parallelism comes from process count instead.

Backpressure: each worker caps in-flight finish jobs (PENDING_MAX) so
source images and raw outputs don't pile up. The GPU is a shared
resource — N workers issuing in parallel saturate it without any
tile-passing IPC overhead.
"""

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import struct
import sys
import threading
import time


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
PENDING_MAX = 8       # jobs in flight per worker (each buffers ~20-40 MB
                      # of raw fp16 outputs + images; 12 workers x 24 slots
                      # exhausted host commit -> MemoryError storms)
FIN_THREADS = int(os.environ.get('GEN_FIN_THREADS', '0'))
BATCH_CANDIDATES = (4, 8, 16)

NO_GPU = {'nearest', 'lanczos', 'manual'}

# UI language for console output: Install.ps1 exports GEN_LANG for the
# zh build (same convention as the PowerShell-side L() helper).
_LANG = os.environ.get('GEN_LANG', 'ja')


def L(ja, zh, en=None):
    if _LANG == 'zh':
        return zh
    if _LANG == 'en' and en is not None:
        return en
    return ja

# Console output is shared between the drain thread's in-place progress
# bar and plain status prints from the main thread; a lock + line-length
# tracker keeps them from interleaving on the same row.
_IO_LOCK = threading.Lock()
_prog_line_len = [0]


def _log(msg):
    """Print a whole line, clearing any in-progress bar first."""
    with _IO_LOCK:
        if _prog_line_len[0]:
            sys.stdout.write('\r' + ' ' * _prog_line_len[0] + '\r')
            _prog_line_len[0] = 0
        print(msg, flush=True)


# ---------------------------------------------------------------- worker

_w = None  # per-worker state


class _W:
    pass


def _worker_main(wid, job_q, mft_q, out_dir, emit_qnt, batch, gpu_sem):
    global _w
    _w = _W()
    _w.emit_qnt = emit_qnt
    _w.alds = ga.load_sources()
    _w.mft_q = mft_q
    _w.out_dir = out_dir
    _w.wid = wid
    _w.batch = batch
    _w.cache_dir = os.environ.get('GEN_CACHE_DIR')
    _w.cache_tag = os.environ.get('GEN_CACHE_TAG', '')
    _w.qnt_level = int(os.environ.get('GEN_QNT_LEVEL', '3'))
    _w.slots = threading.Semaphore(PENDING_MAX)
    _w.fin = ThreadPoolExecutor(FIN_THREADS) if FIN_THREADS else None
    _w.sess = ga.sess()
    _w.inp = _w.sess.get_inputs()[0].name
    _w.gpu_sem = gpu_sem
    _w.tiles = 0
    _w.st = {}

    while True:
        spec = job_q.get()
        if spec is None:
            break
        try:
            _run_job(spec)
        except Exception:
            # one retry absorbs transient IO contention (AV scans,
            # cache-file replace races); a persistent failure reports ERR
            try:
                time.sleep(0.05)
                _run_job(spec)
            except Exception as e:
                arch, var, fn, rec, order = spec
                mft_q.put(('ERR', '%s/%s/%s [%s]: %s'
                           % (arch, var, fn, rec, e)))
    if _w.fin is not None:
        _w.fin.shutdown(wait=True)
    mft_q.put(('STATS', wid, _w.tiles, _w.st))


def _cache_key(src, rec):
    h = hashlib.sha256(_w.cache_tag.encode())
    h.update(rec.encode())
    h.update(src)
    return h.hexdigest()


def _run_job(spec):
    j = _prep_job(spec)
    if j is not None:
        # whole-frame job: single native-size inference
        t0 = time.time()
        o = _infer(lambda a: ga.infer_arr(a, _w.inp, _w.sess),
                   j.pop('_arr'))
        _w.tiles += 1
        _stage('infer', t0)
        j['outs'] = {0: o}
        _submit_finish(j)


def _cache_get(key):
    """Read a cached payload. On Windows the open can be denied
    momentarily while another worker's os.replace swaps the file in
    (delete-pending), or while an AV scan holds a lock — retry briefly,
    then degrade to a miss. The cache is an optimisation and must
    never fail the job."""
    p = os.path.join(_w.cache_dir, key)
    for _ in range(5):
        try:
            with open(p, 'rb') as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError:
            time.sleep(0.02)
    return None


def _cache_put(key, blob):
    p = os.path.join(_w.cache_dir, key)
    tmp = '%s.%d.tmp' % (p, _w.wid)
    with open(tmp, 'wb') as f:
        f.write(blob)
    os.replace(tmp, p)


def _stage(name, t0):
    _w.st[name] = _w.st.get(name, 0.0) + (time.time() - t0) * 1000


def _infer(fn, arg):
    """Run one inference under the cross-process GPU semaphore; retry
    once on transient allocator failures."""
    _w.gpu_sem.acquire()
    try:
        return fn(arg)
    except Exception:
        time.sleep(0.05)
        return fn(arg)
    finally:
        _w.gpu_sem.release()


def _prep_job(spec):
    """CPU side of one job: source lookup -> decode -> model input.

    Returns a pending job dict (with the raw HWC uint8 model input in
    j['_arr']) when the job needs whole-frame GPU inference, or None
    when the job was completed inline (cache hit / no-GPU recipe /
    oversized tiled fallback)."""
    arch, var, fn, rec, order = spec
    t0 = time.time()
    src, at = ga.src_payload(_w.alds, fn, order)
    _stage('src', t0)
    if src is None:
        raise FileNotFoundError('no source for %s' % fn)
    if rec == 'manual':
        return None  # exception payloads are placed separately
    ckey = None
    if _w.cache_dir and _w.emit_qnt:
        ckey = _cache_key(src, rec)
        blob = _cache_get(ckey)
        if blob is not None:
            _cache_hit(spec, at, blob)
            return None
    t0 = time.time()
    # dispatch on magic, not extension: the zh build has .AJP-named
    # entries that actually hold QNT payloads
    si = ajp.decode_rgba(src) if src[:3] == b'AJP' else ga.to_img(src)
    _stage('decode', t0)
    if rec in NO_GPU:
        out = gr.apply(rec, si)
        _save_and_report(spec, at, out, src, ckey)
        return None
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
    if ga.fits_whole(W2, H2):
        # whole-frame: queue for same-shape batched inference
        return {'si': si, 'recipe': rec, 'name': fn,
                'arch': arch, 'var': var, 'src': at,
                'srcbytes': src, 'ckey': ckey,
                '_arr': np.asarray(inp_im),
                'W': W2 * 2, 'H': H2 * 2, 'native': (W2, H2)}
    t0 = time.time()
    meta_tiles, items = gf.prepare_tiles(inp_im)
    _stage('prep', t0)
    outs = {}
    t0 = time.time()
    for i in range(0, len(items), _w.batch):
        chunk = items[i:i + _w.batch]
        a = np.stack([c[1] for c in chunk])
        res = _infer(lambda arr: _w.sess.run(None, {_w.inp: arr})[0], a)
        _w.tiles += len(chunk)
        # whole-batch -> u8 BGR: one vector pass instead of
        # per-tile numpy ops in the finisher (fp32 math; fp16
        # elementwise ops are software-emulated and slower)
        res = res.astype(np.float32)
        np.multiply(res, np.float32(255.0), out=res)
        np.clip(res, 0, 255, out=res)
        u8 = res.transpose(0, 2, 3, 1)[:, :, :, ::-1].astype(np.uint8)
        for (ti, _), o in zip(chunk, u8):
            outs[ti] = o
    _stage('infer', t0)
    j = {'si': si, 'recipe': rec, 'name': fn,
         'arch': arch, 'var': var, 'src': at,
         'srcbytes': src, 'ckey': ckey,
         'tiles': meta_tiles, 'outs': outs,
         'W': W2 * 2, 'H': H2 * 2, 'native': None}
    _submit_finish(j)
    return None


def _submit_finish(j):
    if _w.fin is None:
        _finish_safe(j)
        return
    t0 = time.time()
    _w.slots.acquire()
    _stage('slotwait', t0)
    _w.fin.submit(_finish_safe, j)


def _finish_safe(j):
    t0 = time.time()
    try:
        try:
            _finish(j)
        except Exception:
            time.sleep(0.05)
            _finish(j)  # retry once for transient output-file locks
    except Exception as e:
        _w.mft_q.put(('ERR', '%s/%s/%s: %s'
                      % (j['arch'], j['var'], j['name'], e)))
    finally:
        _stage('finish', t0)
        if _w.fin is not None:
            _w.slots.release()


def _finish(j):
    t0 = time.time()
    if j['native'] is not None:
        w, h = j['native']
        rgb = Image.fromarray(j['outs'][0]).crop((0, 0, w * 2, h * 2))
    else:
        ims = {i: Image.fromarray(a)
               for i, a in j['outs'].items()}
        rgb = gf.combine(j['tiles'], ims, j['W'], j['H'])
    _stage('f_conv', t0)
    t0 = time.time()
    out = gr.apply(j['recipe'], j['si'], rgb=rgb)
    _stage('f_apply', t0)
    t0 = time.time()
    _save_and_report((j['arch'], j['var'], j['name'], j['recipe'], None),
                     j['src'], out, j.get('srcbytes'), j.get('ckey'))
    _stage('f_save', t0)


def _cache_hit(spec, src_at, blob):
    """Cache hit: the payload was already generated from identical
    source bytes (e.g. a re-install after an external patch). Emit the
    stored bytes verbatim and report the manifest entry."""
    arch, var, fn, rec, _ = spec
    d = os.path.join(_w.out_dir, arch, var)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, fn), 'wb') as f:
        f.write(blob)
    # bpp for the manifest: QNT alpha flag at 0x28, AJP alpha_size 0x20
    if blob[:3] == b'AJP':
        bpp = 32 if struct.unpack_from('<I', blob, 0x20)[0] else 24
    else:
        bpp = 32 if struct.unpack_from('<I', blob, 0x28)[0] else 24
    _w.mft_q.put(('%s/%s' % (arch, var), fn,
                  {'x': 0, 'y': 0, 'bpp': bpp,
                   'recipe': rec, 'src': src_at, 'cache': 'hit'}))


def _save_and_report(spec, src, out, src_bytes=None, ckey=None):
    """Write the finished asset. Default: PNG intermediate; with
    --emit-qnt write the final payload bytes (QNT/AJP) directly so the
    repack phase degenerates to a byte copy."""
    arch, var, fn, rec, _ = spec
    d = os.path.join(_w.out_dir, arch, var)
    os.makedirs(d, exist_ok=True)
    if _w.emit_qnt:
        if src_bytes is not None and src_bytes[:3] == b'AJP':
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
                out, out.mode in ('RGBA', 'LA', 'PA'), level=_w.qnt_level)
        with open(os.path.join(d, fn), 'wb') as f:
            f.write(blob)
        if ckey is not None:
            try:
                _cache_put(ckey, blob)
            except OSError:
                pass  # cache is an optimisation; never fail the job
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
    _log(L('  GPU測定: provider=%s バッチ=%d（%.1f タイル/秒）%s',
           '  GPU 测量: provider=%s 批次=%d（%.1f 图块/秒）%s',
           '  GPU benchmark: provider=%s batch=%d (%.1f tiles/s)%s')
         % (prov, best_n, rate,
            '' if best_t else L(' [provider検出失敗]',
                                ' [provider 检测失败]',
                                ' [provider detection failed]')))
    if rate and rate < 3.0:
        _log(L('  警告: 推論がかなり遅いようです（CPU実行？）。'
               'このPCでは生成にかなり時間がかかる見込みです',
               '  警告: 推理速度很慢（可能是用 CPU 运行的？）。'
               '此电脑上的生成预计需要较长时间',
               '  Warning: inference seems quite slow (running on CPU?). '
               'Generation will take a long time on this PC'))
    return BATCH





# ------------------------------------------------------------------ main


CACHE_TAG_VERSION = 'v1'


def _avail_commit_mb():
    """Remaining system commit (RAM + pagefile) in MB, or None when the
    value cannot be determined (non-Windows)."""
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong),
                        ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong),
                        ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong),
                        ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]

        st = _MS()
        st.dwLength = ctypes.sizeof(_MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullAvailPageFile >> 20
    except Exception:
        return None


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


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
    ap.add_argument('--asset-set', choices=('jp', 'vanilla', 'zh'),
                    default=None,
                    help='generate only shared + this variant payloads')
    ap.add_argument('--model', default=None, help='ONNX model path')
    ap.add_argument('--manifest', default=None,
                    help='recipe manifest json path')
    ap.add_argument('--data', default=None,
                    help='installer payload dir used to enumerate names')
    ap.add_argument('--cache-dir', default=None,
                    help='persistent payload cache dir keyed by source '
                         'content hash (survives re-installs; '
                         '--emit-qnt only)')
    args = ap.parse_args()
    if args.workers <= 0:
        # serial workers (FIN_THREADS=0) can go closer to the core count;
        # threaded finishers share each worker's GIL so fewer help
        n = (os.cpu_count() or 8)
        # CPU-bound pipeline (decode/encode dominate); scale with cores.
        # Beyond ~16 processes contention outweighs the extra lanes and
        # each worker's session still commits ~500 MB either way.
        args.workers = max(4, min(16, n - 2))
        avail = _avail_commit_mb()
        if avail is not None:
            # each worker commits ~500 MB (interpreter + numpy/scipy/ort
            # + in-flight image buffers); cap so other apps and the OS
            # still have headroom instead of hitting the commit limit
            mem_cap = max(2, avail // 500)
            if mem_cap < args.workers:
                args.workers = mem_cap
                print(L('  空きメモリの都合でワーカー数を %d に制限します'
                        '（空き %d MB）',
                        '  因可用内存限制，将工作进程数调整为 %d'
                        '（可用 %d MB）',
                        '  Limiting workers to %d due to free memory'
                        ' (%d MB free)')
                      % (args.workers, avail), flush=True)
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
    if args.cache_dir and args.emit_qnt:
        cache_dir = os.path.abspath(args.cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        os.environ['GEN_CACHE_DIR'] = cache_dir
        # tag = generator version + model identity; a payload is only
        # reusable when the same model produced it
        tag = CACHE_TAG_VERSION
        if ga.MODEL and os.path.exists(ga.MODEL):
            tag += ':' + _sha256_file(ga.MODEL)
        os.environ['GEN_CACHE_TAG'] = tag
        _log(L('  素材キャッシュ: %s', '  素材缓存: %s',
               '  Asset cache: %s') % cache_dir)
    _log(L('  並列ワーカー: %d', '  并行工作进程: %d',
           '  Parallel workers: %d') % args.workers)

    mani = gp.load_manifest()
    order_map = {'vanilla': ['vanilla', 'jp'], 'jp': ['jp', 'vanilla'],
                 'shared': ['jp', 'vanilla'], 'zh': ['zh']}
    if args.asset_set == 'zh':
        # zh build layout: GA is the live CG archive, GB holds the
        # cg045xx set, GM is dormant. The payload set is every entry
        # present in the live archives (it also covers the zh-only
        # warning screens cg59001/59002 which have no manifest entry).
        entries = []
        alds = ga.load_sources()
        rec_of = {}
        for key, info in mani.items():
            a2, v2, f2 = key.split('/', 2)
            # zh content matches the vanilla (all-ages) line; prefer its
            # recipe, then shared, then jp
            rank = {'vanilla': 0, 'shared': 1}.get(v2, 2)
            if f2 not in rec_of or rank < rec_of[f2][0]:
                rec_of[f2] = (rank, info.get('recipe', 'ai'))
        seen = set()
        for a in ga.src_arches('zh'):
            k = ('zh', a)
            if k not in alds:
                continue
            for fn in alds[k][2]:
                if fn in seen:
                    continue
                seen.add(fn)
                if args.only and not fn.startswith(args.only):
                    continue
                entries.append((a, 'zh', fn, None))
        specs = [(a, 'zh', fn, rec_of.get(fn, (9, 'ai'))[1],
                  order_map['zh']) for a, _v, fn, _p in entries]
    else:
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
            rec = mani.get('%s/%s/%s' % (arch, var, fn), {}).get(
                'recipe', 'ai')
            specs.append((arch, var, fn, rec, order_map[var]))
    if args.limit:
        specs = specs[:args.limit]
    _log(L('  生成対象: %d 件', '  生成对象: %d 个',
           '  Assets to generate: %d') % len(specs))

    ctx = mp.get_context('spawn')
    job_q = ctx.Queue()
    mft_q = ctx.Queue()
    for s_ in specs:
        job_q.put(s_)
    for _ in range(args.workers):
        job_q.put(None)

    # Calibrate the tile batch size once in the main process (before the
    # workers start competing for the GPU), then hand it to each worker's
    # own inference session.
    sess = ga.sess()
    batch = calibrate_batch(sess, sess.get_inputs()[0].name)
    ga._sess = None
    del sess

    meta = {}
    stage_ms = {}
    n_done = n_err = n_tiles = 0
    expect = len(specs)
    is_tty = sys.stdout.isatty()
    t_prog = time.time()
    prog_at = [0.0]

    def fmt_eta(sec):
        if not math.isfinite(sec) or sec < 0:
            return '--:--'
        return '%d:%02d' % divmod(int(sec), 60)

    def show_progress(final=False):
        now = time.time()
        if not final and now - prog_at[0] < 0.25:
            return
        prog_at[0] = now
        tot = n_done + n_err
        frac = min(1.0, tot / max(1, expect))
        bar = '#' * int(frac * 28)
        bar = bar.ljust(28, '-')
        rate = tot / max(0.001, now - t_prog)
        eta = (expect - tot) / rate if rate > 0 else float('inf')
        line = ('[%s] %d/%d %5.1f%%  %.1f/s  err %d  eta %s'
                % (bar, tot, expect, frac * 100.0, rate, n_err,
                   fmt_eta(eta)))
        if is_tty:
            with _IO_LOCK:
                pad = max(0, _prog_line_len[0] - len(line))
                _prog_line_len[0] = len(line)
                sys.stdout.write('\r' + line + ' ' * pad)
                sys.stdout.flush()
                if final:
                    sys.stdout.write('\n')
        elif final or tot % 200 == 0:
            _log(line)

    def drain_mft():
        nonlocal n_done, n_err, n_tiles
        while True:
            m = mft_q.get()
            if m is None:
                return
            if m[0] == 'ERR':
                _log(m[1])
                n_err += 1
            elif m[0] == 'STATS':
                n_tiles += m[2]
                for k, v in m[3].items():
                    stage_ms[k] = stage_ms.get(k, 0.0) + v
            else:
                sub, fn, info = m
                meta.setdefault(sub, {})[fn] = info
                n_done += 1
            show_progress()

    dt = threading.Thread(target=drain_mft, daemon=True)
    dt.start()

    # Cap simultaneous inferences: enough concurrency to keep the GPU
    # busy, bounded so concurrent DirectML allocations can't exhaust
    # memory when many workers burst at once.
    gpu_sem = ctx.Semaphore(min(args.workers, 4))
    procs = [ctx.Process(target=_worker_main,
                         args=(i, job_q, mft_q, args.out,
                               args.emit_qnt, batch, gpu_sem))
             for i in range(args.workers)]
    t_gpu = time.time()
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    mft_q.put(None)
    dt.join()
    show_progress(final=True)
    el = time.time() - t_gpu
    if n_tiles:
        _log(L('  GPU推論: %d タイル / %.1f秒（%.1f タイル/秒）',
               '  GPU 推理: %d 图块 / %.1f 秒（%.1f 图块/秒）',
               '  GPU inference: %d tiles / %.1fs (%.1f tiles/s)')
             % (n_tiles, el, n_tiles / el))
    if stage_ms and os.environ.get('GEN_STATS'):
        _log(L('  ステージ時間 ms/件（ワーカー合計）: ',
               '  各阶段耗时 ms/项（工作进程合计）: ',
               '  Stage time ms/item (workers total): ') + ', '.join(
            '%s=%.0f' % (k, v / max(1, expect))
            for k, v in sorted(stage_ms.items())))

    for sub, m in meta.items():
        d = os.path.join(args.out, sub)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'manifest.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    hits = sum(1 for m in meta.values() for i in m.values()
               if i.get('cache'))
    _log(L('  完了: %d 件生成（うちキャッシュ再利用 %d 件）/ エラー %d 件',
           '  完成: 已生成 %d 个（其中复用缓存 %d 个）/ 错误 %d 个',
           '  Done: %d generated (%d from cache) / %d errors')
         % (n_done, hits, n_err))


if __name__ == '__main__':
    main()
