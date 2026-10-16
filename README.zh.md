# 战国兰斯 HD 补丁

[日本語版 README](README.md) / [English README](README.en.md)

将 Steam 版 **战国兰斯 (Sengoku Rance / Rance 7)** 的画面从固定的 800×600 提升到 **1600×1200** 高清分辨率的补丁。不仅将绘制坐标与布局放大两倍，游戏内的图像素材也会通过 AI 超分辨率进行高清化。

> **⚠️ 本补丁为非官方的同人作品，与 AliceSoft 及发行商没有任何关系。**
> **使用本补丁的一切后果请自行承担。因安装导致的任何损害或故障，作者概不负责。**

## 功能

- **逻辑分辨率 1600×1200** — 将 `Rance7.ain` 中的坐标与布局常量全面放大两倍（不修改任何可执行文件）
- **图像素材高清化** — 约 6,600 张 CG、立绘、UI、战斗画面、地图等图像通过 AI 超分辨率放大两倍后重新打包
- **启动 Logo 也高清化** — 使 `AliceLogo*.alk` 的 Logo 动画与 `DLL\AliceLogo*.dll` 支持高分辨率（简体中文版：AliceLogo2）
- **OP/ED 影片高清化** — 将 `movie\` 内的影片用 AI 放大两倍后重新编码（640×480 → 1280×960）
- **安装时生成** — HD 素材从您自己的游戏数据现场生成，补丁包本体仅约 120 MB
- **自动识别版本** — 自动判别游戏状态（简体中文版会自动切换为中文界面）
- **安全设计** — 修改前自动创建带时间戳的备份；失败时保留原始文件

## 运行环境

- **Steam 版 战国兰斯**（简体中文版可直接安装）
- **推荐 DirectML 兼容 GPU** — 没有也能运行，但首次素材生成会花费较长时间
- **约 9 GB 可用空间** — 用于生成过程中的工作目录与备份（完成后工作目录自动删除）

## 安装

1. 从[发布页面](https://github.com/after-vesper/rance7_hd_patch/releases/latest)下载 `SengokuRance_HDPatch.zip` 并解压到任意位置
2. 关闭游戏后，双击解压文件夹中的 `Install.cmd` — 会自动检测 Steam 游戏目录
3. 如果游戏文件夹位于 `Program Files` 下，会弹出管理员权限（UAC）确认
4. 开始用 AI 生成 HD 素材与 OP/ED 影片
5. 显示「HD补丁安装完成」即安装成功

> **安装时间参考**：在 Ryzen 9 5900X / GeForce RTX 3070 Ti / 32 GB 内存的环境下，首次安装（生成约 6,600 张素材 + 2 部影片）约需 **9 分钟**。实际时间取决于 GPU 性能和影片数量。

如果不是通过 Steam 安装的，会提示输入游戏路径。也可以用 PowerShell 的 `-GameDir` 参数直接指定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File Install.ps1 -GameDir "D:\Games\SengokuRance"
```

> 游戏运行时无法安装，请先退出游戏。

### 被修改的文件

- `Rance7.ain` — 坐标与布局常量放大两倍
- `Rance7GA.ald` / `Rance7GB.ald` — 简体中文版的高清化对象（`Rance7GM.ald` 不会被修改）
- `AliceLogo*.alk` / `DLL\AliceLogo*.dll` — 启动 Logo 动画高清化（存在时）
- `movie\*.alm` — OP/ED 影片高清化（存在的全部影片）
- `System40.ini` — 将 `ViewWidth` / `ViewHeight` 设为 1600×1200

以上文件在修改前都会先保存到 `backup\hd_<日期时间>\`。
此外还会创建生成素材缓存文件夹 `hd_cache`（详见下文）。

## 卸载

双击 `Uninstall.cmd`，选择要恢复的备份（默认为最新）。

会从最新备份中恢复 `Rance7.ain`、`System40.ini`、`Rance7*.ald`、启动 Logo 相关文件与影片。不会影响存档数据。
全部恢复验证成功后，已使用的备份文件夹会自动删除（其他备份会保留）。
最后会询问是否删除 `hd_cache`（生成素材缓存，约 3.5 GB）。保留的话下次安装可跳过 AI 生成步骤。

## 关于缓存

`hd_cache` 是在游戏文件夹内创建的已生成素材与影片缓存（约 3.5 GB）。

- 重新安装或版本升级时跳过 AI 生成步骤，大幅加快安装速度
- Steam 重装游戏（同一路径）后仍可继续使用
- 当模型或素材来源变化时会自动失效，不会混入旧的生成物

## 版本升级

1. 先用 `Uninstall.cmd` 还原当前补丁（`hd_cache` 可以保留）
2. 再运行新版本的 `Install.cmd`

## 注意事项

- **对象为 Steam 版**（简体中文版已确认可用）
- GPU 不支持 DirectML 时，首次生成将使用 CPU 运行，耗时较长
- 安装程序不会修改游戏可执行文件（`Rance7.exe`）
- 杀毒软件可能误报脚本或附带工具，如遇此情况请加入排除列表
- **本补丁的一切使用后果请自行承担。** 对安装导致的问题（存档损坏、游戏故障等）作者概不负责。建议安装前备份存档

## 许可

- 超分辨率模型 AnimeJaNai HD v3 Sharp1 UltraCompact 采用 **CC BY-NC-SA 4.0** 许可 — 详见 [installer/LICENSES/model.txt](installer/LICENSES/model.txt)
- alice-tools（附带二进制文件）为 GPL 许可 — 详见 [installer/LICENSES/alice-tools.txt](installer/LICENSES/alice-tools.txt)
- ffmpeg（附带二进制文件，仅用于影片高清化）为 GPL 许可 — 详见 [installer/LICENSES/ffmpeg.txt](installer/LICENSES/ffmpeg.txt)
