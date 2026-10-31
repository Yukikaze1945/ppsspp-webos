#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Read a checkout revision or the provenance of a populated source archive."""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
component = sys.argv[1]
path = root / component
if not path.is_dir():
    raise SystemExit(f"Missing source directory: {component}")
if (path / '.git').exists():
    print(subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip())
else:
    snapshot = json.loads((root / 'SOURCE_SNAPSHOT.json').read_text())
    print(snapshot['components'][component]['commit'])
