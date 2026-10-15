# -*- coding: utf-8 -*-
"""Regenerate an AliceLogo*.alk at install time from the user's original
archive: decode each QNT entry, upscale 2x with the audited per-entry
recipe, re-encode, and repack the ALK container.

ALK0 layout: 'ALK0' u32 count / (u32 offset, u32 size) x count / data.
size=0 entries are empty placeholders and are preserved as-is.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.environ.setdefault('GEN_MODEL', os.path.join(_HERE, 'model.onnx'))

import gen_audit as ga
import gen_recipes as gr
import qnt_fast

# UI language for console output (GEN_LANG, same scheme as gen_ring).
_LANG = os.environ.get('GEN_LANG', 'ja')


def L(ja, zh):
    return zh if _LANG == 'zh' else ja


def read_alk(d):
    magic, count = struct.unpack_from('<4sI', d, 0)
    if magic != b'ALK0':
        raise ValueError('not an ALK0 archive')
    ents = []
    for i in range(count):
        off, size = struct.unpack_from('<II', d, 8 + i * 8)
        ents.append(d[off:off + size] if size else b'')
    return ents


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def _cache_key(src_bytes):
    """Same scheme as gen_ring: generator version + model identity +
    the exact source bytes. Whole-output caching is enough here since
    the .alk is a single fixed archive."""
    tag = 'v1:'
    model = os.environ.get('GEN_MODEL')
    if model and os.path.exists(model):
        tag += _sha256_file(model)
    h = hashlib.sha256(tag.encode())
    h.update(b'alk\0')
    h.update(src_bytes)
    return h.hexdigest()


def write_alk(entries, out):
    buf = bytearray(b'ALK0' + struct.pack('<I', len(entries)))
    tab = len(buf)
    buf += b'\x00' * 8 * len(entries)
    for i, e in enumerate(entries):
        struct.pack_into('<II', buf, tab + i * 8, len(buf), len(e))
        buf += e
    with open(out, 'wb') as f:
        f.write(bytes(buf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='original AliceLogo*.alk')
    ap.add_argument('--dst', required=True, help='output AliceLogo*.alk')
    ap.add_argument('--recipes',
                    default=os.path.join(os.path.dirname(
                        os.path.abspath(__file__)), 'alk_recipes.json'))
    ap.add_argument('--cache-dir', default=None,
                    help='persistent whole-output cache directory '
                         '(shared with gen_ring --cache-dir)')
    a = ap.parse_args()

    label = os.path.splitext(os.path.basename(a.dst))[0]
    raw = open(a.src, 'rb').read()
    ck = None
    if a.cache_dir:
        os.makedirs(a.cache_dir, exist_ok=True)
        ck = _cache_key(raw)
        hit = os.path.join(a.cache_dir, ck)
        try:
            with open(hit, 'rb') as f:
                blob = f.read()
        except OSError:
            blob = None  # missing or transiently locked: regenerate
        if blob is not None:
            os.makedirs(os.path.dirname(os.path.abspath(a.dst)),
                        exist_ok=True)
            with open(a.dst, 'wb') as o:
                o.write(blob)
            print(L('  %s.alk: キャッシュから再利用',
                    '  %s.alk: 从缓存复用') % label)
            return

    recipes = json.load(open(a.recipes))
    entries = read_alk(raw)
    # progress bar over the image entries (same style as gen_ring)
    n_img = sum(1 for e in entries if e and e[:4] == b'QNT\x00')
    is_tty = sys.stdout.isatty()
    bar_len = [0]

    def show(i, final=False):
        frac = i / max(1, n_img)
        bar = ('#' * int(frac * 28)).ljust(28, '-')
        line = '  %s [%s] %d/%d %5.1f%%' % (
            label, bar, i, n_img, frac * 100.0)
        if is_tty:
            pad = max(0, bar_len[0] - len(line))
            bar_len[0] = len(line)
            sys.stdout.write('\r' + line + ' ' * pad)
            sys.stdout.flush()
            if final:
                sys.stdout.write('\n')
        elif final or i % 20 == 0:
            print(line, flush=True)

    n_gen = n_pass = 0
    for i, e in enumerate(entries):
        if not e:
            continue
        if e[:4] != b'QNT\x00':
            n_pass += 1
            continue  # non-image payload: keep verbatim
        x, y = struct.unpack_from('<II', e, 0x0C)
        want_alpha = struct.unpack_from('<I', e, 0x28)[0] > 0
        img = ga.to_img(e)
        rec = recipes.get(str(i), 'ai')
        up = gr.apply(rec, img)
        entries[i] = qnt_fast.encode_pil(
            up, want_alpha, x=x * 2, y=y * 2,
            level=int(os.environ.get('GEN_QNT_LEVEL', '3')))
        n_gen += 1
        show(n_gen)
    show(n_gen, final=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    write_alk(entries, a.dst)
    print(L('  %s.alk: 生成 %d コマ / 素通し %d / 計 %d エントリ',
            '  %s.alk: 生成 %d 帧 / 原样保留 %d / 共 %d 项')
          % (label, n_gen, n_pass, len(entries)))
    if ck is not None:
        try:
            tmp = os.path.join(a.cache_dir, ck + '.tmp')
            with open(a.dst, 'rb') as f, open(tmp, 'wb') as o:
                o.write(f.read())
            os.replace(tmp, os.path.join(a.cache_dir, ck))
        except OSError:
            pass  # cache is an optimisation; never fail the job


if __name__ == '__main__':
    main()
