from alembic import context
from researchgit.models import Base
config=context.config
target_metadata=Base.metadata
def run_migrations_offline(): context.configure(url=config.get_main_option("sqlalchemy.url"),target_metadata=target_metadata,literal_binds=True); context.run_migrations()
def run_migrations_online():
    from sqlalchemy import create_engine
    engine=create_engine(config.get_main_option("sqlalchemy.url").replace("+asyncpg", ""))
    with engine.begin() as connection:
        context.configure(connection=connection,target_metadata=target_metadata)
        context.run_migrations()
run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
