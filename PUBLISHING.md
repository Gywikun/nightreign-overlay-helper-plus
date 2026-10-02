# 发布维护说明

## 当前已经发布的项目

- 仓库：[Gywikun/nightreign-overlay-helper-plus](https://github.com/Gywikun/nightreign-overlay-helper-plus)。展示名称：黑夜君临地图信息助手。
- 此仓库是 [NeuraXmy/nightreign-overlay-helper](https://github.com/NeuraXmy/nightreign-overlay-helper) 的公开 Fork；默认分支为 `auto-enhancements`。
- 增强代码基于上游 v0.10.5，基线提交 `a7d4d6838a17f08f532e84273036dbab4f3cbd7c`。
- 当前程序发布为 [v0.10.6-auto.3 预发布版](https://github.com/Gywikun/nightreign-overlay-helper-plus/releases/tag/v0.10.6-auto.3)，包含完整 Windows ZIP、对应源码 ZIP、独立 EXE 和 SHA256 文件。
- 此次截图和指南补充只更新默认分支文档与反馈入口，未更改现有程序或源码附件。

## 已有仓库的后续修改

下面是维护者在新目录取得当前增强分支的示例；不要再次从基线创建同名分支，也不要覆盖正在使用的助手目录。

```powershell
git clone "https://github.com/Gywikun/nightreign-overlay-helper-plus.git" "D:\Projects\nightreign-overlay-helper-public"
Set-Location "D:\Projects\nightreign-overlay-helper-public"
git switch auto-enhancements
```

修改前查看 `git status`，正常提交并推送到当前分支。纯截图/文档补充不需要重新发布 EXE。程序变化应重新验证、构建并使用新的版本号和标签，保留现有版本供使用者下载。

源码运行/依赖安装见[首页](README.md)，Windows 构建脚本为 [scripts/build_windows.ps1](scripts/build_windows.ps1)。发布时保留源代码、资源来源、`LICENSE`、`NOTICE.md` 和对应构建说明。

## 工作流与 Release

本增强分支删除了上游 `.github/workflows/build.yml` 与 `release.yml`。原 `build.yml` 在推送 `v*` 标签时会执行上游 onefile 构建和自动发布步骤，可能与这里的 onedir 程序包及手工发布说明发生冲突。

当前分支没有沿用这两个自动发布工作流。新增工作流前，先明确标签范围、构建方式和产物命名，避免同一个标签触发两套发布。上游 `.python-version` 与 `scripts/ci_version.py` 保留。

## 后续发布检查

1. 先验证程序变化，记录实战与受控测试的实际范围。
2. 生成完整 onedir 程序目录，并保留同目录 `_internal`；用[构建脚本](scripts/build_windows.ps1)和[打包脚本](scripts/package_release.py)准备程序 ZIP、对应源码和校验文件。
3. 新版本更新名称、版本号、变更说明和已知边界，再对增强代码提交创建新标签。
4. Release 优先给普通用户完整 Windows ZIP 下载入口，明确独立 EXE 的运行库依赖；对应源码指向本次发布的固定标签/源码包。
5. 核对附件上传状态、大小和 SHA256；未验证实战兼容性时继续清楚标明预发布与验证边界。
6. 确认 README、[图文指南](docs/使用指南.md)、[状态截图](docs/界面截图.md)和[问题反馈](https://github.com/Gywikun/nightreign-overlay-helper-plus/issues/new/choose)对应实际版本。

代码库不提交 `.venv`、`.work`、本地日志、用户设置、`dist` 或程序 ZIP。体积较大的程序包放 Releases 附件。

## 来源与许可

原始 `LICENSE` 保持不变；上游 README 和 manual 原文保存在 docs 中。代码沿用 AGPLv3，游戏与其他第三方素材的版权归原权利人，具体见 [NOTICE.md](NOTICE.md)。

## 官方参考

- [Fork 仓库](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/fork-a-repo)
- [仓库大文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
- [管理 Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
- [Issue 表单语法](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
