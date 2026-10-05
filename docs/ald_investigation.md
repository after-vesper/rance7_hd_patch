# .ald 展開検証レポート (Phase 2 タスク 1)

調査日: 2026-10-05
対象: Game_Sample/Rance7{BA,GA,GM,WA}.ald

## 結論サマリ

- **展開**: 成功。フォーマットが単純なため自前パーサ (Python, 約40行) で
  全エントリの列挙・展開を検証済み。GARbro / arc_unpacker / alice-tools
  (`alice ar`) でも対応実績あり
- **内包形式**: CG は `QNT` (AliceSoft 独自画像), 一部 `AJP`, 音声は `OGG`。
  QNT は独自デコーダで PNG まで復元できることを確認済み
- **再パック/差分**: System4 の ALDLoader は複数 .ald を列挙して読み込む
  (下記)。`alice ar pack` (alice-tools) で ALD 新規作成が可能なため、
  **元ファイルを触らない差分アーカイブ方式が最有力**

## ALD フォーマット (実測 + GARbro ArcALD.cs と一致)

```
[先頭] 3バイトLE のブロックオフセット表 (先頭3バイトは表自体の長さ/256)
       各エントリ = ファイル先頭オフセット >> 8 (256バイト単位)
[各ファイル] u32 header_size / u32 data_size / ヘッダ残り + ファイル名(CP932)
             / データ本体 (256バイト境界に配置)
[末尾16バイト] マジック "NL\x01\x00" (= u32 0x00014C4E、または 0x00012020)
               u32 0x10 / オフセット+9 の u16 がファイル数 / 残りは0パディング
```

### Game_Sample 内各アーカイブの内容物

| ファイル | サイズ | エントリ数 | 内容 |
|---|---|---|---|
| Rance7BA.ald | 52 MB | 44 | OGG のみ (BGM) |
| Rance7GM.ald | 756 MB | 6512 | QNT 6351 + AJP 161 (CG 本体) |
| Rance7GA.ald | 1.5 MB | 100 | QNT のみ (cg04501- 系) |
| Rance7WA.ald | 4.8 MB | 194 | OGG のみ (効果音/ボイス) |

※ `Rance7BA.bgi` / `Rance7WA.wai` はアーカイブとは別の索引ファイルと思われる
(内容は難読化されている。更新が必要かは別途調査)

## QNT フォーマット (ver 2, 検証済み)

```
u32 'QNT\0' / u32 version(2) / u32 header_size(=0x44)
u32 x, y (描画オフセット) / u32 w, h / u32 bpp
u32 ? / u32 rgb_zlib_size / u32 alpha_zlib_size / (残りヘッダ)
[header_size〜] zlib圧縮 RGB ストリーム → 続いて zlib圧縮アルファストリーム
```

デコード手順 (GARbro ImageQNT.cs 準拠、Python で再現確認済み):

1. RGB ストリームを zlib 展開 (サイズ = 偶数補正後 w*h*3)
2. **チャンネル分離 + 2行インターリーブ**で展開:
   チャンネル(B,G,R)ごとに、(行ペア, 各x) 順に「上行画素, 下行画素」が連続格納
3. アルファは別ストリーム (w*h、行ごとに奇数幅パディング)
4. **差分復号** (出力バッファ上で):
   - 先頭行: 右から `out[i] = out[i-bpp] - out[i]`
   - 2行目以降: 各画素 `out = ((上 + 左) >> 1) - out` (先頭画素のみ `上 - out`)

検証結果: cg04501.QNT (800x600, bpp=24+alpha) を PNG 化して正常な
立ち絵画像が得られた (アルファチャンネル含む)。

## 差分アーカイブ方式の根拠 (ALDLoader.dll 逆アセンブル)

DLL/ALDLoader.dll 内のファイル名パターン:

```
%sB%c.ALD  %sR%c.ALD  %sD%c.ALD  %sW%c.ALD  %sG%c.ALD
%cBGM.ALD  %cRES.ALD  %cDATA.ALD %cWAVE.ALD %cCG.ALD
```

- `%s` = ゲーム名 (Rance7), カテゴリ文字 (B=BGM, W=WAVE, G=CG?), `%c` = 'A'+i
- 実コードで `FindFirstFile("ACG.ALD")` 後、サフィックスを 'A','B','C'… と
  インクリメントしながら各 `{Game}{Cat}{Letter}.ald` の存在を列挙している
- → `Rance7GZ.ald` のような新規サフィックスで追加 .ald を置くだけで
  ゲームが読み込む可能性が高い (公式パッチも同仕組みのはず)
- **同名ファイルの優先順位 (後勝ち/先勝ち) は未確認 → 実機検証が必要**

## 今後のアクション

1. (優先) `alice ar pack` で試作 .ald を作成し、後勝ちか先勝ちかを
   実機で確認する (例: 1ファイルだけ差し替えた Rance7GZ.ald)
2. AJP 形式の仕様確認 (GARbro/alice-tools にデコーダあり)
3. QNT エンコーダ (PNG → QNT) の実装 — 差分アーカイブに入れるために必須。
   alice-tools に変換機能があるか確認、なければデコーダを逆向き実装
4. Rance7BA.bgi / Rance7WA.wai が追加 .ald に影響するか調査
5. アップスケーラ選定 (Real-ESRGAN ncnn-vulkan) と QNT への往復変換確認

## ツール候補の評価メモ

| ツール | ALD 読み | ALD 書き | QNT | 備考 |
|---|---|---|---|---|
| alice-tools (`alice ar/ex`) | ○ | ○ (ar pack) | ○ | 本命。Windows ビルド要確認 |
| GARbro | ○ | × | ○ (読みのみ) | GUI 検証用 |
| arc_unpacker | ○ | × | ○ | 同上 |
| 自前 (Python) | ○ 検証済 | 実装容易 | ○ 検証済 | パイプライン組込み向け |
