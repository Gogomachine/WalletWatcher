"""PostgreSQL database module for production scalability."""

import asyncpg
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import os

# ==================== НАСТРАИВАЕМЫЕ КОНСТАНТЫ ====================
# Время до сброса лимита попыток (в часах)
# Измените на меньшее значение для тестирования, например: 0.5 = 30 минут, 0.0167 = 1 минута
RESET_HOURS = 0.5  # 24 часа с последней попытки
# =================================================================


class PostgresDatabase:
    """PostgreSQL database manager for the bot (production-ready, scalable)."""

    def __init__(self, connection_string: str, pool_size: int = 20, max_overflow: int = 10):
        """Initialize database connection pool.

        Args:
            connection_string: PostgreSQL connection string
                Format: postgresql://user:password@host:port/database
            pool_size: Number of connections in pool (default 20)
            max_overflow: Max overflow connections (default 10)
        """
        self.connection_string = connection_string
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create connection pool."""
        self.pool = await asyncpg.create_pool(
            self.connection_string,
            min_size=5,
            max_size=self.pool_size,
            command_timeout=60,
        )
        print(f"✅ PostgreSQL connection pool created (size: {self.pool_size})")

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            print("✅ PostgreSQL connection pool closed")

    async def init_db(self):
        """Initialize database tables with indexes for performance."""
        async with self.pool.acquire() as conn:
            # Table for tracked addresses
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tracked_addresses (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    address TEXT NOT NULL,
                    nickname TEXT,
                    group_id INTEGER,
                    notifications_enabled BOOLEAN DEFAULT TRUE,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_signature TEXT,
                    last_checked TIMESTAMP,
                    UNIQUE(user_id, address)
                )
            """)

            # Table for groups
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS address_groups (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, name)
                )
            """)

            # Table for user settings
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT PRIMARY KEY,
                    notifications_enabled BOOLEAN DEFAULT TRUE,
                    bot_active BOOLEAN DEFAULT TRUE,
                    language TEXT DEFAULT 'ru',
                    whale_checks_today INTEGER DEFAULT 0,
                    last_whale_check_date DATE,
                    is_premium BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Migrate existing user_settings table (add new columns if missing)
            try:
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS whale_checks_today INTEGER DEFAULT 0
                """)
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS last_whale_check_date DATE
                """)
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE
                """)

                # Fix NULL values in existing records (critical for increment operations)
                await conn.execute("""
                    UPDATE user_settings
                    SET whale_checks_today = 0
                    WHERE whale_checks_today IS NULL
                """)

                # Add address report limits columns
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS address_reports_today INTEGER DEFAULT 0
                """)
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS last_address_report_date DATE
                """)

                # Add new TIMESTAMP columns for precise time tracking (для сброса через 24 часа)
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS last_whale_check_timestamp TIMESTAMP
                """)
                await conn.execute("""
                    ALTER TABLE user_settings
                    ADD COLUMN IF NOT EXISTS last_address_report_timestamp TIMESTAMP
                """)
            except Exception as e:
                # Columns might already exist
                pass

            # Performance indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracked_addresses_user_id
                ON tracked_addresses(user_id)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracked_addresses_address
                ON tracked_addresses(address)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_address_groups_user_id
                ON address_groups(user_id)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracked_addresses_group_id
                ON tracked_addresses(group_id)
            """)

            print("✅ PostgreSQL tables and indexes created")

    async def add_tracked_address(
        self,
        user_id: int,
        address: str,
        nickname: Optional[str] = None
    ) -> bool:
        """Add address to tracking list.

        Args:
            user_id: Telegram user ID
            address: Blockchain address to track
            nickname: Optional nickname for the address

        Returns:
            True if added successfully, False if already exists
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO tracked_addresses (user_id, address, nickname)
                    VALUES ($1, $2, $3)
                    """,
                    user_id, address, nickname
                )
                return True
        except asyncpg.UniqueViolationError:
            return False

    async def remove_tracked_address(self, user_id: int, address: str) -> bool:
        """Remove address from tracking list.

        Args:
            user_id: Telegram user ID
            address: Address to stop tracking

        Returns:
            True if removed, False if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM tracked_addresses WHERE user_id = $1 AND address = $2",
                user_id, address
            )
            return result != "DELETE 0"

    async def get_user_tracked_addresses(self, user_id: int) -> List[Dict]:
        """Get all addresses tracked by a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of tracked address records
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT address, nickname, added_at, last_signature, last_checked
                FROM tracked_addresses
                WHERE user_id = $1
                ORDER BY added_at DESC
                """,
                user_id
            )
            return [dict(row) for row in rows]

    async def get_all_tracked_addresses(self) -> List[Dict]:
        """Get all tracked addresses from all users.

        Returns:
            List of all tracked address records with user_id, group info
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
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
            )
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
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tracked_addresses
                SET last_signature = $1, last_checked = CURRENT_TIMESTAMP
                WHERE id = $2
                """,
                signature, address_id
            )

    async def reset_user_monitoring(self, user_id: int):
        """Reset monitoring state for all user's addresses.

        Args:
            user_id: Telegram user ID
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tracked_addresses
                SET last_signature = NULL, last_checked = NULL
                WHERE user_id = $1
                """,
                user_id
            )

    async def get_user_settings(self, user_id: int) -> Dict:
        """Get user settings.

        Args:
            user_id: Telegram user ID

        Returns:
            User settings dict
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM user_settings WHERE user_id = $1",
                user_id
            )
            if row:
                return dict(row)
            else:
                # Create default settings
                await conn.execute(
                    "INSERT INTO user_settings (user_id) VALUES ($1)",
                    user_id
                )
                return {
                    "user_id": user_id,
                    "notifications_enabled": True,
                    "language": "ru",
                    "bot_active": True
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
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, notifications_enabled)
                VALUES ($1, $2)
                ON CONFLICT(user_id) DO UPDATE SET notifications_enabled = $2
                """,
                user_id, enabled
            )

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
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, bot_active)
                VALUES ($1, $2)
                ON CONFLICT(user_id) DO UPDATE SET bot_active = $2
                """,
                user_id, active
            )

    async def get_tracked_address_count(self, user_id: int) -> int:
        """Get number of addresses tracked by user.

        Args:
            user_id: Telegram user ID

        Returns:
            Number of tracked addresses
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM tracked_addresses WHERE user_id = $1",
                user_id
            )
            return result if result else 0

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
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO address_groups (user_id, name) VALUES ($1, $2)",
                    user_id, name
                )
                return True
        except asyncpg.UniqueViolationError:
            return False

    async def get_user_groups(self, user_id: int) -> List[Dict]:
        """Get all groups for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            List of group records
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, created_at,
                       (SELECT COUNT(*) FROM tracked_addresses WHERE group_id = address_groups.id) as address_count
                FROM address_groups
                WHERE user_id = $1
                ORDER BY name
                """,
                user_id
            )
            return [dict(row) for row in rows]

    async def delete_group(self, user_id: int, group_id: int) -> bool:
        """Delete a group.

        Args:
            user_id: Telegram user ID
            group_id: Group ID

        Returns:
            True if deleted
        """
        async with self.pool.acquire() as conn:
            # Remove group from all addresses first
            await conn.execute(
                "UPDATE tracked_addresses SET group_id = NULL WHERE group_id = $1",
                group_id
            )
            result = await conn.execute(
                "DELETE FROM address_groups WHERE id = $1 AND user_id = $2",
                group_id, user_id
            )
            return result != "DELETE 0"

    async def add_address_to_group(self, user_id: int, address: str, group_id: int) -> bool:
        """Add address to a group.

        Args:
            user_id: Telegram user ID
            address: Address to add
            group_id: Group ID

        Returns:
            True if updated
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tracked_addresses
                SET group_id = $1
                WHERE user_id = $2 AND address = $3
                """,
                group_id, user_id, address
            )
            return result != "UPDATE 0"

    async def remove_address_from_group(self, user_id: int, address: str) -> bool:
        """Remove address from its group.

        Args:
            user_id: Telegram user ID
            address: Address to remove from group

        Returns:
            True if updated
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tracked_addresses
                SET group_id = NULL
                WHERE user_id = $1 AND address = $2
                """,
                user_id, address
            )
            return result != "UPDATE 0"

    async def get_group_addresses(self, user_id: int, group_id: int) -> List[Dict]:
        """Get all addresses in a group.

        Args:
            user_id: Telegram user ID
            group_id: Group ID

        Returns:
            List of address records
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT address, nickname, notifications_enabled, added_at
                FROM tracked_addresses
                WHERE user_id = $1 AND group_id = $2
                ORDER BY added_at DESC
                """,
                user_id, group_id
            )
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
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tracked_addresses
                SET nickname = $1
                WHERE user_id = $2 AND address = $3
                """,
                nickname, user_id, address
            )
            return result != "UPDATE 0"

    async def update_address_notifications(self, user_id: int, address: str, enabled: bool) -> bool:
        """Update notification settings for an address.

        Args:
            user_id: Telegram user ID
            address: Address
            enabled: Whether notifications are enabled

        Returns:
            True if updated
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tracked_addresses
                SET notifications_enabled = $1
                WHERE user_id = $2 AND address = $3
                """,
                enabled, user_id, address
            )
            return result != "UPDATE 0"

    async def get_address_info(self, user_id: int, address: str) -> Optional[Dict]:
        """Get info about a tracked address.

        Args:
            user_id: Telegram user ID
            address: Address

        Returns:
            Address info dict or None
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT address, nickname, group_id, notifications_enabled, added_at
                FROM tracked_addresses
                WHERE user_id = $1 AND address = $2
                """,
                user_id, address
            )
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
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT whale_checks_today, is_premium, last_whale_check_timestamp FROM user_settings WHERE user_id = $1",
                user_id
            )

            if not row:
                # Create default settings
                await conn.execute(
                    "INSERT INTO user_settings (user_id, whale_checks_today) VALUES ($1, 0)",
                    user_id
                )
                return (0, 3)

            checks_today = row['whale_checks_today'] or 0
            is_premium = row['is_premium'] or False
            last_check_timestamp = row['last_whale_check_timestamp']

            # Проверяем, нужно ли сбросить счётчик
            should_reset = False

            if checks_today > 0:
                if last_check_timestamp is None:
                    # Старые данные без timestamp - сбрасываем
                    should_reset = True
                else:
                    try:
                        reset_threshold = last_check_timestamp + timedelta(hours=RESET_HOURS)

                        if datetime.now() >= reset_threshold:
                            should_reset = True
                    except (ValueError, TypeError):
                        should_reset = True

            if should_reset:
                await conn.execute(
                    """
                    UPDATE user_settings
                    SET whale_checks_today = 0, last_whale_check_timestamp = NULL
                    WHERE user_id = $1
                    """,
                    user_id
                )
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
        current_timestamp = datetime.now()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT whale_checks_today, last_whale_check_timestamp FROM user_settings WHERE user_id = $1",
                user_id
            )

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
                            reset_threshold = last_check_timestamp + timedelta(hours=RESET_HOURS)
                            if datetime.now() >= reset_threshold:
                                should_reset = True
                        except (ValueError, TypeError):
                            should_reset = True

                if should_reset:
                    # Сбрасываем и ставим 1
                    await conn.execute(
                        """
                        UPDATE user_settings
                        SET whale_checks_today = 1, last_whale_check_timestamp = $1
                        WHERE user_id = $2
                        """,
                        current_timestamp, user_id
                    )
                else:
                    # Просто инкрементируем
                    await conn.execute(
                        """
                        UPDATE user_settings
                        SET whale_checks_today = COALESCE(whale_checks_today, 0) + 1,
                            last_whale_check_timestamp = $1
                        WHERE user_id = $2
                        """,
                        current_timestamp, user_id
                    )
            else:
                # Создаём нового пользователя
                await conn.execute(
                    """
                    INSERT INTO user_settings (user_id, whale_checks_today, last_whale_check_timestamp)
                    VALUES ($1, 1, $2)
                    """,
                    user_id, current_timestamp
                )

            return True

    async def decrement_whale_check(self, user_id: int) -> bool:
        """Decrement whale check counter (grant additional attempt).

        Args:
            user_id: Telegram user ID

        Returns:
            True if decremented successfully
        """
        async with self.pool.acquire() as conn:
            # Ensure user settings exist
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, whale_checks_today)
                VALUES ($1, 0)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id
            )

            # Decrement counter (but don't go below 0)
            await conn.execute(
                """
                UPDATE user_settings
                SET whale_checks_today = GREATEST(0, whale_checks_today - 1)
                WHERE user_id = $1
                """,
                user_id
            )
            return True

    async def add_whale_checks(self, user_id: int, amount: int) -> bool:
        """Add whale check attempts to user (admin function).

        Args:
            user_id: Telegram user ID
            amount: Number of attempts to add

        Returns:
            True if added successfully
        """
        async with self.pool.acquire() as conn:
            # Ensure user settings exist
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, whale_checks_today)
                VALUES ($1, 0)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id
            )

            # Decrease counter to give more attempts (negative checks = more available)
            await conn.execute(
                """
                UPDATE user_settings
                SET whale_checks_today = GREATEST(0, COALESCE(whale_checks_today, 0) - $2)
                WHERE user_id = $1
                """,
                user_id, amount
            )
            return True

    async def update_premium_status(self, user_id: int, is_premium: bool) -> bool:
        """Update premium status for user.

        Args:
            user_id: Telegram user ID
            is_premium: Premium status

        Returns:
            True if updated
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, is_premium)
                VALUES ($1, $2)
                ON CONFLICT(user_id) DO UPDATE SET is_premium = $2
                """,
                user_id, is_premium
            )
            return True

    # ==================== FREE SUBSCRIPTION LIMITS ====================

    async def get_address_reports_remaining(self, user_id: int) -> tuple[int, int]:
        """Get remaining address reports.

        Лимит сбрасывается через RESET_HOURS часов после последнего отчёта.

        Returns:
            Tuple of (reports_used_today, max_reports)
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT address_reports_today, is_premium, last_address_report_timestamp FROM user_settings WHERE user_id = $1",
                user_id
            )

            if not row:
                await conn.execute(
                    "INSERT INTO user_settings (user_id, address_reports_today) VALUES ($1, 0)",
                    user_id
                )
                return (0, 10)

            reports_today = row['address_reports_today'] or 0
            is_premium = row['is_premium'] or False
            last_report_timestamp = row['last_address_report_timestamp']

            # Проверяем, нужно ли сбросить счётчик
            should_reset = False

            if reports_today > 0:
                if last_report_timestamp is None:
                    # Старые данные без timestamp - сбрасываем
                    should_reset = True
                else:
                    try:
                        reset_threshold = last_report_timestamp + timedelta(hours=RESET_HOURS)

                        if datetime.now() >= reset_threshold:
                            should_reset = True
                    except (ValueError, TypeError):
                        should_reset = True

            if should_reset:
                await conn.execute(
                    """
                    UPDATE user_settings
                    SET address_reports_today = 0, last_address_report_timestamp = NULL
                    WHERE user_id = $1
                    """,
                    user_id
                )
                reports_today = 0

            max_reports = 999999 if is_premium else 10

            return (reports_today, max_reports)

    async def increment_address_report(self, user_id: int) -> bool:
        """Increment address report counter and save timestamp."""
        current_timestamp = datetime.now()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT address_reports_today, last_address_report_timestamp FROM user_settings WHERE user_id = $1",
                user_id
            )

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
                            reset_threshold = last_report_timestamp + timedelta(hours=RESET_HOURS)
                            if datetime.now() >= reset_threshold:
                                should_reset = True
                        except (ValueError, TypeError):
                            should_reset = True

                if should_reset:
                    await conn.execute(
                        """
                        UPDATE user_settings
                        SET address_reports_today = 1, last_address_report_timestamp = $1
                        WHERE user_id = $2
                        """,
                        current_timestamp, user_id
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE user_settings
                        SET address_reports_today = COALESCE(address_reports_today, 0) + 1,
                            last_address_report_timestamp = $1
                        WHERE user_id = $2
                        """,
                        current_timestamp, user_id
                    )
            else:
                await conn.execute(
                    """
                    INSERT INTO user_settings (user_id, address_reports_today, last_address_report_timestamp)
                    VALUES ($1, 1, $2)
                    """,
                    user_id, current_timestamp
                )

            return True

    async def get_favorites_count(self, user_id: int) -> int:
        """Get count of tracked addresses for user."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM tracked_addresses WHERE user_id = $1",
                user_id
            )
            return row['cnt'] if row else 0

    async def get_groups_count(self, user_id: int) -> int:
        """Get count of groups for user."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) as cnt FROM address_groups WHERE user_id = $1",
                user_id
            )
            return row['cnt'] if row else 0

    async def get_free_limits(self, user_id: int) -> dict:
        """Get all FREE subscription limits for user."""
        settings = await self.get_user_settings(user_id)
        is_premium = settings.get('is_premium', False)

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
