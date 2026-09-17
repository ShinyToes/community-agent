"""Explicit, non-destructive account creation for the independent project DB."""
import argparse
from getpass import getpass
from app import create_app
from app.extensions import db
from app.models import User, Student


def main():
    parser = argparse.ArgumentParser(description='创建单个账号；不会覆盖已有账号或删除账号')
    parser.add_argument('--username', required=True)
    parser.add_argument('--role', choices=['admin', 'student'], required=True)
    parser.add_argument('--student-id')
    args = parser.parse_args()
    password = getpass('设置密码（至少12个字符）: ')
    if len(password) < 12 or password != getpass('再次输入密码: '):
        parser.error('密码过短或两次输入不一致')
    app = create_app()
    with app.app_context():
        if User.query.filter_by(username=args.username).first():
            parser.error('账号已存在，不执行密码重置')
        if args.role == 'student' and (not args.student_id or not db.session.get(Student, args.student_id)):
            parser.error('学生账号必须关联已存在的学号')
        db.session.add(User(username=args.username, role=args.role,
                            related_id=args.student_id if args.role == 'student' else None,
                            password=User.hash_password(password), is_active=True))
        db.session.commit()
        print('账号创建成功')


if __name__ == '__main__':
    main()
