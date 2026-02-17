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
