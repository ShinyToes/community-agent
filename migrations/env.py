from alembic import context
from sqlalchemy import create_engine, pool

from community.config import settings, validate_database
from community.extensions import db
from community import models  # noqa: F401

config = context.config
target_metadata = db.metadata


def run(connection):
    validate_database(connection.engine.url,
                      testing=config.attributes.get('community_testing', False))
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    url = validate_database(settings()['SQLALCHEMY_DATABASE_URI'])
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get('connection') is not None:
    run(config.attributes['connection'])
else:
    url = validate_database(settings()['SQLALCHEMY_DATABASE_URI'])
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run(connection)
