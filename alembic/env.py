from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Prefer an explicit URL (tests set this); otherwise the owner/migrator URL.
# Never the runtime DATABASE_URL (app_user).
url = config.get_main_option("sqlalchemy.url")
if not url or url.startswith("driver://"):
    url = settings.MIGRATION_DATABASE_URL
    config.set_main_option("sqlalchemy.url", url)

target_metadata = None

APP_ROLE = "app_user"


def _apply_app_user_password(connection) -> None:
    """Set app_user's password from env. Not stored in versioned migrations.

    ALTER ROLE PASSWORD does not accept bind parameters; quote from env at
    upgrade time so the password never lives in alembic/versions/.
    """
    password = settings.APP_DB_PASSWORD
    if not password:
        raise RuntimeError("APP_DB_PASSWORD must be set in the environment")
    if "\x00" in password:
        raise RuntimeError("APP_DB_PASSWORD contains a NUL byte")
    exists = connection.exec_driver_sql(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
    ).scalar()
    if not exists:
        return
    quoted = password.replace("'", "''")
    connection.exec_driver_sql(f"ALTER ROLE {APP_ROLE} PASSWORD '{quoted}'")


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=url,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    with connectable.connect() as connection:
        _apply_app_user_password(connection)
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
