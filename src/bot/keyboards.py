"""Keyboard layouts for the bot."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu() -> InlineKeyboardMarkup:
    """Get main menu keyboard.

    Returns:
        Main menu inline keyboard
    """
    buttons = [
        [InlineKeyboardButton(text="📊 Проверить адрес", callback_data="menu_check")],
        [
            InlineKeyboardButton(text="➕ Добавить адрес", callback_data="menu_add"),
            InlineKeyboardButton(text="📋 Мои адреса", callback_data="menu_list")
        ],
        [InlineKeyboardButton(text="🎯 Найти случайный кошелёк", callback_data="menu_discover")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tier_discovery_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for tier discovery (gamification).

    Returns:
        Inline keyboard with tier buttons
    """
    buttons = [
        [
            InlineKeyboardButton(text="🐳 Whale", callback_data="discover_whale"),
            InlineKeyboardButton(text="🐬 Dolphin", callback_data="discover_dolphin")
        ],
        [
            InlineKeyboardButton(text="🐟 Fish", callback_data="discover_fish"),
            InlineKeyboardButton(text="🦐 Shrimp", callback_data="discover_shrimp")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard with cancel button.

    Returns:
        Inline keyboard with cancel button
    """
    buttons = [
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_skip_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard with skip and cancel buttons.

    Returns:
        Inline keyboard with skip and cancel
    """
    buttons = [
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_nickname")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
