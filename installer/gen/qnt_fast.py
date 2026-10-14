# -*- coding: utf-8 -*-
"""Vectorized QNT v2 encoder — byte-identical output to tools/qnt.encode
but ~1000x faster (the original walks every pixel in Python loops)."""

import struct
import zlib

import numpy as np

QNT_HEADER_SIZE = 0x44


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

    rgb = zlib.compress(body, level)
    abuf = b''
    if ch == 4:
        achan = enc4[:, :, 3]
        if w & 1:
            achan = np.hstack([achan, np.zeros((h, 1), np.uint8)])
        abuf = zlib.compress(achan.tobytes(), level)

    hdr = struct.pack('<4s13I', b'QNT\x00', 2, QNT_HEADER_SIZE,
                      x, y, w, h, 24, 1, len(rgb), len(abuf), 0, 0, 0)
    hdr = hdr.ljust(QNT_HEADER_SIZE, b'\x00')
    return hdr + rgb + abuf


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
