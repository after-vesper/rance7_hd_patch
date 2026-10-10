# -*- coding: utf-8 -*-
"""ADV画面 (メッセージ枠・画面スロット・システムボタン等) のHDパッチ。

ain_hd_patch.py と同じ MT19937 復号を使い、画面レイアウトの
即値を 800x600 -> 1600x1200 に2倍化する。

使い方:
    python tools/ain_adv_patch.py <入力ain(暗号化済み)> <出力ain>
"""

import struct
import sys
from ain_hd_patch import _mt_stream

PUSH_OP = bytes([0,0])

# --- 連続PUSHブロックの定義 ---
# (ブロック先頭の "00 00" オフセット, 2倍化する引数index群)
BLOCKS = [
    # tagScreen@init: 画面スロット生成 (z, x, y, w, h, ...)
    (0x1978FC, [3, 4]),                 # slot0 壁紙 800x600
    (0x19796C, [1, 2, 3, 4]),           # slot1 背景 (10,36,568,312)
    (0x19799E, [1, 2]),                 # slot1 枠CG 10012 (4,4)
    (0x1979BC, [0, 1, 2, 3, 4]),        # slot1 名前 (8,8,577,25,20)
    (0x197A24, [1, 2, 3, 4]),           # slot2 勢力 (696,4,100,30)
    (0x197A94, [3, 4]),                 # slot3 SP/シーン 800x600
    (0x197B04, [1, 2, 3, 4]),           # slot4 顔 (18,370,186,220)
    (0x197B36, [1, 2]),                 # slot4 枠CG 10011 (12,337)
    (0x197B54, [0, 1, 2, 3, 4]),        # slot4 名前 (16,341,190,24,16)
    # tagSystemButtonManager@0: 自動/早送り/設定ボタン (no,type,cg,z,x,y,w,h)
    (0x1A0D1A, [4, 5, 6, 7]),           # (761,494,36,20)
    (0x1A0D5E, [4, 5, 6, 7]),           # (761,517,36,20)
    (0x1A0DA2, [4, 5, 6, 7]),           # (761,540,36,20)
    # tagMessageFrameManager@0: メッセージ枠データ 6件
    # 引数: (no, cg, z, x, y, w, h, r,g,b, blend, tx, ty, tx2, ty2,
    #        lineSpace, fontSize, face, bold, fr,fg,fb, shL,shU,shR,shD, ...)
    (0x191236, [3,4,5,6, 11,12,13,14, 15,16, 22,23,24,25]),  # type1 台詞枠
    (0x191310, [3,4,5,6, 11,12,13,14, 15,16, 22,23,24,25]),  # type2 思考枠
    (0x1913EA, [3,4,5,6, 11,12,13,14, 15,16, 22,23,24,25]),  # type3 ト書き枠
    (0x1914C4, [3,4,5,6, 11,12,13,14, 15,16, 22,23,24,25]),  # type11 全画面枠
    (0x19159E, [3,4,5,6, 11,12,13,14, 15,16, 22,23,24,25]),  # type12 全画面枠2
    (0x191678, [3,4,5,6, 11,12,13,14, 15,16, 22,23,24,25]),  # type99
]

# --- 個別即値 (オフセットはimmの位置, 値を2倍化) ---
SINGLES = [
    # tagMessageName@create: 名前プレート位置と文字
    (0x190F02, 196),   # プレートX
    (0x190F08, 457),   # プレートY
    (0x190F32, 20),    # テキスト基準X
    (0x190F38, 16),    # テキスト基準Y
    (0x190F50, 186),   # テキスト幅
    (0x190F5E, 16),    # テキスト高/関連
    (0x190F94, 202),   # 名前文字X
    (0x190FA2, 463),   # 名前文字Y
    (0x190FD6, 16),    # 名前フォントサイズ
]


def main(src_path, dst_path):
    enc = open(src_path, "rb").read()
    ks = _mt_stream(0x5D3E3, len(enc))
    dec = bytearray(b ^ k for b, k in zip(enc, ks))

    patched = skipped = 0
    for base, idxs in BLOCKS:
        for k in idxs:
            imm = base + 2 + k * 6
            if dec[imm - 2:imm] != b"\x00\x00":
                raise SystemExit("PUSHでない @0x%x" % (imm - 2))
            # ブロック内は「元のスクリプト値」を2倍化 (適用済み判定は不可)
            old = struct.unpack_from("<i", dec, imm)[0]
            struct.pack_into("<i", dec, imm, old * 2)
            patched += 1
    for off, expected in SINGLES:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for base, idxs in BLOCKS2:
        for k in idxs:
            imm = base + 2 + k * 6
            if dec[imm - 2:imm] != PUSH_OP:
                raise SystemExit("PUSHでない @0x%x" % (imm - 2))
            old = struct.unpack_from("<i", dec, imm)[0]
            struct.pack_into("<i", dec, imm, old * 2)
            patched += 1
    for off, expected in SINGLES2:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for lo, hi, vals in RANGE_PATCH:
        i = lo
        while i < hi:
            if dec[i:i+2] == PUSH_OP:
                v = struct.unpack_from("<i", dec, i + 2)[0]
                if v in vals:
                    struct.pack_into("<i", dec, i + 2, v * 2)
                    patched += 1
            i += 1

    ks = _mt_stream(0x5D3E3, len(dec))
    open(dst_path, "wb").write(bytes(b ^ k for b, k in zip(dec, ks)))
    print("patched %d, skipped %d -> %s" % (patched, skipped, dst_path))



# --- 追加パッチ (ウェイトアイコン / システムメニュー) ---
# BLOCKS2: (先頭PUSHオフセット, 2倍化する引数index群)
BLOCKS2 = [
    (0x18AEF0, [3, 4]),   # tagWaitIconManager@0: アイコン1 pos (762,563)
    # アイコン2 (60004, -1,-1) は自動配置のため対象外
]

# SINGLES2: (immのオフセット, 期待値) -> 2倍化
SINGLES2 = [
    # tagSystemMenu@create
    (0x1FAAEE, 16),    # getTextWidth フォントサイズ
    (0x1FABF2, 80),    # 隠しボタン w
    (0x1FABF8, 26),    # 隠しボタン h
    (0x1FAC78, 2),     # setButtonPos x
    (0x1FAC7E, 572),   # setButtonPos y
    (0x1FAD2A, 2),     # else分岐 nX=2 (SH_LOCALASSIGN内imm)
    (0x1FAD38, 572),   # else分岐 nY = 572 - frameH
    (0x1FAD72, 36),    # nX += 36
    (0x1FAD84, 2),     # nY += 2
    (0x1FADE4, 24),    # ボタン行間 nY += 24
    # tagSystemMenu@createFrame
    (0x1FAE4C, 48),    # nWidth += 48 (左右マージン)
    (0x1FAE5E, 24),    # nHeight = 24 * cnt
    (0x1FAE6C, 2),     # nHeight += 2 (下マージン)
    (0x1FB3EC, 7),     # アイコン nX=7 (SH_LOCALASSIGN内imm)
    (0x1FB3F6, 2),     # アイコン nY=2 (SH_LOCALASSIGN内imm)
    (0x1FB468, 24),    # アイコン行間 nY += 24
    # tagSystemMenu@createButton
    (0x1FB48E, 22),    # nHeight=22 (SH_LOCALASSIGN内imm)
    (0x1FB4AC, 16),    # nTy 計算 (nHeight-16)/2
    (0x1FB50C, 16),    # ボタンテキスト フォントサイズ
    (0x1FB6C0, 1),     # ハイライト枠 nY=1 (SH_LOCALASSIGN内imm)
]

# RANGE_PATCH: (開始, 終了, 2倍化する値の集合)
# tagSystemMenu@createFrame 内のタイル寸法 (CG10074 の 22x24 タイル等)
RANGE_PATCH = [
    (0x1FAE00, 0x1FB460, {16, 22, 24}),
]

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
