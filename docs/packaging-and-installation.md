# 安装、升级与排查

当前公开版本为 **0.9.0**。[GitHub Release](https://github.com/zhiwenC125/Cybertron-agents/releases/tag/v0.9.0) · [npm](https://www.npmjs.com/package/cybertron-agents/v/0.9.0) · [PyPI](https://pypi.org/project/cybertron-agents/0.9.0/)

## 选择一种安装方式

先安装 OpenCode 并配置可用的模型。Cybertron 的运行时需要 Python 3.9 或更高版本。npm 路径还需要 Node.js 18 或更高版本。

### npm

```bash
npx -y cybertron-agents@0.9.0 init --dry-run
npx -y cybertron-agents@0.9.0 init --apply
npx -y cybertron-agents@0.9.0 doctor --global
```

用 `npx` 时，后续子命令也带 `npx -y cybertron-agents@0.9.0`。需要直接运行 `cybertron` 时，可用 `npm install -g cybertron-agents@0.9.0` 安装 CLI，之后再执行 `cybertron init --apply`。

### pipx

```bash
pipx install cybertron-agents==0.9.0
pipx ensurepath
# 重新打开终端后执行下面两条命令
cybertron init --apply
cybertron doctor --global
```

找不到命令时，先用 `~/.local/bin/cybertron --version` 验证 CLI。

### GitHub Release

```bash
curl -fsSL https://github.com/zhiwenC125/Cybertron-agents/releases/download/v0.9.0/install.sh -o install.sh
curl -fsSL https://github.com/zhiwenC125/Cybertron-agents/releases/download/v0.9.0/SHA256SUMS -o SHA256SUMS
awk '$2 == "install.sh"' SHA256SUMS | shasum -a 256 -c -
bash install.sh --dry-run
bash install.sh --apply
```

执行安装脚本前可先审阅内容。安装脚本会打印启动器的完整路径。全局默认位置是 `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/bin/cybertron`。

## 安装位置

- **全局默认**写入 `${XDG_CONFIG_HOME:-$HOME/.config}/opencode`，让多个项目共用角色、命令、插件和 Python 运行时。
- **项目安装**在 `init` 上加 `--project .`，并用 `doctor --project .` 检查。适合隔离试用或项目需要单独的安装版本。
- 安装器默认拒绝重复安装。遇到全局和项目重复时，先确定要保留的安装位置，备份并迁移另一处的 Cybertron 文件。`--allow-duplicate` 适用于确实需要同时保留两套安装的场景。
- 工作记录放在项目的 `.cybertron/`。项目模型覆盖可用 `cybertron models setup --project .`，并可和全局角色安装一起使用。

## 模型与首次启动

运行 `cybertron models setup`，按提示设置十三角色的模型。可用 `models show` 查看映射、`models doctor` 核对加载、`models rollback` 恢复上一版。npm 用户以 `npx -y cybertron-agents@0.9.0` 代替 `cybertron`，Shell 用户用安装器给出的启动器路径。

OpenCode 负责模型认证。Cybertron 的模型配置保存模型 ID，提供方 API Key 通过 OpenCode 或对应环境变量配置。兼容 OpenAI API 的自有网关可用 `cybertron models provider-add` 登记。

重启 OpenCode 后，默认用 Prima 直接描述任务。想先看方案时，用 Shift+Tab 切到 Thirteenth，之后切回 Prima 执行。已有 OpenCode 命令习惯时，也可以使用 `/cybertron <需求>`。[自然语言验收用例](testing/opencode-acceptance.md)

## 升级与排查

1. 在原安装渠道更新 CLI，再用同一个安装位置运行 `init --apply`。pipx 用户先执行 `pipx upgrade cybertron-agents`。
2. 重启 OpenCode，在目标项目运行 `opencode2 debug config` 与 `opencode2 debug agents --standalone`，核对角色和插件的实际加载状态。
3. 若只看到基础 OpenCode 角色，核对 `doctor` 所指安装位置、项目配置的覆盖项，以及宿主是否禁用了 Cybertron 插件。能看到角色只能证明提示词已加载。需要验证执行闭环时，请运行一次隔离项目的最小用例。

DeepSeek Harness 随包提供实验性适配器。用 `cybertron dsh path` 定位目录，再在 DSH 中安装并选择 `Cybertron` preset。[DSH 能力与限制](../cybertron/dsh_adapter/docs/DETAIL.md) · [维护者发布流程](../RELEASE.md)
