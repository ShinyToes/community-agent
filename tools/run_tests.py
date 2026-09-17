"""Run isolated tests with temporary files inside this project."""
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[1]
parent = root / 'instance' / 'test-runs'
parent.mkdir(parents=True, exist_ok=True)
temporary = parent / uuid.uuid4().hex
raise SystemExit(subprocess.call([
    sys.executable, '-m', 'pytest', 'tests', '--ignore=tests/community', '-q', '--tb=short',
    '--basetemp', str(temporary), *sys.argv[1:],
], cwd=root))
