# -*- coding: utf-8 -*-
"""ForgeNeo (A1111互換 extras API) によるPNG一括アップスケール。

`hdpatch.py extract` で展開した PNG 群を API 経由で 2x 化し、
`hdpatch.py repack` で ALD に戻せる形で出力する。

- resize_mode=1 + upscaling_resize_w/h で出力サイズを正確な N 倍に固定
  (倍率指定だと mod-8 丸めが入るため)
- RGBA 入力は RGB を AI で、アルファを Lanczos で個別拡大して再合成
  (extras API はアルファを返さないため)
- 既に正しいサイズの出力がある場合はスキップ (再開可能)

使い方:
    python tools/forge_upscale.py work/src_png work/hd_png
    python tools/forge_upscale.py work/src_png work/hd_png \
        --server http://localhost:7860 --model 2x-AnimeSharpV4_Fast_RCAN_PU \
        --scale 2 --jobs 2 --filter "cg0"
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_SERVER = 'http://localhost:7860'
DEFAULT_MODEL = '2x-AnimeSharpV4_Fast_RCAN_PU'


def _pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        sys.exit('Pillow が必要です: pip install pillow')


def upscale_image(img, server, model, scale, timeout=300):
    """PIL Image -> (AI upscaled RGB PIL Image)."""
    Image = _pil()
    if img.mode != 'RGB':
        img = img.convert('RGB')
    tw, th = img.width * scale, img.height * scale
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    body = json.dumps({
        'resize_mode': 1,
        'upscaling_resize_w': tw,
        'upscaling_resize_h': th,
        'upscaler_1': model,
        'upscaler_2': 'None',
        'extras_upscaler_2_visibility': 0,
        'image': base64.b64encode(buf.getvalue()).decode(),
    }).encode()
    req = urllib.request.Request(
        server.rstrip('/') + '/sdapi/v1/extra-single-image',
        data=body, headers={'Content-Type': 'application/json'})
    res = json.load(urllib.request.urlopen(req, timeout=timeout))
    out = Image.open(io.BytesIO(base64.b64decode(res['image'])))
    return out.convert('RGB')


def process_one(src, dst, server, model, scale):
    """1枚を処理。戻り値: (name, ok, note)"""
    Image = _pil()
    name = os.path.basename(src)
    im = Image.open(src)
    tw, th = im.width * scale, im.height * scale
    if os.path.exists(dst):
        try:
            ex = Image.open(dst)
            if ex.size == (tw, th):
                return name, True, 'skip'
        except Exception:
            pass
    has_alpha = False
    if im.mode in ('RGBA', 'LA', 'PA'):
        im = im.convert('RGBA')
        a_min, a_max = im.getchannel('A').getextrema()
        has_alpha = a_min < 255
    elif im.mode == 'P':
        im = im.convert('RGB')
    if has_alpha:
        rgb = im.convert('RGB')
        alpha = im.getchannel('A')
        rgb2 = upscale_image(rgb, server, model, scale)
        a2 = alpha.resize((tw, th), Image.LANCZOS)
        out = Image.merge('RGBA', (*rgb2.split(), a2))
    else:
        out = upscale_image(im, server, model, scale)
    if out.size != (tw, th):
        out = out.resize((tw, th), Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    out.save(dst, 'PNG')
    return name, True, 'alpha' if has_alpha else 'rgb'


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('indir')
    p.add_argument('outdir')
    p.add_argument('--server', default=DEFAULT_SERVER)
    p.add_argument('--model', default=DEFAULT_MODEL)
    p.add_argument('--scale', type=int, default=2)
    p.add_argument('--jobs', type=int, default=1,
                   help='API 同時リクエスト数 (既定: 1)')
    p.add_argument('--filter', help='対象ファイル名の正規表現')
    p.add_argument('--limit', type=int, default=0,
                   help='未処理ファイルをこの件数までに制限 (0=無制限)')
    p.add_argument('--retry', type=int, default=3)
    p.add_argument('--timeout', type=int, default=300)
    args = p.parse_args()

    pat = re.compile(args.filter, re.I) if args.filter else None
    files = [f for f in sorted(os.listdir(args.indir))
             if f.lower().endswith('.png') and (not pat or pat.search(f))]

    def _is_done(fn):
        # Cheap resume check: existing output with the exact target size.
        try:
            from PIL import Image as _I
            src = _I.open(os.path.join(args.indir, fn))
            dst = os.path.join(args.outdir, fn)
            return os.path.exists(dst) and \
                _I.open(dst).size == (src.width * args.scale,
                                      src.height * args.scale)
        except Exception:
            return False

    if args.limit > 0:
        files = [f for f in files if not _is_done(f)][:args.limit]
    if not files:
        sys.exit('対象PNGがありません: ' + args.indir)
    os.makedirs(args.outdir, exist_ok=True)

    print(f'{len(files)} 件を {args.scale}x 化: server={args.server} '
          f'model={args.model} jobs={args.jobs}', flush=True)

    ok = skip = 0
    failed = []
    t0 = time.time()

    def work(fn):
        src = os.path.join(args.indir, fn)
        dst = os.path.join(args.outdir, fn)
        last = None
        for i in range(args.retry):
            try:
                return process_one(src, dst, args.server, args.model,
                                   args.scale)
            except Exception as e:
                last = e
                time.sleep(2 * (i + 1))
        raise last

    done = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(work, f): f for f in files}
        for fut in as_completed(futs):
            fn = futs[fut]
            done += 1
            try:
                name, good, note = fut.result()
                if note == 'skip':
                    skip += 1
                else:
                    ok += 1
            except Exception as e:
                failed.append((fn, str(e)))
                print(f'  NG {fn}: {e}', flush=True)
            if done % 25 == 0 or done == len(files):
                dt = time.time() - t0
                eta = dt / done * (len(files) - done)
                print(f'{done}/{len(files)} '
                      f'(new={ok} skip={skip} fail={len(failed)}) '
                      f'elapsed={dt:.0f}s eta={eta:.0f}s', flush=True)

    print(f'完了: ok={ok} skip={skip} fail={len(failed)} '
          f'({time.time() - t0:.0f}s)')
    if failed:
        for fn, e in failed:
            print('  FAIL', fn, e)
        sys.exit(1)


if __name__ == '__main__':
    main()
