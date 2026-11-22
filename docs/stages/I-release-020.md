# 阶段 I：0.2.0 三渠道发布核验

> 历史阶段记录，正文反映当时的版本和验证范围。当前行为见 [开发状态](../../DEVELOPMENT_PLAN.md)。

日期：2026-11-15。tag `v0.2.0` 指向提交 `e031548f3794ca8c14cbb865896eb0829b402474`；`main` 发布时指向同一提交。GitHub 的分支和 `main` CI 均通过。

| 渠道 | 公开地址 | 验证结果 |
| --- | --- | --- |
| npm | https://www.npmjs.com/package/cybertron-agents/v/0.2.0 | registry 元数据列出 `0.2.0`；发布 tarball SHA-1 为 `165b38b1a9bf9ff351d132205ac3df08ad587378`；从 registry 安装并运行 CLI 返回 `0.2.0` |
| PyPI | https://pypi.org/project/cybertron-agents/0.2.0/ | 公开 JSON API 列出 wheel 和 sdist；下载 wheel 后在干净虚拟环境安装，`cybertron --version` 返回 `0.2.0`，`init --dry-run` 通过 |
| GitHub | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.2.0 | Release 有 npm tarball、Python wheel、sdist、`install.sh` 四份附件；公开下载脚本与 tag 本地脚本 SHA-256 相同；指定 tag 的 Shell 安装预览通过 |

本地打包前运行 112 项单元测试、阶段 5 隔离验收、引擎自检、npm/Python 包内容一致性检查和 Twine 包元数据检查，均通过。发布后从公开渠道重新读取包，确认安装入口可用。

## 归档摘要差异

GitHub Release 附件使用维护者首次构建的归档；PyPI 文件由维护者上传前重新打包，因此压缩包摘要不同。对 PyPI 文件与 GitHub 附件逐文件比对：sdist 的 112 个文件内容完全相同；wheel 的 93 个文件中只有 `RECORD`、`WHEEL`、`top_level.txt` 三个打包元数据文件不同，代码与资源文件内容相同。不能把 GitHub 附件 SHA-256 用于校验 PyPI 下载文件；应使用各渠道自己的摘要。

| 文件 | GitHub 附件 SHA-256 | PyPI SHA-256 |
| --- | --- | --- |
| wheel | `294eaf6b0d14f584673d59afccd78e2011245427b01739255097b5e59192026a` | `c44654c2e736b19fc630386f008801f294eebae47bbc5b592364e63278b40fb5` |
| sdist | `575f10df8675b20ebea6dfaa1f3bb782b82fa9884a831fb5fd46fa72636b3ed5` | `dbe7339e34bcf780084a636c99288031e0976d7e9682dba69e6bdfc784eac3c7` |

npm 的 SHA-256 为 `b1db6c36e5a248bbc70eceda96dfe8f1aff8fd309c154b40f2e9ef00d1cbd492`；`install.sh` 的 SHA-256 为 `82dced736623431df720072ca23ba0f2fc2dfc14d8bc95f617dd69907cb5f7b2`。本阶段只验证公开包可获取、内容一致和安装入口运行；公司网关的真实 Key 与 38 个模型能力需在公司环境另行验收。
