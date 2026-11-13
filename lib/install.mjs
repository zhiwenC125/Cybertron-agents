import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
  copyFileSync,
} from 'node:fs';
import path from 'node:path';
import os from 'node:os';

/** 解析安装 payload：优先用 npm 包内的 payload/，否则回退到仓库 .opencode/。 */
export function resolvePayload(pkgRoot) {
  const packed = path.join(pkgRoot, 'payload');
  const base = existsSync(path.join(packed, 'agents')) ? packed : path.join(pkgRoot, '.opencode');
  return {
    base,
    agents: path.join(base, 'agents'),
    commands: path.join(base, 'commands'),
  };
}

/** 计算安装目标目录：全局为 ~/.config/opencode，项目为 <dir>/.opencode。 */
export function targetBase({ global = false, projectDir = process.cwd() } = {}) {
  if (global) {
    const configHome = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config');
    return path.join(configHome, 'opencode');
  }
  return path.join(projectDir || process.cwd(), '.opencode');
}

export function listMarkdown(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith('.md'))
    .sort();
}

/** 去掉 JSONC 注释，便于在保留用户配置的前提下读取。 */
function stripJsonc(text) {
  let out = '';
  let i = 0;
  let inString = false;
  let quote = '';
  while (i < text.length) {
    const ch = text[i];
    const next = text[i + 1];
    if (inString) {
      out += ch;
      if (ch === '\\') {
        out += next ?? '';
        i += 2;
        continue;
      }
      if (ch === quote) inString = false;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inString = true;
      quote = ch;
      out += ch;
      i += 1;
      continue;
    }
    if (ch === '/' && next === '/') {
      while (i < text.length && text[i] !== '\n') i += 1;
      continue;
    }
    if (ch === '/' && next === '*') {
      i += 2;
      while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) i += 1;
      i += 2;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}

/** 目标缺配置时写最小配置；已有配置时只在缺少 default_agent 时补上。 */
export function ensureConfig(baseDir, dryRun) {
  const file = path.join(baseDir, 'opencode.jsonc');
  const minimal = `{\n  "$schema": "https://opencode.ai/config.json",\n  "default_agent": "prima"\n}\n`;

  if (!existsSync(file)) {
    if (!dryRun) {
      mkdirSync(baseDir, { recursive: true });
      writeFileSync(file, minimal);
    }
    return { action: 'would-create', file };
  }

  const raw = readFileSync(file, 'utf8');
  if (raw.trim() === '') {
    if (!dryRun) writeFileSync(file, minimal);
    return { action: 'filled-empty', file };
  }

  let data;
  try {
    data = JSON.parse(stripJsonc(raw));
  } catch {
    return { action: 'parse-failed', file };
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return { action: 'not-object', file };
  }
  if ('default_agent' in data) {
    return { action: 'has-default', file };
  }
  data.default_agent = 'prima';
  if (!dryRun) writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`);
  return { action: 'set-default', file };
}

/** 生成安装计划，不写盘。 */
export function planInstall({ pkgRoot, global = false, projectDir = process.cwd() }) {
  const payload = resolvePayload(pkgRoot);
  const base = targetBase({ global, projectDir });
  const items = [];

  for (const kind of ['agents', 'commands']) {
    for (const name of listMarkdown(payload[kind])) {
      const src = path.join(payload[kind], name);
      const target = path.join(base, kind, name);
      let state = 'new';
      if (existsSync(target)) {
        state = readFileSync(src).equals(readFileSync(target)) ? 'same' : 'update';
      }
      items.push({ kind, name, src, target, state });
    }
  }

  return { payload, base, items };
}

/** 执行安装计划：新增直接写，更新先备份 .bak。 */
export function applyInstall(plan) {
  let created = 0;
  let updated = 0;
  let same = 0;
  for (const item of plan.items) {
    if (item.state === 'new') {
      mkdirSync(path.dirname(item.target), { recursive: true });
      copyFileSync(item.src, item.target);
      created += 1;
    } else if (item.state === 'update') {
      mkdirSync(path.dirname(item.target), { recursive: true });
      copyFileSync(item.target, `${item.target}.bak`);
      copyFileSync(item.src, item.target);
      updated += 1;
    } else {
      same += 1;
    }
  }
  return { created, updated, same };
}
