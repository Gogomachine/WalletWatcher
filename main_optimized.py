"""Optimized main bot entry point with PostgreSQL, Redis, and browser reuse."""

import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from src.solana import SolanaClient
from src.evm import EVMClient
from src.blockchain import UniversalBlockchainClient
from src.database.postgres_db import PostgresDatabase
from src.cache.redis_cache import RedisCache
from src.bot import router, init_handlers, AddressMonitor
from src.utils.screenshot_optimized import get_screenshot_service
from src.agents import AgentSystem, set_agent_system
from src.agents.handlers import register_aml_check_handlers


# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def send_notification(bot: Bot, user_id: int, message: str, photo_path: str = None):
    """Send notification to user.

    Args:
        bot: Bot instance
        user_id: Telegram user ID
        message: Message text
        photo_path: Optional path to photo file
    """
    try:
        if photo_path:
            # Send photo with caption
            from aiogram.types import FSInputFile
            from pathlib import Path

            if Path(photo_path).exists():
                photo = FSInputFile(photo_path)
                await bot.send_photo(
                    user_id,
                    photo=photo,
                    caption=message,
                    parse_mode=ParseMode.HTML
                )
                # Clean up photo file after sending
                try:
                    Path(photo_path).unlink()
                except:
                    pass
            else:
                # Fallback to text if photo doesn't exist
                await bot.send_message(
                    user_id,
                    message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
        else:
            # Send text message
            await bot.send_message(
                user_id,
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Error sending notification to {user_id}: {e}")


async def main():
    """Main bot function with optimization."""
    # Get settings from .env
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return

    # Database settings
    postgres_url = os.getenv("POSTGRES_URL", "postgresql://wallet_watcher:password@localhost:5432/wallet_watcher_db")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_fsm_url = os.getenv("REDIS_FSM_URL", "redis://localhost:6379/1")

    # RPC URLs for different networks
    solana_rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    ethereum_rpc_url = os.getenv("ETHEREUM_RPC_URL", "https://eth.llamarpc.com")
    bsc_rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
    polygon_rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    monitor_interval = int(os.getenv("MONITOR_INTERVAL", "10"))

    # Initialize bot with Redis FSM storage
    logger.info("🤖 Initializing bot...")
    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Use Redis for FSM storage (persistent across restarts)
    storage = RedisStorage.from_url(redis_fsm_url)
    dp = Dispatcher(storage=storage)

    # Initialize blockchain clients
    logger.info("🔗 Initializing blockchain clients...")

    # Solana client
    helius_api_key = os.getenv("HELIUS_API_KEY")
    solana_client = SolanaClient(solana_rpc_url, helius_api_key=helius_api_key)

    # EVM clients
    ethereum_client = EVMClient(ethereum_rpc_url, network="ethereum")
    bsc_client = EVMClient(bsc_rpc_url, network="bsc")
    polygon_client = EVMClient(polygon_rpc_url, network="polygon")

    # Universal client
    blockchain_client = UniversalBlockchainClient(
        solana_client=solana_client,
        ethereum_client=ethereum_client,
        bsc_client=bsc_client,
        polygon_client=polygon_client,
        default_evm_client=ethereum_client
    )

    # Initialize PostgreSQL database
    logger.info("💾 Initializing PostgreSQL database...")
    database = PostgresDatabase(postgres_url, pool_size=20)
    await database.connect()
    await database.init_db()

    # Initialize Redis cache
    logger.info("⚡ Initializing Redis cache...")
    cache = RedisCache(redis_url)
    await cache.connect()

    # Initialize optimized screenshot service
    logger.info("📸 Initializing screenshot service...")
    screenshot_service = await get_screenshot_service()
    await screenshot_service.start()

    # Initialize address monitor
    logger.info("👁️  Initializing address monitor...")
    monitor = AddressMonitor(
        solana_client=solana_client,
        database=database,
        notification_callback=lambda user_id, msg, photo=None: send_notification(bot, user_id, msg, photo),
        interval=monitor_interval
    )

    # Initialize multi-agent AML system
    logger.info("🛡️  Initializing TxPeek agent system...")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    agent_system = AgentSystem(
        database=database,
        solana_client=solana_client,
        blockchain_client=blockchain_client,
        screenshot_service=screenshot_service,
        api_key=anthropic_api_key,
    )
    await agent_system.initialize()
    set_agent_system(agent_system)

    # Initialize handlers
    init_handlers(blockchain_client, database, monitor)

    # Register routers (AML check router first for /txpeek command priority)
    register_aml_check_handlers(dp)
    dp.include_router(router)

    # Start monitor
    await monitor.start()

    # Start periodic cache cleanup
    async def cleanup_task():
        while True:
            await asyncio.sleep(3600)  # Every hour
            try:
                await screenshot_service.cleanup_old_screenshots(max_age_seconds=3600)
                logger.info("🗑️  Cleaned up old screenshots")
            except Exception as e:
                logger.error(f"Error cleaning screenshots: {e}")

    cleanup_task_handle = asyncio.create_task(cleanup_task())

    # Start bot
    logger.info("✅ Bot started in OPTIMIZED mode!")
    logger.info(f"   - PostgreSQL connection pool: 20 connections")
    logger.info(f"   - Redis cache: enabled")
    logger.info(f"   - Screenshot service: browser reuse enabled")
    logger.info(f"   - Monitor batch size: 50 addresses/batch")
    logger.info(f"   - TxPeek agent system: active (5 agents)")

    try:
        await dp.start_polling(bot)
    finally:
        logger.info("🛑 Shutting down...")

        # Stop cleanup task
        cleanup_task_handle.cancel()

        # Stop monitor
        await monitor.stop()

        # Stop screenshot service
        await screenshot_service.stop()

        # Close connections
        await cache.close()
        await database.close()
        await blockchain_client.close()
        await storage.close()
        await bot.session.close()

        logger.info("✅ Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
