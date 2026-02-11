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
from src.aml import init_aml_handlers, register_aml_handlers


# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
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

    logger.info("Initializing database...")
    database = Database(database_path)
    await database.init_db()

    # Инициализация монитора адресов
    logger.info("Initializing address monitor...")
    monitor = AddressMonitor(
        solana_client=solana_client,
        database=database,
        notification_callback=lambda user_id, msg, photo=None: send_notification(bot, user_id, msg, photo),
        interval=monitor_interval
    )

    # Инициализация обработчиков
    init_handlers(blockchain_client, database, monitor)

    # Инициализация AML Shield
    logger.info("Initializing AML Shield...")
    init_aml_handlers(database)
    register_aml_handlers(dp)

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
