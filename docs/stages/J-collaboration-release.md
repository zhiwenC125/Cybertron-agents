# 阶段 J：协作治理与可信发布

日期：2026-11-15。`0.2.0` 的代码和最新 README 已在默认分支 `main`；`codex/stages-a-e` 已完整并入后删除远端及本地分支。历史 tag `v0.2.0` 保持不变。

## 已配置

- `main` 使用 GitHub 分支保护：必须经 PR，要求 `offline` CI 成功并保持分支最新；管理员同样受保护；禁止强推与删除。第二位协作者尚未提供用户名，最低审查数暂为 0，邀请接受后改为 1。
- GitHub `pypi` Environment 已创建，部署分支限制为受保护分支。PyPI 发布 job 将使用该 Environment。
- 新增 `CONTRIBUTING.md`、`RELEASE.md`、`scripts/bump_version.py` 和 `.github/workflows/publish.yml`。下一版本由维护者合并到 `main` 后，手动运行 `publish` 并输入已有 tag；工作流核验 tag、版本和 `main` 祖先关系，跑隔离测试，构建同批 npm/Python 包，然后通过 OIDC 分别发布 npm、PyPI，最后创建 GitHub Release。
- `package.json` 仓库地址使用 GitHub 正式仓库 URL，以匹配 npm Trusted Publisher 的仓库身份。

## 验证

- `python3 -m unittest discover -s tests -v`：112 项通过。
- `python3 -m cybertron.stage5_verify`：隔离 QA 完成，项目写入、设备读取和网络连接被阻止。
- `python3 cybertron_primes_engine.py`：引擎自检通过。
- `scripts/bump_version.py --check` 核对现有 `0.2.0` 的四处版本；`0.2.1 --dry-run` 与临时目录渲染验证通过；`publish.yml` YAML 解析通过。

## 待维护者账号与服务端配置

1. 用户提供 GitHub、npm、PyPI 的协作者用户名后，邀请 GitHub collaborator、npm package owner、PyPI project Owner；确认各邀请已接受。个人 GitHub 仓库只有一位 owner，不能直接增加第二位 GitHub owner。
2. 第二位 GitHub collaborator 接受后，把 `main` 的最低批准审查数提高到 1。
3. `publish.yml` 合并至默认分支后，分别在 npm 包设置与 PyPI 项目 Publishing 页面登记 GitHub Actions Trusted Publisher。npm 配置须允许直接发布；PyPI 配置须填写 Environment `pypi`。首次实际 OIDC 发布需要用未来新版本验证；`0.2.0` 已经手工发布，不重复上传。
