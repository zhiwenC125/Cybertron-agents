"""Show why two native writers cannot share the current global snapshot guard."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json

from cybertron.scope_guard import ScopeGuard


with TemporaryDirectory(prefix="cybertron-v6-m3-conflict-") as directory:
    root = Path(directory)
    (root / "docs").mkdir()
    first = ScopeGuard(root, ("docs/a.md",))
    second = ScopeGuard(root, ("docs/b.md",))
    first_before = first.snapshot()
    second_before = second.snapshot()
    (root / "docs/a.md").write_text("writer a")
    (root / "docs/b.md").write_text("writer b")
    report = first.verify_and_rollback(first_before)
    print(json.dumps({
        "first_rejected_paths": report.rejected_paths,
        "second_allowed_file_survived": (root / "docs/b.md").exists(),
        "second_snapshot_still_expects_no_file": "docs/b.md" not in second_before.entries,
    }))
