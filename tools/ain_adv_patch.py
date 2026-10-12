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
    for off, expected in SINGLES3:
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
    for off, expected in SINGLES4:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, val in SINGLES_ABS:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != ABS_BASE[off]:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, ABS_BASE[off]))
        struct.pack_into("<i", dec, off, val)
        patched += 1
    for off, expected in SINGLES5:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES6:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES7:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES8:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES9:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES10:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES11:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1
    for off, expected in SINGLES12:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1



    for off, expected in SINGLES13:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES14:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES15:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES16:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES17:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES18:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES19:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for off, expected in SINGLES20:
        old = struct.unpack_from("<i", dec, off)[0]
        if old != expected:
            raise SystemExit(
                "想定外の値 @0x%x: %d (期待 %d)" % (off, old, expected))
        struct.pack_into("<i", dec, off, expected * 2)
        patched += 1

    for lo, hi, pat in PRE2_PATCH:
        i = lo
        while True:
            j = dec.find(pat, i, hi)
            if j < 0:
                break
            if dec[j - 12:j - 10] != PUSH_OP or dec[j - 6:j - 4] != PUSH_OP:
                raise SystemExit("直前がPUSHでない @0x%x" % j)
            for k in (j - 10, j - 4):
                old = struct.unpack_from("<i", dec, k)[0]
                struct.pack_into("<i", dec, k, old * 2)
                patched += 1
            i = j + len(pat)

    ks = _mt_stream(0x5D3E3, len(dec))
    open(dst_path, "wb").write(bytes(b ^ k for b, k in zip(dec, ks)))
    print("patched %d, skipped %d -> %s" % (patched, skipped, dst_path))



# --- 絶対値書き込み (2倍化ではない個所) ---
ABS_BASE = {
    0x1A8B9E: 12,
    0x1A8BB8: 12,
    0x1A8AE6: -8,
    0x1A8B00: -8,
    0x1A8CFC: -8,
    0x1A8D16: -8,
}
SINGLES_ABS = [
    # tagMap@setCursor: ポインタのワープ先=マーク中心 (50x50家紋の中心=+25)
    (0x1A8B9E, 25),
    (0x1A8BB8, 25),
    # tagMap@lock: カーソル枠スプライト位置 (82x82枠を50x50家紋に中央合わせ: 25-41=-16)
    # member5=ホバーカーソル枠 / member6=ロック枠: 82x82枠を50x50家紋に中央合わせ (-16)
    (0x1A8AE6, -16),
    (0x1A8B00, -16),
    (0x1A8CFC, -16),
    (0x1A8D16, -16),
]

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

# SINGLES3: tagSelect 系共有リストメニュー (館メニュー/環境設定/選択肢 共通)
# (immのオフセット, 期待値) -> 2倍化
SINGLES3 = [
    # tagSelect@create
    (0x19B17E, 374),   # ベース枠幅
    (0x19B1EC, 4),     # タイトルバー +x
    (0x19B1FA, 4),     # タイトルバー +y
    (0x19B2C0, 340),   # 「閉」ボタン +x
    (0x19B2CE, 6),     # 「閉」ボタン +y
    # tagSelect@createBase
    (0x19B88A, 12),    # 枠高マージン
    (0x19B89A, 547),   # 高さ上限 (比較値)
    (0x19B8AC, 547),   # 高さ上限 (代入値)
    (0x19B8C6, 3),     # nH2 = nH + 3
    # tagSelect@createButton
    (0x19BA30, 6),     # 項目間隔 +6
    (0x19BA64, 12),    # 項目間隔 +12
    (0x19BA7C, 10),    # 項目間隔 +10
    (0x19BA90, 42),    # 初期オフセット nH=42
    (0x19BB6C, 26),    # ボタン x
    (0x19BB78, 3),     # ボタン y = nH - 3
    (0x19BBC6, 26),    # 項目高 +26
    # tagSelect@createText
    (0x19BC38, 12), (0x19BC6C, 2), (0x19BC84, 10), (0x19BC98, 42),
    (0x19BCD2, 17),    # テキスト分割幅(文字数)
    (0x19BD72, 22),    # 行高
    (0x19BD80, 2),     # 行間
    (0x19BDB8, 20),    # フォントサイズ
    (0x19BE4E, 364),   # テキストスプライト幅
    (0x19BE80, 5),     # x位置
    (0x19BEB0, 12),    # nTextX
    (0x19BEC2, 1),     # nTextY
    (0x19BF0E, 364), (0x19BF14, 22), (0x19BF44, 364), (0x19BF4A, 22),
    (0x19BFB0, 24),    # nY += 24
    # tagSelect@createSeparator
    (0x19C038, 10), (0x19C06C, 10), (0x19C084, 10), (0x19C098, 42),
    (0x19C104, 364), (0x19C10A, 4), (0x19C11E, 5),
    (0x19C144, 364), (0x19C14A, 4), (0x19C186, 4),
    # tagSelectCg@createSp
    (0x19A23C, 18),    # 項目フォントサイズ
    # tagTitleBar@create
    (0x1ACAC0, 20),    # タイトル文字サイズ
    (0x1ACBEE, 20),    # 数字部分サイズ
]


# SINGLES4: セーブデータ倉庫 (LOAD/SAVE画面) + tagComment/tagInput/tagScrollBar
# tagSaveStore@0 ドロップゾーン矩形
SINGLES4 = [
    (0x1F4CCA, 48), (0x1F4CD0, 44), (0x1F4CD6, 200), (0x1F4CDC, 173),
    (0x1F4CEE, 712), (0x1F4CF4, 480), (0x1F4CFA, 791), (0x1F4D00, 559),
    # tagSaveStore@create: 各タイトルテキスト位置/フォント
    (0x1F5194, 50), (0x1F519A, 18), (0x1F51DA, 20),
    (0x1F52C0, 10), (0x1F52C6, 244), (0x1F5306, 20),
    (0x1F53EC, 277), (0x1F53F2, 8), (0x1F5432, 20),
    (0x1F5518, 714), (0x1F551E, 454), (0x1F555E, 20),
    (0x1F5630, 275), (0x1F5636, 546), (0x1F5676, 16),
    (0x1F56DA, 450),                # スクロールバー長
    (0x1F56F2, 528), (0x1F56F8, 55),# スクロールバー位置
    (0x1F581A, 274), (0x1F5820, 33),# ボタン1
    (0x1F58C8, 388), (0x1F58CE, 33),# ボタン2
    (0x1F5976, 518), (0x1F597C, 8), # ボタン3
    (0x1F5AFA, 8), (0x1F5B00, 270), # 自動セーブスロット位置
    # tagSaveStore@remake
    (0x1F5C9E, 8), (0x1F5CA4, 270),
    # tagSaveStore@createList: 本棚グリッド (SH_LOCALASSIGN/LOCALPLUSA 内imm)
    (0x1F5E0E, 275),                # nX
    (0x1F5E18, 58),                 # nY
    (0x1F5F82, 54),                 # 行送り nY+=54
    # tagStoreData@create: 本スプライト
    (0x1F41AA, 253), (0x1F41B0, 53),
    (0x1F41DC, 193), (0x1F41E8, 60), (0x1F41EE, 53),
    (0x1F4254, 12),                 # 番号フォント
    (0x1F42F6, 253), (0x1F42FC, 53),# カバースプライト
    (0x1F433E, 20),                 # テキストフォント
    (0x1F43BC, 5), (0x1F43C2, 4),   # 日付位置
    (0x1F444A, 5), (0x1F4450, 28),  # タイトル位置
    (0x1F4482, 14), (0x1F4488, 14), # 星スプライト
    (0x1F44BA, 14),                 # 星フォント
    # tagStoreData@setBookPos / setPos
    (0x1F467E, 193),
    (0x1F4726, 193), (0x1F4750, 202), (0x1F475E, 39), (0x1F4792, 193),
    # tagSaveStore@dragData
    (0x1F68BC, 30), (0x1F68D6, 26), # 掴みオフセット
    (0x1F6A9E, 60), (0x1F6AD2, 53), # 本サイズ境界
    (0x1F6C0C, 193),                # 帰還先オフセット
    # tagScrollBar@create: バー太さ
    (0x1B42EA, 20), (0x1B4328, 20),
    # tagScrollBar@setPos: 矢印ボタンオフセット (20px)
    (0x1B4AE6, 20),                 # PUSH 20 (縦: 下矢印)
    (0x1B4B14, 20),                 # .LOCALPLUSA nY3 20
    (0x1B4B44, 20),                 # PUSH 20 (横: 右矢印)
    (0x1B4B72, 20),                 # .LOCALPLUSA nX3 20
    # tagScrollBar@setBar: バー最小サイズ・オフセット
    (0x1B5750, 20),                 # nSize < 20 下限
    (0x1B5762, 20),                 # nSize = 20
    (0x1B5876, 20),                 # .LOCALPLUSA nY 20
    (0x1B588E, 20),                 # .LOCALPLUSA nX 20
    # tagScrollBar@setValue: バーデフォルトサイズ
    (0x1B494E, 20),                 # SH_LOCALASSIGN nSize 20
    # tagScrollBar@setButtonActive: 矢印サイズオフセット
    (0x1B5F7C, 20),                 # .LOCALPLUSA nY 20
    (0x1B5F94, 20),                 # .LOCALPLUSA nX 20
    (0x1B6060, 20), (0x1B6090, 20), # ヒット領域 PUSH 20
    (0x1B610A, 20), (0x1B616A, 20),
    # tagComment
    (0x1B62E2, 16),                 # create フォント
    (0x1B648A, 14),                 # show 行高 (0xe*cnt)
    (0x1B6498, 2),                  # show 行間 (2*(cnt-1))
    (0x1B64B0, 4),                  # show 高さ余白
    (0x1B6476, 4),                  # show 幅余白
    (0x1B6674, 4),                  # show2 幅余白
    (0x1B6688, 16),                 # show2 行高
    (0x1B6696, 4),                  # show2 高さ余白
    (0x1B66BE, 2), (0x1B66D0, 2),   # show2 テキスト原点
    (0x1B6992, 5), (0x1B69A0, 5),   # createBase 外枠 +5
    (0x1B69FC, 5), (0x1B6A02, 5),   # 枠線1
    (0x1B6A20, 5), (0x1B6A32, 5),   # 枠線2
    (0x1B6AAA, 1), (0x1B6AB0, 1),   # 内側オフセット
    (0x1B6ABC, 2), (0x1B6ACA, 2),   # 内側縮小
    (0x1B6AFC, 14),                 # drawText フォント
    (0x1B6BF2, 16),                 # drawText 行送り
    (0x1B6836, 11), (0x1B6850, 20), # setPos マウスオフセット
    (0x1B6900, 568), (0x1B6916, 568), # setPos 下端クランプ
    (0x1B6954, 2), (0x1B6962, 2),   # setPos テキストオフセット
    (0x1B6CD0, 14),                 # getWidth 文字幅係数
    # tagInput@create
    (0x18B58E, 20),                 # テキストボックスフォント
    (0x18B5A0, 4),                  # 行間
    (0x18B5B2, 230), (0x18B5B8, 264), # テキストボックス位置
    (0x18B6A8, 511), (0x18B6AE, 224), # OKボタン位置
]



# SINGLES5: マップ画面 (tagMap/tagMapKuni/tagMapDataManager/tagSystemBar/tagChiiki)
SINGLES5 = [
    # tagMap@create: 地図合成領域 (728x288 -> 1456x576)
    (0x1A80F0, 728), (0x1A80F6, 288),
    # tagSystemBar@create: バー位置とボタン
    (0x1F880C, 568),                # バーY
    (0x1F8852, 502), (0x1F8858, 574),   # ボタン1
    (0x1F889A, 431), (0x1F88A0, 574),   # ボタン2
    (0x1F88E2, 621), (0x1F88E8, 574),   # ボタン3
    (0x1F892A, 331), (0x1F8930, 573),   # ボタン4上
    (0x1F8972, 331), (0x1F8978, 587),   # ボタン5下
    (0x1F8A10, 80), (0x1F8A16, 26),     # 左ボタン1 サイズ
    (0x1F8A28, 2), (0x1F8A2E, 572),     # 左ボタン1 位置
    (0x1F8A8C, 65), (0x1F8A92, 26),     # 左ボタン2 サイズ
    (0x1F8AA4, 86), (0x1F8AAA, 572),    # 左ボタン2 位置
    (0x1F8B08, 65), (0x1F8B0E, 26),     # 左ボタン3 サイズ
    (0x1F8B20, 155), (0x1F8B26, 572),   # 左ボタン3 位置
    (0x1F8B84, 65), (0x1F8B8A, 26),     # 左ボタン4 サイズ
    (0x1F8B9C, 224), (0x1F8BA2, 572),   # 左ボタン4 位置
    # tagSystemBar@checkSelect: バー領域のY判定
    (0x1F913C, 568),
    # tagChiiki@create: 地域リスト枠・スクロール
    (0x1B7234, 2), (0x1B723A, 2),       # スプライト位置(2,2)
    (0x1B7276, 430), (0x1B727C, 3),     # フレーム位置(430,3)
    (0x1B72B8, 3), (0x1B72BE, 3),       # 背景位置(3,3)
    (0x1B7316, 160),                    # タイトルテキスト幅
    (0x1B732E, 406), (0x1B7334, 4),     # タイトル位置
    (0x1B7390, 557), (0x1B7396, 74),    # 矢印ボタン位置
    (0x1B748E, 467), (0x1B7494, 103),   # スクロールバー位置
    (0x1B7506, 149), (0x1B750C, 26),    # 矢印サイズ/位置
    (0x1B7538, 149), (0x1B753E, 26),
    (0x1B75BA, 643), (0x1B75C0, 431),   # 第2スクロール位置
    (0x1B7682, 5), (0x1B7688, 246),     # 要素位置
    # tagCommand@create: コマンドリスト項目
    (0x1B87DA, 16),                     # フォントサイズ
    (0x1B8858, 338), (0x1B885E, 16),    # 項目スプライト w/h
    # tagShisetsu@create: 城/家紋スプライトのバッファサイズ
    (0x1ABAF4, 28), (0x1ABAFA, 38),   # 城アイコン w/h
    (0x1ABB3A, 25), (0x1ABB40, 25),   # 家紋オーバーレイ w/h
    # tagMap@setCursor: 家紋カーソルのスナップ中心 (+25 = 50px家紋の中心)
    # ※SINGLES_ABSで絶対値25を書き込む
    # tagSystemRoute@create: RanceVIIバナー位置 (664,572)
    (0x1FE60E, 664), (0x1FE614, 572),
    # tagShisetsu/tagShisetsuManager: 城アイコン配置
    (0x1ABCFA, 1), (0x1ABD0C, 41),    # setPos 家紋オフセット (+1,+41)
    (0x1ABF9A, 34),                   # setPos 列ピッチ (+34)
    # tagComment: ホバー情報ボックス
    (0x1B64FC, 18), (0x1B650E, 7), (0x1B6520, 18),  # 行高・マージン
    # tagCommand: カーソル位置オフセット
    (0x1B8B3A, -60),
    # tagCommandList@setSelect: 選択カーソル(member3)位置 (x-64, y-4)
    (0x1B902A, -64), (0x1B9038, -4),
    # tagCommandList@setTopIndex: レイアウト
    (0x1B93D4, 66), (0x1B93DE, 6),      # 開始位置
    (0x1B94E2, 20),                     # 行高
    # tagMapInfo@create/setMapNo: 国力パネル
    (0x1AB600, 515), (0x1AB606, 428),   # パネルCG位置
    (0x1AB642, 515), (0x1AB648, 428),   # パネルCG位置(反転版)
    (0x1AB68A, 524), (0x1AB690, 493),   # 数値表示位置
    (0x1AB6A2, 276), (0x1AB6A8, 24),    # 枠スプライト w/h
    (0x1AB6D4, 519), (0x1AB6DA, 432),   # 枠スプライト位置
    (0x1AB70A, 266), (0x1AB710, 27),    # 内側スプライト w/h
    (0x1AB73C, 524), (0x1AB742, 462),   # 内側スプライト位置
    (0x1AB868, 20),                     # フォントサイズ
    (0x1AB8E8, 24),                     # テキストメトリクス
    (0x1AB8EE, 20),                     # フォントサイズ
    # tagMapDataManager@0: 31レコード (markX,markY,maskX,maskY)
    (0x1A8FC0, 705),
    (0x1A8FC6, 56),
    (0x1A8FDE, 626),
    (0x1A8FE4, 6),
    (0x1A8FF8, 663),
    (0x1A8FFE, 176),
    (0x1A9016, 621),
    (0x1A901C, 97),
    (0x1A9030, 584),
    (0x1A9036, 195),
    (0x1A904E, 530),
    (0x1A9054, 142),
    (0x1A9068, 605),
    (0x1A906E, 251),
    (0x1A9086, 576),
    (0x1A908C, 223),
    (0x1A90A0, 661),
    (0x1A90A6, 313),
    (0x1A90BE, 635),
    (0x1A90C4, 265),
    (0x1A90D8, 605),
    (0x1A90DE, 330),
    (0x1A90F6, 576),
    (0x1A90FC, 294),
    (0x1A9110, 556),
    (0x1A9116, 377),
    (0x1A912E, 527),
    (0x1A9134, 354),
    (0x1A9148, 550),
    (0x1A914E, 320),
    (0x1A9166, 538),
    (0x1A916C, 302),
    (0x1A9180, 528),
    (0x1A9186, 275),
    (0x1A919E, 498),
    (0x1A91A4, 235),
    (0x1A91B8, 472),
    (0x1A91BE, 207),
    (0x1A91D6, 447),
    (0x1A91DC, 175),
    (0x1A91F0, 479),
    (0x1A91F6, 254),
    (0x1A920E, 462),
    (0x1A9214, 241),
    (0x1A9228, 424),
    (0x1A922E, 242),
    (0x1A9246, 410),
    (0x1A924C, 226),
    (0x1A9260, 457),
    (0x1A9266, 305),
    (0x1A927E, 434),
    (0x1A9284, 277),
    (0x1A9298, 498),
    (0x1A929E, 373),
    (0x1A92B6, 483),
    (0x1A92BC, 352),
    (0x1A92D0, 446),
    (0x1A92D6, 357),
    (0x1A92EE, 428),
    (0x1A92F4, 330),
    (0x1A9308, 438),
    (0x1A930E, 436),
    (0x1A9326, 418),
    (0x1A932C, 403),
    (0x1A9340, 372),
    (0x1A9346, 473),
    (0x1A935E, 358),
    (0x1A9364, 429),
    (0x1A9378, 397),
    (0x1A937E, 393),
    (0x1A9396, 379),
    (0x1A939C, 347),
    (0x1A93B0, 385),
    (0x1A93B6, 287),
    (0x1A93CE, 363),
    (0x1A93D4, 259),
    (0x1A93E8, 321),
    (0x1A93EE, 271),
    (0x1A9406, 295),
    (0x1A940C, 218),
    (0x1A9420, 348),
    (0x1A9426, 361),
    (0x1A943E, 333),
    (0x1A9444, 320),
    (0x1A9458, 297),
    (0x1A945E, 338),
    (0x1A9476, 280),
    (0x1A947C, 314),
    (0x1A9490, 237),
    (0x1A9496, 283),
    (0x1A94AE, 198),
    (0x1A94B4, 258),
    (0x1A94C8, 242),
    (0x1A94CE, 353),
    (0x1A94E6, 214),
    (0x1A94EC, 331),
    (0x1A9500, 225),
    (0x1A9506, 443),
    (0x1A951E, 164),
    (0x1A9524, 404),
    (0x1A9538, 183),
    (0x1A953E, 357),
    (0x1A9556, 167),
    (0x1A955C, 339),
    (0x1A9570, 146),
    (0x1A9576, 309),
    (0x1A958E, 120),
    (0x1A9594, 289),
    (0x1A95A8, 89),
    (0x1A95AE, 352),
    (0x1A95C6, 57),
    (0x1A95CC, 308),
    (0x1A95E0, 27),
    (0x1A95E6, 378),
    (0x1A95FE, 7),
    (0x1A9604, 345),
    (0x1A9618, 68),
    (0x1A961E, 437),
    (0x1A9636, 32),
    (0x1A963C, 412),
    (0x1A9650, 48),
    (0x1A9656, 494),
    (0x1A966E, 24),
    (0x1A9674, 477),
    # tagShortCutManager@init: F1-F4/F5/ESC ラベルスプライト位置
    (0x1FECD8, 27), (0x1FECDE, 557),    # F1 (27,557)
    (0x1FED3A, 104), (0x1FED40, 557),   # F2 (104,557)
    (0x1FED9C, 172), (0x1FEDA2, 557),   # F3 (172,557)
    (0x1FEDFE, 241), (0x1FEE04, 557),   # F4 (241,557)
    (0x1FEE60, 511), (0x1FEE66, 129),   # F5 (511,129)
    (0x1FEEC2, 41), (0x1FEEC8, 277),    # ESC (41,277)
    # tagChiikiAction@create: 行動回数軍配アイコン
    (0x1B6D84, 126), (0x1B6D8E, 213),   # 基点 (126,213)
    (0x1B6EE8, 27),                    # 列ピッチ 27
    # tagSystemInfo@create: システム情報ダイアログ
    (0x1B9E80, 15), (0x1B9E86, 10),     # タイトルバー位置
    (0x1B9F78, 81), (0x1B9F7E, 24),     # member2 テキスト w/h
    (0x1B9FAA, 172), (0x1B9FB0, 47),    # member2 位置
    (0x1B9EFA, 24),                     # member2 フォント
    (0x1BA01E, 105), (0x1BA024, 35),    # member3 テキスト w/h
    (0x1BA050, 336), (0x1BA056, 82),    # member3 位置
    (0x1BA262, 3),                      # member4 tagDrawText スペース
    (0x1BA27A, 33), (0x1BA280, 100),    # member4 位置
    (0x1BA2C0, 18),                     # member4 フォント
    (0x1BA3F8, 8),                      # member5 tagDrawText スペース
    (0x1BA410, 24), (0x1BA416, 393),    # member5 位置
    (0x1BA456, 16),                     # member5 フォント
    (0x1BA5EE, 467), (0x1BA5F4, 103),   # member6 ボタン1位置
    (0x1BA6B6, 432), (0x1BA6BC, 10),    # member6 ボタン2位置
    (0x1BA81A, 292),                    # 瓢箪アイコン Y
    # tagSystemInfo@getHyotanX: 瓢箪アイコン X (20 + 54*i)
    (0x1BAB98, 20), (0x1BAB9E, 54),
]

SINGLES6 = [
    # tagHoryo@create: 捕虜パネル
    (0x1B2DF0, 282), (0x1B2E04, 201),   # ウィンドウ w/h
    (0x1B2E18, 18), (0x1B2E3C, 29), (0x1B2E42, 420), (0x1B2E66, 18),   # member2 テキスト
    (0x1B2E54, 202),                                                    # member2 テキスト幅
    (0x1B2EA8, 8), (0x1B2ECC, 13), (0x1B2ED2, 287), (0x1B2EF6, 20),    # member3 テキスト
    (0x1B2EE4, 202),                                                    # member3 テキスト幅 (タイトル)
    (0x1B305C, 56), (0x1B3062, 490),    # ボタン1 (勧誘)
    (0x1B310A, 341), (0x1B3110, 288),   # ボタン2 (閉)
    # tagHoryo@open/close: スライドイン (x算出の282, 26, 65, 26, 150)
    (0x1B2CE2, 282), (0x1B2CF6, 26), (0x1B2CFE, 65), (0x1B2D04, 26), (0x1B2D0A, 150),
    (0x1B2D7E, 282), (0x1B2D92, 26), (0x1B2D9A, 65), (0x1B2DA0, 26), (0x1B2DA6, 150),
    # tagHoryo@drawText
    (0x1B3684, 112), (0x1B368E, 39),    # 原点 (112,39)
    (0x1B36C0, 24),                    # フォント
    (0x1B3788, 31), (0x1B37E2, 31),    # 行ピッチ
    # tagDungeon@create: 階層移動確認ダイアログ
    (0x1B3B48, 10), (0x1B3B4E, 36), (0x1B3B54, 568), (0x1B3B5A, 312),  # member3 window (x,y,w,h)
    (0x1B3B7A, 4), (0x1B3B80, 4),      # member3 CG offset
    (0x1B3B92, 8), (0x1B3B98, 8), (0x1B3B9E, 577), (0x1B3BA4, 25), (0x1B3BAA, 20),  # createName
    (0x1B3DBA, 51), (0x1B3DC0, 374),   # member4 tagSelect pos
    # tagDungeon@open/close: zoomUp/zoomDown (51, 374+h-26, 65, 26, 150) + wait 100
    (0x1B3932, 51), (0x1B3938, 374), (0x1B394C, 26),
    (0x1B3954, 65), (0x1B395A, 26), (0x1B3960, 150), (0x1B38C2, 100),
    (0x1B3A22, 51), (0x1B3A28, 374), (0x1B3A3C, 26),
    (0x1B3A44, 65), (0x1B3A4A, 26), (0x1B3A50, 150), (0x1B3A6A, 100),
    # tagItem@create: アイテムアイコンバッファ 64x64
    (0x1BAE34, 64), (0x1BAE3A, 64), (0x1BAED8, 64), (0x1BAEDE, 64),
    (0x1BADB6, 44),                     # 空きスロット番号テキスト フォントサイズ
    (0x1BB004, 64), (0x1BB00A, 64),
    # tagItemList@create: アイテム倉庫
    (0x1BBCA2, 282), (0x1BBCB6, 201),   # ウィンドウ w/h
    (0x1BC09E, 202),                    # アイテムスプライト z (panel z+1 相当)
    (0x1BBCCA, 6), (0x1BBCEE, 13), (0x1BBCF4, 287), (0x1BBD18, 20),    # member3 テキスト
    (0x1BBD06, 202),                                                    # member3 テキスト幅 (タイトル)
    (0x1BBDC2, 8), (0x1BBDE6, 9), (0x1BBDEC, 550), (0x1BBE10, 14),     # member4 テキスト
    (0x1BBDFE, 202),                                                    # member4 テキスト幅
    (0x1BBE66, 202), (0x1BBE6C, 173),   # member5 スクロールバー位置
    (0x1BBE84, 351), (0x1BBE8A, 335),   # member5 スクロールトラック
    # ※スクロール範囲最大行数(18)は論理値のため2倍化しない
    (0x1BBFA4, 341), (0x1BBFAA, 288),   # member6 閉ボタン位置
    # tagItemList@open/close: スライド (86, 572, 65, 26, 150)
    (0x1BBBB0, 86), (0x1BBBB6, 572), (0x1BBBBC, 65), (0x1BBBC2, 26), (0x1BBBC8, 150),
    (0x1BBC1A, 86), (0x1BBC20, 572), (0x1BBC26, 65), (0x1BBC2C, 26), (0x1BBC32, 150),
    # tagItemList@getItemPosX/Y: グリッド (11+68c, 342+68r)
    (0x1BDE1E, 11), (0x1BDE24, 68), (0x1BDE44, 342), (0x1BDE4A, 68),
    # tagItemList@dragItem: ドラッグ中アイコン
    (0x1BCEA6, 32), (0x1BCEC0, 32),     # センタリングオフセット
    (0x1BD0C8, 64), (0x1BD0FC, 64),     # バッファサイズ
    (0x1BD230, 376), (0x1BD236, 282),   # ドロップ判定矩形
    # tagForce@open/close: スライド (155, 572, 65, 26, 150)
    (0x1BF0E0, 155), (0x1BF0E6, 572), (0x1BF0EC, 65), (0x1BF0F2, 26), (0x1BF0F8, 150),
    (0x1BF14A, 155), (0x1BF150, 572), (0x1BF156, 65), (0x1BF15C, 26), (0x1BF162, 150),
    # tagForce@create: 兵力パネル
    (0x1BF1C0, 282), (0x1BF1D4, 201),   # ウィンドウ w/h
    (0x1BF1E8, 13), (0x1BF1EE, 287), (0x1BF1F4, 202),    # タイトルバー (13,287,202)
    (0x1BF206, 185), (0x1BF20C, 343), (0x1BF212, 202),   # ボタン 補充 (185,343)
    (0x1BF242, 185), (0x1BF248, 411), (0x1BF24E, 202),   # ボタン 増員 (185,411)
    (0x1BF27E, 185), (0x1BF284, 479), (0x1BF28A, 202),   # ボタン 解雇 (185,479)
    (0x1BF2BC, 44), (0x1BF2C2, 16),     # member8 バッファ
    (0x1BF2EE, 318), (0x1BF2F4, 538),   # member8 位置
    # NOTE: member9 tagNumberList createCanvas(177,16, r2,g79,b41,a179) -
    # only w/h are pixels; the r/g/b/a color args must not be doubled.
    (0x1BF31C, 177), (0x1BF322, 16),
    (0x1BF34E, 10), (0x1BF354, 530),    # member9 位置
    (0x1BF45C, 56), (0x1BF462, 147),    # member12 ボタン群1 (一発補充)
    (0x1BF50A, 299), (0x1BF510, 286),   # member12 ボタン群2 (決)
    # tagForceFull@create: 一発補充パネル
    (0x1BE110, 13), (0x1BE116, 7),      # タイトルバー (13,7)
    # tagForceFull@drawText
    (0x1BE518, 112), (0x1BE522, 39),    # 原点 (112,39)
    (0x1BE554, 24),                    # フォント
    (0x1BE61C, 31), (0x1BE676, 31),    # 行ピッチ
    # tagForceGold@create: コスト/金 CG位置
    (0x1BE76A, 242), (0x1BE770, 529),
    (0x1BE7A8, 223), (0x1BE7AE, 533),
    (0x1BE7EA, 223), (0x1BE7F0, 533),
    # tagForceScroll@create: +/-スクローラ バッファ・オフセット
    (0x1BEA36, 182), (0x1BEA3C, 16),    # member4 バッファ
    (0x1BEAA6, 182), (0x1BEAAC, 20),    # member5 バッファ
    (0x1BEA7C, 20),                    # member4 Yオフセット
    (0x1BEA04, 0x8e),                  # tagScrollBar max size 142
    # フォント
    (0x1BEE2E, 14),                    # tagForceScroll@setText
    (0x1C05DE, 14),                    # tagForce@set
    (0x1C0AAC, 14),                    # tagForce@setInfo
]

# SINGLES7: 武将一覧テーブル (アイテム倉庫/兵力/捕虜パネルの背後に共通表示)
# tagBushoList (コンテナ) + tagBusho (行) + tagBushoManager/Arrange + tagBushoInfo
SINGLES7 = [
    # tagBusho@setPos: 行内スプライト配置 (member1/2:+1, member4:+2/+1,
    #   member8:+90/+1, member9:+125/+1, member10:+168/+1, member11:+153/+1)
    # NOTE: 0x1E92D8 PUSH 0x1 is `paramX(i+1)` index, not a pixel offset
    (0x1E9308, 1), (0x1E9368, 1), (0x1E938A, 2),
    (0x1E9398, 1), (0x1E93B2, 0x5a), (0x1E93C0, 1), (0x1E93DC, 0x7d),
    (0x1E93EA, 1), (0x1E9420, 0xa8), (0x1E942E, 1), (0x1E944A, 0xe9),
    (0x1E9458, 1), (0x1E947A, 0x99), (0x1E9488, 1),
    # tagBusho@setRect: 行の当たり判定 411x15
    (0x1E94C6, 0x19b), (0x1E94CC, 0xf),
    # tagBusho@create: フォント14, member7高さ14, member8(35x14), member10(69x14),
    #   member12(13x14)
    (0x1E827E, 0xe), (0x1E8320, 0xe), (0x1E8382, 0x23), (0x1E8388, 0xe),
    (0x1E83FC, 0x45), (0x1E8402, 0xe), (0x1E8466, 0xd), (0x1E846C, 0xe),
    # tagBusho@create2: 同上 (member8 70x14, member10 54x14, member11 78x14)
    (0x1E8796, 0xe), (0x1E8838, 0xe), (0x1E88E2, 0x46), (0x1E88E8, 0xe),
    (0x1E8930, 0x36), (0x1E8936, 0xe), (0x1E8962, 0x4e), (0x1E8968, 0xe),
    # tagBusho@createStatus: -100 (行高調整)
    (0x1E9A28, 0x64),
    # tagBusho@drawParamNormal: フォント14, 位置(69,14)(14,14), ピッチ14
    (0x1E9BD2, 0xe), (0x1E9D56, 0x45), (0x1E9D5C, 0xe),
    (0x1E9D7E, 0xe), (0x1E9D84, 0xe), (0x1E9E90, 0xe),
    # tagBusho@drawParamSpecial: 同上 (位置 54,14 / 14,14)
    (0x1E9F6A, 0xe), (0x1EA062, 0x36), (0x1EA068, 0xe),
    (0x1EA08A, 0xe), (0x1EA090, 0xe), (0x1EA19C, 0xe),
    # tagBusho@setWaza: アイコン位置(13,14) ピッチ13 x2系
    (0x1EA3A6, 0xd), (0x1EA3AC, 0xe), (0x1EA3C0, 13),
    (0x1EA41A, 0xd), (0x1EA420, 0xe), (0x1EA434, 13),
    # tagBushoManager@getBushoX: 行X (482 / 382)
    (0x1EB9FC, 0x1e2), (0x1EBA0A, 0x17e),
    # tagBushoManager@getBushoY: 行Y = 110 + idx*15
    (0x1EBA20, 0x6e), (0x1EBA26, 0xf),
    # tagBushoManager@getBushoParamX: パラメータ列 (153 / 90 / 230+21p)
    (0x1EBBF4, 0x99), (0x1EBC16, 0x5a), (0x1EBC24, 0xe6), (0x1EBC38, 0x15),
    # tagBushoManager@getBushoParamWidth: (69 / 55 / 13)
    (0x1EBCBA, 0x45), (0x1EBCDC, 0x37), (0x1EBCEA, 0xd),
    # tagBushoList@open/close: スライド (65, 26, 250)
    (0x1EBF36, 0x41), (0x1EBF4C, 0x1a), (0x1EBF54, 0x41), (0x1EBF5A, 0x1a),
    (0x1EC054, 0x41), (0x1EC06A, 0x1a), (0x1EC072, 0x41), (0x1EC078, 0x1a),
    # tagBushoList@create: カーソルz+10/+31, コメント(11,6)z+1, member13 z+1
    (0x1EC2D2, 0xa), (0x1EC322, 0x1f),
    (0x1EC338, 0xb), (0x1EC346, 6), (0x1EC35A, 1), (0x1EC37C, 1),
    # tagBushoList@createBase: ベース(376,y2)z201, タイトル(381,60)z203
    (0x1ED856, 0x178), (0x1ED85C, 2), (0x1ED870, 0xc9),
    (0x1ED8CC, 0x17d), (0x1ED8D2, 0x3c), (0x1ED8E6, 0xcb),
    # tagBushoList@createBase2: フィルム(476/376,y2)z201, テキスト(242,72)(64,33)フォント16
    (0x1ED918, 0x1dc), (0x1ED924, 0x178), (0x1ED94A, 2), (0x1ED956, 2),
    (0x1ED994, 0xc9), (0x1ED9BE, 0x10),
    (0x1EDA4E, 0xf2), (0x1EDA54, 0x48), (0x1EDA86, 0x40), (0x1EDA8C, 0x21),
    # tagBushoList@createBright: ハイライト領域 y61 h500, x+382, z202
    (0x1EDB22, 61), (0x1EDB30, 0x1f4),
    (0x1EDB5E, 0x17e), (0x1EDC10, 0x17e),
    (0x1EDBD4, 0xca), (0x1EDC86, 0xca),
    # tagBushoList@brightParam: nY-59, 矩形 55x14
    (0x1ECC28, 59), (0x1ECC44, 0x37), (0x1ECC4A, 0xe),
    # tagBushoList@createButton: ボタン位置 (665,765) z+31, (381,33)(477,33)(573,33)
    (0x1EDDFE, 0x299), (0x1EDE04, 8), (0x1EDE22, 0x2fd), (0x1EDE28, 8),
    (0x1EDF18, 0x1f), (0x1EDFFC, 5), (0x1EE010, 0x1f),
    (0x1EE17A, 0x17d), (0x1EE180, 0x21),
    (0x1EE2E0, 0x1dd), (0x1EE2E6, 0x21), (0x1EE310, 0x14),
    (0x1EE3B6, 0x23d), (0x1EE3BC, 0x21),
    # NOTE: 0x1EE3EE PUSH 0x3 in execArrange is a mode guard, not a pixel offset
    # tagBushoArrange@0: バー位置 (340,103) 高さ15, (39,15)
    (0x1F19F4, 0x154), (0x1F19FA, 0x67), (0x1F1A00, 0xf),
    (0x1F1A10, 0x27), (0x1F1A16, 0xf),
    # tagBushoArrange@create: カーソルz+1, ヴェールz911, バー(340,8)z912, z913
    (0x1F1CE6, 1), (0x1F1D52, 0x38f),
    (0x1F1D8E, 0x154), (0x1F1D94, 8), (0x1F1DA8, 0x390), (0x1F1DD0, 0x391),
    # tagBushoArrange@arrange: z+1
    (0x1F282A, 1),
    # tagBushoArrange@squeeze1/2: 行ピッチ15, nY3+=15 / -=15
    (0x1F2DBE, 0xf), (0x1F2EC0, 0xf), (0x1F2E78, 15), (0x1F2F6A, 15),
    (0x1F31C0, 0xf), (0x1F32C2, 0xf), (0x1F327A, 15), (0x1F336C, 15),
    # tagBushoInfo@create: 情報パネル内レイアウト
    (0x1EEAA0, 1), (0x1EEAA6, 2),                    # member3 pos(1,2)
    (0x1EEAF2, 0xc), (0x1EEAF8, 8), (0x1EEB10, 1), (0x1EEB24, 0x14),  # member4(12,8)z+1 f20
    (0x1EEBBC, 0x9c), (0x1EEBC2, 8), (0x1EEBCE, 1),  # member5 pos(156,8)z+1
    (0x1EEBF6, 7), (0x1EEBFC, 0x22), (0x1EEC16, 2),  # member7 pos(7,34)z+2
    (0x1EEC38, 0xf), (0x1EEC3E, 0x2a), (0x1EEC56, 3),  # member8 pos(15,42)z+3
    (0x1EEC8E, 0x59), (0x1EEC94, 0x25), (0x1EECAC, 2), (0x1EECC0, 0xe),  # member11(89,37)z+2 f14
    # tagBushoInfo@setItemNo: アイテムアイコン位置 (29,204)
    (0x1EEEC2, 0x1d), (0x1EEEC8, 0xcc),
    # tagBushoInfo@draw: パラメータ原点y124, フォント14x5, 行ピッチ14x4
    (0x1EF840, 0x7c),
    (0x1EF84E, 0xe), (0x1EF87A, 0xe), (0x1EF8A6, 0xe), (0x1EF8D2, 0xe), (0x1EF8FE, 0xe),
    (0x1EF868, 14), (0x1EF894, 14), (0x1EF8C0, 14), (0x1EF8EC, 14),
    # tagBushoInfo@createUnit: バッファ(362x241), 位置(7,34)z+1
    (0x1F00E4, 0x16a), (0x1F00EA, 0xf1),
    (0x1F0116, 7), (0x1F011C, 0x22), (0x1F013C, 1),
    # tagBushoInfo@createUnit: CGソース矩形 (x,y) x9ペア
    (0x1F01D8, 0x170), (0x1F01DE, 0xc9), (0x1F01F2, 0x1a3), (0x1F01F8, 0x106),
    (0x1F020C, 0x14d), (0x1F0212, 0x120), (0x1F0286, 0x137), (0x1F028C, 0xdb),
    (0x1F02A0, 0x19a), (0x1F02A6, 0x107), (0x1F02BA, 0x109), (0x1F02C0, 0x131),
    (0x1F034A, 0x15e), (0x1F0350, 0xc8), (0x1F0384, 0x1a3), (0x1F038A, 0x106),
    (0x1F039E, 0x13b), (0x1F03A4, 0x128),
    # tagBushoInfo@blendUnit: ブレンド位置 (7,34)
    (0x1F03E8, 7), (0x1F0402, 0x22),
    # tagBushoInfo@createAction: フォント14, テキスト幅14, バッファ高14 x2
    (0x1F0496, 0xe), (0x1F05E8, 0xe), (0x1F060E, 0xe), (0x1F0676, 0xe),
    (0x1F0B46, 22),                              # nX2 += 22
    # tagBushoInfo@dragItem: センタリング -32, バッファ +64, ドロップ矩形
    (0x1EFBE8, 0x20), (0x1EFC02, 0x20), (0x1EFE0A, 0x40), (0x1EFE3E, 0x40),
    (0x1EFF16, 0x11a), (0x1EFF1C, 0x178), (0x1EFF22, 0x23c),
]

# SINGLES8: タイトルメニュー (tagTitle@create) ボタン座標・ピッチ
SINGLES8 = [
    (0x1FF6A0, 0xf2),                  # メニュー基準X 242
    (0x1FF6AA, 0x19a),                 # メニュー基準Y 410
    (0x1FF6F6, 39), (0x1FF728, 39), (0x1FF75A, 39),  # 行ピッチ
    (0x19A6AA, 18),                    # tagSelectCg@createSpTitle: ボタン文字フォント
    (0x199D7C, 322), (0x199D8E, 32),   # tagSelectCg@create: ボタンCGワークサイズ
    # tagSelectCg@create: 状態スプライトへのdrawCg転写 (3,3, slice, 0,0,316,26)
    (0x199E7E, 3), (0x199E84, 3),      # member0 転写先オフセット
    (0x199EA4, 316), (0x199EAA, 26),   # member0 転写元サイズ
    (0x199F92, 3), (0x199F98, 3),      # member1 転写先オフセット
    (0x199FB8, 316), (0x199FBE, 26),   # member1 転写元サイズ
    (0x19A0A6, 3), (0x19A0AC, 3),      # member2 転写先オフセット
    (0x19A0CC, 316), (0x19A0D2, 26),   # member2 転写元サイズ
]

# SINGLES9: 武将詳細パネル (tagBushoRelation@create) 感情マーク/ラベル配置
SINGLES9 = [
    (0x1F0A66, 1),                     # マーク x オフセット nX+1
    (0x1F0A80, 2),                     # マーク y オフセット nY+2
    (0x1F0BE2, 154),                   # ラベル x オフセット nX+154
    (0x1F0BFC, -2),                    # ラベル y オフセット nY-2
]

# SINGLES10: 結果ダイアログ (tagSystemMessage@create) 顔/テキスト/タイトル配置
SINGLES10 = [
    (0x1FDBEC, 129), (0x1FDBF2, 195),  # 顔アイコン位置
    (0x1FDC42, 7),                     # メイン文 create 行間
    (0x1FDC54, 326), (0x1FDC5A, 199),  # メイン文 setPos
    (0x1FDC9A, 24),                    # メイン文フォントサイズ
    (0x1FDCFE, 2),                     # サブ文 create 行間
    (0x1FDD10, 344), (0x1FDD16, 304),  # サブ文 setPos
    (0x1FDD56, 24),                    # サブ文フォントサイズ
    (0x1FDDAC, 1), (0x1FDDB2, 1),
    (0x1FDDB8, 1), (0x1FDDBE, 1),      # サブ文シャドウ幅
    (0x1FDE04, 130), (0x1FDE0A, 165),  # タイトルバー位置
]

# SINGLES11: 起動シーケンス (ShowAliceLogo/ShowWarningScreen) 背景・マスク帯
SINGLES11 = [
    (0x2142D0, 800), (0x2142D6, 600),  # AliceLogo 白背景スプライトサイズ
    (0x2142F4, 800), (0x2142FA, 600),  # AliceLogo 白背景塗りつぶし矩形
    (0x213EFC, 800), (0x213F02, 94),   # 注意文 黒マスク帯スプライトサイズ
    (0x213F20, 800), (0x213F26, 94),   # 注意文 黒マスク帯塗りつぶし矩形
    (0x213F50, 506),                   # 注意文 黒マスク帯 y 位置
]

# SINGLES12: 帝ノート画面 (tagMikadoNote@create / tagMikadoData@create)
SINGLES12 = [
    (0x20267E, 182), (0x202684, 26),   # タイトルバー位置
    (0x20280C, 643), (0x202812, 431),  # ボタン0 位置
    (0x2028D4, 597), (0x2028DA, 26),   # ボタン1 位置
    (0x2029A0, 57), (0x2029A6, 104),   # グリッド y 原点/行ピッチ
    (0x2029F2, 180), (0x2029F8, 111),  # グリッド x 原点/列ピッチ
    (0x2023FE, 68), (0x20240C, 52),    # 得点数字のカード内オフセット
]


# SINGLES13: 合戦画面 (tagBattle*/tagBushoFace/tagSanka*/tagSansen* レイアウト)
SINGLES13 = [
    # tagBushoFace@createSp
    (0x1AC8C0, 10), (0x1AC93E, 65), (0x1AC944, 72), (0x1AC970, 1),
    (0x1AC976, 1), (0x1AC97C, 63), (0x1AC982, 70), (0x1AC9A6, 1),
    (0x1AC9AC, 1), (0x1AC9B2, 63), (0x1AC9B8, 70),
    # tagSanka@create
    (0x1AD142, 65), (0x1AD148, 72), (0x1AD1AA, 16), (0x1AD1B0, 16),
    (0x1AD1E2, 25), (0x1AD1F0, -22),
    # tagSanka@set
    (0x1AD364, 16),
    # tagSankaList@open
    (0x1AD7F0, 1), (0x1AD7F6, 282), (0x1AD80A, 26), (0x1AD812, 65),
    (0x1AD818, 26),
    # tagSankaList@close
    (0x1AD88C, 1), (0x1AD892, 282), (0x1AD8A6, 26), (0x1AD8AE, 65),
    (0x1AD8B4, 26),
    # tagSankaList@create
    (0x1AD8FE, 1), (0x1AD904, 282), (0x1AD950, 120), (0x1AD956, 28),
    (0x1AD982, 193), (0x1AD988, 424), (0x1AD9D4, 13), (0x1AD9DA, 287),
    (0x1AD9FE, 20), (0x1ADB6A, 286),
    # tagSankaList@setValue
    (0x1AEE94, 24),
    # tagSankaList@drawInfo
    (0x1AF2BE, 24), (0x1AF342, 20), (0x1AF778, 39), (0x1AF784, 0),
    (0x1AF78A, 0),
    # tagSansenList@open
    (0x1AFBC0, 1), (0x1AFBC6, 282), (0x1AFBDA, 26), (0x1AFBE2, 65),
    (0x1AFBE8, 26),
    # tagSansenList@close
    (0x1AFC64, 1), (0x1AFC6A, 282), (0x1AFC7E, 26), (0x1AFC86, 65),
    (0x1AFC8C, 26),
    # tagSansenList@create
    (0x1AFCDE, 1), (0x1AFCE4, 282), (0x1AFD0C, 13), (0x1AFD12, 287),
    (0x1AFDFA, 225), (0x1AFE00, 286), (0x1AFEDC, 225), (0x1AFEE2, 286),
    (0x1AFFAA, 299), (0x1AFFB0, 286), (0x1B0082, 188), (0x1B00BC, 315),
    (0x1B013C, 82), (0x1B0154, 180),
    # tagSansenTeki@open
    (0x1B215C, 1), (0x1B2162, 282), (0x1B2176, 26), (0x1B217E, 65),
    (0x1B2184, 26),
    # tagSansenTeki@close
    (0x1B21F4, 1), (0x1B21FA, 282), (0x1B220E, 26), (0x1B2216, 65),
    (0x1B221C, 26),
    # tagSansenTeki@create
    (0x1B2266, 1), (0x1B226C, 282), (0x1B2294, 45), (0x1B229A, 287),
    (0x1B236E, 341), (0x1B2374, 288), (0x1B23F2, 10), (0x1B242C, 315),
    (0x1B24AC, 82), (0x1B24C4, 180), (0x1B2590, 10), (0x1B2596, 3),
    # tagForceFull@create
    (0x1BE0E2, 1), (0x1BE0E8, 2), (0x1BE122, 1),
    # tagForce@create
    (0x1BF1BA, 1),
    # tagBattle@createSpot
    (0x1C1ADE, 6), (0x1C1AFC, 0), (0x1C1B02, 0), (0x1C1B22, 0),
    (0x1C1B28, 320),
    # tagBattle@createSpot2
    (0x1C1BAE, 6), (0x1C1BCC, 0), (0x1C1BD2, 0), (0x1C1BF2, 0),
    (0x1C1BF8, 320),
    # tagBattle@showNumber
    (0x1C20AA, 42), (0x1C20C2, 598), (0x1C2110, 42), (0x1C2116, 278),
    (0x1C213A, 598), (0x1C2140, 278),
    # tagBattle@hideNumber
    (0x1C217E, 42), (0x1C2184, 278), (0x1C21BA, 598), (0x1C21C0, 278),
    (0x1C2296, 42), (0x1C22AE, 598),
    # tagBattle@fillSpotMask
    # NOTE: the 0x80 mask-fill values are alpha levels, not pixels. Doubling
    # them to 256 clamps to opaque and paints the card icon tab solid black.
    (0x1C2D26, 320), (0x1C2D44, 178), (0x1C2D4A, 80), (0x1C2D50, 0),
    (0x1C2D7A, 154), (0x1C2D88, 24), (0x1C2D8E, 26),
    (0x1C2DAC, 154), (0x1C2DBA, 54), (0x1C2DC2, 24), (0x1C2DC8, 26),
    (0x1C2DFA, 24), (0x1C2E00, 26),
    (0x1C2E2C, 54), (0x1C2E34, 24), (0x1C2E3A, 26),
    # tagBattleBase@create
    (0x1C2E9C, 800), (0x1C2EA2, 314), (0x1C2EB6, 0), (0x1C2EBC, 0),
    (0x1C2EF8, 0), (0x1C2EFE, 0), (0x1C2F04, 800), (0x1C2F0A, 314),
    (0x1C2F42, 0), (0x1C2F48, 0), (0x1C2FA0, 0), (0x1C2FA6, 0),
    (0x1C3006, 800), (0x1C300C, 254), (0x1C3020, 0), (0x1C3026, 0),
    (0x1C3032, 0), (0x1C3038, 24), (0x1C303E, 800), (0x1C3044, 254),
    (0x1C3056, 0), (0x1C305C, 314), (0x1C3098, 800), (0x1C309E, 24),
    (0x1C30CA, 0), (0x1C30D0, 0), (0x1C30DC, 0), (0x1C30E2, 0),
    (0x1C30E8, 800), (0x1C30EE, 24), (0x1C3100, 0), (0x1C3106, 290),
    # tagBattlePlace@leave
    (0x1C4504, 400),
    # tagBattlePlace@leave2
    (0x1C4802, 400),
    # tagBattlePlace@calcBushoPosX
    (0x1C681E, 182), (0x1C6824, 180), (0x1C683C, 440), (0x1C6842, 180),
    # tagBattlePlace@calcBushoPosY
    (0x1C6862, 322), (0x1C6868, 82),
    # tagBattleBusho@create
    (0x1C7408, 178), (0x1C740E, 80), (0x1C7446, 154), (0x1C744C, 0),
    (0x1C7452, 24), (0x1C7458, 26), (0x1C7470, 154), (0x1C7476, 54),
    (0x1C747C, 24), (0x1C7482, 26), (0x1C74A0, 0), (0x1C74A6, 0),
    (0x1C74AC, 24), (0x1C74B2, 26), (0x1C74CA, 0), (0x1C74D0, 54),
    (0x1C74D6, 24), (0x1C74DC, 26),
    # tagBattleBusho@setKekka
    (0x1C872A, 18),
    # tagBattleBusho@_setPos
    (0x1C8EF6, 1), (0x1C8F04, 1), (0x1C8FF0, 4), (0x1C8FFE, 4),
    (0x1C9018, 70), (0x1C9026, 44), (0x1C9040, 69), (0x1C904E, 61),
    (0x1C906A, 150), (0x1C9094, -1), (0x1C90A2, -1), (0x1C90C4, 109),
    (0x1C90D2, 4), (0x1C90EC, 28), (0x1C90FA, 44), (0x1C9114, 26),
    (0x1C9122, 61), (0x1C913E, 1), (0x1C9168, 23), (0x1C9176, -1),
    # tagBattleName@create
    (0x1C9398, 84), (0x1C939E, 14),
    # tagBattleName@set
    (0x1C940C, 14),
    # tagBattleName@setPos
    (0x1C9570, 57), (0x1C957C, 27),  (0x1C9596, 3),
    (0x1C95D0, 8), (0x1C95DC, 2),
    # tagBattleHp@create
    (0x1C974A, 80), (0x1C9750, 17), (0x1C9812, 16),
    # tagBattleHp@setPos
    (0x1C9E74, 1), (0x1C9E82, 11), (0x1C9E9C, 19), (0x1C9EAA, 1),
    (0x1C9EC4, 55), (0x1C9ED2, 1), (0x1C9EEC, 4), (0x1C9EFA, 1),
    # tagBattleHp@drawCount
    (0x1CA2B2, 16),
    # tagBattleLevel@setPos
     (0x1CA630, 3),  (0x1CA650, 175),
    (0x1CA666, 12),  (0x1CA680, 3), (0x1CA6B2, 12),
    (0x1CA6DC, 11), (0x1CA6EA, 1),
    # tagBattleLevel@createBack
    (0x1CA8B0, 11), (0x1CA8B6, 0),
    # tagBattleWaza@create
    (0x1CA9AE, 13), (0x1CA9B4, 17),
    # tagBattleWaza@set
    (0x1CABDE, 0), (0x1CABE4, 0), (0x1CABF0, 0), (0x1CABF6, 0),
    (0x1CABFC, 13), (0x1CAC02, 17), (0x1CAC42, 0), (0x1CAC48, 0),
    (0x1CAC54, 0), (0x1CAC5A, 0), (0x1CAC60, 13), (0x1CAC66, 17),
    (0x1CACA6, 0), (0x1CACAC, 0), (0x1CACB8, 0), (0x1CACBE, 0),
    (0x1CACC4, 13), (0x1CACCA, 17), (0x1CAD0A, 0), (0x1CAD10, 0),
    (0x1CAD16, 13), (0x1CAD1C, 17),
    # tagBattleWaza@setPos
    (0x1CAE4A, 71), (0x1CAE56, 29),  (0x1CAE70, 62),
    (0x1CAF18, 95), (0x1CAF24, 53),  (0x1CAF3E, 64),
    # tagBattleFuyo@setPos
    (0x1CB4F0, 6), (0x1CB4FC, 112),  (0x1CB516, 68),
    # tagBattleStatus@create
    (0x1CB6F4, 14), (0x1CB7EE, 80), (0x1CB7F4, 21), (0x1CB86C, 80),
    (0x1CB872, 21),
    # tagBattleStatus@setPos
    (0x1CBC84, 70), (0x1CBC90, 28),  (0x1CBCAA, 21),
    (0x1CBD1A, 50), (0x1CBD28, 7),
    # tagBattleButton@add
    (0x1CC128, 16), (0x1CC724, 134), (0x1CC72A, 20),
    # tagBattleSequence@moveLeft
    (0x1CF538, 289),
    # tagBattleArrow@set: m_nX = 0x55 + 0x64*(nSeqNo-2), m_nY = 275
    (0x1D1804, 85), (0x1D180A, 100), (0x1D182E, 275),
    # tagBattleArrow@update: bob bounds (cmp+assign for each of 275/280)
    (0x1D16C2, 275), (0x1D16D8, 275), (0x1D171A, 280), (0x1D1730, 280),
    # tagBattleFlag@create
    (0x1D0492, 100), (0x1D0498, 14),
    # tagBattleFlag@draw
    (0x1D05FC, 14),
    # tagBattleFlag@moveEnd
    (0x1D0A78, 289), (0x1D0AA6, 289),
    # tagBattleFlag@moveStart: auto moveSize 0x19/0x64, mode1 start nY=314,
    # mode2 start nY=0x121 (moveDown runs 289->314; moveUp runs 314->289)
    (0x1D08E4, 25), (0x1D0934, 100), (0x1D0992, 314), (0x1D09BA, 289),
    # tagBattleFlag@moveInStart
    # tagBattleFlag@setPos
    (0x1D0F46, 9), (0x1D0F54, 8),
    # tagBattleEffect@setPosFromBusho
    (0x1D2102, 1), (0x1D2172, 50),
    # tagBattleNumber@create
    (0x1D5F42, 40), (0x1D5F48, 34),
    # tagBattleNumber@updateDamage
    (0x1D6B94, 40), (0x1D6B9A, 34), (0x1D6BC6, 0), (0x1D6BCC, 0),
    (0x1D6BDE, 0), (0x1D6BE4, 40), (0x1D6BEA, 34), 
    (0x1D6BFE, 34), (0x1D6C0A, 278), (0x1D6C3C, 40), (0x1D6C42, 34),
    (0x1D6C80, 40), (0x1D6C86, 34), (0x1D6CC6, 40), (0x1D6CCC, 34),
    # tagBattleNumber@updateHeal
    (0x1D6F32, 278), (0x1D6F8C, 0), (0x1D6F92, 0), (0x1D6FA4, 0),
    (0x1D6FAA, 40), (0x1D6FB0, 34),  (0x1D6FCA, 244),
    (0x1D6FFA, 40), (0x1D7000, 34),
    # tagBattleTime@create
    (0x1D7170, 375), (0x1D7176, 326), (0x1D72A4, 1),
    # tagBattleBar@create
    (0x1D7B4E, 400), (0x1D7B54, 9), (0x1D7BB4, 14), (0x1D7C5C, 14),
    # tagBattleBar@moveStart: y start offset 3, home x 0xad=173, y 3
    (0x1D80D2, 3), (0x1D80EC, 173), (0x1D80F2, 3),
    # tagBattleBar@moveEnd
    (0x1D813C, 173), (0x1D8142, 3),
    # tagBattleBar@move: nY base 3, clamp 3, home x 0xad=173
    (0x1D81B4, 3), (0x1D81E4, 3), (0x1D81F4, 173),
    # tagBattleBar@createBar: fill h 9, enemy width base 400, marker +0x18/-2
    (0x1D861C, 9), (0x1D864C, 400), (0x1D865A, 9),
    (0x1D867A, 24), (0x1D86A2, -2),
    # tagBattleBar@calcBarSize: default 200x2, bar total width 0x190 x5
    (0x1D8762, 200), (0x1D8774, 200),
    (0x1D878C, 400), (0x1D87AE, 400), (0x1D87D6, 400),
    (0x1D8800, 400), (0x1D8820, 400),
    # tagBattleBar@move
    # tagBattleBar@setPos
    (0x1D83E4, 27), (0x1D83F2, 1), (0x1D840E, 219), (0x1D841C, -3),
    (0x1D8438, 27), (0x1D8446, 12), (0x1D8460, 217), (0x1D846E, 12),
    (0x1D8488, 24), (0x1D849E, -2),
    # tagBattleDungeon@create: metrics nSize (0x1D89D6) plus the fontsize
    # args used for layout math (centerX/normalizeTextY/getTextWidth) —
    # leaving them at 18 draws the digits half a text-width off, on top of
    # the name itself. nY+=1 baseline tweak doubled as well.
    (0x1D89D6, 18),
    (0x1D8A62, 18), (0x1D8A90, 18), (0x1D8AE0, 18), (0x1D8B4C, 18),
    (0x1D8B02, 1),
    # tagBattleDungeon@move/Start/End: plate X=174->348, rest Y=3->6
    (0x1D8CC6, 500), (0x1D8D04, 500),
    (0x1D8C06, 3), (0x1D8C20, 174), (0x1D8C26, 3),
    (0x1D8C70, 174), (0x1D8C76, 3), (0x1D8CE8, 3), (0x1D8D28, 174),
    # tagBattleMessage@create: portrait pos (bRight 0x24e : 0xc, nY=0x2f),
    # face x-nudge for cgNo==99, msg box nY=0xea, text offsets (0xd/0x21, 9),
    # text metrics spacing (13, 4)
    (0x1D8F26, 590), (0x1D8F32, 12), (0x1D8F40, 47), (0x1D9092, 2),
    (0x1D919E, 234), (0x1D9228, 13), (0x1D9234, 33), (0x1D9242, 9),
    (0x1D924E, 13), (0x1D9254, 4),
    (0x1D8FB4, 6), (0x1D8FBA, 33), (0x1D8FC0, 186), (0x1D8FC6, 220),
    (0x1D8FEA, 6), (0x1D8FF0, 33), (0x1D8FF6, 186), (0x1D8FFC, 220),
     (0x1D9050, 6),  (0x1D906A, 33),
    (0x1D90DC, 1), (0x1D9184, 238), (0x1D9190, 200), 
    (0x1D91B2, 10), (0x1D925A, 2), (0x1D929A, 1), (0x1D92C2, 24),
    # tagBattleMessage@wait2
    (0x1D9480, 9),
    (0x1D9462, 13), (0x1D946E, 33), (0x1D94B0, 310), (0x1D94BE, 90),
    (0x1D94D8, 2),
    # tagBattleMessage@drawName: normalizeTextY(24, 16) vertical centering
    (0x1D95B4, 16), (0x1D96EA, 4), (0x1D96F8, 4), (0x1D96CE, 24),
    (0x1D96D4, 16),
    # tagBattleStart@create
    (0x1D982C, 0), (0x1D9832, 0), (0x1D988A, 400), (0x1D9890, 0),
    (0x1D98E0, 374), (0x1D98E6, 256),
    # tagBattleStart@move
    (0x1D9A94, 400), (0x1D9AEC, 0), (0x1D9B14, 400), (0x1D9B22, 0),
    # tagBattleMap@create
    (0x1D9C64, 20), (0x1D9D0A, 276), (0x1D9D10, 24), (0x1D9D9A, 266),
    (0x1D9DA0, 27), (0x1D9EAE, 34), (0x1D9ED6, 34), (0x1D9EE8, 263),
    (0x1D9EF6, 121), (0x1D9F04, 258), (0x1D9F0A, 2),
    # tagBattleMap@move
    (0x1D9F9E, 141), (0x1D9FE4, 258), (0x1D9FEA, 2),
    # tagBattleMap@setPos
    (0x1DA03E, 4), (0x1DA04C, 4), (0x1DA068, 9), (0x1DA076, 34),
    (0x1DA092, 9), (0x1DA0A0, 65),
    # tagBattlePreInfo@create
    (0x1DA1A0, 1), (0x1DA1A6, 2), (0x1DA1F2, 13), (0x1DA1F8, 7),
    (0x1DA210, 1), (0x1DA224, 20), (0x1DA2C2, 1), (0x1DA2D6, 55),
    (0x1DA2DC, 142),
    # tagBattlePreInfo@set
    (0x1DA35C, 11), (0x1DA362, 37), (0x1DA3AC, 11), (0x1DA3B2, 37),
    # tagBattlePreInfo@drawInfo
    # 0x1DA7E8 (PUSH 0xff) is the numerator of "255 / fontSize" which yields
    # the per-line byte budget for splitText (FUNC 1500 doubles it again,
    # so it effectively encodes the ~255px text field width in byte units).
    # It must be doubled along with the font size.
    (0x1DA550, 24), (0x1DA658, 142), (0x1DA662, 40), (0x1DA6D2, 108),
    (0x1DA6D8, 39), (0x1DA6E4, 0), (0x1DA6EA, 0),
    (0x1DA838, 105), (0x1DA876, 31), (0x1DA7E8, 255),
    # tagBattleEnd@create: frame pos (223,211) and territory-icon
    # column base pos (267,217) x2 lists
    (0x1DACC2, 223), (0x1DACC8, 211),
    (0x1DAC96, 267), (0x1DAC9C, 217),
    (0x1DAD52, 267), (0x1DAD58, 217),
    # tagBattlePlace@change: row-advance animation distance 180 (nSize)
    (0x1C5000, 180),
    # tagBattlePlace@leave/leave2: replacement-unit slide-in distance
    # (moveSize arg 0x190 to tagBattleBusho@moveStart for the new unit).
    # The dead-unit slide-out at 0x1C4504/0x1C4802 is already doubled, so
    # the replacement starts at slot-800; without this it slides only
    # +400 and snaps +400 at the end.
    (0x1C45CA, 400),
    (0x1C4B10, 400),
    # NOTE: tagBattleUnit@moveIn/moveOut compare m_nBushoNo < 0x15 (unit-ID
    # boundary, not pixels). Must NOT be doubled or enemy units enter from left.
    # tagBattleUnit@createSp1
    (0x1DC704, 0), (0x1DC70A, 0), (0x1DC87A, 0), (0x1DC880, 0),
    # tagBattleUnit@createSp2
    (0x1DCA78, 0), (0x1DCA7E, 0), (0x1DCEAA, 0), (0x1DCEB0, 0),
    # tagBattleUnit@copySp
    (0x1DD276, 0), (0x1DD27C, 0), (0x1DD288, 0), (0x1DD28E, 0),
    (0x1DD2AC, 0), (0x1DD2B2, 0), (0x1DD308, 0), (0x1DD30E, 0),
    (0x1DD320, 0), (0x1DD352, 0),
]

# SINGLES14: 合戦本編 UI (tagBattleBar 紋章ブレンド位置 / tagBattleBusho 兵種アイコン / 行動回数旗列)
SINGLES14 = [
    # tagBattleBar@create: crest blend offsets (1,1) and (428,1)
    (0x1D7ABC, 1), (0x1D7AC2, 1), (0x1D7B22, 428), (0x1D7B28, 1),
    # tagBattleBusho@set: 兵種アイコン位置 baseW+155(mikata)/+7(teki), baseH+33
    (0x1C80A4, 155), (0x1C80B0, 7), (0x1C80D0, 33),
    # tagBattleWaza@setPos: 行動回数フラグ列 .LOCALPLUSA 65 / .LOCALMINUSA 13 (imm file offsets)
    (0x1CAE84, 65), (0x1CAEE8, 13),
]

# SINGLES15: 参加選択/斥候パネル 説明文の行ピッチ (tagSankaList@drawInfo .LOCALPLUSA nY 31)
SINGLES15 = [
    (0x1AF61E, 31), (0x1AF7FE, 31), (0x1AF8F4, 31),
]

# SINGLES16: 斥候選択画面の未パッチ座標 (tagSankaList / tagSanka)
SINGLES16 = [
    # tagSankaList@create: 決定ボタンX / スロット基準(nX,nY) / ピッチ / マップサムネ位置
    (0x1ADB64, 299), (0x1ADBB6, 13), (0x1ADBC0, 484), (0x1ADC24, 71),
    (0x1AD92C, 11), (0x1AD932, 37),
    # tagSankaList@setValue: normalizeTextY(28,24) + getTextWidth font x2
    (0x1AEF1E, 28), (0x1AEF24, 24), (0x1AF076, 24), (0x1AF122, 24),
    # tagSankaList@drawInfo type==2 (斥候説明文): nX base/width/font, nY, nX2, +nY pitch, nY3
    (0x1AF3C2, 4), (0x1AF414, 105), (0x1AF41A, 169), (0x1AF420, 24),
    (0x1AF440, 40), (0x1AF482, 274), (0x1AF4DE, 31),
    # drawInfo type==3 (スキル説明リスト): nX, nY
    (0x1AF592, 105), (0x1AF59C, 40),
    # drawInfo else (国名+マップサムネ+行): text base/width/font, nY, nX2 x3, thumb offset -32
    (0x1AF676, 142), (0x1AF67C, 118), (0x1AF682, 24), (0x1AF6A2, 40),
    (0x1AF6E4, 260), (0x1AF770, -32),
    (0x1AF7CE, 105), (0x1AF7D4, 155), (0x1AF7DA, 24), (0x1AF844, 260),
    (0x1AF8C4, 105), (0x1AF8CA, 155), (0x1AF8D0, 24), (0x1AF93A, 260),
    # tagSankaList@dragBusho: drag ghost center offset (32,36) + slot size (65,72)
    (0x1AE378, 32), (0x1AE392, 36), (0x1AE5A2, 65), (0x1AE5D6, 72),
]

# SINGLES17: 合戦本編 行動順フラグ列 (tagBattleSequence/tagBattleFlag)
SINGLES17 = [
    # tagBattleSequence@getPosX/getPosY: フラグピッチ100 / 行Y=289
    (0x1D01A0, 100), (0x1D01C0, 289),
    # tagBattleFlag@moveInStart/moveIn: 退避X=800 / 速度係数150
    (0x1D0D8C, 800), (0x1D0E86, 800), (0x1D0E9A, 150),
]

# SINGLES18: 合戦本編 兵士グループ (tagBattleUnit)
SINGLES18 = [
    # tagBattleUnit@getBlendNormal: 単数ユニットの中心座標 (410,257)
    (0x1DD3EA, 410), (0x1DD3FE, 257),
    # tagBattleUnit@getBlendAttack: 攻撃時補正 30
    (0x1DD5A2, 30),
    # tagBattleTime@create: 残りターンピップ初期位置 (379,326) と縦ピッチ 10
    (0x1D71A6, 379), (0x1D71B0, 326), (0x1D72BC, 10),
    # tagBattleTime@dec/anime: ターン消費アニメの相対移動 (-19,-6) x3箇所
    (0x1D75D4, -19), (0x1D7826, -19), (0x1D7938, -19),
    (0x1D75E8, -6), (0x1D783A, -6), (0x1D794C, -6),
]

# SINGLES19: 合戦本編 ホバーコマンド/隊列画像/結果数値/損害表示
SINGLES19 = [
    # tagBattleButton@create: ボタンアンカー 味方(+56,+5) 敵(-25,+5)
    (0x1CBF08, 56), (0x1CBF22, 5), (0x1CBF42, -25), (0x1CBF5C, 5),
    # tagBattleButton@add: ボタン縦ピッチ38 / テキスト影幅2 x4
    (0x1CC102, 38),
    (0x1CC1AC, 2), (0x1CC1C2, 2), (0x1CC1D8, 2), (0x1CC1EE, 2),
    # tagBattleButton@add: テキスト領域 味方(+10,+8,134x20) 敵(+3,+8,134x20)
    (0x1CC356, 10), (0x1CC35C, 134), (0x1CC38E, 8), (0x1CC394, 20),
    (0x1CC506, 3), (0x1CC50C, 134), (0x1CC53E, 8), (0x1CC544, 20),
    # tagBattleButton@setActionShow: 縦ピッチ38 / 名札位置 味方(+10,+8) 敵(+3,+8)
    (0x1CCA04, 38),
    (0x1CCAF0, 10), (0x1CCAFE, 8), (0x1CCB20, 3), (0x1CCB2E, 8),
    # tagBattleBusho@setKekka: 結果数値 テキスト領域(7,7,66x17)
    # / 表示位置 味方+70 敵+28 / +19 (フォント18は既パッチ済み)
    (0x1C8818, 7), (0x1C881E, 66), (0x1C8824, 18),
    (0x1C8848, 7), (0x1C884E, 17), (0x1C8854, 18),
    (0x1C88BE, 70), (0x1C88CA, 28), (0x1C88E6, 19),
    # tagBattle@showNumber/hideNumber: 損害数値の初期Yとスライド量
    (0x1C201C, 312), (0x1C2088, 34),
    (0x1C220C, 278), (0x1C2274, 34),
    # tagBattleUnit@blendUnit: 隊列CG判定 480x370->960x740 / 固定アンカー(467,322)
    (0x1DCFEC, 480), (0x1DD000, 370),
    (0x1DD02A, 467), (0x1DD034, 322),
    # tagBattleUnit@blendUnit: attack sprite anchors nW-0x10e / nH-0x10e (270),
    # mode==3 extra nX shift -267 (pixel offsets, must follow 2x CG size)
    (0x1DD07C, 270), (0x1DD096, 270), (0x1DD0D0, -267),
    # tagBattlePlace@moveIn: スライド距離400 (leave系は既パッチ済み)
    # 敵開始位置 = backupX + 400 + hosei が画面内(1280-1580)になるのを
    # +800 で画面右外に出す
    (0x1C3A80, 400),
    # tagBattlePlace@moveIn: 入場スタッガー nHosei=i*100 / RAND(100) x2箇所
    (0x1C3940, 100), (0x1C3990, 100), (0x1C39B8, 100),
    # tagBattleNumber@update: 桁ピッチ40 / 散布 0x44,0x22,0x14,0x22
    # (create canvas 40x34 is already patched in SINGLES13)
    (0x1D6644, 40),
    (0x1D65A0, 68), (0x1D65A8, 34), (0x1D65CE, 20), (0x1D65EE, 34),
    # tagBattleNumber@updateDamage: アニメオフセット 20,68 / 桁ピッチ40
    (0x1D68AA, 20), (0x1D68CC, 68), (0x1D6CFE, 40),
    # tagBattleNumber@updateHeal: アニメオフセット 68 / 桁ピッチ40
    (0x1D6D1E, 68), (0x1D7022, 40),
]

# SINGLES20: タイトル背景スクロール復元 (tagTitleBack / tagTitle@create)
# ベイク済みcg12504を半透明ヴェール原本に戻してパノラマスクロールを再表示する。
# ピクセルバッファ 800x600 -> 1600x1200, ラップ境界 1600 -> 3200 に合わせる
# (cg12501/12502 は 3200x1200 に2x化済み)。
SINGLES20 = [
    # tagTitle@create: スクロール速度 nSize (A=1, B=3 px/100ms)
    (0x1FF538, 1), (0x1FF566, 3),
    # tagTitle@create: cg12500 ロゴ setPos y=60 / 雷エフェクト setPos y=18
    (0x1FF5FE, 0x3c), (0x1FF65A, 0x12),
    # tagTitleBack@create: ピクセルバッファ 800x600
    (0x20048E, 0x320), (0x200494, 0x258),
    # tagTitleBack@moveLeft/moveRight: パノラマ幅ラップ境界 1600
    (0x200772, 0x640), (0x20078E, 0x640), (0x2008A0, 0x640),
    # tagTitleBack@copyBack: コピー幅800 / 高600 / 境界1600
    (0x20092C, 0x320), (0x200936, 0x258),
    (0x200942, 0x320), (0x20094A, 0x640), (0x20099C, 0x640),
]

# PRE2_PATCH: 指定CALLMETHODの直前2個のPUSH即値を2倍化する
# (範囲lo..hi内で命令バイト列patを検索し、直前の PUSH A PUSH B を2倍化)
PRE2_PATCH = [
    # tagUnitDataManager@0: 兵士フォーメーション座標テーブル
    # tagUnitData@setPos(nIndex,nNo,nPlace,nRight,nBottom) の nRight/nBottom
    # 関数範囲 0x1E31D6..0x1E52E0 (disasm) -> file +0x18
    (0x1E31EE, 0x1E52F8, bytes([0x5C, 0x00, 0x2D, 0x0E, 0x00, 0x00])),
]

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

