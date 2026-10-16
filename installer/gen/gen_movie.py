# -*- coding: utf-8 -*-
"""Regenerate the OP/ED movies at install time from the user's backed-up
originals: ffmpeg decodes each .alm (MPEG-PS) to raw frames, the shared
gen_audit inference core upscales each frame 2x whole-frame, and ffmpeg
re-encodes to the original-compatible MPEG-1 video + MP2 audio program
stream (CBR/VBV, GOP16, no B-frames — see docs/movie_upscale.md).

usage: gen_movie.py --src-dir <backup dir> --dst-dir <out dir>
                    --ffmpeg <ffmpeg.exe> [--bitrate 12M]
                    [--cache-dir <dir>]

Sources are read from <src-dir>/movie/<name>; outputs are written to
<dst-dir>/<name>. Movies absent from the backup are skipped. A whole-
output cache keyed on model + source bytes lets re-installs skip the
work entirely.
"""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
from fractions import Fraction
from queue import Queue

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.environ.setdefault('GEN_MODEL', os.path.join(_HERE, 'model.onnx'))

import numpy as np  # noqa: E402

import gen_audit as ga  # noqa: E402

# UI language for console output (GEN_LANG, same scheme as gen_ring).
_LANG = os.environ.get('GEN_LANG', 'ja')


def L(ja, zh):
    return zh if _LANG == 'zh' else ja


# movie/*.alm is globbed at run time so language-specific extras
# (e.g. the zh build's Rance7ED.alm) are picked up automatically.


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def _cache_key(src_path, max_width):
    """Generator version + model identity + exact source bytes (same
    scheme as gen_ring/gen_alk). max_width is part of the key because it
    changes the output."""
    tag = 'v2:%d:' % max_width
    model = os.environ.get('GEN_MODEL')
    if model and os.path.exists(model):
        tag += _sha256_file(model)
    h = hashlib.sha256(tag.encode())
    h.update(b'mov\0')
    h.update(_sha256_file(src_path).encode())
    return h.hexdigest()


def _probe(ffmpeg, src):
    """Return (w, h, fps_str, total_frames) for the first video stream by
    parsing `ffmpeg -i` stderr (ffprobe is not bundled with the runtime).
    total_frames is derived from Duration x fps; 0 when unknown."""
    p = subprocess.run([ffmpeg, '-hide_banner', '-i', src],
                       capture_output=True, text=True)
    m = re.search(r'Video:.*?(\d{2,5})x(\d{2,5})', p.stderr)
    if not m:
        raise RuntimeError('cannot probe %s' % src)
    w, h = int(m.group(1)), int(m.group(2))
    fm = re.search(r'([\d.]+)\s*fps', p.stderr)
    fps = float(fm.group(1)) if fm else 29.97
    # express as a clean rational (29.97 -> 30000/1001)
    fps_str = str(Fraction(fps).limit_denominator(1001))
    total = 0
    dm = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', p.stderr)
    if dm:
        dur = (int(dm.group(1)) * 3600 + int(dm.group(2)) * 60 +
               float(dm.group(3)))
        total = int(dur * fps)
    return w, h, fps_str, total


# console progress: same in-place 28-char bar as gen_ring.show_progress
# (carriage-return redraw on a tty, periodic lines when redirected)
_IS_TTY = sys.stdout.isatty()
_prog_len = [0]


def _prog(name, n, total, t0, final=False):
    frac = min(1.0, n / total) if total else 0.0
    bar = ('#' * int(frac * 28)).ljust(28, '-')
    rate = n / max(0.001, time.perf_counter() - t0)
    # same field order as gen_ring/gen_alk: name [bar] n/total pct% rate eta
    if total:
        prog = '%d/%d %5.1f%%' % (n, total, frac * 100.0)
        eta = '  eta %d:%02d' % divmod(int((total - n) / max(rate, 0.01)), 60)
    else:
        prog = '%d frames' % n
        eta = ''
    line = '  %s [%s] %s  %.1f fps%s' % (name, bar, prog, rate, eta)
    if _IS_TTY:
        pad = max(0, _prog_len[0] - len(line))
        _prog_len[0] = len(line)
        sys.stdout.write('\r' + line + ' ' * pad)
        sys.stdout.flush()
        if final:
            sys.stdout.write('\n')
            _prog_len[0] = 0
    elif final or n % 300 == 0:
        print(line, flush=True)


def _upscale(ffmpeg, src, dst, bitrate, name, max_width):
    s = ga.sess()
    inp = s.get_inputs()[0].name
    w, h, fps, total = _probe(ffmpeg, src)
    dw, dh = w * 2, h * 2
    # The English (Kagura) build ships a rebuilt PlayMovie.dll that renders
    # via VMR-7/9/EVR windowless; its decoder/renderer path rejects MPEG-1
    # frames wider than ~1184 px (74 macroblocks) — video goes black while
    # audio keeps playing. --max-width caps the encoded width for such
    # editions; the upscale still runs at 2x and ffmpeg scales down.
    ow, oh = dw, dh
    if max_width and dw > max_width:
        ow = max_width & ~1
        oh = (dh * ow // dw) & ~1
    vf = ['-vf', 'scale=%d:%d:flags=lanczos' % (ow, oh)] if (ow, oh) != (dw, dh) else []

    dec = subprocess.Popen([
        ffmpeg, '-v', 'error', '-i', src,
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen([
        ffmpeg, '-v', 'error', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'gbrp', '-s', '%dx%d' % (dw, dh),
        '-framerate', fps, '-i', '-',
        '-i', src, '-map', '0:v:0', '-map', '1:a:0?',
        ] + vf + [
        '-c:v', 'mpeg1video', '-b:v', bitrate, '-maxrate', bitrate,
        '-bufsize', '3600k', '-g', '16', '-bf', '0',
        '-c:a', 'copy', '-f', 'vcd', dst],
        stdin=subprocess.PIPE)

    fsz = w * h * 3
    q = Queue(maxsize=64)

    def reader():
        while True:
            buf = dec.stdout.read(fsz)
            if len(buf) < fsz:
                break
            q.put(buf)
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()

    n = 0
    t0 = time.perf_counter()
    prog_at = [0.0]
    while True:
        buf = q.get()
        if buf is None:
            break
        a = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        pl = ga.infer_planes(a, inp, s)     # uint8 CHW, B,G,R
        enc.stdin.write(pl[1].tobytes())    # G plane
        enc.stdin.write(pl[0].tobytes())    # B plane
        enc.stdin.write(pl[2].tobytes())    # R plane
        n += 1
        now = time.perf_counter()
        if now - prog_at[0] >= 0.25:
            prog_at[0] = now
            _prog(name, n, total, t0)

    enc.stdin.close()
    dec.wait()
    enc.wait()
    _prog(name, n, total, t0, final=True)
    if enc.returncode != 0:
        raise RuntimeError('ffmpeg encode failed for %s' % src)
    print('    %d frames in %.0fs' % (n, time.perf_counter() - t0),
          flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src-dir', required=True,
                    help='backup directory containing movie/*.alm')
    ap.add_argument('--dst-dir', required=True,
                    help='output directory for the HD .alm files')
    ap.add_argument('--ffmpeg', required=True, help='ffmpeg.exe path')
    ap.add_argument('--bitrate', default='12M')
    ap.add_argument('--max-width', type=int, default=0,
                    help='cap encoded width in px (even); used for the '
                         'Kagura/English build whose rebuilt PlayMovie '
                         'rejects MPEG-1 wider than ~1184 px')
    ap.add_argument('--cache-dir', default=None)
    a = ap.parse_args()

    mov_dir = os.path.join(a.src_dir, 'movie')
    movies = sorted(os.listdir(mov_dir)) if os.path.isdir(mov_dir) else []
    movies = [n for n in movies if n.lower().endswith('.alm')]
    n_gen = 0
    for name in movies:
        src = os.path.join(mov_dir, name)
        dst = os.path.join(a.dst_dir, name)
        ck = None
        if a.cache_dir:
            os.makedirs(a.cache_dir, exist_ok=True)
            ck = _cache_key(src, a.max_width)
            hit = os.path.join(a.cache_dir, ck)
            try:
                with open(hit, 'rb') as f:
                    blob = f.read()
            except OSError:
                blob = None  # missing or transiently locked: re-encode
            if blob is not None:
                os.makedirs(os.path.dirname(os.path.abspath(dst)),
                            exist_ok=True)
                with open(dst, 'wb') as o:
                    o.write(blob)
                print(L('  %s: キャッシュから再利用',
                        '  %s: 从缓存复用') % name)
                n_gen += 1
                continue
        print(L('  %s: HD化して再エンコード中 ...',
                '  %s: 正在高清化并重新编码 ...') % name)
        os.makedirs(a.dst_dir, exist_ok=True)
        tmp = dst + '.tmp'
        _upscale(a.ffmpeg, src, tmp, a.bitrate, name, a.max_width)
        os.replace(tmp, dst)
        n_gen += 1
        if ck is not None:
            try:
                with open(dst, 'rb') as f, open(hit + '.tmp', 'wb') as o:
                    o.write(f.read())
                os.replace(hit + '.tmp', hit)
            except OSError:
                pass  # cache is an optimisation; never fail the job
    print(L('  ムービー生成: %d 本', '  影片生成: %d 部') % n_gen)
    if n_gen == 0:
        print(L('  （バックアップに movie/*.alm が無いため'
                '何もしませんでした）',
                '  （备份中没有 movie/*.alm，未执行任何操作）'))


if __name__ == '__main__':
    main()
