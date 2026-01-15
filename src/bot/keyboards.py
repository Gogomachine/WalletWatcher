"""Keyboard layouts for the bot."""

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)


def get_main_menu() -> ReplyKeyboardMarkup:
    """Get main menu keyboard.

    Returns:
        Main menu keyboard
    """
    keyboard = [
        [KeyboardButton(text="📊 Проверить адрес")],
        [KeyboardButton(text="➕ Добавить адрес"), KeyboardButton(text="📋 Мои адреса")],
        [KeyboardButton(text="⚙️ Настройки")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


def get_back_keyboard(skip_button: bool = False) -> ReplyKeyboardMarkup:
    """Get keyboard with back button.

    Args:
        skip_button: Whether to include skip button

    Returns:
        Keyboard with back button
    """
    keyboard = []
    if skip_button:
        keyboard.append([KeyboardButton(text="⏭️ Пропустить")])
    keyboard.append([KeyboardButton(text="🔙 Назад")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True
    )


def get_tracked_addresses_keyboard(addresses: list) -> InlineKeyboardMarkup:
    """Get keyboard with tracked addresses.

    Args:
        addresses: List of tracked address records

    Returns:
        Inline keyboard with addresses
    """
    buttons = []

    for addr in addresses:
        address = addr['address']
        nickname = addr.get('nickname')

        # Кнопка с никнеймом или сокращенным адресом
        label = nickname if nickname else f"{address[:8]}...{address[-4:]}"

        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"addr_{address}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_address_actions_keyboard(address: str) -> InlineKeyboardMarkup:
    """Get keyboard with actions for an address.

    Args:
        address: Solana address

    Returns:
        Inline keyboard with actions
    """
    buttons = [
        [InlineKeyboardButton(text="🔍 Проверить", callback_data=f"check_{address}")],
        [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"remove_{address}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_list")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_notifications_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    """Get keyboard for notification settings.

    Args:
        enabled: Whether notifications are currently enabled

    Returns:
        Inline keyboard with notification toggle
    """
    button_text = "🔕 Выключить уведомления" if enabled else "🔔 Включить уведомления"

    buttons = [
        [InlineKeyboardButton(text=button_text, callback_data="toggle_notifications")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)
