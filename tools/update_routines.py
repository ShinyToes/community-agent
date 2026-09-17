"""Update routines only in the isolated project DB; never rebuild tables."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.local_mysql import mysql, ROOT

if __name__ == '__main__':
    sql = ['ALTER DATABASE student_management_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;',
           'SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;']
    for name in ('03_functions.sql', '02_procedures.sql', '04_triggers.sql', '06_gpa_4_3_sync.sql'):
        sql.append((ROOT/'sql'/name).read_text(encoding='utf-8'))
    mysql('\n'.join(sql))
    print('Project routines updated; no business table was dropped.')
