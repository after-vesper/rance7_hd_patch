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

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
