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
    for off, expected in SINGLES5:
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
]

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
