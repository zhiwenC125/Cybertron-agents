import assert from 'node:assert/strict';
import test from 'node:test';
import { nativeDispatch, childSession, nativeToolStatus } from '../cybertron/v6_plugin/hook_logic.mjs';

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
