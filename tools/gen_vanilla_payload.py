# -*- coding: utf-8 -*-
"""Generate the vanilla-variant payload set.

Extracts the vanilla-source QNTs for every entry listed in
manifest.json's `vanilla` arrays, decodes them to PNG in
work/van_src/, and (after ForgeNeo upscaling to work/van_hd/)
encodes them back to QNT payloads under installer/data/*/vanilla/.

Usage:
    python work/gen_vanilla_payload.py extract     # build work/van_src
    python work/gen_vanilla_payload.py encode      # work/van_hd -> data
"""
import json
import mmap
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import ald  # noqa: E402
import hdpatch  # noqa: E402
import qnt  # noqa: E402

SRC_DIR = 'work/van_src'
HD_DIR = 'work/van_hd'
MANIFEST = 'work/van_manifest.json'
INSTALLER_MANIFEST = 'installer/data/manifest.json'


def open_ald(path):
    f = open(path, 'rb')
    d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    return d, {e[3]: e[:3] for e in ald.list_entries(d) if e[3]}


def targets(src_dir):
    """src_dir: directory holding PRISTINE vanilla ALDs (the backup
    folder, not the live-patched vanilla/)."""
    m = json.load(open(INSTALLER_MANIFEST))
    out = {}
    gm = os.path.join(src_dir, 'Rance7GM.ald')
    ga = os.path.join(src_dir, 'Rance7GA.ald')
    for name in m['archives']['Rance7GM.ald']['vanilla']:
        out[name] = (gm, 'GM/vanilla')
    for name in m['archives']['Rance7GA.ald']['vanilla']:
        # GA-added names were relocated from GM; GA-changed names come
        # from GA itself. Prefer GA when the entry exists there.
        out[name] = (ga, 'GA/vanilla')
    return out, gm, ga


def cmd_extract():
    src_dir = sys.argv[2] if len(sys.argv) > 2 else 'vanilla/backup'
    if not os.path.isdir(src_dir):
        # pick newest backup dir
        src_dir = sorted(
            e.path for e in os.scandir(src_dir) if e.is_dir())[-1]
    tg, gm, ga = targets(src_dir)
    alds = {}
    meta = {}
    os.makedirs(SRC_DIR, exist_ok=True)
    for name, (ald_path, dst) in sorted(tg.items()):
        if ald_path not in alds:
            alds[ald_path] = open_ald(ald_path)
        d, em = alds[ald_path]
        if name not in em:
            # GA-added name: its vanilla source lives in GM
            if gm not in alds:
                alds[gm] = open_ald(gm)
            d, em = alds[gm]
        if name not in em:
            sys.exit(f'no vanilla source for {name}')
        pos, hs, ds = em[name]
        payload = bytes(d[pos + hs:pos + hs + ds])
        png = os.path.join(SRC_DIR, os.path.splitext(name)[0] + '.png')
        w, h, ch, _px = qnt.decode(payload)
        bpp = ch * 8
        if not os.path.exists(png):
            hdpatch.qnt_to_png(payload, png)
        x, y = struct.unpack_from('<II', payload, 0x0C)
        meta[name] = {'bpp': bpp, 'x': x, 'y': y, 'w': w, 'h': h,
                      'dst': dst}
    json.dump(meta, open(MANIFEST, 'w'), indent=0)
    print(f'extracted {len(meta)} sources -> {SRC_DIR}')
    print(f'next: python tools/forge_upscale.py {SRC_DIR} {HD_DIR} '
          f'--jobs 2')


def cmd_encode():
    meta = json.load(open(MANIFEST))
    done = missing = 0
    for name, info in sorted(meta.items()):
        png = os.path.join(
            HD_DIR, os.path.splitext(name)[0] + '.png')
        if not os.path.exists(png):
            missing += 1
            continue
        out = os.path.join('installer/data', info['dst'], name)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        payload = hdpatch.png_to_qnt(
            png, info['bpp'] == 32, info['x'] * 2, info['y'] * 2)
        # sanity: payload dims must be exactly 2x source
        w2, h2 = struct.unpack_from('<II', payload, 0x14)
        if (w2, h2) != (info['w'] * 2, info['h'] * 2):
            sys.exit(f'{name}: dims {w2}x{h2} != 2x src '
                     f'{info["w"]}x{info["h"]}')
        open(out, 'wb').write(payload)
        done += 1
    print(f'encoded {done} payloads, missing {missing}')


if __name__ == '__main__':
    globals()['cmd_' + sys.argv[1]]()
