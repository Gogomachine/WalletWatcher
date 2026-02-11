"""AML Shield Service - Claude AI integration for crypto security."""

import os
from typing import List, Dict, Optional
from anthropic import AsyncAnthropic

# ============================================================
# БАЗА ЗНАНИЙ (AML Crypto Энциклопедия)
# ============================================================
AML_ENCYCLOPEDIA = """
AML / CRYPTO — ЭНЦИКЛОПЕДИЯ КОМПЛАЙЕНСА. Версия 1.0 | Февраль 2026.

МЕТОДЫ АНОНИМИЗАЦИИ:
- Миксеры и тамблеры: объединяют средства множества пользователей, разрывая связь отправитель-получатель. $82млрд крипто-ML в 2025. Tornado Cash: 254тыс ETH ($605млн). YoMix: рост 5x.
- Chain Hopping: конвертация между блокчейнами через мосты, DEX, своп-сервисы. $743,8млн в мосты в 2023. 68% отмывания 2024.
- Peel-цепочки: серия переводов, где на каждом шаге малая сумма "отщепляется". Паттерн "хвост кометы". 100-1000+ шагов.

ДЕАНОНИМИЗАЦИЯ:
- Кластеризация адресов — основа блокчейн-аналитики. Эвристики Bitcoin (UTXO) и Ethereum (аккаунт).
- Дастинг-атаки: микросуммы для деанонимизации. ~71 000 кошельков атаковано.

ВЛОЖЕННЫЕ БИРЖИ:
- Торгуют через аккаунт на регулируемой бирже без KYC.
- Garantex → Grinex → MKAN Coin → Exved. "Эффект гидры" — закрытие порождает преемников.

КЛЮЧЕВЫЕ КЕЙСЫ:
- Ronin Bridge $625млн: Lazarus Group, социнженерия через LinkedIn, 6 дней без обнаружения.
- Nomad Bridge $190млн: "моб-атака", сотни копировали эксплойт.
- Lazarus Group: Tornado Cash → DeFi chain hopping → YoMix → THORChain + eXch.

КРАСНЫЕ ФЛАГИ:
- Транзакционные: необычные суммы, связь с миксерами, множественные мелкие переводы (peel), взаимодействие с санкционными адресами.
- Адресные: новый адрес с крупной суммой, связь с darknet/gambling, паттерн "промежуточного" кошелька.

МЕТОДЫ ОБФУСКАЦИИ (многослойный стандарт):
peel chain → миксер → chain hop → DEX → no-KYC биржа → CEX. Lazarus: ВСЕ техники за 7 дней.

СТАТИСТИКА 2025: $82млрд крипто-ML (Chainalysis). Мосты — цель #1. 68% отмывания через chain hopping.
"""

# ============================================================
# SYSTEM PROMPT ДЛЯ AI АГЕНТА
# ============================================================
SYSTEM_PROMPT = f"""Ты — AML Shield, AI-помощник по крипто-безопасности, встроенный в бота TxPeek.

БАЗА ЗНАНИЙ:
{AML_ENCYCLOPEDIA}

ПРАВИЛА:
1. Отвечай ПРОСТЫМ языком. Без жаргона — если используешь термин, сразу объясни.
2. Используй аналогии из жизни: "Миксер — как если бы 100 человек сложили деньги в коробку и взяли чужие купюры"
3. Объясняй ПОЧЕМУ это важно лично для пользователя.
4. Используй эмодзи: 🔴 опасно, 🟡 внимание, 🟢 безопасно, 🛡️ совет.
5. Будь кратким — 2-3 абзаца. Это Telegram, не статья.
6. Ссылайся на реальные кейсы.
7. Отвечай на русском.
8. Если спрашивают про конкретный адрес — дай чеклист на что смотреть, объясни что проверка лучше через специализированные сервисы.
9. Давай практические советы.
10. НЕ пугай, а вооружай знаниями.

КОНТЕКСТ: Пользователь использует TxPeek для мониторинга Solana-кошельков. Он может спрашивать о безопасности адресов, P2P-сделках, грязной крипте и т.д."""


class AMLService:
    """AML Shield AI Service using Claude API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize AML Service.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
        """
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        self.client = AsyncAnthropic(api_key=self.api_key)

    async def ask(
        self,
        question: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Ask AML agent a question.

        Args:
            question: User's question
            conversation_history: Previous messages for context

        Returns:
            AI response string
        """
        try:
            messages = []
            if conversation_history:
                messages.extend([
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in conversation_history
                ])
            messages.append({"role": "user", "content": question})

            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=SYSTEM_PROMPT,
                messages=messages,
            )

            answer = "\n".join(
                block.text for block in response.content
                if block.type == "text"
            )
            return answer or "Произошла ошибка. Попробуй ещё раз."

        except Exception as e:
            print(f"AML Agent error: {e}")
            return "⚠️ Временные технические неполадки. Попробуй через минуту."

    @staticmethod
    def analyze_address_risk(tx_history: List[Dict]) -> Dict:
        """Analyze address risk based on transaction history.

        Args:
            tx_history: List of transaction records

        Returns:
            Risk analysis dict with score, level, emoji, factors, summary
        """
        risk_factors = []
        risk_score = 0

        # Check wallet age
        if tx_history:
            first_tx = tx_history[-1] if tx_history else None
            if first_tx and first_tx.get('blockTime'):
                import time
                age_ms = (time.time() - first_tx['blockTime']) * 1000
                age_days = age_ms / (1000 * 60 * 60 * 24)
                if age_days < 7:
                    risk_factors.append("🟡 Молодой адрес (< 7 дней)")
                    risk_score += 20

        # Check transaction count
        if len(tx_history) < 3:
            risk_factors.append("🟡 Мало транзакций — может быть промежуточный кошелёк")
            risk_score += 15

        # Check for peel-chain pattern
        outgoing = [tx for tx in tx_history if tx.get('type') == 'send']
        if len(outgoing) > 20:
            amounts = [tx.get('amount', 0) for tx in outgoing]
            if amounts:
                avg_amount = sum(amounts) / len(amounts)
                small_tx_ratio = len([a for a in amounts if a < avg_amount * 0.1]) / len(amounts)
                if small_tx_ratio > 0.5:
                    risk_factors.append("🔴 Паттерн peel-chain — множество мелких переводов")
                    risk_score += 40

        # Check for round amounts
        round_amounts = [
            tx for tx in tx_history
            if tx.get('amount', 0) >= 100 and tx.get('amount', 0) % 10 == 0
        ]
        if len(round_amounts) > len(tx_history) * 0.5 and len(tx_history) > 5:
            risk_factors.append("🟡 Много круглых сумм — нетипично для обычного трейдинга")
            risk_score += 15

        # Determine risk level
        if risk_score >= 50:
            risk_level = "ВЫСОКИЙ"
            risk_emoji = "🔴"
        elif risk_score >= 20:
            risk_level = "СРЕДНИЙ"
            risk_emoji = "🟡"
        else:
            risk_level = "НИЗКИЙ"
            risk_emoji = "🟢"

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "risk_emoji": risk_emoji,
            "risk_factors": risk_factors,
            "summary": "\n".join(risk_factors) if risk_factors else "🟢 Явных красных флагов не обнаружено",
        }

    @staticmethod
    def format_peek_with_aml(address: str, balance: float, tx_count: int) -> str:
        """Format peek message with AML tag.

        Args:
            address: Wallet address
            balance: Wallet balance
            tx_count: Transaction count

        Returns:
            Formatted message string
        """
        short_addr = f"{address[:4]}...{address[-4:]}"
        aml_tag = ""

        if tx_count < 3:
            aml_tag = "\n🛡️ _Мало транзакций — будь осторожен_"
        elif balance > 1000:
            aml_tag = "\n🛡️ _Крупный баланс — проверь историю перед сделкой_"

        return (
            f"🔍 Тебе выпал:\n\n"
            f"📍 `{short_addr}`\n"
            f"💰 Баланс: {balance:.6f} SOL\n"
            f"📊 Транзакций: {tx_count}"
            f"{aml_tag}"
        )
