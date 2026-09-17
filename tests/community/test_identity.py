import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from werkzeug.security import check_password_hash

from community import create_app
from community.cli import migration_config
from community.config import validate_database
from community.extensions import db
from community.models import AuditEvent, User
from .conftest import login, register, token


@pytest.mark.parametrize('uri', [
    'mysql+pymysql://localhost/student_management',
    'mysql+pymysql://localhost/student_management_agent',
    'mysql+pymysql://localhost/other',
    'sqlite://', 'postgresql://localhost/community_agent', None,
])
def test_reject_noncommunity_database(uri):
    with pytest.raises(RuntimeError):
        validate_database(uri)


def test_ignore_legacy_config(monkeypatch):
    monkeypatch.setenv('AGENT_DATABASE_URL', 'mysql+pymysql://localhost/student_management')
    monkeypatch.setenv('AGENT_SECRET_KEY', 'legacy')
    app = create_app({'TESTING': True, 'SECRET_KEY': 'a' * 40,
                      'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
    assert app.config['SQLALCHEMY_DATABASE_URI'] == 'sqlite://'
    assert app.config['SESSION_COOKIE_NAME'] == 'community_session'


def test_migration_repeat_rollback_and_schema_match(app):
    with app.app_context(), db.engine.begin() as connection:
        config = migration_config(connection)
        command.upgrade(config, 'head')
        assert set(inspect(connection).get_table_names()) == {
            'user', 'audit_event', 'auth_rate_bucket', 'alembic_version',
            'post', 'post_revision', 'post_tag', 'tag', 'content_chunk', 'post_operation'}
        assert compare_metadata(MigrationContext.configure(connection), db.metadata) == []
        command.downgrade(config, 'base')
        assert inspect(connection).get_table_names() == ['alembic_version']
        command.upgrade(config, 'head')
    assert app.test_client().get('/health/ready').status_code == 200


def test_registration_password_roles_duplicate_and_isolation(app, client):
    response = register(client, 'ALICE', role='admin', active=False, id=777)
    assert response.status_code == 201
    assert response.json['role'] == 'member'
    assert response.json['username'] == 'alice'
    assert client.get('/admin').status_code == 403
    other = app.test_client()
    assert other.get('/auth/me').status_code == 401
    assert register(other, 'bob').status_code == 201
    assert client.get('/auth/me').json['username'] == 'alice'
    assert other.get('/auth/me').json['username'] == 'bob'
    assert register(other, 'Alice').status_code == 409
    with app.app_context():
        user = db.session.scalar(select(User).where(User.username == 'alice'))
        assert user.active and user.id != 777
        assert user.password_hash != 'test-password-1234'
        assert check_password_hash(user.password_hash, 'test-password-1234')
        assert len(db.session.scalars(select(User)).all()) == 2


def test_csrf_rotation_logout_and_cookie_flags(client):
    old_token = token(client)
    assert client.post('/auth/register', json={'username': 'alice', 'password': 'test-password-1234'}).status_code == 400
    response = register(client, password='abc123')
    cookie = response.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert client.post('/auth/logout', json={}, headers={'X-CSRFToken': old_token}).status_code == 400
    assert client.get('/auth/logout').status_code == 405
    assert client.post('/auth/logout', json={}, headers={'X-CSRFToken': token(client)}).status_code == 204
    assert client.get('/auth/me').status_code == 401
    assert login(client, password='wrong-password-123').status_code == 401
    assert login(client, password='abc123').status_code == 200


def test_disabled_existing_session_and_audit(app, client):
    register(client)
    result = app.test_cli_runner().invoke(args=['disable-user', '--username', 'alice', '--reason', '测试停用'])
    assert result.exit_code == 0
    assert client.get('/auth/me').status_code == 401
    assert login(client).status_code == 401
    with app.app_context():
        event = db.session.scalar(select(AuditEvent).where(AuditEvent.action == 'disable_user'))
        assert event.reason == '测试停用' and event.actor_id is None


def test_admin_cli_never_overwrites_member(app, client):
    register(client)
    runner = app.test_cli_runner()
    result = runner.invoke(args=['create-admin', '--username', 'alice'], input='new-password-1234\nnew-password-1234\n')
    assert result.exit_code != 0
    assert client.get('/auth/me').json['role'] == 'member'
    result = runner.invoke(args=['create-admin', '--username', 'admin'], input='abc123\nabc123\n')
    assert result.exit_code == 0, result.output
    other = app.test_client()
    assert login(other, 'admin', 'abc123').status_code == 200
    assert other.get('/admin').status_code == 200


def test_shared_rate_limit_no_forwarded_header_bypass(app, client):
    app.config['LOGIN_RATE_LIMIT'] = 2
    assert login(client).status_code == 401
    assert login(app.test_client()).status_code == 401
    other = app.test_client()
    response = other.post('/auth/login', json={'username': 'unknown', 'password': 'test-password-1234'},
                          headers={'X-CSRFToken': token(other), 'X-Forwarded-For': '8.8.8.8'})
    assert response.status_code == 429
    assert response.headers['Retry-After']


def test_concurrent_registration_unique(app):
    def attempt(_):
        return register(app.test_client(), 'sameuser').status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(attempt, range(2))) == [201, 409]


@pytest.mark.parametrize('payload', [[], None, {'username': ['alice'], 'password': 'test-password-1234'},
    {'username': 'alice', 'password': 'short'}, {'username': '<script>', 'password': 'test-password-1234'},
    {'username': 'alice', 'password': 'a' * 129}])
def test_invalid_input(client, payload):
    response = client.post('/auth/register', json=payload, headers={'X-CSRFToken': token(client)})
    assert response.status_code == 400


def test_pages_security_headers_no_legacy_routes(client):
    for path in ['/', '/auth/login', '/auth/register']:
        response = client.get(path)
        assert response.status_code == 200
        assert 'Community' in response.text
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'form-action' in response.headers['Content-Security-Policy']
    for path in ['/students', '/grades', '/agent', '/files', '/static/uploads/example.txt']:
        assert client.get(path).status_code == 404
    assert client.get('/admin').status_code == 401


def test_factory_does_not_import_legacy_modules():
    code = "from community import create_app; import sys; create_app({'TESTING': True, 'SECRET_KEY': 'x'*40, 'SQLALCHEMY_DATABASE_URI': 'sqlite://'}); assert 'app' not in sys.modules and 'config' not in sys.modules"
    subprocess.run([sys.executable, '-c', code], check=True)


def test_missing_database_schema_returns_safe_error():
    app = create_app({'TESTING': True, 'SECRET_KEY': 'x' * 40, 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
    client = app.test_client()
    response = client.get('/health/ready')
    assert response.status_code == 503
    assert 'SELECT' not in response.text and 'sqlite' not in response.text
    assert client.get('/health/live').status_code == 200


def test_missing_schema_with_logged_in_cookie_is_safe(client):
    register(client)
    with client.application.app_context(), db.engine.begin() as connection:
        command.downgrade(migration_config(connection), 'base')
    response = client.get('/auth/me')
    assert response.status_code == 503
    assert 'SELECT' not in response.text
