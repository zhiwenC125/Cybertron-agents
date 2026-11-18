#!/usr/bin/env node
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  applyInstall,
  ensureConfig,
  listMarkdown,
  planInstall,
  resolvePayload,
  targetBase,
} from '../lib/install.mjs';

const pkgRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function runModelCli(args) {
  const runtime = existsSync(path.join(pkgRoot, '.opencode', 'agents'))
    ? pkgRoot : path.join(pkgRoot, 'payload', 'cybertron-runtime');
  const result = spawnSync(process.env.CYBERTRON_PYTHON || 'python3',
    ['-m', 'cybertron.model_cli', ...args], {
      cwd: runtime, stdio: 'inherit', shell: false,
      env: { ...process.env, CYBERTRON_PROJECT_CWD: process.cwd(),
        PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
  });
  if (result.error) throw result.error;
  return result.status ?? 1;
}

function usage() {
  console.log(`cybertron-agents

用法:
  cybertron init [--global | --project DIR] [--apply] [--dry-run]
  cybertron doctor [--global | --project DIR]
  cybertron models setup|show|doctor|rollback [--global | --project DIR]
  cybertron dsh path
  cybertron --version
  cybertron --help

默认 init 只预览（dry-run），加 --apply 才写入。`);
}

function parseArgs(argv) {
  const opts = { global: false, projectDir: process.cwd(), apply: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--global') {
      opts.global = true;
    } else if (arg === '--project') {
      opts.projectDir = argv[i + 1];
      i += 1;
    } else if (arg.startsWith('--project=')) {
      opts.projectDir = arg.slice('--project='.length);
    } else if (arg === '--apply') {
      opts.apply = true;
    } else if (arg === '--dry-run') {
      opts.apply = false;
    } else {
      opts.error = `未知参数: ${arg}`;
    }
  }
  return opts;
}

const MARKS = { new: '+', update: '~', same: '=' };

function describe(item) {
  const note = item.state === 'update' ? ' (备份为 .bak 后覆盖)' : '';
  return `  ${MARKS[item.state]} ${item.target}${note}`;
}

const CONFIG_TEXT = {
  'would-create': '将写入最小配置',
  'filled-empty': '空配置；请先移走或修复',
  'has-default': '已有默认角色，保持不变',
  'missing-default': '沿用 OpenCode 默认角色',
  'parse-failed': '无法解析，跳过',
  'not-object': '不是对象，跳过',
};

function runInit(opts) {
  const dryRun = !opts.apply;
  const plan = planInstall({
    pkgRoot,
    global: opts.global,
    projectDir: opts.projectDir,
  });

  if (plan.items.length === 0) {
    console.error('未找到可安装的 payload（检查 .opencode/agents 或 payload/）。');
    process.exit(1);
  }

  console.log(`安装目标: ${plan.base}`);
  console.log(`payload: ${plan.payload.base}`);
  console.log(`模式: ${dryRun ? '预览（dry-run，加 --apply 写入）' : '写入（--apply）'}`);
  for (const item of plan.items) console.log(describe(item));

  const config = ensureConfig(plan.base, true);
  console.log(`配置: ${config.file} -> ${CONFIG_TEXT[config.action] ?? config.action}`);
  if (['filled-empty', 'parse-failed', 'not-object'].includes(config.action)) {
    console.error('已有配置无法安全安装；请先修复配置。');
    process.exitCode = 2;
    return;
  }

  if (dryRun) {
    console.log('\n这是预览。确认后加 --apply 执行。');
    return;
  }

  const result = applyInstall(plan, config.action === 'would-create' ? config.file : null, () => {
    const modelStatus = runModelCli(['apply', ...(opts.global ? ['--global'] : ['--project', opts.projectDir])]);
    if (modelStatus !== 0) throw new Error('模型编队重应用失败，安装文件已恢复');
  });
  console.log(`\n新增 ${result.created}，更新 ${result.updated}，未变 ${result.same}`);
  console.log('安装完成。运行: opencode2 debug agents');
  console.log(`模型编队配置入口: npx -y cybertron-agents@${JSON.parse(readFileSync(path.join(pkgRoot, 'package.json'), 'utf8')).version} models setup（全局安装或 Shell 启动器可用对应 cybertron 入口）`);
}

function runDshPath() {
  const payload = resolvePayload(pkgRoot);
  const candidates = [
    path.join(payload.base, 'dsh-adapter'),
    path.join(pkgRoot, 'cybertron', 'dsh_adapter'),
  ];
  const bundle = candidates.find(dir => existsSync(path.join(dir, 'package.json')));
  if (!bundle) {
    console.error('未找到 DSH bundle（payload/dsh-adapter/package.json）。');
    process.exit(1);
  }
  console.log(bundle);
}

function runDoctor(opts) {
  const base = targetBase({ global: opts.global, projectDir: opts.projectDir });
  const payload = resolvePayload(pkgRoot);
  const agents = listMarkdown(path.join(base, 'agents'));
  const commands = listMarkdown(path.join(base, 'commands'));
  const plugin = path.join(base, 'plugins', 'cybertron.js');
  const pluginHelper = path.join(base, 'plugins', 'hook_logic.mjs');
  const pluginPolicy = path.join(base, 'plugins', 'shell_policy.mjs');
  const runtime = path.join(base, 'cybertron-runtime', 'cybertron', 'plugin_cli.py');
  const config = path.join(base, 'opencode.jsonc');
  const expected = listMarkdown(payload.agents).length;

  console.log(`目标: ${base}`);
  console.log(`已安装角色: ${agents.length}（期望 ${expected}）`);
  console.log(`已安装命令: ${commands.length}`);
  console.log(`运行时: ${existsSync(plugin) && existsSync(pluginHelper) && existsSync(pluginPolicy) && existsSync(runtime) ? '存在' : '缺失'}`);
  console.log(`配置: ${existsSync(config) ? '存在' : '缺失'}`);
  console.log(`node: ${process.version}`);

  if (agents.length !== expected) {
    console.log('提示: 角色数量不符，重新运行当前安装入口的 init --apply。');
  }
  if (agents.length !== expected || commands.length !== 1 || !existsSync(config)
      || !existsSync(plugin) || !existsSync(pluginHelper) || !existsSync(pluginPolicy) || !existsSync(runtime)) {
    process.exitCode = 1;
  }
}

const argv = process.argv.slice(2);
if (argv.includes('--version') || argv.includes('-v')) {
  const pkg = JSON.parse(readFileSync(path.join(pkgRoot, 'package.json'), 'utf8'));
  console.log(pkg.version);
  process.exit(0);
}
if (argv.length === 0 || argv.includes('--help') || argv.includes('-h')) {
  usage();
  process.exit(0);
}

const cmd = argv[0];
if (cmd === 'models') process.exit(runModelCli(argv.slice(1)));
if (cmd === 'dsh') {
  if (argv[1] === 'path') {
    runDshPath();
    process.exit(0);
  }
  console.error('用法: cybertron dsh path');
  process.exit(2);
}


const opts = parseArgs(argv.slice(1));
if (opts.error) {
  console.error(opts.error);
  usage();
  process.exit(2);
}

if (cmd === 'init') {
  runInit(opts);
} else if (cmd === 'doctor') {
  runDoctor(opts);
} else {
  console.error(`未知命令: ${cmd}`);
  usage();
  process.exit(2);
}
