import re

import click
from alembic import command
from alembic.config import Config
from flask import current_app
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .config import ROOT
from .extensions import db
from .models import AuditEvent, AuthRateBucket, User


def migration_config(connection=None):
    config = Config(str(ROOT / 'alembic.community.ini'))
    if connection is not None:
        config.attributes['connection'] = connection
        config.attributes['community_testing'] = current_app.testing
    return config


def register_commands(app):
    @app.cli.command('db-upgrade')
    def db_upgrade():
        """Apply only versioned community migrations; never call legacy SQL."""
        with db.engine.begin() as connection:
            command.upgrade(migration_config(connection), 'head')
        click.echo('Community migrations are up to date.')

    @app.cli.command('create-admin')
    @click.option('--username', prompt=True)
    @click.password_option()
    def create_admin(username, password):
        """Create a new administrator; never promote/reset an existing account."""
        username = username.strip().lower()
        if not re.fullmatch(r'[a-z0-9_]{3,32}', username) or not 6 <= len(password) <= 128:
            raise click.ClickException('用户名为 3–32 位字母/数字/下划线；密码为 6–128 个字符。')
        user = User(username=username, password_hash=generate_password_hash(password), role='admin')
        db.session.add(user)
        try:
            db.session.flush()
            db.session.add(AuditEvent(actor_id=None, target_id=user.id,
                                      action='create_admin', reason='本地维护命令创建管理员'))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise click.ClickException('用户名已存在，不覆盖账号。') from None
        click.echo('Administrator created.')

    @app.cli.command('disable-user')
    @click.option('--username', required=True)
    @click.option('--reason', required=True)
    def disable_user(username, reason):
        """Local operator maintenance; account sessions expire on next request."""
        if not reason.strip() or len(reason) > 500:
            raise click.ClickException('需提供 1–500 字符处理原因。')
        user = db.session.scalar(select(User).where(User.username == username.strip().lower()).with_for_update())
        if not user:
            raise click.ClickException('用户不存在。')
        if not user.active:
            click.echo('User is already disabled.')
            return
        user.active = False
        db.session.add(AuditEvent(actor_id=None, target_id=user.id,
                                  action='disable_user', reason=reason.strip()))
        db.session.commit()
        click.echo('User disabled.')

    @app.cli.command('prune-auth-counters')
    def prune_auth_counters():
        """Remove expired rate buckets; schedule periodically on the server."""
        import time
        current = int(time.time()) // app.config['AUTH_RATE_WINDOW']
        db.session.execute(delete(AuthRateBucket).where(AuthRateBucket.window < current - 1))
        db.session.commit()
        click.echo('Expired counters removed.')
