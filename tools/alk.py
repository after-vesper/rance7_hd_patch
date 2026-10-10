"""ALK0 (AliceSoft プラグインデータアーカイブ) の展開/再パック。

フォーマット (AliceLogo3.alk 実測):
    [先頭] 'ALK0' u32 count / (u32 offset, u32 size) x count / データ連結
    データは無アライン連続配置。size=0 は「次エントリと同じ物」扱い。

使い方:
    python tools/alk.py list    <alk>
    python tools/alk.py extract <alk> <outdir>     # エントリを entry%03d.qnt で保存
    python tools/alk.py pack    <indir> <out.alk>  # entry%03d.* を番号順に再パック
"""
import os
import struct
import sys


def read_entries(path):
    d = open(path, 'rb').read()
    magic, count = struct.unpack_from('<4sI', d, 0)
    if magic != b'ALK0':
        raise ValueError('not ALK0')
    o = 8
    ents = []
    for _ in range(count):
        off, size = struct.unpack_from('<II', d, o)
        o += 8
        ents.append(d[off:off + size] if size else b'')
    return ents


def cmd_list(path):
    for i, e in enumerate(read_entries(path)):
        sig = e[:4]
        info = ''
        if sig == b'QNT\x00':
            x, y, w, h, bpp = struct.unpack_from('<IIIII', e, 0x0C)
            info = f'{w}x{h} @{x},{y}'
        print(f'{i:3d} {len(e):8d} {sig!r} {info}')


def cmd_extract(path, outdir):
    os.makedirs(outdir, exist_ok=True)
    for i, e in enumerate(read_entries(path)):
        ext = '.qnt' if e[:4] == b'QNT\x00' else '.bin'
        open(os.path.join(outdir, f'entry{i:03d}{ext}'), 'wb').write(e)


def cmd_pack(indir, out):
    files = sorted(f for f in os.listdir(indir) if f.startswith('entry'))
    ents = [open(os.path.join(indir, f), 'rb').read() for f in files]
    outb = bytearray(b'ALK0' + struct.pack('<I', len(ents)))
    tab = len(outb)
    outb += b'\x00' * 8 * len(ents)
    for i, e in enumerate(ents):
        struct.pack_into('<II', outb, tab + i * 8, len(outb), len(e))
        outb += e
    open(out, 'wb').write(bytes(outb))
    print(f'{len(ents)} エントリ -> {out}')


if __name__ == '__main__':
    c = sys.argv[1]
    if c == 'list':
        cmd_list(sys.argv[2])
    elif c == 'extract':
        cmd_extract(sys.argv[2], sys.argv[3])
    elif c == 'pack':
        cmd_pack(sys.argv[2], sys.argv[3])
