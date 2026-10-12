#!/usr/bin/env python3
"""HD アセットパッチ用パイプライン: .ald 内の QNT を展開・差し替え・再パックする。

使い方:
    python tools/hdpatch.py extract Rance7GM.ald work/gm_png
    python tools/hdpatch.py upscale work/gm_png work/gm_png_2x --scale 2
    python tools/hdpatch.py repack Rance7GM.ald work/gm_png_2x Rance7GM_new.ald
    python tools/hdpatch.py apply <ゲームdir>/Rance7GM.ald work/gm_png_2x

外部アップスケーラを使う場合は upscale に --cmd を指定:
    python tools/hdpatch.py upscale in_dir out_dir --scale 4 \
        --cmd "realesrgan-ncnn-vulkan -i {in} -o {out} -s {scale}"
"""

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ajp
import ald
import io
import qnt

try:
    from PIL import Image
except ImportError:
    Image = None


def _require_pil():
    if Image is None:
        sys.exit('Pillow が必要です: pip install Pillow')


def qnt_to_png(payload, path):
    """QNT ペイロードを PNG (RGBA/RGB) として保存。(w, h, bpp) を返す。"""
    _require_pil()
    w, h, ch, px = qnt.decode(payload)
    img = Image.frombytes('RGBA' if ch == 4 else 'RGB', (w, h), px, 'raw',
                          'BGRA' if ch == 4 else 'BGR')
    img.save(path)
    return w, h, ch * 8


def _extract_one(job):
    """ワーカー: (payload, path, name) -> manifest エントリ用タプル。"""
    payload, path, name = job
    if name.lower().endswith('.ajp'):
        img = ajp.decode_rgba(payload)
        img.save(path)
        return name, {'w': img.width, 'h': img.height,
                      'bpp': 32 if img.mode == 'RGBA' else 24}
    w, h, bpp = qnt_to_png(payload, path)
    x, y = struct.unpack_from('<II', payload, 0x0C)
    return name, {'w': w, 'h': h, 'bpp': bpp, 'x': x, 'y': y}


def _repack_one(job):
    """ワーカー: (kind, pngパス, manifest値, 原本bytes) -> 差し替えバイト列"""
    kind, png, info, orig = job
    if kind == 'ajp':
        # AJP: PNG -> JPEG(品質95) -> 原本ヘッダをテンプレートに再エンコード。
        # 原本に PM マスクがあれば PNG のアルファから再生成して保持する。
        from PIL import Image
        _, _, _, asec = ajp.decode(orig)
        img = Image.open(png)
        alpha = None
        if asec is not None:
            if img.mode != 'RGBA':
                raise ValueError(
                    '%s: original has alpha mask but PNG is %s'
                    % (png, img.mode))
            alpha = img.getchannel('A').tobytes()
        rgb = img.convert('RGB')
        buf = io.BytesIO()
        rgb.save(buf, 'JPEG', quality=95)
        return ajp.encode(img.width, img.height, buf.getvalue(),
                          alpha, orig)
    want_alpha = info.get('bpp', 24) == 32
    if not want_alpha:
        from PIL import Image
        want_alpha = Image.open(png).mode in ('RGBA', 'LA', 'PA')
    return png_to_qnt(png, want_alpha, info.get('x', 0), info.get('y', 0))


def png_to_qnt(path, want_alpha, x=0, y=0):
    """PNG を QNT v2 バイト列に変換。want_alpha=True なら32bppで出力。"""
    _require_pil()
    img = Image.open(path)
    if want_alpha:
        img = img.convert('RGBA')
        r, g, b, a = img.split()
        bgr = Image.merge('RGB', (b, g, r)).tobytes()
        return qnt.encode(img.width, img.height, bgr, a.tobytes(), x, y)
    img = img.convert('RGB')
    r, g, b = img.split()
    return qnt.encode(img.width, img.height,
                      Image.merge('RGB', (b, g, r)).tobytes(), None, x, y)


def cmd_extract(args):
    """ALD から QNT を PNG として展開し manifest.json を書き出す。"""
    data = open(args.ald, 'rb').read()
    entries = [e for e in sorted(ald.list_entries(data), key=lambda e: e[0])
               if e[3]]
    os.makedirs(args.outdir, exist_ok=True)
    jobs = []
    n_skip = 0
    pat = re.compile(args.filter, re.I) if args.filter else None
    for off, hsize, dsize, name, _ in entries:
        if (name.lower().endswith(('.qnt', '.ajp'))
                and (not pat or pat.search(name))):
            jobs.append((data[off + hsize:off + hsize + dsize],
                         os.path.join(args.outdir, name[:-4] + '.png'),
                         name))
        else:
            n_skip += 1
    manifest = {}
    done = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for name, info in ex.map(_extract_one, jobs, chunksize=4):
            manifest[name] = info
            done += 1
            if done % 200 == 0:
                print(f'{done}/{len(jobs)} 件展開...', flush=True)
    with open(os.path.join(args.outdir, 'manifest.json'), 'w',
              encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f'{len(jobs)} 件をPNG化、その他 {n_skip} 件スキップ -> {args.outdir}')


def _iter_pngs(indir):
    for fn in sorted(os.listdir(indir)):
        if fn.lower().endswith('.png'):
            yield fn


def _run_upscaler(args, src, dst):
    """外部コマンドまたは Pillow で画像を1枚アップスケールする。"""
    if args.cmd:
        cmd = (args.cmd.replace('{in}', src).replace('{out}', dst)
               .replace('{scale}', str(args.scale)))
        subprocess.run(cmd, shell=True, check=True)
    else:
        img = Image.open(src)
        resample = (Image.LANCZOS if args.method == 'lanczos'
                    else Image.NEAREST)
        img.resize((img.width * args.scale, img.height * args.scale),
                   resample).save(dst)


def _upscale_one_pil(job):
    """ワーカー: Pillow で1枚拡大。(src, dst, scale, method)"""
    src, dst, scale, method = job
    img = Image.open(src)
    resample = Image.LANCZOS if method == 'lanczos' else Image.NEAREST
    img.resize((img.width * scale, img.height * scale), resample).save(dst)


def _upscale_alpha_split(args, src, dst, tmpdir):
    """RGBA を RGB + グレースケールα に分割して個別に拡大し再合成する。

    外部アップスケーラが透過を保持しない場合に使う。アルファは
    滑らかなので Pillow (BICUBIC) で拡大する。
    """
    img = Image.open(src).convert('RGBA')
    rgb = img.convert('RGB')
    alpha = img.getchannel('A')
    rgb_tmp = os.path.join(tmpdir, 'rgb.png')
    rgb_up = os.path.join(tmpdir, 'rgb_up.png')
    rgb.save(rgb_tmp)
    _run_upscaler(args, rgb_tmp, rgb_up)
    up = Image.open(rgb_up).convert('RGB')
    a_up = alpha.resize((up.width, up.height), Image.BICUBIC)
    up.putalpha(a_up)
    up.save(dst)


def cmd_upscale(args):
    """PNG 群をアップスケール。--cmd 指定時は外部ツール、無指定は Pillow。"""
    _require_pil()
    os.makedirs(args.outdir, exist_ok=True)
    tmpdir = os.path.join(args.outdir, '.tmp_alpha')

    if not args.cmd and not args.alpha_split:
        # Pillow 単体パスは並列化できる
        jobs = [(os.path.join(args.indir, fn), os.path.join(args.outdir, fn),
                 args.scale, args.method) for fn in _iter_pngs(args.indir)]
        n = 0
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for _ in ex.map(_upscale_one_pil, jobs, chunksize=8):
                n += 1
                if n % 200 == 0:
                    print(f'{n}/{len(jobs)} 件処理...', flush=True)
    else:
        n = 0
        for fn in _iter_pngs(args.indir):
            src = os.path.join(args.indir, fn)
            dst = os.path.join(args.outdir, fn)
            if args.alpha_split and Image.open(src).mode == 'RGBA':
                os.makedirs(tmpdir, exist_ok=True)
                _upscale_alpha_split(args, src, dst, tmpdir)
            else:
                _run_upscaler(args, src, dst)
            n += 1
            if n % 100 == 0:
                print(f'{n} 件処理...', flush=True)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # manifest も引き継ぐ
    mf = os.path.join(args.indir, 'manifest.json')
    if os.path.exists(mf):
        shutil.copy2(mf, os.path.join(args.outdir, 'manifest.json'))
    print(f'{n} 件 -> {args.outdir}')


def _load_manifest(pngdir):
    mf = os.path.join(pngdir, 'manifest.json')
    if os.path.exists(mf):
        with open(mf, encoding='utf-8') as f:
            return json.load(f)
    return {}


def repack_ald(ald_path, pngdir, out_path, njobs=None):
    """原本 ALD を読み、pngdir に同名 PNG があれば QNT を差し替えて再パック。"""
    data = open(ald_path, 'rb').read()
    entries = [e for e in sorted(ald.list_entries(data), key=lambda e: e[0])
               if e[3]]
    manifest = _load_manifest(pngdir)
    footer = data[-12:]
    disk = footer[4] - 1

    # 差し替え対象の PNG → QNT 変換を並列実行
    jobs = []
    for off, hsize, dsize, name, _ in entries:
        png = os.path.join(pngdir, os.path.splitext(name)[0] + '.png')
        if name.lower().endswith('.qnt') and os.path.exists(png):
            jobs.append(('qnt', name, png, manifest.get(name, {}), None))
        elif name.lower().endswith('.ajp') and os.path.exists(png):
            orig = data[off + hsize:off + hsize + dsize]
            jobs.append(('ajp', name, png, {}, orig))
    payloads = {}
    if jobs:
        with ProcessPoolExecutor(max_workers=njobs) as ex:
            done = 0
            for name, payload in zip(
                    (j[1] for j in jobs),
                    ex.map(_repack_one,
                           [(j[0], j[2], j[3], j[4]) for j in jobs], chunksize=4)):
                payloads[name] = payload
                done += 1
                if done % 200 == 0:
                    print(f'{done}/{len(jobs)} 件変換...', flush=True)

    files = []
    replaced = 0
    for off, hsize, dsize, name, _ in entries:
        if name in payloads:
            files.append((name, payloads[name]))
            replaced += 1
        else:
            files.append((name, data[off + hsize:off + hsize + dsize]))

    lt = ald.read_link_table(data)
    link_map = {no: (dk, pt) for no, (dk, pt) in enumerate(lt) if dk >= 0}
    extras = ald.read_extras(data)
    ald.pack(files, out_path, disk=disk, link_map=link_map,
             map_size=len(lt), extras=extras)
    return len(files), replaced


def cmd_repack(args):
    n, rep = repack_ald(args.ald, args.pngdir, args.out, args.jobs)
    print(f'{n} エントリ中 {rep} 件を差し替え -> {args.out}')


def cmd_apply(args):
    """原本を .bak にバックアップし、差し替え版を原本パスに配置する。"""
    target = args.ald
    bak = target + '.bak'
    if not os.path.exists(bak):
        shutil.copy2(target, bak)
        print(f'バックアップ: {bak}')
    else:
        print(f'バックアップ既存: {bak}')
    tmp = target + '.new'
    n, rep = repack_ald(target, args.pngdir, tmp, args.jobs)
    os.replace(tmp, target)
    print(f'{n} エントリ中 {rep} 件を差し替え -> {target}')


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    e = sub.add_parser('extract', help='ALD から QNT を PNG 展開')
    e.add_argument('ald')
    e.add_argument('outdir')
    e.add_argument('--jobs', type=int, default=None,
                   help='並列ワーカー数 (既定: CPUコア数)')
    e.add_argument('--filter', help='展開対象をファイル名正規表現で絞る '
                                    '(例: "cg0000|cg0450")')
    e.set_defaults(f=cmd_extract)

    u = sub.add_parser('upscale', help='PNG 群をアップスケール')
    u.add_argument('indir')
    u.add_argument('outdir')
    u.add_argument('--scale', type=int, default=2)
    u.add_argument('--cmd', help='外部アップスケーラのコマンドテンプレート '
                                 '({in} {out} {scale} が置換される)')
    u.add_argument('--method', choices=['nearest', 'lanczos'],
                   default='lanczos')
    u.add_argument('--alpha-split', action='store_true',
                   help='RGBA を RGB+α に分けて拡大し再合成 '
                        '(透過を保持しない外部ツール向け)')
    u.add_argument('--jobs', type=int, default=None,
                   help='並列ワーカー数 (Pillow パスのみ有効)')
    u.set_defaults(f=cmd_upscale)

    r = sub.add_parser('repack', help='PNG 群で ALD を再パック')
    r.add_argument('ald')
    r.add_argument('pngdir')
    r.add_argument('out')
    r.add_argument('--jobs', type=int, default=None)
    r.set_defaults(f=cmd_repack)

    a = sub.add_parser('apply', help='原本をバックアップしつつ差し替え版で置換')
    a.add_argument('ald')
    a.add_argument('pngdir')
    a.add_argument('--jobs', type=int, default=None)
    a.set_defaults(f=cmd_apply)

    args = p.parse_args()
    args.f(args)


if __name__ == '__main__':
    main()
