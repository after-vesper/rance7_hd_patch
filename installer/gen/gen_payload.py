# -*- coding: utf-8 -*-
"""Generate HD payload images from the user's own source ALDs.

For every shipped payload (installer/data/{arch}/{variant}/*.QNT):
  1. look up the assigned recipe in work/recipe_manifest.json
  2. pull the same-named QNT from the source ALD (jp or vanilla)
  3. decode, apply the recipe (gen_recipes.apply)
  4. write the 2x PNG to out/{arch}/{variant}/{name}.png plus a
     manifest.json stub (x,y offsets) consumable by tools/hdpatch.py repack

Usage:
    python work/gen_payload.py                    # everything (slow)
    python work/gen_payload.py --only cg10051     # single asset
    python work/gen_payload.py --variant shared --limit 50
"""

import argparse
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'work'))

import gen_audit as ga  # noqa: E402
import gen_recipes as gr  # noqa: E402
import ajp  # noqa: E402

DATA = ga.DATA
MANIFEST = os.environ.get(
    'GEN_MANIFEST', os.path.join(ROOT, 'work', 'recipe_manifest.json'))
OUT_DEFAULT = os.path.join(ROOT, 'work', 'gen_png')


def load_manifest():
    return json.load(open(MANIFEST, encoding='utf-8'))


def iter_payloads(variant=None, only=None):
    """Yield (arch, variant, name, path) for every shipped QNT payload."""
    for arch in ('GM', 'GA'):
        for var in ('shared', 'jp', 'vanilla'):
            if variant and var != variant:
                continue
            d = os.path.join(DATA, arch, var)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if os.path.splitext(fn)[1].lower() not in ('.qnt', '.ajp'):
                    continue
                if only and not fn.startswith(only):
                    continue
                yield arch, var, fn, os.path.join(d, fn)


def gen_one(name, var, alds, recipe):
    """Generate the 2x output PIL image for one payload.

    Returns (image, src_tag, recipe) or raises.
    """
    if var == 'vanilla':
        order = ['vanilla', 'jp']
    elif var == 'jp':
        order = ['jp', 'vanilla']
    else:
        # shared payload: prefer jp source, fall back to vanilla
        order = ['jp', 'vanilla']
    src, at = ga.src_payload(alds, name, order)
    if src is None:
        raise FileNotFoundError('no source for %s' % name)
    if name.lower().endswith('.ajp'):
        si = ajp.decode_rgba(src)
    else:
        si = ga.to_img(src)
    out = gr.apply(recipe, si)
    return out, at, si.size


_w_alds = None
_w_out = None


def _worker_init(out_dir):
    """Per-process: load source ALDs and warm the ONNX session."""
    global _w_alds, _w_out
    _w_alds = ga.load_sources()
    _w_out = out_dir
    ga.sess()


def _worker(job):
    """Generate one payload PNG in a worker process."""
    arch, var, fn, _path, rec, order = job
    out_dir = _w_out
    if rec == 'manual':
        return None  # exception payloads are placed separately
    si_src, at = ga.src_payload(_w_alds, fn, order)
    if si_src is None:
        return ('ERR', '%s/%s/%s: no source' % (arch, var, fn))
    try:
        si = ajp.decode_rgba(si_src) if fn.lower().endswith('.ajp') \
            else ga.to_img(si_src)
        out_im = gr.apply(rec, si)
    except Exception as e:
        return ('ERR', '%s/%s/%s [%s]: %s' % (arch, var, fn, rec, e))
    png = os.path.join(out_dir, arch, var, fn[:-4] + '.png')
    os.makedirs(os.path.dirname(png), exist_ok=True)
    out_im.save(png)
    return (('%s/%s' % (arch, var)), fn,
            {'x': 0, 'y': 0,
             'bpp': 32 if out_im.mode == 'RGBA' else 24,
             'recipe': rec, 'src': at})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=OUT_DEFAULT)
    ap.add_argument('--variant', default=None)
    ap.add_argument('--only', default=None)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--shard', type=int, default=0,
                    help='process only jobs[shard::nshards]')
    ap.add_argument('--nshards', type=int, default=1)
    ap.add_argument('--skip-existing', action='store_true')
    ap.add_argument('--workers', type=int, default=1)
    args = ap.parse_args()

    mani = load_manifest()
    alds = ga.load_sources()

    jobs = list(iter_payloads(args.variant, args.only))
    if args.nshards > 1:
        jobs = jobs[args.shard::args.nshards]
    if args.skip_existing:
        jobs = [(a, v, f, p) for a, v, f, p in jobs
                if not os.path.exists(os.path.join(
                    args.out, a, v, f[:-4] + '.png'))]
    if args.limit:
        jobs = jobs[:args.limit]
    print('%d payloads to generate' % len(jobs), flush=True)

    if args.workers > 1:
        import multiprocessing as mp
        order_map = {'vanilla': ['vanilla', 'jp'], 'jp': ['jp', 'vanilla'],
                     'shared': ['jp', 'vanilla']}
        joblist = [(a, v, f, p,
                    mani.get('%s/%s/%s' % (a, v, f), {}).get('recipe', 'ai'),
                    order_map[v])
                   for a, v, f, p in jobs]
        meta = {}
        n_done = n_err = 0
        ctx = mp.get_context('spawn')
        with ctx.Pool(args.workers, initializer=_worker_init,
                      initargs=(args.out,)) as pool:
            for r in pool.imap_unordered(_worker, joblist, chunksize=8):
                if r is None:
                    continue
                if r[0] == 'ERR':
                    print(r[1], flush=True)
                    n_err += 1
                    continue
                sub, fn, info = r
                meta.setdefault(sub, {})[fn] = info
                n_done += 1
                if n_done % 200 == 0:
                    print('%d/%d done (%d err)' % (n_done, len(jobs), n_err),
                          flush=True)
        for sub, m in meta.items():
            d = os.path.join(args.out, sub)
            os.makedirs(d, exist_ok=True)
            mf = os.path.join(d, 'manifest%d.json' % args.shard
                              if args.nshards > 1 else 'manifest.json')
            with open(mf, 'w', encoding='utf-8') as f:
                json.dump(m, f, ensure_ascii=False, indent=1)
        print('done: %d generated, %d errors -> %s'
              % (n_done, n_err, args.out))
        return

    meta = {}
    n_done = n_skip = n_err = 0
    for arch, var, fn, path in jobs:
        key = '%s/%s/%s' % (arch, var, fn)
        rec = mani.get(key, {}).get('recipe', 'ai')
        try:
            if rec == 'manual':
                raise RuntimeError('manual recipe -> exception payload')
            out, at, ssize = gen_one(fn, var, alds, rec)
        except Exception as e:
            print('ERR %s [%s]: %s' % (key, rec, e), flush=True)
            n_err += 1
            continue
        d = os.path.join(args.out, arch, var)
        os.makedirs(d, exist_ok=True)
        png = os.path.join(d, fn[:-4] + '.png')
        out.save(png)
        meta.setdefault('%s/%s' % (arch, var), {})[fn] = {
            'x': 0, 'y': 0, 'bpp': 32 if out.mode == 'RGBA' else 24,
            'recipe': rec, 'src': at}
        n_done += 1
        if n_done % 50 == 0:
            print('%d/%d generated (%d err)' % (n_done, len(jobs), n_err),
                  flush=True)
    for sub, m in meta.items():
        mf = os.path.join(args.out, sub,
                          'manifest%d.json' % args.shard
                          if args.nshards > 1 else 'manifest.json')
        with open(mf, 'w', encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    print('done: %d generated, %d errors -> %s' % (n_done, n_err, args.out))


if __name__ == '__main__':
    main()
