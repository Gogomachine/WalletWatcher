"""Migration script to transfer data from SQLite to PostgreSQL."""

import asyncio
import aiosqlite
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database.postgres_db import PostgresDatabase


async def migrate_data():
    """Migrate all data from SQLite to PostgreSQL."""
    load_dotenv()
    
    # Paths
    sqlite_path = os.getenv("DATABASE_PATH", "./data/bot.db")
    postgres_url = os.getenv("POSTGRES_URL", "postgresql://wallet_watcher:password@localhost:5432/wallet_watcher_db")
    
    print("=" * 60)
    print("🔄 SQLite → PostgreSQL Migration Tool")
    print("=" * 60)
    print(f"\n📁 SQLite database: {sqlite_path}")
    print(f"🐘 PostgreSQL URL: {postgres_url.split('@')[1] if '@' in postgres_url else postgres_url}")
    
    # Check if SQLite database exists
    if not Path(sqlite_path).exists():
        print(f"\n❌ SQLite database not found at: {sqlite_path}")
        print("   Create the database or check the path in .env")
        return
    
    # Connect to PostgreSQL
    print("\n🔌 Connecting to PostgreSQL...")
    pg_db = PostgresDatabase(postgres_url)
    await pg_db.connect()
    await pg_db.init_db()
    print("✅ PostgreSQL connected and initialized")
    
    # Connect to SQLite
    print("\n🔌 Connecting to SQLite...")
    sqlite_db = await aiosqlite.connect(sqlite_path)
    sqlite_db.row_factory = aiosqlite.Row
    print("✅ SQLite connected")
    
    try:
        # Migrate tracked_addresses
        print("\n📊 Migrating tracked_addresses...")
        async with sqlite_db.execute("SELECT * FROM tracked_addresses") as cursor:
            addresses = await cursor.fetchall()
            
            if not addresses:
                print("   ℹ️  No addresses to migrate")
            else:
                migrated = 0
                errors = 0
                
                for row in addresses:
                    try:
                        async with pg_db.pool.acquire() as conn:
                            await conn.execute(
                                """
                                INSERT INTO tracked_addresses 
                                (user_id, address, nickname, group_id, notifications_enabled, added_at, last_signature, last_checked)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                                ON CONFLICT (user_id, address) DO NOTHING
                                """,
                                row['user_id'],
                                row['address'],
                                row.get('nickname'),
                                row.get('group_id'),
                                bool(row.get('notifications_enabled', 1)),
                                row.get('added_at'),
                                row.get('last_signature'),
                                row.get('last_checked')
                            )
                            migrated += 1
                    except Exception as e:
                        errors += 1
                        print(f"   ⚠️  Error migrating address {row['address'][:16]}...: {e}")
                
                print(f"   ✅ Migrated {migrated} addresses ({errors} errors)")
        
        # Migrate address_groups
        print("\n📊 Migrating address_groups...")
        async with sqlite_db.execute("SELECT * FROM address_groups") as cursor:
            groups = await cursor.fetchall()
            
            if not groups:
                print("   ℹ️  No groups to migrate")
            else:
                migrated = 0
                errors = 0
                
                for row in groups:
                    try:
                        async with pg_db.pool.acquire() as conn:
                            await conn.execute(
                                """
                                INSERT INTO address_groups 
                                (user_id, name, created_at)
                                VALUES ($1, $2, $3)
                                ON CONFLICT (user_id, name) DO NOTHING
                                """,
                                row['user_id'],
                                row['name'],
                                row.get('created_at')
                            )
                            migrated += 1
                    except Exception as e:
                        errors += 1
                        print(f"   ⚠️  Error migrating group {row['name']}: {e}")
                
                print(f"   ✅ Migrated {migrated} groups ({errors} errors)")
        
        # Migrate user_settings
        print("\n📊 Migrating user_settings...")
        async with sqlite_db.execute("SELECT * FROM user_settings") as cursor:
            settings = await cursor.fetchall()
            
            if not settings:
                print("   ℹ️  No settings to migrate")
            else:
                migrated = 0
                errors = 0
                
                for row in settings:
                    try:
                        async with pg_db.pool.acquire() as conn:
                            await conn.execute(
                                """
                                INSERT INTO user_settings 
                                (user_id, notifications_enabled, bot_active, language, created_at)
                                VALUES ($1, $2, $3, $4, $5)
                                ON CONFLICT (user_id) DO NOTHING
                                """,
                                row['user_id'],
                                bool(row.get('notifications_enabled', 1)),
                                bool(row.get('bot_active', 1)),
                                row.get('language', 'ru'),
                                row.get('created_at')
                            )
                            migrated += 1
                    except Exception as e:
                        errors += 1
                        print(f"   ⚠️  Error migrating settings for user {row['user_id']}: {e}")
                
                print(f"   ✅ Migrated {migrated} user settings ({errors} errors)")
        
        # Verification
        print("\n🔍 Verification:")
        async with pg_db.pool.acquire() as conn:
            addr_count = await conn.fetchval("SELECT COUNT(*) FROM tracked_addresses")
            group_count = await conn.fetchval("SELECT COUNT(*) FROM address_groups")
            user_count = await conn.fetchval("SELECT COUNT(*) FROM user_settings")
            
            print(f"   📋 Tracked addresses: {addr_count}")
            print(f"   📁 Groups: {group_count}")
            print(f"   👤 User settings: {user_count}")
        
        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Verify the data in PostgreSQL")
        print("2. Update your .env file with POSTGRES_URL")
        print("3. Run the bot with: python main_optimized.py")
        print("4. (Optional) Backup your SQLite database: cp ./data/bot.db ./data/bot.db.backup")
        
    finally:
        await sqlite_db.close()
        await pg_db.close()
        print("\n🔌 Connections closed")


if __name__ == "__main__":
    asyncio.run(migrate_data())
