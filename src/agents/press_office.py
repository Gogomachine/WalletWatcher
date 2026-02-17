"""Press Office Agent - Telegram user interface.

Role:
    The ONLY interface between the bot and the user in Telegram.
    Receives messages, formats responses, manages UX.
    Has no access to internal data - works only with what Officer provides.

Access:
    - Telegram: send/receive messages
    - Officer: bidirectional communication
    - No access to Archivist, Investigator, Verifier

Security:
    - Never reveal internal architecture (agents, structure)
    - Never pass raw internal data
    - Never promise 100% accuracy
    - Never give financial recommendations
    - Never help bypass AML controls
"""

import logging
import re
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
)
from aiogram.enums import ParseMode, ChatAction

from .base import (
    BaseAgent, OfficerVerdict, RiskLevel, NetworkType, detect_network,
)

logger = logging.getLogger(__name__)

# Address regex patterns
SOLANA_ADDRESS_REGEX = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
EVM_ADDRESS_REGEX = re.compile(r'\b0x[a-fA-F0-9]{40}\b')
BITCOIN_ADDRESS_REGEX = re.compile(r'\b(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}\b')
TRON_ADDRESS_REGEX = re.compile(r'\bT[a-zA-Z0-9]{33}\b')


PRESS_OFFICE_SYSTEM_PROMPT = """Ты — Пресс-секретарь (Press Office) системы TxPeek.
Твоя роль — единственный интерфейс между системой и пользователем в Telegram.

ЗАДАЧИ:
1. Форматировать результаты AML-проверок для пользователя
2. Отвечать на общие вопросы об AML и криптобезопасности
3. Объяснять результаты простым языком

ПРАВИЛА:
- НИКОГДА не раскрывать внутреннюю архитектуру (агенты, структуру)
- НИКОГДА не передавать сырые внутренние данные
- НИКОГДА не обещать 100% точность
- НИКОГДА не давать финансовых рекомендаций
- НИКОГДА не помогать обойти AML-контроль
- Ответ на РУССКОМ
- Быть дружелюбным, но профессиональным
- Использовать эмодзи умеренно"""


class PressOfficeAgent(BaseAgent):
    """Press Office - Telegram interface agent."""

    name = "PressOffice"
    system_prompt = PRESS_OFFICE_SYSTEM_PROMPT

    def __init__(self, officer=None, api_key=None):
        """Initialize Press Office.

        Args:
            officer: OfficerAgent instance
            api_key: Anthropic API key
        """
        super().__init__(api_key=api_key)
        self.officer = officer

    def extract_address(self, text: str) -> Optional[tuple[str, str]]:
        """Extract a crypto address from text.

        Args:
            text: Message text

        Returns:
            Tuple of (address, network) or None if no address found
        """
        text = text.strip()

        # Remove /check command prefix if present
        if text.startswith("/check"):
            text = text[6:].strip()

        # Try EVM first (most specific pattern)
        match = EVM_ADDRESS_REGEX.search(text)
        if match:
            return (match.group(0), "ethereum")

        # Bitcoin
        match = BITCOIN_ADDRESS_REGEX.search(text)
        if match:
            return (match.group(0), "bitcoin")

        # Tron
        match = TRON_ADDRESS_REGEX.search(text)
        if match:
            return (match.group(0), "tron")

        # Solana (broadest pattern, check last)
        match = SOLANA_ADDRESS_REGEX.search(text)
        if match:
            return (match.group(0), "solana")

        return None

    async def handle_check_command(
        self,
        bot: Bot,
        message: Message,
        address: str = None,
        network: str = None,
    ) -> Optional[OfficerVerdict]:
        """Handle address check request from user.

        Full flow:
            1. Validate and extract address
            2. Send "analyzing" status
            3. Forward to Officer
            4. Format and send result

        Args:
            bot: Telegram Bot instance
            message: Incoming Telegram message
            address: Pre-extracted address (optional)
            network: Pre-detected network (optional)

        Returns:
            OfficerVerdict or None
        """
        user_id = message.from_user.id
        chat_id = message.chat.id

        # Extract address if not provided
        if not address:
            extracted = self.extract_address(message.text or "")
            if not extracted:
                await bot.send_message(
                    chat_id,
                    "\u26a0\ufe0f <b>Address not recognized</b>\n\n"
                    "Please send a valid crypto address or use:\n"
                    "<code>/check &lt;address&gt;</code>\n\n"
                    "Supported networks: Solana, Ethereum, BSC, Polygon",
                    parse_mode=ParseMode.HTML,
                )
                return None
            address, network = extracted

        # Detect network from address if not provided
        if not network:
            net = detect_network(address)
            network = net.value

        # Send status message
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        status_msg = await bot.send_message(
            chat_id,
            "\U0001f50d <b>TxPeek \u2014 AML Analysis</b>\n\n"
            f"\U0001f4cb Address: <code>{address[:8]}...{address[-6:]}</code>\n"
            f"\U0001f310 Network: {network.capitalize()}\n\n"
            "\u23f3 Checking sanctions databases...",
            parse_mode=ParseMode.HTML,
        )

        # Update status
        try:
            await bot.edit_message_text(
                "\U0001f50d <b>TxPeek \u2014 AML Analysis</b>\n\n"
                f"\U0001f4cb Address: <code>{address[:8]}...{address[-6:]}</code>\n"
                f"\U0001f310 Network: {network.capitalize()}\n\n"
                "\U0001f4ca Collecting transaction data...",
                chat_id=chat_id,
                message_id=status_msg.message_id,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        # Forward to Officer
        if not self.officer:
            await bot.edit_message_text(
                "\u26a0\ufe0f Analysis service temporarily unavailable. Please try again later.",
                chat_id=chat_id,
                message_id=status_msg.message_id,
            )
            return None

        verdict = await self.officer.handle_address_check(user_id, address, network)

        # Delete status message
        try:
            await bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass

        # Format and send result
        await self._send_verdict(bot, chat_id, verdict)

        return verdict

    async def _send_verdict(self, bot: Bot, chat_id: int, verdict: OfficerVerdict):
        """Format and send verdict to Telegram user."""
        # Short address
        addr = verdict.address
        short_addr = f"{addr[:6]}...{addr[-6:]}" if len(addr) > 16 else addr

        # Risk emoji and label
        risk = verdict.risk_level
        network_display = verdict.network.capitalize() if verdict.network else "Unknown"

        # Build the main message
        if risk in (RiskLevel.HIGH_RISK, RiskLevel.CRITICAL):
            header = "\U0001f6a8 <b>TxPeek \u2014 WARNING</b>"
        else:
            header = "\U0001f50d <b>TxPeek \u2014 Check Result</b>"

        # Main text
        text = (
            f"{header}\n\n"
            f"<b>Address:</b> <code>{short_addr}</code>\n"
            f"<b>Network:</b> {network_display}\n"
            f"<b>Status:</b> {risk.emoji} {risk.label}\n"
            f"<b>Score:</b> {verdict.risk_score}/100\n"
            f"<b>Confidence:</b> {verdict.confidence}%\n"
        )

        # Add reason
        if verdict.reason:
            text += f"\n{verdict.reason}\n"

        # Add recommendation
        if verdict.recommendation:
            rec_emoji = "\U0001f4a1"
            if risk in (RiskLevel.HIGH_RISK, RiskLevel.CRITICAL):
                rec_emoji = "\u26a0\ufe0f"
            text += f"\n{rec_emoji} <i>Recommendation: {verdict.recommendation}</i>\n"

        # Disclaimer
        text += (
            "\n<i>\u26a0\ufe0f Analysis is informational only and does not "
            "constitute financial advice. DYOR.</i>"
        )

        # Ensure we don't exceed Telegram's 4096 char limit
        if len(text) > 4000:
            text = text[:3997] + "..."

        # Inline keyboard
        buttons = []
        buttons.append([
            InlineKeyboardButton(
                text="\U0001f4cb Details",
                callback_data=f"aml_detail_{verdict.case_id}",
            ),
        ])
        if verdict.screenshot_path:
            buttons.append([
                InlineKeyboardButton(
                    text="\U0001f4f8 Screenshot",
                    callback_data=f"aml_screenshot_{verdict.case_id}",
                ),
            ])
        # Feedback buttons — для самообучения Офицера
        buttons.append([
            InlineKeyboardButton(
                text="\u2705 Верно",
                callback_data=f"fb_correct_{verdict.case_id}",
            ),
            InlineKeyboardButton(
                text="\u274c Неверно",
                callback_data=f"fb_incorrect_{verdict.case_id}",
            ),
        ])
        buttons.append([
            InlineKeyboardButton(
                text="\u2b06\ufe0f Завышено",
                callback_data=f"fb_too_high_{verdict.case_id}",
            ),
            InlineKeyboardButton(
                text="\u2b07\ufe0f Занижено",
                callback_data=f"fb_too_low_{verdict.case_id}",
            ),
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        # Send screenshot as photo if available, otherwise text
        screenshot_sent = False
        if verdict.screenshot_path and Path(verdict.screenshot_path).exists():
            try:
                photo = FSInputFile(verdict.screenshot_path)
                await bot.send_photo(
                    chat_id,
                    photo=photo,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                screenshot_sent = True
            except Exception as e:
                self.logger.warning(f"Failed to send screenshot: {e}")

        if not screenshot_sent:
            await bot.send_message(
                chat_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )

    async def send_detailed_report(
        self,
        bot: Bot,
        chat_id: int,
        verdict: OfficerVerdict,
    ):
        """Send a detailed breakdown report.

        Args:
            bot: Telegram Bot instance
            chat_id: Chat to send to
            verdict: The verdict to detail
        """
        parts = []

        parts.append(
            f"\U0001f4cb <b>Detailed Report</b>\n"
            f"Case: <code>{verdict.case_id}</code>\n"
            f"Address: <code>{verdict.address}</code>\n"
            f"Network: {verdict.network}\n"
            f"Risk: {verdict.risk_level.emoji} {verdict.risk_level.label} "
            f"({verdict.risk_score}/100)\n"
        )

        # Investigator data
        inv = verdict.investigator_report
        if inv:
            inv_text = "\n<b>\U0001f575\ufe0f Investigation Report:</b>\n"
            if inv.get("balance"):
                inv_text += f"  Balance: {inv['balance']:.4f} {inv.get('symbol', '')}\n"
            if inv.get("total_transactions"):
                inv_text += f"  Transactions: {inv['total_transactions']}\n"
            if inv.get("wallet_age_first_tx"):
                inv_text += f"  First TX: {inv['wallet_age_first_tx'][:10]}\n"

            # CEX
            cex = inv.get("cex_interactions", [])
            if cex:
                cex_names = ", ".join(c.get("name", "?") for c in cex)
                inv_text += f"  CEX: {cex_names}\n"

            # DEX
            dex = inv.get("dex_interactions", [])
            if dex:
                inv_text += f"  DEX: {', '.join(dex)}\n"

            # Mixers
            mixers = inv.get("mixer_interactions", [])
            if mixers:
                mixer_names = ", ".join(m.get("name", "?") for m in mixers)
                inv_text += f"  \U0001f6a8 Mixers: {mixer_names}\n"
            else:
                inv_text += "  Mixers: Not detected\n"

            # Patterns
            patterns = inv.get("detected_patterns", [])
            if patterns:
                inv_text += "  Patterns:\n"
                for p in patterns[:5]:
                    inv_text += f"    \u2022 {p}\n"

            parts.append(inv_text)

        # Verifier data
        ver = verdict.verifier_report
        if ver:
            ver_text = "\n<b>\u2705 Compliance Report:</b>\n"

            checks = {
                "OFAC SDN": ver.get("ofac_sdn", "n/a"),
                "ChainAbuse": ver.get("chainabuse_status", "n/a"),
                "USDT Frozen": ver.get("usdt_frozen", "n/a"),
                "USDC Frozen": ver.get("usdc_frozen", "n/a"),
                "Explorer Labels": ver.get("explorer_labels", "n/a"),
            }

            for check_name, status in checks.items():
                if status == "clean":
                    icon = "\u2705"
                elif status == "flagged":
                    icon = "\U0001f6ab"
                elif status == "suspicious":
                    icon = "\u26a0\ufe0f"
                else:
                    icon = "\u2796"
                ver_text += f"  {icon} {check_name}: {status}\n"

            if ver.get("chainabuse_reports", 0) > 0:
                ver_text += f"  ChainAbuse reports: {ver['chainabuse_reports']}\n"

            # Score factors
            factors = ver.get("score_factors", [])
            if factors:
                ver_text += "\n  Score breakdown:\n"
                for desc, pts in factors[:5]:
                    ver_text += f"    +{pts}: {desc}\n"

            mitigating = ver.get("mitigating_factors", [])
            if mitigating:
                for desc, pts in mitigating:
                    ver_text += f"    {pts}: {desc}\n"

            parts.append(ver_text)

        # Combine and send
        full_text = "\n".join(parts)

        full_text += (
            "\n\n<i>\u26a0\ufe0f Analysis is based on open-source data. "
            "Professional compliance services (Chainalysis, TRM Labs) "
            "may provide additional coverage.</i>"
        )

        # Split if too long
        if len(full_text) > 4096:
            chunks = self._split_message(full_text, 4000)
            for chunk in chunks:
                await bot.send_message(
                    chat_id,
                    chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        else:
            await bot.send_message(
                chat_id,
                full_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    def format_start_message(self, language: str = "ru") -> str:
        """Format /start welcome message."""
        if language == "en":
            return (
                "\U0001f50d <b>Welcome to TxPeek!</b>\n\n"
                "I check crypto addresses for AML risks using open databases, "
                "sanctions lists, and transaction analysis.\n\n"
                "<b>How to use:</b>\n"
                "\u2022 Send any crypto address directly\n"
                "\u2022 Use <code>/check &lt;address&gt;</code>\n"
                "\u2022 Use /help for all commands\n\n"
                "<b>Supported:</b> Solana, Ethereum, BSC, Polygon\n\n"
                "<i>\u26a0\ufe0f Results are informational. Not financial advice.</i>"
            )

        return (
            "\U0001f50d <b>TxPeek \u2014 AML-\u0430\u043d\u0430\u043b\u0438\u0437 "
            "\u043a\u0440\u0438\u043f\u0442\u043e\u0430\u0434\u0440\u0435\u0441\u043e\u0432</b>\n\n"
            "\u041f\u0440\u043e\u0432\u0435\u0440\u044f\u044e \u0430\u0434\u0440\u0435\u0441\u0430 "
            "\u043f\u043e \u0441\u0430\u043d\u043a\u0446\u0438\u043e\u043d\u043d\u044b\u043c "
            "\u0441\u043f\u0438\u0441\u043a\u0430\u043c, \u0431\u043b\u044d\u043a\u043b\u0438"
            "\u0441\u0442\u0430\u043c \u0438 \u0430\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u044e "
            "\u0442\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u043e\u043d\u043d\u044b\u0435 "
            "\u043f\u0430\u0442\u0442\u0435\u0440\u043d\u044b.\n\n"
            "<b>\u041a\u0430\u043a \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c:</b>\n"
            "\u2022 \u041e\u0442\u043f\u0440\u0430\u0432\u044c \u043b\u044e\u0431\u043e\u0439 "
            "\u043a\u0440\u0438\u043f\u0442\u043e\u0430\u0434\u0440\u0435\u0441 \u043d\u0430\u043f\u0440"
            "\u044f\u043c\u0443\u044e\n"
            "\u2022 \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 <code>/check "
            "&lt;\u0430\u0434\u0440\u0435\u0441&gt;</code>\n"
            "\u2022 /help \u2014 \u0441\u043f\u0440\u0430\u0432\u043a\u0430 \u043f\u043e "
            "\u043a\u043e\u043c\u0430\u043d\u0434\u0430\u043c\n\n"
            "<b>\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u043c\u044b\u0435 "
            "\u0441\u0435\u0442\u0438:</b> Solana, Ethereum, BSC, Polygon\n\n"
            "<i>\u26a0\ufe0f \u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u043d\u043e"
            "\u0441\u044f\u0442 \u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u043e\u043d"
            "\u043d\u044b\u0439 \u0445\u0430\u0440\u0430\u043a\u0442\u0435\u0440. DYOR.</i>"
        )

    def format_help_message(self, language: str = "ru") -> str:
        """Format /help message."""
        if language == "en":
            return (
                "\U0001f4d6 <b>TxPeek Commands</b>\n\n"
                "/check <code>&lt;address&gt;</code> \u2014 Check address for AML risks\n"
                "/risk \u2014 Risk levels explained\n"
                "/help \u2014 This message\n"
                "/about \u2014 About TxPeek\n\n"
                "<b>Tip:</b> You can also just send an address directly!"
            )

        return (
            "\U0001f4d6 <b>\u041a\u043e\u043c\u0430\u043d\u0434\u044b TxPeek</b>\n\n"
            "/check <code>&lt;\u0430\u0434\u0440\u0435\u0441&gt;</code> \u2014 "
            "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0430\u0434\u0440\u0435\u0441\n"
            "/risk \u2014 \u041e\u0431\u044a\u044f\u0441\u043d\u0435\u043d\u0438\u0435 "
            "\u0443\u0440\u043e\u0432\u043d\u0435\u0439 \u0440\u0438\u0441\u043a\u0430\n"
            "/help \u2014 \u042d\u0442\u043e \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435\n"
            "/about \u2014 \u041e TxPeek\n"
            "/aml \u2014 AML Shield \u2014 AI-\u043a\u043e\u043d\u0441\u0443\u043b\u044c\u0442\u0430\u043d\u0442\n\n"
            "<b>\u0421\u043e\u0432\u0435\u0442:</b> \u041c\u043e\u0436\u043d\u043e \u043f\u0440\u043e"
            "\u0441\u0442\u043e \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0430\u0434"
            "\u0440\u0435\u0441 \u0431\u0435\u0437 \u043a\u043e\u043c\u0430\u043d\u0434\u044b!"
        )

    def format_risk_explanation(self, language: str = "ru") -> str:
        """Format /risk explanation message."""
        if language == "en":
            return (
                "\U0001f4ca <b>TxPeek Risk Levels</b>\n\n"
                "\U0001f7e2 <b>CLEAN</b> (0-15)\n"
                "No threats found. Safe to interact.\n\n"
                "\U0001f7e1 <b>LOW RISK</b> (16-35)\n"
                "Minor flags detected. Monitoring recommended.\n\n"
                "\U0001f7e0 <b>MEDIUM RISK</b> (36-60)\n"
                "Suspicious connections found. Exercise caution.\n\n"
                "\U0001f534 <b>HIGH RISK</b> (61-85)\n"
                "Connections to sanctions, mixers, or scams. Avoid.\n\n"
                "\u26d4 <b>CRITICAL</b> (86-100)\n"
                "Direct sanctions match or criminal activity. Do NOT interact.\n\n"
                "<i>Score factors: OFAC SDN, ChainAbuse, stablecoin freezes, "
                "transaction patterns, counterparty analysis.</i>"
            )

        return (
            "\U0001f4ca <b>\u0423\u0440\u043e\u0432\u043d\u0438 \u0440\u0438\u0441\u043a\u0430 "
            "TxPeek</b>\n\n"
            "\U0001f7e2 <b>CLEAN</b> (0-15)\n"
            "\u0423\u0433\u0440\u043e\u0437 \u043d\u0435 \u043e\u0431\u043d\u0430\u0440\u0443"
            "\u0436\u0435\u043d\u043e.\n\n"
            "\U0001f7e1 <b>LOW RISK</b> (16-35)\n"
            "\u041d\u0435\u0437\u043d\u0430\u0447\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 "
            "\u0444\u043b\u0430\u0433\u0438. \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e"
            "\u0432\u0430\u043d \u043c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433.\n\n"
            "\U0001f7e0 <b>MEDIUM RISK</b> (36-60)\n"
            "\u041f\u043e\u0434\u043e\u0437\u0440\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 "
            "\u0441\u0432\u044f\u0437\u0438. \u0422\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f "
            "\u043e\u0441\u0442\u043e\u0440\u043e\u0436\u043d\u043e\u0441\u0442\u044c.\n\n"
            "\U0001f534 <b>HIGH RISK</b> (61-85)\n"
            "\u0421\u0432\u044f\u0437\u0438 \u0441 \u0441\u0430\u043d\u043a\u0446\u0438\u044f"
            "\u043c\u0438/\u043c\u0438\u043a\u0441\u0435\u0440\u0430\u043c\u0438/\u0441\u043a\u0430"
            "\u043c\u0430\u043c\u0438. \u0418\u0437\u0431\u0435\u0433\u0430\u0442\u044c.\n\n"
            "\u26d4 <b>CRITICAL</b> (86-100)\n"
            "\u0410\u0434\u0440\u0435\u0441 \u0432 \u0441\u0430\u043d\u043a\u0446\u0438\u043e\u043d"
            "\u043d\u044b\u0445 \u0441\u043f\u0438\u0441\u043a\u0430\u0445. \u041d\u0415 "
            "\u0432\u0437\u0430\u0438\u043c\u043e\u0434\u0435\u0439\u0441\u0442\u0432\u043e\u0432\u0430"
            "\u0442\u044c.\n\n"
            "<i>\u0424\u0430\u043a\u0442\u043e\u0440\u044b: OFAC SDN, ChainAbuse, "
            "\u0437\u0430\u043c\u043e\u0440\u043e\u0437\u043a\u0430 \u0441\u0442\u0435\u0439\u0431"
            "\u043b\u043a\u043e\u0438\u043d\u043e\u0432, \u043f\u0430\u0442\u0442\u0435\u0440\u043d\u044b "
            "\u0442\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0439, \u0430\u043d\u0430\u043b\u0438"
            "\u0437 \u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u043e\u0432.</i>"
        )

    def format_about_message(self, language: str = "ru") -> str:
        """Format /about message."""
        if language == "en":
            return (
                "\U0001f50d <b>About TxPeek</b>\n\n"
                "TxPeek checks crypto addresses for AML risks using:\n\n"
                "\u2022 OFAC SDN sanctions lists\n"
                "\u2022 ChainAbuse reports\n"
                "\u2022 Stablecoin freeze status (USDT/USDC)\n"
                "\u2022 Blockchain explorer labels\n"
                "\u2022 Transaction pattern analysis\n"
                "\u2022 Counterparty identification\n\n"
                "<b>Supported:</b> Solana (Phase 1), Ethereum/EVM (Phase 2)\n\n"
                "<i>Built with open-source data. Not a replacement for "
                "professional compliance tools.</i>"
            )

        return (
            "\U0001f50d <b>O TxPeek</b>\n\n"
            "TxPeek \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u0435\u0442 \u043a\u0440\u0438\u043f"
            "\u0442\u043e\u0430\u0434\u0440\u0435\u0441\u0430 \u043d\u0430 AML-\u0440\u0438\u0441"
            "\u043a\u0438 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044f:\n\n"
            "\u2022 \u0421\u0430\u043d\u043a\u0446\u0438\u043e\u043d\u043d\u044b\u0435 \u0441\u043f"
            "\u0438\u0441\u043a\u0438 OFAC SDN\n"
            "\u2022 \u041e\u0442\u0447\u0451\u0442\u044b ChainAbuse\n"
            "\u2022 \u0421\u0442\u0430\u0442\u0443\u0441 \u0437\u0430\u043c\u043e\u0440\u043e"
            "\u0437\u043a\u0438 \u0441\u0442\u0435\u0439\u0431\u043b\u043a\u043e\u0438\u043d"
            "\u043e\u0432 (USDT/USDC)\n"
            "\u2022 \u041b\u0435\u0439\u0431\u043b\u044b \u044d\u043a\u0441\u043f\u043b\u043e"
            "\u0440\u0435\u0440\u043e\u0432\n"
            "\u2022 \u0410\u043d\u0430\u043b\u0438\u0437 \u0442\u0440\u0430\u043d\u0437\u0430"
            "\u043a\u0446\u0438\u043e\u043d\u043d\u044b\u0445 \u043f\u0430\u0442\u0442\u0435"
            "\u0440\u043d\u043e\u0432\n"
            "\u2022 \u0418\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0446\u0438\u044f "
            "\u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u043e\u0432\n\n"
            "<b>\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430:</b> Solana (Phase 1), "
            "Ethereum/EVM (Phase 2)\n\n"
            "<i>\u041f\u043e\u0441\u0442\u0440\u043e\u0435\u043d \u043d\u0430 \u043e\u0442\u043a"
            "\u0440\u044b\u0442\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0445. \u041d\u0435 "
            "\u0437\u0430\u043c\u0435\u043d\u044f\u0435\u0442 \u043f\u0440\u043e\u0444\u0435\u0441"
            "\u0441\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u0435 compliance-\u0438\u043d"
            "\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u044b.</i>"
        )

    @staticmethod
    def _split_message(text: str, max_length: int = 4000) -> list:
        """Split a long message into chunks respecting HTML tags.

        Args:
            text: Full text to split
            max_length: Maximum length per chunk

        Returns:
            List of text chunks
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        current = ""

        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_length:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line

        if current:
            chunks.append(current)

        return chunks
