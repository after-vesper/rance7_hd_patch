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


def encode(width, height, jpeg, template_hdr=None):
    """(w,h,JPEGバイト列) -> AJP バイト列。alpha は非対応 (CG30031系は無し)。"""
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
    struct.pack_into('<II', hdr, 0x1C, 0, 0)
    return bytes(hdr) + bytes(img)


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
