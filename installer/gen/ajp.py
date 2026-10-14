# -*- coding: utf-8 -*-
"""AJP (AliceSoft JPEG image) の展開/2x化/再エンコード。

フォーマット (GARbro ImageAJP.cs / Rance7 実測):
    [ヘッダ 0x38B] 'AJP\0' / u32 version(0) / u32 header_size(56) /
        u32 width / u32 height / u32 image_offset(56) / u32 image_size /
        u32 alpha_offset / u32 alpha_size / 残りは未使用
    [画像部] JPEGデータ。先頭16バイトのみ固定キーでXOR難読化。

使い方:
    python tools/ajp.py decode <ajp> <out.png>   # AJP -> PNG
    python tools/ajp.py encode <png> <out.ajp>   # PNG -> AJP (JPEG品質指定可)
"""

import io
import struct
import sys

KEY = bytes([
    0x5D, 0x91, 0xAE, 0x87, 0x4A, 0x56, 0x41, 0xCD,
    0x83, 0xEC, 0x4C, 0x92, 0xB5, 0xCB, 0x16, 0x34,
])
HDR_SIZE = 0x38


def decode(data):
    """AJP バイト列 -> (width, height, JPEGバイト列, alpha部bytes or None)"""
    if data[:3] != b'AJP':
        raise ValueError('not AJP')
    w, h = struct.unpack_from('<II', data, 0x0C)
    img_off, img_size = struct.unpack_from('<II', data, 0x14)
    a_off, a_size = struct.unpack_from('<II', data, 0x1C)
    img = bytearray(data[img_off:img_off + img_size])
    for i in range(min(16, len(img))):
        img[i] ^= KEY[i]
    if img[:2] != b'\xff\xd8':
        raise ValueError('decoded data is not JPEG')
    alpha = data[a_off:a_off + a_size] if a_size else None
    return w, h, bytes(img), alpha


def decode_mask(data):
    """AJP alpha部 ('PM\\x02' マスク) -> (w, h, 256階調alphaバイト列)。

    GARbro ImageAJP.cs ReadMask 準拠:
        [ヘッダ 0x40B] 'PM\\x02\\x00' ... +0x18 w / +0x1c h /
            +0x20 data_offset / +0x24 pal_offset
        [data] インデックス画像のRLE:
            <0xF8       リテラル
            0xF8 b      エスケープ (b をそのまま出力)
            0xFC n b0 b1  2バイトパターンを (n*2+4) バイト分前方へ繰り返し
            0xFD n b    b を (n+4) バイト出力
            0xFE n      2行前から (n+3) バイト複写
            0xFF n      1行前から (n+3) バイト複写
        [pal] 0x300B のRGBパレット。index -> (r+g+b)/3 でグレー化。
    """
    data = bytearray(data)
    for i in range(min(16, len(data))):
        data[i] ^= KEY[i]
    if data[:2] != b'PM':
        raise ValueError('not PM mask')
    w, h = struct.unpack_from('<II', data, 0x18)
    data_off, pal_off = struct.unpack_from('<II', data, 0x20)
    n = w * h
    pixels = bytearray(n)
    dst = 0
    i = data_off
    while dst < n:
        c = data[i]
        i += 1
        if c < 0xF8:
            pixels[dst] = c
            dst += 1
        elif c == 0xF8:
            pixels[dst] = data[i]
            i += 1
            dst += 1
        elif c == 0xFC:
            count = data[i] * 2 + 4
            pixels[dst:dst + 2] = data[i + 1:i + 3]
            i += 3
            for k in range(count):
                pixels[dst + 2 + k] = pixels[dst + k]
            dst += count + 2
        elif c == 0xFD:
            count = data[i] + 4
            b = data[i + 1]
            i += 2
            pixels[dst:dst + count] = bytes([b]) * count
            dst += count
        elif c in (0xFE, 0xFF):
            count = data[i] + 3
            i += 1
            src = dst - w * (2 if c == 0xFE else 1)
            for k in range(count):
                pixels[dst + k] = pixels[src + k]
            dst += count
        else:
            raise ValueError('bad mask op 0x%02x @%d' % (c, i))
    pal = data[pal_off:pal_off + 0x300]
    if len(pal) < 0x300:
        raise ValueError('short palette')
    gray = [(pal[k * 3] + pal[k * 3 + 1] + pal[k * 3 + 2]) // 3
            for k in range(0x100)]
    return w, h, bytes(gray[v] for v in pixels)


def encode_mask(width, height, alpha):
    """256階調alphaバイト列 -> PM マスクセクション。

    パレットは恒等グレー (index==alpha) を使う。圧縮は
    リテラル + 0xFD 連打 + 0xFE/0xFF 行複写の貪欲マッチ。
    実機デコーダ (pms8_extract) は行単位で処理するため、
    各コマンドが出力する画素数は必ず行内に収める。
    """
    n = width * height
    if len(alpha) != n:
        raise ValueError('alpha size mismatch')
    out = bytearray()
    pos = 0
    while pos < n:
        room = width - pos % width   # 現在行の残り画素数
        # 1行前/2行前との一致長
        best_op = 0
        best_len = 0
        for op, back in ((0xFF, width), (0xFE, width * 2)):
            if pos < back:
                continue
            l = 0
            src = pos - back
            while l < room and alpha[src + l] == alpha[pos + l]:
                l += 1
            if l > best_len:
                best_op, best_len = op, l
        # 同一バイト連打
        run = 1
        b = alpha[pos]
        while run < room and alpha[pos + run] == b:
            run += 1
        if run >= 4 and run > best_len:
            take = min(run, 0xFF + 4)
            out += bytes((0xFD, take - 4, b))
            pos += take
            continue
        if best_len >= 3:
            take = min(best_len, 0xFF + 3)
            out += bytes((best_op, take - 3))
            pos += take
            continue
        if b >= 0xF8:
            out += bytes((0xF8, b))
        else:
            out.append(b)
        pos += 1
    data_off = 0x40
    pal_off = data_off + len(out)
    pal = bytearray()
    for k in range(0x100):
        pal += bytes((k, k, k))
    hdr = bytearray(0x40)
    hdr[0:4] = b'PM\x02\x00'
    struct.pack_into('<I', hdr, 4, 0x80040)
    struct.pack_into('<II', hdr, 0x18, width, height)
    struct.pack_into('<II', hdr, 0x20, data_off, pal_off)
    sec = bytearray(hdr) + out + pal
    for i in range(min(16, len(sec))):
        sec[i] ^= KEY[i]
    return bytes(sec)


def decode_rgba(data):
    """AJP バイト列 -> PIL Image (RGB or RGBA)。"""
    import io as _io
    from PIL import Image
    w, h, jpeg, alpha = decode(data)
    img = Image.open(_io.BytesIO(jpeg)).convert('RGB')
    if alpha:
        aw, ah, mask = decode_mask(alpha)
        if (aw, ah) == (w, h):
            img.putalpha(Image.frombytes('L', (w, h), mask))
    return img


def encode(width, height, jpeg, alpha=None, template_hdr=None):
    """(w,h,JPEGバイト列,alpha=None) -> AJP バイト列。

    alpha: w*h の256階調バイト列。指定時は PM マスクとして同梱する。
    """
    img = bytearray(jpeg)
    for i in range(min(16, len(img))):
        img[i] ^= KEY[i]
    if template_hdr is not None:
        hdr = bytearray(template_hdr[:HDR_SIZE])
    else:
        hdr = bytearray(HDR_SIZE)
        hdr[0:4] = b'AJP\x00'
        struct.pack_into('<I', hdr, 8, HDR_SIZE)
    struct.pack_into('<II', hdr, 0x0C, width, height)
    struct.pack_into('<II', hdr, 0x14, HDR_SIZE, len(img))
    if alpha is None:
        struct.pack_into('<II', hdr, 0x1C, 0, 0)
        return bytes(hdr) + bytes(img)
    mask = encode_mask(width, height, alpha)
    a_off = HDR_SIZE + len(img)
    struct.pack_into('<II', hdr, 0x1C, a_off, len(mask))
    return bytes(hdr) + bytes(img) + mask


def cmd_decode(src, dst):
    from PIL import Image
    w, h, jpeg, _ = decode(open(src, 'rb').read())
    Image.open(io.BytesIO(jpeg)).convert('RGB').save(dst)
    print('%s -> %s (%dx%d)' % (src, dst, w, h))


def cmd_encode(src, dst, quality=95):
    from PIL import Image
    img = Image.open(src).convert('RGB')
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    open(dst, 'wb').write(encode(img.width, img.height, buf.getvalue()))
    print('%s -> %s (%dx%d)' % (src, dst, img.width, img.height))


if __name__ == '__main__':
    if sys.argv[1] == 'decode':
        cmd_decode(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == 'encode':
        cmd_encode(sys.argv[2], sys.argv[3])
