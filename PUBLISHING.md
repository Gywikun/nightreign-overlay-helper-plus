# 发布到 GitHub

## 推荐：Fork 上游并保留 Git 历史

1. 登录 GitHub，打开 https://github.com/NeuraXmy/nightreign-overlay-helper ，点击 Fork。
2. 选择自己的账号，仓库名可改为 `nightreign-overlay-helper-plus`。
3. 将 Fork 克隆到一个新的本地目录，不要覆盖正在使用的助手目录。
4. 从原版 v0.10.5 基线创建 `auto-enhancements` 分支，复制本准备目录的内容，保留克隆目录中的 `.git`。

以下命令已使用你的账号 `Gywikun`；目录路径可按需调整：

```powershell
git clone "https://github.com/Gywikun/nightreign-overlay-helper-plus.git" "D:\Projects\nightreign-overlay-helper-public"
Set-Location "D:\Projects\nightreign-overlay-helper-public"
git remote add upstream "https://github.com/NeuraXmy/nightreign-overlay-helper.git"
git fetch upstream tag v0.10.5
git switch -c auto-enhancements a7d4d6838a17f08f532e84273036dbab4f3cbd7c
```

将准备目录内的文件和文件夹复制到这个克隆目录。隐藏文件 `.gitignore` 也需要复制；保留目标目录原有的 `.git`。
这是对选定基线应用增强源码，不需要强制推送或重写上游历史。

```powershell
git status --short
git add README.md NOTICE.md .gitignore PUBLISHING.md LICENSE launch.py config.yaml pyproject.toml requirements-lock.txt build.bat manual.txt
git add src tests scripts assets data docs
git add "README-增强版.md" "CHANGELOG-增强版.md"
git diff --cached --stat
git commit -m "Add automatic map caching, recognition feedback and soft short alerts"
git push -u origin auto-enhancements
```

在 GitHub 的仓库设置中，将默认分支设为 `auto-enhancements`，这样首页直接显示增强版说明。

如果不使用 Fork，也可以创建新的 Public 仓库并上传这些源文件；README 与 NOTICE 中的上游归属说明仍应保留。

## 仓库说明建议

> 基于 NeuraXmy/nightreign-overlay-helper v0.10.5 的非官方自动增强版：自动定位、地图缓存与后台刷新、识别状态提示、柔和短提示音。代码沿用 AGPLv3。

## 发布程序包

代码仓库提交源文件，不提交 `.venv`、`.work`、`dist`、`release`、本地日志或用户配置。

在 Releases 里选择 Draft a new release：

- Tag：`v0.10.6-auto.3`。
- Target：增强代码所在的 `auto-enhancements` 分支。
- Title：`v0.10.6-auto.3 — 自动增强版 r3`。
- 先作为 Pre-release 发布，明确实际游戏/HDR验证边界。
- 上传 Windows 完整程序包、对应源码包与 SHA256 校验文件。

程序包约 137 MiB，应放在 Releases 附件中。GitHub 普通 Git 仓库会阻止超过 100 MiB 的单个文件；网页上传单文件限制为 25 MiB。因此不要把程序 ZIP 拖到 Code 文件列表里，也不要把源码 ZIP 当作源码仓库。

本目录 README 已标明原项目、原作者、版本、基线提交、修改日期、功能差异和许可证。
原始 LICENSE 保持不变，原 README/manual 保存在 docs/。发布 exe 时一并提供对应源代码与构建方法。

## 官方参考

- Fork：https://docs.github.com/en/pull-requests/how-tos/work-with-forks/fork-a-repo
- 大文件：https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
- Releases：https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository
- 上游许可证：https://github.com/NeuraXmy/nightreign-overlay-helper/blob/main/LICENSE
