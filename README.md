# Nightreign Overlay Helper Plus

黑夜君临悬浮助手：非官方自动增强版。

**本项目基于 [NeuraXmy/nightreign-overlay-helper](https://github.com/NeuraXmy/nightreign-overlay-helper) 的 [v0.10.5](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/v0.10.5) 修改。**

- 原项目作者：NeuraXmy（贴吧署名 NeuraXmy / bilibili 署名 ルナ茶）。
- 基线提交：[`a7d4d6838a17f08f532e84273036dbab4f3cbd7c`](https://github.com/NeuraXmy/nightreign-overlay-helper/commit/a7d4d6838a17f08f532e84273036dbab4f3cbd7c)。
- 修改日期：2026-10-02。
- 当前增强版本：`0.10.6+auto.3`（r3）。
- 代码沿用上游 **GNU AGPLv3**，完整许可证见 [LICENSE](LICENSE)，来源与修改说明见 [NOTICE.md](NOTICE.md)。

这是独立维护的增强版本。原有功能与资源来源均保留署名，不将原作者的工作标为本项目原创。

## 在原版基础上的改进

| 改进 | 行为 |
|---|---|
| 自动定位 | 尝试从游戏截图定位 DAY 提示、血条和标准完整地图区域 |
| 地图缓存 | 同一局重复开图复用已经识别的结果，默认不强制重新扫描 |
| 后台刷新 | 刷新期间保留上一轮标注；新结果通过检查后替换 |
| 识别状态 | 显示等待、扫描、缓存、候选接近、失败及更新时间 |
| 结果检查 | 首次扫描在展示前检查游戏前台状态、完整地图与明显画面变化 |
| 提示音 | 约 0.2 秒的柔和短音，降低默认音量并减少重复提示 |
| 校准与纠错 | 显示检测区域预览，提供备用框选和直接计时纠正入口 |
| 配置隔离 | 使用独立增强版配置目录，保留原版用户配置 |

原版的缩圈、雨中冒险、血条比例标记、五种角色绝招倒计时及地图数据继续沿用。具体变更见 [CHANGELOG-增强版.md](CHANGELOG-增强版.md)。

## 使用

从 [Releases](https://github.com/Gywikun/nightreign-overlay-helper-plus/releases) 获取 Windows 程序包，完整解压后运行 `NightreignHelper-Auto-r3.exe`，保留同目录的 `_internal` 文件夹。

1. 进入游戏前启动助手，游戏使用窗口化或无边框窗口化。
2. 开局 DAY 提示可见时自动开始计时；打开完整地图并缩放到最小后自动识别。
3. 同一局再次开图直接使用缓存。画面明显变化、持续开图达到刷新周期或人工请求时才更新。
4. 自动定位失败时可使用备用校准，结果会保存。

完整设置与已知边界见 [README-增强版.md](README-增强版.md)。

## 从源码运行

当前已在 Windows 11、Python 3.13 上验证。依赖版本见 [requirements-lock.txt](requirements-lock.txt)。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe launch.py
```

测试：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Windows 构建：

```powershell
.\scripts\build_windows.ps1
```

输出为 `dist/NightreignHelper-Auto-r3/`，使用 PyInstaller `--onedir --windowed`。程序包和对应源码包在 Releases 一起提供。

## 验证范围与已知边界

- r3 的 66 项自动测试及本机原生程序启动、设置保存、退出检查已通过。
- 地图缓存与标注保留经过受控真实窗口控件测试；这些测试不是实际游戏对局验收。
- 实际游戏、HDR、特殊界面比例和物理设备听感仍需使用者反馈。
- 地图数据来自 v0.10.5，不会在线更新游戏资料。缓存仅保存在内存，退出后需重新识别。
- 完整地图识别已支持；局部地图随缩放跟踪、路线规划和队友共享尚未实现。
- 识别完成表示通过当前检查，不保证每个游戏预测百分之百正确。
- 通过截图识别游戏，不读写游戏内存，不自动发送游戏操作。

## 来源、许可与资源声明

代码在 GNU AGPLv3 下提供。保留原作者声明与完整许可证；分发修改后的程序时，也提供对应源码与构建说明。

游戏图片、地图和其他第三方素材的版权归各自权利人；本项目不声称拥有这些素材的版权。

保留上游致谢：

- [Fuwish](https://github.com/Fuwishx)：地图解包数据。
- [雀煊](https://space.bilibili.com/391379672)：大空洞水晶布局分享。

上游 README 与附带说明的原文分别保存在 [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md) 和 [docs/UPSTREAM_MANUAL.txt](docs/UPSTREAM_MANUAL.txt)，其中的原始声明按原文保留。
