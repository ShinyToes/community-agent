import os

import pytest
from alembic import command
from sqlalchemy.engine import make_url

from community import create_app
from community.extensions import db
from community.cli import migration_config


@pytest.fixture
def app(tmp_path):
    uri = os.getenv('COMMUNITY_TEST_DATABASE_URL')
    if uri:
        url = make_url(uri)
        # Destructive migration tests may run only on our separate test instance.
        assert (url.drivername, url.host, url.port, url.database) == (
            'mysql+pymysql', '127.0.0.1', 13308, 'community_agent')
    application = create_app({
        'TESTING': True, 'SECRET_KEY': 'community-test-key-' * 3,
        'SQLALCHEMY_DATABASE_URI': uri or 'sqlite:///' + (tmp_path / 'community.sqlite').as_posix(),
    })
    if uri:
        with application.app_context(), db.engine.begin() as connection:
            command.downgrade(migration_config(connection), 'base')
    result = application.test_cli_runner().invoke(args=['db-upgrade'])
    assert result.exit_code == 0, result.output + repr(result.exception)
    yield application
    with application.app_context():
        db.session.remove()
        if uri:
            with db.engine.begin() as connection:
                command.downgrade(migration_config(connection), 'base')
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def token(client):
    return client.get('/auth/csrf').json['csrf_token']


def register(client, username='alice', **extra):
    return client.post('/auth/register', json={
        'username': username, 'password': 'test-password-1234', **extra,
    }, headers={'X-CSRFToken': token(client)})


def login(client, username='alice', password='test-password-1234'):
    return client.post('/auth/login', json={'username': username, 'password': password},
                       headers={'X-CSRFToken': token(client)})
