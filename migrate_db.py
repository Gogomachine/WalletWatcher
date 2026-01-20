"""Database migration script to add group support and notifications."""

import asyncio
import aiosqlite
import os
from pathlib import Path


async def migrate_database(db_path: str):
    """Add missing columns and tables to existing database.

    Args:
        db_path: Path to database file
    """
    print(f"🔄 Migrating database: {db_path}")

    async with aiosqlite.connect(db_path) as db:
        # Check existing tables
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            tables = [row[0] for row in await cursor.fetchall()]
            print(f"✓ Existing tables: {', '.join(tables)}")

        # Check if tracked_addresses has new columns
        async with db.execute("PRAGMA table_info(tracked_addresses)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
            print(f"✓ Existing columns in tracked_addresses: {', '.join(columns)}")

        # Add missing columns to tracked_addresses
        if 'nickname' not in columns:
            print("  → Adding 'nickname' column...")
            await db.execute("ALTER TABLE tracked_addresses ADD COLUMN nickname TEXT")

        if 'group_id' not in columns:
            print("  → Adding 'group_id' column...")
            await db.execute("ALTER TABLE tracked_addresses ADD COLUMN group_id INTEGER")

        if 'notifications_enabled' not in columns:
            print("  → Adding 'notifications_enabled' column...")
            await db.execute("ALTER TABLE tracked_addresses ADD COLUMN notifications_enabled INTEGER DEFAULT 1")

        # Create address_groups table if not exists
        if 'address_groups' not in tables:
            print("  → Creating 'address_groups' table...")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS address_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, name)
                )
            """)

        # Create user_settings table if not exists
        if 'user_settings' not in tables:
            print("  → Creating 'user_settings' table...")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    notifications_enabled INTEGER DEFAULT 1,
                    language TEXT DEFAULT 'ru',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # Create indexes if not exist
        print("  → Creating indexes...")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_addresses
            ON tracked_addresses(user_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_groups
            ON address_groups(user_id)
        """)

        await db.commit()
        print("✅ Migration completed successfully!")


async def main():
    """Run migration."""
    # Default database path
    db_path = os.getenv("DATABASE_PATH", "./data/bot.db")

    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Check if database exists
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        print("Creating new database with full schema...")

        # Import and initialize database
        from src.database.db import Database
        db = Database(db_path)
        await db.init_db()
        print("✅ New database created!")
    else:
        # Run migration on existing database
        await migrate_database(db_path)

    # Verify final structure
    print("\n📊 Final database structure:")
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as cursor:
            tables = await cursor.fetchall()
            for table in tables:
                table_name = table[0]
                if table_name == 'sqlite_sequence':
                    continue
                print(f"\n  📋 {table_name}:")
                async with db.execute(f"PRAGMA table_info({table_name})") as col_cursor:
                    cols = await col_cursor.fetchall()
                    for col in cols:
                        print(f"     - {col[1]} ({col[2]})")


if __name__ == "__main__":
    asyncio.run(main())
