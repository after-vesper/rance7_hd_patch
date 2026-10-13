"""Export the installer asset payload from the live (HD) game archives.

Produces ``installer/data/``:

    manifest.json            archive -> shared/jp/vanilla entry lists + loose files
    hd_sites.json            AIN anchor table (copied from tools/)
    GM/shared/*.QNT|AJP      payloads whose source is identical in vanilla & jp
    GM/jp/  GM/vanilla/      payloads for entries whose source differs by variant
    GA/...                   same split for Rance7GA.ald (incl. added entries)
    files/AliceLogo3.alk     whole-file replacements (base identical in all variants)
    files/AliceLogo3.dll

jp payloads are taken verbatim from the live archives (AI-upscaled set).
vanilla payloads are generated here as exact NEAREST 2x of the vanilla
source QNTs, so non-R18 installs never receive jp-derived imagery.

Usage: python tools/export_payload.py [--out installer/data]
"""

import argparse
import hashlib
import json
import mmap
import os
import re
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ald  # noqa: E402
import qnt  # noqa: E402

GAME = 'game'
VAN = 'vanilla'
JP = 'jp'

ARCHIVES = {
    'Rance7GM.ald': ('GM', 12),
    'Rance7GA.ald': ('GA', 0),
}

LOOSE_FILES = ['AliceLogo3.alk', 'DLL/AliceLogo3.dll']


def open_ald(path):
    f = open(path, 'rb')
    data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    return f, data


def entry_map(data):
    out = {}
    for pos, hs, ds, name, _ in ald.list_entries(data):
        out[name] = (pos, hs, ds)
    return out


def payload_sha1(data, e):
    pos, hs, ds = e
    return hashlib.sha1(data[pos + hs:pos + hs + ds]).digest()


def payload_bytes(data, e):
    pos, hs, ds = e
    return bytes(data[pos + hs:pos + hs + ds])


def src_same(v_map, v_data, j_map, j_data, name):
    """True when the entry's 1x source is byte-identical in vanilla and jp."""
    if name not in v_map or name not in j_map:
        return False
    return payload_sha1(v_data, v_map[name]) == \
        payload_sha1(j_data, j_map[name])


def nearest2x_qnt(payload):
    """Exact 2x upscale of a QNT payload (offsets doubled too)."""
    x, y = struct.unpack_from('<II', payload, 0x0C)
    w, h, ch, px = qnt.decode(payload)
    try:
        from PIL import Image
    except ImportError:
        sys.exit('Pillow is required: pip install pillow')
    mode = 'RGBA' if ch == 4 else 'RGB'
    raw = 'BGRA' if ch == 4 else 'BGR'
    im = Image.frombytes(mode, (w, h), px, 'raw', raw)
    im = im.resize((w * 2, h * 2), Image.NEAREST)
    if ch == 4:
        full = im.tobytes('raw', 'BGRA')
        bgr = bytearray(len(full) // 4 * 3)
        alp = bytearray(len(full) // 4)
        bgr[0::3] = full[0::4]
        bgr[1::3] = full[1::4]
        bgr[2::3] = full[2::4]
        alp[0::1] = full[3::4]
        return qnt.encode(w * 2, h * 2, bytes(bgr), bytes(alp), x * 2, y * 2)
    bgr = im.tobytes('raw', 'BGR')
    return qnt.encode(w * 2, h * 2, bgr, None, x * 2, y * 2)


def write_payload(out_dir, name, data):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, name), 'wb') as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='installer/data')
    args = ap.parse_args()
    out = args.out

    lives, vmaps, jmaps = {}, {}, {}
    vdatas, jdatas, ldatas = {}, {}, {}
    for fname, (sub, _disk) in ARCHIVES.items():
        lf, ldata = open_ald(os.path.join(GAME, fname))
        vf, vdata = open_ald(os.path.join(VAN, fname))
        jf, jdata = open_ald(os.path.join(JP, fname))
        lives[fname] = (lf, ldata, entry_map(ldata))
        vmaps[fname], vdatas[fname] = vmap = entry_map(vdata), vdata
        jmaps[fname], jdatas[fname] = jmap = entry_map(jdata), jdata
        ldatas[fname] = ldata

    manifest = {'archives': {}, 'files': [], 'ain_sites': 'hd_sites.json',
                'resolution': {'ViewWidth': 1600, 'ViewHeight': 1200}}

    n_shared = n_jp = n_van = 0
    for fname, (sub, disk) in ARCHIVES.items():
        ldata = lives[fname][1]
        lmap = lives[fname][2]
        diff = json.load(open(f'work/asset_diff_{fname}.json'))
        changed, added = set(diff['changed']), set(diff['added'])

        # For source comparison, GA-added names resolve through GM.
        vgm_map, vgm_data = vmaps['Rance7GM.ald'], vdatas['Rance7GM.ald']
        jgm_map, jgm_data = jmaps['Rance7GM.ald'], jdatas['Rance7GM.ald']

        def src_identical(name, exists_in_archive):
            vm = vmaps[fname] if exists_in_archive else vgm_map
            vd = vdatas[fname] if exists_in_archive else vgm_data
            jm = jmaps[fname] if exists_in_archive else jgm_map
            jd = jdatas[fname] if exists_in_archive else jgm_data
            return src_same(vm, vd, jm, jd, name)

        shared, jp_only, van_only = [], [], []
        for name in sorted(changed):
            if src_identical(name, True):
                shared.append(name)
            else:
                jp_only.append(name)
                van_only.append(name)
        for name in sorted(added):
            if src_identical(name, False):
                shared.append(name)
            else:
                jp_only.append(name)
                van_only.append(name)

        for name in shared + jp_only:
            write_payload(os.path.join(
                out, sub, 'shared' if name in set(shared) else 'jp'),
                name, payload_bytes(ldata, lmap[name]))
        n_shared += len(shared)
        n_jp += len(jp_only)

        for name in van_only:
            if name in vmaps[fname]:
                src = payload_bytes(vdatas[fname], vmaps[fname][name])
            elif name in vgm_map:
                src = payload_bytes(vgm_data, vgm_map[name])
            else:
                sys.exit(f'{fname}: no vanilla source for {name}')
            if not src[:4] == b'QNT\x00':
                sys.exit(f'{fname}: vanilla source {name} is not QNT')
            write_payload(os.path.join(out, sub, 'vanilla'), name,
                          nearest2x_qnt(src))
            n_van += 1

        manifest['archives'][fname] = {
            'dir': sub, 'disk': disk,
            'shared': shared, 'jp': jp_only, 'vanilla': van_only,
        }
        print(f'{fname}: shared={len(shared)} jp={len(jp_only)} '
              f'vanilla={len(van_only)}')

    # Loose files (identical base across variants -> whole-file replace)
    for rel in LOOSE_FILES:
        dst = os.path.join(out, 'files', rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(GAME, rel), dst)
        manifest['files'].append({'src': f'files/{rel}', 'dst': rel})

    shutil.copy2('tools/hd_sites.json', os.path.join(out, 'hd_sites.json'))
    with open(os.path.join(out, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=1)

    print(f'done: shared={n_shared} jp={n_jp} vanilla={n_van} -> {out}')


if __name__ == '__main__':
    main()
