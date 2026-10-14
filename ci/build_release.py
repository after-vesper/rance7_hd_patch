# -*- coding: utf-8 -*-
"""Build the generation-mode release package.

Copies installer/ into a clean tree and strips shipped payload images:
only `manual` recipe payloads (hand-edited exceptions) keep their raw
files under data/{arch}/{variant}; everything else is regenerated from
the user's own game archives at install time.

Usage: python ci/build_release.py [--zip]

Output: <repo>/release/SengokuRance_HDPatch/
        <repo>/release/SengokuRance_HDPatch.zip  (with --zip)
"""

import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'installer')
DST = os.path.join(ROOT, 'release', 'SengokuRance_HDPatch')
MANIFEST = os.path.join(ROOT, 'installer', 'gen', 'recipe_manifest.json')


def main():
    mani = json.load(open(MANIFEST, encoding='utf-8'))
    keep = {k.split('/', 2)[2] for k, v in mani.items()
            if v.get('recipe') == 'manual'}

    if os.path.exists(DST):
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)

    n_drop = n_keep = 0
    for arch in ('GM', 'GA'):
        for var in ('shared', 'jp', 'vanilla'):
            d = os.path.join(DST, 'data', arch, var)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if fn in keep:
                    n_keep += 1
                    continue
                os.remove(os.path.join(d, fn))
                n_drop += 1
    print('dropped %d payload files, kept %d manual exceptions'
          % (n_drop, n_keep))

    # AliceLogo3.alk is regenerated from the user's backup at install
    # time (gen/gen_alk.py); do not ship the derived archive.
    alk = os.path.join(DST, 'data', 'files', 'AliceLogo3.alk')
    if os.path.exists(alk):
        os.remove(alk)
        print('dropped data/files/AliceLogo3.alk (regenerated at install)')

    # drop interpreter caches and bundled package test suites; the
    # runtime regenerates .pyc files and none of our code imports tests
    n_rm = 0
    for dp, dns, _ in os.walk(DST, topdown=False):
        name = os.path.basename(dp)
        if name == '__pycache__' or (
                'site-packages' in dp and
                ((name == 'tests' and 'numpy' not in dp) or
                 name in ('doc', 'distutils', '_pyinstaller'))):
            shutil.rmtree(dp, ignore_errors=True)
            n_rm += 1
    print('removed %d cache/test directories' % n_rm)

    # prune payload dirs left empty by generation (data/{GM,GA}/*,
    # data/files) - manifest.json/hd_sites.json stay
    data_root = os.path.join(DST, 'data')
    for dp, dns, fns in os.walk(data_root, topdown=False):
        if dp != data_root and not os.listdir(dp):
            os.rmdir(dp)

    total = 0
    for dp, _, fns in os.walk(DST):
        for fn in fns:
            total += os.path.getsize(os.path.join(dp, fn))
    print('release tree: %s (%.1f MB uncompressed)'
          % (DST, total / 1e6))

    if '--zip' in sys.argv:
        zpath = DST + '.zip'
        if os.path.exists(zpath):
            os.remove(zpath)
        base = os.path.basename(DST)
        with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=9) as z:
            for dp, _, fns in os.walk(DST):
                for fn in fns:
                    p = os.path.join(dp, fn)
                    z.write(p, os.path.join(base,
                            os.path.relpath(p, DST)))
        print('zip: %s (%.1f MB)' % (zpath, os.path.getsize(zpath) / 1e6))


if __name__ == '__main__':
    main()
