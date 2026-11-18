# Cybertron for DeepSeek Harness

This bundle adds a `Cybertron` agent preset to DeepSeek Harness. The preset
mounts the `cy_*` tools backed by the deterministic Cybertron kernel in the
current working directory. Installing the bundle does not make `cy_*` tools
available to other presets or sessions.

## What it provides

| Tool | Purpose |
| --- | --- |
| `cy_plan` | Create a validated plan graph, seed one from a learned template, or apply one revisioned graph operation. |
| `cy_state` | Read the run ledger projection: node status, ready nodes, gates, repair feedback. |
| `cy_ask` | Record a human question on the run; refused during an active dispatch. |
| `cy_templates` | List templates distilled from fully completed runs. |
| `cy_metrics` | Read the project metrics panel or one run projection. |

The kernel owns state and evidence. The model proposes plans and graph
operations; invalid capabilities, roles, write scopes, dependencies, and
stale revisions are rejected by the kernel, not by prompt text.

## Requirements

- The bundle resolves the Python kernel from its packaged sibling
  (`cybertron-runtime`) or a linked checkout; the target project does not need
  to contain the Cybertron source. Set the `python` config field to a different
  interpreter when needed, and `PYTHONPATH` is composed automatically.
- A native subagent provider is composed in the profile. The preset declares a
  `subagent` tool but does not supply the provider.
- Dispatch binding for DSH child sessions (per-node write scope and verified
  child receipts) is not implemented by this bundle yet. Until it is, treat
  the DSH adapter as planning and ledger access, not as a fully governed
  second host. The OpenCode host remains the one with native dispatch binding.
- The DSH preset is a single `prima` persona, so it keeps `cy_plan` for
  compatibility. The OpenCode 13-role composition splits plan authorship to
  `thirteenth` and dispatch to `prima`; DSH does not yet expose that split.

## Install

Install the bundle directory with the plugin manager or:

```sh
dsh plugin --profile <profile> add /path/to/cybertron/dsh_adapter
```

Then start a new session and select the `Cybertron` preset.
