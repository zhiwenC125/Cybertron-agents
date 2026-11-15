# 阶段 I：0.2.1 三渠道发布核验

日期：2026-11-15。tag `v0.2.1` 指向提交 `5fe31e593055a18fd03af2e80e56d6095d06d8f3`；发布时 `main` 指向 `a5ffbdce6c6414148a70d37ffa450da576c0fc09`（包含 PR #4 的 workflow 修复）。PR #3 的 `offline` CI 与 `main` CI 均通过。

| 渠道 | 公开地址 | 验证结果 |
| --- | --- | --- |
| npm | https://www.npmjs.com/package/cybertron-agents/v/0.2.1 | registry 列出 `0.2.1`；tarball SHA-1 为 `faafcd2e741730518e2977d781ad63dcaded1389`；带 SLSA provenance 证明（Transparency log index `3899564258`）；从 registry 运行 `npx -y cybertron-agents@0.2.1 init --dry-run` 成功 |
| PyPI | https://pypi.org/project/cybertron-agents/0.2.1/ | wheel 与 sdist 均存在；在干净 venv 安装后 `cybertron --version` 返回 `0.2.1`，`init --dry-run` 使用包内 payload |
| GitHub | https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.2.1 | Release 含 tgz、wheel、sdist、`install.sh` 与 `SHA256SUMS` |

## 发布过程

- PR #3 合并后创建并推送附注 tag `v0.2.1`。
- 首次 `publish.yml`（run `43700677910`）失败：npm 把 `dist/cybertron-agents-0.2.1.tgz` 解析成 GitHub 仓库简写 `github:dist/...`，执行 `git ls-remote ssh://git@github.com/dist/...` 后以 128 退出；同一次运行的 PyPI job 已成功发布 0.2.1。
- PR #4 修复：`npm publish "./dist/..."`、为 npm job 增加 `actions/checkout`、移除 `setup-node@v4` 不支持的 `package-manager-cache`，并新增 `publish_pypi` 开关。
- 重试 run `43701212591` 使用 `publish_pypi=false`：npm 通过 OIDC 发布成功并创建 GitHub Release，PyPI job 按输入跳过，避免重复发布不可变版本。

## 归档摘要

GitHub Release 与 PyPI 的构建时间不同，摘要不可互换；各渠道应使用自己的摘要：

| 文件 | GitHub Release SHA-256 | PyPI SHA-256 |
| --- | --- | --- |
| wheel | `260b00100b529a688f1b701edbb725c8ecf9201201ea3c373342c688605a4df3` | `9e9921a9b186bc3557db89116325b93aaee4ff389d2f433b49d32f35930f0462` |
| sdist | `e88f3a4d725cf542c0facb2318a5b230942bf6cf8ea3b454fba78b5c66d46d4a` | `5e33f53c9327358647c6e7b6bfe2a6d723046ba8a701953f03d6743d78ada485` |

GitHub `SHA256SUMS` 中的 npm tgz 为 `7b2c5c967c86eb99955327e5af74fa16b96cb91f6bfdd5a54e67ec3b06d1055b`，`install.sh` 为 `14debe6ca1e210de307bf52d142d8d89c4c906d7c8156309d6c862532ba05554`。

## 本地验证

发布前运行 112 项单元测试、`scripts/bump_version.py 0.2.1 --check` 与 `node scripts/build-payload.mjs`，均通过。npm 与 PyPI 的 OIDC Trusted Publishing 流程均已实际跑通；公司网关的真实凭证与模型能力仍需在公司环境另行验收。
