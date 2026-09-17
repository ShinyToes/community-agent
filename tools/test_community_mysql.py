"""Own an ephemeral test Compose project on 13308; never reset the real community DB."""
from pathlib import Path
import os
import subprocess
import sys
import uuid

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / '.env.community')
url = make_url(values['COMMUNITY_DATABASE_URL'])
if url.database != 'community_agent' or url.host != '127.0.0.1' or url.port not in (13307, 13309):
    raise SystemExit('This test helper requires the generated local community configuration.')
environment = {**os.environ, 'COMMUNITY_MYSQL_PORT': '13308',
    'COMMUNITY_TEST_DATABASE_URL': url.set(port=13308).render_as_string(hide_password=False)}
compose = ['docker', '--context', 'desktop-linux', 'compose', '--env-file', '.env.community',
           '-f', 'compose.community.yaml', '-p', 'community-agent-identity-tests-' + uuid.uuid4().hex[:10]]
# No bind mounts, no real instance data: this named test project owns its test volume.
try:
    subprocess.run([*compose, 'up', '-d', '--wait', '--wait-timeout', '120'],
                   cwd=root, env=environment, check=True)
    result = subprocess.call([sys.executable, 'tools/run_community_tests.py'], cwd=root, env=environment)
finally:
    subprocess.run([*compose, 'down', '--volumes'], cwd=root, env=environment, check=True)
raise SystemExit(result)
