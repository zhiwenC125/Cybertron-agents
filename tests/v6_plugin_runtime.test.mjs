import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
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
  const sessionUpdates = [];
  const approvals = [];
  let approved = false;
  const ctx = {
    location: { project: { canonical: project } },
    storage: { get: async key => storage.get(key), set: async (key, value) => storage.set(key, value),
      remove: async key => storage.delete(key) },
    permission: { assert: async request => {
      approvals.push(request);
      if (!approved) throw new Error('human denied');
    } },
    session: {
      hook: async (name, fn) => sessionHooks.set(name, fn),
      get: async ({ sessionID }) => sessionID === 'child-1'
        ? { agent: 'alpha-trion', parentID: 'parent',
            permissions: sessionUpdates.at(-1)?.permissions.map(({ action, resource, effect }) =>
              ({ effect, resource, action })) }
        : sessionID === 'shell-child'
          ? { agent: 'solus-prime', parentID: 'parent', permissions: sessionUpdates.at(-1)?.permissions }
        : sessionID === 'preplan-child'
          ? { agent: 'thirteenth', parentID: 'preplan-parent' }
          : { agent: 'prima' },
      update: async value => sessionUpdates.push(value),
      switchModel: async () => undefined,
      wait: async () => undefined,
    },
    tool: {
      transform: async fn => fn({ add: tool => tools.set(tool.name, tool) }),
      hook: async (name, fn) => toolHooks.set(name, fn),
    },
  };
  await plugin.setup(ctx);
  // Pre-plan: prima may dispatch thirteenth before any run exists.
  await toolHooks.get('execute.before')({ tool: 'subagent', sessionID: 'preplan-parent',
    callID: 'plan-call', input: { description: 'Clarify intent and plan', agentID: 'thirteenth' } });
  const preplanTools = { cy_plan: {}, cy_templates: {}, question: {}, cy_state: {},
    cy_ask: {}, cy_metrics: {}, cy_check: {}, cy_review_reject: {}, subagent: {} };
  const preplanContext = { agent: 'thirteenth', sessionID: 'preplan-child',
    tools: preplanTools, system: [], model: { providerID: 'vendor', id: 'test' } };
  await sessionHooks.get('context')(preplanContext);
  assert.ok(preplanTools.cy_plan);
  assert.ok(preplanTools.question);
  assert.ok(preplanTools.cy_templates);
  assert.equal(preplanTools.subagent, undefined);
  const preplan = JSON.parse((await tools.get('cy_plan').execute({
    template: { type: 'read_only_scan', objective: 'Pre-plan handoff test' },
  }, { agent: 'thirteenth', sessionID: 'preplan-child' })).content);
  assert.equal(preplan.access_mode, 'read-only');
  const preplanAdopted = JSON.parse((await tools.get('cy_state').execute({},
    { agent: 'prima', sessionID: 'preplan-parent' })).content);
  assert.equal(preplanAdopted.run_id, preplan.run_id);
  assert.equal(preplanAdopted.handoff.next_agent, 'prima');
  const discovered = JSON.parse((await tools.get('cy_runs').execute({},
    { agent: 'prima', sessionID: 'resume-parent' })).content);
  assert.ok(discovered.runs.some(item => item.run_id === preplan.run_id));
  const resumed = JSON.parse((await tools.get('cy_resume').execute({ run_id: preplan.run_id },
    { agent: 'prima', sessionID: 'resume-parent' })).content);
  assert.equal(resumed.run_id, preplan.run_id);
  assert.equal(storage.get('run/resume-parent'), preplan.run_id);
  const shell = async event => toolHooks.get('execute.before')(event);
  await shell({ tool: 'shell', agent: 'vector-prime', sessionID: 'parent',
    input: { command: 'git show HEAD' } });
  await assert.rejects(shell({ tool: 'shell', agent: 'vector-prime', sessionID: 'parent',
    input: { command: 'git push' } }), /not allow-listed/);
  await assert.rejects(shell({ tool: 'shell', agent: 'vector-prime', sessionID: 'parent',
    input: { command: "sh -c 'rm -rf /'" } }), /not allow-listed/);
  await assert.rejects(shell({ tool: 'shell', agent: 'micronus-prime', sessionID: 'parent',
    input: { command: 'make all' } }), /not allow-listed/);
  await shell({ tool: 'shell', agent: 'nexus-prime', sessionID: 'parent',
    input: { command: 'openocd -f board.cfg' } });
  await assert.rejects(shell({ tool: 'shell', agent: 'prima', sessionID: 'parent',
    input: { command: 'git status' } }), /no shell allow-list/);
  assert.deepEqual([...tools.keys()], ['cy_plan', 'cy_state', 'cy_runs', 'cy_resume',
    'cy_ask', 'cy_new_run', 'cy_escalate',
    'cy_templates', 'cy_capabilities', 'cy_metrics', 'cy_shell', 'cy_check', 'cy_verify', 'cy_delete', 'cy_review_reject']);
  assert.deepEqual(tools.get('cy_plan').input.properties.nodes.items.properties.kind.enum,
    ['task', 'review', 'verify']);
  assert.deepEqual(tools.get('cy_plan').input.properties.node.properties.kind.enum,
    ['task', 'review', 'verify']);
  assert.ok(toolHooks.has('execute.before'));
  assert.ok(toolHooks.has('execute.after'));
  await assert.rejects(sessionHooks.get('context')({ agent: 'prima', tools: {}, system: [],
    model: { providerID: 'vendor', id: 'test' } }), /Native subagent tool is unavailable/);
  const context = { agent: 'prima', tools: { subagent: {}, cy_check: {} }, system: [],
    model: { providerID: 'vendor', id: 'test' } };
  await sessionHooks.get('context')(context);
  assert.equal(context.tools.cy_check, undefined);
  const mismatched = { agent: 'prima', tools: { subagent: {} }, system: [],
    model: { providerID: 'vendor', id: 'user-picked' } };
  await sessionHooks.get('context')(mismatched);
  const mismatchNote = mismatched.system.find(item => /differs from the configured Prima default/.test(item.text));
  assert.ok(mismatchNote);
  assert.match(mismatchNote.text, /user-picked/);
  assert.equal(context.tools.cy_plan, undefined);
  assert.match(context.system[0].text, /cy_state first/);
  assert.match(context.system[0].text, /cy_runs and cy_resume/);
  const planner = { agent: 'thirteenth', sessionID: 'planner',
    tools: { cy_plan: {}, cy_state: {}, cy_templates: {}, question: {}, subagent: {},
      cy_ask: {}, cy_metrics: {}, cy_check: {}, cy_review_reject: {} },
    system: [], model: { providerID: 'vendor', id: 'test' } };
  await sessionHooks.get('context')(planner);
  assert.ok(planner.tools.cy_plan);
  assert.ok(planner.tools.question);
  assert.equal(planner.tools.subagent, undefined);
  assert.match(planner.system[0].text, /submit clear requests directly/);
  const plannerPlan = JSON.parse((await tools.get('cy_plan').execute({
    template: { type: 'read_only_scan', objective: 'Planner handoff test' },
  }, { agent: 'thirteenth', sessionID: 'planner' })).content);
  assert.equal(plannerPlan.access_mode, 'read-only');
  await assert.rejects(tools.get('cy_state').execute({ wait: true },
    { agent: 'thirteenth', sessionID: 'planner' }), /prima owns wait/);
  const adopted = JSON.parse((await tools.get('cy_state').execute(
    {}, { agent: 'prima', sessionID: 'planner' })).content);
  assert.equal(adopted.run_id, plannerPlan.run_id);
  assert.deepEqual(tools.get('cy_plan').input.properties.template.properties.type.enum,
    ['bug_fix', 'read_only_scan']);
  await sessionHooks.get('prompt')({ sessionID: 'read-only-parent',
    prompt: { text: '请先准备一个只读检查计划，不要修改文件，先问我是否同意。' } });
  await assert.rejects(tools.get('cy_plan').execute({ node: {
    node_id: 'bad', kind: 'task', capability: 'doc.write', role: 'alpha-trion',
    objective: 'Write a report', write_scope: ['docs/report.md'],
    acceptance: ['report exists'], verifiers: ['scope_guard'],
  } }, { agent: 'thirteenth', sessionID: 'read-only-parent' }), /read-only/);
  const readonlyPlan = JSON.parse((await tools.get('cy_plan').execute({
    template: { type: 'read_only_scan', objective: 'Inspect the temporary directory layout' },
  }, { agent: 'thirteenth', sessionID: 'read-only-parent' })).content);
  assert.deepEqual(readonlyPlan.write_scope, []);
  assert.equal(readonlyPlan.access_mode, 'read-only');
  await sessionHooks.get('prompt')({ sessionID: 'full-parent',
    prompt: { text: '把 hello.c 写到桌面，允许项目外写入，使用完全权限。' } });
  const fullInput = {
    node: { node_id: 'hello', kind: 'task', capability: 'code.write', role: 'solus-prime',
      objective: 'Write hello.c to the Desktop', write_scope: ['Desktop/hello.c'],
      acceptance: ['hello.c exists'], verifiers: ['scope_guard'] },
  };
  await sessionHooks.get('prompt')({ sessionID: 'no-full-access',
    prompt: { text: '只写一个文件，不要使用完全权限。' } });
  const priorApprovals = approvals.length;
  await assert.rejects(tools.get('cy_plan').execute({ ...fullInput, access_mode: 'danger-full-access' },
    { agent: 'thirteenth', sessionID: 'no-full-access' }), /explicit request/);
  assert.equal(approvals.length, priorApprovals);
  await assert.rejects(tools.get('cy_plan').execute(fullInput,
    { agent: 'thirteenth', sessionID: 'full-parent' }), /human denied/);
  assert.equal(approvals.at(-1).action, 'cy_full_access_decision');
  approved = true;
  const fullPlan = JSON.parse((await tools.get('cy_plan').execute(fullInput,
    { agent: 'thirteenth', sessionID: 'full-parent' })).content);
  assert.equal(fullPlan.access_mode, 'danger-full-access');
  assert.match(readFileSync(fullPlan.events_path, 'utf8'), /approval.granted/);
  approved = false;
  await sessionHooks.get('prompt')({ sessionID: 'narrow-parent',
    prompt: { text: '帮我在桌面写一个 md 文件，只写这个文件，不要修改任何其他文件。' } });
  const approvalsBeforeNarrow = approvals.length;
  const narrowPlan = JSON.parse((await tools.get('cy_plan').execute({
    node: { node_id: 'note', kind: 'task', capability: 'doc.write', role: 'alpha-trion',
      objective: 'Write one requested file outside the project', write_scope: [],
      external_scope: [path.resolve(project, '..', 'requested-note.md')],
      acceptance: ['note exists'], verifiers: ['scope_guard'] },
  }, { agent: 'thirteenth', sessionID: 'narrow-parent' })).content);
  assert.equal(narrowPlan.access_mode, 'workspace-write');
  assert.equal(approvals.length, approvalsBeforeNarrow);
  assert.equal(readonlyPlan.nodes[0].role, 'onyx-prime');
  assert.equal(readonlyPlan.nodes[0].card, '[scan] scan.static | (read only)');
  const plan = JSON.parse((await tools.get('cy_plan').execute({ node: {
    node_id: 'n1', kind: 'task', capability: 'doc.write', role: 'alpha-trion',
    objective: 'Write notes.md', write_scope: ['notes.md'],
    acceptance: ['notes.md exists'], verifiers: ['scope_guard'],
  } }, { agent: 'thirteenth', sessionID: 'parent' })).content);
  assert.equal(plan.review_current, true);
  assert.equal(plan.adaptive_verification, true);
  assert.equal(tools.has('cy_plan_review'), false);
  await assert.rejects(tools.get('cy_plan').execute({},
    { agent: 'prima', sessionID: 'parent' }), /Only thirteenth/);
  await assert.rejects(tools.get('cy_ask').execute({ question: 'Confirm notes.md?' },
    { agent: 'prima', sessionID: 'parent', messageID: 'message-1', id: 'tool-1' }), /human denied/);
  assert.equal(readFileSync(JSON.parse((await tools.get('cy_state').execute({},
    { agent: 'prima', sessionID: 'parent' })).content).events_path, 'utf8').includes('human.requested'), false);
  approved = true;
  await tools.get('cy_ask').execute({ question: 'Confirm notes.md?' },
    { agent: 'prima', sessionID: 'parent', messageID: 'message-1', id: 'tool-1' });
  assert.equal(approvals.at(-1).action, 'cy_ask_decision');
  assert.deepEqual(approvals.at(-1).resources, ['Confirm notes.md?']);
  const approvedLog = readFileSync(JSON.parse((await tools.get('cy_state').execute({},
    { agent: 'prima', sessionID: 'parent' })).content).events_path, 'utf8');
  assert.match(approvedLog, /human.requested/);
  assert.match(approvedLog, /approval.granted/);
  const readonlyAsked = JSON.parse((await tools.get('cy_ask').execute({
    question: 'May I start the read-only scan?'
  }, { agent: 'prima', sessionID: 'read-only-parent', messageID: 'message-2', id: 'tool-2' })).content);
  assert.equal(readonlyAsked.run_id, readonlyPlan.run_id);
  assert.equal(readonlyAsked.status, 'ready');
  assert.match(readFileSync(readonlyAsked.events_path, 'utf8'), /human.requested/);
  await toolHooks.get('execute.after')({ tool: 'question', sessionID: 'parent', agent: 'prima',
    callID: 'question-1', status: 'completed',
    input: { questions: [{ header: 'Parser', question: 'Which parser?' }] },
    result: { metadata: { answers: [['native']] } } });
  const questionState = JSON.parse((await tools.get('cy_state').execute({},
    { agent: 'prima', sessionID: 'parent' })).content);
  const questionLog = readFileSync(questionState.events_path, 'utf8');
  assert.match(questionLog, /human.answered/);
  assert.match(questionLog, /native/);
  await assert.rejects(toolHooks.get('execute.before')({ tool: 'subagent', sessionID: 'parent',
    callID: 'bad-call', input: { description: 'bad card', agentID: 'alpha-trion' } }),
    /node card/);
  const event = { tool: 'subagent', sessionID: 'parent', callID: 'call-1',
    input: { description: plan.card, agentID: 'alpha-trion' } };
  await toolHooks.get('execute.before')(event);
  const activeDispatch = storage.get('dispatch/call-1');
  // A parallel rejection may have read the previous call's token before this
  // dispatch stored its own. It cannot replace a call-specific receipt.
  storage.set(`token/${plan.run_id}`, 'stale-run-token');
  await assert.rejects(toolHooks.get('execute.before')({ ...event, callID: 'call-2' }),
    /not ready/);
  assert.deepEqual(storage.get('dispatch/call-1'), activeDispatch);
  await toolHooks.get('execute.after')({ ...event, status: 'completed',
    result: { metadata: { sessionID: 'child-1' } } });
  await sessionHooks.get('context')({ agent: 'alpha-trion', sessionID: 'child-1',
    tools: {}, system: [], model: { providerID: 'vendor', id: 'test' } });
  assert.deepEqual(sessionUpdates[0].permissions.filter(rule => rule.action === 'edit'), [
    { action: 'edit', resource: '*', effect: 'deny' },
    { action: 'edit', resource: 'notes.md', effect: 'allow' },
  ]);
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
  await assert.rejects(tools.get('cy_review_reject').execute({
    affected_node_id: 'n1', diagnostic: 'finding',
  }, { agent: 'prima', sessionID: 'parent' }), /Only the L2 reviewer/);
  await assert.rejects(tools.get('cy_check').execute({ target: 'test' },
    { agent: 'nexus-prime', sessionID: 'child-1' }), /cannot run cy_check target test/);
  await assert.rejects(tools.get('cy_check').execute({ target: 'build' },
    { agent: 'nexus-prime', sessionID: 'child-1' }), /bound native verification child/);
  const child = storage.get('child/child-1');
  storage.set('child/child-1', { ...child, kind: 'review', planned_verification: true });
  const review = { agent: 'micronus-prime', sessionID: 'child-1',
    tools: { read: {}, cy_check: {}, shell: {} }, system: [] };
  await sessionHooks.get('context')(review);
  assert.deepEqual(Object.keys(review.tools), ['read']);
  assert.ok(review.system.some(item => /separate bound verify nodes/.test(item.text)));

  // A second run uses the same host hooks and needs only its implementation child.
  writeFileSync(path.join(project, 'pyproject.toml'), '[project]\nname = "fixture"\n');
  mkdirSync(path.join(project, 'tests'));
  writeFileSync(path.join(project, 'tests', 'test_notes.py'),
    'import unittest\nfrom pathlib import Path\nclass Notes(unittest.TestCase):\n'
    + '    def test_contents(self): self.assertEqual(Path("notes.md").read_text(), "updated notes")\n');
  const checked = JSON.parse((await tools.get('cy_plan').execute({ node: {
    node_id: 'n2', kind: 'task', capability: 'doc.write', role: 'alpha-trion',
    objective: 'Write notes.md and run the declared test',
    write_scope: ['notes.md'], acceptance: ['notes.md exists'],
    verifiers: ['scope_guard', 'test'], satisfies: ['recorded'],
  }, intent: { goal: 'Verify notes', confirmed: false, done: [
    { id: 'recorded', criterion: 'The fixed test passes', evidence: 'test' },
  ] } }, { agent: 'thirteenth', sessionID: 'parent' })).content);
  storage.delete('bound/child-1');
  const checkedDispatch = { ...event, callID: 'check-implementation',
    input: { ...event.input, description: checked.card } };
  await toolHooks.get('execute.before')(checkedDispatch);
  await toolHooks.get('execute.after')({ ...checkedDispatch, status: 'completed',
    result: { metadata: { sessionID: 'child-1' } } });
  await sessionHooks.get('context')({ agent: 'alpha-trion', sessionID: 'child-1',
    tools: {}, system: [], model: { providerID: 'vendor', id: 'test' } });
  writeFileSync(path.join(project, 'notes.md'), 'updated notes');
  const result = JSON.parse((await tools.get('cy_state').execute({ wait: true },
    { agent: 'prima', sessionID: 'parent' })).content);
  const sandboxAvailable = existsSync('/usr/bin/sandbox-exec');
  assert.equal(result.status, sandboxAvailable ? 'completed' : 'blocked');
  assert.equal(result.nodes.length, 1);
  assert.equal(result.intent_coverage[0].satisfied, sandboxAvailable);
  const inlineReceipt = readFileSync(result.events_path, 'utf8').trim().split('\n')
    .map(line => JSON.parse(line)).find(item => item.type === 'gate.check');
  assert.equal(inlineReceipt.inline, true);
  assert.equal(inlineReceipt.node_id, 'n2');
  assert.equal(inlineReceipt.status, sandboxAvailable ? 'pass' : 'unavailable');
  if (sandboxAvailable) assert.equal(inlineReceipt.receipt.exit, 0);

  await assert.rejects(tools.get('cy_shell').execute({ commands: [['make']] },
    { agent: 'solus-prime', sessionID: 'shell-child' }), /verified project child/);
  await assert.rejects(shell({ tool: 'shell', agent: 'solus-prime', sessionID: 'shell-child',
    input: { command: 'make all' } }), /use cy_shell/);
  if (sandboxAvailable) {
    mkdirSync(path.join(project, 'src'));
    writeFileSync(path.join(project, 'Makefile'), 'all:\n\tprintf ok > build/result.txt\n');
    const shellPlan = JSON.parse((await tools.get('cy_plan').execute({ node: {
      node_id: 'shell-code', kind: 'task', capability: 'code.write', role: 'solus-prime',
      objective: 'Check the build in a scratch workspace',
      write_scope: ['src/main.py'], acceptance: ['Make exits successfully'],
      verifiers: ['scope_guard'],
    } }, { agent: 'thirteenth', sessionID: 'parent' })).content);
    const shellDispatch = { ...event, callID: 'shell-build',
      input: { description: shellPlan.card, agentID: 'solus-prime' } };
    await toolHooks.get('execute.before')(shellDispatch);
    await toolHooks.get('execute.after')({ ...shellDispatch, status: 'completed',
      result: { metadata: { sessionID: 'shell-child' } } });
    const shellContext = { agent: 'solus-prime', sessionID: 'shell-child',
      tools: { cy_shell: {}, shell: {}, bash: {} }, system: [] };
    await sessionHooks.get('context')(shellContext);
    assert.deepEqual(Object.keys(shellContext.tools), ['cy_shell']);
    await assert.rejects(tools.get('cy_shell').execute({ commands: [['make']] },
      { agent: 'alchemist', sessionID: 'shell-child' }), /node and role/);
    approved = false;
    await assert.rejects(tools.get('cy_shell').execute({ commands: [['make']] },
      { agent: 'solus-prime', sessionID: 'shell-child' }), /human denied/);
    approved = true;
    const shellReceipt = JSON.parse((await tools.get('cy_shell').execute({ commands: [['make']] },
      { agent: 'solus-prime', sessionID: 'shell-child', messageID: 'build', id: 'cmd' })).content);
    assert.equal(approvals.at(-1).action, 'cy_shell');
    assert.equal(shellReceipt.status, 'pass');
    assert.equal(shellReceipt.receipts[0].exit, 0);
    assert.equal(existsSync(path.join(project, 'build')), false);
    const receiptEvent = readFileSync(shellPlan.events_path, 'utf8').trim().split('\n')
      .map(line => JSON.parse(line)).find(entry => entry.type === 'shell.executed');
    assert.equal(receiptEvent.call_id, 'shell-build');
    assert.equal(receiptEvent.receipts[0].sha256, shellReceipt.receipts[0].sha256);
    assert.equal(receiptEvent.source_intact, true);
  }
});
