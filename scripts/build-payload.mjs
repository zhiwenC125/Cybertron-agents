import { cpSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const payload = path.join(root, 'payload');

rmSync(payload, { recursive: true, force: true });
for (const kind of ['agents', 'commands']) {
  const src = path.join(root, '.opencode', kind);
  const dest = path.join(payload, kind);
  mkdirSync(dest, { recursive: true });
  cpSync(src, dest, { recursive: true });
}
for (const base of [payload, path.join(root, 'cybertron', 'payload')]) {
  const pluginDir = path.join(base, 'plugins');
  const runtimeDir = path.join(base, 'cybertron-runtime', 'cybertron');
  mkdirSync(pluginDir, { recursive: true });
  mkdirSync(runtimeDir, { recursive: true });
  cpSync(path.join(root, '.opencode', 'plugins', 'cybertron.js'),
    path.join(pluginDir, 'cybertron.js'));
  for (const filename of ['__init__.py', ...readdirSync(path.join(root, 'cybertron'))
    .filter(name => name.endsWith('.py'))]) {
    cpSync(path.join(root, 'cybertron', filename), path.join(runtimeDir, filename));
  }
}
console.log(`payload 已生成: ${payload}`);
