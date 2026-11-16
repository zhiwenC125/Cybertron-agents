import { Plugin } from '@opencode/plugin';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { nativeDispatch, childSession, nativeToolStatus } from './hook_logic.mjs';

const pluginDirectory = path.dirname(fileURLToPath(import.meta.url));
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

function runtimePath() {
  const bundled = path.resolve(pluginDirectory, '..', 'cybertron-runtime');
  if (existsSync(path.join(bundled, 'cybertron', 'host_v6_cli.py'))) return bundled;
  const checkout = path.resolve(pluginDirectory, '..', '..');
  if (existsSync(path.join(checkout, 'cybertron', 'host_v6_cli.py'))) return checkout;
  throw new Error('Cybertron v6 Python runtime is missing; rebuild the payload');
}

function primaryModel(project) {
  const configHome = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config');
  const local = path.join(project, '.cybertron', 'models.json');
  const global = path.join(configHome, 'cybertron', 'models.json');
  const file = existsSync(local) ? local : global;
  if (!existsSync(file)) return null;
  const profile = JSON.parse(readFileSync(file, 'utf8'));
  if (profile.schema_version !== 1 || typeof profile.agents?.prima !== 'string') {
    throw new Error('Cybertron model profile is invalid; run cybertron models doctor');
  }
  const separator = profile.agents.prima.indexOf('/');
  if (separator < 1) throw new Error('Cybertron prima model ID is invalid');
  const providerID = profile.agents.prima.slice(0, separator);
  const rest = profile.agents.prima.slice(separator + 1);
  const variantSeparator = rest.lastIndexOf('#');
  const id = variantSeparator < 0 ? rest : rest.slice(0, variantSeparator);
  const variant = variantSeparator < 0 ? undefined : rest.slice(variantSeparator + 1);
  return { providerID, id, ...(variant ? { variant } : {}) };
}

function bridge(operation, project, payload, signal) {
  return new Promise((resolve, reject) => {
    const runtime = runtimePath();
    const child = spawn(process.env.CYBERTRON_PYTHON || 'python3',
      ['-m', 'cybertron.host_v6_cli', operation, '--project', project], {
        cwd: runtime, shell: false, signal,
        env: { ...process.env, PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', reject);
    child.on('close', code => {
      let result;
      try { result = JSON.parse(stdout); } catch { result = null; }
      if (code !== 0) return reject(new Error(result?.error || stderr.slice(-500) || 'Cybertron host bridge failed'));
      if (!result) return reject(new Error('Cybertron host bridge returned invalid JSON'));
      resolve(result);
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

const nodeInput = {
  type: 'object',
  properties: {
    node_id: { type: 'string' }, kind: { type: 'string', enum: ['task'] },
    capability: { type: 'string' }, role: { type: 'string' }, objective: { type: 'string' },
    depends_on: { type: 'array', items: { type: 'string' } },
    read_scope: { type: 'array', items: { type: 'string' } },
    write_scope: { type: 'array', items: { type: 'string' } },
    acceptance: { type: 'array', items: { type: 'string' } },
    verifiers: { type: 'array', items: { type: 'string' } },
  },
  required: ['node_id', 'kind', 'capability', 'role', 'objective', 'write_scope', 'acceptance', 'verifiers'],
  additionalProperties: false,
};

export default Plugin.define({
  id: 'cybertron.v6.runtime',
  async setup(ctx) {
    const project = ctx.location.project.canonical;
    await ctx.session.hook('prompt', async event => {
      const selected = await ctx.session.get({ sessionID: event.sessionID });
      if (selected.agent === 'prima') {
        const model = primaryModel(project);
        if (model) await ctx.session.switchModel({ sessionID: event.sessionID, model });
      }
    });
    await ctx.tool.transform(editor => {
      editor.add({
        name: 'cy_plan', description: 'Create a validated v6 task graph, use the optional bug_fix plan seed, or apply one revisioned graph operation. Returns ready native subagent cards.',
        input: { type: 'object', properties: {
          node: nodeInput, nodes: { type: 'array', items: nodeInput, minItems: 1 },
          template: { type: 'object', properties: {
            type: { type: 'string', enum: ['bug_fix'] }, objective: { type: 'string' },
            write_scope: { type: 'array', items: { type: 'string' }, minItems: 1 },
          }, required: ['type', 'objective', 'write_scope'], additionalProperties: false },
          operation: { type: 'object', additionalProperties: true },
        }, additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may create plans');
          const run_id = await ctx.storage.get(`run/${context.sessionID}`);
          if (run_id && (input.node || input.nodes || input.template || !input.operation))
            throw new Error('Existing run requires one graph operation');
          if (!run_id && ([input.node, input.nodes, input.template].filter(Boolean).length !== 1 || input.operation))
            throw new Error('New run requires exactly one node, nodes, or template');
          const result = run_id
            ? await bridge('plan_op', project, { run_id, operation: input.operation }, context.signal)
            : await bridge('plan', project, { node: input.node, nodes: input.nodes,
                template: input.template,
                host_session_id: context.sessionID }, context.signal);
          if (!run_id) await ctx.storage.set(`run/${context.sessionID}`, result.run_id);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_state', description: 'Read the v6 run; wait for the native child to finish before settling the node.',
        input: { type: 'object', properties: { wait: { type: 'boolean' } }, additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may read the run state');
          const run_id = await ctx.storage.get(`run/${context.sessionID}`);
          if (!run_id) throw new Error('No v6 run in this session; call cy_plan first');
          let state = await bridge('state', project, { run_id }, context.signal);
          if (input.wait && state.status === 'running' && state.child_session_id) {
            await ctx.session.wait({ sessionID: state.child_session_id });
            const token = await ctx.storage.get(`token/${run_id}`);
            state = await bridge('finish', project,
              { run_id, token, child_session_id: state.child_session_id }, context.signal);
          }
          return { content: JSON.stringify(state) };
        },
      });
      editor.add({
        name: 'cy_ask', description: 'Record a question that requires a human answer.',
        input: { type: 'object', properties: { question: { type: 'string' } },
          required: ['question'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may request human input');
          const run_id = await ctx.storage.get(`run/${context.sessionID}`);
          if (!run_id) throw new Error('No v6 run in this session');
          const result = await bridge('ask', project, { run_id, question: input.question }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_check', description: 'Run a fixed lint, build, or test target in an isolated project copy and return tool receipts.',
        input: { type: 'object', properties: {
          target: { type: 'string', enum: ['lint', 'build', 'test'] },
          run_id: { type: 'string' },
        }, required: ['target'], additionalProperties: false },
        execute: async (input, context) => {
          const allowed = new Set(['micronus-prime', 'nexus-prime', 'alchemist',
            'solus-prime', 'amalgamous', 'vector-prime']);
          if (!allowed.has(context.agent)) throw new Error('This role cannot run cy_check');
          const result = await bridge('check', project,
            { target: input.target, run_id: input.run_id }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
    });
    await ctx.tool.hook('execute.before', async event => {
      if (event.tool !== 'subagent') return;
      const parent = await ctx.session.get({ sessionID: event.sessionID });
      if (parent.agent !== 'prima') throw new Error('Only prima may dispatch a native subagent');
      const run_id = await ctx.storage.get(`run/${event.sessionID}`);
      if (!run_id) throw new Error('No ready Cybertron node; call cy_plan first');
      const { nodeID, role, callID, card } = nativeDispatch(event);
      const active_token = await ctx.storage.get(`token/${run_id}`);
      const result = await bridge('before', project,
        { run_id, node_id: nodeID, role, card, call_id: callID, active_token });
      if (result.rejected) {
        await ctx.storage.set(`token/${run_id}`, result.token);
        const active_call = await ctx.storage.get(`active/${run_id}`);
        if (active_call) {
          const active = await ctx.storage.get(`dispatch/${active_call}`);
          if (active) await ctx.storage.set(`dispatch/${active_call}`, { ...active, token: result.token });
        }
        throw new Error(result.reason);
      }
      await ctx.storage.set(`dispatch/${callID}`, { run_id, token: result.token,
        started_ms: Date.now(), parent_session_id: event.sessionID });
      await ctx.storage.set(`active/${run_id}`, callID);
      await ctx.storage.set(`token/${run_id}`, result.token);
    });
    await ctx.tool.hook('execute.after', async event => {
      if (event.tool !== 'subagent') return;
      const call_id = event.callID || event.id || event.toolCallID;
      const started = call_id ? await ctx.storage.get(`dispatch/${call_id}`) : null;
      if (!started) return; // A rejected before-hook has no dispatch to settle.
      const child_session_id = childSession(event.result);
      const tool_status = nativeToolStatus(event);
      const result = await bridge('after', project, {
        run_id: started.run_id, call_id, token: started.token, child_session_id,
        tool_status, duration_ms: Math.max(0, Date.now() - started.started_ms),
        output_sha256: digest(event.result || event.error?.message || ''),
      });
      await ctx.storage.set(`token/${started.run_id}`, result.token);
    });
    await ctx.session.hook('context', event => {
      if (event.agent !== 'prima') {
        delete event.tools.cy_state;
        delete event.tools.cy_plan;
        delete event.tools.cy_ask;
        delete event.tools.subagent;
        if (!['micronus-prime', 'nexus-prime', 'alchemist', 'solus-prime',
          'amalgamous', 'vector-prime'].includes(event.agent)) delete event.tools.cy_check;
        return;
      }
      delete event.tools.cy_check;
      const expected = primaryModel(project);
      if (expected && (event.model.providerID !== expected.providerID ||
          event.model.id !== expected.id || event.model.variant !== expected.variant)) {
        throw new Error('Cybertron prima model differs from active session; run cybertron models doctor');
      }
      event.system.push({ type: 'text', text:
        'Cybertron v6 M2: plan the smallest valid task graph for the user request with cy_plan. Use node for one task, nodes for a dependency graph, or the optional bug_fix template. For a single requested Markdown file within alpha-trion allowed paths, use capability doc.write, role alpha-trion, write_scope containing only that path, and scope_guard verifier; keep the requested content exact. Each task needs a registered capability and role, narrow write_scope, acceptance, and scope_guard verifier. Dispatch only a ready node through the native subagent tool; use its exact returned card as description and include node_id, capability, write_scope, objective, and run_id in the child prompt. Call cy_state with wait=true after each child returns. The kernel derives risk gates from the actual workspace diff; cy_check runs fixed lint/build/test targets for eligible roles, and a run_id binds its receipt to the run. Required gates cannot be removed; mark_not_applicable and complete_run remain fail-closed until trusted verifier facts exist. Background is still running; cancellation is terminal. Never claim model text as tool evidence.' });
    });
  },
});
