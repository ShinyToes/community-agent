"""Create local demo accounts once; write credentials only to an ignored local file."""
from pathlib import Path
import sys
import secrets
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import User, Student

if __name__ == '__main__':
    app = create_app()
    output = Path(app.instance_path) / 'demo-login.txt'
    with app.app_context():
        if User.query.first() or output.exists():
            raise SystemExit('Accounts or login file already exist; nothing overwritten.')
        if not db.session.get(Student, 'S2027001'):
            raise SystemExit('Create fictional demo data first.')
        entries = []
        for username, role, sid in [('demo_admin', 'admin', None), ('demo_student', 'student', 'S2027001')]:
            password = secrets.token_urlsafe(20)
            db.session.add(User(username=username, password=User.hash_password(password),
                                role=role, related_id=sid, is_active=True))
            entries.append(username + ': ' + password)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Rollback if the private credential file cannot be written.
        output.write_text('\n'.join(entries) + '\n', encoding='utf-8')
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            output.unlink(missing_ok=True)
            raise
        print('Demo accounts created; credentials are in instance/demo-login.txt (not printed).')
