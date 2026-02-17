"""Archivist Agent - Immutable data storage and retrieval.

Role:
    Keeper of accumulated information. Immutable storage - data cannot be
    modified or deleted after writing. Communicates EXCLUSIVELY with the Officer.

Access:
    - Read-only on own database
    - Write only by Officer's order
    - Communication only with Officer

Prohibited:
    - Modifying/deleting existing records
    - Passing data to anyone other than Officer
    - Making analytical conclusions
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from .base import BaseAgent, AgentMessage, Priority

logger = logging.getLogger(__name__)


class ArchivistAgent(BaseAgent):
    """Archivist agent - immutable data storage for AML cases."""

    name = "Archivist"

    def __init__(self, database, api_key=None):
        """Initialize Archivist with database connection.

        Args:
            database: PostgresDatabase or Database instance
            api_key: Anthropic API key (not used by Archivist, passed to BaseAgent)
        """
        super().__init__(api_key=api_key)
        self.database = database

    async def initialize(self):
        """Create the AML archive tables if they don't exist."""
        pool = getattr(self.database, 'pool', None)
        if pool is None:
            self.logger.warning("No pool available, skipping archive table creation")
            return

        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS aml_archive (
                    id SERIAL PRIMARY KEY,
                    case_id TEXT UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    address TEXT NOT NULL,
                    network TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    risk_score INTEGER NOT NULL,
                    confidence INTEGER DEFAULT 0,
                    verdict_reason TEXT,
                    recommendation TEXT,
                    investigator_data JSONB,
                    verifier_data JSONB,
                    linked_addresses TEXT[],
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_aml_archive_address
                ON aml_archive(address)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_aml_archive_user_id
                ON aml_archive(user_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_aml_archive_case_id
                ON aml_archive(case_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_aml_archive_created_at
                ON aml_archive(created_at)
            """)

        self.logger.info("Archivist: archive tables initialized")

    async def process(self, message: AgentMessage) -> AgentMessage:
        """Process message from Officer.

        Supports:
            - msg_type="query": Search for existing records
            - msg_type="write_order": Store new case data
        """
        if message.sender != "Officer":
            self.logger.warning(
                f"Archivist: rejected message from {message.sender} "
                f"(only Officer allowed)"
            )
            return self._create_response(
                recipient=message.sender,
                case_id=message.case_id,
                content={"error": "Access denied. Only Officer can communicate with Archivist."},
                msg_type="error",
            )

        if message.msg_type == "query":
            return await self._handle_query(message)
        elif message.msg_type == "write_order":
            return await self._handle_write(message)
        else:
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"error": f"Unknown message type: {message.msg_type}"},
                msg_type="error",
            )

    async def _handle_query(self, message: AgentMessage) -> AgentMessage:
        """Search archive for existing records.

        Content should contain:
            - address: str (required) - Address to search
            - max_age_hours: int (optional) - Max age of records in hours
        """
        content = message.content
        address = content.get("address", "")

        if not address:
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"status": "NOT_FOUND", "records": []},
            )

        pool = getattr(self.database, 'pool', None)
        if pool is None:
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"status": "NOT_FOUND", "records": [], "note": "No database pool"},
            )

        try:
            async with pool.acquire() as conn:
                # Exact address match
                rows = await conn.fetch(
                    """
                    SELECT case_id, user_id, address, network, risk_level, risk_score,
                           confidence, verdict_reason, recommendation,
                           investigator_data, verifier_data, linked_addresses, created_at
                    FROM aml_archive
                    WHERE address = $1
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    address,
                )

                if not rows:
                    return self._create_response(
                        recipient="Officer",
                        case_id=message.case_id,
                        content={"status": "NOT_FOUND", "records": []},
                    )

                records = []
                for row in rows:
                    record = dict(row)
                    # Convert datetime to string for serialization
                    if record.get("created_at"):
                        record["created_at"] = record["created_at"].isoformat()
                    records.append(record)

                # Check freshness
                max_age_hours = content.get("max_age_hours", 24)
                fresh_records = []
                cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

                for rec in records:
                    created = rec.get("created_at", "")
                    if created:
                        try:
                            created_dt = datetime.fromisoformat(created)
                            if created_dt.tzinfo is None:
                                created_dt = created_dt.replace(tzinfo=timezone.utc)
                            if created_dt >= cutoff:
                                fresh_records.append(rec)
                        except (ValueError, TypeError):
                            pass

                # Build risk level history
                risk_history = [
                    {
                        "case_id": r["case_id"],
                        "risk_level": r["risk_level"],
                        "risk_score": r["risk_score"],
                        "created_at": r["created_at"],
                    }
                    for r in records
                ]

                return self._create_response(
                    recipient="Officer",
                    case_id=message.case_id,
                    content={
                        "status": "FOUND",
                        "total_records": len(records),
                        "fresh_records": fresh_records,
                        "all_records": records,
                        "risk_history": risk_history,
                        "has_fresh_data": len(fresh_records) > 0,
                    },
                )

        except Exception as e:
            self.logger.error(f"Archivist query error: {e}")
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"status": "ERROR", "error": str(e), "records": []},
                msg_type="error",
            )

    async def _handle_write(self, message: AgentMessage) -> AgentMessage:
        """Write new case data to archive. Immutable - no updates/deletes.

        Content should contain:
            - case_id, user_id, address, network, risk_level, risk_score,
              confidence, verdict_reason, recommendation,
              investigator_data, verifier_data, linked_addresses
        """
        content = message.content
        pool = getattr(self.database, 'pool', None)

        if pool is None:
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"status": "ERROR", "error": "No database pool"},
                msg_type="error",
            )

        try:
            async with pool.acquire() as conn:
                import json
                inv_data = content.get("investigator_data")
                ver_data = content.get("verifier_data")
                # Convert dicts to JSON strings for JSONB columns
                if isinstance(inv_data, dict):
                    inv_data = json.dumps(inv_data)
                if isinstance(ver_data, dict):
                    ver_data = json.dumps(ver_data)

                await conn.execute(
                    """
                    INSERT INTO aml_archive (
                        case_id, user_id, address, network,
                        risk_level, risk_score, confidence,
                        verdict_reason, recommendation,
                        investigator_data, verifier_data, linked_addresses
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (case_id) DO NOTHING
                    """,
                    content.get("case_id", message.case_id),
                    content.get("user_id", 0),
                    content.get("address", ""),
                    content.get("network", "unknown"),
                    content.get("risk_level", "CLEAN"),
                    content.get("risk_score", 0),
                    content.get("confidence", 0),
                    content.get("verdict_reason", ""),
                    content.get("recommendation", ""),
                    inv_data,
                    ver_data,
                    content.get("linked_addresses", []),
                )

            self.logger.info(
                f"Archivist: recorded case {message.case_id} "
                f"for address {content.get('address', '?')}"
            )

            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"status": "RECORDED", "case_id": message.case_id},
            )

        except Exception as e:
            self.logger.error(f"Archivist write error: {e}")
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"status": "ERROR", "error": str(e)},
                msg_type="error",
            )
