"""Base agent classes and message protocol for the TxPeek multi-agent system.

Architecture:
    USER (Telegram) -> PRESS_OFFICE -> OFFICER -> [INVESTIGATOR + VERIFIER + ARCHIVIST] -> OFFICER -> PRESS_OFFICE -> USER

Agents never send messages to Telegram directly (only Press Office).
Agents never bypass the Officer (exception: Investigator -> Verifier by Officer's order).
"""

import os
import uuid
import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from anthropic import AsyncAnthropic


logger = logging.getLogger(__name__)


# ============================================================
# Enums
# ============================================================

class RequestType(Enum):
    """Types of requests that can be processed."""
    ADDRESS_CHECK = "address_check"
    INFO_REQUEST = "info_request"
    GENERAL_QUESTION = "general_question"
    OUT_OF_SCOPE = "out_of_scope"


class Priority(Enum):
    """Task priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(Enum):
    """AML risk levels with emoji indicators."""
    CLEAN = ("CLEAN", "\U0001f7e2", 0, 15)          # green circle
    LOW_RISK = ("LOW_RISK", "\U0001f7e1", 16, 35)    # yellow circle
    MEDIUM_RISK = ("MEDIUM_RISK", "\U0001f7e0", 36, 60)  # orange circle
    HIGH_RISK = ("HIGH_RISK", "\U0001f534", 61, 85)   # red circle
    CRITICAL = ("CRITICAL", "\u26d4", 86, 100)        # no entry

    def __init__(self, label: str, emoji: str, score_min: int, score_max: int):
        self.label = label
        self.emoji = emoji
        self.score_min = score_min
        self.score_max = score_max

    @classmethod
    def from_score(cls, score: int) -> "RiskLevel":
        """Get risk level from numeric score (0-100)."""
        score = max(0, min(100, score))
        for level in cls:
            if level.score_min <= score <= level.score_max:
                return level
        return cls.CRITICAL


class NetworkType(Enum):
    """Supported blockchain networks."""
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    BITCOIN = "bitcoin"
    TRON = "tron"
    BSC = "bsc"
    POLYGON = "polygon"
    UNKNOWN = "unknown"


class CheckStatus(Enum):
    """Status markers used in reports."""
    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    FLAGGED = "flagged"
    CRITICAL = "critical"
    NOT_FOUND = "not_found"
    ERROR = "error"
    NA = "n/a"


# ============================================================
# Data classes
# ============================================================

@dataclass
class AgentMessage:
    """Message passed between agents."""
    sender: str
    recipient: str
    case_id: str
    content: Any
    msg_type: str = "task"  # task, result, error, query, write_order
    priority: Priority = Priority.MEDIUM
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CaseContext:
    """Context for an AML check case."""
    case_id: str = field(default_factory=lambda: f"CASE-{uuid.uuid4().hex[:8].upper()}")
    user_id: int = 0
    address: str = ""
    network: NetworkType = NetworkType.UNKNOWN
    request_type: RequestType = RequestType.ADDRESS_CHECK
    priority: Priority = Priority.MEDIUM
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Results from agents
    investigator_report: Optional[dict] = None
    verifier_report: Optional[dict] = None
    archivist_data: Optional[dict] = None

    # Final verdict
    risk_level: Optional[RiskLevel] = None
    risk_score: Optional[int] = None
    confidence: Optional[int] = None
    verdict_reason: str = ""
    recommendation: str = ""
    screenshot_path: Optional[str] = None
    archived: bool = False


@dataclass
class InvestigatorReport:
    """Structured report from the Investigator agent."""
    case_id: str = ""
    address: str = ""
    network: str = ""
    explorer_url: str = ""
    timestamp: str = ""

    # Profile
    wallet_age_first_tx: str = ""
    wallet_age_last_tx: str = ""
    total_transactions: int = 0
    incoming_tx: int = 0
    outgoing_tx: int = 0
    balance: float = 0.0
    balance_usd: float = 0.0
    symbol: str = ""
    tokens: list = field(default_factory=list)
    nft_count: int = 0

    # Counterparties
    cex_interactions: list = field(default_factory=list)
    dex_interactions: list = field(default_factory=list)
    mixer_interactions: list = field(default_factory=list)
    bridge_interactions: list = field(default_factory=list)
    suspicious_counterparties: list = field(default_factory=list)
    unknown_large_counterparties: list = field(default_factory=list)

    # Patterns
    detected_patterns: list = field(default_factory=list)

    # Screenshot
    screenshot_path: Optional[str] = None

    # Assessment
    preliminary_status: CheckStatus = CheckStatus.CLEAN
    comment: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "address": self.address,
            "network": self.network,
            "explorer_url": self.explorer_url,
            "timestamp": self.timestamp,
            "wallet_age_first_tx": self.wallet_age_first_tx,
            "wallet_age_last_tx": self.wallet_age_last_tx,
            "total_transactions": self.total_transactions,
            "incoming_tx": self.incoming_tx,
            "outgoing_tx": self.outgoing_tx,
            "balance": self.balance,
            "balance_usd": self.balance_usd,
            "symbol": self.symbol,
            "tokens": self.tokens,
            "nft_count": self.nft_count,
            "cex_interactions": self.cex_interactions,
            "dex_interactions": self.dex_interactions,
            "mixer_interactions": self.mixer_interactions,
            "bridge_interactions": self.bridge_interactions,
            "suspicious_counterparties": self.suspicious_counterparties,
            "unknown_large_counterparties": self.unknown_large_counterparties,
            "detected_patterns": self.detected_patterns,
            "screenshot_path": self.screenshot_path,
            "preliminary_status": self.preliminary_status.value,
            "comment": self.comment,
        }


@dataclass
class VerifierReport:
    """Structured report from the Verifier agent."""
    case_id: str = ""
    risk_score: int = 0

    # Check results
    ofac_sdn: CheckStatus = CheckStatus.NA
    eu_sanctions: CheckStatus = CheckStatus.NA
    chainabuse_reports: int = 0
    chainabuse_status: CheckStatus = CheckStatus.NA
    usdt_frozen: CheckStatus = CheckStatus.NA
    usdc_frozen: CheckStatus = CheckStatus.NA
    explorer_labels: CheckStatus = CheckStatus.NA
    explorer_label_text: str = ""
    github_scam_dbs: CheckStatus = CheckStatus.NA

    # Score breakdown
    score_factors: list = field(default_factory=list)  # list of (description, points)
    mitigating_factors: list = field(default_factory=list)

    # Cross-analysis
    cross_analysis_notes: list = field(default_factory=list)
    exposure_level: str = ""  # "direct", "1-hop", "2-hop", "none"

    # Recommendation
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "risk_score": self.risk_score,
            "ofac_sdn": self.ofac_sdn.value,
            "eu_sanctions": self.eu_sanctions.value,
            "chainabuse_reports": self.chainabuse_reports,
            "chainabuse_status": self.chainabuse_status.value,
            "usdt_frozen": self.usdt_frozen.value,
            "usdc_frozen": self.usdc_frozen.value,
            "explorer_labels": self.explorer_labels.value,
            "explorer_label_text": self.explorer_label_text,
            "github_scam_dbs": self.github_scam_dbs.value,
            "score_factors": self.score_factors,
            "mitigating_factors": self.mitigating_factors,
            "cross_analysis_notes": self.cross_analysis_notes,
            "exposure_level": self.exposure_level,
            "recommendation": self.recommendation,
        }


@dataclass
class OfficerVerdict:
    """Final verdict from the Chief Officer."""
    case_id: str = ""
    address: str = ""
    network: str = ""
    risk_level: RiskLevel = RiskLevel.CLEAN
    risk_score: int = 0
    confidence: int = 0
    reason: str = ""
    recommendation: str = ""
    should_archive: bool = True
    screenshot_path: Optional[str] = None

    # Full reports for detailed view
    investigator_report: Optional[dict] = None
    verifier_report: Optional[dict] = None


# ============================================================
# Base Agent
# ============================================================

class BaseAgent:
    """Base class for all agents in the TxPeek system.

    Each agent has access to Claude API as its "reasoning brain".
    The LLM interprets collected data and generates assessments
    according to the agent's role defined in its system prompt.
    """

    name: str = "BaseAgent"
    system_prompt: str = ""
    model: str = "claude-sonnet-4-20250514"

    def __init__(self, api_key: Optional[str] = None):
        self.logger = logging.getLogger(f"txpeek.{self.name}")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client: Optional[AsyncAnthropic] = None

    @property
    def llm(self) -> Optional[AsyncAnthropic]:
        """Lazy-initialized Anthropic client."""
        if self._client is None and self._api_key:
            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def think(self, prompt: str, max_tokens: int = 1024) -> str:
        """Send a prompt to Claude API and get a response.

        This is the agent's 'brain' — used to reason about collected data.

        Args:
            prompt: The user-role message describing what to analyze
            max_tokens: Max response tokens

        Returns:
            Claude's response text, or empty string on failure
        """
        if not self.llm:
            self.logger.debug(f"{self.name}: no API key, skipping LLM call")
            return ""

        try:
            response = await self.llm.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            return "\n".join(
                block.text for block in response.content if block.type == "text"
            )
        except Exception as e:
            self.logger.warning(f"{self.name} LLM error: {e}")
            return ""

    async def process(self, message: AgentMessage) -> AgentMessage:
        """Process an incoming message. Override in subclasses."""
        raise NotImplementedError

    def _create_response(
        self,
        recipient: str,
        case_id: str,
        content: Any,
        msg_type: str = "result",
        priority: Priority = Priority.MEDIUM,
    ) -> AgentMessage:
        """Create a response message."""
        return AgentMessage(
            sender=self.name,
            recipient=recipient,
            case_id=case_id,
            content=content,
            msg_type=msg_type,
            priority=priority,
        )


def detect_network(address: str) -> NetworkType:
    """Detect blockchain network by address format.

    Args:
        address: Blockchain address string

    Returns:
        Detected NetworkType
    """
    import re

    address = address.strip()

    # EVM: 0x + 40 hex chars
    if re.match(r'^0x[a-fA-F0-9]{40}$', address):
        return NetworkType.ETHEREUM

    # Bitcoin: bc1... / 1... / 3...
    if re.match(r'^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$', address):
        return NetworkType.BITCOIN

    # Tron: T + 33 chars
    if re.match(r'^T[a-zA-Z0-9]{33}$', address):
        return NetworkType.TRON

    # Solana: base58, 32-44 chars
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', address):
        return NetworkType.SOLANA

    return NetworkType.UNKNOWN
