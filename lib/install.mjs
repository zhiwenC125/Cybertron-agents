import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
  copyFileSync,
  unlinkSync,
  lstatSync,
} from 'node:fs';
import path from 'node:path';

/** In a source checkout use current assets; published packages use payload/. */
export function resolvePayload(pkgRoot) {
  const packed = path.join(pkgRoot, 'payload');
  const source = path.join(pkgRoot, '.opencode');
  const base = existsSync(path.join(source, 'agents')) ? source : packed;
  return {
    base,
    agents: path.join(base, 'agents'),
    commands: path.join(base, 'commands'),
  };
}

/** 计算安装目标目录：全局为 ~/.config/opencode，项目为 <dir>/.opencode。 */
export function targetBase({ global = false, projectDir = process.cwd() } = {}) {
  if (global) {
    const configHome = process.env.XDG_CONFIG_HOME || path.join(process.env.HOME, '.config');
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

function assertSafeTarget(base, target) {
  const relative = path.relative(base, target);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`安装目标越界: ${target}`);
  }
  let current = base;
  for (const component of relative.split(path.sep)) {
    current = path.join(current, component);
    if (lstatSync(current, { throwIfNoEntry: false })?.isSymbolicLink()) {
      throw new Error(`拒绝符号链接安装目标: ${current}`);
    }
  }
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
  let cleaned = '';
  let quoted = false;
  for (let pos = 0; pos < out.length; pos += 1) {
    const ch = out[pos];
    if (quoted && ch === '\\' && pos + 1 < out.length) {
      cleaned += ch + out[pos + 1];
      pos += 1;
      continue;
    }
    if (ch === '"') quoted = !quoted;
    if (ch === ',' && !quoted) {
      let next = pos + 1;
      while (next < out.length && /\s/.test(out[next])) next += 1;
      if (out[next] === '}' || out[next] === ']') continue;
    }
    cleaned += ch;
  }
  return cleaned;
}

/** 目标缺配置时写最小配置；已有配置保持原字节，不重写注释或未知字段。 */
export function ensureConfig(baseDir, dryRun) {
  const file = path.join(baseDir, 'opencode.jsonc');
  const minimal = `{\n  "$schema": "https://opencode.ai/config.json"\n}\n`;

  if (!existsSync(file)) {
    if (!dryRun) {
      mkdirSync(baseDir, { recursive: true });
      writeFileSync(file, minimal);
    }
    return { action: 'would-create', file };
  }

  const raw = readFileSync(file, 'utf8');
  if (raw.trim() === '') {
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
  return { action: 'missing-default', file };
}

/** 生成安装计划，不写盘。 */
export function planInstall({ pkgRoot, global = false, projectDir = process.cwd() }) {
  const payload = resolvePayload(pkgRoot);
  const base = targetBase({ global, projectDir });
  if (lstatSync(base, { throwIfNoEntry: false })?.isSymbolicLink() ||
      lstatSync(path.join(base, 'cybertron-runtime'), { throwIfNoEntry: false })?.isSymbolicLink()) {
    throw new Error(`拒绝符号链接安装或运行时目录: ${base}`);
  }
  const items = [];

  for (const kind of ['agents', 'commands']) {
    for (const name of listMarkdown(payload[kind])) {
      const src = path.join(payload[kind], name);
      const target = path.join(base, kind, name);
      let state = 'new';
      assertSafeTarget(base, target);
      if (existsSync(target)) {
        state = readFileSync(src).equals(readFileSync(target)) ? 'same' : 'update';
      }
      items.push({ kind, name, src, target, state });
    }
  }

  const runtime = existsSync(path.join(payload.base, 'cybertron-runtime', 'cybertron'))
    ? path.join(payload.base, 'cybertron-runtime', 'cybertron')
    : path.join(pkgRoot, 'cybertron');
  const extras = [
    { kind: 'plugins', name: 'cybertron.js', src: path.join(payload.base, 'plugins', 'cybertron.js'),
      target: path.join(base, 'plugins', 'cybertron.js') },
    ...readdirSync(runtime).filter(name => name.endsWith('.py')).sort().map(name => ({
      kind: 'runtime', name, src: path.join(runtime, name),
      target: path.join(base, 'cybertron-runtime', 'cybertron', name),
    })),
  ];
  for (const item of extras) {
    if (!existsSync(item.src)) throw new Error(`缺少运行时文件: ${item.src}`);
    assertSafeTarget(base, item.target);
    item.state = existsSync(item.target)
      ? (readFileSync(item.src).equals(readFileSync(item.target)) ? 'same' : 'update') : 'new';
    items.push(item);
  }

  return { payload, base, items };
}

/** 执行安装计划：新增直接写，更新先备份 .bak。 */
function nextBackup(target) {
  for (let index = 1; ; index += 1) {
    const backup = `${target}.bak.${index}`;
    if (!existsSync(backup)) return backup;
  }
}

export function applyInstall(plan, configFile = null, postApply = null) {
  let created = 0;
  let updated = 0;
  let same = 0;
  const changed = [];
  try {
    for (const item of plan.items) {
      if (item.state === 'same') {
        same += 1;
        continue;
      }
      mkdirSync(path.dirname(item.target), { recursive: true });
      const previous = item.state === 'update' ? readFileSync(item.target) : null;
      const backup = previous === null ? null : nextBackup(item.target);
      if (backup) writeFileSync(backup, previous, { flag: 'wx' });
      changed.push({ target: item.target, previous, backup });
      const temporary = `${item.target}.cybertron-tmp`;
      try {
        copyFileSync(item.src, temporary);
        copyFileSync(temporary, item.target);
      } finally {
        if (existsSync(temporary)) unlinkSync(temporary);
      }
      if (previous === null) created += 1;
      else updated += 1;
    }
    if (configFile) {
      mkdirSync(path.dirname(configFile), { recursive: true });
      changed.push({ target: configFile, previous: null, backup: null });
      writeFileSync(configFile, `{\n  "$schema": "https://opencode.ai/config.json"\n}\n`, { flag: 'wx' });
    }
    if (postApply) postApply();
  } catch (error) {
    for (const item of changed.reverse()) {
      if (item.previous === null) {
        if (existsSync(item.target)) unlinkSync(item.target);
      } else writeFileSync(item.target, item.previous);
      if (item.backup && existsSync(item.backup)) unlinkSync(item.backup);
    }
    throw error;
  }
  return { created, updated, same };
}
