import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { callBridge, hostIdOf, jsonResult, pythonPathRoots } from '../cybertron/dsh_adapter/bridge.js'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
process.env.PYTHONPATH = [root, process.env.PYTHONPATH].filter(Boolean).join(':')

const NODE = {
  node_id: 'n1', kind: 'task', capability: 'doc.write', role: 'alpha-trion',
  objective: 'Write notes.md', write_scope: ['notes.md'],
  acceptance: ['notes.md exists'], verifiers: ['scope_guard'],
}

test('bridge lists templates and creates a validated run in a temporary project', async () => {
  const project = mkdtempSync(path.join(os.tmpdir(), 'cybertron-dsh-bridge-'))
  try {
    const empty = await callBridge('templates', project, {}, undefined, { python: 'python3' })
    assert.deepEqual(empty.templates, [])
    const plan = await callBridge('plan', project,
      { node: NODE, host_session_id: 'dsh-test', request_class: 'doc-single',
        objective: 'Write notes.md' }, undefined, { python: 'python3' })
    assert.equal(plan.status, 'ready')
    assert.equal(plan.ready_nodes[0], 'n1')
    assert.equal(plan.request_class, 'doc-single')
    const state = await callBridge('state', project, { run_id: plan.run_id },
      undefined, { python: 'python3' })
    assert.equal(state.run_id, plan.run_id)
    assert.deepEqual(state.ready_nodes, ['n1'])
    const metrics = await callBridge('metrics', project, {}, undefined, { python: 'python3' })
    assert.equal(metrics.summary.runs, 1)
  } finally {
    rmSync(project, { recursive: true, force: true })
  }
})

test('bridge rejects an invalid plan instead of guessing', async () => {
  const project = mkdtempSync(path.join(os.tmpdir(), 'cybertron-dsh-bridge-'))
  try {
    await assert.rejects(
      callBridge('plan', project,
        { node: { ...NODE, role: 'prima' }, host_session_id: 'dsh-test' },
        undefined, { python: 'python3' }),
      /error|capability|role/i,
    )
  } finally {
    rmSync(project, { recursive: true, force: true })
  }
})

test('transport helpers are deterministic', () => {
  assert.equal(jsonResult({ a: 1 }), '{"a":1}')
  assert.equal(hostIdOf({ agent: { id: 'agent-7' } }), 'agent-7')
  assert.equal(hostIdOf({ agent: { session: { id: 'ses-1' } } }), 'ses-1')
  assert.equal(hostIdOf({}), 'dsh')
})


test('registers the five cy tools without importing DSH internals', async () => {
  const { apply } = await import('../cybertron/dsh_adapter/index.js');
  const tools = new Map();
  const ctx = {
    tools: { register: tool => tools.set(tool.name, tool) },
    workingDirectory: { ensure: async () => process.cwd() },
  };
  apply(ctx, { python: process.execPath });
  assert.deepEqual([...tools.keys()], ['cy_plan', 'cy_state', 'cy_ask', 'cy_templates', 'cy_metrics']);
  for (const tool of tools.values()) {
    assert.equal(typeof tool.execute, 'function');
    assert.equal(typeof tool.description, 'string');
  }
});


test('resolves the bundled Python runtime without ambient PYTHONPATH', async () => {
  const project = mkdtempSync(path.join(os.tmpdir(), 'cybertron-dsh-runtime-'))
  const previous = process.env.PYTHONPATH
  delete process.env.PYTHONPATH
  try {
    assert.ok(pythonPathRoots(project).some(root => root.endsWith('cybertron') || root.endsWith('cybertron-runtime')))
    const empty = await callBridge('templates', project, {}, undefined, { python: 'python3' })
    assert.deepEqual(empty.templates, [])
  } finally {
    if (previous !== undefined) process.env.PYTHONPATH = previous
    rmSync(project, { recursive: true, force: true })
  }
})
