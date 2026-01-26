"""Database module for storing tracked addresses and user data."""

import aiosqlite
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import os

# ==================== НАСТРАИВАЕМЫЕ КОНСТАНТЫ ====================
# Время до сброса лимита попыток (в часах)
# Измените на меньшее значение для тестирования, например: 0.5 = 30 минут, 0.0167 = 1 минута
RESET_HOURS = 0.5  # 24 часа с последней попытки
# =================================================================


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
                    group_id INTEGER,
                    notifications_enabled INTEGER DEFAULT 1,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_signature TEXT,
                    last_checked TIMESTAMP,
                    UNIQUE(user_id, address)
                )
            """)

            # Table for groups
            await db.execute("""
                CREATE TABLE IF NOT EXISTS address_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, name)
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

            # Migrate existing tracked_addresses table if needed
            async with db.execute("PRAGMA table_info(tracked_addresses)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]

                # Add missing columns
                if 'nickname' not in columns:
                    await db.execute("ALTER TABLE tracked_addresses ADD COLUMN nickname TEXT")

                if 'group_id' not in columns:
                    await db.execute("ALTER TABLE tracked_addresses ADD COLUMN group_id INTEGER")

                if 'notifications_enabled' not in columns:
                    await db.execute("ALTER TABLE tracked_addresses ADD COLUMN notifications_enabled INTEGER DEFAULT 1")

            # Migrate user_settings table if needed
            async with db.execute("PRAGMA table_info(user_settings)") as cursor:
                settings_columns = [row[1] for row in await cursor.fetchall()]

                # Add bot_active column if missing
                if 'bot_active' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN bot_active INTEGER DEFAULT 1")

                # Add whale check limits columns if missing
                if 'whale_checks_today' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN whale_checks_today INTEGER DEFAULT 0")

                if 'last_whale_check_date' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN last_whale_check_date DATE")

                # Add new TIMESTAMP column for precise time tracking (для сброса через 24 часа)
                if 'last_whale_check_timestamp' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN last_whale_check_timestamp TIMESTAMP")

                if 'is_premium' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN is_premium INTEGER DEFAULT 0")

                # Fix NULL values in existing records (critical for increment operations)
                await db.execute("""
                    UPDATE user_settings
                    SET whale_checks_today = 0
                    WHERE whale_checks_today IS NULL
                """)

                # Add address report limits columns if missing
                if 'address_reports_today' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN address_reports_today INTEGER DEFAULT 0")

                if 'last_address_report_date' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN last_address_report_date DATE")

                # Add new TIMESTAMP column for precise time tracking (для сброса через 24 часа)
                if 'last_address_report_timestamp' not in settings_columns:
                    await db.execute("ALTER TABLE user_settings ADD COLUMN last_address_report_timestamp TIMESTAMP")

            # Index for faster queries
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_addresses
                ON tracked_addresses(user_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_groups
                ON address_groups(user_id)
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
            List of all tracked address records with user_id, group info
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT
                    t.id,
                    t.user_id,
                    t.address,
                    t.nickname,
                    t.last_signature,
                    t.last_checked,
                    t.group_id,
                    t.notifications_enabled,
                    g.name as group_name
                FROM tracked_addresses t
                LEFT JOIN address_groups g ON t.group_id = g.id
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

    async def reset_user_monitoring(self, user_id: int):
        """Reset monitoring state for all user's addresses (clear last signatures).

        This makes the bot start monitoring from current moment, ignoring old transactions.

        Args:
            user_id: Telegram user ID
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE tracked_addresses
                SET last_signature = NULL, last_checked = NULL
                WHERE user_id = ?
                """,
                (user_id,)
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
                        "language": "ru",
                        "bot_active": 1
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

    async def update_bot_active(
        self,
        user_id: int,
        active: bool
    ):
        """Update bot active status for user.

        Args:
            user_id: Telegram user ID
            active: Whether bot is active for this user
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_settings (user_id, bot_active)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET bot_active = ?
                """,
                (user_id, int(active), int(active))
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

    # Group management methods

    async def create_group(self, user_id: int, name: str) -> bool:
        """Create a new address group.

        Args:
            user_id: Telegram user ID
            name: Group name

        Returns:
            True if created successfully, False if already exists
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT INTO address_groups (user_id, name) VALUES (?, ?)",
                    (user_id, name)
                )
                await db.commit()
                return True
        except aiosqlite.IntegrityError:
            return False

    async def get_user_groups(self, user_id: int) -> List[Dict]:
        """Get all groups for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of group records
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, name, created_at,
                       (SELECT COUNT(*) FROM tracked_addresses WHERE group_id = address_groups.id) as address_count
                FROM address_groups
                WHERE user_id = ?
                ORDER BY name
                """,
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def delete_group(self, user_id: int, group_id: int) -> bool:
        """Delete a group.

        Args:
            user_id: Telegram user ID
            group_id: Group ID

        Returns:
            True if deleted
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Remove group from all addresses first
            await db.execute(
                "UPDATE tracked_addresses SET group_id = NULL WHERE group_id = ?",
                (group_id,)
            )
            cursor = await db.execute(
                "DELETE FROM address_groups WHERE id = ? AND user_id = ?",
                (group_id, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def add_address_to_group(self, user_id: int, address: str, group_id: int) -> bool:
        """Add address to a group.

        Args:
            user_id: Telegram user ID
            address: Address to add
            group_id: Group ID

        Returns:
            True if updated
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tracked_addresses
                SET group_id = ?
                WHERE user_id = ? AND address = ?
                """,
                (group_id, user_id, address)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def remove_address_from_group(self, user_id: int, address: str) -> bool:
        """Remove address from its group.

        Args:
            user_id: Telegram user ID
            address: Address to remove from group

        Returns:
            True if updated
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tracked_addresses
                SET group_id = NULL
                WHERE user_id = ? AND address = ?
                """,
                (user_id, address)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_group_addresses(self, user_id: int, group_id: int) -> List[Dict]:
        """Get all addresses in a group.

        Args:
            user_id: Telegram user ID
            group_id: Group ID

        Returns:
            List of address records
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT address, nickname, notifications_enabled, added_at
                FROM tracked_addresses
                WHERE user_id = ? AND group_id = ?
                ORDER BY added_at DESC
                """,
                (user_id, group_id)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_address_nickname(self, user_id: int, address: str, nickname: str) -> bool:
        """Update nickname for an address.

        Args:
            user_id: Telegram user ID
            address: Address
            nickname: New nickname

        Returns:
            True if updated
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tracked_addresses
                SET nickname = ?
                WHERE user_id = ? AND address = ?
                """,
                (nickname, user_id, address)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_address_notifications(self, user_id: int, address: str, enabled: bool) -> bool:
        """Update notification settings for an address.

        Args:
            user_id: Telegram user ID
            address: Address
            enabled: Whether notifications are enabled

        Returns:
            True if updated
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tracked_addresses
                SET notifications_enabled = ?
                WHERE user_id = ? AND address = ?
                """,
                (int(enabled), user_id, address)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_address_info(self, user_id: int, address: str) -> Optional[Dict]:
        """Get info about a tracked address.

        Args:
            user_id: Telegram user ID
            address: Address

        Returns:
            Address info dict or None
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT address, nickname, group_id, notifications_enabled, added_at
                FROM tracked_addresses
                WHERE user_id = ? AND address = ?
                """,
                (user_id, address)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    # Whale check limits methods

    async def get_whale_checks_remaining(self, user_id: int) -> tuple[int, int]:
        """Get remaining whale checks.

        Лимит сбрасывается через RESET_HOURS часов после последней попытки.

        Args:
            user_id: Telegram user ID

        Returns:
            Tuple of (checks_used_today, max_checks)
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Получаем текущие данные пользователя
            async with db.execute(
                "SELECT whale_checks_today, is_premium, last_whale_check_timestamp FROM user_settings WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

                if not row:
                    # Create default settings
                    await db.execute(
                        "INSERT INTO user_settings (user_id, whale_checks_today) VALUES (?, 0)",
                        (user_id,)
                    )
                    await db.commit()
                    return (0, 3)

                checks_today = row['whale_checks_today'] or 0
                is_premium = row['is_premium'] or 0
                last_check_timestamp = row['last_whale_check_timestamp']

                # Проверяем, нужно ли сбросить счётчик
                should_reset = False

                if checks_today > 0:
                    if last_check_timestamp is None:
                        # Старые данные без timestamp - сбрасываем счётчик
                        should_reset = True
                    else:
                        try:
                            # Парсим timestamp из базы
                            last_check = datetime.fromisoformat(last_check_timestamp)
                            reset_threshold = last_check + timedelta(hours=RESET_HOURS)

                            if datetime.now() >= reset_threshold:
                                # Прошло достаточно времени - сбрасываем счётчик
                                should_reset = True
                        except (ValueError, TypeError):
                            # Если timestamp некорректный - сбрасываем
                            should_reset = True

                if should_reset:
                    await db.execute(
                        """
                        UPDATE user_settings
                        SET whale_checks_today = 0, last_whale_check_timestamp = NULL
                        WHERE user_id = ?
                        """,
                        (user_id,)
                    )
                    await db.commit()
                    checks_today = 0

                # Max checks: 3 for free, 5 for premium
                max_checks = 5 if is_premium else 3

                return (checks_today, max_checks)

    async def increment_whale_check(self, user_id: int) -> bool:
        """Increment whale check counter and save timestamp.

        Сохраняет timestamp последней попытки для корректного сброса через RESET_HOURS часов.

        Args:
            user_id: Telegram user ID

        Returns:
            True if incremented successfully
        """
        current_timestamp = datetime.now().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Проверяем, нужно ли сбросить счётчик
            async with db.execute(
                "SELECT whale_checks_today, last_whale_check_timestamp FROM user_settings WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                checks_today = row['whale_checks_today'] or 0
                last_check_timestamp = row['last_whale_check_timestamp']

                # Проверяем, прошло ли RESET_HOURS часов
                should_reset = False
                if checks_today > 0:
                    if last_check_timestamp is None:
                        # Старые данные без timestamp - сбрасываем
                        should_reset = True
                    else:
                        try:
                            last_check = datetime.fromisoformat(last_check_timestamp)
                            reset_threshold = last_check + timedelta(hours=RESET_HOURS)
                            if datetime.now() >= reset_threshold:
                                should_reset = True
                        except (ValueError, TypeError):
                            should_reset = True

                if should_reset:
                    # Сбрасываем и ставим 1
                    await db.execute(
                        """
                        UPDATE user_settings
                        SET whale_checks_today = 1, last_whale_check_timestamp = ?
                        WHERE user_id = ?
                        """,
                        (current_timestamp, user_id)
                    )
                else:
                    # Просто инкрементируем
                    await db.execute(
                        """
                        UPDATE user_settings
                        SET whale_checks_today = COALESCE(whale_checks_today, 0) + 1,
                            last_whale_check_timestamp = ?
                        WHERE user_id = ?
                        """,
                        (current_timestamp, user_id)
                    )
            else:
                # Создаём нового пользователя
                await db.execute(
                    """
                    INSERT INTO user_settings (user_id, whale_checks_today, last_whale_check_timestamp)
                    VALUES (?, 1, ?)
                    """,
                    (user_id, current_timestamp)
                )

            await db.commit()
            return True

    async def decrement_whale_check(self, user_id: int) -> bool:
        """Decrement whale check counter (grant additional attempt).

        Args:
            user_id: Telegram user ID

        Returns:
            True if decremented successfully
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Ensure user settings exist
            await db.execute(
                """
                INSERT OR IGNORE INTO user_settings (user_id, whale_checks_today)
                VALUES (?, 0)
                """,
                (user_id,)
            )

            # Decrement counter (but don't go below 0)
            await db.execute(
                """
                UPDATE user_settings
                SET whale_checks_today = MAX(0, whale_checks_today - 1)
                WHERE user_id = ?
                """,
                (user_id,)
            )
            await db.commit()
            return True

    async def add_whale_checks(self, user_id: int, amount: int) -> bool:
        """Add whale check attempts to user (admin function).

        Args:
            user_id: Telegram user ID
            amount: Number of attempts to add

        Returns:
            True if added successfully
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Ensure user settings exist
            await db.execute(
                """
                INSERT OR IGNORE INTO user_settings (user_id, whale_checks_today)
                VALUES (?, 0)
                """,
                (user_id,)
            )

            # Decrease counter to give more attempts (negative checks = more available)
            await db.execute(
                """
                UPDATE user_settings
                SET whale_checks_today = MAX(0, COALESCE(whale_checks_today, 0) - ?)
                WHERE user_id = ?
                """,
                (amount, user_id)
            )
            await db.commit()
            return True

    async def update_premium_status(self, user_id: int, is_premium: bool) -> bool:
        """Update premium status for user.

        Args:
            user_id: Telegram user ID
            is_premium: Premium status

        Returns:
            True if updated
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_settings (user_id, is_premium)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET is_premium = ?
                """,
                (user_id, int(is_premium), int(is_premium))
            )
            await db.commit()
            return True

    # ==================== FREE SUBSCRIPTION LIMITS ====================

    async def get_address_reports_remaining(self, user_id: int) -> tuple[int, int]:
        """Get remaining address reports.

        Лимит сбрасывается через RESET_HOURS часов после последнего отчёта.

        Returns:
            Tuple of (reports_used_today, max_reports)
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute(
                "SELECT address_reports_today, is_premium, last_address_report_timestamp FROM user_settings WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

                if not row:
                    await db.execute(
                        "INSERT INTO user_settings (user_id, address_reports_today) VALUES (?, 0)",
                        (user_id,)
                    )
                    await db.commit()
                    return (0, 10)

                reports_today = row['address_reports_today'] or 0
                is_premium = row['is_premium'] or 0
                last_report_timestamp = row['last_address_report_timestamp']

                # Проверяем, нужно ли сбросить счётчик
                should_reset = False

                if reports_today > 0:
                    if last_report_timestamp is None:
                        # Старые данные без timestamp - сбрасываем
                        should_reset = True
                    else:
                        try:
                            last_report = datetime.fromisoformat(last_report_timestamp)
                            reset_threshold = last_report + timedelta(hours=RESET_HOURS)

                            if datetime.now() >= reset_threshold:
                                should_reset = True
                        except (ValueError, TypeError):
                            should_reset = True

                if should_reset:
                    await db.execute(
                        """
                        UPDATE user_settings
                        SET address_reports_today = 0, last_address_report_timestamp = NULL
                        WHERE user_id = ?
                        """,
                        (user_id,)
                    )
                    await db.commit()
                    reports_today = 0

                max_reports = 999999 if is_premium else 10

                return (reports_today, max_reports)

    async def increment_address_report(self, user_id: int) -> bool:
        """Increment address report counter and save timestamp."""
        current_timestamp = datetime.now().isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute(
                "SELECT address_reports_today, last_address_report_timestamp FROM user_settings WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                reports_today = row['address_reports_today'] or 0
                last_report_timestamp = row['last_address_report_timestamp']

                # Проверяем, прошло ли RESET_HOURS часов
                should_reset = False
                if reports_today > 0:
                    if last_report_timestamp is None:
                        # Старые данные без timestamp - сбрасываем
                        should_reset = True
                    else:
                        try:
                            last_report = datetime.fromisoformat(last_report_timestamp)
                            reset_threshold = last_report + timedelta(hours=RESET_HOURS)
                            if datetime.now() >= reset_threshold:
                                should_reset = True
                        except (ValueError, TypeError):
                            should_reset = True

                if should_reset:
                    await db.execute(
                        """
                        UPDATE user_settings
                        SET address_reports_today = 1, last_address_report_timestamp = ?
                        WHERE user_id = ?
                        """,
                        (current_timestamp, user_id)
                    )
                else:
                    await db.execute(
                        """
                        UPDATE user_settings
                        SET address_reports_today = COALESCE(address_reports_today, 0) + 1,
                            last_address_report_timestamp = ?
                        WHERE user_id = ?
                        """,
                        (current_timestamp, user_id)
                    )
            else:
                await db.execute(
                    """
                    INSERT INTO user_settings (user_id, address_reports_today, last_address_report_timestamp)
                    VALUES (?, 1, ?)
                    """,
                    (user_id, current_timestamp)
                )

            await db.commit()
            return True

    async def get_favorites_count(self, user_id: int) -> int:
        """Get count of tracked addresses for user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM tracked_addresses WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_groups_count(self, user_id: int) -> int:
        """Get count of groups for user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM address_groups WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_free_limits(self, user_id: int) -> dict:
        """Get all FREE subscription limits for user."""
        settings = await self.get_user_settings(user_id)
        is_premium = settings.get('is_premium', 0)

        reports_used, max_reports = await self.get_address_reports_remaining(user_id)
        whale_used, max_whale = await self.get_whale_checks_remaining(user_id)
        favorites_count = await self.get_favorites_count(user_id)
        groups_count = await self.get_groups_count(user_id)

        return {
            'is_premium': bool(is_premium),
            'reports': {'used': reports_used, 'max': max_reports, 'remaining': max_reports - reports_used},
            'whale': {'used': whale_used, 'max': max_whale, 'remaining': max_whale - whale_used},
            'favorites': {'count': favorites_count, 'max': 999999 if is_premium else 2},
            'groups': {'count': groups_count, 'max': 999999 if is_premium else 1},
        }
