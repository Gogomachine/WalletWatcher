"""Database module for storing tracked addresses and user data."""

import aiosqlite
from typing import List, Optional, Dict
from datetime import datetime
import os


class Database:
    """SQLite database manager for the bot."""

    def __init__(self, db_path: str):
        """Initialize database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def init_db(self):
        """Initialize database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # Table for tracked addresses
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tracked_addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    address TEXT NOT NULL,
                    nickname TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_signature TEXT,
                    last_checked TIMESTAMP,
                    UNIQUE(user_id, address)
                )
            """)

            # Table for user settings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    notifications_enabled INTEGER DEFAULT 1,
                    language TEXT DEFAULT 'ru',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Index for faster queries
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_addresses
                ON tracked_addresses(user_id)
            """)

            await db.commit()

    async def add_tracked_address(
        self,
        user_id: int,
        address: str,
        nickname: Optional[str] = None
    ) -> bool:
        """Add address to tracking list.

        Args:
            user_id: Telegram user ID
            address: Solana address to track
            nickname: Optional nickname for the address

        Returns:
            True if added successfully, False if already exists
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO tracked_addresses (user_id, address, nickname)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, address, nickname)
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            # Address already tracked by this user
            return False

    async def remove_tracked_address(self, user_id: int, address: str) -> bool:
        """Remove address from tracking list.

        Args:
            user_id: Telegram user ID
            address: Solana address to stop tracking

        Returns:
            True if removed, False if not found
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM tracked_addresses WHERE user_id = ? AND address = ?",
                (user_id, address)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_user_tracked_addresses(self, user_id: int) -> List[Dict]:
        """Get all addresses tracked by a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of tracked address records
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT address, nickname, added_at, last_signature, last_checked
                FROM tracked_addresses
                WHERE user_id = ?
                ORDER BY added_at DESC
                """,
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_all_tracked_addresses(self) -> List[Dict]:
        """Get all tracked addresses from all users.

        Returns:
            List of all tracked address records with user_id
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, user_id, address, nickname, last_signature, last_checked
                FROM tracked_addresses
                """
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_last_signature(
        self,
        address_id: int,
        signature: str
    ):
        """Update last known signature for an address.

        Args:
            address_id: Address record ID
            signature: Transaction signature
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE tracked_addresses
                SET last_signature = ?, last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (signature, address_id)
            )
            await db.commit()

    async def get_user_settings(self, user_id: int) -> Dict:
        """Get user settings.

        Args:
            user_id: Telegram user ID

        Returns:
            User settings dict
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_settings WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                else:
                    # Create default settings
                    await db.execute(
                        "INSERT INTO user_settings (user_id) VALUES (?)",
                        (user_id,)
                    )
                    await db.commit()
                    return {
                        "user_id": user_id,
                        "notifications_enabled": 1,
                        "language": "ru"
                    }

    async def update_notifications_enabled(
        self,
        user_id: int,
        enabled: bool
    ):
        """Update notification settings for user.

        Args:
            user_id: Telegram user ID
            enabled: Whether notifications are enabled
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_settings (user_id, notifications_enabled)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET notifications_enabled = ?
                """,
                (user_id, int(enabled), int(enabled))
            )
            await db.commit()

    async def get_tracked_address_count(self, user_id: int) -> int:
        """Get number of addresses tracked by user.

        Args:
            user_id: Telegram user ID

        Returns:
            Number of tracked addresses
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM tracked_addresses WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
