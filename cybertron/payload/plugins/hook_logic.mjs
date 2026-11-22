import path from 'node:path';
import os from 'node:os';
import { lstatSync, realpathSync } from 'node:fs';

export function nativeDispatch(event) {
  const card = event.input?.description;
  const match = /^\[([^\]]+)\] ([^|]+) \| (.+)$/.exec(card || '');
  const role = event.input?.agentID || event.input?.agent || event.input?.agentId;
  const callID = event.callID || event.id || event.toolCallID;
  if (!match || !role || !callID) {
    throw new Error('Native subagent requires node card, role, and call ID');
  }
  return { nodeID: match[1], capability: match[2].trim(), writeScope: match[3].trim(),
    role, callID, card };
}

export function childSession(result) {
  const direct = result?.sessionID || result?.sessionId || result?.metadata?.sessionID;
  if (typeof direct === 'string' && direct) return direct;
  const content = result?.content;
  if (typeof content === 'string') {
    try {
      const parsed = JSON.parse(content);
      return parsed.sessionID || parsed.sessionId || null;
    } catch { /* Host result is free text. */ }
  }
  return null;
}

export function nativeToolStatus(event) {
  if (event.status === 'completed') return 'completed';
  if (event.error?.name === 'AbortError') return 'cancelled';
  return 'error';
}

/**
 * Build the child-session permission rules for one dispatch. Under
 * workspace-write the project scopes are allowed directly; every declared
 * external path is `ask`, so the host gates it per call and the kernel can
 * record that the gate ran. `danger-full-access` keeps the existing open set.
 */
export function childPermissionRules({ accessMode, writeScope, externalScope }) {
  if (accessMode === 'danger-full-access') {
    return [
      { action: 'edit', resource: '*', effect: 'allow' },
      { action: 'external_directory', resource: '*', effect: 'allow' },
      { action: 'edit', resource: '.git/**', effect: 'deny' },
      { action: 'edit', resource: '.opencode/**', effect: 'deny' },
      { action: 'edit', resource: '.cybertron/runs/**', effect: 'deny' },
      { action: 'edit', resource: '.cybertron/templates/**', effect: 'deny' },
      { action: 'edit', resource: 'opencode.jsonc', effect: 'deny' },
      { action: 'shell', resource: '*', effect: 'deny' },
    ]
  }
  const external = externalScope?.length === 1 ? [
    // V2 checks dirname(target)/* before checking the exact file with edit.
    // Both still require the plugin's per-tool scope check.
    { action: 'external_directory', resource: path.join(path.dirname(externalScope[0]), '*'), effect: 'ask' },
    { action: 'edit', resource: externalScope[0], effect: 'ask' },
  ] : [];
  return [
    { action: 'edit', resource: '*', effect: 'deny' },
    ...(writeScope || []).map(resource => ({ action: 'edit', resource, effect: 'allow' })),
    { action: 'shell', resource: '*', effect: 'deny' },
    { action: 'external_directory', resource: '*', effect: 'deny' },
    ...external,
  ]
}

export function outsideProject(project, target) {
  const relative = path.relative(project, target);
  return relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative);
}

export function toolPath(project, value) {
  if (typeof value !== 'string' || !value) return null;
  return path.resolve(project, value.startsWith('~/') ? path.join(os.homedir(), value.slice(2)) : value);
}

/** Identify the exact leaf before and after the approval wait. */
export function externalFileState(target) {
  const parent = path.dirname(target);
  if (realpathSync(parent) !== parent || !lstatSync(parent).isDirectory())
    throw new Error('External write requires an existing canonical parent directory');
  const directory = lstatSync(parent, { bigint: true });
  const file = lstatSync(target, { throwIfNoEntry: false, bigint: true });
  if (file && (!file.isFile() || file.nlink !== 1n))
    throw new Error('External write requires a regular file with no symbolic or hard links');
  return {
    exists: Boolean(file),
    identity: [directory.dev, directory.ino, file?.dev, file?.ino,
      file?.ctimeNs, file?.size].map(String).join(':'),
  };
}

/** A run that can no longer accept nodes; a new request may start a fresh run. */
export function runIsTerminal(state) {
  return Boolean(state) && (state.status === 'completed' || state.status === 'superseded')
}
const REVIEWER_DENY = [
  '.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', '*.keystore',
  '*.jks', 'id_rsa*', 'id_ed25519*', '.ssh/**', '.aws/**',
  '.config/gcloud/**', '.npmrc', '.pypirc', '.netrc', '.docker/config.json',
  'kubeconfig*', 'secrets/**', '**/secrets/**', 'credentials*', '.git/**',
];
const globToRegExp = pattern => '^' + pattern
  .replace(/[.+^${}()|[\]\\]/g, '\\$&')
  .replace(/\*\*/g, '.*')
  .replace(/\*/g, '[^/]*')
  .replace(/\?/g, '.') + '$';

export function reviewerPathDenied(value) {
  if (typeof value !== 'string' || !value) return false;
  let normalized = value.replace(/\\/g, '/');
  if (normalized.startsWith('./')) normalized = normalized.slice(2);
  if (normalized.split('/').includes('.git')) return true;
  return REVIEWER_DENY.some(pattern => new RegExp(globToRegExp(pattern)).test(normalized));
}
