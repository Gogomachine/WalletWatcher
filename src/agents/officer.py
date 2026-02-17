"""Chief Officer Agent - Central coordinator.

Role:
    Central coordinator. Manages agents, verifies results, makes final
    decisions on risk level.

Access:
    - Full access to all agents
    - Read/Write to Archivist (only one who initiates writes)
    - Right to reject, re-request, or modify results from any agent

Protocols:
    ON_RECEIVE_REQUEST_FROM_PRESS:
        1. Classify request (ADDRESS_CHECK, INFO_REQUEST, GENERAL_QUESTION, OUT_OF_SCOPE)
        2. Assign priority
        3. Distribute tasks with clear instructions

    ON_RECEIVE_RESULTS:
        1. Verify data completeness from each agent
        2. Cross-check consistency of Investigator and Verifier reports
        3. On discrepancies -> re-request with contradictions noted
        4. Form SINGLE VERDICT
        5. Decide on archiving
        6. Pass final answer to Press Office
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .base import (
    BaseAgent, AgentMessage, CaseContext, OfficerVerdict,
    RequestType, Priority, RiskLevel, NetworkType, CheckStatus,
    detect_network,
)

logger = logging.getLogger(__name__)


OFFICER_SYSTEM_PROMPT = """Ты — Главный Офицер (Chief Officer) системы TxPeek.
Твоя роль — центральный координатор AML-анализа криптовалютных адресов.

ЗАДАЧИ:
1. Анализировать отчёты Расследователя (on-chain данные) и Проверятора (compliance)
2. Сопоставлять данные, находить противоречия
3. Формировать ЕДИНЫЙ ВЕРДИКТ с обоснованием
4. При противоречиях — ВСЕГДА выбирать более осторожную оценку

УРОВНИ РИСКА:
🟢 CLEAN (0-15) — угрозы не обнаружены
🟡 LOW_RISK (16-35) — незначительные флаги
🟠 MEDIUM_RISK (36-60) — подозрительные связи
🔴 HIGH_RISK (61-85) — связи с санкциями/миксерами/скамами
⛔ CRITICAL (86-100) — адрес в санкционных списках

ПРАВИЛА:
- False positive лучше false negative
- Не давать финансовых рекомендаций
- Открыто признавать ограничения (open-source базы ≠ Chainalysis)
- Ответ на РУССКОМ языке
- Быть кратким: 2-4 предложения для обоснования
- Если данных мало — указать на неполноту анализа"""


class OfficerAgent(BaseAgent):
    """Chief Officer - central coordinator of the multi-agent system.

    Способен к автономному самообучению: после каждого вердикта рефлексирует,
    анализирует прошлые кейсы и эволюционирует через LearningEngine.
    Динамический промпт обогащается выученными правилами.
    """

    name = "Officer"
    system_prompt = OFFICER_SYSTEM_PROMPT

    def __init__(self, archivist=None, investigator=None, verifier=None,
                 api_key=None, learning_engine=None):
        """Initialize Officer with subordinate agents.

        Args:
            archivist: ArchivistAgent instance
            investigator: InvestigatorAgent instance
            verifier: VerifierAgent instance
            api_key: Anthropic API key
            learning_engine: LearningEngine instance for self-learning
        """
        super().__init__(api_key=api_key)
        self.archivist = archivist
        self.investigator = investigator
        self.verifier = verifier
        self.learning_engine = learning_engine

    async def handle_address_check(self, user_id: int, address: str, network: str = None) -> OfficerVerdict:
        """Handle an address check request from Press Office.

        This is the main entry point for AML checks.

        Args:
            user_id: Telegram user ID
            address: Address to check
            network: Optional network hint

        Returns:
            OfficerVerdict with the final assessment
        """
        # Detect network
        if network:
            try:
                net = NetworkType(network)
            except ValueError:
                net = detect_network(address)
        else:
            net = detect_network(address)

        if net == NetworkType.UNKNOWN:
            return OfficerVerdict(
                address=address,
                network="unknown",
                risk_level=RiskLevel.CLEAN,
                risk_score=0,
                confidence=0,
                reason="Could not determine blockchain network for this address.",
                recommendation="Please specify the network or check the address format.",
            )

        # Create case context
        case = CaseContext(
            user_id=user_id,
            address=address,
            network=net,
            request_type=RequestType.ADDRESS_CHECK,
        )

        self.logger.info(
            f"Officer: initiating check for {address[:8]}... "
            f"on {net.value} (case {case.case_id})"
        )

        # Step 0: Consult memory — найти похожие кейсы из архива
        similar_cases = []
        if self.learning_engine:
            similar_cases = await self.learning_engine.find_similar_cases(
                address, net.value
            )

        # Step 1: Query Archivist for cached results
        cached = await self._query_archivist(case)
        if cached:
            self.logger.info(f"Officer: returning cached result for {address[:8]}...")
            return cached

        # Step 2: Run Investigator and Verifier (Investigator first, then Verifier with data)
        investigator_report = await self._run_investigator(case)
        verifier_report = await self._run_verifier(case, investigator_report)

        # Step 3: Synthesize verdict (uses Claude API + learned rules)
        verdict = await self._synthesize_verdict(
            case, investigator_report, verifier_report, similar_cases
        )

        # Step 4: Archive results
        await self._archive_results(case, verdict, investigator_report, verifier_report)

        # Step 5: Self-reflection — рефлексия над решением
        if self.learning_engine:
            reflection = await self.learning_engine.self_reflect(
                case_id=case.case_id,
                address=case.address,
                network=case.network.value,
                risk_score=verdict.risk_score,
                risk_level=verdict.risk_level.label,
                reason=verdict.reason,
                investigator_data=investigator_report,
                verifier_data=verifier_report,
            )
            if reflection:
                verdict.self_reflection = reflection

        return verdict

    async def _query_archivist(self, case: CaseContext) -> Optional[OfficerVerdict]:
        """Query Archivist for existing fresh records."""
        if not self.archivist:
            return None

        try:
            query_msg = AgentMessage(
                sender="Officer",
                recipient="Archivist",
                case_id=case.case_id,
                content={"address": case.address, "max_age_hours": 24},
                msg_type="query",
            )

            response = await self.archivist.process(query_msg)
            content = response.content

            if content.get("has_fresh_data"):
                fresh = content["fresh_records"]
                if fresh:
                    latest = fresh[0]
                    try:
                        risk_level = RiskLevel[latest["risk_level"]]
                    except (KeyError, ValueError):
                        risk_level = RiskLevel.CLEAN

                    return OfficerVerdict(
                        case_id=latest.get("case_id", case.case_id),
                        address=case.address,
                        network=case.network.value,
                        risk_level=risk_level,
                        risk_score=latest.get("risk_score", 0),
                        confidence=latest.get("confidence", 0),
                        reason=latest.get("verdict_reason", "Cached result"),
                        recommendation=latest.get("recommendation", ""),
                        investigator_report=latest.get("investigator_data"),
                        verifier_report=latest.get("verifier_data"),
                    )

        except Exception as e:
            self.logger.warning(f"Archivist query failed: {e}")

        return None

    async def _run_investigator(self, case: CaseContext) -> Optional[dict]:
        """Run the Investigator agent."""
        if not self.investigator:
            self.logger.warning("No Investigator agent available")
            return None

        try:
            task_msg = AgentMessage(
                sender="Officer",
                recipient="Investigator",
                case_id=case.case_id,
                content={
                    "address": case.address,
                    "network": case.network.value,
                },
                msg_type="task",
            )

            response = await self.investigator.process(task_msg)

            if response.msg_type == "error":
                self.logger.warning(
                    f"Investigator error: {response.content.get('error', 'unknown')}"
                )
                return None

            return response.content

        except Exception as e:
            self.logger.error(f"Investigator failed: {e}")
            return None

    async def _run_verifier(self, case: CaseContext, investigator_data: Optional[dict]) -> Optional[dict]:
        """Run the Verifier agent with Investigator data for cross-analysis."""
        if not self.verifier:
            self.logger.warning("No Verifier agent available")
            return None

        try:
            task_msg = AgentMessage(
                sender="Officer",
                recipient="Verifier",
                case_id=case.case_id,
                content={
                    "address": case.address,
                    "network": case.network.value,
                    "investigator_data": investigator_data,
                },
                msg_type="task",
            )

            response = await self.verifier.process(task_msg)

            if response.msg_type == "error":
                self.logger.warning(
                    f"Verifier error: {response.content.get('error', 'unknown')}"
                )
                return None

            return response.content

        except Exception as e:
            self.logger.error(f"Verifier failed: {e}")
            return None

    def _get_effective_system_prompt(self) -> str:
        """Получить эффективный системный промпт с выученными правилами."""
        base = self.system_prompt
        if self.learning_engine:
            supplement = self.learning_engine.get_evolved_prompt_supplement()
            if supplement:
                return base + supplement
        return base

    async def _synthesize_verdict(
        self,
        case: CaseContext,
        investigator_report: Optional[dict],
        verifier_report: Optional[dict],
        similar_cases: Optional[list] = None,
    ) -> OfficerVerdict:
        """Synthesize final verdict from agent reports.

        When reports conflict, ALWAYS choose the more cautious assessment.
        Uses Claude API + learned rules for reasoning.
        """
        verdict = OfficerVerdict(
            case_id=case.case_id,
            address=case.address,
            network=case.network.value,
        )

        # Collect risk indicators
        inv_status = None
        ver_score = 0
        reasons = []

        if investigator_report:
            verdict.investigator_report = investigator_report
            verdict.screenshot_path = investigator_report.get("screenshot_path")

            inv_status_str = investigator_report.get("preliminary_status", "clean")
            try:
                inv_status = CheckStatus(inv_status_str)
            except ValueError:
                inv_status = CheckStatus.CLEAN

            if inv_status == CheckStatus.CRITICAL:
                reasons.append("Investigator: CRITICAL findings")
            elif inv_status == CheckStatus.FLAGGED:
                reasons.append("Investigator: flagged indicators")
            elif inv_status == CheckStatus.SUSPICIOUS:
                reasons.append("Investigator: suspicious patterns detected")

            patterns = investigator_report.get("detected_patterns", [])
            if patterns:
                reasons.extend(patterns[:3])

            mixers = investigator_report.get("mixer_interactions", [])
            if mixers:
                reasons.append(
                    f"Mixer interactions: {', '.join(m.get('name', '') for m in mixers)}"
                )

        if verifier_report:
            verdict.verifier_report = verifier_report
            ver_score = verifier_report.get("risk_score", 0)

            if verifier_report.get("ofac_sdn") == "flagged":
                reasons.append("OFAC SDN list match")
            if verifier_report.get("usdt_frozen") == "flagged":
                reasons.append("USDT account frozen")
            if verifier_report.get("usdc_frozen") == "flagged":
                reasons.append("USDC account frozen")
            if verifier_report.get("chainabuse_reports", 0) > 0:
                reasons.append(
                    f"ChainAbuse: {verifier_report['chainabuse_reports']} reports"
                )
            if verifier_report.get("explorer_label_text"):
                reasons.append(
                    f"Explorer label: {verifier_report['explorer_label_text']}"
                )

        # Determine risk score
        final_score = ver_score
        if inv_status in (CheckStatus.CRITICAL, CheckStatus.FLAGGED) and ver_score < 50:
            final_score = max(final_score, 50)
        if inv_status == CheckStatus.SUSPICIOUS and ver_score < 20:
            final_score = max(final_score, 20)

        verdict.risk_score = max(0, min(100, final_score))
        verdict.risk_level = RiskLevel.from_score(verdict.risk_score)

        # Confidence
        data_points = 0
        if investigator_report:
            data_points += 1
            if investigator_report.get("total_transactions", 0) > 0:
                data_points += 1
            if investigator_report.get("screenshot_path"):
                data_points += 1
        if verifier_report:
            data_points += 1
            if verifier_report.get("ofac_sdn") != "n/a":
                data_points += 1
            if verifier_report.get("chainabuse_status") != "n/a":
                data_points += 1
        verdict.confidence = min(95, data_points * 15 + 10)

        # Use Claude API to generate human-readable verdict reasoning
        import json

        # Собрать контекст из памяти (похожие кейсы)
        memory_context = ""
        if similar_cases:
            memory_lines = []
            for sc in similar_cases[:3]:
                if sc.get("type") == "past_reflection":
                    memory_lines.append(
                        f"- Прошлая проверка: score={sc.get('prev_score')}, "
                        f"уровень={sc.get('prev_level')}, "
                        f"рефлексия: {sc.get('reflection', '')[:150]}"
                    )
                else:
                    memory_lines.append(
                        f"- Прошлый вердикт: score={sc.get('prev_score')}, "
                        f"уровень={sc.get('prev_level')}, "
                        f"причина: {sc.get('prev_reason', '')[:150]}"
                    )
            memory_context = (
                "\n\nПАМЯТЬ (предыдущие проверки этого адреса):\n"
                + "\n".join(memory_lines)
                + "\nУчти этот опыт при формировании вердикта."
            )

        llm_prompt = (
            f"Адрес: {case.address}\n"
            f"Сеть: {case.network.value}\n"
            f"Risk Score (рассчитанный): {verdict.risk_score}/100\n"
            f"Уровень: {verdict.risk_level.label}\n\n"
            f"Данные Расследователя:\n{json.dumps(investigator_report, ensure_ascii=False, default=str)[:2000] if investigator_report else 'нет данных'}\n\n"
            f"Данные Проверятора:\n{json.dumps(verifier_report, ensure_ascii=False, default=str)[:2000] if verifier_report else 'нет данных'}"
            f"{memory_context}\n\n"
            "Сформируй КРАТКИЙ вердикт (2-4 предложения):\n"
            "1. Обоснование уровня риска\n"
            "2. Ключевые факторы\n"
            "3. Рекомендация\n"
            "Формат: только текст, без заголовков и маркеров."
        )

        # Используем эволюционированный промпт
        effective_prompt = self._get_effective_system_prompt()
        llm_analysis = ""
        if self.llm:
            try:
                response = await self.llm.messages.create(
                    model=self.model,
                    max_tokens=400,
                    system=effective_prompt,
                    messages=[{"role": "user", "content": llm_prompt}],
                )
                llm_analysis = "\n".join(
                    b.text for b in response.content if b.type == "text"
                )
            except Exception as e:
                self.logger.warning(f"Officer LLM error: {e}")
                llm_analysis = ""

        if llm_analysis:
            # LLM обогащает вердикт человекочитаемым обоснованием
            verdict.reason = llm_analysis.strip()
        elif reasons:
            verdict.reason = "; ".join(reasons[:5])
        elif verdict.risk_level == RiskLevel.CLEAN:
            verdict.reason = "Угрозы не обнаружены в санкционных списках, блэклистах и транзакционных паттернах."
        else:
            verdict.reason = "Обнаружены потенциальные индикаторы риска."

        # Generate recommendation (fallback if LLM didn't include it)
        if verdict.risk_level == RiskLevel.CLEAN:
            verdict.recommendation = "Низкий риск. Проблем не обнаружено."
        elif verdict.risk_level == RiskLevel.LOW_RISK:
            verdict.recommendation = "Незначительные флаги. Рекомендован мониторинг."
        elif verdict.risk_level == RiskLevel.MEDIUM_RISK:
            verdict.recommendation = "Подозрительные связи. Требуется осторожность."
        elif verdict.risk_level == RiskLevel.HIGH_RISK:
            verdict.recommendation = "Высокий риск. Избегать взаимодействия с этим адресом."
        else:
            verdict.recommendation = "КРИТИЧЕСКИЙ РИСК. НЕ взаимодействовать с этим адресом."

        verdict.should_archive = True

        self.logger.info(
            f"Officer: verdict for {case.address[:8]}... = "
            f"{verdict.risk_level.emoji} {verdict.risk_level.label} "
            f"(score: {verdict.risk_score}, confidence: {verdict.confidence}%)"
        )

        return verdict

    async def _archive_results(
        self,
        case: CaseContext,
        verdict: OfficerVerdict,
        investigator_report: Optional[dict],
        verifier_report: Optional[dict],
    ):
        """Archive the results via Archivist."""
        if not self.archivist or not verdict.should_archive:
            return

        try:
            write_msg = AgentMessage(
                sender="Officer",
                recipient="Archivist",
                case_id=case.case_id,
                content={
                    "case_id": case.case_id,
                    "user_id": case.user_id,
                    "address": case.address,
                    "network": case.network.value,
                    "risk_level": verdict.risk_level.label,
                    "risk_score": verdict.risk_score,
                    "confidence": verdict.confidence,
                    "verdict_reason": verdict.reason,
                    "recommendation": verdict.recommendation,
                    "investigator_data": investigator_report,
                    "verifier_data": verifier_report,
                    "linked_addresses": [],
                },
                msg_type="write_order",
            )

            response = await self.archivist.process(write_msg)
            if response.content.get("status") == "RECORDED":
                self.logger.info(f"Officer: case {case.case_id} archived successfully")
            else:
                self.logger.warning(
                    f"Officer: archive failed: {response.content}"
                )

        except Exception as e:
            self.logger.error(f"Officer: archive error: {e}")

    async def handle_info_request(self, question: str) -> str:
        """Handle a general AML information request using Claude API.

        Args:
            question: User's question about AML

        Returns:
            Answer string
        """
        # Try LLM first for intelligent response
        llm_answer = await self.think(
            f"Пользователь спрашивает: {question}\n\n"
            "Ответь кратко (2-3 абзаца) как AML-эксперт. "
            "Отвечай на русском. Используй эмодзи умеренно.",
            max_tokens=500,
        )

        if llm_answer:
            return llm_answer

        # Fallback: hardcoded responses
        lower = question.lower()
        if any(kw in lower for kw in ["risk", "уровн", "скор"]):
            return (
                "TxPeek использует систему скоринга рисков:\n\n"
                "\U0001f7e2 CLEAN (0-15) — угрозы не обнаружены\n"
                "\U0001f7e1 LOW RISK (16-35) — незначительные флаги\n"
                "\U0001f7e0 MEDIUM RISK (36-60) — подозрительные связи\n"
                "\U0001f534 HIGH RISK (61-85) — связи с санкциями/миксерами\n"
                "\u26d4 CRITICAL (86-100) — адрес в санкционных списках\n\n"
                "Скор рассчитывается на основе санкционных списков, блэклистов, "
                "паттернов транзакций и анализа контрагентов."
            )

        return (
            "TxPeek проверяет адреса по открытым санкционным базам, "
            "блэклистам и анализирует транзакционные паттерны. "
            "Отправь мне любой криптоадрес для полной AML-проверки."
        )
