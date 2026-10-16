# 戦国ランス HD アセットパッチ 実装仕様 (Phase 2)

> 本ファイルは git 管理外(.git/info/exclude)。新セッション開始時の引き継ぎ資料。

## プロジェクト概要

Steam 版 戦国ランス (Rance7.exe, 日本語版, System4.0 Ver1.31, appid 3867170) の
アセットを高解像度化するパッチ。Phase 1 (ウィンドウサイズ変更パッチ) が前提。

- Phase 1 リポジトリ: `C:\Users\akihiro\projects\rance7_window_size_patch`
  (GitHub: after-vesper/rance7_window_size_patch)
- 本リポジトリ: `rance7_hd_patch` (GitHub: after-vesper/rance7_hd_patch, private)
- Phase 2 のインストールは Phase 1 導入済みを前提とする

## 著作権方針 (重要)

アップスケール済みアセットの**配布はしない**。代わりに、ユーザーの手元の
ゲームデータをローカルで変換するツールを配布する:

```
ゲームフォルダを指定
  → .ald から画像展開
  → アップスケール (Real-ESRGAN / waifu2x 系, CPU or NCNN Vulkan)
  → 再パック or 差分アーカイブ配置
  → 元ファイルはバックアップ
```

配布物はツール本体 + OSS モデル重みのみ。ゲーム素材は一切含まない。

## 技術的前提 (Phase 1 判明分)

- ゲーム内部描画は 800x600 (4:3) 固定、GDI BitBlt 経由
- Phase 1 がクライアントサイズへスケーリング表示 + マウス座標逆変換済み
- 素材を 2x 化してもゲームの座標系は 800x600 のまま → 表示崩れしないよう
  「素材のピクセル密度を上げ、ゲームには同寸法として認識させる」方向が現実的
- 描画座標系そのものの引き上げは Phase 1 側の追加対応が必要 (難度高)

## 既知ツール候補

- .ald 展開: GARbro, arc_unpacker など既存ツールが対応実績あり (要検証)
- .ald 作成(再パック): ツールの作成対応を確認。または System40 の
  パッチ用差分アーカイブ機構の有無を調査
- アップスケール: Real-ESRGAN / waifu2x (ncnn-vulkan 版推奨、モデルは OSS)

## 最初のタスク

1. Game_Sample 内の .ald (Rance7BA.ald 等) を既存ツールまたは自前解析で
   展開できるか検証する
2. 展開した画像形式 (.bgi? .alk? 内包形式) を特定する
3. 再パック or 差分アーカイブ方式の可否を調査する

## リポジトリ運用

- AGENTS.md のルールに従う (Conventional Commits / 日本語コメント・ドキュメント /
  作業ブランチ運用 / マージはユーザー許可制)
- Game_Sample, Patch_Sample, AGENTS.md, docs/implementation_spec.md は
  .git/info/exclude で管理外
- .gitignore: *.exe *.dll *.ald *.ain *.obj *.lib dist/ 等を除外


## AIN patch rule: z-order immediates must never be doubled

`z` arguments to `tagSprite@setZ`, `tagDrawText@setZ`, and `*@create(...,nZ,...)`
are layer sort keys, not pixel coordinates. Doubling only some of them flips
ordering vs. unpatched z values (e.g. `tagButtonGroup` z stays at 202 while a
panel z goes 201->402, hiding the button sprites behind a baked panel image -
this made the prisoner-screen recruit button always look enabled).

`tools/ain_zfix.py` restores the 40 wrongly-doubled z immediates in-place, and
the corresponding tuples have been removed from the `ain_adv_patch*.py` tables.
