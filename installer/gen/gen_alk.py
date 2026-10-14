# -*- coding: utf-8 -*-
"""Regenerate AliceLogo3.alk at install time from the user's original
archive: decode each QNT entry, upscale 2x with the audited per-entry
recipe, re-encode, and repack the ALK container.

ALK0 layout: 'ALK0' u32 count / (u32 offset, u32 size) x count / data.
size=0 entries are empty placeholders and are preserved as-is.
"""
import argparse
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


def read_alk(path):
    d = open(path, 'rb').read()
    magic, count = struct.unpack_from('<4sI', d, 0)
    if magic != b'ALK0':
        raise ValueError('not an ALK0 archive: %s' % path)
    ents = []
    for i in range(count):
        off, size = struct.unpack_from('<II', d, 8 + i * 8)
        ents.append(d[off:off + size] if size else b'')
    return ents


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
    ap.add_argument('--src', required=True, help='original AliceLogo3.alk')
    ap.add_argument('--dst', required=True, help='output AliceLogo3.alk')
    ap.add_argument('--recipes',
                    default=os.path.join(os.path.dirname(
                        os.path.abspath(__file__)), 'alk_recipes.json'))
    a = ap.parse_args()

    recipes = json.load(open(a.recipes))
    entries = read_alk(a.src)
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
            up, want_alpha, x=x * 2, y=y * 2, level=6)
        n_gen += 1
        print('entry %3d %-9s %dx%d -> %dx%d' %
              (i, rec, img.width, img.height, up.width, up.height))
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    write_alk(entries, a.dst)
    print('alk: %d generated, %d passthrough, %d entries -> %s' %
          (n_gen, n_pass, len(entries), a.dst))


if __name__ == '__main__':
    main()
