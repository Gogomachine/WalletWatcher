"""Bot command handlers."""

import re
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatType
from .keyboards import (
    get_main_menu,
    get_tracked_addresses_keyboard,
    get_address_actions_keyboard,
    get_notifications_keyboard,
    get_cancel_keyboard,
    get_skip_keyboard
)
from ..solana.client import SolanaClient
from ..database.db import Database


router = Router()


class AddressStates(StatesGroup):
    """States for address input."""
    waiting_for_address = State()
    waiting_for_nickname = State()


# Глобальные переменные для клиентов (будут инициализированы в main.py)
solana_client: SolanaClient = None
database: Database = None
monitor = None


def init_handlers(sol_client: SolanaClient, db: Database, addr_monitor):
    """Initialize handlers with dependencies.

    Args:
        sol_client: Solana client instance
        db: Database instance
        addr_monitor: Address monitor instance
    """
    global solana_client, database, monitor
    solana_client = sol_client
    database = db
    monitor = addr_monitor


def is_solana_address(text: str) -> bool:
    """Check if text looks like a Solana address.

    Args:
        text: Text to check

    Returns:
        True if looks like Solana address
    """
    if not text:
        return False
    # Solana addresses are base58 encoded, 32-44 characters
    return bool(re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', text.strip()))


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
    # Если в группе, отвечаем кратко
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(
            "👋 Привет! Я бот для отслеживания Solana адресов.\n\n"
            "Отправьте адрес или используйте /menu для просмотра команд."
        )
    else:
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            f"Я бот для отслеживания Solana адресов.\n\n"
            f"Я могу:\n"
            f"• Показать информацию о любом адресе\n"
            f"• Отслеживать адреса в реальном времени\n"
            f"• Уведомлять о новых транзакциях\n\n"
            f"Используйте меню ниже для навигации:",
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
        "/settings - Настройки\n\n"
        "<b>Получение информации:</b>\n"
        "Просто отправьте Solana адрес, и я покажу всю информацию о нём:\n"
        "• Баланс в SOL\n"
        "• Возраст кошелька\n"
        "• Последняя транзакция\n"
        "• Является ли адрес биржевым\n\n"
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
    if not is_solana_address(address):
        await message.reply("❌ Неверный формат адреса Solana")
        return

    # Добавляем в отслеживание
    success = await database.add_tracked_address(
        message.from_user.id,
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
    addresses = await database.get_user_tracked_addresses(message.from_user.id)

    if not addresses:
        await message.reply(
            "У вас пока нет отслеживаемых адресов.\n\n"
            "Используйте /track <адрес> для добавления."
        )
        return

    keyboard = get_tracked_addresses_keyboard(addresses)
    await message.reply(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес для управления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    """Handle /settings command."""
    await show_settings(message)


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

    if not addresses:
        await callback.message.edit_text(
            "У вас пока нет отслеживаемых адресов.\n\n"
            "Используйте меню для добавления.",
            reply_markup=get_main_menu()
        )
        await callback.answer()
        return

    keyboard = get_tracked_addresses_keyboard(addresses)
    await callback.message.edit_text(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес для управления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu_settings")
async def menu_settings_callback(callback: CallbackQuery):
    """Handle 'Settings' menu button."""
    await show_settings_callback(callback)


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

    # Добавляем без никнейма
    success = await database.add_tracked_address(
        callback.from_user.id,
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
    if not is_solana_address(address):
        await message.reply(
            "❌ Неверный формат адреса Solana.\n\n"
            "Адрес должен быть в формате base58 и содержать 32-44 символа."
        )
        return

    await message.reply("⏳ Получаю информацию...")

    info = await solana_client.get_wallet_info(address)

    if "error" in info:
        await message.reply(
            f"❌ Ошибка: {info['error']}\n\n"
            "Убедитесь, что вы отправили корректный Solana адрес."
        )
        await state.clear()
        return

    # Форматирование сообщения
    msg = format_wallet_info(info)

    # Проверяем, добавляем ли адрес в отслеживание
    data = await state.get_data()
    if data.get('adding_to_tracking'):
        # Сохраняем адрес и спрашиваем никнейм
        await state.update_data(address=address)
        await state.set_state(AddressStates.waiting_for_nickname)
        await message.reply(msg, disable_web_page_preview=True, parse_mode="HTML")
        await message.reply(
            "✏️ Хотите задать никнейм для этого адреса?\n\n"
            "Отправьте никнейм или нажмите 'Пропустить':",
            reply_markup=get_skip_keyboard()
        )
    else:
        await message.reply(msg, disable_web_page_preview=True, parse_mode="HTML")
        await state.clear()


@router.message(StateFilter(AddressStates.waiting_for_nickname))
async def process_nickname(message: Message, state: FSMContext):
    """Process nickname for tracked address."""
    data = await state.get_data()
    address = data['address']
    nickname = message.text.strip()

    # Добавляем адрес в отслеживание
    success = await database.add_tracked_address(
        message.from_user.id,
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


# Автоматическая проверка адресов в сообщениях


@router.message(F.text)
async def handle_text_message(message: Message, state: FSMContext):
    """Handle text messages - check if it's a Solana address."""
    # Если мы в состоянии ожидания, пропускаем
    current_state = await state.get_state()
    if current_state:
        return

    text = message.text.strip()

    # Проверяем, является ли текст адресом Solana
    if is_solana_address(text):
        await check_address(message, text)


async def check_address(message: Message, address: str):
    """Check and display address information.

    Args:
        message: Message object
        address: Solana address
    """
    await message.reply("⏳ Получаю информацию...")

    info = await solana_client.get_wallet_info(address)

    if "error" in info:
        await message.reply(f"❌ Ошибка: {info['error']}")
        return

    msg = format_wallet_info(info)
    await message.reply(msg, disable_web_page_preview=True, parse_mode="HTML")


# Address management callbacks


@router.callback_query(F.data.startswith("addr_"))
async def show_address_actions(callback: CallbackQuery):
    """Show actions for a tracked address."""
    address = callback.data.split("_", 1)[1]

    await callback.message.edit_text(
        f"🔍 <b>Адрес:</b> <code>{address}</code>\n\n"
        "Выберите действие:",
        reply_markup=get_address_actions_keyboard(address),
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

    info = await solana_client.get_wallet_info(address)
    msg = format_wallet_info(info)

    await callback.message.edit_text(msg, disable_web_page_preview=True, parse_mode="HTML")
    await callback.answer()


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
    addresses = await database.get_user_tracked_addresses(callback.from_user.id)
    keyboard = get_tracked_addresses_keyboard(addresses)

    await callback.message.edit_text(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес для управления:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


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
    is_exchange = info.get('is_exchange')
    exchange_name = info.get('exchange_name')

    # Create explorer URL for address
    address_explorer_url = f"https://solscan.io/account/{address}"

    msg = f"📊 <b>Информация об адресе</b>\n\n"
    msg += f"📍 <a href='{address_explorer_url}'><b>{address[:8]}...{address[-6:]}</b></a>\n\n"

    # Exchange status
    if is_exchange:
        msg += f"🏦 <b>Биржа:</b> {exchange_name} ✅\n\n"

    # Balance - Total Value (текущий баланс)
    if balance is not None:
        msg += f"💰 <b>Total Value:</b> {balance:.4f} SOL\n\n"
    else:
        msg += f"💰 <b>Total Value:</b> Недоступен\n\n"

    # Wallet age (возраст кошелька)
    if wallet_age:
        msg += f"🗓️ <b>Возраст кошелька:</b> {wallet_age['formatted']}\n"
        if wallet_age.get('first_transaction_date'):
            first_date = wallet_age['first_transaction_date'].strftime('%d.%m.%Y')
            msg += f"📅 <b>С:</b> {first_date}\n\n"
    else:
        msg += f"🗓️ <b>Возраст кошелька:</b> Нет транзакций\n\n"

    # Last transaction
    if last_tx and last_tx.get('timestamp'):
        msg += f"🔄 <b>Последняя транзакция:</b>\n"
        msg += f"⏰ {last_tx['timestamp'].strftime('%d.%m.%Y %H:%M:%S')}\n"
        msg += f"🔗 <a href='{last_tx['explorer_url']}'>Посмотреть в эксплорере</a>\n"

    return msg
