"""Local isolated database lifecycle. Never deletes a database or volume."""
from pathlib import Path
import argparse
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / 'instance' / 'mysql.env'
COMPOSE = ['docker', 'compose', '--env-file', str(ENV), '-f', str(ROOT / 'compose.yaml')]


def configure():
    config = ROOT / '.env.agent'
    if ENV.exists() or config.exists():
        if not (ENV.exists() and config.exists()):
            raise SystemExit('已有部分配置；不会覆盖，请手动核对 .env.agent 与 instance/mysql.env。')
        print('Reusing existing project configuration.')
        return
    ENV.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_hex(24)
    ENV.write_text('MYSQL_ROOT_PASSWORD=' + secrets.token_hex(24) + '\nMYSQL_PASSWORD=' + password + '\n', encoding='utf-8')
    config.write_text('AGENT_SECRET_KEY=' + secrets.token_hex(32)
        + '\nAGENT_DATABASE_URL=mysql+pymysql://student_agent:' + password
        + '@127.0.0.1:13306/student_management_agent?charset=utf8mb4'
        + '\nDEEPSEEK_API_KEY=\nDEEPSEEK_MODEL=deepseek-chat\n'
        + 'CURRENT_ACADEMIC_YEAR=\nCURRENT_SEMESTER=\nOCR_EXECUTABLE=\n',
        encoding='utf-8')
    print('Project configuration created. Credentials are stored locally and not printed.')


def mysql(sql):
    command = COMPOSE + ['exec', '-T', 'mysql', 'sh', '-c',
                         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --default-character-set=utf8mb4 -uroot -N -B']
    result = subprocess.run(command, input=sql, text=True, encoding='utf-8',
                            capture_output=True, cwd=ROOT)
    if result.returncode:
        # DDL errors have no login secrets in input; surface bounded diagnostic.
        raise SystemExit(result.stderr[-3000:])
    return result.stdout


def initialize():
    count = mysql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='student_management_agent';")
    if int(count.strip()) != 0:
        raise SystemExit('Database already contains tables; initialization refused. Use additive migrations.')
    names = ['01_schema.sql', '01b_college_update.sql', '01c_physical_exam.sql',
             '01d_course_weights.sql', '03_functions.sql', '02_procedures.sql',
             '04_triggers.sql', '06_gpa_4_3_sync.sql']
    sql = ['ALTER DATABASE student_management_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;']
    for name in names:
        content = (ROOT / 'sql' / name).read_text(encoding='utf-8-sig')
        content = '\n'.join(line for line in content.splitlines()
                            if not line.strip().upper().startswith(('CREATE DATABASE', 'DROP DATABASE')))
        sql.append(content)
    mysql('\n'.join(sql))
    print('Initialized only student_management_agent; original lab database was not accessed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['configure', 'start', 'status', 'init', 'stop'])
    action = parser.parse_args().action
    if action == 'configure':
        configure()
    elif action == 'init':
        initialize()
    else:
        args = {'start': ['up', '-d', '--wait'], 'status': ['ps'], 'stop': ['stop']}[action]
        raise SystemExit(subprocess.call(COMPOSE + args, cwd=ROOT))
