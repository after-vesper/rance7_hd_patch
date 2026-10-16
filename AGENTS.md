# AGENTS.md — Sengoku Rance AIN Patch Development

This repository develops an unofficial feature patch for Sengoku Rance (Steam version).
The patch modifies `Rance7.ain` (System4 bytecode). The game executable is never modified.

> How to use this file: it is the primary context document for the AI agent (Devin).
> Keep it up to date as the project evolves. Place it at the repository root.

## 1. Environment Setup (required before any work)

### 1.0 Git initialization (first-time setup only)

If the repository is not yet a git repo, initialize it and set the LOCAL
identity (do not touch global config):

```powershell
git init
git config user.name "after-vesper"
git config user.email "aftervesper682@gmail.com"
```

Verify with `git config user.name` → `after-vesper` and `git config user.email`
→ `aftervesper682@gmail.com`.

### 1.1 alice-tools — download automatically

On project setup (or whenever `tools/alice.exe` is missing), download the
official release and place `alice.exe` in `tools/`:

```powershell
mkdir -Force tools
curl -L -o tools\alice-tools.zip https://github.com/nunuhara/alice-tools/releases/download/0.13.0/alice-tools-0.13.0.zip
Expand-Archive -Force tools\alice-tools.zip tools\alice-tools-tmp
# locate alice.exe inside the archive and copy it:
Get-ChildItem tools\alice-tools-tmp -Recurse -Filter alice.exe |
  Copy-Item -Destination tools\alice.exe
Remove-Item -Recurse -Force tools\alice-tools-tmp, tools\alice-tools.zip
.\tools\alice.exe --version   # must print "alice-tools version 0.13.0"
```

Upstream: https://github.com/nunuhara/alice-tools — release page:
https://github.com/nunuhara/alice-tools/releases/tag/0.13.0

alice-tools is GPL-licensed. If the repository ships binaries, also ship the
source offer (zip / license texts) for compliance; prefer downloading instead.

### 1.2 Game data — must be supplied by the user

The repository keeps a runnable copy of the game under `game/` so the patch
can be applied and tested in place. Ask the user to copy the entire game
install directory there (`Rance7.exe`, `Rance7.ain`, `System40.ini`,
`SaveData/`, all resource folders).

Game files are copyrighted and must NOT be committed or downloaded — `game/`
is gitignored.

| Required file | Where it comes from |
|---|---|
| `game/Rance7.ain` | Inside `game/` (copied from the game install) |
| `tools/alice.exe` | Auto-downloaded per 1.1 |
| `tools/xdelta3decode.exe` | Only needed if producing xdelta releases |

Recommended layout:

```
repo/
  AGENTS.md            <- this file
  game/                <- full game install (gitignored; test target)
    Rance7.ain         <- the file we patch
    Rance7.exe
    System40.ini
    SaveData/
    ...
  tools/alice.exe
  dump/                <- generated disassembly (gitignored)
    Rance7.jam         <- full code disassembly
    Rance7.txt         <- strings/messages
    functions.txt      <- function signatures
    globals.txt        <- global variables
    structs.txt        <- structure definitions
  src/
    <feature>.jaf      <- feature code (JAF language)
  hooks.jam            <- generated hook fragments
  build.ps1            <- build script (dump -> verify -> inject -> rebuild)
```

IMPORTANT: never commit `game/`, `dump/`, or any extracted game text/art.
They are copyrighted game data. Only commit `.jaf` sources, hook scripts, and
signature JSON files you generated.

## 2. Generate the dumps (first command to run)

```powershell
mkdir dump
.\tools\alice.exe ain dump -c -o dump\Rance7.jam  game\Rance7.ain   # code (~1.1M lines)
.\tools\alice.exe ain dump -t -o dump\Rance7.txt  game\Rance7.ain   # strings/messages
.\tools\alice.exe ain dump -f -o dump\functions.txt game\Rance7.ain # function table
.\tools\alice.exe ain dump -g -o dump\globals.txt   game\Rance7.ain # globals
.\tools\alice.exe ain dump -S -o dump\structs.txt   game\Rance7.ain # structs
```

Expected `game\Rance7.ain` SHA256 for the unmodified Steam release:
`7CB8B11941A140077B99877F030E84427DECC2B40825092404B81912C83ABBBC`
Verify with: `powershell -Command "(Get-FileHash game\Rance7.ain).Hash"`

## 3. JAM format (disassembly)

`dump/Rance7.jam` contains one block per function:

```
; FUNCTION_NAME
; ARG  0: argName : lint
; VAR  1: localVar : int
; RETURN: lint
FUNC 1234
	PUSHLOCALPAGE
	PUSH 1
	SH_LOCALREF localVar
	SH_GLOBALREF ＧＦ
	...
	CALLFUNC 別の関数
	IFZ 0x0012ab
0x0012ab:
	RETURN
ENDFUNC FUNCTION_NAME
```

- Instructions are tab-indented; `0x........:` are jump labels.
- `SH_LOCALREF`/`SH_GLOBALREF`/`SH_LOCALASSIGN` resolve variable names.
- `S_PUSH "..."` pushes a string; `MSG '...'` displays dialogue.
- `CALLFUNC name` / `CALLSYS lib.func` / `CALLMETHOD type@method` are calls.
- `EOF <file>` markers delimit original source files.

## 4. JAF language (feature code)

C-based language compiled into ain bytecode via `alice ain edit --jaf`.
Full grammar reference: `alice-tools-source.zip -> src/core/jaf/jaf_parser.y`.

```c
// New function (use a unique prefix, e.g. CodexXxx, to avoid collisions)
bool MyFeatureEnabled()
{
    return ◆予備０１ == 1 && ＧＦ[181] == 1;   // existing globals, directly usable
}

// Override an existing function; super() calls the original
override int 合戦_攻撃_複数(int a, int b, ref array<int> arr)
{
    MyHook();
    return super(a, b, arr);
}
```

Key points:

- Encoding is UTF-8; Japanese identifiers work (`選択肢(...)`, `ＧＦ[]`, `◆ターン`).
- Types: `void bool int char lint float string`, `ref T`, `array<T>`/`array@T@N`,
  `wrap<T>`, `option<T>`, `intp floatp`, `hll_*`, `imain_system`,
  `struct/class/interface/enum/functype/delegate`.
- All C operators + `===`/`!==` (ref compare), `<-` (ref rebind), `assert(x)`,
  `new T(...)`, `this`, `super()`, `Option::Some/None`, `true/false`, `NULL`.
- Message statement `'text';` emits a dialogue MSG instruction.
- NOT supported: compound initializers `{1,2,3}`, generics, `__FUNC__`.
- Any global, function, struct or HLL method present in the ain can be called
  by name — resolve names from `dump/globals.txt`, `dump/functions.txt`,
  `dump/structs.txt`, or the `.jam` code itself.

## 5. Feature implementation workflow

For every "implement feature X" request, follow this exact sequence:

### 5.1 Locate hook points
Search `dump/Rance7.jam` for the relevant function by name or by a nearby
`S_PUSH`/`MSG` string. Identify:
- the `FUNC` block and its `; ARG`/`; VAR`/`; RETURN` header,
- the instruction(s) where the hook must run,
- which locals/globals are in scope at that point.

### 5.2 Choose state storage
- Per-save flags: unused slots of `ＧＦ[]` (array<lint>, saved per game).
  Track used slots in this file under "Allocated GF slots".
- Global (cross-save) state: dedicated functions in the ain handle persistence;
  prefer per-save slots unless the feature must persist across playthroughs.
- Never renumber or repurpose slots already used by the game or prior patches.

### 5.3 Write `src/<feature>.jaf`
- New functions: `<Prefix><Name>(...)`. Keep one feature per file.
- To *replace* behavior: `override` the function and call `super(...)`.
  WARNING: `override` only works when the target is called via `CALLFUNC`
  (index bound at compile time). Functions invoked by name at runtime —
  `CALLONJUMP`/`SJUMP` (e.g. `全国版ＴＯＰ`) — resolve to the LAST duplicate
  in the function table, which is the original, so the override never runs.
  For those, always use a `CALLFUNC` hook injected via `hooks.jam` instead.
  Check the call site in the `.jam` dump before choosing.
- Reuse existing UI primitives found in the dump (`選択肢`, `通知`, `RAND(n)`, ...).

### 5.4 Inject hooks into existing functions
A function added via `--jaf` is dead code until called. Edit the target
function's body text and emit a `hooks.jam` fragment:

```
FUNC <original func number>
    <original instructions>
    CALLFUNC <Prefix><Hook>       <- inserted
    <original instructions>
ENDFUNC <original name>
```

Rules:
- Insert `CALLFUNC` (with any needed argument pushes) at the chosen point.
- Make it idempotent: skip injection if `CALLFUNC <Prefix>` already present.
- For early-return hooks, insert after `FUNC n`:
  `<arg pushes> CALLFUNC X  IFZ label  <early return>  label:`

### 5.5 Build and verify

```powershell
# 1. compile the .jaf into the ain
.\tools\alice.exe ain edit --jaf src\feature.jaf -o build\step1.ain game\Rance7.ain
# 2. inject hooks via jam
.\tools\alice.exe ain edit --jam hooks.jam -o build\final.ain build\step1.ain
# 3. verify: dump the result and confirm the hook is present and valid
.\tools\alice.exe ain dump --function <hookedFunc> -o check.jam build\final.ain
# 4. install into the test game (after backup, see section 6)
Copy-Item build\final.ain game\Rance7.ain -Force
# 5. launch game\Rance7.exe and verify the feature in-game
```

Always build to a NEW file, never overwrite the source ain in place.
`game/` is the live test install — the patched game can be launched directly
for verification.

## 6. Safety rules (non-negotiable)

- Never modify `game\Rance7.ain` in place; write to a temp file, verify, then swap.
- Before applying, back up `game/Rance7.ain`, `game/System40.ini`, and
  `game/SaveData/` into `backup/<patch>_<timestamp>/`.
- Close the game before writing: check `Get-Process -Name Rance7` and refuse
  to overwrite while it is running.
- Refuse to build when required functions are missing or structurally different
  from expectations (compare normalized instruction sequences, masking
  `S_PUSH`/`MSG` text operands and label addresses).
- Never commit game data (ain, dumps, extracted strings) to the repository.

## 7. Allocated resources (keep updated)

| Resource | Used by | Range |
|---|---|---|
| `ＧＦ[181..239]` | NationalExpansion patch (reference implementation) | occupied |

Note: `ＧＦ` is allocated as a flat array of 1000 lints by init FUNC 6711
(`PUSHGLOBALPAGE PUSH 78 PUSH 1000 PUSH 1 A_ALLOC`). Vanilla uses indices up
to ~177, so slots outside 0..239 are safest for new patches. Record each
patch's own allocations in its source file's header comment rather than
here, so this file stays project-agnostic.

Add new entries here whenever a patch allocates global-array slots, flag bits,
or function-name prefixes.

## 8. Reference implementation

`Sengoku_Rance_NationalExpansion_v1.4.4` (the patch this repo is modeled on):

- `patcher/batch_attack.jaf` — batch-attack feature; examples of `override` on
  battle functions and `ref array<int>` parameters.
- `patcher/expansion.jaf` — 1522 lines: settings menu, flags in `ＧＦ[]`,
  save-blocking guards, post-battle hooks, custom badge UI via `tagSprite`.
- `Universal.ps1` — the reference build pipeline: dump → signature-verify →
  `ain edit --jaf` → regex hook injection → `ain edit --jam` → hash-verify.
- Hook points it uses (all exist in stock Steam ain): `全国版ＴＯＰ`,
  `味方勢力ターン`, `合戦メイン`, `全国アルゴリズム`, `敵ＦＰ登録`, `ＩＶ合戦後`,
  `全国クリアイベント`, `ゲーム進行情報`, `館＿メイン`, save/load functions.

## 9. Community resources

- alice-tools (the compiler used here): https://github.com/nunuhara/alice-tools
- Sengoku Rance modding wiki (Japanese): https://wikiwiki.jp/rance-mod/戦国ランス
  - `MOD作成/基本` — file roles, AinDecompiler walkthroughs, ASM decompile workflow
  - `MOD作成/jaf一覧` — catalog of the game's original `.jaf` sources and what
    each function does (map setup, damage calc, prisoner handling, ...)
  - `MOD導入` — how compiled `.jaf` patches are installed

### Notes from the wiki that matter here

- **System4 resolves duplicate function names by using the LAST one in the
  ain.** Quick Compile / `ain edit` append patched functions rather than
  rewriting in place — this is why `override` works. Repeated compiles bloat
  the file; the wiki describes regenerating a clean `main.jam` to shrink it.
- Original functions carry their source filename in `EOF`/`;` markers
  (e.g. `シナリオ\Ｍ／プロローグ.JAF`). Vanilla functions appear under
  source folders like `多田\`; patch-appended functions show a `.jaf` filename.
- **AinDecompiler** (GUI alternative by SomeLoliCatgirl) can open ain files,
  decompile to `.jaf` (`File > Decompile code`: vanilla sources end up in
  per-source folders, mod code in `remaining.jaf`), and quick-compile `.jaf`
  patches. Useful to visually confirm a hook point or inspect a modded ain.

## 10. デバッグ環境 (xsystem4)

`game/xsystem4/` に xsystem4 1.0.0 を配置済み
(https://github.com/nunuhara/xsystem4/releases/tag/1.0.0)。
System4 の互換エンジンで、本家 `Rance7.exe` の代わりに
`xsystem4.exe` からゲームを起動すると実行中の ain VM を観察できる。
本リポジトリの暗号化済み ain でも起動確認済み (メイン関数到達)。

### 起動方法

```powershell
game\xsystem4\xsystem4.exe        # 通常起動 (xsystem4エンジンでゲームを実行)
game\xsystem4\xsystem4-debug.exe  # デバッガ付き起動 (REPL が開く)
# または同梱の "Start in debugger.lnk" ショートカット
```

exe は `xsystem4/` サブフォルダから実行し、親ディレクトリの
ゲームデータ (`Rance7.ain`, `System40.ini`, ald 各種) を読む。

### デバッガの基本コマンド

デバッガ付き起動では実行が止まった状態で `dbg(cmd)>` が出る。

| コマンド | 意味 |
|---|---|
| `c` | 実行再開 (continue) |
| `bt` | バックトレース (呼び出し中の関数名一覧) |
| `l <n>` | `bt` の n 番目フレームのローカル変数を表示 |
| `p <name>` | グローバル変数を表示 (全角名の入力に注意) |
| `m` | クラスメンバ変数の表示 |
| `bp` | ブレークポイント設定 |
| `help` | コマンド一覧 |

ゲーム実行中にマウス中ボタン (ホイール) をクリックすると
実行を中断してデバッガに入れる。`c` で復帰。

### 調査での使い方

- 描画・位置関係の問題 (HD化の残課題) を調べるとき、
  対象シーンで実行を止め `bt` で関数呼び出しを確認し、
  `l` で座標やフラグの実値を読むと .jam 静的解析だけより速い。
- `bp` で特定関数にブレークを張り、引数の値を確認する用途にも使える。

### 注意点

- セーブデータは `~/.xsystem4/Sengoku Rance/SaveData/` 配下に
  別保存される (本家セーブと互換性なし・本家を壊すこともない)。
- xsystem4 はエンジン再実装なので描画結果が本家と完全一致するとは
  限らない。表示検証は最終的に `Rance7.exe` 実機で行うこと。
- `xsystem4-debug.exe` は別プロセス名。タスクキル時は
  `xsystem4*.exe` を対象にする。
- その他: F11 フルスクリーン切替、Alt+S スクリーンショット。

## 11. スクリーンショット取得手順 (実機検証用)

4K/150% DPI 環境で `Rance7.exe` の**ウィンドウ全体**を撮るには
`tools/cap.ps1` を使う:

```powershell
powershell -File tools/cap.ps1 work/shot.png                    # 撮るだけ
powershell -File tools/cap.ps1 work/shot.png -Keys "down,down,enter"  # キー送信後に撮影
```

ポイント:

- **プロセスを PerMonitorV2 にする** (`SetProcessDpiAwarenessContext(-4)`)
  してから `GetWindowRect` を取ること。DPI非対応のままだと
  座標・サイズが1.5倍ずれて正しく撮れない。
- キャプチャは `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT=2)`。
  BitBlt/CopyFromScreen だとクライアント領域しか取れない・
  縮小前の古いフレームが取れることがあるので使わない。
- 期待サイズは **1606x1270** 程度 (1600x1200クライアント +
  タイトルバー/枠)。これより小さい場合は失敗している。
- キー送信は `keybd_event` (SendKeys はフォーカスが無いと届かない)。
  送信前に `SetForegroundWindow` でフォーカスを取ること。
  マウスは `ClientToScreen` + `SetCursorPos` + `mouse_event` で
  クライアント座標指定クリックが可能。
- タイトルメニューの選択肢はキーボード操作が確実:
  フォーカス直後は未選択 → ↓1回目で「はじめから」、
  ↓2回目で「つづきから」、↓3回目で「アリスの館」。
  ロード画面確認は「つづきから」(↓×2 + Enter) で即到達できる。

## 12. Feature request template

When asking the AI to implement a feature, provide:

```
Feature name:
Trigger:          (when/where it should run — e.g. "after winning a normal battle")
Behavior:         (what it does)
Config:           (ON/OFF setting? default? per-save?)
Persistence:      (per-save flags needed? global?)
Affected funcs:   (if known — otherwise AI searches the dump)
Compatibility:    (must work on saves created before the patch?)
```

## 作業メモ（HD化パッチ開発）

### ALDリパックの注意
- `hdpatch.repack_ald` は「基底ALD + pngdir内のPNG」で再構築する。
  **必ず直前の変換済みALD（例: `rance7_window_size_patch/patch_staging/Rance7GM.ald`）を基底にすること**。
  `.orig`を基底にすると過去の2x変換が全て巻き戻る。
- pngdir に `manifest.json` が無いとアルファが ch3 に落ちて透過/マスクが壊れる。
  manifest は各QNTの `asz>0` を `bpp:32` として生成する（QNTヘッダのbppフィールドは24のままのことがある）。
- キャプチャ: `tools/cap.ps1 <out.png>`（DPI考慮済み）。キー送信 `-Keys "down,down,enter"`。
- **画面は150%スケーリング**: キャプチャ画像(1606×1270)はクライアント(1066×800)の1.5倍。
  画像座標÷1.5がクライアント座標。マウス操作は必ずクライアント座標で行うこと。
- LOAD→マップ遷移: タイトルで↓×2+Enter→ロード画面、セーブ行(1010,225)→LOAD窓(250,325)へドラッグ、ダイアログ「はい」(783,638)。

### アセット2x化の二重適用防止（重要）
- **一度2x化したCGを二度と2x化しない**こと。過去に抽出元として
  「既に2x化済みの live ALD」を使ったため 4x 化する事故が起きた（cg10282-89,
  cg10501-10560 等42件。2025-10-11修復済み）。
- 抽出は**必ず原本 `game/Rance7GM.ald.orig`** から行うこと。live の
  `game/Rance7GM.ald` から extract→upscale→apply すると既存2x資産が4x化する。
- 2x化済み資産の一覧は `work/upscaled.json`（gitignore対象・ローカル管理）。
  バッチ適用前に必ず照合し、掛かる場合はリストから除外する。
- 監査: `python tools/hd_audit.py game/Rance7GM.ald game/Rance7GM.ald.orig
  work/upscaled.json --write-manifest` で 4x/other を検出しマニフェストを再生成できる。
- `Rance7GM.ald` 以外の ALD (BA/GA/WA) には原本バックアップが無いため監査不可。
  これらを弄る場合は先に `*.ald.orig` バックアップを作ること。

### AIN互換適用（アンカー型パッチャ）

固定オフセット型 `tools/ain_*_patch*.py` は **JP適用済み ain（SHA256 `7CB8B119...`）専用**。
他バリアント（vanilla `B4459F06`、NE適用済み等）には使わないこと。

バリアント非依存の適用はアンカー方式:

```powershell
# サイト表の再生成（jp原版 -> game/Rance7.ain 差分から）
python tools/ain_export_sites.py            # -> tools/hd_sites.json
# 任意バリアントへの適用（dry-run 推奨）
python tools/apply_hd_ain.py <in.ain> <out.ain> --dry-run
python tools/apply_hd_ain.py <in.ain> <out.ain>
# 英語版（Kagura）は専用サイト表を指定すること（省略時は jp 表が使われる）
python tools/en_export_sites.py work/lang/en/Rance7.ain \
    --out installer/data/hd_sites_en.json
python tools/apply_hd_ain.py work/lang/en/Rance7.ain <out.ain> \
    --sites=installer/data/hd_sites_en.json
```

- サイト特定は「関数名 + 命令文脈（±3命令、S_PUSH/JUMP/CALL系オペランドはマスク）」。
- 同名関数の複製（override）は全コピーに適用。
- 他Modが本体を書き換えた関数では operand 値一致の relaxed fallback が走る（結果は要レビュー）。
- 検証済みバリアント: jp(完全一致) / vanilla(2006解決, JP専用9関数は正しくskip) /
  ne(2024) / jp_ne(2033)。HD→NE順も NE Universal.ps1 が素通しで成功し、
  NEのoverrideコピーがHD値を継承する。
- JPパッチは ain 差し替え型（vanilla->7CB8B119, R18シーン関数追加）。
  GM.ald のエントリ名は vanilla/jp で同一（中身のみ差し替え）。

### インストーラー構成（installer/）
- ランタイム/バイナリは `ci/provision_runtime.ps1` が取得する
  （embedded Python → `installer/runtime/`、alice.exe・ffmpeg.exe →
  `installer/bin/`）。両ディレクトリは gitignore 対象。
- `installer/bin/ffmpeg.exe` は imageio-ffmpeg 0.5.1 同梱の静的ビルド
  （ffmpeg 4.2.2）。ムービーHD化のみに使用。mpeg1video/mp2/vcd muxer
  必須 — 別バージョンに差し替える場合は `-encoders`/`-muxers` で確認。
- ムービーHD化は `installer/gen/gen_movie.py` がバックアップ済み原版
  （`backup\hd_*\movie\`）からインストール時生成する。manifest には
  載せない（optional 扱いのため）。詳細は docs/movie_upscale.md。
