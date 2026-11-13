#!/usr/bin/env node
import path from 'node:path';
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

function usage() {
  console.log(`cybertron-agents

用法:
  cybertron init [--global | --project DIR] [--apply] [--dry-run]
  cybertron doctor [--global | --project DIR]
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
  'filled-empty': '将补全 default_agent',
  'has-default': '已有 default_agent',
  'set-default': '将补 default_agent',
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

  const config = ensureConfig(plan.base, dryRun);
  console.log(`配置: ${config.file} -> ${CONFIG_TEXT[config.action] ?? config.action}`);

  if (dryRun) {
    console.log('\n这是预览。确认后加 --apply 执行。');
    return;
  }

  const result = applyInstall(plan);
  console.log(`\n新增 ${result.created}，更新 ${result.updated}，未变 ${result.same}`);
  console.log('安装完成。运行: opencode2 debug agents');
}

function runDoctor(opts) {
  const base = targetBase({ global: opts.global, projectDir: opts.projectDir });
  const payload = resolvePayload(pkgRoot);
  const agents = listMarkdown(path.join(base, 'agents'));
  const commands = listMarkdown(path.join(base, 'commands'));
  const config = path.join(base, 'opencode.jsonc');
  const expected = listMarkdown(payload.agents).length;

  console.log(`目标: ${base}`);
  console.log(`已安装角色: ${agents.length}（期望 ${expected}）`);
  console.log(`已安装命令: ${commands.length}`);
  console.log(`配置: ${existsSync(config) ? '存在' : '缺失'}`);
  console.log(`node: ${process.version}`);

  if (agents.length !== expected) {
    console.log('提示: 角色数量不符，运行 cybertron init --apply 重新安装。');
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
