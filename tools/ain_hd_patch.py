# -*- coding: utf-8 -*-
"""Rance7.ain への HD (1600x1200) パッチを再現適用するスクリプト。

Steam版の ain は MT19937 (seed 0x5D3E3, init 69069倍) ストリームで
XOR 暗号化されている。復号 -> 即値書き換え -> 再暗号化 を行う。

使い方:
    python tools/ain_hd_patch.py game/Rance7.ain.orig game/Rance7.ain
"""

import struct
import sys

# パッチ一覧: (復号済みバイナリ内オフセット, 旧値, 新値, 内容)
PATCHES = [
    # tagTitle@create: 火の粉スプライト Z をベイク画像(21)より上へ
    (0x1FF57A, 11, 25, "火の粉 Z"),
    # tagTitle@create: メニューボタン座標を2倍化
    (0x1FF6A0, 242, 484, "メニューX"),
    (0x1FF6AA, 410, 820, "メニュー開始Y"),
    (0x1FF6F6, 39, 78, "ボタン縦間隔"),
    (0x1FF728, 39, 78, "ボタン縦間隔"),
    (0x1FF75A, 39, 78, "ボタン縦間隔"),
    # tagSelectCg@createSpTitle: ボタン文字サイズを2倍化
    (0x19A6AA, 18, 36, "選択肢テキストサイズ"),
    # tagSelectCg@create: ボタン背景スプライトを2倍化
    (0x199D7C, 322, 644, "ボタン背景幅"),
    (0x199D8E, 32, 64, "ボタン背景高さ"),
    (0x199E7E, 3, 6, "copyCg dstX #1"),
    (0x199E84, 3, 6, "copyCg dstY #1"),
    (0x199EA4, 316, 632, "copyCg srcW #1"),
    (0x199EAA, 26, 52, "copyCg srcH #1"),
    (0x199F92, 3, 6, "copyCg dstX #2"),
    (0x199F98, 3, 6, "copyCg dstY #2"),
    (0x199FB8, 316, 632, "copyCg srcW #2"),
    (0x199FBE, 26, 52, "copyCg srcH #2"),
    (0x19A0A6, 3, 6, "copyCg dstX #3"),
    (0x19A0AC, 3, 6, "copyCg dstY #3"),
    (0x19A0CC, 316, 632, "copyCg srcW #3"),
    (0x19A0D2, 26, 52, "copyCg srcH #3"),
    # ShowWarningScreen: 初回起動のみの下帯黒マスクを2倍化
    (0x213EFC, 800, 1600, "マスク幅 (createPixelOnly)"),
    (0x213F02, 94, 188, "マスク高さ"),
    (0x213F20, 800, 1600, "マスク塗り幅 (CG_FILL)"),
    (0x213F26, 94, 188, "マスク塗り高さ"),
    (0x213F50, 506, 1012, "マスク配置Y (SP_SET_POS)"),
    # ShowAliceLogo: 終了時の白フラッシュスプライトを2倍化
    (0x2142D0, 800, 1600, "白フラッシュ幅"),
    (0x2142D6, 600, 1200, "白フラッシュ高さ"),
    (0x2142F4, 800, 1600, "白フラッシュ塗り幅"),
    (0x2142FA, 600, 1200, "白フラッシュ塗り高さ"),
]


def _mt_stream(seed, n):
    """戦国ランス ain 暗号化と同じ MT19937 バリアントの鍵ストリーム。
    初期化は標準の 1812433253 倍ではなく 69069 倍。"""
    N, M = 624, 397
    st = [seed & 0xFFFFFFFF]
    for i in range(1, N):
        st.append((69069 * st[i - 1]) & 0xFFFFFFFF)
    idx = N
    mag = [0, 0x9908B0DF]
    out = bytearray()
    while len(out) < n:
        if idx >= N:
            for kk in range(N - M):
                y = (st[kk] & 0x80000000) | (st[kk + 1] & 0x7FFFFFFF)
                st[kk] = st[kk + M] ^ (y >> 1) ^ mag[y & 1]
            for kk in range(N - M, N - 1):
                y = (st[kk] & 0x80000000) | (st[kk + 1] & 0x7FFFFFFF)
                st[kk] = st[kk + (M - N)] ^ (y >> 1) ^ mag[y & 1]
            y = (st[N - 1] & 0x80000000) | (st[0] & 0x7FFFFFFF)
            st[N - 1] = st[M - 1] ^ (y >> 1) ^ mag[y & 1]
            idx = 0
        y = st[idx]
        idx += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        out.append(y & 0xFF)
    return out


def decrypt(data):
    ks = _mt_stream(0x5D3E3, len(data))
    return bytearray(b ^ k for b, k in zip(data, ks))


def main(src_path, dst_path):
    enc = open(src_path, "rb").read()
    dec = decrypt(enc)
    for off, old, new, desc in PATCHES:
        cur = struct.unpack_from("<i", dec, off)[0]
        if cur == new:
            print("skip (適用済み) %s @0x%x" % (desc, off))
            continue
        if cur != old:
            raise SystemExit(
                "想定外の値 @0x%x %s: %d (期待 %d)" % (off, desc, cur, old))
        struct.pack_into("<i", dec, off, new)
        print("patch %s @0x%x: %d -> %d" % (desc, off, old, new))
    # 再暗号化 (鍵ストリームは対称)
    ks = _mt_stream(0x5D3E3, len(dec))
    open(dst_path, "wb").write(bytes(b ^ k for b, k in zip(dec, ks)))
    print("wrote %s" % dst_path)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
