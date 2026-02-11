"""AML Shield Telegram bot handlers."""

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, ForceReply
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from typing import Optional

from .service import AMLService

# ============================================================
# FSM States
# ============================================================

class AMLStates(StatesGroup):
    """States for AML conversation."""
    waiting_for_question = State()


# ============================================================
# Router и глобальные переменные
# ============================================================

aml_router = Router()

# Глобальные переменные (инициализируются через init_aml_handlers)
aml_service: Optional[AMLService] = None
database = None

# Быстрые вопросы
QUICK_QUESTIONS = {
    "aml_dirty": "Что такое грязная крипта и чем она опасна для обычного пользователя? Объясни простым языком с примерами.",
    "aml_p2p": "Насколько безопасно покупать крипту через P2P? На что обратить внимание чтобы не получить грязные монеты? Дай практический чеклист.",
    "aml_frozen": "Биржа заморозила мой счёт из-за подозрительной транзакции. Почему это могло произойти и что делать? Пошаговый план.",
    "aml_redflags": "Какие главные красные флаги что крипта может быть грязной? Простой чеклист для обычного человека.",
    "aml_check": "Как обычному человеку проверить криптовалюту или адрес перед покупкой? Какие есть бесплатные инструменты и на что смотреть?",
}

# Лимиты
FREE_QUESTIONS_PER_DAY = 5


def init_aml_handlers(db, api_key: Optional[str] = None):
    """Initialize AML handlers with dependencies.

    Args:
        db: Database instance
        api_key: Optional Anthropic API key
    """
    global aml_service, database
    database = db
    try:
        aml_service = AMLService(api_key)
    except ValueError as e:
        print(f"Warning: AML Service not initialized: {e}")
        aml_service = None


def register_aml_handlers(dp):
    """Register AML router with dispatcher.

    Args:
        dp: Dispatcher instance
    """
    dp.include_router(aml_router)


# ============================================================
# Database helpers
# ============================================================

async def check_aml_usage(user_id: int) -> bool:
    """Check if user can ask AML questions.

    Args:
        user_id: Telegram user ID

    Returns:
        True if user has remaining questions
    """
    if not database:
        return True

    used = await database.get_aml_questions_today(user_id)
    # TODO: Check premium for unlimited
    return used < FREE_QUESTIONS_PER_DAY


async def increment_aml_usage(user_id: int):
    """Increment user's AML question count.

    Args:
        user_id: Telegram user ID
    """
    if database:
        await database.increment_aml_questions(user_id)


async def save_conversation(user_id: int, question: str, answer: str):
    """Save conversation to database.

    Args:
        user_id: Telegram user ID
        question: User's question
        answer: AI's answer
    """
    if database:
        await database.save_aml_conversation(user_id, question, answer)


async def get_conversation_history(user_id: int, limit: int = 4):
    """Get user's conversation history.

    Args:
        user_id: Telegram user ID
        limit: Number of message pairs to retrieve

    Returns:
        List of conversation messages
    """
    if database:
        return await database.get_aml_conversation_history(user_id, limit)
    return []


# ============================================================
# Handlers
# ============================================================

@aml_router.message(Command("aml"))
async def cmd_aml(message: Message):
    """Handle /aml command - show AML menu."""
    if not aml_service:
        await message.answer(
            "⚠️ AML Shield временно недоступен.\n"
            "Проверьте настройку ANTHROPIC_API_KEY."
        )
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Что такое грязная крипта?", callback_data="aml_dirty")],
        [InlineKeyboardButton(text="🔄 Безопасен ли P2P?", callback_data="aml_p2p")],
        [InlineKeyboardButton(text="🧊 Заморозили счёт!", callback_data="aml_frozen")],
        [InlineKeyboardButton(text="⚠️ Красные флаги", callback_data="aml_redflags")],
        [InlineKeyboardButton(text="🛡️ Как проверить крипту?", callback_data="aml_check")],
        [InlineKeyboardButton(text="💬 Задать свой вопрос", callback_data="aml_ask")],
    ])

    await message.answer(
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


@aml_router.callback_query(F.data == "aml_menu")
async def callback_aml_menu(callback: CallbackQuery):
    """Return to AML menu."""
    await callback.answer()

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Что такое грязная крипта?", callback_data="aml_dirty")],
        [InlineKeyboardButton(text="🔄 Безопасен ли P2P?", callback_data="aml_p2p")],
        [InlineKeyboardButton(text="🧊 Заморозили счёт!", callback_data="aml_frozen")],
        [InlineKeyboardButton(text="⚠️ Красные флаги", callback_data="aml_redflags")],
        [InlineKeyboardButton(text="🛡️ Как проверить крипту?", callback_data="aml_check")],
        [InlineKeyboardButton(text="💬 Задать свой вопрос", callback_data="aml_ask")],
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


@aml_router.callback_query(F.data.in_(QUICK_QUESTIONS.keys()))
async def callback_quick_question(callback: CallbackQuery):
    """Handle quick question callbacks."""
    await callback.answer()

    user_id = callback.from_user.id
    question_key = callback.data
    question = QUICK_QUESTIONS[question_key]

    # Check usage limit
    can_ask = await check_aml_usage(user_id)
    if not can_ask:
        await callback.message.edit_text(
            "⚠️ Лимит вопросов на сегодня исчерпан (5/5)\n\n"
            "💫 <b>Pro-подписка</b> — безлимитные AML-консультации\n"
            "Или возвращайся завтра!",
            parse_mode="HTML"
        )
        return

    # Show loading message
    await callback.message.edit_text("🛡️ Анализирую...")

    # Get answer from AI
    answer = await aml_service.ask(question)

    # Update usage and save conversation
    await increment_aml_usage(user_id)
    await save_conversation(user_id, question, answer)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Уточнить", callback_data="aml_ask"),
            InlineKeyboardButton(text="🔙 AML меню", callback_data="aml_menu"),
        ],
    ])

    await callback.message.edit_text(
        answer,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@aml_router.callback_query(F.data == "aml_ask")
async def callback_aml_ask(callback: CallbackQuery, state: FSMContext):
    """Handle 'ask question' callback."""
    await callback.answer()

    await state.set_state(AMLStates.waiting_for_question)

    await callback.message.answer(
        "💬 Задай свой вопрос по крипто-безопасности.\n\n"
        "Например:\n"
        "• <i>\"Что будет если я получу крипту с миксера?\"</i>\n"
        "• <i>\"Кто такие Lazarus Group?\"</i>\n"
        "• <i>\"Как работают peel-цепочки?\"</i>\n\n"
        "Напиши вопрос прямо сейчас 👇",
        parse_mode="HTML"
    )


@aml_router.message(StateFilter(AMLStates.waiting_for_question))
async def process_aml_question(message: Message, state: FSMContext):
    """Process user's AML question."""
    user_id = message.from_user.id
    question = message.text

    if not question or question.startswith("/"):
        await state.clear()
        return

    # Check usage limit
    can_ask = await check_aml_usage(user_id)
    if not can_ask:
        await message.answer(
            "⚠️ Лимит AML-вопросов на сегодня: 5/5\n"
            "Pro-подписка = безлимит 🛡️",
            parse_mode="HTML"
        )
        await state.clear()
        return

    # Show typing action
    await message.answer("🛡️ Анализирую...")

    # Get conversation history for context
    history = await get_conversation_history(user_id, 4)

    # Get answer from AI
    answer = await aml_service.ask(question, history)

    # Update usage and save
    await increment_aml_usage(user_id)
    await save_conversation(user_id, question, answer)

    await state.clear()

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Ещё вопрос", callback_data="aml_ask"),
            InlineKeyboardButton(text="🔙 AML меню", callback_data="aml_menu"),
        ],
    ])

    await message.answer(
        answer,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
