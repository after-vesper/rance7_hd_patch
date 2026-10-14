"""ALD (AliceSoft System アーカイブ) の一覧/展開/作成。

フォーマット概要 (libsys4 ald.c / GARbro ArcALD.cs 準拠):

    [ポインタテーブル] 3バイトLEエントリの配列。エントリ0はテーブル自身の
        セクタ数、以降は各ファイルの先頭オフセット(256B単位)。
        末尾に終端エントリ(次のオフセット)が1つ必要。
    [リンクテーブル(ファイルマップ)] 3バイトLEエントリの配列。
        ファイル番号(ファイル名の数値部分)でインデックスされ、
        entry = (disk番号+1, そのdiskのポインタ表index+1)。
    [ファイルデータ] 各256B境界: u32 header_size / u32 data_size /
        ファイル名(CP932, header_size-16バイト) / データ本体
    [フッタ16B] 'NL\\x01\\x00' / u32 0x10 / u8 自disk番号+1 /
        u16 ファイル数(@+9) / 0パディング

使い方:
    python tools/ald.py list    <ald>
    python tools/ald.py extract <ald> <outdir>
    python tools/ald.py pack    <indir> <out.ald> [--map-from <ald>] [--disk N]
"""

import mmap
import os
import re
import struct
import sys


def _u24(b, off):
    return b[off] | (b[off + 1] << 8) | (b[off + 2] << 16)


def list_entries(data):
    """(オフセット, header_size, data_size, 名前) のリストを返す。"""
    ptr_secs = _u24(data, 0)
    n = (ptr_secs * 256) // 3
    entries = []
    for i in range(1, n):
        sec = _u24(data, i * 3)
        if sec == 0:
            break
        pos = sec << 8
        hsize, dsize = struct.unpack_from('<II', data, pos)
        extra = data[pos + 8:pos + 0x10]
        name = data[pos + 0x10:pos + hsize].split(b'\x00')[0]
        entries.append((pos, hsize, dsize, name.decode('cp932', 'replace'), extra))
    return entries


def read_link_table(data):
    """リンクテーブルを [(disk, ptr), ...] で返す (file番号順)。"""
    ptr_secs = _u24(data, 0)
    link_end = _u24(data, 3)
    lt = data[ptr_secs * 256:link_end * 256]
    n = len(lt) // 3
    return [(lt[i * 3] - 1, (lt[i * 3 + 1] | (lt[i * 3 + 2] << 8)) - 1)
            for i in range(n)]


def file_number(name):
    """ファイル名の数値部分をファイル番号として取り出す。無ければ None。"""
    m = re.search(r'(\d+)', os.path.splitext(name)[0])
    return int(m.group(1)) if m else None


def pack(files, out_path, disk=0, link_map=None, map_size=0, extras=None):
    """files: [(アーカイブ内名, データbytes), ...] を .ald として書き出す。

    disk: このアーカイブの disk 番号 (サフィックス文字 A=0, B=1, ...)
    link_map: file番号 -> (disk, ptr) の辞書。None なら同梱ファイルを
              file番号から自動生成する。
    map_size: リンクテーブルのエントリ数 (0 なら自動)。
    extras: ファイル名 -> ヘッダ+8の8バイトフィールド (元アーカイブから
            引き継ぐ場合に使用)。未指定は 0。
    """
    extras = extras or {}
    files = [(n.encode('cp932'), d) for n, d in files]
    count = len(files)

    # ポインタテーブル: エントリ0=テーブルサイズ、1..count=各ファイル位置、
    # さらに終端として「最終ファイルの次」を1エントリ
    ptr_secs = ((count + 2) * 3 + 255) // 256

    # リンクテーブル
    if link_map is None:
        link_map = {}
        for i, (name, _) in enumerate(files):
            no = file_number(name.decode('cp932'))
            if no is not None:
                link_map[no] = (disk, i)
    if map_size <= 0:
        map_size = max(link_map, default=-1) + 1
    lt = bytearray(map_size * 3)
    for no, (dsk, ptr) in link_map.items():
        if no >= map_size:
            raise ValueError(f'map_size不足: fileno {no}')
        lt[no * 3] = dsk + 1
        lt[no * 3 + 1] = (ptr + 1) & 0xFF
        lt[no * 3 + 2] = ((ptr + 1) >> 8) & 0xFF
    map_secs = (len(lt) + 255) // 256
    data_start_sec = ptr_secs + map_secs

    # ファイルデータ配置
    pos = data_start_sec << 8
    offsets = []
    body = bytearray()
    for name, payload in files:
        offsets.append(pos >> 8)
        # 名前フィールドは16バイト単位でパディング (原本と同様)
        hdr_size = 0x10 + max(16, (len(name) + 16) & ~15)
        extra = extras.get(name.decode('cp932'), b'\x00' * 8)
        body += struct.pack('<II', hdr_size, len(payload)) + extra
        body += name.ljust(hdr_size - 0x10, b'\x00') + payload
        pos += (hdr_size + len(payload) + 255) & ~255
        body += b'\x00' * (-len(body) % 256)
    offsets.append(pos >> 8)  # 終端 (末尾エントリの ptr+1 参照用)

    # ポインタテーブル書き出し
    pt = bytearray()
    pt += ptr_secs.to_bytes(3, 'little')
    for off in offsets:
        pt += off.to_bytes(3, 'little')
    pt += b'\x00' * (ptr_secs * 256 - len(pt))

    # フッタ (disk番号+1, ファイル数)
    footer = struct.pack('<4sI', b'NL\x01\x00', 0x10)
    footer += bytes([disk + 1]) + struct.pack('<H', count) + b'\x00\x00\x00\x00\x00'

    with open(out_path, 'wb') as f:
        f.write(pt)
        f.write(lt.ljust(map_secs * 256, b'\x00'))
        f.write(body)
        f.write(footer)
    return count


def update_in_place(path, payloads):
    """既存エントリを同名ペイロードでその場差し替えする (差分デプロイ用)。

    新データが元スロットに収まればその場で上書き、収まらなければ
    データ領域末尾に追記してポインタ表エントリと終端だけ更新する。
    リンクテーブル(位置index参照)とフッタの件数は変わらない。
    追記した分だけ旧スロットがデッド領域化するため、繰り返すと
    アーカイブが膨らむ点に注意 (定期的に pack で再構築すれば圧縮される)。

    payloads: {アーカイブ内名: bytes}。戻り値: {name: 'inplace'|'appended'}。
    """
    results = {}
    f = open(path, 'r+b')
    mm = mmap.mmap(f.fileno(), 0)
    try:
        entries = list_entries(mm)
        # list_entries は終端(フッタ位置を指す疑似エントリ)も返す。
        # 実ファイルは名前が空でないエントリで、idx はポインタ表index-1。
        real = [(idx, e) for idx, e in enumerate(entries) if e[3]]
        count = len(real)
        offs = [_u24(mm, i * 3) << 8 for i in range(1, count + 2)]
        term = offs[-1]
        if term + 16 != len(mm) or bytes(mm[term:term + 4]) != b'NL\x01\x00':
            raise ValueError(f'{path}: フッタ位置がデータ終端と一致しません')
        footer = bytes(mm[term:term + 16])
        jobs = [(idx, pos, hsize, name) for idx, (pos, hsize, dsize, name, _)
                in real if name in payloads]
        missing = set(payloads) - {n for _, _, _, n in jobs}
        headers = {name: bytearray(mm[pos:pos + hsize])
                   for _, pos, hsize, name in jobs}
    finally:
        mm.close()
    if missing:
        raise ValueError(f'{path}: エントリが見つかりません: {sorted(missing)}')

    for idx, pos, hsize, name in jobs:
        payload = payloads[name]
        hdr = headers[name]
        struct.pack_into('<I', hdr, 4, len(payload))
        need = hsize + len(payload)
        slot_end = min((o for o in offs if o > pos), default=term)
        if need <= slot_end - pos:
            f.seek(pos)
            f.write(hdr)
            f.write(payload)
            pad = slot_end - pos - need
            if pad:
                f.write(b'\x00' * pad)
            results[name] = 'inplace'
        else:
            new_pos = term
            f.seek(new_pos)
            f.write(hdr)
            f.write(payload)
            end = new_pos + need
            new_term = (end + 255) & ~255
            f.write(b'\x00' * (new_term - end))
            f.write(footer)
            f.seek((idx + 1) * 3)
            f.write((new_pos >> 8).to_bytes(3, 'little'))
            f.seek((count + 1) * 3)
            f.write((new_term >> 8).to_bytes(3, 'little'))
            offs[idx] = new_pos
            offs[-1] = term = new_term
            results[name] = 'appended'
    f.close()
    return results


def read_extras(data):
    """ファイル名 -> ヘッダ+8の8バイト の辞書を返す。"""
    return {name: extra for _, _, _, name, extra in list_entries(data) if name}


def cmd_list(path):
    data = open(path, 'rb').read()
    for pos, hsize, dsize, name, _ in list_entries(data):
        print(f'{pos:#10x} {dsize:>10} {name}')


def cmd_extract(path, outdir):
    data = open(path, 'rb').read()
    os.makedirs(outdir, exist_ok=True)
    for pos, hsize, dsize, name, _ in list_entries(data):
        if not name:
            continue
        payload = data[pos + hsize:pos + hsize + dsize]
        out = os.path.join(outdir, name)
        with open(out, 'wb') as f:
            f.write(payload)
        print(name)


def cmd_pack(indir, out_path, map_from=None, disk=0):
    files = []
    for fn in sorted(os.listdir(indir)):
        p = os.path.join(indir, fn)
        if os.path.isfile(p):
            files.append((fn, open(p, 'rb').read()))
    link_map = None
    map_size = 0
    extras = None
    if map_from:
        src = open(map_from, 'rb').read()
        table = read_link_table(src)
        map_size = len(table)
        link_map = {no: v for no, v in enumerate(table) if v[0] >= 0}
        extras = read_extras(src)
    n = pack(files, out_path, disk=disk, link_map=link_map,
             map_size=map_size, extras=extras)
    print(f'{out_path}: {n} files')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'list':
        cmd_list(sys.argv[2])
    elif cmd == 'extract':
        cmd_extract(sys.argv[2], sys.argv[3])
    elif cmd == 'update':
        # ald update <ald> <indir> [名前...] : indir内のペイロードファイルで
        # 同名エントリをその場差し替え (指定時は名前フィルタ)
        ald_path, indir = sys.argv[2], sys.argv[3]
        only = set(sys.argv[4:])
        payloads = {}
        for fn in sorted(os.listdir(indir)):
            p = os.path.join(indir, fn)
            if os.path.isfile(p) and (not only or fn in only):
                payloads[fn] = open(p, 'rb').read()
        res = update_in_place(ald_path, payloads)
        for n, how in res.items():
            print(f'{n}: {how}')
    elif cmd == 'pack':
        map_from = disk = None
        args = sys.argv[2:]
        if '--map-from' in args:
            i = args.index('--map-from')
            map_from = args[i + 1]
            del args[i:i + 2]
        if '--disk' in args:
            i = args.index('--disk')
            disk = int(args[i + 1])
            del args[i:i + 2]
        cmd_pack(args[0], args[1], map_from=map_from, disk=disk or 0)
    else:
        print(__doc__)
        sys.exit(1)
