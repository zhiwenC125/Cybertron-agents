# v0.3.0 发布验收

> 发布：2026-11-17 · GitHub Actions [publish run 43930849708](https://github.com/zhiwenC125/Cybertron-agents/actions/runs/43930849708)
> tag：`v0.3.0`（annotated `24d000e`）→ `main` 提交 `6142fbb`
> 验收时间（UTC）：2026-11-16T18:55:04.332617+00:00

## 渠道

| 渠道 | 版本 | 地址 | 摘要 |
| --- | --- | --- | --- |
| npm | `cybertron-agents@0.3.0` | https://www.npmjs.com/package/cybertron-agents/v/0.3.0 | `sha512-uEmV3/bFy4lHCjrIQY7iof2KoH1Fc3jJMK/NgU4RPBWULWU2T1zbqamjN+f9ZIsfsgSzmk2QAnAHNyK6I1BlSw==` |
| PyPI | `cybertron-agents 0.3.0` | https://pypi.org/project/cybertron-agents/0.3.0/ | wheel `dbec05455565a43bdf956d30ca348f9d15aadfba2b49330160d71b710f077e51`；sdist `788adefbc63c9f8312d106ff53af6495fa31f749af4c707cc3be813b26eecba8` |
| GitHub Release | `v0.3.0` | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.3.0 | `cybertron-agents-0.3.0.tgz` `e9f07826b9d767a9f11ac90708fb083bfdd173b23ae6d39d1ea1c008ed23c6b7`；`install.sh` `3efab88774bb1def3f902df44ffcd290e42e01246bfcf3c3e4f3f1187ca4e5cf` |

Release 附件包含 npm tgz、wheel、sdist、`install.sh` 与 `SHA256SUMS`；工作流从 tag 重新构建并比对包内容后发布。

## 公开渠道安装验收

在本机临时目录从公开渠道安装，不依赖源码 checkout：

| 渠道 | 命令 | 结果 |
| --- | --- | --- |
| npm | `npx -y cybertron-agents@0.3.0 --version` | `0.3.0` |
| npm | `npx -y cybertron-agents@0.3.0 dsh path` | 解析到 `.../node_modules/cybertron-agents/payload/dsh-adapter` |
| npm | `npx -y cybertron-agents@0.3.0 init --apply --project <tmp>` | 13 个角色；`opencode2 debug config` 通过 |
| PyPI | `pip install cybertron-agents==0.3.0` + `cybertron --version` | `cybertron-agents 0.3.0` |
| PyPI | `cybertron dsh path` | 解析到 `.../site-packages/cybertron/payload/dsh-adapter` |
| PyPI | `cybertron init --dry-run --project <tmp>` | 预览写入 64 个文件，未落盘 |
| Shell | Release 的 `install.sh --dry-run --project <tmp>` | 预览写入 64 个文件，未落盘 |

工作流 verify 作业在 Intel macOS runner 上安装了 `clang-tidy`，运行 233 项 Python 单测、阶段 5 隔离验证、引擎自检和包内容比对；build、npm、PyPI、GitHub Release 作业全部通过。

## 说明

- 0.3.0 是 v6 动态任务图的功能版本，1.0 留待后续稳定化。
- DSH 适配器随 npm/PyPI 包分发（`payload/dsh-adapter`），用 `cybertron dsh path` 取路径后 `dsh plugin --profile <profile> add <路径>`；目前是实验性第二宿主，未绑定 DSH 子会话写范围。
- 旧九步 run 只读保留，不参与 v2 调度。
