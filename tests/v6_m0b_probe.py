import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cybertron.graph import PlanGraph, PlanNode
from cybertron.kernel import DispatchOutcome, SingleNodeKernel

stage = Path('/Users/alanbanana/Cybertron-Agent/docs/stages')
with tempfile.TemporaryDirectory(prefix='cybertron-v6-m0b-') as directory:
    root = Path(directory)
    node = PlanNode('n1', 'task', 'doc.write', 'alpha-trion', 'Write notes',
                    write_scope=('notes.md',), acceptance=('notes exists',),
                    verifiers=('scope_guard',))
    plan = root / 'plan.json'
    plan.write_text(json.dumps(PlanGraph([node]).to_dict()))
    cases = []
    for run_id, code in [
        ('success', "from pathlib import Path; Path('notes.md').write_text('ready'); print('wrote notes')"),
        ('violation', "from pathlib import Path; Path('notes.md').write_text('retry'); Path('escape.txt').write_text('forbidden'); print('attempted escape')"),
    ]:
        def dispatch(current_node, context):
            argv = [sys.executable, '-c', code]
            completed = subprocess.run(argv, cwd=root, capture_output=True)
            return DispatchOutcome(command='python3 -c ' + repr(code),
                                   exit_code=completed.returncode,
                                   output=completed.stdout + completed.stderr,
                                   source='tool')
        result = SingleNodeKernel(root, plan, run_id).run(dispatch)
        events = [json.loads(line) for line in result.events_path.read_text().splitlines()]
        cases.append({
            'run_id': run_id,
            'status': result.status,
            'rejected_paths': result.rejected_paths,
            'events': events,
            'escape_exists_after_rollback': (root / 'escape.txt').exists(),
        })
    assert cases[0]['status'] == 'completed'
    assert cases[1]['status'] == 'failed'
    assert 'escape.txt' in cases[1]['rejected_paths']
    assert not cases[1]['escape_exists_after_rollback']
    (stage / 'v6-m0b-integration-probe.json').write_text(
        json.dumps({'source': 'tool', 'cases': cases}, ensure_ascii=False, indent=2) + '\n'
    )
print('real subprocess integration: success completed; violation failed and escape rolled back')
