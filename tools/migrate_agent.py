"""Add only Agent tables; never create/alter existing business tables."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect
from app import create_app
from app.extensions import db
from app import agent_models


def migrate():
    app = create_app()
    with app.app_context():
        names = inspect(db.engine).get_table_names()
        if not {'user', 'student', 'enrollment', 'grade'}.issubset(names):
            raise SystemExit('Initialize the independent business database first.')
        tables = [table for table in db.metadata.sorted_tables if table.name.startswith('agent_')]
        db.metadata.create_all(db.engine, tables=tables, checkfirst=True)
        print('Agent tables are present; existing business tables were not changed.')


if __name__ == '__main__':
    migrate()
