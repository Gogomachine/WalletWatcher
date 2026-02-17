"""TxPeek Multi-Agent AML System.

Architecture:
                      +--------------+
                      |  TELEGRAM     |
                      |  USER         |
                      +------+-------+
                             |
                      +------v-------+
                      | PRESS OFFICE |  <- Telegram message handler
                      +------+-------+
                             |
                      +------v-------+
                 +----+   OFFICER    +----+
                 |    +------+-------+    |
                 |           |            |
          +------v--+  +----v-----+  +---v------+
          |ARCHIVIST|  |INVESTIGA-|  | VERIFIER |
          +---------+  |TOR       |  +----------+
                       +----------+

Data flow:
    USER (Telegram) -> PRESS OFFICE -> OFFICER ->
    [INVESTIGATOR + VERIFIER + ARCHIVIST] -> OFFICER ->
    PRESS OFFICE -> USER (Telegram)
"""

import logging
import os
from typing import Optional

from .base import (
    RiskLevel, NetworkType, RequestType, Priority,
    CheckStatus, CaseContext, OfficerVerdict,
    InvestigatorReport, VerifierReport,
    detect_network,
)
from .archivist import ArchivistAgent
from .investigator import InvestigatorAgent
from .verifier import VerifierAgent
from .officer import OfficerAgent
from .press_office import PressOfficeAgent
from .learning import LearningEngine

logger = logging.getLogger(__name__)


class AgentSystem:
    """Central manager for the multi-agent AML system.

    Initializes all agents with proper dependencies and
    provides access to the Press Office for Telegram handlers.
    """

    def __init__(
        self,
        database=None,
        solana_client=None,
        blockchain_client=None,
        screenshot_service=None,
        api_key: Optional[str] = None,
    ):
        """Initialize the agent system.

        Args:
            database: PostgresDatabase or Database instance
            solana_client: SolanaClient instance
            blockchain_client: UniversalBlockchainClient instance
            screenshot_service: OptimizedScreenshotService instance
            api_key: Anthropic API key for Claude reasoning
        """
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

        # Learning engine for Officer self-training
        self.learning_engine = LearningEngine(
            database=database,
            api_key=self._api_key,
        )

        # Create agents bottom-up (dependencies first)
        self.archivist = ArchivistAgent(database=database, api_key=self._api_key)

        self.investigator = InvestigatorAgent(
            solana_client=solana_client,
            evm_client=blockchain_client,
            screenshot_service=screenshot_service,
            api_key=self._api_key,
        )

        self.verifier = VerifierAgent(
            solana_client=solana_client,
            api_key=self._api_key,
        )

        self.officer = OfficerAgent(
            archivist=self.archivist,
            investigator=self.investigator,
            verifier=self.verifier,
            api_key=self._api_key,
            learning_engine=self.learning_engine,
        )

        self.press_office = PressOfficeAgent(
            officer=self.officer,
            api_key=self._api_key,
        )

        self._initialized = False

    async def initialize(self):
        """Initialize agent system (create database tables, etc.)."""
        if self._initialized:
            return

        try:
            await self.archivist.initialize()
            await self.learning_engine.initialize()
            self._initialized = True
            logger.info(
                f"Agent system initialized (learning: gen #{self.learning_engine.generation})"
            )
        except Exception as e:
            logger.error(f"Agent system initialization failed: {e}")
            # Don't raise - allow system to function without archive
            self._initialized = True

    @property
    def is_ready(self) -> bool:
        return self._initialized


# Global agent system instance
_agent_system: Optional[AgentSystem] = None


def get_agent_system() -> Optional[AgentSystem]:
    """Get the global agent system instance."""
    return _agent_system


def set_agent_system(system: AgentSystem):
    """Set the global agent system instance."""
    global _agent_system
    _agent_system = system


__all__ = [
    "AgentSystem",
    "get_agent_system",
    "set_agent_system",
    "ArchivistAgent",
    "InvestigatorAgent",
    "VerifierAgent",
    "OfficerAgent",
    "PressOfficeAgent",
    "LearningEngine",
    "RiskLevel",
    "NetworkType",
    "RequestType",
    "Priority",
    "CheckStatus",
    "CaseContext",
    "OfficerVerdict",
    "InvestigatorReport",
    "VerifierReport",
    "detect_network",
]
