"""QNT (AliceSoft System 画像形式) のデコード/エンコード。

フォーマット (version 2):
    u32 'QNT\\0' / u32 version / u32 header_size
    u32 x, y / u32 w, h / u32 bpp / u32 ? / u32 rgb_zlib_size / u32 alpha_zlib_size
    [header_size 〜] zlib RGB ストリーム、続いて zlib アルファストリーム

RGB ストリームは (偶数補正した) w*h*3 バイト。チャンネル(B,G,R)ごとに
行ペア単位で「上行画素, 下行画素」が交互に格納されている。
アルファは行優先、奇数幅では各行末に 1 バイトのパディング。
その後差分復号 (先頭行は左隣との差、2行目以降は上・左の平均との差)。
"""

import struct
import zlib

QNT_HEADER_SIZE = 0x44


def decode(data):
    """QNT バイト列 -> (w, h, bpp, RGBA or RGB バイト列)。画素は BGR(A) 順。"""
    magic, ver, hsz = struct.unpack_from('<4sII', data, 0)
    if magic != b'QNT\x00' or ver not in (1, 2):
        raise ValueError('unsupported QNT version')
    x, y, w, h, bpp = struct.unpack_from('<IIIII', data, 0x0C)
    psz, asz = struct.unpack_from('<II', data, 0x24)
    ch = 4 if asz else 3
    w2, h2 = (w + 1) & ~1, (h + 1) & ~1
    inp = zlib.decompress(data[hsz:hsz + psz])
    if len(inp) != h2 * w2 * 3:
        raise ValueError('bad rgb stream size')
    alpha = zlib.decompress(data[hsz + psz:hsz + psz + asz]) if asz else None

    stride = ch * w
    out = bytearray(w * h * ch)
    # チャンネル分離・2行インターリーブ解除
    src = 0
    for c in range(3):
        dst = c
        for _ in range(h >> 1):
            for _ in range(w):
                out[dst] = inp[src]; src += 1
                out[dst + stride] = inp[src]; src += 1
                dst += ch
            dst += stride
            src += 2 * (w & 1)
        if h & 1:
            for _ in range(w):
                out[dst] = inp[src]; src += 2
                dst += ch
            src += 2 * (w & 1)
    if ch == 4:
        src = 0
        dst = 3
        for _ in range(h):
            for _ in range(w):
                out[dst] = alpha[src]; src += 1; dst += 4
            src += w & 1

    # 差分復号
    dst = ch
    for _ in range(stride - ch):
        out[dst] = (out[dst - ch] - out[dst]) & 0xFF
        dst += 1
    for _ in range(h - 1):
        for _ in range(ch):
            out[dst] = (out[dst - stride] - out[dst]) & 0xFF
            dst += 1
        for _ in range(stride - ch):
            out[dst] = (((out[dst - stride] + out[dst - ch]) >> 1) - out[dst]) & 0xFF
            dst += 1
    return w, h, ch, bytes(out)


def encode(w, h, pixels, alpha=None, x=0, y=0):
    """BGR(A) 画素列 -> QNT バイト列。alpha を渡すと 32bpp。"""
    ch = 4 if alpha is not None else 3
    stride = ch * w
    out = bytearray(pixels)
    if ch == 4:
        # pixels は BGR、alpha を差し込む
        full = bytearray(w * h * 4)
        full[0::4] = out[0::3]
        full[1::4] = out[1::3]
        full[2::4] = out[2::3]
        full[3::4] = alpha
        out = full

    # 差分エンコード (デコードの逆操作)
    enc = bytearray(out)
    dst = ch
    for i in range(stride - ch):
        enc[dst] = (out[dst - ch] - out[dst]) & 0xFF
        dst += 1
    for _ in range(h - 1):
        for i in range(ch):
            enc[dst] = (out[dst - stride] - out[dst]) & 0xFF
            dst += 1
        for i in range(stride - ch):
            enc[dst] = (((out[dst - stride] + out[dst - ch]) >> 1) - out[dst]) & 0xFF
            dst += 1

    # チャンネル分離 + 2行インターリーブ
    w2, h2 = (w + 1) & ~1, (h + 1) & ~1
    body = bytearray()
    for c in range(3):
        dst = c
        for _ in range(h >> 1):
            for _ in range(w):
                body.append(enc[dst])
                body.append(enc[dst + stride])
                dst += ch
            dst += stride
            body += b'\x00' * (2 * (w & 1))
        if h & 1:
            for _ in range(w):
                body.append(enc[dst])
                body.append(0)
                dst += ch
            body += b'\x00' * (2 * (w & 1))
    if len(body) != h2 * w2 * 3:
        raise ValueError('internal: bad packed size')

    rgb = zlib.compress(bytes(body), 9)
    abuf = b''
    if ch == 4:
        ab = bytearray()
        src = 3
        for _ in range(h):
            for _ in range(w):
                ab.append(enc[src]); src += 4
            ab += b'\x00' * (w & 1)
        abuf = zlib.compress(bytes(ab), 9)

    hdr = struct.pack('<4s13I', b'QNT\x00', 2, QNT_HEADER_SIZE,
                      x, y, w, h, 24, 1, len(rgb), len(abuf), 0, 0, 0)
    hdr = hdr.ljust(QNT_HEADER_SIZE, b'\x00')
    return hdr + rgb + abuf
