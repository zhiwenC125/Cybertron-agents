/**
 * Cybertron tools for DeepSeek Harness.
 *
 * The plugin is a transport: it spawns the deterministic Python kernel and
 * returns its JSON. It never decides node state, gate evidence, or plan
 * validity itself. The preset that mounts it is the only place the cy_* tools
 * exist, so a normal DSH session does not inherit the orchestrator surface.
 *
 * The bundle must not import `@deepseek-ai/dsh-tools`: a profile/link-installed
 * bundle resolves from its own directory, while DSH packages live in the
 * installation. The registry accepts the plain tool definition below, so the
 * bundle stays loadable without a profile dependency on DSH internals.
 */
import { callBridge, hostIdOf, jsonResult } from './bridge.js'

const defineTool = definition => definition

export const name = 'cybertron-dsh'
export const inject = ['tools', 'workingDirectory']

const jsonOutput = {
  schema: { type: 'string' },
  render: (_args, value) => [{ type: 'text', text: value }],
}

export function apply(ctx, config = {}) {
  const projectOf = async exec => {
    if (exec.agent === undefined) return process.cwd()
    return ctx.workingDirectory.ensure(exec.agent, exec.signal)
  }

  ctx.tools.register(defineTool({
    name: 'cy_plan',
    description: 'Create or revise a validated Cybertron plan graph. Provide a JSON payload: '
      + 'one of {"node": {...}}, {"nodes": [...]}, {"template_id": ..., "objective": ...}, '
      + 'or {"operation": {...}} with "run_id". Optional fields: write_scope, test_scope, '
      + 'skip (read-only capabilities), request_class, access_mode '
      + '(read-only | workspace-write | danger-full-access), slug (English folder name), '
      + 'session_title. Returns the run state as JSON.',
    parameters: {
      payload: { type: 'string', required: true, description: 'JSON object describing the plan or one graph operation.' },
    },
    output: jsonOutput,
    async execute(args, exec) {
      let payload
      try { payload = JSON.parse(args.payload) } catch { throw new Error('payload must be a JSON object') }
      if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
        throw new Error('payload must be a JSON object')
      }
      const project = await projectOf(exec)
      let result
      if (payload.operation) {
        if (typeof payload.run_id !== 'string' || !payload.run_id) throw new Error('operation requires run_id')
        result = await callBridge('plan_op', project,
          { run_id: payload.run_id, operation: payload.operation }, exec.signal, config)
      } else {
        result = await callBridge('plan', project, {
          node: payload.node, nodes: payload.nodes,
          template_id: payload.template_id, objective: payload.objective,
          write_scope: payload.write_scope, test_scope: payload.test_scope,
          skip: payload.skip, request_class: payload.request_class,
          access_mode: payload.access_mode, slug: payload.slug,
          session_title: payload.session_title,
          host_session_id: hostIdOf(exec),
        }, exec.signal, config)
      }
      return jsonResult(result)
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cy_state',
    description: 'Read one Cybertron run ledger projection, including node status, ready nodes, gates, and repair feedback.',
    parameters: { run_id: { type: 'string', required: true, description: 'Cybertron run id.' } },
    output: jsonOutput,
    async execute(args, exec) {
      return jsonResult(await callBridge('state', await projectOf(exec),
        { run_id: args.run_id }, exec.signal, config))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cy_ask',
    description: 'Record a human question on a Cybertron run; the kernel refuses during an active dispatch.',
    parameters: {
      run_id: { type: 'string', required: true, description: 'Cybertron run id.' },
      question: { type: 'string', required: true, description: 'Question for the human.' },
    },
    output: jsonOutput,
    async execute(args, exec) {
      return jsonResult(await callBridge('ask', await projectOf(exec),
        { run_id: args.run_id, question: args.question }, exec.signal, config))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cy_templates',
    description: 'List learned plan templates distilled from completed runs, with node, dispatch, and intervention counts.',
    parameters: {},
    output: jsonOutput,
    async execute(_args, exec) {
      return jsonResult(await callBridge('templates', await projectOf(exec), {}, exec.signal, config))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cy_metrics',
    description: 'Read the Cybertron metrics panel, or one run projection when run_id is given.',
    parameters: { run_id: { type: 'string', description: 'Optional Cybertron run id.' } },
    output: jsonOutput,
    async execute(args, exec) {
      return jsonResult(await callBridge('metrics', await projectOf(exec),
        { run_id: args.run_id }, exec.signal, config))
    },
  }))
}
