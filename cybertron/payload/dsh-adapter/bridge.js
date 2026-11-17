/**
 * Transport-only helpers for the Cybertron DSH adapter. This module has no
 * dsh package imports, so it can be tested with plain Node against the real
 * Python bridge.
 */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const MAX_OUTPUT = 2 * 1024 * 1024
const ADAPTER_DIR = path.dirname(fileURLToPath(import.meta.url))

export function pythonPathRoots(project) {
  // A linked/source bundle lives beside `cybertron/`; a packed npm bundle
  // exposes the Python runtime as a sibling `cybertron-runtime/` directory.
  // Resolve both before falling back to the caller's project or environment.
  return [...new Set([
    path.resolve(ADAPTER_DIR, '..', 'cybertron-runtime'),
    path.resolve(ADAPTER_DIR, '..', '..'),
    project,
  ].filter(Boolean))]
}

export function callBridge(operation, project, payload, signal, config = {}) {
  const python = config.python || process.env.CYBERTRON_PYTHON || 'python3'
  const timeoutMs = Number(config.timeoutMs) > 0 ? Number(config.timeoutMs) : 120000
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-m', 'cybertron.host_v6_cli', operation, '--project', project], {
      cwd: project,
      shell: false,
      env: { ...process.env,
        PYTHONPATH: [...pythonPathRoots(project), process.env.PYTHONPATH]
          .filter(Boolean).join(path.delimiter) },
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (error, value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (error) reject(error)
      else resolve(value)
    }
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      finish(new Error(`Cybertron bridge timed out after ${timeoutMs}ms`))
    }, timeoutMs)
    child.on('error', error => finish(error))
    child.stdout.on('data', chunk => {
      stdout += chunk
      if (stdout.length > MAX_OUTPUT) {
        child.kill('SIGKILL')
        finish(new Error('Cybertron bridge output exceeded the limit'))
      }
    })
    child.stderr.on('data', chunk => { stderr += chunk })
    child.on('close', code => {
      let result
      try { result = JSON.parse(stdout) } catch { result = null }
      if (code !== 0) {
        finish(new Error(result?.error || stderr.slice(-800) || 'Cybertron bridge failed'))
        return
      }
      if (!result) {
        finish(new Error('Cybertron bridge returned invalid JSON'))
        return
      }
      finish(undefined, result)
    })
    if (signal) {
      if (signal.aborted) {
        child.kill('SIGKILL')
        finish(new Error('tool call aborted'))
        return
      }
      signal.addEventListener('abort', () => {
        child.kill('SIGKILL')
        finish(new Error('tool call aborted'))
      }, { once: true })
    }
    child.stdin.end(JSON.stringify(payload))
  })
}

export function jsonResult(value) {
  return JSON.stringify(value)
}

export function hostIdOf(exec) {
  const agent = exec?.agent
  for (const value of [agent?.id, agent?.session?.id, agent?.sessionID]) {
    if (typeof value === 'string' && value) return value
  }
  return 'dsh'
}
