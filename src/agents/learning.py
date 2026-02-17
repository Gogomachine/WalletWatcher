"""Officer Learning Engine — самообучение и эволюция.

Система позволяет Офицеру:
1. Запоминать свои решения и рефлексировать над ними
2. Получать фидбек от пользователей (верно/неверно/завышено/занижено)
3. Периодически эволюционировать — синтезировать новые правила из опыта
4. Подстраивать динамический промпт на основе выученных паттернов
5. Калибровать уверенность на основе точности

Цикл обучения:
    VERDICT → SELF_REFLECTION → USER_FEEDBACK → ACCUMULATE →
    (every N cases) → EVOLUTION → UPDATED_RULES → better VERDICT
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Через сколько кейсов запускать цикл эволюции
EVOLUTION_THRESHOLD = 10

# Максимум выученных правил в динамическом промпте
MAX_LEARNED_RULES = 15


@dataclass
class FeedbackRecord:
    """Запись фидбека пользователя по вердикту."""
    case_id: str = ""
    user_id: int = 0
    address: str = ""
    network: str = ""
    # Вердикт Офицера
    officer_risk_score: int = 0
    officer_risk_level: str = ""
    officer_reason: str = ""
    # Фидбек пользователя: correct, incorrect, too_high, too_low
    feedback_type: str = ""
    feedback_comment: str = ""
    created_at: str = ""


@dataclass
class LearnedPattern:
    """Выученный паттерн/правило."""
    pattern_id: str = ""
    rule_text: str = ""          # Текст правила на русском
    source: str = ""             # "evolution" | "feedback" | "self_reflection"
    confidence: float = 0.5      # 0.0–1.0, растёт при подтверждении
    times_applied: int = 0       # Сколько раз правило было применено
    times_confirmed: int = 0     # Сколько раз подтверждено фидбеком
    created_at: str = ""
    last_used_at: str = ""
    active: bool = True


@dataclass
class EvolutionRecord:
    """Запись об эволюционном цикле."""
    evolution_id: str = ""
    generation: int = 0          # Номер поколения
    cases_analyzed: int = 0
    feedback_used: int = 0
    new_rules: list = field(default_factory=list)
    deprecated_rules: list = field(default_factory=list)
    accuracy_before: float = 0.0
    accuracy_after: float = 0.0
    evolution_summary: str = ""
    created_at: str = ""


class LearningEngine:
    """Движок самообучения Офицера.

    Хранит память, обрабатывает фидбек, запускает эволюцию,
    формирует динамический промпт.
    """

    def __init__(self, database=None, api_key: Optional[str] = None):
        self.database = database
        self._api_key = api_key
        self.logger = logging.getLogger("txpeek.learning")

        # In-memory кэш (подгружается из БД при initialize)
        self._learned_rules: list[LearnedPattern] = []
        self._generation: int = 0
        self._cases_since_evolution: int = 0
        self._total_cases: int = 0
        self._correct_count: int = 0
        self._total_feedback: int = 0

        # LLM клиент (lazy)
        self._client = None

    @property
    def llm(self):
        if self._client is None and self._api_key:
            import os
            from anthropic import AsyncAnthropic
            key = self._api_key or os.getenv("ANTHROPIC_API_KEY")
            if key:
                self._client = AsyncAnthropic(api_key=key)
        return self._client

    @property
    def accuracy(self) -> float:
        """Текущая точность (по фидбеку)."""
        if self._total_feedback == 0:
            return 0.0
        return self._correct_count / self._total_feedback

    @property
    def generation(self) -> int:
        return self._generation

    # ============================================================
    # Инициализация БД
    # ============================================================

    async def initialize(self):
        """Создать таблицы обучения и загрузить состояние из БД."""
        pool = getattr(self.database, 'pool', None)
        if pool is None:
            self.logger.warning("No pool — learning engine работает только in-memory")
            return

        async with pool.acquire() as conn:
            # Таблица фидбека
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS officer_feedback (
                    id SERIAL PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    user_id BIGINT NOT NULL,
                    address TEXT NOT NULL,
                    network TEXT DEFAULT '',
                    officer_risk_score INTEGER DEFAULT 0,
                    officer_risk_level TEXT DEFAULT '',
                    officer_reason TEXT DEFAULT '',
                    feedback_type TEXT NOT NULL,
                    feedback_comment TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица выученных правил
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS officer_learned_patterns (
                    id SERIAL PRIMARY KEY,
                    pattern_id TEXT UNIQUE NOT NULL,
                    rule_text TEXT NOT NULL,
                    source TEXT DEFAULT 'evolution',
                    confidence REAL DEFAULT 0.5,
                    times_applied INTEGER DEFAULT 0,
                    times_confirmed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active BOOLEAN DEFAULT TRUE
                )
            """)

            # Лог эволюции
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS officer_evolution_log (
                    id SERIAL PRIMARY KEY,
                    evolution_id TEXT UNIQUE NOT NULL,
                    generation INTEGER DEFAULT 0,
                    cases_analyzed INTEGER DEFAULT 0,
                    feedback_used INTEGER DEFAULT 0,
                    new_rules JSONB DEFAULT '[]',
                    deprecated_rules JSONB DEFAULT '[]',
                    accuracy_before REAL DEFAULT 0.0,
                    accuracy_after REAL DEFAULT 0.0,
                    evolution_summary TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Индексы
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_case ON officer_feedback(case_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_address ON officer_feedback(address)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_active ON officer_learned_patterns(active)
            """)

        # Загрузить состояние
        await self._load_state()
        self.logger.info(
            f"LearningEngine initialized: generation={self._generation}, "
            f"rules={len(self._learned_rules)}, accuracy={self.accuracy:.1%}"
        )

    async def _load_state(self):
        """Загрузить выученные правила и статистику из БД."""
        pool = getattr(self.database, 'pool', None)
        if pool is None:
            return

        async with pool.acquire() as conn:
            # Загрузить активные правила
            rows = await conn.fetch("""
                SELECT pattern_id, rule_text, source, confidence,
                       times_applied, times_confirmed, created_at,
                       last_used_at, active
                FROM officer_learned_patterns
                WHERE active = TRUE
                ORDER BY confidence DESC
                LIMIT $1
            """, MAX_LEARNED_RULES)

            self._learned_rules = []
            for row in rows:
                self._learned_rules.append(LearnedPattern(
                    pattern_id=row["pattern_id"],
                    rule_text=row["rule_text"],
                    source=row["source"],
                    confidence=row["confidence"],
                    times_applied=row["times_applied"],
                    times_confirmed=row["times_confirmed"],
                    created_at=str(row["created_at"]),
                    last_used_at=str(row["last_used_at"]),
                    active=row["active"],
                ))

            # Загрузить поколение
            gen_row = await conn.fetchrow("""
                SELECT COALESCE(MAX(generation), 0) AS gen FROM officer_evolution_log
            """)
            self._generation = gen_row["gen"] if gen_row else 0

            # Статистика фидбека
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE feedback_type = 'correct') AS correct
                FROM officer_feedback
            """)
            if stats:
                self._total_feedback = stats["total"]
                self._correct_count = stats["correct"]

            # Кейсы с последней эволюции
            last_evo = await conn.fetchrow("""
                SELECT created_at FROM officer_evolution_log
                ORDER BY created_at DESC LIMIT 1
            """)
            if last_evo:
                cases_since = await conn.fetchval("""
                    SELECT COUNT(*) FROM aml_archive
                    WHERE created_at > $1
                """, last_evo["created_at"])
                self._cases_since_evolution = cases_since or 0
            else:
                total_cases = await conn.fetchval(
                    "SELECT COUNT(*) FROM aml_archive"
                )
                self._cases_since_evolution = total_cases or 0

    # ============================================================
    # Динамический промпт
    # ============================================================

    def get_evolved_prompt_supplement(self) -> str:
        """Сформировать дополнение к системному промпту из выученных правил.

        Возвращает блок текста, который добавляется к базовому system prompt Офицера.
        """
        if not self._learned_rules:
            return ""

        active_rules = [r for r in self._learned_rules if r.active and r.confidence >= 0.3]
        if not active_rules:
            return ""

        # Сортируем по уверенности
        active_rules.sort(key=lambda r: r.confidence, reverse=True)

        rules_text = "\n".join(
            f"  {i+1}. {r.rule_text} (уверенность: {r.confidence:.0%})"
            for i, r in enumerate(active_rules[:MAX_LEARNED_RULES])
        )

        return (
            f"\n\nВЫУЧЕННЫЕ ПРАВИЛА (поколение #{self._generation}, "
            f"точность: {self.accuracy:.0%}):\n"
            f"{rules_text}\n\n"
            "Применяй эти правила наряду с базовыми. "
            "Если правило противоречит фактам — игнорируй его."
        )

    # ============================================================
    # Саморефлексия (после каждого вердикта)
    # ============================================================

    async def self_reflect(
        self,
        case_id: str,
        address: str,
        risk_score: int,
        risk_level: str,
        reason: str,
        investigator_data: Optional[dict],
        verifier_data: Optional[dict],
    ) -> Optional[str]:
        """Офицер рефлексирует над своим решением.

        Вызывается ПОСЛЕ вынесения вердикта. LLM анализирует:
        - Были ли слабые места в анализе?
        - Что можно улучшить?
        - Какие новые паттерны замечены?

        Returns:
            Текст рефлексии или None
        """
        if not self.llm:
            return None

        inv_summary = json.dumps(investigator_data, ensure_ascii=False, default=str)[:1500] if investigator_data else "нет"
        ver_summary = json.dumps(verifier_data, ensure_ascii=False, default=str)[:1500] if verifier_data else "нет"

        prompt = (
            f"Ты только что вынес вердикт по адресу {address[:12]}...\n"
            f"Risk Score: {risk_score}/100, Уровень: {risk_level}\n"
            f"Обоснование: {reason}\n\n"
            f"Данные расследователя: {inv_summary}\n"
            f"Данные проверятора: {ver_summary}\n\n"
            "САМОРЕФЛЕКСИЯ — ответь кратко (2-3 предложения):\n"
            "1. Насколько ты уверен в вердикте? Какие слабые места?\n"
            "2. Есть ли паттерн, который стоит запомнить на будущее?\n"
            "3. Если бы у тебя было больше данных, что бы ты проверил?\n"
            "Формат: только текст, без заголовков."
        )

        try:
            from anthropic import AsyncAnthropic
            response = await self.llm.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=(
                    "Ты — система саморефлексии AML-аналитика. "
                    "Критически оценивай собственные решения. "
                    "Будь честен о слабых местах. Отвечай на русском."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            reflection = "\n".join(
                b.text for b in response.content if b.type == "text"
            )
            self.logger.info(f"Self-reflection for {case_id}: {reflection[:100]}...")
            return reflection.strip()
        except Exception as e:
            self.logger.warning(f"Self-reflection failed: {e}")
            return None

    # ============================================================
    # Обработка фидбека
    # ============================================================

    async def record_feedback(
        self,
        case_id: str,
        user_id: int,
        address: str,
        network: str,
        risk_score: int,
        risk_level: str,
        reason: str,
        feedback_type: str,
        feedback_comment: str = "",
    ):
        """Записать фидбек пользователя и обновить статистику.

        Args:
            feedback_type: 'correct' | 'incorrect' | 'too_high' | 'too_low'
        """
        pool = getattr(self.database, 'pool', None)
        if pool is None:
            self.logger.warning("No pool — feedback не сохранён")
            return

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO officer_feedback (
                    case_id, user_id, address, network,
                    officer_risk_score, officer_risk_level, officer_reason,
                    feedback_type, feedback_comment
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
                case_id, user_id, address, network,
                risk_score, risk_level, reason,
                feedback_type, feedback_comment,
            )

        # Обновить in-memory статистику
        self._total_feedback += 1
        if feedback_type == "correct":
            self._correct_count += 1

        self._cases_since_evolution += 1

        self.logger.info(
            f"Feedback recorded: {case_id} = {feedback_type} "
            f"(accuracy now: {self.accuracy:.1%})"
        )

        # Проверить, нужна ли эволюция
        if self._cases_since_evolution >= EVOLUTION_THRESHOLD:
            await self.evolve()

    # ============================================================
    # Поиск похожих кейсов
    # ============================================================

    async def find_similar_cases(self, address: str, network: str) -> list[dict]:
        """Найти похожие кейсы с фидбеком для обогащения анализа.

        Ищет:
        1. Тот же адрес (повторная проверка)
        2. Тот же тип сети с похожим фидбеком

        Returns:
            Список релевантных записей
        """
        pool = getattr(self.database, 'pool', None)
        if pool is None:
            return []

        results = []
        async with pool.acquire() as conn:
            # Тот же адрес
            rows = await conn.fetch("""
                SELECT f.case_id, f.feedback_type, f.feedback_comment,
                       f.officer_risk_score, f.officer_risk_level,
                       f.created_at
                FROM officer_feedback f
                WHERE f.address = $1
                ORDER BY f.created_at DESC
                LIMIT 5
            """, address)

            for row in rows:
                results.append({
                    "case_id": row["case_id"],
                    "type": "same_address",
                    "feedback": row["feedback_type"],
                    "comment": row["feedback_comment"],
                    "prev_score": row["officer_risk_score"],
                    "prev_level": row["officer_risk_level"],
                })

        return results

    # ============================================================
    # Эволюция
    # ============================================================

    async def evolve(self):
        """Запустить цикл эволюции.

        LLM анализирует накопленный фидбек и синтезирует новые правила.
        Старые неэффективные правила деактивируются.
        """
        pool = getattr(self.database, 'pool', None)
        if pool is None or not self.llm:
            self.logger.info("Evolution skipped: no pool or no LLM")
            return

        self.logger.info(
            f"Starting evolution cycle (gen {self._generation} → {self._generation + 1})"
        )

        accuracy_before = self.accuracy

        # Собрать фидбек с последней эволюции
        async with pool.acquire() as conn:
            # Последняя эволюция
            last_evo = await conn.fetchrow("""
                SELECT created_at FROM officer_evolution_log
                ORDER BY created_at DESC LIMIT 1
            """)

            if last_evo:
                feedback_rows = await conn.fetch("""
                    SELECT case_id, address, network,
                           officer_risk_score, officer_risk_level, officer_reason,
                           feedback_type, feedback_comment
                    FROM officer_feedback
                    WHERE created_at > $1
                    ORDER BY created_at DESC
                    LIMIT 50
                """, last_evo["created_at"])
            else:
                feedback_rows = await conn.fetch("""
                    SELECT case_id, address, network,
                           officer_risk_score, officer_risk_level, officer_reason,
                           feedback_type, feedback_comment
                    FROM officer_feedback
                    ORDER BY created_at DESC
                    LIMIT 50
                """)

        if not feedback_rows:
            self.logger.info("Evolution skipped: no new feedback")
            return

        # Подготовить данные для LLM
        feedback_data = []
        for row in feedback_rows:
            feedback_data.append({
                "address": row["address"][:12] + "...",
                "network": row["network"],
                "score": row["officer_risk_score"],
                "level": row["officer_risk_level"],
                "reason": row["officer_reason"][:200],
                "feedback": row["feedback_type"],
                "comment": row["feedback_comment"],
            })

        current_rules = [
            {"rule": r.rule_text, "confidence": r.confidence, "applied": r.times_applied}
            for r in self._learned_rules if r.active
        ]

        evolution_prompt = (
            f"Ты — система эволюции AML-аналитика TxPeek. Поколение: #{self._generation}\n"
            f"Текущая точность: {accuracy_before:.1%}\n\n"
            f"ТЕКУЩИЕ ПРАВИЛА:\n{json.dumps(current_rules, ensure_ascii=False)}\n\n"
            f"ФИДБЕК ПО ПОСЛЕДНИМ КЕЙСАМ:\n{json.dumps(feedback_data, ensure_ascii=False)}\n\n"
            "ЗАДАЧА — на основе фидбека:\n"
            "1. Какие НОВЫЕ правила стоит добавить? (макс 3)\n"
            "2. Какие текущие правила УСТАРЕЛИ и их стоит убрать?\n"
            "3. Краткое резюме: что улучшить в следующем поколении?\n\n"
            "Ответ СТРОГО в формате JSON:\n"
            "{\n"
            '  "new_rules": ["правило 1", "правило 2"],\n'
            '  "deprecate_rules": ["текст устаревшего правила"],\n'
            '  "summary": "краткое резюме эволюции"\n'
            "}\n"
            "Правила формулируй конкретно и actionable. На русском."
        )

        try:
            response = await self.llm.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                system=(
                    "Ты — система метаобучения AML. Анализируй фидбек и "
                    "синтезируй улучшенные правила. Отвечай ТОЛЬКО JSON."
                ),
                messages=[{"role": "user", "content": evolution_prompt}],
            )

            raw_text = "\n".join(
                b.text for b in response.content if b.type == "text"
            ).strip()

            # Извлечь JSON (LLM может обернуть в ```json```)
            if "```" in raw_text:
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            evolution_data = json.loads(raw_text)

        except Exception as e:
            self.logger.error(f"Evolution LLM failed: {e}")
            return

        new_rules = evolution_data.get("new_rules", [])
        deprecate = evolution_data.get("deprecate_rules", [])
        summary = evolution_data.get("summary", "")

        # Применить эволюцию
        new_generation = self._generation + 1
        now = datetime.now(timezone.utc)
        import uuid

        # Добавить новые правила
        added_ids = []
        async with pool.acquire() as conn:
            for rule_text in new_rules:
                if not rule_text or len(rule_text) < 5:
                    continue
                pid = f"RULE-G{new_generation}-{uuid.uuid4().hex[:6].upper()}"
                try:
                    await conn.execute("""
                        INSERT INTO officer_learned_patterns
                            (pattern_id, rule_text, source, confidence, created_at)
                        VALUES ($1, $2, 'evolution', 0.5, $3)
                        ON CONFLICT (pattern_id) DO NOTHING
                    """, pid, rule_text, now)
                    added_ids.append(pid)
                    self._learned_rules.append(LearnedPattern(
                        pattern_id=pid,
                        rule_text=rule_text,
                        source="evolution",
                        confidence=0.5,
                        created_at=now.isoformat(),
                        active=True,
                    ))
                except Exception as e:
                    self.logger.warning(f"Failed to add rule: {e}")

            # Деактивировать устаревшие
            deprecated_ids = []
            for dep_text in deprecate:
                for rule in self._learned_rules:
                    if rule.active and dep_text.lower() in rule.rule_text.lower():
                        rule.active = False
                        deprecated_ids.append(rule.pattern_id)
                        await conn.execute("""
                            UPDATE officer_learned_patterns
                            SET active = FALSE
                            WHERE pattern_id = $1
                        """, rule.pattern_id)

            # Записать эволюцию
            evo_id = f"EVO-{new_generation}-{uuid.uuid4().hex[:6].upper()}"
            await conn.execute("""
                INSERT INTO officer_evolution_log
                    (evolution_id, generation, cases_analyzed, feedback_used,
                     new_rules, deprecated_rules,
                     accuracy_before, accuracy_after, evolution_summary, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
                evo_id, new_generation, self._cases_since_evolution,
                len(feedback_rows),
                json.dumps(new_rules, ensure_ascii=False),
                json.dumps(deprecate, ensure_ascii=False),
                accuracy_before, accuracy_before,  # after будет обновлён позже
                summary, now,
            )

        self._generation = new_generation
        self._cases_since_evolution = 0

        # Убрать неактивные из кэша
        self._learned_rules = [r for r in self._learned_rules if r.active]

        self.logger.info(
            f"Evolution complete: gen #{new_generation}, "
            f"+{len(added_ids)} rules, -{len(deprecated_ids)} deprecated. "
            f"Summary: {summary[:100]}"
        )

    # ============================================================
    # Статистика
    # ============================================================

    async def get_stats(self) -> dict:
        """Получить статистику обучения."""
        pool = getattr(self.database, 'pool', None)

        stats = {
            "generation": self._generation,
            "active_rules": len([r for r in self._learned_rules if r.active]),
            "total_feedback": self._total_feedback,
            "correct_feedback": self._correct_count,
            "accuracy": f"{self.accuracy:.1%}",
            "cases_since_evolution": self._cases_since_evolution,
            "next_evolution_in": max(0, EVOLUTION_THRESHOLD - self._cases_since_evolution),
        }

        if pool:
            async with pool.acquire() as conn:
                total_rules = await conn.fetchval(
                    "SELECT COUNT(*) FROM officer_learned_patterns"
                )
                total_evolutions = await conn.fetchval(
                    "SELECT COUNT(*) FROM officer_evolution_log"
                )
                stats["total_rules_ever"] = total_rules or 0
                stats["total_evolutions"] = total_evolutions or 0

        return stats

    async def get_learned_rules_display(self) -> list[dict]:
        """Получить правила для отображения пользователю."""
        return [
            {
                "rule": r.rule_text,
                "confidence": f"{r.confidence:.0%}",
                "source": r.source,
                "applied": r.times_applied,
                "confirmed": r.times_confirmed,
            }
            for r in self._learned_rules
            if r.active
        ]
