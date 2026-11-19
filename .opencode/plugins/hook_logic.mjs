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
      { action: 'edit', resource: 'opencode.jsonc', effect: 'deny' },
      { action: 'shell', resource: '*', effect: 'deny' },
    ]
  }
  const external = (externalScope || []).flatMap(path => ([
    { action: 'external_directory', resource: path, effect: 'ask' },
    { action: 'external_directory', resource: path + '/*', effect: 'ask' },
    { action: 'edit', resource: path, effect: 'ask' },
    { action: 'edit', resource: path + '/*', effect: 'ask' },
  ]))
  return [
    { action: 'edit', resource: '*', effect: 'deny' },
    ...(writeScope || []).map(resource => ({ action: 'edit', resource, effect: 'allow' })),
    { action: 'shell', resource: '*', effect: 'deny' },
    { action: 'external_directory', resource: '*', effect: 'deny' },
    ...external,
  ]
}

const normalizePath = value => String(value).replace(/\/\*$/, '').replace(/\/+$/, '')

/** True when `target` is `root` or lies below it. */
export function pathCovered(roots, target) {
  const value = normalizePath(target)
  return (roots || []).some(root => {
    const base = normalizePath(root)
    return value === base || value.startsWith(base + '/')
  })
}

/**
 * Decide what the permission hook should do with one evaluation.
 * Returns 'skip' for project-internal or relative paths, 'ask' when every
 * outside path is covered by the node's declared external scope, and 'deny'
 * otherwise. `external_directory` reports the directory boundary of a write,
 * so containment may hold in either direction.
 */
export function externalGate({ action, resources, external, projectRoot, effect }) {
  const outside = (resources || []).filter(value => value.startsWith('/') || value.startsWith('~'))
  if (!outside.length) return 'skip'
  if (outside.every(value => pathCovered([projectRoot], value))) return 'skip'
  const related = value => (external || []).some(root =>
    pathCovered([value], root) || pathCovered([root], value))
  const declared = action === 'external_directory'
    ? outside.every(related)
    : outside.every(value => pathCovered(external, value))
  if (!declared) return 'deny'
  // A saved "always" approval resolves the write to allow before this hook
  // runs; keep it and record a standing grant instead of asking again.
  return effect === 'allow' ? 'allow' : 'ask'
}

/** True when every outside resource is covered by a recorded "always" grant. */
export function grantCovers({ resources, grants }) {
  if (!grants || !grants.length) return false
  const related = value => grants.some(root =>
    pathCovered([value], root) || pathCovered([root], value))
  return (resources || []).every(value =>
    value.startsWith('/') || value.startsWith('~') ? related(value) : true)
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
