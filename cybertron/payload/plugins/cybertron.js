import { Plugin } from '@opencode/plugin';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, readFileSync, realpathSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { nativeDispatch, childSession, nativeToolStatus, childPermissionRules,
  outsideProject, toolPath, externalFileState, runIsTerminal, reviewerPathDenied } from './hook_logic.mjs';
import shellPolicy from './shell_policy.mjs';

const pluginDirectory = path.dirname(fileURLToPath(import.meta.url));
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const contentDigest = value => createHash('sha256').update(value, 'utf8').digest('hex');
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
const noWriteRequested = text =>
  /^(?:\s*)(?:只读(?:检查|分析|模式|[：:，。\s]|$)|read[- ]only\b)|本次(?:任务|操作|检查)(?:仅限|保持|为)只读|(?:项目|工作区)(?:保持|设为)只读|不(?:要|得)?(?:创建|修改|删除|写入)(?:任何|所有|全部)?文件(?:[。！；，,.!;\s]|$)|\b(?:keep|leave|set) (?:the )?(?:workspace|project) read[- ]only\b|\bdo not (?:write|modify|create|delete) (?:(?:any|all) )?files?(?:[.,;!]|$)/i.test(text);
const fullAccessRequested = text =>
  !/(?:不要|禁止|不得|无需|不需要|不允许|不用|不能)[^，。！？\n]{0,16}(?:完全权限|全局权限|无限制|danger[- ]full[- ]access)|(?:no|without|never|don.t)\s+(?:use |request )?(?:full access|unrestricted access|danger[- ]full[- ]access)/i.test(text) &&
  /完全权限|无限制(?:访问|写入)|full access|danger[- ]full[- ]access|unrestricted (?:access|write)|blanket (?:access|write)|(?:允许|授权|同意).*(?:所有|任意|整个).*(?:项目外|电脑|磁盘|文件|目录|路径)|(?:write|access) (?:anywhere|everywhere)/i.test(text);

function protectedTarget(target) {
  const parts = target.split(path.sep);
  return parts.some((part, i) => ['.git', '.opencode', 'opencode.jsonc'].includes(part) ||
    part === '.cybertron' && ['runs', 'templates'].includes(parts[i + 1]) ||
    part === 'cybertron' && parts[i + 1] === 'registry.py');
}

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
    node_id: { type: 'string' }, kind: { type: 'string', enum: ['task', 'review', 'verify'] },
    capability: { type: 'string' }, role: { type: 'string' }, objective: { type: 'string' },
    depends_on: { type: 'array', items: { type: 'string' } },
    read_scope: { type: 'array', items: { type: 'string' } },
    write_scope: { type: 'array', items: { type: 'string' } },
    external_scope: { type: 'array', items: { type: 'string' } },
    acceptance: { type: 'array', items: { type: 'string' } },
    verifiers: { type: 'array', items: { type: 'string', enum: ['scope_guard', 'loop1'] },
      description: 'Use ["scope_guard"]. Put runnable checks in dedicated verify nodes.' },
    satisfies: { type: 'array', items: { type: 'string' },
      description: 'Lowercase IDs of the acceptance criteria this node covers.' },
    requires: { type: 'array', items: { type: 'string' } },
    check_target: { type: 'string', enum: ['lint', 'build', 'test', 'sim'] },
    expected_content: { type: 'string',
      description: 'Exact requested text of a single file. Include the requested trailing newline, if any.' },
  },
  required: ['node_id', 'kind', 'capability', 'role', 'objective', 'write_scope', 'acceptance', 'verifiers'],
  additionalProperties: false,
};

export default Plugin.define({
  id: 'cybertron.v6.runtime',
  async setup(ctx) {
    const project = ctx.location.project.canonical;
    const externalWrites = new Map();
    const externalWriteKey = (session, call) => JSON.stringify([session, call]);
    const recordExternalWrite = (write, outcome, detail) =>
      bridge('external_write', project, { ...write.receipt, outcome, detail,
        changed_lines: write.changedLines });
    await ctx.session.hook('prompt', async event => {
      const selected = await ctx.session.get({ sessionID: event.sessionID });
      if (!selected.parentID) {
        const prompt = event.prompt?.text || '';
        await ctx.storage.set(`full-access-requested/${event.sessionID}`, fullAccessRequested(prompt));
        if (noWriteRequested(prompt)) {
          await ctx.storage.set(`read-only/${event.sessionID}`, true);
          await ctx.storage.set(`access/${event.sessionID}`, 'read-only');
        } else if (fullAccessRequested(prompt)) {
          await ctx.storage.set(`read-only/${event.sessionID}`, false);
          await ctx.storage.set(`access/${event.sessionID}`, 'danger-full-access');
        } else {
          await ctx.storage.set(`read-only/${event.sessionID}`, false);
          await ctx.storage.set(`access/${event.sessionID}`, 'workspace-write');
        }
        const model = selected.agent === 'prima' ? primaryModel(project) : null;
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
      editor.update?.('subagent', tool => {
        const dispatch = tool.execute;
        tool.execute = async (input, context) => {
          const result = await dispatch(input, context);
          if (context.agent !== 'prima' || !childSession(result)) return result;
          return { ...result, content: 'Cybertron native child dispatched. Call cy_state(wait=true) '
            + 'to wait and settle it, then continue with the returned next_actions.' };
        };
      });
      editor.add({
        name: 'cy_plan', description: 'Create a validated v6 task graph. Derive each write_scope and external_scope from the current user request. A named outside file uses workspace-write plus that exact external_scope and host approval. Danger-full-access means unrestricted outside writes and always requires a separate host approval. Include an intent contract, node satisfies mapping, acceptance criteria, and scope_guard. Use read_only_scan for read-only requests. A controlled cy_delete tool handles declared deletions after dangerous.confirm approval. Returns ready native subagent cards.',
        input: { type: 'object', properties: {
          node: nodeInput, nodes: { type: 'array', items: nodeInput, minItems: 1 },
          template: { type: 'object', properties: {
            type: { type: 'string', enum: ['bug_fix', 'read_only_scan'] }, objective: { type: 'string' },
            write_scope: { type: 'array', items: { type: 'string' }, minItems: 1 },
          }, required: ['type', 'objective'], additionalProperties: false },
          template_id: { type: 'string' },
          objective: { type: 'string' },
          gates: { type: 'array', items: { type: 'string' } },
          slug: { type: 'string' },
          write_scope: { type: 'array', items: { type: 'string' } },
          test_scope: { type: 'array', items: { type: 'string' } },
          skip: { type: 'array', items: { type: 'string' } },
          request_class: { type: 'string' },
          new_run: { type: 'boolean' },
          change_reason: { type: 'string' },
          seed_from_run_id: { type: 'string' },
          satisfies: { type: 'object', description: 'For templates only, map node IDs to arrays of criterion IDs.', additionalProperties: {
            type: 'array', items: { type: 'string' },
          } },
          intent: { type: 'object', properties: {
            goal: { type: 'string' },
            source: { type: 'string' },
            done: { type: 'array', minItems: 1, items: { type: 'object', properties: {
            id: { type: 'string', pattern: '^[a-z][a-z0-9_-]{0,31}$' }, criterion: { type: 'string' },
              evidence: { type: 'string', enum: ['artifact', 'test', 'review', 'receipt'] },
            }, required: ['id', 'criterion'], additionalProperties: false } },
            non_goals: { type: 'array', items: { type: 'string' } },
            forbidden_capabilities: { type: 'array', items: { type: 'string' } },
            forbidden_paths: { type: 'array', items: { type: 'string' } },
            confirmed: { type: 'boolean' },
          }, required: ['goal', 'done', 'confirmed'], additionalProperties: false },
          access_mode: { type: 'string', enum: ['read-only', 'workspace-write', 'danger-full-access'] },
          operation: { type: 'object', properties: {
            op: { type: 'string', enum: ['revise'] },
            op_id: { type: 'string' },
            plan_revision: { type: 'integer' },
            reason: { type: 'string' },
            nodes: { type: 'array', items: nodeInput },
            remove_nodes: { type: 'array', items: { type: 'string' } },
            retry_nodes: { type: 'array', items: { type: 'string' } },
            gates: { type: 'array', items: { type: 'string' } },
          }, required: ['op', 'op_id', 'plan_revision', 'reason'], additionalProperties: false },
        }, additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'thirteenth') throw new Error('Only thirteenth may author plans');
          const hashNodeContent = ({ expected_content, ...node }) => expected_content === undefined
            ? node : { ...node, expected_content_sha256: contentDigest(expected_content) };
          const session = await ctx.session.get({ sessionID: context.sessionID });
          const entry = session?.parentID || context.sessionID;
          const handoff = session?.parentID && await ctx.storage.get(`planning-request/${entry}`);
          const pendingSupersede = session?.parentID && await ctx.storage.get(`supersede/${entry}`);
          let run_id = handoff?.run_id || await ctx.storage.get(`run/${context.sessionID}`);
          const current = run_id ? await bridge('state', project, { run_id }, context.signal) : null;
          const readOnly = await ctx.storage.get(`read-only/${entry}`);
          if (input.operation) {
            if (!run_id || input.operation.op !== 'revise' ||
                (session?.parentID && !handoff?.run_id))
              throw new Error('A revision needs the current planning handoff or an existing planner session');
            if (handoff && input.operation.plan_revision !== handoff.plan_revision)
              throw new Error('Use the revision from the current planning handoff');
            if (readOnly && current.access_mode !== 'read-only')
              throw new Error('A writing run cannot continue in a read-only turn');
            if (input.new_run || input.intent || input.access_mode || input.node || input.nodes ||
                input.template || input.template_id || input.gates || input.seed_from_run_id)
              throw new Error('A revision preserves the current intent and access mode. Submit only operation.');
            const operation = { ...input.operation, nodes: (input.operation.nodes || []).map(hashNodeContent) };
            const result = await bridge('plan_op', project, {
              run_id, operation, planner_session_id: context.sessionID,
            }, context.signal);
            return { content: JSON.stringify(result) };
          }
          if (handoff?.run_id) throw new Error('Use revise on the same run with the supplied revision');
          const previous_run_id = runIsTerminal(current) ? run_id : null;
          if (previous_run_id) run_id = null;
          if (run_id && (!input.new_run || !input.change_reason?.trim()))
            throw new Error('An existing run requires a revision. Use a new run only if the user changes the goal.');
          if (current?.active_dispatches?.length) throw new Error('An active dispatch must settle first');
          if ([input.node, input.nodes, input.template, input.template_id, input.seed_from_run_id].filter(Boolean).length !== 1)
            throw new Error('New run requires exactly one node, nodes, template, template_id, or seed_from_run_id');
          let access_mode = input.access_mode || await ctx.storage.get(`access/${entry}`) || 'workspace-write';
          if (readOnly || input.template?.type === 'read_only_scan') access_mode = 'read-only';
          if (input.template_id && !input.objective) throw new Error('A template seed requires the new objective');
          if (input.skip && !input.template_id) throw new Error('skip is only valid with a template seed');
          if (input.intent && (input.template || input.template_id || input.seed_from_run_id) && !input.satisfies)
            throw new Error('intent with a template or seed requires a satisfies map');
          const supersede = Boolean(run_id);
          if ((supersede || !run_id) && access_mode === 'danger-full-access') {
            const entry = session?.parentID || context.sessionID;
            if (!await ctx.storage.get(`full-access-requested/${entry}`))
              throw new Error('Unrestricted access requires an explicit request in the current user message');
            await ctx.permission.assert({
              sessionID: context.sessionID, agent: context.agent,
              source: { type: 'tool', messageID: context.messageID, id: context.id },
              action: 'cy_full_access_decision', resources: ['*'],
              metadata: { project, reason: 'Unrestricted project and external writes' },
            });
          }
          const result = await bridge('plan', project, {
            node: input.node && hashNodeContent(input.node), nodes: input.nodes?.map(hashNodeContent),
            template: input.template, template_id: input.template_id, objective: input.objective,
            write_scope: input.write_scope, test_scope: input.test_scope, skip: input.skip,
            request_class: input.request_class, intent: input.intent, satisfies: input.satisfies,
            parent_run_id: run_id || pendingSupersede?.run_id || previous_run_id,
            supersedes_run_id: run_id || pendingSupersede?.run_id,
            change_reason: input.change_reason || pendingSupersede?.change_reason || '',
            seed_from_run_id: input.seed_from_run_id, access_mode,
            session_title: session?.title || input.objective || '', slug: input.slug || '',
            host_session_id: entry, host: 'opencode', planned_verification: true, gates: input.gates,
          }, context.signal);
          if ((supersede || !run_id) && access_mode === 'danger-full-access') {
            await bridge('ask', project, { run_id: result.run_id,
              question: 'Approve unrestricted project and external writes',
              approved: true }, context.signal);
          }
          const questionsKey = `intake/questions/${context.sessionID}`;
          for (const answer of await ctx.storage.get(questionsKey) || [])
            await bridge('ask', project, { run_id: result.run_id, ...answer }, context.signal);
          await ctx.storage.remove(questionsKey);
          if (supersede || !run_id) {
            if (pendingSupersede && session?.parentID)
              await ctx.storage.remove(`supersede/${session.parentID}`);
            await ctx.storage.set(`run/${context.sessionID}`, result.run_id);
            await ctx.storage.set(`access/${context.sessionID}`, result.access_mode || access_mode);
            // A planning child gives the parent its run id, so prima can adopt
            // the plan without the human copying the id between agents.
            if (session?.parentID)
              await ctx.storage.set(`run/${session.parentID}`, result.run_id);
          }
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_state', description: 'Read the v6 run; wait for the native child to finish before settling the node.',
        input: { type: 'object', properties: {
          wait: { type: 'boolean' },
        }, additionalProperties: false },
        execute: async (input, context) => {
          if (!['prima', 'thirteenth'].includes(context.agent))
            throw new Error('Only prima may settle and thirteenth may read the run state');
          if (context.agent === 'thirteenth' && input.wait)
            throw new Error('The planner may read the run but prima owns wait/settle');
          const session = await ctx.session.get({ sessionID: context.sessionID });
          const handoff = session?.parentID && await ctx.storage.get(`planning-request/${session.parentID}`);
          let run_id = handoff?.run_id || await ctx.storage.get(`run/${context.sessionID}`);
          if (context.agent === 'prima') {
            const planner = await ctx.storage.get(`planning-child/${context.sessionID}`);
            if (planner) {
              if (!input.wait)
                return { content: JSON.stringify({ status: 'planning',
                  next_actions: [{ tool: 'cy_state', arguments: { wait: true } }] }) };
              await ctx.session.wait({ sessionID: planner });
              await ctx.storage.remove(`planning-child/${context.sessionID}`);
              await ctx.storage.remove(`planning-request/${context.sessionID}`);
              run_id = await ctx.storage.get(`run/${context.sessionID}`);
            }
          }
          if (!run_id) return { content: JSON.stringify({ status: 'no_run',
            next_actions: [{ tool: 'subagent', agent: 'thirteenth', reason: 'plan the request' }] }) };
          let state = await bridge('state', project, { run_id }, context.signal);
          await ctx.storage.set(`access/${context.sessionID}`, state.access_mode);
          if (input.wait && (state.status === 'running' ||
              (state.active_dispatches || []).length > 0)) {
            for (const active of state.active_dispatches || []) {
              if (!active.child_session_id) continue;
              await ctx.session.wait({ sessionID: active.child_session_id });
              const dispatch = await ctx.storage.get(`dispatch/${active.call_id}`);
              if (!dispatch) throw new Error('Missing bound native dispatch receipt');
              const child_error = Boolean(await ctx.storage.get(
                `tool_error/${active.child_session_id}`));
              state = await bridge('finish', project,
                { run_id, token: dispatch.token, call_id: active.call_id,
                  child_session_id: active.child_session_id, child_error }, context.signal);
              await ctx.storage.remove(`tool_error/${active.child_session_id}`);
            }
          }
          return { content: JSON.stringify(state) };
        },
      });
      editor.add({
        name: 'cy_runs', description: 'List persisted Cybertron runs in this project, including status and next actions. Use when a new OpenCode session needs to find unfinished work.',
        input: { type: 'object', properties: {}, additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may discover runs');
          const result = await bridge('runs', project, {}, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_resume', description: 'Adopt a persisted run found by cy_runs in this OpenCode session. Does not execute or settle a node.',
        input: { type: 'object', properties: { run_id: { type: 'string' } },
          required: ['run_id'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may resume a run');
          if (typeof input.run_id !== 'string' || !input.run_id.trim())
            throw new Error('run_id must be a non-empty string');
          const currentID = await ctx.storage.get(`run/${context.sessionID}`);
          if (currentID && currentID !== input.run_id) {
            const current = await bridge('state', project, { run_id: currentID }, context.signal);
            if (!runIsTerminal(current))
              throw new Error('Current run is unfinished; use cy_new_run before switching runs');
          }
          const state = await bridge('state', project, { run_id: input.run_id }, context.signal);
          if (state.status === 'superseded')
            throw new Error('This run was superseded; resume its replacement instead');
          await ctx.storage.set(`run/${context.sessionID}`, state.run_id);
          await ctx.storage.set(`access/${context.sessionID}`, state.access_mode);
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
          const pending = await ctx.storage.get(`grant_request/${context.sessionID}`);
          if (pending) {
            const grant = await bridge('grant_approve', project, {
              run_id, request_id: pending, approver: 'human',
              via: 'opencode.permission',
            }, context.signal);
            await ctx.storage.remove(`grant_request/${context.sessionID}`);
            return { content: JSON.stringify({ ...result, grant }) };
          }
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_new_run', description: 'Freeze planning on the current run and prepare a replacement run. Call this before dispatching thirteenth when the user changes requirements while the current run is not terminal; then dispatch thirteenth, which must pass supersedes_run_id via cy_plan.',
        input: { type: 'object', properties: {
          run_id: { type: 'string' },
          change_reason: { type: 'string' },
        }, required: ['change_reason'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may start a replacement run');
          const run_id = input.run_id || await ctx.storage.get(`run/${context.sessionID}`);
          if (!run_id) throw new Error('No v6 run in this session');
          if (typeof input.change_reason !== 'string' || !input.change_reason.trim())
            throw new Error('change_reason is required');
          const state = await bridge('state', project, { run_id }, context.signal);
          if (state.status === 'running' || (state.active_dispatches || []).length)
            throw new Error('Cannot replace a run during an active dispatch');
          await ctx.storage.set(`supersede/${context.sessionID}`,
            { run_id, change_reason: input.change_reason.trim() });
          return { content: JSON.stringify({ old_run_id: run_id,
            status: 'ready_for_replacement_plan' }) };
        },
      });
      editor.add({
        name: 'cy_escalate', description: 'Request a capability grant for one node. Does not approve it: after this returns, call cy_ask so the human opens the host approval card. Kinds: read.expand, network.read, write.expand, exec.expand, pkg.install, vcs.write, vcs.push, external.write, deploy, device, dangerous.confirm. A gate named dangerous.confirm requires kind dangerous.confirm.',
        input: { type: 'object', properties: {
          run_id: { type: 'string' },
          node_id: { type: 'string' },
          kind: { type: 'string' },
          scope: { type: 'object' },
          constraints: { type: 'object' },
          reason: { type: 'string' },
          ttl_seconds: { type: 'integer' },
          mode: { type: 'string', enum: ['once', 'run', 'standing'] },
        }, required: ['node_id', 'kind'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'prima') throw new Error('Only prima may request a capability grant');
          const run_id = input.run_id || await ctx.storage.get(`run/${context.sessionID}`);
          if (!run_id) throw new Error('No v6 run in this session');
          if (input.kind === 'external.write') {
            const state = await bridge('state', project, { run_id }, context.signal);
            const node = state.nodes.find(node => node.node_id === input.node_id);
            if (state.access_mode === 'workspace-write' && node?.external_scope.length)
              return { content: JSON.stringify({ status: 'approval_at_write',
                message: 'Dispatch the declared file node. OpenCode will request approval for the actual write.' }) };
          }
          const result = await bridge('grant_request', project, {
            run_id, node_id: input.node_id, kind: input.kind,
            scope: input.scope || {}, constraints: input.constraints || {},
            reason: input.reason || '', ttl_seconds: input.ttl_seconds,
            mode: input.mode || 'once',
          }, context.signal);
          await ctx.storage.set(`grant_request/${context.sessionID}`, result.request_id);
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
        name: 'cy_capabilities', description: 'List registered capability -> role mappings. Call this before cy_plan when you are unsure which role can perform an action.',
        input: { type: 'object', properties: {}, additionalProperties: false },
        execute: async (_input, context) => {
          if (!['prima', 'thirteenth'].includes(context.agent))
            throw new Error('Only prima and thirteenth may read the capability catalog');
          const result = await bridge('planning_tools', project, {}, context.signal);
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
          node_id: { type: 'string' },
        }, required: ['target'], additionalProperties: false },
        execute: async (input, context) => {
          const targets = { 'micronus-prime': ['lint'], alchemist: ['test', 'sim'],
            'quintus-prime': ['test', 'sim'], 'nexus-prime': ['build'] };
          if (!targets[context.agent]?.includes(input.target))
            throw new Error(`This role cannot run cy_check target ${input.target}`);
          const binding = await ctx.storage.get(`child/${context.sessionID}`);
          if (!binding || !await ctx.storage.get(`bound/${context.sessionID}`) ||
              (input.run_id && input.run_id !== binding.run_id) ||
              (input.node_id && input.node_id !== binding.node_id))
            throw new Error('cy_check requires its verified native node binding');
          const result = await bridge('check', project, {
            target: input.target, run_id: binding.run_id, call_id: binding.call_id,
            node_id: binding.node_id, child_session_id: context.sessionID,
          }, context.signal);
          return { content: JSON.stringify({ target: result.target, status: result.status,
            receipts: result.receipts, diagnostic: result.diagnostic }) };
        },
      });
      editor.add({
        name: 'cy_verify', description: 'Record independent acceptance findings against the bound evidence.',
        input: { type: 'object', properties: {
          passed: { type: 'boolean' }, findings: { type: 'string' },
        }, required: ['passed', 'findings'], additionalProperties: false },
        execute: async (input, context) => {
          if (context.agent !== 'megatronus') throw new Error('Only megatronus may verify acceptance');
          const binding = await ctx.storage.get(`child/${context.sessionID}`);
          if (!binding || !await ctx.storage.get(`bound/${context.sessionID}`))
            throw new Error('cy_verify requires its verified native node binding');
          const result = await bridge('verify_acceptance', project, {
            run_id: binding.run_id, call_id: binding.call_id,
            child_session_id: context.sessionID, passed: input.passed, findings: input.findings,
          }, context.signal);
          return { content: JSON.stringify(result) };
        },
      });
      editor.add({
        name: 'cy_delete', description: 'Delete exactly one path declared in the node write_scope. Requires a dangerous.confirm grant; this is the controlled replacement for rm -rf in a subagent without a shell.',
        input: { type: 'object', properties: { path: { type: 'string' } },
          required: ['path'], additionalProperties: false },
        execute: async (input, context) => {
          if (!['solus-prime', 'nexus-prime'].includes(context.agent))
            throw new Error('This role may not delete paths');
          const binding = await ctx.storage.get(`child/${context.sessionID}`);
          if (!binding || !await ctx.storage.get(`bound/${context.sessionID}`))
            throw new Error('cy_delete needs a verified node binding');
          const result = await bridge('delete_path', project, {
            run_id: binding.run_id, node_id: binding.node_id, path: input.path,
          }, context.signal);
          if (result.status === 'needs_grant')
            throw new Error('Cybertron: dangerous.confirm grant required; call cy_escalate(kind=dangerous.confirm, node_id=...) then cy_ask');
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
      const childBinding = await ctx.storage.get(`child/${event.sessionID}`);
      const boundRun = childBinding?.run_id || await ctx.storage.get(`run/${event.sessionID}`);
      const boundAccess = await ctx.storage.get(`access/${event.sessionID}`)
        || childBinding?.access_mode;
      const writeTarget = ['write', 'edit'].includes(event.tool)
        ? toolPath(project, event.input?.path ?? event.input?.filePath) : null;
      if (writeTarget && shellPolicy.cybertronRoles.includes(event.agent)) {
        if (boundAccess === 'read-only') throw new Error('This run is read-only');
        if (existsSync(writeTarget) && lstatSync(writeTarget).nlink > 1 &&
            lstatSync(writeTarget).isFile()) throw new Error('Cybertron cannot edit a hard-linked file');
        let ancestor = writeTarget;
        while (!existsSync(ancestor) && path.dirname(ancestor) !== ancestor)
          ancestor = path.dirname(ancestor);
        const canonical = path.join(realpathSync(ancestor), path.relative(ancestor, writeTarget));
        if (protectedTarget(writeTarget) || protectedTarget(canonical))
          throw new Error('Cybertron configuration and run state are protected');
        if (childBinding && canonical !== writeTarget)
          throw new Error('Cybertron write target must use its canonical path');
      }
      if (event.tool === 'write' && writeTarget && childBinding?.external_scope.length && outsideProject(project, writeTarget)) {
        if (typeof ctx.permission?.hook !== 'function' || !event.id ||
            !await ctx.storage.get(`bound/${event.sessionID}`))
          throw new Error('External write needs a verified OpenCode child permission binding');
        if (childBinding.external_scope.length !== 1)
          throw new Error('An external write node must declare exactly one file');
        const declared = childBinding.external_scope[0];
        const canonical = path.join(realpathSync(path.dirname(writeTarget)), path.basename(writeTarget));
        if (canonical !== declared)
          throw new Error(`External write is restricted to ${declared}`);
        if (typeof event.input.content !== 'string')
          throw new Error('External write requires exact text content');
        const receipt = { run_id: childBinding.run_id, call_id: childBinding.call_id,
          tool_call_id: event.id, target: declared, content_sha256: contentDigest(event.input.content) };
        if ([...externalWrites.values()].some(active => active.receipt.target === declared))
          throw new Error('An exact-file write is already active for this target');
        const key = externalWriteKey(event.sessionID, event.id);
        const write = { receipt, file: externalFileState(declared), approval: 'pending' };
        externalWrites.set(key, write);
        try {
          const status = await recordExternalWrite(write, 'inspect');
          if (status.outcome !== 'available')
            throw new Error(`Previous external write outcome: ${status.outcome}. Do not retry this action.`);
          event.input.path = declared;
          return;
        } catch (error) {
          externalWrites.delete(key);
          throw error;
        }
      }
      if (boundRun && ['bash', 'shell', 'write', 'edit'].includes(event.tool)) {
        const dispatch = childBinding?.call_id
          ? await ctx.storage.get(`dispatch/${childBinding.call_id}`) : null;
        if (dispatch?.node_id) {
          const gate = await bridge('gate_tool', project, {
            run_id: boundRun, node_id: dispatch.node_id,
            tool: event.tool, input: event.input,
          }, event.signal);
          if (gate.action === 'needs_grant')
            throw new Error(`Cybertron: grant required (${gate.kinds.join(', ')}) for node ${gate.node_id}; call cy_escalate, then cy_ask`);
        }
      }
      if (boundRun && boundAccess === 'danger-full-access' &&
          ['bash', 'shell', 'write', 'edit'].includes(event.tool)) {
        const verdict = await bridge('intercept', project, {
          run_id: boundRun, tool: event.tool, input: event.input,
          node_id: childBinding?.node_id,
        }, event.signal);
        if (verdict.action === 'confirm') {
          await ctx.storage.set(`danger/${event.sessionID}`, {
            command_sha256: verdict.command_sha256, tool: event.tool,
            at: Date.now(),
          });
          throw new Error(`Cybertron: full-access dangerous action requires confirmation. ${verdict.instruction}`);
        }
      }
      if (['read', 'glob', 'grep'].includes(event.tool) &&
          ['micronus-prime', 'liege-maximo'].includes(event.agent)) {
        const raw = event.input?.filePath ?? event.input?.path ?? event.input?.file
          ?? event.input?.pattern;
        const values = Array.isArray(raw) ? raw : [raw];
        for (const value of values)
          if (reviewerPathDenied(value))
            throw new Error(`Cybertron: reviewer cannot read sensitive path: ${value}`);
      }
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
        if (/[\n\r;|&<>`]|\$\(/.test(command)) {
          await ctx.storage.set(`tool_error/${event.sessionID}`, true);
          throw new Error('Cybertron: shell chaining, redirection, or substitution is denied');
        }
        const verdict = shellVerdict(policy, command);
        if (verdict === 'deny') {
          await ctx.storage.set(`tool_error/${event.sessionID}`, true);
          throw new Error(`Cybertron: shell command denied by policy: ${command}`);
        }
        if (verdict === 'unlisted') {
          await ctx.storage.set(`tool_error/${event.sessionID}`, true);
          throw new Error(`Cybertron: shell command is not allow-listed for ${role}: ${command}`);
        }
        return;
      }
      if (event.tool !== 'subagent') return;
      const actor = event.agent || (await ctx.session.get({ sessionID: event.sessionID })).agent;
      const target = event.input?.agentID || event.input?.agent || event.input?.agentId;
      if (actor !== 'prima') {
        if (shellPolicy.cybertronRoles.includes(actor) || shellPolicy.cybertronRoles.includes(target))
          throw new Error('Only prima may dispatch a Cybertron subagent');
        return;
      }
      let run_id = await ctx.storage.get(`run/${event.sessionID}`);
      if (run_id) {
        const current = await bridge('state', project, { run_id }, event.signal);
        if (runIsTerminal(current)) {
          // Without this, a planner dispatch after a finished run is treated
          // as a node dispatch and fails with 'requires node card'.
          await ctx.storage.remove(`run/${event.sessionID}`);
          run_id = null;
        }
      }
      if (target === 'thirteenth') {
        if (await ctx.storage.get(`planning-request/${event.sessionID}`))
          throw new Error('Wait for the active planning handoff using cy_state(wait=true)');
        const supersede = await ctx.storage.get(`supersede/${event.sessionID}`);
        const state = run_id && !supersede
          ? await bridge('planning_handoff', project, { run_id, parent_session_id: event.sessionID }, event.signal)
          : null;
        await ctx.storage.set(`planning-request/${event.sessionID}`,
          state ? { run_id, plan_revision: state.plan_revision } : {});
        return;
      }
      if (!run_id) throw new Error('No ready Cybertron node; dispatch thirteenth to plan first');
      if (await ctx.storage.get(`planning-request/${event.sessionID}`))
        throw new Error('Wait for the planning handoff before dispatching an execution node');
      if (event.input?.sessionID || event.input?.sessionId || event.input?.task_id)
        throw new Error('A Cybertron node needs a fresh native child. Omit the previous child session ID.');
      if (await ctx.storage.get(`read-only/${event.sessionID}`) &&
          (await bridge('state', project, { run_id }, event.signal)).access_mode !== 'read-only')
        throw new Error('A writing run cannot dispatch during a read-only turn');
      const { nodeID, role, callID, card } = nativeDispatch(event);
      const result = await bridge('before', project,
        { run_id, node_id: nodeID, role, card, call_id: callID });
      if (result.rejected) {
        if (result.needs_grant) {
          throw new Error(`Cybertron: grant required for ${result.node_id}: ${result.needs_grant.join(', ')}; call cy_escalate, then cy_ask for human approval`);
        }
        throw new Error(result.reason);
      }
      await ctx.storage.set(`dispatch/${callID}`, { run_id, token: result.token,
        node_id: result.node_id, write_scope: result.write_scope,
        kind: result.kind, check_target: result.check_target,
        planned_verification: result.planned_verification,
        external_scope: result.external_scope || [],
        access_mode: result.access_mode || 'workspace-write',
        started_ms: Date.now(), parent_session_id: event.sessionID });
    });
    await ctx.tool.hook('execute.after', async event => {
      const key = externalWriteKey(event.sessionID, event.id);
      const write = externalWrites.get(key);
      if (write && event.tool === 'write') {
        externalWrites.delete(key);
        if (event.status === 'completed' && write.approval === 'approved') {
          await recordExternalWrite(write, 'applied');
        } else if (write.approval !== 'denied') {
          const reason = event.error?.error?.permission ?? event.error?.permission;
          const detail = typeof reason === 'string' ? reason : 'write outcome unverified';
          await recordExternalWrite(write,
            write.approval === 'approved' ? 'unverified' : 'blocked_by_host', detail);
        }
      }
      if ((event.status === 'error' || event.error) &&
          ['bash', 'shell', 'write', 'edit'].includes(event.tool))
        await ctx.storage.set(`tool_error/${event.sessionID}`, true);
      if (event.tool === 'read' && event.status === 'completed' &&
          ['micronus-prime', 'liege-maximo'].includes(event.agent)) {
        const binding = await ctx.storage.get(`child/${event.sessionID}`);
        const target = toolPath(project, event.input?.path ?? event.input?.filePath);
        if (binding && target && await ctx.storage.get(`bound/${event.sessionID}`))
          await bridge('review_read', project, { run_id: binding.run_id, call_id: binding.call_id,
            child_session_id: event.sessionID, path: target, output_sha256: digest(event.result) });
      }
      if (event.tool === 'question') {
        // The native OpenCode question card is the only user-facing ask UI.
        // Persist its question and the structured answer in the run ledger so
        // the plan is auditable without a second text prompt.
        const call_id = event.callID || event.id || event.toolCallID;
        if (event.status !== 'completed') return;
        const selected = await ctx.session.get({ sessionID: event.sessionID });
        if (!['prima', 'thirteenth'].includes(event.agent || selected.agent)) return;
        const handoff = selected.parentID && await ctx.storage.get(`planning-request/${selected.parentID}`);
        const run_id = handoff?.run_id || await ctx.storage.get(`run/${event.sessionID}`);
        const asked = Array.isArray(event.input?.questions)
          ? event.input.questions.map(item => String(item?.question || '').trim()).filter(Boolean) : [];
        const answers = event.result?.metadata?.answers || event.result?.answers;
        if (!asked.length || !Array.isArray(answers)) return;
        for (let index = 0; index < asked.length; index += 1) {
          const answer = Array.isArray(answers[index]) ? answers[index].map(String) : [];
          try {
            const entry = { question: asked[index], answers: answer };
            if (run_id) {
              await bridge('ask', project, { run_id, ...entry }, ctx.signal);
            } else {
              const key = `intake/questions/${event.sessionID}`;
              await ctx.storage.set(key, [...await ctx.storage.get(key) || [], entry]);
            }
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
      if (!started) {
        const target = event.input?.agentID || event.input?.agent || event.input?.agentId;
        const child = childSession(event.result);
        if (target === 'thirteenth' && child) {
          await ctx.storage.set(`planning-child/${event.sessionID}`, child);
        } else if (target === 'thirteenth') {
          await ctx.storage.remove(`planning-request/${event.sessionID}`);
        }
        return; // A rejected before-hook has no dispatch to settle.
      }
      const child_session_id = childSession(event.result);
      const tool_status = nativeToolStatus(event);
      await bridge('after', project, {
        run_id: started.run_id, call_id, token: started.token, child_session_id,
        tool_status, duration_ms: Math.max(0, Date.now() - started.started_ms),
        output_sha256: digest(event.result || event.error?.message || ''),
      });
      if (child_session_id && tool_status === 'completed') {
        await ctx.storage.set(`child/${child_session_id}`, {
          run_id: started.run_id, call_id, node_id: started.node_id,
          kind: started.kind, check_target: started.check_target,
          planned_verification: started.planned_verification,
          write_scope: started.write_scope, external_scope: started.external_scope || [],
          access_mode: started.access_mode || 'workspace-write',
          parent_session_id: started.parent_session_id,
        });
        await ctx.storage.set(`access/${child_session_id}`,
          started.access_mode || 'workspace-write');
      }
    });
    if (typeof ctx.permission?.hook === 'function') {
      await ctx.permission.hook('evaluate', async evaluation => {
        if (!['edit', 'external_directory'].includes(evaluation.action) ||
            evaluation.effect === 'deny') return;
        const binding = await ctx.storage.get(`child/${evaluation.sessionID}`);
        if (!binding?.external_scope.length) return;
        const resources = evaluation.resources || [];
        if (evaluation.action === 'edit' &&
            !resources.some(resource => path.isAbsolute(resource))) return;
        const write = externalWrites.get(externalWriteKey(evaluation.sessionID, evaluation.source?.id));
        const deny = message => {
          evaluation.effect = 'deny';
          evaluation.message = message;
        };
        if (!write || resources.length !== 1)
          return deny('External access is restricted to the active single-file write');
        const { target } = write.receipt;
        if (evaluation.action === 'external_directory') {
          if (resources[0] !== path.join(path.dirname(target), '*'))
            return deny('External directory does not match the active file');
          // The directory resource is only a routing check for this exact
          // native write. There is no directory approval or saved directory rule.
          evaluation.effect = 'allow';
          return;
        }
        if (resources[0] !== target)
          return deny('External edit does not match the declared file');
        if (evaluation.metadata?.cybertron_single_file_approval === true) {
          evaluation.effect = 'ask';
          evaluation.message = write.file.exists ? 'Approve replacement of this file' : 'Approve creation of this file';
          return;
        }

        const diff = evaluation.metadata?.files?.[0];
        if (diff?.file === target && Number.isSafeInteger(diff.additions)
            && Number.isSafeInteger(diff.deletions))
          write.changedLines = diff.additions + diff.deletions;
        const status = await recordExternalWrite(write, 'requested');
        if (status.outcome !== 'requested')
          return deny(`Previous external write outcome: ${status.outcome}`);
        try {
          // Native edit uses save=["*"]. Use the same host permission action
          // with an exact resource and no reusable approval.
          await ctx.permission.assert({
            sessionID: evaluation.sessionID, agent: evaluation.agent,
            source: evaluation.source, action: 'edit', resources: [target], save: [],
            metadata: { cybertron_single_file_approval: true, target,
              operation: write.file.exists ? 'replace' : 'create',
              content_sha256: write.receipt.content_sha256 },
          });
        } catch (error) {
          write.approval = 'denied';
          const detail = error?._tag === 'Permission.BlockedError' ? 'edit' : undefined;
          await recordExternalWrite(write, detail ? 'blocked_by_host' : 'denied', detail);
          return deny(detail ? 'OpenCode denied this edit' : 'External file approval did not succeed');
        }
        let sameFile = false;
        try {
          sameFile = externalFileState(target).identity === write.file.identity;
        } catch { /* The target or its parent is no longer safe to use. */ }
        if (!sameFile) {
          write.approval = 'denied';
          await recordExternalWrite(write, 'blocked_by_host', 'target changed while awaiting approval');
          return deny('External write target changed while awaiting approval');
        }
        await recordExternalWrite(write, 'approved');
        write.approval = 'approved';
        evaluation.effect = 'allow';
      });
    }
    await ctx.session.hook('context', async event => {
      if (!shellPolicy.cybertronRoles.includes(event.agent)) return;
      const session = await ctx.session.get({ sessionID: event.sessionID });
      if (event.agent === 'thirteenth') {
        const handoff = session.parentID && await ctx.storage.get(`planning-request/${session.parentID}`);
        if (session.parentID && !handoff) throw new Error('Planner has no active handoff from prima');
        for (const tool of ['cy_ask', 'cy_runs', 'cy_resume', 'cy_escalate', 'cy_new_run',
          'cy_metrics', 'cy_check', 'cy_verify', 'cy_review_reject', 'subagent']) delete event.tools[tool];
        event.system.push({ type: 'text', text: handoff?.run_id
          ? `Cybertron replanning: call cy_state for run ${handoff.run_id} revision ${handoff.plan_revision}. Use cy_plan with operation {op: "revise", op_id, plan_revision, reason, nodes, retry_nodes}. Supply only changed/new nodes. Keep the goal, acceptance criteria, and authorized scopes. Preserve unrelated receipts. Retry failed checks after fixing their inputs.`
          : 'Cybertron planning: submit clear requests directly. Ask a native question only for a consequential ambiguity. For one exact Markdown document use alpha-trion, kind task, capability doc.write, verifiers ["scope_guard"], expected_content, and one artifact criterion bound by the node satisfies array. For business source use solus-prime and code.write. For required tests, use cy_capabilities to find an available verify target, then bind it to the criterion and producer dependencies. Submit explicit nodes with narrow scopes. Prima takes over in this session.' });
        return;
      }
      if (event.agent !== 'prima') {
        const parentRun = session.parentID && await ctx.storage.get(`run/${session.parentID}`);
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
              accessMode: binding.access_mode === 'danger-full-access' && !binding.write_scope.length
                ? 'read-only' : binding.access_mode,
              writeScope: binding.write_scope,
              externalScope: binding.external_scope,
            });
            if (event.agent === 'vector-prime' && binding.access_mode !== 'read-only') {
              for (const effect of ['allow', 'ask', 'deny'])
                for (const resource of shellPolicy.roles[event.agent][effect])
                  permissions.push({ action: 'shell', resource, effect });
            } else if (event.agent === 'vector-prime') {
              for (const resource of shellPolicy.roles[event.agent].allow)
                permissions.push({ action: 'shell', resource, effect: 'allow' });
              for (const resource of shellPolicy.roles[event.agent].deny)
                permissions.push({ action: 'shell', resource, effect: 'deny' });
            }
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
          if (binding.check_target) {
            event.system.push({ type: 'text', text: `This node requires cy_check with target "${binding.check_target}". Run that tool once now and return its real receipt to Prima.` });
          } else if (binding.planned_verification && binding.kind === 'review') {
            for (const tool of ['cy_check', 'shell', 'bash']) delete event.tools[tool];
            event.system.push({ type: 'text', text: 'Review this node using the supplied diff and permitted read-only tools. Read the relevant project files, then report findings. Executable checks belong to separate bound verify nodes.' });
          } else if (binding.kind === 'verify' && event.agent === 'megatronus') {
            const state = await bridge('state', project, { run_id: binding.run_id });
            const receipts = state.planning_context.checks.map(check => ({
              node_id: check.node_id, target: check.gate, status: check.status,
              plan_revision: check.plan_revision, receipt: check.receipt,
            }));
            event.system.push({ type: 'text', text: 'Check these kernel-bound results against the criteria, '
              + 'then call cy_verify with passed and findings. The kernel already verified the binding and hashes. '
              + 'Use the received evidence, without searching ledger files. '
              + JSON.stringify({ run_id: state.run_id, revision: state.plan_revision,
                criteria: state.intent_coverage, gates: state.passed_gates, receipts }) });
          }
        }
        delete event.tools.cy_state;
        delete event.tools.cy_runs;
        delete event.tools.cy_resume;
        delete event.tools.cy_capabilities;
        delete event.tools.cy_plan;
        delete event.tools.cy_ask;
        delete event.tools.question;
        delete event.tools.cy_templates;
        delete event.tools.cy_metrics;
        delete event.tools.subagent;
        if (event.agent !== 'liege-maximo') delete event.tools.cy_review_reject;
        if (!['quintus-prime', 'micronus-prime', 'nexus-prime', 'alchemist'].includes(event.agent))
          delete event.tools.cy_check;
        if (event.agent !== 'megatronus') delete event.tools.cy_verify;
        return;
      }
      delete event.tools.cy_review_reject;
      delete event.tools.cy_plan;
      if (event.tools.subagent) event.tools.subagent.description +=
        ' For Cybertron nodes set input.description to the exact card from cy_state, including the square brackets and |. A planning handoff to thirteenth uses a short description.';
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
      delete event.tools.cy_verify;
      delete event.tools.cy_check;
      event.system.push({ type: 'text', text:
        'Cybertron dispatcher: call cy_state first to discover a same-session plan. In another session, use cy_runs and cy_resume if the user wants to continue a persisted run. For a new request dispatch thirteenth. Call cy_state(wait=true) after every native dispatch even if the tool says it is running in the background. Follow next_actions and use the exact kernel card. Pass verify targets to their registered roles and give megatronus the acceptance criteria and the existing receipts. When next_actions names thirteenth, hand over the existing run ID, revision, failure diagnostics and receipts, then wait for the revised plan. Keep working until the ledger completes, a human decision is required, or the ledger identifies a blocker you cannot resolve.' });
    });
  },
});
