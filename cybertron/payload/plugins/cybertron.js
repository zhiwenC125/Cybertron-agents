import { Plugin } from '@opencode/plugin';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { nativeDispatch, childSession, nativeToolStatus, childPermissionRules, externalGate, grantCovers } from './hook_logic.mjs';
import shellPolicy from './shell_policy.mjs';

const pluginDirectory = path.dirname(fileURLToPath(import.meta.url));
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const globToRegExp = pattern => {
  let source = '^';
  for (const char of pattern) {
    if (char === '*') source += '.*';
    else if (char === '?') source += '.';
    else source += char.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp(source + '$');
};
const shellVerdict = (policy, command) => {
  const match = pattern => globToRegExp(pattern).test(command);
  if ((policy.deny || []).some(match)) return 'deny';
  if ((policy.allow || []).some(match) || (policy.ask || []).some(match)) return 'allow';
  return 'unlisted';
};
const noWriteRequested = text => /只读|不(?:要|得)?(?:创建|修改|删除|写入).*文件|read[- ]only|do not (?:write|modify|create|delete) (?:any )?files?/i.test(text);
const writeNowRequested = text => /(?:允许|可以|同意)(?:现在|继续)?(?:写入|修改|创建).*文件|(?:you may|please) (?:write|modify|create) (?:the )?files?/i.test(text);
const fullAccessRequested = text =>
  /完全权限|full access|danger[- ]full[- ]access|越出(?:当前)?项目|outside (?:the )?project|(?:允许|可以|同意).*(?:项目外|桌面|下载|任意|所有|外部).*(?:文件|路径|目录)|write (?:to )?(?:the )?(?:desktop|downloads|outside)/i.test(text)
  || /(?:写到|创建|保存到|放到|写入).*(?:桌面|Desktop|下载|Downloads)|(?:桌面|Desktop|下载|Downloads).*(?:写|创建|保存|放)/i.test(text);

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
    node_id: { type: 'string' }, kind: { type: 'string', enum: ['task', 'review'] },
    capability: { type: 'string' }, role: { type: 'string' }, objective: { type: 'string' },
    depends_on: { type: 'array', items: { type: 'string' } },
    read_scope: { type: 'array', items: { type: 'string' } },
    write_scope: { type: 'array', items: { type: 'string' } },
    external_scope: { type: 'array', items: { type: 'string' } },
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
        const prompt = event.prompt?.text || '';
        if (noWriteRequested(prompt)) {
          await ctx.storage.set(`read-only/${event.sessionID}`, true);
          await ctx.storage.set(`access/${event.sessionID}`, 'read-only');
        } else if (fullAccessRequested(prompt)) {
          await ctx.storage.set(`read-only/${event.sessionID}`, false);
          await ctx.storage.set(`access/${event.sessionID}`, 'danger-full-access');
        } else if (writeNowRequested(prompt)) {
          await ctx.storage.set(`read-only/${event.sessionID}`, false);
          if (await ctx.storage.get(`access/${event.sessionID}`) === 'read-only')
            await ctx.storage.set(`access/${event.sessionID}`, 'workspace-write');
        } else if (!await ctx.storage.get(`access/${event.sessionID}`)) {
          await ctx.storage.set(`access/${event.sessionID}`, 'workspace-write');
        }
        const model = primaryModel(project);
        if (model) {
          const sameModel = (left, right) => left && right
            && left.providerID === right.providerID && left.id === right.id
            && (left.variant || undefined) === (right.variant || undefined);
          const selectedModel = selected.model;
          const lastAuto = await ctx.storage.get(`model/auto/${event.sessionID}`);
          // Respect a model the user explicitly picked in OpenCode. The
          // configured Prima model is a default, not a hard override.
          const userPicked = selectedModel && !sameModel(selectedModel, model)
            && !sameModel(selectedModel, lastAuto);
          if (!userPicked) {
            try {
              await ctx.session.switchModel({ sessionID: event.sessionID, model });
              await ctx.storage.set(`model/auto/${event.sessionID}`, model);
            } catch (error) {
              console.warn(`Cybertron: could not switch to configured Prima model: ${error.message}`);
            }
          } else {
            await ctx.storage.set(`model/override/${event.sessionID}`, selectedModel);
          }
        }
      }
    });
    await ctx.tool.transform(editor => {
      editor.add({
        name: 'cy_plan', description: 'Create a validated v6 task graph. For a read-only inspection use template {type:"read_only_scan",objective:"..."} (write_scope=[]). For fixes use bug_fix or explicit nodes. Pass access_mode read-only/workspace-write/danger-full-access. Under workspace-write, list intended outside paths in the node external_scope; each write then needs a host approval (once/always/reject). Use danger-full-access only for explicit blanket authorization of Desktop/Downloads/outside paths. Pass an English slug for the on-disk run folder. Returns ready native subagent cards.',
        input: { type: 'object', properties: {
          node: nodeInput, nodes: { type: 'array', items: nodeInput, minItems: 1 },
          template: { type: 'object', properties: {
            type: { type: 'string', enum: ['bug_fix', 'read_only_scan'] }, objective: { type: 'string' },
            write_scope: { type: 'array', items: { type: 'string' }, minItems: 1 },
          }, required: ['type', 'objective'], additionalProperties: false },
          template_id: { type: 'string' },
          objective: { type: 'string' },
          slug: { type: 'string' },
          write_scope: { type: 'array', items: { type: 'string' } },
          test_scope: { type: 'array', items: { type: 'string' } },
          skip: { type: 'array', items: { type: 'string' } },
          request_class: { type: 'string' },
          access_mode: { type: 'string', enum: ['read-only', 'workspace-write', 'danger-full-access'] },
          operation: { type: 'object', properties: {
            op: { type: 'string', enum: ['add_node', 'add_edge', 'reassign_role', 'split_node',
              'retry_node', 'insert_gate', 'mark_not_applicable', 'request_human', 'complete_run'] },
            op_id: { type: 'string' },
            plan_revision: { type: 'integer' },
          }, required: ['op', 'op_id', 'plan_revision'], additionalProperties: true },
        }, additionalProperties: false },
        execute: async (input, context) => {
          if (!['prima', 'thirteenth'].includes(context.agent))
            throw new Error('Only thirteenth may author plans; prima only dispatches');
          const run_id = await ctx.storage.get(`run/${context.sessionID}`);
          const session = await ctx.session.get({ sessionID: context.sessionID });
          let access_mode = input.access_mode || await ctx.storage.get(`access/${context.sessionID}`) || 'workspace-write';
          if (input.template?.type === 'read_only_scan') access_mode = 'read-only';
          if (run_id && (input.node || input.nodes || input.template || input.template_id || !input.operation))
            throw new Error('Existing run requires one graph operation');
          if (!run_id && ([input.node, input.nodes, input.template, input.template_id].filter(Boolean).length !== 1 || input.operation))
            throw new Error('New run requires exactly one node, nodes, template, or template_id');
          if (input.template_id && !input.objective)
            throw new Error('A template seed requires the new objective');
          if (input.skip && !input.template_id)
            throw new Error('skip is only valid with a template seed');
          if (input.template?.type === 'bug_fix' && !input.template.write_scope?.length)
            throw new Error('bug_fix requires write_scope');
          if (input.template?.type === 'read_only_scan' &&
              (input.template.write_scope?.length || input.write_scope?.length))
            throw new Error('read_only_scan cannot have write_scope');
          if (access_mode === 'read-only' &&
              (input.node?.write_scope?.length || input.nodes?.some(node => node.write_scope?.length) ||
               input.template?.type === 'bug_fix' || input.template_id || input.write_scope?.length ||
               (input.operation && input.operation.op !== 'request_human')))
            throw new Error('This session is read-only; cy_plan cannot create or revise a writing node');
          const result = run_id
            ? await bridge('plan_op', project, { run_id, operation: input.operation }, context.signal)
            : await bridge('plan', project, { node: input.node, nodes: input.nodes,
                template: input.template, template_id: input.template_id,
                objective: input.objective, write_scope: input.write_scope,
                test_scope: input.test_scope, skip: input.skip,
                request_class: input.request_class,
                access_mode, session_title: session?.title || input.objective || '',
                slug: input.slug || '', host_session_id: context.sessionID,
                host: 'opencode' }, context.signal);
          if (!run_id) {
            await ctx.storage.set(`run/${context.sessionID}`, result.run_id);
            // A planning child gives the parent its run id, so prima can adopt
            // the plan without the human copying the id between agents.
            if (session?.parentID)
              await ctx.storage.set(`run/${session.parentID}`, result.run_id);
          }
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_plan_review',
        description: 'Review the current plan revision before dispatch. Records plan.reviewed with deterministic feasibility findings; prima must call this on the current revision before the first subagent dispatch.',
        input: { type: 'object', properties: {
          run_id: { type: 'string', description: 'Optional run id to adopt and review.' },
        }, additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may review a plan');
          let run_id = await ctx.storage.get(`run/${context.sessionID}`);
          if (input.run_id !== undefined) {
            if (typeof input.run_id !== 'string' || !input.run_id.trim())
              throw new Error('run_id must be a non-empty string');
            run_id = input.run_id.trim();
            await ctx.storage.set(`run/${context.sessionID}`, run_id);
          }
          if (!run_id) throw new Error('No v6 run in this session; ask thirteenth for the run_id');
          const result = await bridge('review_plan', project, { run_id }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_state', description: 'Read the v6 run; wait for the native child to finish before settling the node.',
        input: { type: 'object', properties: {
          wait: { type: 'boolean' },
          run_id: { type: 'string', description: 'Adopt a run created by thirteenth in another session.' },
        }, additionalProperties: false },
        execute: async (input, context) => {
          if (!['prima', 'thirteenth'].includes(context.agent))
            throw new Error('Only prima may settle and thirteenth may read the run state');
          if (context.agent === 'thirteenth' && input.wait)
            throw new Error('The planner may read the run but prima owns wait/settle');
          let run_id = await ctx.storage.get(`run/${context.sessionID}`);
          if (input.run_id !== undefined) {
            if (typeof input.run_id !== 'string' || !input.run_id.trim())
              throw new Error('run_id must be a non-empty string');
            run_id = input.run_id.trim();
            await ctx.storage.set(`run/${context.sessionID}`, run_id);
          }
          if (!run_id) throw new Error(context.agent === 'thirteenth'
            ? 'No v6 run in this session; call cy_plan first'
            : 'No v6 run in this session; ask thirteenth for the run_id');
          let state = await bridge('state', project, { run_id }, context.signal);
          if (input.wait && state.status === 'running') {
            for (const active of state.active_dispatches || []) {
              if (!active.child_session_id) continue;
              await ctx.session.wait({ sessionID: active.child_session_id });
              const dispatch = await ctx.storage.get(`dispatch/${active.call_id}`);
              if (!dispatch) throw new Error('Missing bound native dispatch receipt');
              state = await bridge('finish', project,
                { run_id, token: dispatch.token, call_id: active.call_id,
                  child_session_id: active.child_session_id }, context.signal);
            }
          }
          return { content: JSON.stringify(state) };
        },
      });
      editor.add({
        name: 'cy_ask', description: 'Formal host approval gate for one yes/no decision. Prefer the native question tool for user questions; this opens the OpenCode permission card and records approval.granted in the run ledger.',
        input: { type: 'object', properties: { question: { type: 'string' } },
          required: ['question'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may request human input');
          const run_id = await ctx.storage.get(`run/${context.sessionID}`);
          if (!run_id) throw new Error('No v6 run in this session');
          if (typeof input.question !== 'string' || !input.question.trim())
            throw new Error('question is required');
          const state = await bridge('state', project, { run_id }, context.signal);
          if (state.status === 'running')
            throw new Error('cannot request human input during an active dispatch');
          await ctx.permission.assert({
            sessionID: context.sessionID, agent: context.agent,
            source: { type: 'tool', messageID: context.messageID, id: context.id },
            action: 'cy_ask_decision', resources: [input.question.trim()],
            metadata: { question: input.question.trim(), run_id },
          });
          const result = await bridge('ask', project,
            { run_id, question: input.question, approved: true }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_templates', description: 'List learned plan templates from completed runs, with their node, dispatch, and human-intervention counts.',
        input: { type: 'object', properties: {}, additionalProperties: false },
        execute: async (input, context) => {
          if (!['prima', 'thirteenth'].includes(context.agent))
            throw new Error('Only thirteenth and prima may read templates');
          const result = await bridge('templates', project, {}, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_metrics', description: 'Read the run metrics panel or one run ledger projection; pass run_id for a single run.',
        input: { type: 'object', properties: { run_id: { type: 'string' } }, additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may read metrics');
          const result = await bridge('metrics', project, { run_id: input.run_id }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_check', description: 'Run a fixed lint, build, test, or Renode simulation target in an isolated project copy and return tool receipts.',
        input: { type: 'object', properties: {
          target: { type: 'string', enum: ['lint', 'build', 'test', 'sim'] },
          run_id: { type: 'string' },
        }, required: ['target'], additionalProperties: false },
        execute: async (input, context) => {
          const targets = {
            'micronus-prime': ['lint'],
            'solus-prime': ['lint'],
            'amalgamous': ['lint'],
            'alchemist': ['test', 'sim'],
            'nexus-prime': ['build'],
          };
          const allowed = new Set(Object.keys(targets));
          if (!allowed.has(context.agent) ||
              !targets[context.agent].includes(input.target))
            throw new Error(`This role cannot run cy_check target ${input.target}`);
          const result = await bridge('check', project,
            { target: input.target, run_id: input.run_id }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_review_reject',
        description: 'Record a blocking L2 finding against a direct producer of this review node.',
        input: { type: 'object', properties: {
          affected_node_id: { type: 'string' }, diagnostic: { type: 'string' },
        }, required: ['affected_node_id', 'diagnostic'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'liege-maximo') throw new Error('Only the L2 reviewer may reject');
          const binding = await ctx.storage.get(`child/${context.sessionID}`);
          if (!binding || !await ctx.storage.get(`bound/${context.sessionID}`))
            throw new Error('L2 reviewer has no verified native node binding');
          const dispatch = await ctx.storage.get(`dispatch/${binding.call_id}`);
          if (!dispatch) throw new Error('Missing bound native dispatch receipt');
          const result = await bridge('review_reject', project, {
            run_id: binding.run_id, call_id: binding.call_id, token: dispatch.token,
            child_session_id: context.sessionID, affected_node_id: input.affected_node_id,
            diagnostic: input.diagnostic,
          }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
    });
    await ctx.tool.hook('execute.before', async event => {
      if (event.tool === 'shell' || event.tool === 'bash') {
        const role = event.agent;
        const policy = shellPolicy.roles?.[role];
        if (!policy) {
          if ((shellPolicy.cybertronRoles || []).includes(role))
            throw new Error(`Cybertron: ${role} has no shell allow-list`);
          return;
        }
        const command = typeof event.input === 'string'
          ? event.input : (event.input?.command ?? event.input?.cmd);
        if (typeof command !== 'string' || !command.trim())
          throw new Error('Cybertron: shell command must be a non-empty string');
        if (/[\n\r;|&<>`]|\$\(/.test(command))
          throw new Error('Cybertron: shell chaining, redirection, or substitution is denied');
        const verdict = shellVerdict(policy, command);
        if (verdict === 'deny')
          throw new Error(`Cybertron: shell command denied by policy: ${command}`);
        if (verdict === 'unlisted')
          throw new Error(`Cybertron: shell command is not allow-listed for ${role}: ${command}`);
        return;
      }
      if (event.tool !== 'subagent') return;
      const parent = await ctx.session.get({ sessionID: event.sessionID });
      if (parent.agent !== 'prima') throw new Error('Only prima may dispatch a native subagent');
      const run_id = await ctx.storage.get(`run/${event.sessionID}`);
      const target = event.input?.agentID || event.input?.agent || event.input?.agentId;
      if (!run_id) {
        // Pre-plan phase: prima may dispatch thirteenth to clarify intent and
        // author the plan before any Cybertron node exists.
        if (target === 'thirteenth') return;
        throw new Error('No ready Cybertron node; call cy_plan first');
      }
      const reviewState = await bridge('state', project, { run_id }, event.signal);
      if (!reviewState.review_current)
        throw new Error('Plan review required: call cy_plan_review on the current plan revision before dispatch');
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
        node_id: result.node_id, write_scope: result.write_scope,
        external_scope: result.external_scope || [],
        access_mode: result.access_mode || 'workspace-write',
        started_ms: Date.now(), parent_session_id: event.sessionID });
      await ctx.storage.set(`active/${run_id}`, callID);
      await ctx.storage.set(`token/${run_id}`, result.token);
    });
    await ctx.tool.hook('execute.after', async event => {
      if (event.tool === 'question') {
        // The native OpenCode question card is the only user-facing ask UI.
        // Persist its question and the structured answer in the run ledger so
        // the plan is auditable without a second text prompt.
        const call_id = event.callID || event.id || event.toolCallID;
        if (event.status !== 'completed') return;
        const selected = await ctx.session.get({ sessionID: event.sessionID });
        if (!['prima', 'thirteenth'].includes(selected.agent)) return;
        const run_id = await ctx.storage.get(`run/${event.sessionID}`);
        if (!run_id) return;
        const asked = Array.isArray(event.input?.questions)
          ? event.input.questions.map(item => String(item?.question || '').trim()).filter(Boolean) : [];
        const answers = event.result?.metadata?.answers || event.result?.answers;
        if (!asked.length || !Array.isArray(answers)) return;
        for (let index = 0; index < asked.length; index += 1) {
          const answer = Array.isArray(answers[index]) ? answers[index].map(String) : [];
          try {
            await bridge('ask', project, { run_id, question: asked[index], answers: answer }, ctx.signal);
          } catch (error) {
            // Never turn a completed user answer into a failed tool call.
            console.warn(`Cybertron: could not record question answer (${call_id || 'no call id'}): ${error.message}`);
          }
        }
        return;
      }
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
      if (child_session_id && tool_status === 'completed') {
        await ctx.storage.set(`child/${child_session_id}`, {
          run_id: started.run_id, call_id, node_id: started.node_id,
          write_scope: started.write_scope, external_scope: started.external_scope || [],
          access_mode: started.access_mode || 'workspace-write',
          parent_session_id: started.parent_session_id,
        });
      }
    });
    if (ctx.permission && typeof ctx.permission.hook === 'function') {
      // External writes are declared in the plan and gated by OpenCode's own
      // ask/once/always/reject rules. This hook only narrows undeclared paths
      // and records what the host decided; it never turns allow back into ask.
      const replyHandler = async event => {
        const data = event && event.data ? event.data : event;
        if (!data || !data.sessionID || data.reply === undefined) return;
        const binding = await ctx.storage.get(`child/${data.sessionID}`);
        if (!binding) return;
        const last = await ctx.storage.get(`perm/${data.sessionID}`);
        if (!last) return;
        if (data.reply === 'always') {
          const grants = (await ctx.storage.get(`grant/${binding.run_id}`)) || [];
          await ctx.storage.set(`grant/${binding.run_id}`,
            [...new Set([...grants, ...last.resources])]);
        }
        await bridge('permission', project, {
          run_id: binding.run_id, call_id: binding.call_id,
          request_id: data.requestID || last.request_id,
          action: last.action, resources: last.resources, reply: data.reply,
        });
      };
      if (ctx.event && typeof ctx.event.subscribe === 'function') {
        try {
          const stream = ctx.event.subscribe({ types: ['permission.replied'] });
          if (stream && typeof stream[Symbol.asyncIterator] === 'function') {
            void (async () => {
              try {
                for await (const item of stream) await replyHandler(item);
              } catch (error) {
                console.warn(`Cybertron: permission reply stream stopped: ${error.message}`);
              }
            })();
          }
        } catch (error) {
          console.warn(`Cybertron: cannot subscribe to permission replies: ${error.message}`);
        }
      }
      await ctx.permission.hook('evaluate', async evaluation => {
        if (evaluation.action !== 'edit' && evaluation.action !== 'external_directory') return;
        if (!evaluation.resources || !evaluation.resources.length) return;
        const binding = await ctx.storage.get(`child/${evaluation.sessionID}`);
        if (!binding) return;
        const external = binding.external_scope || [];
        if (!external.length) return;
        const verdict = externalGate({ action: evaluation.action, resources: evaluation.resources,
          external, projectRoot: project, effect: evaluation.effect });
        if (verdict === 'skip') return;
        if (verdict === 'deny') {
          evaluation.effect = 'deny';
          evaluation.message = 'Cybertron: path is outside the node external_scope';
          return;
        }
        const requestId = `${evaluation.sessionID}:${evaluation.action}:${evaluation.resources.join('|')}`;
        try {
          const grants = await ctx.storage.get(`grant/${binding.run_id}`);
          if (grantCovers({ resources: evaluation.resources, grants })) {
            // An "always" reply is already on record for this run: skip the
            // prompt but keep the standing grant visible in the ledger.
            evaluation.effect = 'allow';
            await bridge('permission', project, {
              run_id: binding.run_id, call_id: binding.call_id, request_id: requestId,
              action: evaluation.action, resources: evaluation.resources, granted: true,
            });
            return;
          }
          if (verdict === 'allow') {
            // OpenCode saved an "always" rule: record it and leave allow.
            await bridge('permission', project, {
              run_id: binding.run_id, call_id: binding.call_id, request_id: requestId,
              action: evaluation.action, resources: evaluation.resources, granted: true,
            });
            return;
          }
          await ctx.storage.set(`perm/${evaluation.sessionID}`,
            { action: evaluation.action, resources: evaluation.resources, request_id: requestId });
          evaluation.effect = 'ask';
          evaluation.message = 'Cybertron: approve this external write';
          await bridge('permission', project, {
            run_id: binding.run_id, call_id: binding.call_id, request_id: requestId,
            action: evaluation.action, resources: evaluation.resources,
          });
        } catch (error) {
          console.warn(`Cybertron: could not record permission event: ${error.message}`);
        }
      });
    }
    await ctx.session.hook('context', async event => {
      if (event.agent === 'thirteenth') {
        const session = await ctx.session.get({ sessionID: event.sessionID });
        if (!session.parentID) {
          delete event.tools.cy_ask;
          delete event.tools.cy_ask_decision;
          delete event.tools.cy_plan_review;
          delete event.tools.cy_metrics;
          delete event.tools.cy_check;
          delete event.tools.cy_review_reject;
          delete event.tools.subagent;
          event.system.push({ type: 'text', text:
            'Cybertron planner: you are thirteenth, the only role that authors the plan. Clarify the human intent with `question`, check `cy_templates` before planning, then create or revise the kernel-validated graph with `cy_plan`. The kernel writes and validates plan.json; do not read or edit it directly. Do not dispatch `subagent`, run shell, or edit files: dispatch, approval, and settlement belong to prima. After `cy_plan` returns, give the human and prima the run_id, ready node cards, access_mode, gates, and any risk that needs human confirmation.' });
          event.system.push({ type: 'text', text:
            'When the user requests a read-only inspection or says not to modify files, create the read_only_scan template with a short objective: onyx-prime / scan.static and write_scope=[]. Do not substitute doc.write or a writing node. If the user asks for approval before execution, ask with the native question tool and do not hand off until the answer approves. Use a short English slug (for example hello-doc) for cy_plan.slug; the on-disk run folder uses only that slug and stores the UUID inside run.json. Access modes are host-native: read-only (no writes), workspace-write (default; project write_scope plus any declared external_scope paths, each gated by a host approval card), and danger-full-access (only when the user explicitly authorizes a blanket Desktop/Downloads/outside scope). Prefer external_scope for a few known outside files: the user approves each write (or chooses always) and the kernel records it. Use danger-full-access only when the user asks for unrestricted outside access. Pass access_mode to cy_plan. In danger-full-access mode role write roots relax, but .git, .opencode, .cybertron/runs, and opencode.jsonc stay forbidden. If an outside-project write is ambiguous, ask with the native question tool before planning; never select danger-full-access without explicit authorization.' });
          return;
        }
      }
      if (event.agent !== 'prima') {
        const session = await ctx.session.get({ sessionID: event.sessionID });
        const parentRun = session.parentID && await ctx.storage.get(`run/${session.parentID}`);
        if (event.agent === 'thirteenth' && !parentRun) {
          // Planning child: prima dispatched thirteenth before any run exists.
          // Keep only the planning surface; the run id is handed to prima by
          // cy_plan, so the human never switches agents or copies ids.
          delete event.tools.cy_state;
          delete event.tools.cy_plan_review;
          delete event.tools.cy_ask;
          delete event.tools.cy_ask_decision;
          delete event.tools.cy_metrics;
          delete event.tools.cy_check;
          delete event.tools.cy_review_reject;
          delete event.tools.subagent;
          event.system.push({ type: 'text', text:
            'Cybertron planning child: you are thirteenth, dispatched by prima to clarify the human intent and author the plan. Ask the human with the native `question` tool, check `cy_templates`, then create the kernel-validated graph with `cy_plan`. The kernel writes plan.json; do not edit it. Do not dispatch subagent, run shell, edit files, review plans, or settle nodes. When the plan is ready, return the plan summary, ready cards, access_mode, and gates; prima will review and dispatch.' });
          return;
        }
        if (parentRun) {
          let binding;
          for (let attempt = 0; attempt < 100; attempt++) {
            binding = await ctx.storage.get(`child/${event.sessionID}`);
            if (binding) break;
            await new Promise(resolve => setTimeout(resolve, 50));
          }
          if (!binding || binding.run_id !== parentRun ||
              binding.parent_session_id !== session.parentID) {
            throw new Error('Native child has no verified Cybertron node binding');
          }
          if (!await ctx.storage.get(`bound/${event.sessionID}`)) {
            const permissions = childPermissionRules({
              accessMode: binding.access_mode,
              writeScope: binding.write_scope,
              externalScope: binding.external_scope,
            });
            await ctx.session.update({ sessionID: event.sessionID, permissions });
            const updated = await ctx.session.get({ sessionID: event.sessionID });
            if (JSON.stringify(updated.permissions) !== JSON.stringify(permissions))
              throw new Error('Native child permission binding was not persisted');
            const dispatch = await ctx.storage.get(`dispatch/${binding.call_id}`);
            if (!dispatch || dispatch.run_id !== binding.run_id)
              throw new Error('Missing bound native dispatch receipt');
            await bridge('bind', project, { run_id: binding.run_id, call_id: binding.call_id,
              token: dispatch.token, child_session_id: event.sessionID,
              write_scope: binding.write_scope,
              external_scope: binding.external_scope || [] });
            await ctx.storage.set(`bound/${event.sessionID}`, true);
          }
        }
        delete event.tools.cy_state;
        delete event.tools.cy_plan;
        delete event.tools.cy_plan_review;
        delete event.tools.cy_ask;
        delete event.tools.question;
        delete event.tools.cy_templates;
        delete event.tools.cy_metrics;
        delete event.tools.subagent;
        if (event.agent !== 'liege-maximo') delete event.tools.cy_review_reject;
        if (!['micronus-prime', 'nexus-prime', 'alchemist', 'solus-prime',
          'amalgamous'].includes(event.agent)) delete event.tools.cy_check;
        return;
      }
      delete event.tools.cy_check;
      delete event.tools.cy_review_reject;
      delete event.tools.cy_plan;
      if (!event.tools.subagent && !event.tools.execute)
        throw new Error('Native subagent tool is unavailable for prima; disable the legacy cybertron.runtime plugin in this project with plugins: ["-cybertron.runtime"] and restart OpenCode');
      const expected = primaryModel(project);
      if (expected && (event.model.providerID !== expected.providerID ||
          event.model.id !== expected.id || event.model.variant !== expected.variant)) {
        // The user can switch models in OpenCode at any time. Adapt to the
        // active session model instead of failing the whole turn; the note
        // makes the mismatch visible without discarding the user's choice.
        const expectedName = `${expected.providerID}/${expected.id}${expected.variant ? '#' + expected.variant : ''}`;
        const activeName = `${event.model.providerID}/${event.model.id}${event.model.variant ? '#' + event.model.variant : ''}`;
        await ctx.storage.set(`model/override/${event.sessionID}`, event.model);
        event.system.push({ type: 'text', text:
          `Cybertron: active session model ${activeName} differs from the configured Prima default ${expectedName}. Continue with the session-selected model; do not claim a model switch.` });
      }
      event.system.push({ type: 'text', text:
        'Cybertron dispatcher: you are the single human-facing entry. If no run exists, first dispatch thirteenth as a planning subagent with the human request; thirteenth will ask the human to clarify intent and author the plan, and its run id is handed to you automatically. When it returns, read the run with cy_state, call cy_plan_review on the current revision, then dispatch ready nodes through the native subagent tool. A plan revision invalidates the review and blocks dispatch until you review again. Use the exact kernel card as the description and include node_id, capability, write_scope, objective, and run_id in the child prompt. Call cy_state with wait=true after each child returns. Use cy_ask for formal host approval before a risky dispatch; use the native question tool only when the human must choose. Do not call cy_plan, do not edit files, and never claim model text as tool evidence.' });
      event.system.push({ type: 'text', text:
        'If no run exists yet, dispatch thirteenth first as the planning subagent; do not ask the human to switch agents or copy a run id. Do not create nodes, revise scopes, or change access_mode yourself; read access_mode, write_scope, and gates from cy_state after thirteenth returns.' });
    });
  },
});
