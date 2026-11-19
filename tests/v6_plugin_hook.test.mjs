import assert from 'node:assert/strict';
import test from 'node:test';
import { nativeDispatch, childSession, nativeToolStatus, childPermissionRules, pathCovered, externalGate, grantCovers, runIsTerminal, reviewerPathDenied } from '../cybertron/v6_plugin/hook_logic.mjs';

test('native card binds node, capability, scope, role, and call', () => {
  assert.deepEqual(nativeDispatch({ input: { description: '[n1] doc.write | notes.md', agentID: 'alpha-trion' },
    callID: 'call-1' }), {
    nodeID: 'n1', capability: 'doc.write', writeScope: 'notes.md',
    role: 'alpha-trion', callID: 'call-1', card: '[n1] doc.write | notes.md',
  });
});

test('missing card, role, or call ID is rejected', () => {
  for (const event of [
    { input: { description: 'write notes', agentID: 'alpha-trion' }, callID: 'x' },
    { input: { description: '[n1] doc.write | notes.md' }, callID: 'x' },
    { input: { description: '[n1] doc.write | notes.md', agentID: 'alpha-trion' } },
  ]) assert.throws(() => nativeDispatch(event));
});

test('child session and cancellation semantics', () => {
  assert.equal(childSession({ metadata: { sessionID: 'child-1' } }), 'child-1');
  assert.equal(childSession({ content: '{"sessionID":"child-2"}' }), 'child-2');
  assert.equal(childSession({ content: 'background' }), null);
  assert.equal(nativeToolStatus({ status: 'completed' }), 'completed');
  assert.equal(nativeToolStatus({ status: 'error', error: { name: 'AbortError' } }), 'cancelled');
  assert.equal(nativeToolStatus({ status: 'error', error: { name: 'Other' } }), 'error');
});

test('workspace-write child rules allow project scope and ask for external paths', () => {
  const rules = childPermissionRules({
    accessMode: 'workspace-write',
    writeScope: ['docs/**'],
    externalScope: ['/tmp/report.md'],
  });
  const last = (action, resource) => [...rules].reverse()
    .find(rule => rule.action === action && rule.resource === resource);
  assert.deepEqual(last('edit', 'docs/**'), { action: 'edit', resource: 'docs/**', effect: 'allow' });
  assert.equal(last('external_directory', '/tmp/report.md').effect, 'ask');
  assert.equal(last('edit', '/tmp/report.md').effect, 'ask');
  assert.equal(last('edit', '*').effect, 'deny');
  assert.equal(last('shell', '*').effect, 'deny');
});

test('danger-full-access keeps the open rule set and ignores external scope', () => {
  const rules = childPermissionRules({ accessMode: 'danger-full-access', writeScope: [], externalScope: [] });
  assert.equal(rules[0].effect, 'allow');
  assert.equal(rules.find(rule => rule.action === 'external_directory').effect, 'allow');
  assert.equal(rules.find(rule => rule.resource === '.git/**').effect, 'deny');
});

test('pathCovered respects directory boundaries and comment wildcards', () => {
  assert.equal(pathCovered(['/tmp/x'], '/tmp/x/report.md'), true);
  assert.equal(pathCovered(['/tmp/x'], '/tmp/x'), true);
  assert.equal(pathCovered(['/tmp/x'], '/tmp/xy/report.md'), false);
  assert.equal(pathCovered(['/tmp/x'], '/tmp/x/*'), true);
});

test('external gate skips project paths and gates only declared outside paths', () => {
  const projectRoot = '/work/project';
  const external = ['/Users/x/Desktop/report.md'];
  assert.equal(externalGate({ action: 'edit', resources: ['docs/a.md'], external, projectRoot }), 'skip');
  assert.equal(externalGate({ action: 'edit', resources: ['/work/project/docs/a.md'], external, projectRoot }), 'skip');
  assert.equal(externalGate({ action: 'edit', resources: ['/Users/x/Desktop/report.md'], external, projectRoot }), 'ask');
  assert.equal(externalGate({ action: 'edit', resources: ['/Users/x/Desktop/other.md'], external, projectRoot }), 'deny');
  assert.equal(externalGate({ action: 'external_directory', resources: ['/Users/x/Desktop/*'], external, projectRoot }), 'ask');
  assert.equal(externalGate({ action: 'edit', resources: ['/Users/x/Desktop/report.md'],
    external, projectRoot, effect: 'allow' }), 'allow');
  assert.equal(externalGate({ action: 'edit', resources: ['/Users/x/Desktop/other.md'],
    external, projectRoot, effect: 'allow' }), 'deny');
});

test('standing grants cover later writes in the same declared scope', () => {
  const grants = ['/Users/x/Desktop/report.md'];
  assert.equal(grantCovers({ resources: ['/Users/x/Desktop/report.md'], grants }), true);
  assert.equal(grantCovers({ resources: ['/Users/x/Desktop/other.md'], grants }), false);
  assert.equal(grantCovers({ resources: ['docs/a.md'], grants }), true);
  assert.equal(grantCovers({ resources: ['/Users/x/Desktop/report.md'], grants: [] }), false);
});

test('only a completed run frees the session for a new plan', () => {
  assert.equal(runIsTerminal({ status: 'completed' }), true);
  assert.equal(runIsTerminal({ status: 'ready' }), false);
  assert.equal(runIsTerminal({ status: 'running' }), false);
  assert.equal(runIsTerminal({ status: 'blocked' }), false);
  assert.equal(runIsTerminal({ status: 'superseded' }), true);
  assert.equal(runIsTerminal(null), false);
  assert.equal(reviewerPathDenied('.env'), true);
  assert.equal(reviewerPathDenied('.ssh/id_rsa'), true);
  assert.equal(reviewerPathDenied('.git/config'), true);
  assert.equal(reviewerPathDenied('services/auth/a.py'), false);
});
