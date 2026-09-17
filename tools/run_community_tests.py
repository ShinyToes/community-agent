"""Run community tests without loading legacy conftest or legacy DB settings."""
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[1]
parent = root / 'instance' / 'community-test-runs'
parent.mkdir(parents=True, exist_ok=True)
raise SystemExit(subprocess.call([
    sys.executable, '-m', 'pytest', 'tests/community', '--confcutdir=tests/community', '--import-mode=importlib',
    '-q', '--tb=short', '--basetemp', str(parent / uuid.uuid4().hex), *sys.argv[1:],
], cwd=root))
