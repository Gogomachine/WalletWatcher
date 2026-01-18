"""Main bot entry point."""

import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.solana import SolanaClient
from src.evm import EVMClient
from src.blockchain import UniversalBlockchainClient
from src.database import Database
from src.bot import router, init_handlers, AddressMonitor


# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def send_notification(bot: Bot, user_id: int, message: str):
    """Send notification to user.

    Args:
        bot: Bot instance
        user_id: Telegram user ID
        message: Message text
    """
    try:
        await bot.send_message(
            user_id,
            message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error sending notification to {user_id}: {e}")


async def main():
    """Main bot function."""
    # Получение настроек из .env
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return

    # RPC URLs for different networks
    solana_rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    ethereum_rpc_url = os.getenv("ETHEREUM_RPC_URL", "https://eth.llamarpc.com")
    bsc_rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
    polygon_rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

    # Telegram API credentials for channel parsing
    telegram_api_id = os.getenv("TELEGRAM_API_ID")
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH")

    # Convert API ID to int if provided
    if telegram_api_id:
        try:
            telegram_api_id = int(telegram_api_id)
        except ValueError:
            logger.warning("Invalid TELEGRAM_API_ID format, whale discovery will be disabled")
            telegram_api_id = None

    database_path = os.getenv("DATABASE_PATH", "./data/bot.db")
    monitor_interval = int(os.getenv("MONITOR_INTERVAL", "10"))

    # Инициализация бота
    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Инициализация клиентов
    logger.info("Initializing blockchain clients...")

    # Solana client with Telegram channel parser support
    helius_api_key = os.getenv("HELIUS_API_KEY")
    solana_client = SolanaClient(
        solana_rpc_url,
        helius_api_key=helius_api_key,
        telegram_api_id=telegram_api_id,
        telegram_api_hash=telegram_api_hash
    )

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

    logger.info("Initializing database...")
    database = Database(database_path)
    await database.init_db()

    # Инициализация монитора адресов
    logger.info("Initializing address monitor...")
    monitor = AddressMonitor(
        solana_client=solana_client,
        database=database,
        notification_callback=lambda user_id, msg: send_notification(bot, user_id, msg),
        interval=monitor_interval
    )

    # Инициализация обработчиков
    init_handlers(blockchain_client, database, monitor)

    # Регистрация роутера
    dp.include_router(router)

    # Запуск монитора
    await monitor.start()

    # Запуск бота
    logger.info("Bot started!")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        await monitor.stop()
        await blockchain_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
