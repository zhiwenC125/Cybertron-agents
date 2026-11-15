# Release process

版本从 `main` 的已审查提交发布。当前采用**手动触发 GitHub Actions `publish.yml`**：工作流从已存在的 `vX.Y.Z` tag 构建，依次验证、打包、通过 npm/PyPI Trusted Publishing 上传，再创建 GitHub Release。工作流不会从开发分支发布，也不保存长期发布 Token。

## 一次性维护者配置

1. 在 GitHub 仓库设置中保护 `main`：要求 Pull Request 和 `offline` CI 成功。第二位协作者接受邀请后，将最低审查人数从当前的 0 提高到 1。仓库位于个人账号下，只有一位 GitHub owner；新增成员是 collaborator。需要两位 GitHub owner 时应转入 Organization，并重新检查发布身份的仓库名。
2. 在 GitHub 仓库创建名为 `pypi` 的 Environment。可以设置必要的人工审批；发布工作流的 PyPI job 使用这个环境。
3. 在 npm 包的 **Settings → Trusted publishing** 中添加 GitHub Actions：Owner `zhiwenC125`，Repository `Cybertron-agents`，Workflow filename `publish.yml`。允许直接 `npm publish`；Environment 留空，与工作流一致。npm 要求的 Node/npm 版本由工作流安装。新建信任关系后，应在 npm 要求的期限内完成首次成功发布。
4. 在 PyPI 项目 `cybertron-agents` 的 **Manage → Publishing** 中添加 GitHub Actions Trusted Publisher：Owner `zhiwenC125`，Repository `Cybertron-agents`，Workflow `publish.yml`，Environment `pypi`。字段必须与工作流完全一致。
5. 至少邀请另一位可信维护者：GitHub collaborator、npm package owner、PyPI project Owner。PyPI Owner 具有删除项目及移除其他 Owner 的能力，需审慎授权。各渠道分别核查邀请已接受。个人 GitHub 仓库不能拥有第二位仓库 owner。

参考：[npm Trusted Publishing](https://docs.npmjs.com/trusted-publishers/)、[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)、[GitHub 分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。

## 每次发布

1. 从最新 `main` 开发布准备分支：`git switch -c release/vX.Y.Z`。
2. 运行 `python3 scripts/bump_version.py X.Y.Z`。它同时更新 npm、Python、Shell 默认 tag 和 Python fallback 版本；运行 `python3 scripts/bump_version.py --check` 核对。随后运行 `node scripts/build-payload.mjs`，更新 README、安装文档、阶段记录和变更说明。在 `docs/releases/vX.Y.Z.md` 写发布说明；`publish.yml` 会把它作为 GitHub Release 正文，缺失会先让 verify 失败。
3. 运行 [CONTRIBUTING.md](CONTRIBUTING.md) 所列测试及安装包验收，在临时项目验证三条安装路径。提交 PR，等待 `offline` CI 与维护者审查；合并到 `main`。
4. 在 `main` 上建立并推送指向合并提交的**附注 tag**：`git tag -a vX.Y.Z -m 'Cybertron Agents X.Y.Z'`，然后 `git push origin vX.Y.Z`。不要移动或复用已有发布 tag。
5. 在 GitHub **Actions → publish → Run workflow** 输入该 tag。工作流验证 tag 已在 `main` 历史中且版本完全一致，再构建一次、比对包内容，通过 OIDC 发布到 npm 和 PyPI，最后上传同批归档及 `SHA256SUMS` 到 GitHub Release。若某渠道已成功而后续渠道失败，只重跑失败 job；不要重复发布不可变版本。
6. 从三个**公开**渠道下载或查询版本，检查包文件名、摘要和 CLI 版本。将验收结果写入 `docs/stages/` 并提交到 `main`。若不同渠道分别重建导致压缩包摘要不同，逐文件比对并记录各渠道自己的摘要。

## 故障处理

- `npm` OIDC 失败：检查 npm Trusted Publisher 的 Owner、Repository、`publish.yml` 和允许的 `npm publish` 操作；确认 Node ≥22.14、npm ≥11.5.1，以及工作流有 `id-token: write`。
- PyPI OIDC 失败：检查 PyPI 上的 Owner、Repository、Workflow、Environment `pypi` 是否与工作流一致；确认 Environment 可供该 job 使用。
- CI 失败：修复源码并提交新的 PR；不要用跳过测试或修改旧 tag 的方式发布。
- 其中一渠道成功、另一渠道失败：保留已成功的不可变版本，修复配置后在 GitHub Actions 中只重跑失败的 job。若必须修改包内容，则升级到新版本。
- 发布后的热修复使用新的补丁版本。PyPI 和 npm 的同版本包不可覆盖；`git tag` 也不移动。

`0.2.0` 是手动发布的历史版本；其实际渠道摘要见[发布验收记录](docs/stages/I-release-020.md)。
