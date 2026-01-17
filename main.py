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

    solana_rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    helius_api_key = os.getenv("HELIUS_API_KEY")
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
    logger.info("Initializing Solana client...")
    solana_client = SolanaClient(solana_rpc_url, helius_api_key)

    logger.info("Initializing database...")
    database = Database(database_path)
    await database.init_db()

    # Инициализация монитора адресов
    logger.info("Initializing address monitor...")
    monitor = AddressMonitor(
        solana_client=solana_client,
        database=database,
        notification_callback=lambda uid, msg: send_notification(bot, uid, msg),
        interval=monitor_interval
    )

    # Инициализация обработчиков
    init_handlers(solana_client, database, monitor)
    dp.include_router(router)

    # Запуск монитора
    await monitor.start()

    logger.info("Bot started!")
    try:
        # Запуск polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Очистка ресурсов
        logger.info("Shutting down...")
        await monitor.stop()
        await solana_client.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
