"""Create a fresh, randomly named test database inside the project container only."""
from pathlib import Path
import os
import re
import sys
import uuid
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.local_mysql import mysql
from config import Config
from sqlalchemy.engine import make_url

if __name__ == '__main__':
    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    if url.host != '127.0.0.1' or url.port != 13306 or url.database != 'student_management_agent':
        raise SystemExit('This test runner only supports the local project container on 127.0.0.1:13306.')
    name = 'student_management_agent_test_' + uuid.uuid4().hex[:12]
    assert re.fullmatch(r'student_management_agent_test_[0-9a-f]{12}', name)
    mysql(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL ON {name}.* TO 'student_agent'@'%';")
    try:
        names = ['01_schema.sql', '01b_college_update.sql', '01c_physical_exam.sql',
                 '01d_course_weights.sql', '03_functions.sql', '02_procedures.sql',
                 '04_triggers.sql', '06_gpa_4_3_sync.sql']
        scripts = ['SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;']
        for script in names:
            sql = (ROOT / 'sql' / script).read_text(encoding='utf-8-sig')
            sql = '\n'.join(line for line in sql.splitlines() if not line.strip().upper().startswith(('CREATE DATABASE', 'DROP DATABASE')))
            scripts.append(sql.replace('student_management_agent', name))
        mysql('\n'.join(scripts))
        test_url = url.set(database=name).render_as_string(hide_password=False)
        from app import create_app
        from app.extensions import db
        app = create_app({'SECRET_KEY': 'mysql-test-only', 'SQLALCHEMY_DATABASE_URI': test_url,
                          'SQLALCHEMY_ENGINE_OPTIONS': {}, 'UPLOADED_PHOTOS_DEST': str(ROOT/'instance'/'test-uploads')})
        with app.app_context():
            db.metadata.create_all(db.engine, tables=[t for t in db.metadata.sorted_tables if t.name.startswith('agent_')])
            db.engine.dispose()
        environment = os.environ.copy()
        environment['AGENT_TEST_DATABASE_URL'] = test_url
        result = subprocess.call([sys.executable, str(ROOT/'tools/run_tests.py'),
                                  '--disable-warnings'], env=environment, cwd=ROOT)
    finally:
        # Only this freshly generated database can be dropped, never a supplied name.
        mysql(f'DROP DATABASE {name};')
    raise SystemExit(result)
