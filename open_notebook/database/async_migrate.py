"""
Async SQL migration system for Postgres/pgvector.
"""

import os
from pathlib import Path
from typing import List

from loguru import logger

from .repository import db_connection, repo_query

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class AsyncMigration:
    """Handles individual SQL migration operations with async support."""

    def __init__(self, version: int, path: Path, sql: str) -> None:
        self.version = version
        self.path = path
        self.sql = sql

    @classmethod
    def from_file(cls, file_path: Path) -> "AsyncMigration":
        version = int(file_path.name.split("_", 1)[0])
        sql = file_path.read_text(encoding="utf-8")
        embedding_dimension = os.getenv("OPEN_NOTEBOOK_EMBEDDING_DIMENSION", "1536")
        sql = sql.replace("{{EMBEDDING_DIMENSION}}", embedding_dimension)
        return cls(version=version, path=file_path, sql=sql)

    async def run(self) -> None:
        try:
            async with db_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(self.sql)
                    await cursor.execute(
                        """
                        INSERT INTO _sbl_migrations (version, name)
                        VALUES (%s, %s)
                        ON CONFLICT (version) DO NOTHING
                        """,
                        (self.version, self.path.name),
                    )
                await connection.commit()
        except Exception as e:
            logger.error(f"Migration {self.path.name} failed: {str(e)}")
            raise


class AsyncMigrationRunner:
    """Runs pending migrations in version order."""

    def __init__(self, migrations: List[AsyncMigration]) -> None:
        self.migrations = sorted(migrations, key=lambda item: item.version)

    async def run_all(self) -> None:
        current_version = await get_latest_version()
        for migration in self.migrations:
            if migration.version > current_version:
                logger.info(f"Running migration {migration.version}: {migration.path.name}")
                await migration.run()


class AsyncMigrationManager:
    """Main migration manager with async support."""

    def __init__(self):
        self.up_migrations = [
            AsyncMigration.from_file(path)
            for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
        ]
        self.runner = AsyncMigrationRunner(self.up_migrations)

    async def ensure_migrations_table(self) -> None:
        async with db_connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS _sbl_migrations (
                        version integer PRIMARY KEY,
                        name text NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
            await connection.commit()

    async def get_current_version(self) -> int:
        await self.ensure_migrations_table()
        return await get_latest_version()

    async def needs_migration(self) -> bool:
        current_version = await self.get_current_version()
        latest_known = max((migration.version for migration in self.up_migrations), default=0)
        return current_version < latest_known

    async def run_migration_up(self):
        await self.ensure_migrations_table()
        current_version = await self.get_current_version()
        logger.info(f"Current version before migration: {current_version}")

        if await self.needs_migration():
            await self.runner.run_all()
            new_version = await self.get_current_version()
            logger.info(f"Migration successful. New version: {new_version}")
        else:
            logger.info("Database is already at the latest version")


async def get_latest_version() -> int:
    """Get the latest version from the migrations table."""
    try:
        versions = await get_all_versions()
        if not versions:
            return 0
        return max(version["version"] for version in versions)
    except Exception:
        return 0


async def get_all_versions() -> List[dict]:
    """Get all versions from the migrations table."""
    try:
        return await repo_query("SELECT * FROM _sbl_migrations ORDER BY version")
    except Exception:
        return []
