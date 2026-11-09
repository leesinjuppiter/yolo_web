from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import database_url
from app.core.database import Base
from app.dataset import models  # noqa: F401 - register schema metadata


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url(), poolclass=NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
