import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { registerHooks } from 'node:module';
import test from 'node:test';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === '@opencode/plugin') {
      return { url: 'data:text/javascript,export const Plugin={define:value=>value}', shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

const plugin = (await import('../cybertron/v6_plugin/cybertron.js')).default;

test('plugin registers native hooks and rejects invalid dispatch visibly', async () => {
  const project = mkdtempSync(path.join(tmpdir(), 'cybertron-plugin-test-'));
  mkdirSync(path.join(project, '.cybertron'));
  writeFileSync(path.join(project, '.cybertron', 'models.json'),
    JSON.stringify({ schema_version: 1, agents: { prima: 'vendor/test' } }));
  const storage = new Map();
  const tools = new Map();
  const toolHooks = new Map();
  const sessionHooks = new Map();
  const ctx = {
    location: { project: { canonical: project } },
    storage: { get: async key => storage.get(key), set: async (key, value) => storage.set(key, value) },
    session: {
      hook: async (name, fn) => sessionHooks.set(name, fn),
      get: async () => ({ agent: 'prima' }),
      wait: async () => undefined,
    },
    tool: {
      transform: async fn => fn({ add: tool => tools.set(tool.name, tool) }),
      hook: async (name, fn) => toolHooks.set(name, fn),
    },
  };
  await plugin.setup(ctx);
  assert.deepEqual([...tools.keys()], ['cy_plan', 'cy_state', 'cy_ask', 'cy_check']);
  assert.ok(toolHooks.has('execute.before'));
  assert.ok(toolHooks.has('execute.after'));
  const context = { agent: 'prima', tools: {}, system: [],
    model: { providerID: 'vendor', id: 'test' } };
  await sessionHooks.get('context')(context);
  assert.equal(context.tools.cy_check, undefined);
  assert.match(context.system[0].text, /single requested Markdown file/);
  assert.match(context.system[0].text, /doc\.write.*alpha-trion.*write_scope.*scope_guard/);
  const plan = JSON.parse((await tools.get('cy_plan').execute({ node: {
    node_id: 'n1', kind: 'task', capability: 'doc.write', role: 'alpha-trion',
    objective: 'Write notes.md', write_scope: ['notes.md'],
    acceptance: ['notes.md exists'], verifiers: ['scope_guard'],
  } }, { agent: 'prima', sessionID: 'parent' })).content);
  await assert.rejects(toolHooks.get('execute.before')({ tool: 'subagent', sessionID: 'parent',
    callID: 'bad-call', input: { description: 'bad card', agentID: 'alpha-trion' } }),
    /node card/);
  const event = { tool: 'subagent', sessionID: 'parent', callID: 'call-1',
    input: { description: plan.card, agentID: 'alpha-trion' } };
  await toolHooks.get('execute.before')(event);
  await assert.rejects(toolHooks.get('execute.before')({ ...event, callID: 'call-2' }),
    /not ready/);
  await toolHooks.get('execute.after')({ ...event, status: 'completed',
    result: { metadata: { sessionID: 'child-1' } } });
  assert.equal(JSON.parse((await tools.get('cy_state').execute({},
    { agent: 'prima', sessionID: 'parent' })).content).status, 'running');
  writeFileSync(path.join(project, 'notes.md'), 'done');
  const settled = JSON.parse((await tools.get('cy_state').execute({ wait: true },
    { agent: 'prima', sessionID: 'parent' })).content);
  assert.equal(settled.status, 'completed');
  const eventLog = readFileSync(settled.events_path, 'utf8');
  assert.match(eventLog, /plan.op.rejected/);
  assert.match(eventLog, /node.completed/);
  await assert.rejects(tools.get('cy_check').execute({ target: 'build' },
    { agent: 'prima', sessionID: 'parent' }), /cannot run cy_check/);
  writeFileSync(path.join(project, 'CMakeLists.txt'),
    'cmake_minimum_required(VERSION 3.20)\nproject(hello C)\nadd_executable(hello main.c)\n');
  writeFileSync(path.join(project, 'main.c'), 'int main(void){return 0;}\n');
  const check = JSON.parse((await tools.get('cy_check').execute({ target: 'build' },
    { agent: 'nexus-prime', sessionID: 'child-1' })).content);
  assert.equal(check.status, 'pass');
  assert.match(check.receipts.at(-1).command, /cmake --build build/);
});
