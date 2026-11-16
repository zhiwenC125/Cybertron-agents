import { cpSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const payload = path.join(root, 'payload');
const pluginSource = path.join(root, 'cybertron', 'v6_plugin', 'cybertron.js');
const hookSource = path.join(root, 'cybertron', 'v6_plugin', 'hook_logic.mjs');
const checkoutPlugin = path.join(root, '.opencode', 'plugins', 'cybertron.js');

mkdirSync(path.dirname(checkoutPlugin), { recursive: true });
cpSync(pluginSource, checkoutPlugin);
cpSync(hookSource, path.join(root, '.opencode', 'plugins', 'hook_logic.mjs'));

rmSync(payload, { recursive: true, force: true });
for (const kind of ['agents', 'commands']) {
  const src = path.join(root, '.opencode', kind);
  const dest = path.join(payload, kind);
  mkdirSync(dest, { recursive: true });
  cpSync(src, dest, { recursive: true });
  const bundled = path.join(root, 'cybertron', 'payload', kind);
  mkdirSync(bundled, { recursive: true });
  cpSync(src, bundled, { recursive: true });
}
for (const base of [payload, path.join(root, 'cybertron', 'payload')]) {
  cpSync(path.join(root, 'cybertron', 'dsh_adapter'),
    path.join(base, 'dsh-adapter'), { recursive: true });
  const pluginDir = path.join(base, 'plugins');
  const runtimeDir = path.join(base, 'cybertron-runtime', 'cybertron');
  mkdirSync(pluginDir, { recursive: true });
  mkdirSync(runtimeDir, { recursive: true });
  cpSync(pluginSource,
    path.join(pluginDir, 'cybertron.js'));
  cpSync(hookSource, path.join(pluginDir, 'hook_logic.mjs'));
  for (const filename of ['__init__.py', ...readdirSync(path.join(root, 'cybertron'))
    .filter(name => name.endsWith('.py'))]) {
    cpSync(path.join(root, 'cybertron', filename), path.join(runtimeDir, filename));
  }
}
console.log(`payload 已生成: ${payload}`);
