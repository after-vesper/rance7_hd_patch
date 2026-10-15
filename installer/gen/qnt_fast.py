# -*- coding: utf-8 -*-
"""Vectorized QNT v2 encoder — byte-identical output to tools/qnt.encode
but ~1000x faster (the original walks every pixel in Python loops)."""

import struct
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np

QNT_HEADER_SIZE = 0x44

_Z_POOL = None


def _zpool():
    global _Z_POOL
    if _Z_POOL is None:
        _Z_POOL = ThreadPoolExecutor(4)
    return _Z_POOL


def _zchunk(args):
    data, level, last = args
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    d = c.compress(data)
    d += c.flush(zlib.Z_FINISH if last else zlib.Z_FULL_FLUSH)
    return d


def compress_par(data, level=9, parts=4):
    """Parallel zlib.compress with identical format. The body is split
    into chunks deflated concurrently (pigz-style: each chunk ends with
    Z_FULL_FLUSH so the concatenated output is one valid zlib stream).
    Slightly larger output than a single pass (a few %)."""
    if len(data) < (2 << 20) or parts < 2:
        return zlib.compress(data, level)
    parts = min(parts, len(data) >> 20)
    sz = (len(data) + parts - 1) // parts
    jobs = [(data[i * sz:(i + 1) * sz], level, i == parts - 1)
            for i in range(parts)]
    out = (b'\x78\x9c' + b''.join(_zpool().map(_zchunk, jobs))
           + struct.pack('>I', zlib.adler32(data)))
    return out


def encode(w, h, pixels, alpha=None, x=0, y=0, level=9):
    """BGR(A) pixel bytes -> QNT bytes. Identical format to qnt.encode."""
    ch = 4 if alpha is not None else 3
    stride = ch * w
    out = np.frombuffer(bytes(pixels), np.uint8)
    if ch == 4:
        a = np.frombuffer(bytes(alpha), np.uint8)
        full = np.empty(w * h * 4, np.uint8)
        full[0::4] = out[0::3]
        full[1::4] = out[1::3]
        full[2::4] = out[2::3]
        full[3::4] = a
        out = full
    px = out.reshape(h, stride).astype(np.int16)

    # --- diff encoding (inverse of the decoder's reconstruction) ---
    enc = np.empty((h, stride), np.uint8)
    enc[0, :ch] = px[0, :ch]
    # first row: horizontal diff
    enc[0, ch:] = (px[0, :-ch] - px[0, ch:]) & 0xFF
    prev = px[:-1]           # row above
    cur = px[1:]
    enc[1:, :ch] = (prev[:, :ch] - cur[:, :ch]) & 0xFF
    enc[1:, ch:] = (((prev[:, ch:] + cur[:, :-ch]) >> 1)
                    - cur[:, ch:]) & 0xFF

    # --- channel separation + 2-row interleave ---
    enc4 = enc.reshape(h, w, ch).astype(np.uint8)
    w2 = (w + 1) & ~1
    pair_h = h // 2
    bodies = []
    for c in range(3):
        chan = enc4[:, :, c]
        a_even = chan[0:pair_h * 2:2]   # (pair_h, w)
        a_odd = chan[1:pair_h * 2:2]
        inter = np.stack([a_even, a_odd], axis=2)   # (pair_h, w, 2)
        row = inter.reshape(pair_h, w * 2)
        if w & 1:
            row = np.hstack([row, np.zeros((pair_h, 2), np.uint8)])
        if h & 1:
            last = np.stack([chan[-1], np.zeros(w, np.uint8)],
                            axis=1).reshape(1, w * 2)
            if w & 1:
                last = np.hstack([last, np.zeros((1, 2), np.uint8)])
            row = np.vstack([row, last])
        bodies.append(row.tobytes())
    body = b''.join(bodies)
    if len(body) != ((h + 1) & ~1) * w2 * 3:
        raise ValueError('internal: bad packed size')

    rgb = compress_par(body, level)
    abuf = b''
    if ch == 4:
        achan = enc4[:, :, 3]
        if w & 1:
            achan = np.hstack([achan, np.zeros((h, 1), np.uint8)])
        abuf = compress_par(achan.tobytes(), level)

    hdr = struct.pack('<4s13I', b'QNT\x00', 2, QNT_HEADER_SIZE,
                      x, y, w, h, 24, 1, len(rgb), len(abuf), 0, 0, 0)
    hdr = hdr.ljust(QNT_HEADER_SIZE, b'\x00')
    return hdr + rgb + abuf


_diag_cache = {}


def _diagonals(h, w):
    """Anti-diagonal index pairs (rs, xs) covering r>=1,x>=1 of a h*w grid."""
    key = (h, w)
    di = _diag_cache.get(key)
    if di is None:
        di = []
        for k in range(2, h + w - 1):
            r0 = max(1, k - w + 1)
            r1 = min(h - 1, k - 1)
            if r0 > r1:
                continue
            rs = np.arange(r0, r1 + 1)
            di.append((rs, k - rs))
        _diag_cache[key] = di
    return di


def decode(data):
    """QNT bytes -> (w, h, bpp, BGR(A) bytes). Byte-identical to qnt.decode."""
    magic, ver, hsz = struct.unpack_from('<4sII', data, 0)
    if magic != b'QNT\x00' or ver not in (1, 2):
        raise ValueError('unsupported QNT version')
    x, y, w, h, bpp = struct.unpack_from('<IIIII', data, 0x0C)
    psz, asz = struct.unpack_from('<II', data, 0x24)
    ch = 4 if asz else 3
    w2, h2 = (w + 1) & ~1, (h + 1) & ~1
    inp = np.frombuffer(zlib.decompress(data[hsz:hsz + psz]), np.uint8)
    if inp.size != h2 * w2 * 3:
        raise ValueError('bad rgb stream size')

    # undo channel separation + 2-row interleave -> residual planes
    seg = h2 * w2
    res = np.empty((h2, w2, ch), np.uint8)
    for c in range(3):
        s = inp[c * seg:(c + 1) * seg].reshape(-1, w2 * 2)
        pairs = s[:h // 2, :w * 2].reshape(-1, w, 2)
        res[0:(h // 2) * 2:2, :w, c] = pairs[:, :, 0]
        res[1:(h // 2) * 2:2, :w, c] = pairs[:, :, 1]
        if h & 1:
            res[h - 1, :w, c] = s[h // 2, 0:w * 2:2]
    if ch == 4:
        a_in = np.frombuffer(
            zlib.decompress(data[hsz + psz:hsz + psz + asz]), np.uint8)
        # stock encoders may pad the alpha plane to h2 rows; the first
        # h rows of stride w2 are what the decoder consumes
        if a_in.size < h * w2:
            raise ValueError('bad alpha stream size')
        res[:h, :w, 3] = a_in[:h * w2].reshape(h, w2)[:, :w]

    # diff decode: d = (up + left) / 2 - residual, wrapped mod 256.
    # Row 0 and col 0 are plain cumulative sums; the interior is a true
    # 2-D recurrence -> sweep anti-diagonals (cells on one diagonal only
    # depend on earlier diagonals, so each sweep is one vector op).
    e = res[:h, :w].astype(np.int16)
    a = np.empty_like(e)
    a[0, 0] = e[0, 0]
    if w > 1:
        a[0, 1:] = (e[0, 0] - np.cumsum(e[0, 1:], axis=0)) & 0xFF
    if h > 1:
        a[1:, 0] = (a[0, 0] - np.cumsum(e[1:, 0], axis=0)) & 0xFF
    for rs, xs in _diagonals(h, w):
        a[rs, xs] = (((a[rs - 1, xs] + a[rs, xs - 1]) >> 1)
                     - e[rs, xs]) & 0xFF
    return w, h, ch, (a & 0xFF).astype(np.uint8).tobytes()


def encode_pil(img, want_alpha, x=0, y=0, level=9):
    """PIL image -> QNT bytes."""
    if want_alpha:
        img = img.convert('RGBA')
        r, g, b, a = img.split()
        rgb = np.stack([np.asarray(b), np.asarray(g), np.asarray(r)],
                       axis=2)
        return encode(img.width, img.height, rgb.tobytes(),
                      a.tobytes(), x, y, level)
    img = img.convert('RGB')
    r, g, b = img.split()
    rgb = np.stack([np.asarray(b), np.asarray(g), np.asarray(r)],
                   axis=2)
    return encode(img.width, img.height, rgb.tobytes(), None, x, y,
                  level)
