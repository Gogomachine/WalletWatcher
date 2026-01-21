"""Keyboard layouts for the bot."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def get_main_menu() -> InlineKeyboardMarkup:
    """Get main menu keyboard.

    Returns:
        Main menu inline keyboard
    """
    buttons = [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile")],
        [
            InlineKeyboardButton(text="➕ Добавить адрес", callback_data="menu_add"),
            InlineKeyboardButton(text="📋 Мои адреса", callback_data="menu_list")
        ],
        [InlineKeyboardButton(text="👀 Подсмотреть", callback_data="menu_whale")],
        [InlineKeyboardButton(text="🔍 Анализ", callback_data="menu_analysis")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings")],
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


def get_tracked_addresses_keyboard(addresses: list, groups: list = None) -> InlineKeyboardMarkup:
    """Get keyboard with tracked addresses and groups.

    Args:
        addresses: List of tracked address records
        groups: List of group records

    Returns:
        Inline keyboard with addresses and groups
    """
    buttons = []

    # Add groups first if any
    if groups:
        for group in groups:
            group_id = group['id']
            group_name = group['name']
            address_count = group.get('address_count', 0)

            buttons.append([
                InlineKeyboardButton(
                    text=f"📁 {group_name} ({address_count})",
                    callback_data=f"group_{group_id}"
                )
            ])

    # Add ungrouped addresses
    ungrouped = [addr for addr in addresses if not addr.get('group_id')]

    if ungrouped:
        for addr in ungrouped:
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

    # Add "Create Group" button
    buttons.append([
        InlineKeyboardButton(
            text="➕ Создать группу",
            callback_data="create_group"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_address_actions_keyboard(address: str, notifications_enabled: bool = True) -> InlineKeyboardMarkup:
    """Get keyboard with actions for an address.

    Args:
        address: Solana address
        notifications_enabled: Whether notifications are currently enabled

    Returns:
        Inline keyboard with actions
    """
    notif_text = "🔕 Выключить уведомления" if notifications_enabled else "🔔 Включить уведомления"
    notif_callback = f"notif_off_{address}" if notifications_enabled else f"notif_on_{address}"

    buttons = [
        [InlineKeyboardButton(text="🔍 Проверить", callback_data=f"check_{address}")],
        [InlineKeyboardButton(text=notif_text, callback_data=notif_callback)],
        [InlineKeyboardButton(text="✏️ Назвать адрес", callback_data=f"rename_{address}")],
        [InlineKeyboardButton(text="📁 Добавить в группу", callback_data=f"addtogroup_{address}")],
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


def get_whale_result_keyboard(address: str) -> InlineKeyboardMarkup:
    """Get keyboard for whale discovery result.

    Args:
        address: Solana address that was discovered

    Returns:
        Inline keyboard with add to favorites button
    """
    buttons = [
        [InlineKeyboardButton(text="⭐ Добавить в избранное", callback_data=f"fav_add_{address}")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_group_addresses_keyboard(addresses: list, group_id: int) -> InlineKeyboardMarkup:
    """Get keyboard with addresses in a group.

    Args:
        addresses: List of address records in group
        group_id: Group ID

    Returns:
        Inline keyboard with addresses
    """
    buttons = []

    for addr in addresses:
        address = addr['address']
        nickname = addr.get('nickname')

        label = nickname if nickname else f"{address[:8]}...{address[-4:]}"

        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"addr_{address}"
            )
        ])

    # Group balance button
    buttons.append([
        InlineKeyboardButton(
            text="💰 Общий SOL баланс",
            callback_data=f"groupbal_{group_id}"
        )
    ])

    # Back button
    buttons.append([
        InlineKeyboardButton(
            text="🔙 Назад к списку",
            callback_data="back_to_list"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="🗑️ Удалить группу",
            callback_data=f"delgroup_{group_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_select_addresses_keyboard(addresses: list) -> InlineKeyboardMarkup:
    """Get keyboard for selecting addresses to add to group.

    Args:
        addresses: List of ungrouped address records

    Returns:
        Inline keyboard with addresses
    """
    buttons = []

    for addr in addresses:
        address = addr['address']
        nickname = addr.get('nickname')

        label = nickname if nickname else f"{address[:8]}...{address[-4:]}"

        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"selectaddr_{address}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data="cancel_group"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_persistent_keyboard(bot_active: bool = True) -> ReplyKeyboardMarkup:
    """Get persistent reply keyboard shown at the bottom of the chat.

    Args:
        bot_active: Whether bot is active for the user

    Returns:
        Reply keyboard with action buttons
    """
    # Control button changes based on bot status
    control_button = KeyboardButton(text="🛑 Стоп") if bot_active else KeyboardButton(text="🚀 Поехали")

    buttons = [
        [
            KeyboardButton(text="👤 Профиль"),
            KeyboardButton(text="📋 Отслеживание")
        ],
        [
            KeyboardButton(text="👀 Подсмотреть"),
            KeyboardButton(text="🔍 Анализ")
        ],
        [
            KeyboardButton(text="⚙️ Настройки"),
            control_button
        ]
    ]

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        persistent=True
    )
