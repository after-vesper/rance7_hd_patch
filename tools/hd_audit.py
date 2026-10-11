"""HD asset audit: compare a patched ALD against the pristine original and
report per-entry scale ratios (same / 2x / 4x / other).

Usage:
    python tools/hd_audit.py <patched.ald> <original.ald> [--write-manifest out.json]

The manifest records every entry currently at exactly 2x so that future
upscale batches can skip them (never upscale twice).
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ald import list_entries  # noqa: E402


def qnt_sizes(path):
    """{cg_number: (w, h)} read from QNT headers only."""
    data = open(path, 'rb').read()
    out = {}
    for pos, hsize, dsize, name, _ in list_entries(data):
        if not name.lower().endswith('.qnt'):
            continue
        num = name[2:-4]
        if not num.isdigit():
            continue
        d = data[pos + hsize:pos + hsize + 64]
        if d[:4] != b'QNT\x00':
            continue
        _, _, w, h, _ = struct.unpack_from('<IIIII', d, 0x0C)
        out[int(num)] = (w, h)
    return out


def audit(patched, original):
    """Classify entries present in both archives by scale ratio."""
    orig = qnt_sizes(original)
    cur = qnt_sizes(patched)
    res = {'same': [], '2x': [], '4x': [], 'other': [], 'new': []}
    for k in sorted(set(cur) | set(orig)):
        c = cur.get(k)
        o = orig.get(k)
        if o is None:
            res['new'].append(k)
        elif c == o:
            res['same'].append(k)
        elif c == (o[0] * 2, o[1] * 2):
            res['2x'].append(k)
        elif c == (o[0] * 4, o[1] * 4):
            res['4x'].append(k)
        else:
            res['other'].append((k, o, c))
    return res


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    write_manifest = '--write-manifest' in sys.argv
    out_path = args[2] if len(args) > 2 else 'work/upscaled.json'
    res = audit(args[0], args[1])
    print('same:', len(res['same']), '2x:', len(res['2x']),
          '4x:', len(res['4x']), 'other:', len(res['other']),
          'new:', len(res['new']))
    if res['4x']:
        print('4x entries:', res['4x'])
    if res['other']:
        print('other:', res['other'][:50])
    if write_manifest:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        manifest = {'ald': os.path.basename(args[0]), 'upscaled_2x': res['2x']}
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=0)
        print('manifest ->', out_path)


if __name__ == '__main__':
    main()
