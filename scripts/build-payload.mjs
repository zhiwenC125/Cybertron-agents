import { cpSync, mkdirSync, rmSync } from 'node:fs';
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
console.log(`payload 已生成: ${payload}`);
