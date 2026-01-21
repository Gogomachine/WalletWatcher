"""Redis caching service for performance optimization."""

import redis.asyncio as redis
import json
from typing import Optional, Any, Dict
import asyncio


class RedisCache:
    """Redis cache manager for wallet info and rate limiting."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Initialize Redis connection.

        Args:
            redis_url: Redis connection URL
        """
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None

    async def connect(self):
        """Connect to Redis."""
        self.redis = await redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=5,
            retry_on_timeout=True
        )
        # Test connection
        await self.redis.ping()
        print("✅ Redis connection established")

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            print("✅ Redis connection closed")

    # ============ Wallet Info Caching ============

    async def get_wallet_info(self, address: str) -> Optional[Dict]:
        """Get cached wallet information.

        Args:
            address: Blockchain address

        Returns:
            Cached wallet info dict or None if not in cache
        """
        key = f"wallet:{address}"
        data = await self.redis.get(key)
        if data:
            return json.loads(data)
        return None

    async def set_wallet_info(self, address: str, info: Dict, ttl: int = 300):
        """Cache wallet information.

        Args:
            address: Blockchain address
            info: Wallet information dict
            ttl: Time to live in seconds (default 5 minutes)
        """
        key = f"wallet:{address}"
        await self.redis.setex(key, ttl, json.dumps(info))

    async def invalidate_wallet_info(self, address: str):
        """Invalidate cached wallet info.

        Args:
            address: Blockchain address
        """
        key = f"wallet:{address}"
        await self.redis.delete(key)

    # ============ Balance Caching (shorter TTL) ============

    async def get_balance(self, address: str) -> Optional[float]:
        """Get cached balance.

        Args:
            address: Blockchain address

        Returns:
            Cached balance or None
        """
        key = f"balance:{address}"
        data = await self.redis.get(key)
        if data:
            return float(data)
        return None

    async def set_balance(self, address: str, balance: float, ttl: int = 60):
        """Cache balance (1 minute TTL by default).

        Args:
            address: Blockchain address
            balance: Balance value
            ttl: Time to live in seconds (default 1 minute)
        """
        key = f"balance:{address}"
        await self.redis.setex(key, ttl, str(balance))

    # ============ Rate Limiting ============

    async def check_rate_limit(self, user_id: int, max_requests: int = 10, window: int = 60) -> bool:
        """Check if user has exceeded rate limit.

        Args:
            user_id: Telegram user ID
            max_requests: Maximum requests allowed in window
            window: Time window in seconds (default 60)

        Returns:
            True if request is allowed, False if rate limited
        """
        key = f"rate_limit:{user_id}"
        count = await self.redis.get(key)

        if count and int(count) >= max_requests:
            return False

        return True

    async def increment_rate_limit(self, user_id: int, window: int = 60):
        """Increment user's request counter.

        Args:
            user_id: Telegram user ID
            window: Time window in seconds for expiration
        """
        key = f"rate_limit:{user_id}"
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        await pipe.execute()

    async def get_rate_limit_count(self, user_id: int) -> int:
        """Get current rate limit count for user.

        Args:
            user_id: Telegram user ID

        Returns:
            Number of requests in current window
        """
        key = f"rate_limit:{user_id}"
        count = await self.redis.get(key)
        return int(count) if count else 0

    async def reset_rate_limit(self, user_id: int):
        """Reset rate limit for user.

        Args:
            user_id: Telegram user ID
        """
        key = f"rate_limit:{user_id}"
        await self.redis.delete(key)

    # ============ User Data Caching ============

    async def get_user_addresses(self, user_id: int) -> Optional[list]:
        """Get cached list of user's tracked addresses.

        Args:
            user_id: Telegram user ID

        Returns:
            Cached list or None
        """
        key = f"user_addresses:{user_id}"
        data = await self.redis.get(key)
        if data:
            return json.loads(data)
        return None

    async def set_user_addresses(self, user_id: int, addresses: list, ttl: int = 30):
        """Cache user's tracked addresses list.

        Args:
            user_id: Telegram user ID
            addresses: List of address dicts
            ttl: Time to live in seconds (default 30 seconds)
        """
        key = f"user_addresses:{user_id}"
        await self.redis.setex(key, ttl, json.dumps(addresses))

    async def invalidate_user_addresses(self, user_id: int):
        """Invalidate cached user addresses.

        Args:
            user_id: Telegram user ID
        """
        key = f"user_addresses:{user_id}"
        await self.redis.delete(key)

    # ============ Transaction Signature Caching ============

    async def get_last_signature(self, address: str) -> Optional[str]:
        """Get cached last signature for address.

        Args:
            address: Blockchain address

        Returns:
            Last signature or None
        """
        key = f"last_sig:{address}"
        return await self.redis.get(key)

    async def set_last_signature(self, address: str, signature: str, ttl: int = 3600):
        """Cache last signature for address.

        Args:
            address: Blockchain address
            signature: Transaction signature
            ttl: Time to live in seconds (default 1 hour)
        """
        key = f"last_sig:{address}"
        await self.redis.setex(key, ttl, signature)

    # ============ Statistics ============

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache stats
        """
        info = await self.redis.info("stats")
        keys_count = await self.redis.dbsize()

        return {
            "total_keys": keys_count,
            "total_commands_processed": info.get("total_commands_processed", 0),
            "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
            "connected": await self.redis.ping()
        }

    # ============ Cache Warming (для предзагрузки) ============

    async def warm_cache_for_user(self, user_id: int, addresses: list):
        """Pre-warm cache with user's addresses.

        Args:
            user_id: Telegram user ID
            addresses: List of addresses to warm up
        """
        # Cache user addresses list
        await self.set_user_addresses(user_id, addresses, ttl=60)

    # ============ Batch Operations ============

    async def mget_wallet_info(self, addresses: list) -> Dict[str, Optional[Dict]]:
        """Get multiple wallet infos at once.

        Args:
            addresses: List of addresses

        Returns:
            Dict mapping address to wallet info (or None if not cached)
        """
        if not addresses:
            return {}

        keys = [f"wallet:{addr}" for addr in addresses]
        values = await self.redis.mget(keys)

        result = {}
        for addr, value in zip(addresses, values):
            if value:
                result[addr] = json.loads(value)
            else:
                result[addr] = None

        return result

    async def mset_wallet_info(self, wallet_infos: Dict[str, Dict], ttl: int = 300):
        """Set multiple wallet infos at once.

        Args:
            wallet_infos: Dict mapping address to wallet info
            ttl: Time to live in seconds
        """
        if not wallet_infos:
            return

        pipe = self.redis.pipeline()
        for address, info in wallet_infos.items():
            key = f"wallet:{address}"
            pipe.setex(key, ttl, json.dumps(info))
        await pipe.execute()

    # ============ Health Check ============

    async def health_check(self) -> bool:
        """Check if Redis is healthy.

        Returns:
            True if healthy, False otherwise
        """
        try:
            return await self.redis.ping()
        except Exception as e:
            print(f"❌ Redis health check failed: {e}")
            return False
