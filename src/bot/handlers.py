"""Bot command handlers."""

import os
import random
from datetime import datetime
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup,
    InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
)
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatType
from .keyboards import (
    get_main_menu,
    get_tracked_addresses_keyboard,
    get_address_actions_keyboard,
    get_notifications_keyboard,
    get_cancel_keyboard,
    get_skip_keyboard,
    get_whale_result_keyboard,
    get_persistent_keyboard,
    get_group_addresses_keyboard,
    get_whale_limit_exceeded_keyboard,
    get_admin_panel_keyboard,
    get_admin_user_actions_keyboard
)
from ..blockchain.universal_client import UniversalBlockchainClient, detect_address_type
from ..database.db import Database
from ..utils.screenshot import take_solscan_screenshot


router = Router()

# Забавные фразы для процесса получения скриншота
PEEK_PHRASES = [
    "👀 Заглядываю за угол...",
    "🪟 Задвинул жалюзи...",
    "📱 Делаю вид что говорю по телефону...",
    "🕊️ Подсматриваю за голубями...",
    "💓 Слушаю сердцебиение транзакции...",
    "🌳 Прячусь за деревом...",
    "🥷 Переодеваюсь в одежду охранника...",
    "💔 Разбиваю сердца...",
    "🐱 Обожаю котят...",
    "👁️ Наблюдаю за тобой...",
    "🍿 Наблюдаю за чипсами...",
    "🕵️ Обманываю тайное правительство...",
    "😬 Кусаю кусалку...",
    "🤭 Хихикаю...",
    "🎵 Скидывают эту песню себе на мп3 плеер...",
    "🧊 Что-то делаю в холодильнике...",
    "📦 Заканчиваю шуршать...",
    "🍄 Восхищаюсь опятами...",
    "🐟 Зеркалю анчоус...",
    "🥫 Восхищаюсь открывашками...",
    "🎭 Дергаю за ниточки...",
    "🗣️ Узнаю сплетни...",
    "⚛️ Ворую нейтрино...",
    "🍪 Выпекаю печенье...",
    "☠️ Отравляю диктатора...",
    "🫘 Смотрю на фасоль...",
    "🍿 Ищу попкорн...",
    "🐊 Делаю сальто над крокодилами...",
    "🤭 Хихикаю над окружающими...",
    "🥧 Выпекаю яблочный пирог...",
    "👖 Затягиваю пояса...",
    "😋 Смешно ем...",
    "🐱 Играюсь с котятами...",
    "🐶 Чешу за ушком...",
    "🤫 Шушукаюсь...",
    "😛 Показываю язык...",
    "🔴 Обрезаю красный провод...",
    "🟢 Обрезаю зеленый провод...",
    "🔵 Обрезаю синий провод...",
    "🦖 Притворяюсь динозавром...",
    "😂 Органично хохочу...",
    "🍺 Открываю пиво..."
]


def get_random_peek_phrase() -> str:
    """Get random peek phrase for screenshot process."""
    return random.choice(PEEK_PHRASES)


def format_added_at(added_at) -> str:
    """Format added_at timestamp for display.

    Args:
        added_at: datetime object or string from database

    Returns:
        Formatted string like "Добавлен в избранное 22.03.2026 18:03"
    """
    if added_at is None:
        return ""

    if isinstance(added_at, str):
        try:
            added_at = datetime.fromisoformat(added_at)
        except ValueError:
            return ""

    return f"📅 Добавлен в избранное {added_at.strftime('%d.%m.%Y %H:%M')}"


async def _perform_whale_check(message: Message, user_id: int, show_remaining: bool = True) -> None:
    """Perform whale address discovery and display results.

    Common logic for /whale command, text button, and callback.

    Args:
        message: Message object to reply to
        user_id: Telegram user ID
        show_remaining: Whether to show remaining attempts in result
    """
    # Check daily limit
    checks_used, max_checks = await database.get_whale_checks_remaining(user_id)
    remaining = max_checks - checks_used

    if remaining <= 0:
        # Limit exceeded - show payment options
        limit_msg = (
            "⛔ <b>Лимит исчерпан</b>\n\n"
            "У вас закончились попытки 'Подсмотреть'.\n\n"
            "💡 Вы можете:\n"
            "• Купить дополнительные попытки за Telegram Stars\n"
            "• Оформить премиум подписку (5 попыток/день)\n"
            "• Подождать 24 часа с момента последней попытки"
        )

        await message.answer(
            limit_msg,
            parse_mode="HTML",
            reply_markup=get_whale_limit_exceeded_keyboard(checks_used)
        )
        return

    # Increment counter before showing
    await database.increment_whale_check(user_id)

    status_msg = await message.answer(
        f"👀 Подсматриваю...\n\n"
        f"<i>Осталось попыток: {remaining - 1}</i>",
        parse_mode="HTML"
    )

    # Discover random whale address
    address = await blockchain_client.discover_whale_address(min_balance_usd=100000)

    if not address:
        await status_msg.edit_text(
            "❌ <b>Не удалось подсмотреть</b>\n\n"
            "Попробуйте позже.",
            parse_mode="HTML"
        )
        return

    # Get wallet info
    await status_msg.edit_text("👀 Получаю информацию...")
    info = await blockchain_client.get_wallet_info(address)

    if "error" in info:
        await status_msg.edit_text(
            f"❌ Ошибка при получении информации: {info['error']}",
            parse_mode="HTML"
        )
        return

    # Format wallet info
    msg = "👀 <b>Подсмотрел!</b>\n\n"
    msg += format_wallet_info(info)
    if show_remaining:
        msg += f"\n\n<i>💫 Осталось попыток: {remaining - 1}</i>"

    # Try to get screenshot from Solscan
    await status_msg.edit_text(get_random_peek_phrase())
    screenshot_path = await take_solscan_screenshot(address)

    if screenshot_path and Path(screenshot_path).exists():
        # Send photo with caption and favorite button
        photo = FSInputFile(screenshot_path)
        await message.answer_photo(
            photo=photo,
            caption=msg,
            parse_mode="HTML",
            reply_markup=get_whale_result_keyboard(address)
        )
        await status_msg.delete()

        # Clean up screenshot file
        try:
            Path(screenshot_path).unlink()
        except Exception:
            pass
    else:
        # Fallback to text only if screenshot failed
        await status_msg.edit_text(
            msg,
            disable_web_page_preview=True,
            parse_mode="HTML",
            reply_markup=get_whale_result_keyboard(address)
        )


class AddressStates(StatesGroup):
    """States for address input."""
    waiting_for_address = State()
    waiting_for_nickname = State()


class GroupStates(StatesGroup):
    """States for group management."""
    waiting_for_group_name = State()
    selecting_addresses_for_group = State()


class RenameStates(StatesGroup):
    """States for renaming address."""
    waiting_for_new_nickname = State()


class AdminStates(StatesGroup):
    """States for admin operations."""
    waiting_for_user_id = State()
    waiting_for_premium_user_id = State()
    waiting_for_remove_premium_user_id = State()
    waiting_for_attempts_user_id = State()


def get_admin_ids() -> list:
    """Get admin IDs from environment variable (loaded dynamically).

    Returns:
        List of admin Telegram user IDs
    """
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    return [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]


def is_admin(user_id: int) -> bool:
    """Check if user is an admin.

    Args:
        user_id: Telegram user ID

    Returns:
        True if user is admin
    """
    return user_id in get_admin_ids()


# Глобальные переменные для клиентов (будут инициализированы в main.py)
blockchain_client: UniversalBlockchainClient = None
database: Database = None
monitor = None


def init_handlers(bl_client: UniversalBlockchainClient, db: Database, addr_monitor):
    """Initialize handlers with dependencies.

    Args:
        bl_client: Universal blockchain client instance
        db: Database instance
        addr_monitor: Address monitor instance
    """
    global blockchain_client, database, monitor
    blockchain_client = bl_client
    database = db
    monitor = addr_monitor


def is_blockchain_address(text: str) -> bool:
    """Check if text looks like a blockchain address (Solana or EVM).

    Args:
        text: Text to check

    Returns:
        True if looks like a valid blockchain address
    """
    if not text:
        return False

    address_type = detect_address_type(text.strip())
    return address_type in ["solana", "evm"]


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    # Если в группе, отвечаем кратко
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(
            "👋 Привет! Я бот для отслеживания всяких разных адресов.\n\n"
            "Отправьте адрес или используйте /menu для просмотра команд.",
            reply_markup=get_persistent_keyboard()
        )
    else:
        await message.answer(
            "👋 Привет!\n\n"
            "Я бот для отслеживания всяких разных адресов. (пока только солана :) )\n\n"
            "Я могу:\n"
            "• Показать информацию о любом адресе со скриншотиками прикольно, удобно можно сразу в эксплорер\n"
            "• Отслеживать адреса в реальном времени, создавать группы адресов, баланс группы можно тоже посмотреть\n"
            "• Уведомлять о новых транзакциях тоже со скриншотиками\n"
            "• Пикантный режим \"Подсмотреть\", с конкурсами и тамадой\n"
            "• 💎 Premium подписка с бонусами и доступом в VIP сообщество\n\n"
            "Используйте меню ниже для навигации:",
            reply_markup=get_persistent_keyboard()
        )
        # Send inline menu after persistent keyboard
        await message.answer(
            "📱 Главное меню:",
            reply_markup=get_main_menu()
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command."""
    await message.reply(
        "📖 <b>Справка</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/menu - Показать главное меню\n"
        "/check <адрес> - Проверить адрес\n"
        "/track <адрес> - Добавить адрес в отслеживание\n"
        "/list - Мои отслеживаемые адреса\n"
        "/whale - Подсмотреть (случайный адрес)\n"
        "/analysis - Анализ (скоро)\n"
        "/settings - Настройки\n"
        "/admin - Админ-панель (только для админов)\n\n"
        "<b>Получение информации:</b>\n"
        "Просто отправьте Solana адрес, и я покажу всю информацию о нём:\n"
        "• Баланс в SOL\n"
        "• Возраст кошелька\n"
        "• Последняя транзакция\n"
        "• Статус активности (Активный/Засыпающий/Спящий)\n\n"
        "<b>👀 Подсмотреть:</b>\n"
        "Команда /whale выбирает случайный адрес из списка. "
        "Можете добавить его в избранное для отслеживания!\n\n"
        "<b>Отслеживание:</b>\n"
        "Добавьте адрес в список отслеживания, и вы будете получать уведомления "
        "о каждой новой транзакции в режиме реального времени."
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Handle /menu command."""
    await message.reply(
        "📱 Главное меню:",
        reply_markup=get_main_menu()
    )
    # Update persistent keyboard
    await message.answer(
        "Используйте кнопки ниже:",
        reply_markup=get_persistent_keyboard()
    )


@router.message(F.text == "👤 Профиль")
async def text_profile_button(message: Message):
    """Handle 'Profile' button press."""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    # Get user stats
    count = await database.get_tracked_address_count(user_id)
    groups = await database.get_user_groups(user_id)
    settings = await database.get_user_settings(user_id)
    checks_used, max_checks = await database.get_whale_checks_remaining(user_id)

    username_str = f"@{username}" if username else "Не указан"
    is_premium = settings.get('is_premium', 0)
    subscription_status = "💎 Премиум" if is_premium else "🆓 Бесплатная"

    remaining_checks = max_checks - checks_used

    await message.answer(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"👨‍💻 <b>Имя:</b> {first_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📝 <b>Username:</b> {username_str}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"📋 Отслеживаемых адресов: {count}\n"
        f"📁 Групп: {len(groups)}\n\n"
        f"💎 <b>Подписка:</b> {subscription_status}\n"
        f"👀 <b>Подсмотреть:</b> {remaining_checks} попыток\n\n"
        f"<i>Лимит обновляется через 24 часа после последней попытки</i>",
        parse_mode="HTML"
    )


@router.message(F.text == "📋 Отслеживание")
async def text_tracking_button(message: Message):
    """Handle 'Tracking' button press."""
    # Show list of tracked addresses and groups
    addresses = await database.get_user_tracked_addresses(message.from_user.id)
    groups = await database.get_user_groups(message.from_user.id)

    if not addresses:
        await message.answer(
            "📋 <b>Отслеживание</b>\n\n"
            "У вас пока нет отслеживаемых адресов.\n"
            "Используйте команду /track или кнопку ➕ в главном меню.",
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
    else:
        keyboard = get_tracked_addresses_keyboard(addresses, groups)
        await message.answer(
            f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
            "Нажмите на адрес или группу для управления:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


@router.message(F.text == "👀 Подсмотреть")
async def text_whale_button(message: Message):
    """Handle 'Peek' button press with daily limit check."""
    await _perform_whale_check(message, message.from_user.id)


@router.message(F.text == "🔍 Анализ")
async def text_analysis_button(message: Message):
    """Handle 'Analysis' button press."""
    await message.answer(
        "🔍 <b>Анализ</b>\n\n"
        "Скоро здесь появятся отчеты безопасности и настоящий АМЛ как у крутышек 😎",
        parse_mode="HTML"
    )


@router.message(F.text == "⚙️ Настройки")
async def text_settings_button(message: Message):
    """Handle 'Settings' button press."""
    await show_settings(message)


@router.message(F.text == "💎 Подписки")
async def text_subscription_button(message: Message):
    """Handle 'Subscription' button press - shows subscription info."""
    user_id = message.from_user.id
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)

    if is_premium:
        msg = (
            "💎 <b>Ваша подписка: PREMIUM</b>\n\n"
            "✅ Безлимитное отслеживание адресов\n"
            "✅ Безлимитное создание групп\n"
            "✅ 5 попыток 'Подсмотреть' в день\n"
            "   <i>(дополнительные: от 100 ⭐, пакеты со скидкой до 40%)</i>\n"
            "✅ 20 АМЛ отчетов в месяц <i>(скоро)</i>\n"
            "✅ Доступ в Discord и VIP Telegram\n"
            "✅ Бонусы при эйрдропе 🎁\n\n"
            "<i>Спасибо за поддержку!</i> 🙏"
        )
        buttons = [[InlineKeyboardButton(text="🔙 В меню", callback_data="cancel")]]
    else:
        limits = await database.get_free_limits(user_id)
        msg = (
            "📋 <b>Ваша подписка: FREE</b>\n\n"
            f"👀 Подсмотреть: {limits['whale']['remaining']} попыток\n"
            f"📊 Запросы по адресам: {limits['reports']['remaining']}/{limits['reports']['max']} сегодня\n"
            f"⭐ Избранное: {limits['favorites']['count']}/{limits['favorites']['max']} адресов\n"
            f"📁 Группы: {limits['groups']['count']}/{limits['groups']['max']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 <b>PREMIUM подписка</b>\n\n"
            "✨ Безлимитное отслеживание адресов\n"
            "✨ Безлимитное создание групп\n"
            "✨ 5 попыток 'Подсмотреть' в день\n"
            "   <i>(дополнительные: от 100 ⭐, пакеты со скидкой до 40%)</i>\n"
            "✨ 20 АМЛ отчетов в месяц <i>(скоро)</i>\n"
            "✨ Доступ в Discord и VIP Telegram\n"
            "✨ Бонусы при эйрдропе 🎁\n\n"
            "💰 <b>Цена: 1 ⭐</b> (тестовый период)"
        )
        buttons = [
            [InlineKeyboardButton(text="💎 Купить Premium (1 ⭐)", callback_data="buy_premium")],
            [InlineKeyboardButton(text="🔙 В меню", callback_data="cancel")]
        ]

    await message.answer(
        msg,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.message(Command("check"))
async def cmd_check(message: Message):
    """Handle /check command with address."""
    # Извлекаем адрес из команды
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "📍 Отправьте адрес после команды:\n"
            "<code>/check 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU</code>",
            parse_mode="HTML"
        )
        return

    address = parts[1].strip()
    await check_address(message, address)


@router.message(Command("track"))
async def cmd_track(message: Message):
    """Handle /track command to add address to tracking."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "📍 Отправьте адрес после команды:\n"
            "<code>/track 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU</code>",
            parse_mode="HTML"
        )
        return

    address = parts[1].strip()

    # Проверяем валидность
    if not is_blockchain_address(address):
        await message.reply("❌ Неверный формат адреса Solana")
        return

    # Check favorites limit for FREE users
    user_id = message.from_user.id
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)
    if not is_premium:
        favorites_count = await database.get_favorites_count(user_id)
        if favorites_count >= 2:
            await message.reply(
                "⛔ <b>Лимит FREE подписки</b>\n\n"
                "Максимум 2 адреса в избранном.\n"
                "Оформите премиум для безлимитного отслеживания!",
                parse_mode="HTML"
            )
            return

    # Добавляем в отслеживание
    success = await database.add_tracked_address(
        user_id,
        address,
        None
    )

    if success:
        await message.reply(
            f"✅ Адрес добавлен в отслеживание!\n\n"
            f"<code>{address}</code>\n\n"
            f"Вы будете получать уведомления о новых транзакциях.",
            parse_mode="HTML"
        )
    else:
        await message.reply("❌ Этот адрес уже отслеживается.")


@router.message(Command("list"))
async def cmd_list(message: Message):
    """Handle /list command to show tracked addresses."""
    user_id = message.from_user.id
    addresses = await database.get_user_tracked_addresses(user_id)
    groups = await database.get_user_groups(user_id)

    if not addresses:
        await message.reply(
            "У вас пока нет отслеживаемых адресов.\n\n"
            "Используйте /track <адрес> для добавления."
        )
        return

    keyboard = get_tracked_addresses_keyboard(addresses, groups)
    await message.reply(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес или группу для управления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Handle /settings command."""
    await show_settings(message)


@router.message(Command("analysis"))
async def cmd_analysis(message: Message):
    """Handle /analysis command - redirect to /txpeek."""
    await message.reply(
        "🔍 <b>AML-Анализ</b>\n\n"
        "Используйте <code>/txpeek &lt;адрес&gt;</code> для полной AML-проверки адреса.\n\n"
        "Или просто отправьте адрес — я проверю его автоматически.\n\n"
        "Проверяю по:\n"
        "• Санкционным спискам OFAC SDN\n"
        "• Базе ChainAbuse\n"
        "• Статусу заморозки USDT/USDC\n"
        "• Лейблам эксплореров\n"
        "• Паттернам транзакций",
        parse_mode="HTML"
    )


@router.message(Command("whale"))
async def cmd_whale(message: Message):
    """Handle /whale command - peek at random whale address."""
    await _perform_whale_check(message, message.from_user.id)


# Callback handlers для inline кнопок


@router.callback_query(F.data == "menu_check")
async def menu_check_callback(callback: CallbackQuery, state: FSMContext):
    """Handle 'Check address' menu button."""
    await state.set_state(AddressStates.waiting_for_address)
    await callback.message.edit_text(
        "📍 Отправьте Solana адрес для проверки:\n\n"
        "Пример: <code>7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_add")
async def menu_add_callback(callback: CallbackQuery, state: FSMContext):
    """Handle 'Add address' menu button."""
    await state.set_state(AddressStates.waiting_for_address)
    await state.update_data(adding_to_tracking=True)
    await callback.message.edit_text(
        "📍 Отправьте Solana адрес для отслеживания:\n\n"
        "Пример: <code>7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_list")
async def menu_list_callback(callback: CallbackQuery):
    """Handle 'My addresses' menu button."""
    addresses = await database.get_user_tracked_addresses(callback.from_user.id)
    groups = await database.get_user_groups(callback.from_user.id)

    if not addresses:
        await callback.message.edit_text(
            "У вас пока нет отслеживаемых адресов.\n\n"
            "Используйте меню для добавления.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return

    keyboard = get_tracked_addresses_keyboard(addresses, groups)
    await callback.message.edit_text(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес или группу для управления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_aml")
async def menu_aml_callback(callback: CallbackQuery):
    """Handle 'AML Shield' menu button."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Что такое грязная крипта?", callback_data="aml_dirty")],
        [InlineKeyboardButton(text="🔄 Безопасен ли P2P?", callback_data="aml_p2p")],
        [InlineKeyboardButton(text="🧊 Заморозили счёт!", callback_data="aml_frozen")],
        [InlineKeyboardButton(text="⚠️ Красные флаги", callback_data="aml_redflags")],
        [InlineKeyboardButton(text="🛡️ Как проверить крипту?", callback_data="aml_check")],
        [InlineKeyboardButton(text="💬 Задать свой вопрос", callback_data="aml_ask")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ])

    await callback.message.edit_text(
        "🛡️ <b>AML Shield</b> — твой помощник по крипто-безопасности\n\n"
        "Я помогу разобраться в:\n"
        "• Грязной крипте и как от неё защититься\n"
        "• Рисках P2P-сделок\n"
        "• Заморозке счетов на биржах\n"
        "• Проверке адресов перед сделкой\n\n"
        "Выбери действие или просто задай вопрос:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_profile")
async def menu_profile_callback(callback: CallbackQuery):
    """Handle 'Profile' menu button."""
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name

    # Get user stats
    count = await database.get_tracked_address_count(user_id)
    groups = await database.get_user_groups(user_id)
    settings = await database.get_user_settings(user_id)
    checks_used, max_checks = await database.get_whale_checks_remaining(user_id)

    username_str = f"@{username}" if username else "Не указан"
    is_premium = settings.get('is_premium', 0)
    subscription_status = "💎 Премиум" if is_premium else "🆓 Бесплатная"

    remaining_checks = max_checks - checks_used

    await callback.message.edit_text(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"👨‍💻 <b>Имя:</b> {first_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📝 <b>Username:</b> {username_str}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"📋 Отслеживаемых адресов: {count}\n"
        f"📁 Групп: {len(groups)}\n\n"
        f"💎 <b>Подписка:</b> {subscription_status}\n"
        f"👀 <b>Подсмотреть:</b> {remaining_checks} попыток\n\n"
        f"<i>Лимит обновляется через 24 часа после последней попытки</i>",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "menu_settings")
async def menu_settings_callback(callback: CallbackQuery):
    """Handle 'Settings' menu button."""
    await show_settings_callback(callback)


@router.callback_query(F.data == "menu_whale")
async def menu_whale_callback(callback: CallbackQuery):
    """Handle 'Peek' menu button with daily limit check."""
    await callback.answer()
    # Use message from callback to send whale check results
    await _perform_whale_check(callback.message, callback.from_user.id)


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    """Handle cancel button."""
    await state.clear()
    await callback.message.edit_text(
        "❌ Отменено.\n\nИспользуйте меню ниже:",
        reply_markup=get_main_menu()
    )
    await callback.answer()


@router.callback_query(F.data == "skip_nickname")
async def skip_nickname_callback(callback: CallbackQuery, state: FSMContext):
    """Handle skip nickname button."""
    data = await state.get_data()
    address = data.get('address')

    if not address:
        await callback.answer("Ошибка: адрес не найден", show_alert=True)
        return

    # Check favorites limit for FREE users
    user_id = callback.from_user.id
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)
    if not is_premium:
        favorites_count = await database.get_favorites_count(user_id)
        if favorites_count >= 2:
            await callback.message.edit_text(
                "⛔ <b>Лимит FREE подписки</b>\n\n"
                "Максимум 2 адреса в избранном.\n"
                "Оформите премиум для безлимитного отслеживания!",
                parse_mode="HTML",
                reply_markup=get_main_menu()
            )
            await state.clear()
            await callback.answer()
            return

    # Добавляем без никнейма
    success = await database.add_tracked_address(
        user_id,
        address,
        None
    )

    if success:
        await callback.message.edit_text(
            f"✅ Адрес успешно добавлен в отслеживание!\n\n"
            f"<code>{address}</code>\n\n"
            f"Вы будете получать уведомления о новых транзакциях.",
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
    else:
        await callback.message.edit_text(
            "❌ Этот адрес уже отслеживается.",
            reply_markup=get_main_menu()
        )

    await state.clear()
    await callback.answer()


@router.message(StateFilter(AddressStates.waiting_for_address))
async def process_address(message: Message, state: FSMContext):
    """Process received address."""
    address = message.text.strip()

    # Проверка валидности адреса
    if not is_blockchain_address(address):
        await message.reply(
            "❌ Неверный формат адреса Solana.\n\n"
            "Адрес должен быть в формате base58 и содержать 32-44 символа."
        )
        return

    status_msg = await message.reply("⏳ Получаю информацию...")

    info = await blockchain_client.get_wallet_info(address)

    if "error" in info:
        await status_msg.edit_text(
            f"❌ Ошибка: {info['error']}\n\n"
            "Убедитесь, что вы отправили корректный Solana адрес."
        )
        await state.clear()
        return

    # Форматирование сообщения
    msg = format_wallet_info(info)

    # Try to get screenshot from Solscan
    await status_msg.edit_text(get_random_peek_phrase())
    screenshot_path = await take_solscan_screenshot(address)

    # Проверяем, добавляем ли адрес в отслеживание
    data = await state.get_data()
    if data.get('adding_to_tracking'):
        # Сохраняем адрес и спрашиваем никнейм
        await state.update_data(address=address)
        await state.set_state(AddressStates.waiting_for_nickname)

        if screenshot_path and Path(screenshot_path).exists():
            # Send photo with caption
            photo = FSInputFile(screenshot_path)
            await message.answer_photo(
                photo=photo,
                caption=msg,
                parse_mode="HTML"
            )
            await status_msg.delete()

            # Clean up screenshot file
            try:
                Path(screenshot_path).unlink()
            except Exception:
                pass
        else:
            # Fallback to text only
            await status_msg.edit_text(msg, disable_web_page_preview=True, parse_mode="HTML")

        await message.reply(
            "✏️ Хотите задать никнейм для этого адреса?\n\n"
            "Отправьте никнейм или нажмите 'Пропустить':",
            reply_markup=get_skip_keyboard()
        )
    else:
        if screenshot_path and Path(screenshot_path).exists():
            # Send photo with caption
            photo = FSInputFile(screenshot_path)
            await message.answer_photo(
                photo=photo,
                caption=msg,
                parse_mode="HTML"
            )
            await status_msg.delete()

            # Clean up screenshot file
            try:
                Path(screenshot_path).unlink()
            except Exception:
                pass
        else:
            # Fallback to text only
            await status_msg.edit_text(msg, disable_web_page_preview=True, parse_mode="HTML")

        await state.clear()


@router.message(StateFilter(AddressStates.waiting_for_nickname))
async def process_nickname(message: Message, state: FSMContext):
    """Process nickname for tracked address."""
    data = await state.get_data()
    address = data['address']
    nickname = message.text.strip()

    # Check favorites limit for FREE users
    user_id = message.from_user.id
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)
    if not is_premium:
        favorites_count = await database.get_favorites_count(user_id)
        if favorites_count >= 2:
            await message.reply(
                "⛔ <b>Лимит FREE подписки</b>\n\n"
                "Максимум 2 адреса в избранном.\n"
                "Оформите премиум для безлимитного отслеживания!",
                parse_mode="HTML"
            )
            await state.clear()
            return

    # Добавляем адрес в отслеживание
    success = await database.add_tracked_address(
        user_id,
        address,
        nickname
    )

    if success:
        await message.reply(
            f"✅ Адрес успешно добавлен в отслеживание!\n\n"
            f"🏷️ Никнейм: {nickname}\n"
            f"Вы будете получать уведомления о новых транзакциях."
        )
    else:
        await message.reply("❌ Этот адрес уже отслеживается.")

    await state.clear()


async def check_address(message: Message, address: str):
    """Check and display address information.

    Args:
        message: Message object
        address: Solana address
    """
    user_id = message.from_user.id

    # Check daily limit for address reports
    reports_used, max_reports = await database.get_address_reports_remaining(user_id)
    remaining = max_reports - reports_used

    if remaining <= 0:
        settings = await database.get_user_settings(user_id)
        is_premium = settings.get('is_premium', 0)
        if not is_premium:
            await message.reply(
                "⛔ <b>Лимит исчерпан</b>\n\n"
                "Вы использовали все 10 бесплатных запросов.\n\n"
                "💡 Оформите премиум подписку для безлимитных запросов\n"
                "или подождите 24 часа с момента последнего запроса",
                parse_mode="HTML"
            )
            return

    # Increment counter
    await database.increment_address_report(user_id)

    status_msg = await message.reply("⏳ Получаю информацию...")

    info = await blockchain_client.get_wallet_info(address)

    if "error" in info:
        await status_msg.edit_text(f"❌ Ошибка: {info['error']}")
        return

    # Format text info
    msg = format_wallet_info(info)

    # Try to get screenshot from Solscan
    await status_msg.edit_text(get_random_peek_phrase())
    screenshot_path = await take_solscan_screenshot(address)

    # Create "Add to favorites" button
    keyboard = get_whale_result_keyboard(address)

    if screenshot_path and Path(screenshot_path).exists():
        # Send photo with caption
        photo = FSInputFile(screenshot_path)
        await message.answer_photo(
            photo=photo,
            caption=msg,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await status_msg.delete()

        # Clean up screenshot file
        try:
            Path(screenshot_path).unlink()
        except Exception:
            pass
    else:
        # Fallback to text only if screenshot failed
        await status_msg.edit_text(
            msg,
            disable_web_page_preview=True,
            parse_mode="HTML",
            reply_markup=keyboard
        )


# Address management callbacks


@router.callback_query(F.data.startswith("addr_"))
async def show_address_actions(callback: CallbackQuery):
    """Show actions for a tracked address."""
    address = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

    # Get address info to check notification status
    addr_info = await database.get_address_info(user_id, address)
    notifications_enabled = addr_info.get('notifications_enabled', 1) if addr_info else True

    nickname = addr_info.get('nickname', '') if addr_info else ''
    display_text = nickname if nickname else f"{address[:8]}...{address[-6:]}"
    added_at_str = format_added_at(addr_info.get('added_at')) if addr_info else ''

    await callback.message.edit_text(
        f"🔍 <b>Адрес:</b> {display_text}\n"
        f"<code>{address}</code>\n"
        f"{added_at_str}\n\n"
        "Выберите действие:",
        reply_markup=get_address_actions_keyboard(address, notifications_enabled),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("remove_"))
async def remove_address(callback: CallbackQuery):
    """Remove address from tracking."""
    address = callback.data.split("_", 1)[1]

    success = await database.remove_tracked_address(callback.from_user.id, address)

    if success:
        await callback.message.edit_text(
            f"✅ Адрес удален из отслеживания:\n<code>{address}</code>",
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text("❌ Ошибка при удалении адреса.")

    await callback.answer()


@router.callback_query(F.data.startswith("check_"))
async def check_address_callback(callback: CallbackQuery):
    """Check address info via callback."""
    address = callback.data.split("_", 1)[1]

    await callback.message.edit_text("⏳ Получаю информацию...")

    info = await blockchain_client.get_wallet_info(address)
    msg = format_wallet_info(info)

    # Try to get screenshot from Solscan
    await callback.message.edit_text(get_random_peek_phrase())
    screenshot_path = await take_solscan_screenshot(address)

    # Create "Add to favorites" button
    keyboard = get_whale_result_keyboard(address)

    if screenshot_path and Path(screenshot_path).exists():
        # Delete status message and send photo with caption
        await callback.message.delete()
        photo = FSInputFile(screenshot_path)
        await callback.message.answer_photo(
            photo=photo,
            caption=msg,
            parse_mode="HTML",
            reply_markup=keyboard
        )

        # Clean up screenshot file
        try:
            Path(screenshot_path).unlink()
        except Exception:
            pass
    else:
        # Fallback to text only if screenshot failed
        await callback.message.edit_text(
            msg,
            disable_web_page_preview=True,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    await callback.answer()


@router.callback_query(F.data.startswith("fav_add_"))
async def add_to_favorites_callback(callback: CallbackQuery):
    """Add address to favorites (tracked addresses)."""
    address = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    # Check if already tracking
    existing = await database.get_user_tracked_addresses(user_id)
    if any(addr['address'] == address for addr in existing):
        await callback.answer("⚠️ Этот адрес уже в избранном!", show_alert=True)
        return

    # Check favorites limit for FREE users
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)
    if not is_premium:
        favorites_count = await database.get_favorites_count(user_id)
        if favorites_count >= 2:
            await callback.answer(
                "⛔ Лимит FREE: максимум 2 адреса в избранном.\n"
                "Оформите премиум для безлимита!",
                show_alert=True
            )
            return

    # Add to tracked addresses without nickname
    await database.add_tracked_address(user_id, address, None)
    await callback.answer("⭐ Адрес добавлен в избранное!", show_alert=True)


# Notification management for addresses

@router.callback_query(F.data.startswith("notif_on_"))
async def enable_address_notifications(callback: CallbackQuery):
    """Enable notifications for an address."""
    address = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    await database.update_address_notifications(user_id, address, True)
    await callback.answer("🔔 Уведомления включены для этого адреса")

    # Refresh the address actions menu
    addr_info = await database.get_address_info(user_id, address)
    nickname = addr_info.get('nickname', '') if addr_info else ''
    display_text = nickname if nickname else f"{address[:8]}...{address[-6:]}"
    added_at_str = format_added_at(addr_info.get('added_at')) if addr_info else ''

    await callback.message.edit_text(
        f"🔍 <b>Адрес:</b> {display_text}\n"
        f"<code>{address}</code>\n"
        f"{added_at_str}\n\n"
        "Выберите действие:",
        reply_markup=get_address_actions_keyboard(address, True),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("notif_off_"))
async def disable_address_notifications(callback: CallbackQuery):
    """Disable notifications for an address."""
    address = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    await database.update_address_notifications(user_id, address, False)
    await callback.answer("🔕 Уведомления выключены для этого адреса")

    # Refresh the address actions menu
    addr_info = await database.get_address_info(user_id, address)
    nickname = addr_info.get('nickname', '') if addr_info else ''
    display_text = nickname if nickname else f"{address[:8]}...{address[-6:]}"
    added_at_str = format_added_at(addr_info.get('added_at')) if addr_info else ''

    await callback.message.edit_text(
        f"🔍 <b>Адрес:</b> {display_text}\n"
        f"<code>{address}</code>\n"
        f"{added_at_str}\n\n"
        "Выберите действие:",
        reply_markup=get_address_actions_keyboard(address, False),
        parse_mode="HTML"
    )


# Rename address

@router.callback_query(F.data.startswith("rename_"))
async def rename_address_callback(callback: CallbackQuery, state: FSMContext):
    """Start renaming an address."""
    address = callback.data.split("_", 1)[1]

    await state.update_data(address=address)
    await state.set_state(RenameStates.waiting_for_new_nickname)

    await callback.message.edit_text(
        f"✏️ <b>Назвать адрес</b>\n\n"
        f"<code>{address}</code>\n\n"
        "Отправьте новый никнейм для этого адреса:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(StateFilter(RenameStates.waiting_for_new_nickname))
async def process_new_nickname(message: Message, state: FSMContext):
    """Process new nickname for address."""
    data = await state.get_data()
    address = data.get('address')
    nickname = message.text.strip()

    if not address:
        await message.reply("Ошибка: адрес не найден")
        await state.clear()
        return

    await database.update_address_nickname(message.from_user.id, address, nickname)
    await message.reply(
        f"✅ Адрес переименован!\n\n"
        f"🏷️ <b>{nickname}</b>\n"
        f"<code>{address}</code>",
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    """Toggle notifications on/off."""
    settings = await database.get_user_settings(callback.from_user.id)
    new_state = not settings['notifications_enabled']

    await database.update_notifications_enabled(callback.from_user.id, new_state)

    status = "включены ✅" if new_state else "выключены ❌"
    await callback.answer(f"Уведомления {status}")

    # Update message
    await show_settings_callback(callback)


@router.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    """Go back to address list."""
    user_id = callback.from_user.id
    addresses = await database.get_user_tracked_addresses(user_id)
    groups = await database.get_user_groups(user_id)
    keyboard = get_tracked_addresses_keyboard(addresses, groups)

    await callback.message.edit_text(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес или группу для управления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


# Group management

@router.callback_query(F.data == "create_group")
async def create_group_callback(callback: CallbackQuery, state: FSMContext):
    """Start group creation."""
    await state.set_state(GroupStates.waiting_for_group_name)

    await callback.message.edit_text(
        "📁 <b>Создание группы</b>\n\n"
        "Отправьте название для новой группы:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(StateFilter(GroupStates.waiting_for_group_name))
async def process_group_name(message: Message, state: FSMContext):
    """Process group name and create group."""
    group_name = message.text.strip()
    user_id = message.from_user.id

    if len(group_name) > 50:
        await message.reply("❌ Название группы слишком длинное (максимум 50 символов)")
        return

    # Check groups limit for FREE users
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)
    if not is_premium:
        groups_count = await database.get_groups_count(user_id)
        if groups_count >= 1:
            await message.reply(
                "⛔ <b>Лимит FREE подписки</b>\n\n"
                "Максимум 1 группа.\n"
                "Оформите премиум для безлимитного количества групп!",
                parse_mode="HTML"
            )
            await state.clear()
            return

    success = await database.create_group(user_id, group_name)

    if success:
        await message.reply(
            f"✅ Группа <b>«{group_name}»</b> создана!\n\n"
            "Теперь вы можете добавить в неё адреса.",
            parse_mode="HTML"
        )
        await state.clear()
    else:
        await message.reply(
            "❌ Группа с таким названием уже существует.\n\n"
            "Придумайте другое название."
        )


@router.callback_query(F.data.startswith("group_"))
async def show_group_callback(callback: CallbackQuery):
    """Show addresses in a group."""
    group_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id

    groups = await database.get_user_groups(user_id)
    group = next((g for g in groups if g['id'] == group_id), None)

    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    addresses = await database.get_group_addresses(user_id, group_id)

    if addresses:
        keyboard = get_group_addresses_keyboard(addresses, group_id)
        await callback.message.edit_text(
            f"📁 <b>Группа: {group['name']}</b>\n\n"
            f"Адресов в группе: {len(addresses)}\n\n"
            "Нажмите на адрес для управления:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"📁 <b>Группа: {group['name']}</b>\n\n"
            "В группе пока нет адресов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_list")],
                [InlineKeyboardButton(text="🗑️ Удалить группу", callback_data=f"delgroup_{group_id}")]
            ]),
            parse_mode="HTML"
        )

    await callback.answer()


@router.callback_query(F.data.startswith("delgroup_"))
async def delete_group_callback(callback: CallbackQuery):
    """Delete a group."""
    group_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id

    success = await database.delete_group(user_id, group_id)

    if success:
        await callback.answer("✅ Группа удалена")
        # Show updated list
        await back_to_list(callback)
    else:
        await callback.answer("❌ Ошибка при удалении группы", show_alert=True)


@router.callback_query(F.data.startswith("groupbal_"))
async def show_group_balance(callback: CallbackQuery):
    """Calculate and show total SOL balance for all addresses in group."""
    group_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id

    # Get group info
    groups = await database.get_user_groups(user_id)
    group = next((g for g in groups if g['id'] == group_id), None)

    if not group:
        await callback.answer("❌ Группа не найдена", show_alert=True)
        return

    # Get all addresses in group
    addresses = await database.get_group_addresses(user_id, group_id)

    if not addresses:
        await callback.answer("❌ В группе нет адресов", show_alert=True)
        return

    await callback.message.edit_text(
        f"💰 <b>Подсчёт баланса группы {group['name']}</b>\n\n"
        f"⏳ Проверяю {len(addresses)} адресов...",
        parse_mode="HTML"
    )
    await callback.answer()

    # Calculate total balance
    total_balance = 0.0
    address_balances = []
    errors = []

    for addr in addresses:
        address = addr['address']
        nickname = addr.get('nickname', '')
        display_name = nickname if nickname else f"{address[:8]}...{address[-4:]}"

        try:
            info = await blockchain_client.get_wallet_info(address)
            if "error" not in info and info.get('balance') is not None:
                balance = info['balance']
                total_balance += balance
                address_balances.append({
                    'name': display_name,
                    'address': address,
                    'balance': balance
                })
            else:
                errors.append(display_name)
        except Exception as e:
            print(f"Error getting balance for {address}: {e}")
            errors.append(display_name)

    # Format result message
    msg = f"💰 <b>Общий баланс группы: {group['name']}</b>\n\n"
    msg += f"<b>Итого: {total_balance:.4f} SOL</b>\n\n"

    if address_balances:
        msg += "📊 <b>По адресам:</b>\n"
        for item in sorted(address_balances, key=lambda x: x['balance'], reverse=True):
            msg += f"• {item['name']}: {item['balance']:.4f} SOL\n"

    if errors:
        msg += f"\n⚠️ Не удалось получить баланс для {len(errors)} адресов"

    # Add back button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к группе", callback_data=f"group_{group_id}")]
    ])

    await callback.message.edit_text(
        msg,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("addtogroup_"))
async def add_to_group_start(callback: CallbackQuery, state: FSMContext):
    """Start adding address to group."""
    address = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

    groups = await database.get_user_groups(user_id)

    if not groups:
        await callback.answer(
            "❌ У вас нет групп. Сначала создайте группу!",
            show_alert=True
        )
        return

    await state.update_data(address=address)

    # Show groups to choose from
    buttons = []
    for group in groups:
        buttons.append([
            InlineKeyboardButton(
                text=f"📁 {group['name']}",
                callback_data=f"togroup_{group['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
    ])

    await callback.message.edit_text(
        f"📁 <b>Добавить в группу</b>\n\n"
        f"<code>{address}</code>\n\n"
        "Выберите группу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("togroup_"))
async def add_to_group_confirm(callback: CallbackQuery, state: FSMContext):
    """Confirm adding address to group."""
    group_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id

    data = await state.get_data()
    address = data.get('address')

    if not address:
        await callback.answer("❌ Ошибка: адрес не найден", show_alert=True)
        return

    success = await database.add_address_to_group(user_id, address, group_id)

    if success:
        await callback.answer("✅ Адрес добавлен в группу!")
        await state.clear()
        # Show updated address list
        await back_to_list(callback)
    else:
        await callback.answer("❌ Ошибка при добавлении в группу", show_alert=True)


@router.callback_query(F.data == "cancel_group")
async def cancel_group_creation(callback: CallbackQuery, state: FSMContext):
    """Cancel group creation."""
    await state.clear()
    await back_to_list(callback)


async def show_settings(message: Message):
    """Show user settings.

    Args:
        message: Message object
    """
    settings = await database.get_user_settings(message.from_user.id)
    count = await database.get_tracked_address_count(message.from_user.id)

    notifications_status = "Включены ✅" if settings['notifications_enabled'] else "Выключены ❌"

    await message.reply(
        f"⚙️ <b>Настройки</b>\n\n"
        f"👤 <b>Пользователь:</b> {message.from_user.first_name}\n"
        f"📋 <b>Отслеживаемых адресов:</b> {count}\n"
        f"🔔 <b>Уведомления:</b> {notifications_status}\n",
        reply_markup=get_notifications_keyboard(settings['notifications_enabled']),
        parse_mode="HTML"
    )


async def show_settings_callback(callback: CallbackQuery):
    """Show user settings via callback.

    Args:
        callback: CallbackQuery object
    """
    settings = await database.get_user_settings(callback.from_user.id)
    count = await database.get_tracked_address_count(callback.from_user.id)

    notifications_status = "Включены ✅" if settings['notifications_enabled'] else "Выключены ❌"

    await callback.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"👤 <b>Пользователь:</b> {callback.from_user.first_name}\n"
        f"📋 <b>Отслеживаемых адресов:</b> {count}\n"
        f"🔔 <b>Уведомления:</b> {notifications_status}\n",
        reply_markup=get_notifications_keyboard(settings['notifications_enabled']),
        parse_mode="HTML"
    )


# Telegram Stars payment handlers

@router.callback_query(F.data.startswith("buy_whale_check_"))
async def buy_whale_check_callback(callback: CallbackQuery):
    """Handle purchase of additional whale check(s) via Telegram Stars.

    Callback data format: buy_whale_check_{attempts}_{price}
    """
    try:
        # Parse callback data: buy_whale_check_5_400 -> attempts=5, price=400
        parts = callback.data.split("_")
        attempts = int(parts[3])  # Number of attempts to purchase
        price_stars = int(parts[4])  # Price in stars
    except Exception:
        await callback.answer("❌ Ошибка в данных", show_alert=True)
        return

    user_id = callback.from_user.id

    # Create invoice label based on attempts count
    if attempts == 1:
        label = "Дополнительная попытка 'Подсмотреть'"
        title = "🎰 Дополнительная попытка"
        description = "Купить 1 дополнительную попытку 'Подсмотреть'.\n\nВы сможете найти адрес с призовым балансом!"
    else:
        label = f"{attempts} попыток 'Подсмотреть'"
        title = f"🎰 Пакет: {attempts} попыток"
        description = f"Купить {attempts} дополнительных попыток 'Подсмотреть'.\n\nВы сможете найти адрес с призовым балансом!"

    prices = [LabeledPrice(label=label, amount=price_stars)]

    # Delete previous message and send invoice
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer_invoice(
        title=title,
        description=description,
        payload=f"whale_check:{user_id}:{attempts}:{price_stars}",
        provider_token="",  # Empty for Telegram Stars
        currency="XTR",  # Telegram Stars currency code
        prices=prices
    )

    await callback.answer()


@router.callback_query(F.data == "menu_subscription")
async def menu_subscription_callback(callback: CallbackQuery):
    """Show subscription info page."""
    user_id = callback.from_user.id
    settings = await database.get_user_settings(user_id)
    is_premium = settings.get('is_premium', 0)

    if is_premium:
        msg = (
            "💎 <b>Ваша подписка: PREMIUM</b>\n\n"
            "✅ Безлимитное отслеживание адресов\n"
            "✅ Безлимитное создание групп\n"
            "✅ 5 попыток 'Подсмотреть' в день\n"
            "   <i>(дополнительные: от 100 ⭐, пакеты со скидкой до 40%)</i>\n"
            "✅ 20 АМЛ отчетов в месяц <i>(скоро)</i>\n"
            "✅ Доступ в Discord и VIP Telegram\n"
            "✅ Бонусы при эйрдропе 🎁\n\n"
            "<i>Спасибо за поддержку!</i> 🙏"
        )
        buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data="cancel")]]
    else:
        limits = await database.get_free_limits(user_id)
        msg = (
            "📋 <b>Ваша подписка: FREE</b>\n\n"
            f"👀 Подсмотреть: {limits['whale']['remaining']} попыток\n"
            f"📊 Запросы по адресам: {limits['reports']['remaining']}/{limits['reports']['max']} сегодня\n"
            f"⭐ Избранное: {limits['favorites']['count']}/{limits['favorites']['max']} адресов\n"
            f"📁 Группы: {limits['groups']['count']}/{limits['groups']['max']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 <b>PREMIUM подписка</b>\n\n"
            "✨ Безлимитное отслеживание адресов\n"
            "✨ Безлимитное создание групп\n"
            "✨ 5 попыток 'Подсмотреть' в день\n"
            "   <i>(дополнительные: от 100 ⭐, пакеты со скидкой до 40%)</i>\n"
            "✨ 20 АМЛ отчетов в месяц <i>(скоро)</i>\n"
            "✨ Доступ в Discord и VIP Telegram\n"
            "✨ Бонусы при эйрдропе 🎁\n\n"
            "💰 <b>Цена: 1 ⭐</b> (тестовый период)"
        )
        buttons = [
            [InlineKeyboardButton(text="💎 Купить Premium (1 ⭐)", callback_data="buy_premium")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cancel")]
        ]

    await callback.message.edit_text(
        msg,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "buy_premium")
async def buy_premium_callback(callback: CallbackQuery):
    """Handle premium subscription purchase."""
    user_id = callback.from_user.id

    # Check if already premium
    settings = await database.get_user_settings(user_id)
    if settings.get('is_premium', 0):
        await callback.answer("💎 Вы уже Premium пользователь!", show_alert=True)
        return

    # Create invoice for Telegram Stars (1 star for testing)
    prices = [LabeledPrice(label="Premium подписка", amount=1)]

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer_invoice(
        title="💎 Premium подписка",
        description=(
            "✨ Безлимитное отслеживание адресов и групп\n"
            "✨ 5 попыток 'Подсмотреть' в день\n"
            "✨ 20 АМЛ отчетов в месяц (скоро)\n"
            "✨ Discord + VIP Telegram\n"
            "✨ Бонусы при эйрдропе"
        ),
        payload=f"premium:{user_id}",
        provider_token="",  # Empty for Telegram Stars
        currency="XTR",
        prices=prices
    )

    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    """
    Handle pre-checkout query (mandatory for Telegram payments).
    This is called before the user confirms payment.
    """
    # Always approve the checkout
    # You can add validation logic here if needed
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    """
    Handle successful payment.
    Grant the user premium status or additional whale check attempt.
    """
    payment = message.successful_payment
    user_id = message.from_user.id

    # Parse payload to determine what was purchased
    payload = payment.invoice_payload

    try:
        parts = payload.split(":")

        if parts[0] == "premium":
            # User bought premium subscription
            await database.update_premium_status(user_id, True)

            await message.answer(
                "🎉 <b>Добро пожаловать в Premium!</b>\n\n"
                "✅ Безлимитное отслеживание адресов\n"
                "✅ Безлимитное создание групп\n"
                "✅ 5 попыток 'Подсмотреть' в день\n"
                "   <i>(дополнительные: от 100 ⭐, пакеты со скидкой до 40%)</i>\n"
                "✅ 20 АМЛ отчетов в месяц <i>(скоро)</i>\n"
                "✅ Доступ в Discord и VIP Telegram\n"
                "✅ Бонусы при эйрдропе 🎁\n\n"
                "<i>Спасибо за поддержку! 💎</i>",
                parse_mode="HTML",
                reply_markup=get_main_menu()
            )

            print(f"💎 Premium purchased: {payment.total_amount} XTR from user {user_id}")

        elif parts[0] == "whale_check":
            # User bought additional whale check(s)
            # Payload format: whale_check:{user_id}:{attempts}:{price}
            attempts = int(parts[2]) if len(parts) > 2 else 1

            # Grant attempts by decrementing counter multiple times
            for _ in range(attempts):
                await database.decrement_whale_check(user_id)

            checks_used, max_checks = await database.get_whale_checks_remaining(user_id)
            remaining = max_checks - checks_used

            if attempts == 1:
                attempts_text = "1 дополнительная попытка"
            else:
                attempts_text = f"{attempts} дополнительных попыток"

            await message.answer(
                f"✅ <b>Оплата успешна!</b>\n\n"
                f"💫 Вам начислено {attempts_text} 'Подсмотреть'\n"
                f"👀 Осталось попыток: {remaining}\n\n"
                f"<i>Спасибо за поддержку! Удачи в поиске призового адреса! 🎰</i>",
                parse_mode="HTML"
            )

            print(f"💰 Whale check purchased: {attempts} attempts for {payment.total_amount} XTR from user {user_id}")

    except Exception as e:
        print(f"❌ Error processing payment: {e}")
        await message.answer(
            "⚠️ Оплата прошла успешно, но произошла ошибка.\n\n"
            "Пожалуйста, свяжитесь с поддержкой.",
            parse_mode="HTML"
        )


# ==================== ADMIN COMMANDS ====================


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Handle /admin command - show admin panel."""
    user_id = message.from_user.id

    if not is_admin(user_id):
        await message.reply("❌ У вас нет прав администратора.")
        return

    await message.answer(
        "🔐 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_admin_panel_keyboard()
    )


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    """Show admin panel."""
    user_id = callback.from_user.id

    if not is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🔐 <b>Админ-панель</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_admin_panel_keyboard()
    )


@router.callback_query(F.data == "admin_find_user")
async def admin_find_user(callback: CallbackQuery, state: FSMContext):
    """Admin: find user by ID."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "👤 <b>Поиск пользователя</b>\n\n"
        "Введите Telegram ID пользователя:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_user_id)


@router.callback_query(F.data == "admin_give_premium")
async def admin_give_premium(callback: CallbackQuery, state: FSMContext):
    """Admin: give premium to user."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "💎 <b>Выдать премиум</b>\n\n"
        "Введите Telegram ID пользователя:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_premium_user_id)


@router.callback_query(F.data == "admin_remove_premium")
async def admin_remove_premium(callback: CallbackQuery, state: FSMContext):
    """Admin: remove premium from user."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "❌ <b>Убрать премиум</b>\n\n"
        "Введите Telegram ID пользователя:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_remove_premium_user_id)


@router.callback_query(F.data == "admin_give_attempts")
async def admin_give_attempts(callback: CallbackQuery, state: FSMContext):
    """Admin: give free attempts to user."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🎁 <b>Выдать попытки</b>\n\n"
        "Введите Telegram ID пользователя:",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_attempts_user_id)


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    """Admin: show bot statistics."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    # Get stats from database
    try:
        all_addresses = await database.get_all_tracked_addresses()
        total_addresses = len(all_addresses)
        unique_users = len(set(addr['user_id'] for addr in all_addresses))

        stats_msg = (
            "📊 <b>Статистика бота</b>\n\n"
            f"👥 Активных пользователей: {unique_users}\n"
            f"📍 Отслеживаемых адресов: {total_addresses}\n"
            f"🔐 Админов: {len(get_admin_ids())}\n"
        )

        await callback.message.edit_text(
            stats_msg,
            parse_mode="HTML",
            reply_markup=get_admin_panel_keyboard()
        )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка получения статистики: {e}",
            parse_mode="HTML",
            reply_markup=get_admin_panel_keyboard()
        )


@router.message(StateFilter(AdminStates.waiting_for_user_id))
async def admin_process_user_id(message: Message, state: FSMContext):
    """Process user ID input for admin search."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        await message.reply(
            "❌ Некорректный ID. Введите числовой Telegram ID.",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Get user info
    settings = await database.get_user_settings(target_user_id)
    limits = await database.get_free_limits(target_user_id)

    is_premium = settings.get('is_premium', 0)
    whale_remaining = limits['whale']['remaining']

    user_info = (
        f"👤 <b>Пользователь #{target_user_id}</b>\n\n"
        f"💎 Премиум: {'Да' if is_premium else 'Нет'}\n"
        f"👀 Попыток осталось: {whale_remaining}\n"
        f"📍 Избранных адресов: {limits['favorites']['count']}\n"
        f"📁 Групп: {limits['groups']['count']}\n"
    )

    await state.clear()
    await message.answer(
        user_info,
        parse_mode="HTML",
        reply_markup=get_admin_user_actions_keyboard(target_user_id, bool(is_premium))
    )


@router.message(StateFilter(AdminStates.waiting_for_premium_user_id))
async def admin_process_premium_user_id(message: Message, state: FSMContext):
    """Process user ID for giving premium."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        await message.reply(
            "❌ Некорректный ID. Введите числовой Telegram ID.",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Give premium
    await database.update_premium_status(target_user_id, True)

    await state.clear()
    await message.answer(
        f"✅ Премиум выдан пользователю #{target_user_id}",
        parse_mode="HTML",
        reply_markup=get_admin_panel_keyboard()
    )


@router.message(StateFilter(AdminStates.waiting_for_remove_premium_user_id))
async def admin_process_remove_premium_user_id(message: Message, state: FSMContext):
    """Process user ID for removing premium."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        await message.reply(
            "❌ Некорректный ID. Введите числовой Telegram ID.",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Remove premium
    await database.update_premium_status(target_user_id, False)

    await state.clear()
    await message.answer(
        f"✅ Премиум убран у пользователя #{target_user_id}",
        parse_mode="HTML",
        reply_markup=get_admin_panel_keyboard()
    )


@router.message(StateFilter(AdminStates.waiting_for_attempts_user_id))
async def admin_process_attempts_user_id(message: Message, state: FSMContext):
    """Process user ID for giving attempts."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        await message.reply(
            "❌ Некорректный ID. Введите числовой Telegram ID.",
            reply_markup=get_cancel_keyboard()
        )
        return

    # Get user info
    settings = await database.get_user_settings(target_user_id)
    is_premium = settings.get('is_premium', 0)

    await state.clear()
    await message.answer(
        f"🎁 <b>Выдать попытки пользователю #{target_user_id}</b>\n\n"
        "Выберите количество попыток:",
        parse_mode="HTML",
        reply_markup=get_admin_user_actions_keyboard(target_user_id, bool(is_premium))
    )


@router.callback_query(F.data.startswith("admin_toggle_premium_"))
async def admin_toggle_premium(callback: CallbackQuery):
    """Admin: toggle premium for user."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    target_user_id = int(callback.data.split("_")[-1])

    # Get current status
    settings = await database.get_user_settings(target_user_id)
    is_premium = settings.get('is_premium', 0)

    # Toggle premium
    new_status = not bool(is_premium)
    await database.update_premium_status(target_user_id, new_status)

    status_text = "выдан" if new_status else "убран"
    await callback.answer(f"✅ Премиум {status_text}!", show_alert=True)

    # Update message
    limits = await database.get_free_limits(target_user_id)
    whale_remaining = limits['whale']['remaining']

    user_info = (
        f"👤 <b>Пользователь #{target_user_id}</b>\n\n"
        f"💎 Премиум: {'Да' if new_status else 'Нет'}\n"
        f"👀 Попыток осталось: {whale_remaining}\n"
        f"📍 Избранных адресов: {limits['favorites']['count']}\n"
        f"📁 Групп: {limits['groups']['count']}\n"
    )

    try:
        await callback.message.edit_text(
            user_info,
            parse_mode="HTML",
            reply_markup=get_admin_user_actions_keyboard(target_user_id, new_status)
        )
    except TelegramBadRequest:
        pass  # Message not modified - ignore


@router.callback_query(F.data.startswith("admin_add_attempts_"))
async def admin_add_attempts(callback: CallbackQuery):
    """Admin: add attempts to user."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    parts = callback.data.split("_")
    target_user_id = int(parts[3])
    amount = int(parts[4])

    # Add attempts
    await database.add_whale_checks(target_user_id, amount)

    await callback.answer(f"✅ Добавлено {amount} попыток!", show_alert=True)

    # Update message
    settings = await database.get_user_settings(target_user_id)
    limits = await database.get_free_limits(target_user_id)

    is_premium = settings.get('is_premium', 0)
    whale_remaining = limits['whale']['remaining']

    user_info = (
        f"👤 <b>Пользователь #{target_user_id}</b>\n\n"
        f"💎 Премиум: {'Да' if is_premium else 'Нет'}\n"
        f"👀 Попыток осталось: {whale_remaining}\n"
        f"📍 Избранных адресов: {limits['favorites']['count']}\n"
        f"📁 Групп: {limits['groups']['count']}\n"
    )

    try:
        await callback.message.edit_text(
            user_info,
            parse_mode="HTML",
            reply_markup=get_admin_user_actions_keyboard(target_user_id, bool(is_premium))
        )
    except TelegramBadRequest:
        pass  # Message not modified - ignore


# ==================== END ADMIN COMMANDS ====================


# Автоматическая проверка адресов в сообщениях
# ВАЖНО: Этот обработчик должен быть в конце, после всех StateFilter обработчиков!


@router.message(F.text)
async def handle_text_message(message: Message, state: FSMContext):
    """Handle text messages - check if it's a Solana address."""
    # Если мы в состоянии ожидания, пропускаем
    current_state = await state.get_state()
    if current_state:
        return

    text = message.text.strip()

    # Проверяем, является ли текст адресом Solana
    if is_blockchain_address(text):
        await check_address(message, text)


def format_wallet_info(info: dict) -> str:
    """Format wallet information into a readable message.

    Args:
        info: Wallet information dict

    Returns:
        Formatted message string
    """
    if "error" in info:
        return f"❌ Ошибка: {info['error']}"

    address = info['address']
    balance = info.get('balance')
    wallet_age = info.get('wallet_age')
    last_tx = info.get('last_transaction')
    symbol = info.get('symbol', '')
    explorer_base = info.get('explorer', 'https://solscan.io')

    # Create explorer URL for address
    if info.get('network_type') == 'evm':
        address_explorer_url = f"{explorer_base}/address/{address}"
    else:  # Solana
        address_explorer_url = f"{explorer_base}/account/{address}"

    # Address with link (hyperlinked text)
    msg = f"📍 <a href='{address_explorer_url}'>{address[:8]}...{address[-6:]}</a>\n"

    # Balance in SOL (native token)
    if balance is not None:
        msg += f"💰 Баланс: {balance:.4f} {symbol}\n"
    else:
        msg += f"💰 Баланс: Недоступен\n"

    msg += "\n"

    # Wallet age (возраст кошелька)
    if wallet_age:
        msg += f"🗓 Возраст кошелька: {wallet_age['formatted']}\n"
        if wallet_age.get('first_transaction_date'):
            first_date = wallet_age['first_transaction_date'].strftime('%d.%m.%Y')
            msg += f"📅 С: {first_date}\n"
    else:
        msg += f"🗓 Возраст кошелька: Нет транзакций\n"

    msg += "\n"

    # Last transaction and activity status
    if last_tx and last_tx.get('timestamp'):
        msg += f"🔄 Последняя транзакция:\n"
        msg += f"⏰ {last_tx['timestamp'].strftime('%d.%m.%Y %H:%M:%S')}\n"
        msg += f"🔗 <a href='{last_tx['explorer_url']}'>Посмотреть в эксплорере</a>\n\n"

        # Calculate activity status based on last transaction time
        from datetime import datetime, timedelta
        now = datetime.now()
        last_tx_time = last_tx['timestamp']
        time_diff = now - last_tx_time

        if time_diff <= timedelta(days=30):  # Last month
            activity_status = "🟢 Активный"
        elif time_diff <= timedelta(days=180):  # 30 days to 6 months
            activity_status = "🟡 Засыпающий"
        else:  # More than 6 months
            activity_status = "🔴 Спящий"

        msg += f"📊 Статус: {activity_status}\n"

    return msg
