"""M1 tool-backed 1/4/9-node plan-shape integration probe.

Each dispatch launches a real child process. No model text or fake host receipt
is used as completion evidence.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cybertron.graph import PlanGraph, PlanNode
from cybertron.kernel import DispatchOutcome, SingleNodeKernel


ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "docs/stages"
cases = []
for size in (1, 4, 9):
    with tempfile.TemporaryDirectory(prefix=f"cybertron-v6-m1-{size}-") as directory:
        workspace = Path(directory)
        graph = PlanGraph()
        for index in range(size):
            node = PlanNode(
                node_id=f"n{index}", kind="task", capability="doc.write",
                role="alpha-trion", objective=f"Write docs/n{index}.md",
                depends_on=(f"n{index - 1}",) if index else (),
                write_scope=(f"docs/n{index}.md",),
                acceptance=(f"docs/n{index}.md exists [auto]",),
                verifiers=("scope_guard",),
            )
            graph.apply_op({"op_id": f"add-{index}", "plan_revision": graph.revision,
                            "op": "add_node", "node": node.to_dict()})
        records = []
        while ready := graph.ready_nodes():
            assert len(ready) == 1
            current = ready[0]
            isolated = PlanNode.from_dict(current.to_dict())
            isolated.depends_on = ()  # The full graph already checked readiness.
            plan_path = workspace / f"plan-{current.node_id}.json"
            plan_path.write_text(json.dumps(PlanGraph([isolated]).to_dict()))
            script = ("from pathlib import Path; "
                      f"p=Path('docs/{current.node_id}.md'); "
                      "p.parent.mkdir(exist_ok=True); "
                      f"p.write_text('{current.node_id}'); print(p)")
            tool_record = {}

            def dispatch(node, context):
                command = [sys.executable, "-c", script]
                completed = subprocess.run(command, cwd=workspace, capture_output=True)
                output = completed.stdout + completed.stderr
                tool_record.update({"cmd": "python3 -c " + repr(script),
                                    "exit": completed.returncode,
                                    "utc": datetime.now(timezone.utc).isoformat(),
                                    "sha256": hashlib.sha256(output).hexdigest(),
                                    "source": "tool"})
                return DispatchOutcome(command=tool_record["cmd"],
                                       exit_code=completed.returncode,
                                       output=output, source="tool")

            result = SingleNodeKernel(workspace, plan_path, current.node_id).run(dispatch)
            assert result.status == "completed", (size, current.node_id, result)
            current.status = result.status
            events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
            assert events[-1]["evidence"]["source"] == "tool"
            records.append({"node_id": current.node_id, "tool": tool_record,
                            "artifact_sha256": hashlib.sha256(
                                (workspace / "docs" / f"{current.node_id}.md").read_bytes()).hexdigest(),
                            "events_sha256": hashlib.sha256(result.events_path.read_bytes()).hexdigest(),
                            "status": result.status})
        assert len(records) == size
        cases.append({"node_count": len(graph.nodes), "dispatch_count": len(records),
                      "plan_revision": graph.revision, "records": records})

output = STAGE / "v6-m1-plan-shapes.json"
output.write_text(json.dumps({"source": "tool", "cases": cases}, ensure_ascii=False, indent=2) + "\n")
print("M1 tool-backed plan shapes: " + ", ".join(
    f"{case['node_count']} nodes / {case['dispatch_count']} dispatches" for case in cases))
