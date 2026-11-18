# v0.7.1 发布验收

> 发布：2026-11-18 · GitHub Actions [publish run 44291448457](https://github.com/zhiwenC125/Cybertron-agents/actions/runs/44291448457)
> tag：`v0.7.1`（annotated）→ `main` 提交 `9dd491b`
> PR：[#16](https://github.com/zhiwenC125/Cybertron-agents/pull/16)（squash 合并）

## 渠道

| 渠道 | 版本 | 地址 | 摘要 |
| --- | --- | --- | --- |
| npm | `cybertron-agents@0.7.1` | https://www.npmjs.com/package/cybertron-agents/v/0.7.1 | tgz `sha256:02c547cd8a38bc8e488684810a37002009014ab6c8a87b88438503f7d9911f0a`；`shasum:7ebbd4616372751a1b91ef9492b537b2847d51a9` |
| PyPI | `cybertron-agents 0.7.1` | https://pypi.org/project/cybertron-agents/0.7.1/ | wheel `e9251651ee1b0a6ebea1aababd09c6406cef74ac0af258dee69f8600c4c2f284`；sdist `7805faf389b2a5e8f08e227b7d1cac76ba09f8d025f54ec526e0f7e626a45c9d` |
| GitHub Release | `v0.7.1` | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.7.1 | `cybertron-agents-0.7.1.tgz` `02c547cd…`；wheel `e9251651…`；sdist `7805faf3…`；`install.sh` `8c594da0b33f978757f2488b738f75b98fb3c2fee9765af9759945f3b6dbadb6`；`SHA256SUMS` |

Release 附件包含 npm tgz、wheel、sdist、`install.sh` 与 `SHA256SUMS`；工作流从 tag 重新构建并比对包内容后发布。三个渠道的产物摘要与 `SHA256SUMS` 一致。

## 公开渠道安装验收

在本机临时目录从公开渠道安装，不依赖源码 checkout：

| 渠道 | 命令 | 结果 |
| --- | --- | --- |
| npm | `npx -y cybertron-agents@0.7.1 --version` | `0.7.1` |
| PyPI | `pip install cybertron-agents==0.7.1` + `cybertron --version` | `cybertron-agents 0.7.1` |

npm 首次查询曾返回 404，约 90 秒后 registry 可读到 0.7.1；这是 npm 的发布后处理延迟，不是发布失败。

## CI

- `verify` 的 `offline` 作业在 `macos-15-intel` 上通过（约 1 分 54 秒），含 278 项 Python 单测、阶段 5 隔离验证、引擎自检与 npm/wheel 包内容比对。
- `build`、`npm`、`pypi`、`github_release` 作业全部成功。
- 本机受沙箱限制，5 项依赖嵌套 `sandbox-exec` 的用例会报 `Operation not permitted`；CI runner 不受影响。

## 说明

- 0.7.1 在 OpenCode 上引入 `external_scope` 与宿主原生升权；DSH 侧沿用会话模式与单次 `sandbox_permissions`。
- DSH dispatch 绑定仍未实现；DSH 目前只提供计划与账本访问。
- 项目外写入没有快照与回滚，只有产物哈希。
- 发布说明见 [v0.7.1.md](../releases/v0.7.1.md)。
