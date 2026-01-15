"""Bot command handlers."""

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from .keyboards import (
    get_main_menu,
    get_tracked_addresses_keyboard,
    get_address_actions_keyboard,
    get_notifications_keyboard,
    get_back_keyboard
)
from ..solana.client import SolanaClient
from ..database.db import Database


router = Router()


class AddressStates(StatesGroup):
    """States for address input."""
    waiting_for_address = State()
    waiting_for_nickname = State()
    waiting_for_remove_address = State()


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


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command."""
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
    await message.answer(
        "📖 <b>Справка</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/menu - Показать главное меню\n\n"
        "<b>Получение информации:</b>\n"
        "Просто отправьте Solana адрес, и я покажу всю информацию о нём:\n"
        "• Баланс в SOL\n"
        "• Возраст кошелька\n"
        "• Последняя транзакция\n"
        "• Является ли адрес биржевым\n\n"
        "<b>Отслеживание:</b>\n"
        "Добавьте адрес в список отслеживания, и вы будете получать уведомления "
        "о каждой новой транзакции в режиме реального времени.",
        reply_markup=get_back_keyboard()
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Handle /menu command."""
    await message.answer(
        "📱 Главное меню:",
        reply_markup=get_main_menu()
    )


@router.message(F.text == "📊 Проверить адрес")
async def check_address_request(message: Message, state: FSMContext):
    """Request address to check."""
    await state.set_state(AddressStates.waiting_for_address)
    await message.answer(
        "📍 Отправьте Solana адрес для проверки:\n\n"
        "Пример: 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        reply_markup=get_back_keyboard()
    )


@router.message(F.text == "➕ Добавить адрес")
async def add_address_request(message: Message, state: FSMContext):
    """Request address to add to tracking."""
    await state.set_state(AddressStates.waiting_for_address)
    await state.update_data(adding_to_tracking=True)
    await message.answer(
        "📍 Отправьте Solana адрес для отслеживания:\n\n"
        "Пример: 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        reply_markup=get_back_keyboard()
    )


@router.message(F.text == "📋 Мои адреса")
async def show_tracked_addresses(message: Message):
    """Show user's tracked addresses."""
    addresses = await database.get_user_tracked_addresses(message.from_user.id)

    if not addresses:
        await message.answer(
            "У вас пока нет отслеживаемых адресов.\n\n"
            "Используйте кнопку '➕ Добавить адрес' для добавления.",
            reply_markup=get_main_menu()
        )
        return

    keyboard = get_tracked_addresses_keyboard(addresses)
    await message.answer(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес для управления:",
        reply_markup=keyboard
    )


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message):
    """Show user settings."""
    settings = await database.get_user_settings(message.from_user.id)
    count = await database.get_tracked_address_count(message.from_user.id)

    notifications_status = "Включены ✅" if settings['notifications_enabled'] else "Выключены ❌"

    await message.answer(
        f"⚙️ <b>Настройки</b>\n\n"
        f"👤 <b>Пользователь:</b> {message.from_user.first_name}\n"
        f"📋 <b>Отслеживаемых адресов:</b> {count}\n"
        f"🔔 <b>Уведомления:</b> {notifications_status}\n",
        reply_markup=get_notifications_keyboard(settings['notifications_enabled'])
    )


@router.message(StateFilter(AddressStates.waiting_for_address))
async def process_address(message: Message, state: FSMContext):
    """Process received address."""
    address = message.text.strip()

    # Проверка валидности адреса и получение информации
    await message.answer("⏳ Получаю информацию...")

    info = await solana_client.get_wallet_info(address)

    if "error" in info:
        await message.answer(
            f"❌ Ошибка: {info['error']}\n\n"
            "Убедитесь, что вы отправили корректный Solana адрес.",
            reply_markup=get_main_menu()
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
        await message.answer(msg, disable_web_page_preview=True)
        await message.answer(
            "✏️ Хотите задать никнейм для этого адреса?\n\n"
            "Отправьте никнейм или нажмите 'Пропустить':",
            reply_markup=get_back_keyboard(skip_button=True)
        )
    else:
        await message.answer(msg, reply_markup=get_main_menu(), disable_web_page_preview=True)
        await state.clear()


@router.message(StateFilter(AddressStates.waiting_for_nickname))
async def process_nickname(message: Message, state: FSMContext):
    """Process nickname for tracked address."""
    data = await state.get_data()
    address = data['address']

    nickname = None if message.text == "⏭️ Пропустить" else message.text.strip()

    # Добавляем адрес в отслеживание
    success = await database.add_tracked_address(
        message.from_user.id,
        address,
        nickname
    )

    if success:
        await message.answer(
            f"✅ Адрес успешно добавлен в отслеживание!\n\n"
            f"{'🏷️ Никнейм: ' + nickname if nickname else ''}\n"
            f"Вы будете получать уведомления о новых транзакциях.",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            "❌ Этот адрес уже отслеживается.",
            reply_markup=get_main_menu()
        )

    await state.clear()


@router.callback_query(F.data.startswith("addr_"))
async def show_address_actions(callback: CallbackQuery):
    """Show actions for a tracked address."""
    address = callback.data.split("_", 1)[1]

    await callback.message.edit_text(
        f"🔍 <b>Адрес:</b> <code>{address}</code>\n\n"
        "Выберите действие:",
        reply_markup=get_address_actions_keyboard(address)
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
        )
    else:
        await callback.message.edit_text(
            "❌ Ошибка при удалении адреса."
        )

    await callback.answer()


@router.callback_query(F.data.startswith("check_"))
async def check_address_callback(callback: CallbackQuery):
    """Check address info via callback."""
    address = callback.data.split("_", 1)[1]

    await callback.message.edit_text("⏳ Получаю информацию...")

    info = await solana_client.get_wallet_info(address)
    msg = format_wallet_info(info)

    await callback.message.edit_text(msg, disable_web_page_preview=True)
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
    count = await database.get_tracked_address_count(callback.from_user.id)
    notifications_status = "Включены ✅" if new_state else "Выключены ❌"

    await callback.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"👤 <b>Пользователь:</b> {callback.from_user.first_name}\n"
        f"📋 <b>Отслеживаемых адресов:</b> {count}\n"
        f"🔔 <b>Уведомления:</b> {notifications_status}\n",
        reply_markup=get_notifications_keyboard(new_state)
    )


@router.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    """Go back to address list."""
    addresses = await database.get_user_tracked_addresses(callback.from_user.id)
    keyboard = get_tracked_addresses_keyboard(addresses)

    await callback.message.edit_text(
        f"📋 <b>Ваши отслеживаемые адреса ({len(addresses)}):</b>\n\n"
        "Нажмите на адрес для управления:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.message(F.text == "🔙 Назад")
async def back_to_menu(message: Message, state: FSMContext):
    """Return to main menu."""
    await state.clear()
    await message.answer(
        "📱 Главное меню:",
        reply_markup=get_main_menu()
    )


@router.message(F.text == "⏭️ Пропустить")
async def skip_nickname(message: Message, state: FSMContext):
    """Skip nickname input."""
    await process_nickname(message, state)


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

    msg = f"📊 <b>Информация об адресе</b>\n\n"
    msg += f"📍 <b>Адрес:</b> <code>{address}</code>\n\n"

    # Exchange status
    if is_exchange:
        msg += f"🏦 <b>Биржевой адрес:</b> {exchange_name} ✅\n\n"
    else:
        msg += f"🏦 <b>Биржевой адрес:</b> Нет\n\n"

    # Balance
    if balance is not None:
        msg += f"💰 <b>Баланс:</b> {balance:.4f} SOL\n\n"
    else:
        msg += f"💰 <b>Баланс:</b> Недоступен\n\n"

    # Wallet age
    if wallet_age:
        msg += f"🗓️ <b>Возраст кошелька:</b> {wallet_age['formatted']}\n"
        msg += f"📅 <b>Первая транзакция:</b> {wallet_age['first_transaction'].strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    else:
        msg += f"🗓️ <b>Возраст кошелька:</b> Нет транзакций\n\n"

    # Last transaction
    if last_tx:
        msg += f"🔄 <b>Последняя транзакция:</b>\n"
        msg += f"⏰ {last_tx['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        msg += f"🔗 <a href='{last_tx['explorer_url']}'>Посмотреть в эксплорере</a>\n"

    return msg
