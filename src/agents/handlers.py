"""Telegram bot handlers for the TxPeek multi-agent AML system.

Integrates the agent system with aiogram handlers for Telegram.
All user-facing interactions go through the Press Office agent.
"""

import logging
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from . import get_agent_system, AgentSystem

logger = logging.getLogger(__name__)

aml_check_router = Router()

# Cache of recent verdicts for detail/screenshot callbacks
_verdict_cache: dict = {}  # case_id -> OfficerVerdict
MAX_CACHE_SIZE = 100


def _cache_verdict(verdict):
    """Cache a verdict for later detail retrieval."""
    global _verdict_cache
    if len(_verdict_cache) > MAX_CACHE_SIZE:
        # Remove oldest entries
        keys = list(_verdict_cache.keys())
        for k in keys[:MAX_CACHE_SIZE // 2]:
            _verdict_cache.pop(k, None)
    _verdict_cache[verdict.case_id] = verdict


# ============================================================
# /check command handler (AML check)
# ============================================================

@aml_check_router.message(Command("txpeek"))
async def cmd_txpeek(message: Message):
    """Handle /txpeek command - full AML address check."""
    system = get_agent_system()
    if not system or not system.is_ready:
        await message.reply(
            "\u26a0\ufe0f AML analysis service is initializing. Please try again.",
            parse_mode=ParseMode.HTML,
        )
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "\U0001f50d <b>TxPeek AML Check</b>\n\n"
            "Usage: <code>/txpeek &lt;address&gt;</code>\n\n"
            "Example:\n"
            "<code>/txpeek 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    address = parts[1].strip()
    bot = message.bot

    verdict = await system.press_office.handle_check_command(
        bot=bot,
        message=message,
        address=address,
    )

    if verdict:
        _cache_verdict(verdict)


# ============================================================
# /risk command handler
# ============================================================

@aml_check_router.message(Command("risk"))
async def cmd_risk(message: Message):
    """Handle /risk command - explain risk levels."""
    system = get_agent_system()
    if not system:
        return

    # Detect language from user settings or default to Russian
    language = "ru"
    text = system.press_office.format_risk_explanation(language)

    await message.reply(text, parse_mode=ParseMode.HTML)


# ============================================================
# /about command handler
# ============================================================

@aml_check_router.message(Command("about"))
async def cmd_about(message: Message):
    """Handle /about command."""
    system = get_agent_system()
    if not system:
        return

    language = "ru"
    text = system.press_office.format_about_message(language)

    await message.reply(text, parse_mode=ParseMode.HTML)


# ============================================================
# Callback handlers for AML results
# ============================================================

@aml_check_router.callback_query(F.data.startswith("aml_detail_"))
async def callback_aml_detail(callback: CallbackQuery):
    """Show detailed AML report."""
    await callback.answer()

    case_id = callback.data.replace("aml_detail_", "")
    verdict = _verdict_cache.get(case_id)

    if not verdict:
        await callback.message.answer(
            "\u26a0\ufe0f Report expired. Please run the check again.",
            parse_mode=ParseMode.HTML,
        )
        return

    system = get_agent_system()
    if not system:
        return

    bot = callback.bot
    chat_id = callback.message.chat.id

    await system.press_office.send_detailed_report(bot, chat_id, verdict)


# ============================================================
# Feedback handlers — самообучение Офицера
# ============================================================

@aml_check_router.callback_query(F.data.startswith("fb_"))
async def callback_feedback(callback: CallbackQuery):
    """Handle feedback buttons for Officer self-learning."""
    await callback.answer()

    data = callback.data  # fb_correct_CASE-XXXXX, fb_incorrect_..., fb_too_high_..., fb_too_low_...

    # Parse feedback type and case_id
    parts = data.split("_", 2)
    if len(parts) < 3:
        return

    feedback_type = parts[1]  # correct, incorrect, too_high, too_low
    # Handle two-word types: too_high, too_low
    if feedback_type == "too":
        sub_parts = data.split("_", 3)
        if len(sub_parts) < 4:
            return
        feedback_type = f"{sub_parts[1]}_{sub_parts[2]}"  # too_high or too_low
        case_id = sub_parts[3]
    else:
        case_id = parts[2]

    verdict = _verdict_cache.get(case_id)
    if not verdict:
        await callback.message.answer(
            "\u26a0\ufe0f Результат устарел. Запустите проверку заново.",
            parse_mode=ParseMode.HTML,
        )
        return

    system = get_agent_system()
    if not system or not system.learning_engine:
        await callback.message.answer(
            "\u26a0\ufe0f Система обучения недоступна.",
            parse_mode=ParseMode.HTML,
        )
        return

    user_id = callback.from_user.id

    await system.learning_engine.record_feedback(
        case_id=case_id,
        user_id=user_id,
        address=verdict.address,
        network=verdict.network,
        risk_score=verdict.risk_score,
        risk_level=verdict.risk_level.label,
        reason=verdict.reason,
        feedback_type=feedback_type,
    )

    feedback_labels = {
        "correct": "\u2705 Спасибо! Отмечено как верный вердикт.",
        "incorrect": "\u274c Спасибо! Отмечено как неверный. Офицер учтёт.",
        "too_high": "\u2b06\ufe0f Спасибо! Отмечено как завышенный риск.",
        "too_low": "\u2b07\ufe0f Спасибо! Отмечено как заниженный риск.",
    }

    response_text = feedback_labels.get(
        feedback_type, "\u2705 Фидбек принят."
    )

    # Показать статистику обучения
    stats = await system.learning_engine.get_stats()
    response_text += (
        f"\n\n<i>\U0001f9e0 Поколение #{stats['generation']} | "
        f"Точность: {stats['accuracy']} | "
        f"Правил: {stats['active_rules']}</i>"
    )

    await callback.message.answer(response_text, parse_mode=ParseMode.HTML)


# ============================================================
# /brain command — статистика обучения
# ============================================================

@aml_check_router.message(Command("brain"))
async def cmd_brain(message: Message):
    """Show Officer learning statistics and evolved rules."""
    system = get_agent_system()
    if not system or not system.learning_engine:
        await message.reply(
            "\u26a0\ufe0f Система обучения не инициализирована.",
            parse_mode=ParseMode.HTML,
        )
        return

    stats = await system.learning_engine.get_stats()
    rules = await system.learning_engine.get_learned_rules_display()

    text = (
        "\U0001f9e0 <b>TxPeek — Мозг Офицера</b>\n\n"
        f"<b>Поколение:</b> #{stats['generation']}\n"
        f"<b>Точность:</b> {stats['accuracy']}\n"
        f"<b>Всего фидбеков:</b> {stats['total_feedback']}\n"
        f"<b>Из них верных:</b> {stats['correct_feedback']}\n"
        f"<b>Активных правил:</b> {stats['active_rules']}\n"
        f"<b>До следующей эволюции:</b> {stats['next_evolution_in']} кейсов\n"
    )

    if rules:
        text += "\n<b>Выученные правила:</b>\n"
        for i, rule in enumerate(rules[:10], 1):
            text += (
                f"\n{i}. {rule['rule']}\n"
                f"   <i>Уверенность: {rule['confidence']} | "
                f"Источник: {rule['source']}</i>\n"
            )
    else:
        text += (
            "\n<i>Правил пока нет. Оставляйте фидбек после проверок, "
            "и Офицер начнёт учиться!</i>"
        )

    text += (
        "\n\n<i>\U0001f4a1 Оставляйте фидбек кнопками под результатами "
        "проверок — это помогает Офицеру эволюционировать.</i>"
    )

    await message.reply(text, parse_mode=ParseMode.HTML)


@aml_check_router.callback_query(F.data.startswith("aml_screenshot_"))
async def callback_aml_screenshot(callback: CallbackQuery):
    """Send the screenshot from AML check."""
    await callback.answer()

    case_id = callback.data.replace("aml_screenshot_", "")
    verdict = _verdict_cache.get(case_id)

    if not verdict or not verdict.screenshot_path:
        await callback.message.answer(
            "\u26a0\ufe0f Screenshot not available.",
            parse_mode=ParseMode.HTML,
        )
        return

    from pathlib import Path
    from aiogram.types import FSInputFile

    if Path(verdict.screenshot_path).exists():
        photo = FSInputFile(verdict.screenshot_path)
        await callback.message.answer_photo(
            photo=photo,
            caption=f"\U0001f4f8 Solscan overview for <code>{verdict.address[:8]}...</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await callback.message.answer(
            "\u26a0\ufe0f Screenshot file no longer available.",
            parse_mode=ParseMode.HTML,
        )


# ============================================================
# Auto-detection hook for agent-based AML checks
# ============================================================

async def try_aml_check(bot: Bot, message: Message, address: str) -> bool:
    """Attempt an AML check if the agent system is available.

    This can be called from the main handlers when an address is detected.

    Args:
        bot: Bot instance
        message: Telegram message
        address: Detected address

    Returns:
        True if AML check was performed, False if agent system unavailable
    """
    system = get_agent_system()
    if not system or not system.is_ready:
        return False

    verdict = await system.press_office.handle_check_command(
        bot=bot,
        message=message,
        address=address,
    )

    if verdict:
        _cache_verdict(verdict)
        return True

    return False


def register_aml_check_handlers(dp):
    """Register AML check handlers with the dispatcher.

    Args:
        dp: aiogram Dispatcher instance
    """
    dp.include_router(aml_check_router)
