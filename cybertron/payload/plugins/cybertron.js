import { Plugin } from '@opencode/plugin';
import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const pluginDirectory = path.dirname(fileURLToPath(import.meta.url));

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

function runtimePath() {
  const bundled = path.resolve(pluginDirectory, '..', 'cybertron-runtime');
  if (existsSync(path.join(bundled, 'cybertron', 'plugin_cli.py'))) return bundled;
  const checkout = path.resolve(pluginDirectory, '..', '..');
  if (existsSync(path.join(checkout, 'cybertron', 'plugin_cli.py'))) return checkout;
  throw new Error('Cybertron Python runtime is missing; reinstall Cybertron agents');
}

function bridge(operation, { project, sessionID, request, runID, mode, answer }, signal) {
  return new Promise((resolve, reject) => {
    const runtime = runtimePath();
    const command = process.env.CYBERTRON_PYTHON || 'python3';
    const argv = ['-m', 'cybertron.plugin_cli', operation, '--project', project,
      '--host-session', sessionID];
    if (request) argv.push('--request', request);
    if (runID) argv.push('--run-id', runID);
    if (mode) argv.push('--mode', mode);
    if (answer) argv.push('--answer', answer);
    const child = spawn(command, argv, {
      cwd: runtime, shell: false, signal,
      env: { ...process.env, PYTHONPATH: [runtime, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) return reject(new Error(`Cybertron bridge failed: ${stderr.slice(-500)}`));
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error('Cybertron bridge returned invalid JSON')); }
    });
  });
}

export default Plugin.define({
  id: 'cybertron.runtime',
  async setup(ctx) {
    const project = ctx.location.project.canonical;
    await ctx.session.hook('prompt', async event => {
      const request = event.prompt.text?.trim();
      if (request) await ctx.storage.set(`prompt/${event.sessionID}`, request);
      const selected = await ctx.session.get({ sessionID: event.sessionID });
      if (selected.agent === 'prima') {
        const model = primaryModel(project);
        if (model) await ctx.session.switchModel({ sessionID: event.sessionID, model });
      }
    });
    await ctx.tool.transform(editor => {
      editor.add({
        name: 'cybertron_run',
        description: 'Start or advance the persistent Cybertron multiagent workflow for the latest user request. Call once before answering a new development request.',
        input: { type: 'object', properties: {
          mode: { type: 'string', enum: ['software', 'hardware'] },
          new_run: { type: 'boolean', description: 'Start a new run for a new task in the same OpenCode session' },
        }, additionalProperties: false },
        execute: async (input, context) => {
          const key = `run/${context.sessionID}`;
          const existing = await ctx.storage.get(key);
          const request = await ctx.storage.get(`prompt/${context.sessionID}`);
          const previous = await ctx.storage.get(`prompt-used/${context.sessionID}`);
          if (!existing && (typeof request !== 'string' || !request.trim())) {
            throw new Error('No user request is available for this OpenCode session');
          }
          const prior = existing ? await bridge('status', {
            project, sessionID: context.sessionID, runID: existing,
          }, context.signal) : null;
          const differentRequest = typeof request === 'string' && request !== previous;
          const shouldStart = !existing || input.new_run === true ||
            (differentRequest && (prior.status === 'completed' ||
              prior.config === 'changed' ||
              (prior.status === 'blocked' && prior.stage_id !== 1)));
          const runID = !shouldStart ? existing : (await bridge('start', {
            project, sessionID: context.sessionID, request, mode: input.mode || 'software',
          }, context.signal)).run_id;
          await ctx.storage.set(key, runID);
          const result = await bridge('continue', {
            project, sessionID: context.sessionID, runID,
            answer: !shouldStart && differentRequest ? request : undefined,
          }, context.signal);
          if (typeof request === 'string') await ctx.storage.set(`prompt-used/${context.sessionID}`, request);
          return { content: JSON.stringify(result) };
        },
      });
    });
    await ctx.session.hook('context', event => {
      if (event.agent !== 'prima') {
        delete event.tools.cybertron_run;
        return;
      }
      const expected = primaryModel(project);
      if (expected && (event.model.providerID !== expected.providerID ||
          event.model.id !== expected.id || event.model.variant !== expected.variant)) {
        throw new Error('Cybertron prima model differs from active session; run cybertron models doctor');
      }
      delete event.tools.subagent;
      event.system.push({ type: 'text', text: 'For each new user development request, call cybertron_run exactly once before answering. Pass mode=hardware only when the user explicitly requests firmware or device work; otherwise mode=software. Set new_run=true when the user starts a distinct task in this same chat. The tool owns the nine-stage ledger and all role dispatch. Do not launch subagents directly. Report the returned run ID, current stage, and block_reason exactly as returned. Do not guess why a run is blocked. Never claim fake or model-only evidence is a real test receipt.' });
    });
  },
});
