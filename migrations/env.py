from logging.config import fileConfig

from alembic import context

from server.app import models  # noqa: F401
from server.app.config import get_settings
from server.app.db import Base, make_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata

if context.is_offline_mode():
    url = get_settings().database_url.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
