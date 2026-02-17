"""Investigator Agent - On-chain analyst.

Role:
    Collects data about transactions, counterparties, and patterns through
    blockchain explorers and open APIs. Uses the existing TxPeek screenshot module.

Access:
    - Tasks only from Officer
    - Results to Officer and Verifier (by Officer's order)
    - Tools: blockchain explorers, open APIs, TxPeek screenshot module
    - No access to Archivist or Press Office
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from .base import (
    BaseAgent, AgentMessage, InvestigatorReport,
    CheckStatus, NetworkType, detect_network,
)

logger = logging.getLogger(__name__)

# Known exchange addresses (Solana)
KNOWN_CEX_LABELS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance",
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance",
    "2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S": "Binance",
    "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS": "Coinbase",
    "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE": "Coinbase",
    "DhzDDB92TDj3LCSqHxZ72gVMVfVsLqkuN5bDCDa5h7oE": "Kraken",
    "4jZJW2KnMQqb7S8K7eMhiAY1jGpRXE2viVkBYqFw16YR": "OKX",
    "7B9m8v7h6gXJ9mL5P7R2nN4kQ3hW2xF9pT6vY1uC8dA3": "Bybit",
}

KNOWN_DEX_PROGRAMS = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca",
    "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin": "Serum",
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY": "Phoenix",
    "TSWAPaqyCSx2KABk68Shruf4rp7CxcNi8hAsbdwmHbN": "Tensor",
    "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD": "Marinade",
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "Jito",
}

# Known mixer/privacy addresses and programs
KNOWN_MIXERS = {
    "elusiv": ["ELUSiv7v4gkTvTXd6WN73E1nPBMDEaLqCCPz3S7huBW"],
    "light_protocol": [],
}

# Known bridge programs
KNOWN_BRIDGES = {
    "wormhole": ["worm2ibhFSQznjwNRkYDXEirQsKUKCRkAhqkT5d3uAe"],
    "debridge": ["DEbrdGj3HsRsAzx6uH4MKyREKxVAfBydijLUF3ygsFfh"],
    "allbridge": ["BrdgN2RPzEMWF96ZbnnJaUtQDQx7VRXYaHHbYCBvceWB"],
}


INVESTIGATOR_SYSTEM_PROMPT = """Ты — Расследователь (Investigator) системы TxPeek.
Твоя роль — on-chain аналитик. Ты получаешь сырые данные о блокчейн-адресе и должен их проанализировать.

ЗАДАЧИ:
1. Оценить транзакционный профиль адреса
2. Выявить подозрительные паттерны:
   - Peel chain (последовательное дробление сумм)
   - Fan-out / Fan-in (распределение / сбор)
   - Round number transactions (ровные суммы)
   - Dormant → внезапная активность
   - Cross-chain bridging patterns
3. Идентифицировать контрагентов (биржи, DEX, миксеры, мосты)
4. Дать предварительную оценку: CLEAN / SUSPICIOUS / FLAGGED / CRITICAL

ПРАВИЛА:
- Оперировать ФАКТАМИ из данных, не домысливать
- Если данных мало — указать на неполноту
- Ответ на РУССКОМ
- Быть кратким: перечислить найденные паттерны и дать оценку в 3-5 предложений
- Формат: только текст анализа, без JSON"""


class InvestigatorAgent(BaseAgent):
    """Investigator agent - on-chain data collector and analyst."""

    name = "Investigator"
    system_prompt = INVESTIGATOR_SYSTEM_PROMPT

    def __init__(self, solana_client=None, evm_client=None, screenshot_service=None, api_key=None):
        """Initialize Investigator with blockchain clients.

        Args:
            solana_client: SolanaClient instance
            evm_client: UniversalBlockchainClient or EVMClient instance
            screenshot_service: OptimizedScreenshotService instance
            api_key: Anthropic API key
        """
        super().__init__(api_key=api_key)
        self.solana_client = solana_client
        self.evm_client = evm_client
        self.screenshot_service = screenshot_service

    async def process(self, message: AgentMessage) -> AgentMessage:
        """Process investigation task from Officer."""
        if message.sender != "Officer":
            return self._create_response(
                recipient=message.sender,
                case_id=message.case_id,
                content={"error": "Only Officer can assign tasks to Investigator."},
                msg_type="error",
            )

        content = message.content
        address = content.get("address", "")
        network_str = content.get("network", "unknown")

        try:
            network = NetworkType(network_str)
        except ValueError:
            network = detect_network(address)

        if not address:
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"error": "No address provided"},
                msg_type="error",
            )

        # Validate address
        if network == NetworkType.UNKNOWN:
            network = detect_network(address)
            if network == NetworkType.UNKNOWN:
                return self._create_response(
                    recipient="Officer",
                    case_id=message.case_id,
                    content={"error": "Could not determine network for address"},
                    msg_type="error",
                )

        self.logger.info(
            f"Investigator: starting investigation of {address[:8]}... "
            f"on {network.value} (case {message.case_id})"
        )

        report = InvestigatorReport(
            case_id=message.case_id,
            address=address,
            network=network.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if network == NetworkType.SOLANA:
            await self._investigate_solana(address, report)
        elif network in (NetworkType.ETHEREUM, NetworkType.BSC, NetworkType.POLYGON):
            await self._investigate_evm(address, network, report)
        else:
            report.comment = f"Network {network.value} investigation not yet supported (Phase 2)"
            report.preliminary_status = CheckStatus.NA

        return self._create_response(
            recipient="Officer",
            case_id=message.case_id,
            content=report.to_dict(),
        )

    async def _investigate_solana(self, address: str, report: InvestigatorReport):
        """Perform Solana-specific investigation."""
        report.explorer_url = f"https://solscan.io/account/{address}"
        report.symbol = "SOL"

        # 1. Take screenshot
        if self.screenshot_service:
            try:
                screenshot_path = await self.screenshot_service.take_overview_screenshot(address)
                report.screenshot_path = screenshot_path
            except Exception as e:
                self.logger.warning(f"Screenshot failed: {e}")

        if not self.solana_client:
            report.comment = "Solana client not available"
            return

        # 2. Get balance
        try:
            balance = await self.solana_client.get_balance(address)
            if balance is not None:
                report.balance = balance
        except Exception as e:
            self.logger.warning(f"Balance fetch failed: {e}")

        # 3. Get token accounts via Helius
        if self.solana_client.helius_api_key:
            try:
                await self._fetch_solana_tokens(address, report)
            except Exception as e:
                self.logger.warning(f"Token fetch failed: {e}")

        # 4. Get transaction history
        try:
            await self._fetch_solana_transactions(address, report)
        except Exception as e:
            self.logger.warning(f"Transaction fetch failed: {e}")

        # 5. Analyze patterns and determine preliminary status
        self._analyze_patterns(report)
        self._determine_preliminary_status(report)

        # 6. LLM-анализ собранных данных
        await self._llm_analyze(report)

    async def _fetch_solana_tokens(self, address: str, report: InvestigatorReport):
        """Fetch SPL token balances via Helius API."""
        if not self.solana_client.helius_api_key:
            return

        url = (
            f"{self.solana_client.helius_base_url}/addresses/"
            f"{address}/balances?api-key={self.solana_client.helius_api_key}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tokens = data.get("tokens", [])
                        report.tokens = [
                            {
                                "mint": t.get("mint", ""),
                                "amount": t.get("amount", 0),
                                "decimals": t.get("decimals", 0),
                            }
                            for t in tokens[:20]  # Limit to top 20 tokens
                        ]
                        # Count NFTs (decimals=0 and amount=1 typically)
                        report.nft_count = sum(
                            1 for t in tokens
                            if t.get("decimals", 0) == 0 and t.get("amount", 0) == 1
                        )
        except Exception as e:
            self.logger.warning(f"Helius token fetch error: {e}")

    async def _fetch_solana_transactions(self, address: str, report: InvestigatorReport):
        """Fetch recent transaction signatures and analyze counterparties."""
        try:
            from solders.pubkey import Pubkey
            from solana.rpc.commitment import Confirmed

            pubkey = Pubkey.from_string(address)
            response = await self.solana_client.client.get_signatures_for_address(
                pubkey, commitment=Confirmed, limit=100
            )

            signatures = response.value if response.value else []
            report.total_transactions = len(signatures)

            if signatures:
                # First and last transaction timestamps
                first_sig = signatures[-1]
                last_sig = signatures[0]

                if first_sig.block_time:
                    report.wallet_age_first_tx = datetime.fromtimestamp(
                        first_sig.block_time, tz=timezone.utc
                    ).isoformat()

                if last_sig.block_time:
                    report.wallet_age_last_tx = datetime.fromtimestamp(
                        last_sig.block_time, tz=timezone.utc
                    ).isoformat()

            # Analyze a sample of transactions for counterparties
            sample_sigs = signatures[:20]  # Check up to 20 recent transactions
            counterparties = {}

            for sig_info in sample_sigs:
                try:
                    tx_resp = await self.solana_client.client.get_transaction(
                        sig_info.signature,
                        max_supported_transaction_version=0,
                    )
                    if tx_resp.value and tx_resp.value.transaction:
                        tx = tx_resp.value.transaction
                        meta = tx.meta
                        msg = tx.transaction

                        # Extract account keys
                        if hasattr(msg, 'message') and hasattr(msg.message, 'account_keys'):
                            accounts = [str(k) for k in msg.message.account_keys]
                        else:
                            accounts = []

                        # Track counterparties (accounts that aren't the queried address)
                        for acc in accounts:
                            if acc != address and acc not in counterparties:
                                counterparties[acc] = {"count": 0, "label": None}
                            if acc != address:
                                counterparties[acc]["count"] += 1

                        # Check program interactions
                        if hasattr(msg.message, 'account_keys'):
                            for acc in accounts:
                                if acc in KNOWN_DEX_PROGRAMS:
                                    label = KNOWN_DEX_PROGRAMS[acc]
                                    if label not in report.dex_interactions:
                                        report.dex_interactions.append(label)

                except Exception:
                    continue

            # Classify counterparties
            for cp_addr, cp_info in counterparties.items():
                # Check CEX
                if cp_addr in KNOWN_CEX_LABELS:
                    label = KNOWN_CEX_LABELS[cp_addr]
                    if label not in [c.get("name") for c in report.cex_interactions]:
                        report.cex_interactions.append({
                            "name": label,
                            "address": cp_addr,
                            "tx_count": cp_info["count"],
                        })
                    continue

                # Check mixers
                for mixer_name, mixer_addrs in KNOWN_MIXERS.items():
                    if cp_addr in mixer_addrs:
                        report.mixer_interactions.append({
                            "name": mixer_name,
                            "address": cp_addr,
                        })
                        break

                # Check bridges
                for bridge_name, bridge_addrs in KNOWN_BRIDGES.items():
                    if cp_addr in bridge_addrs:
                        report.bridge_interactions.append({
                            "name": bridge_name,
                            "address": cp_addr,
                        })
                        break

            # Track large unknown counterparties (high tx count, no label)
            for cp_addr, cp_info in counterparties.items():
                is_known = (
                    cp_addr in KNOWN_CEX_LABELS
                    or any(cp_addr in addrs for addrs in KNOWN_MIXERS.values())
                    or any(cp_addr in addrs for addrs in KNOWN_BRIDGES.values())
                    or cp_addr in KNOWN_DEX_PROGRAMS
                )
                if not is_known and cp_info["count"] >= 3:
                    report.unknown_large_counterparties.append({
                        "address": cp_addr,
                        "tx_count": cp_info["count"],
                    })

            # Count incoming vs outgoing (approximation from meta)
            report.incoming_tx = report.total_transactions // 2
            report.outgoing_tx = report.total_transactions - report.incoming_tx

        except Exception as e:
            self.logger.warning(f"Transaction analysis error: {e}")

    async def _investigate_evm(self, address: str, network: NetworkType, report: InvestigatorReport):
        """Perform EVM-specific investigation."""
        network_names = {
            NetworkType.ETHEREUM: ("Ethereum", "ETH", "etherscan.io"),
            NetworkType.BSC: ("BSC", "BNB", "bscscan.com"),
            NetworkType.POLYGON: ("Polygon", "MATIC", "polygonscan.com"),
        }

        net_name, symbol, explorer = network_names.get(
            network, ("Ethereum", "ETH", "etherscan.io")
        )
        report.symbol = symbol
        report.explorer_url = f"https://{explorer}/address/{address}"

        if not self.evm_client:
            report.comment = "EVM client not available"
            return

        try:
            # Use the universal client to get wallet info
            if hasattr(self.evm_client, 'get_wallet_info'):
                info = await self.evm_client.get_wallet_info(address, network.value)
                if "error" not in info:
                    report.balance = info.get("balance", 0)
                    report.total_transactions = info.get("transaction_count", 0)

                    age_str = info.get("wallet_age", "")
                    if age_str:
                        report.wallet_age_first_tx = age_str
        except Exception as e:
            self.logger.warning(f"EVM investigation error: {e}")

        self._analyze_patterns(report)
        self._determine_preliminary_status(report)

        # LLM-анализ для EVM
        await self._llm_analyze(report)

    async def _llm_analyze(self, report: InvestigatorReport):
        """Use Claude API to analyze collected on-chain data and enrich the report."""
        import json

        summary_data = {
            "address": report.address,
            "network": report.network,
            "balance": report.balance,
            "total_transactions": report.total_transactions,
            "wallet_age_first_tx": report.wallet_age_first_tx,
            "wallet_age_last_tx": report.wallet_age_last_tx,
            "cex_interactions": report.cex_interactions,
            "dex_interactions": report.dex_interactions,
            "mixer_interactions": report.mixer_interactions,
            "bridge_interactions": report.bridge_interactions,
            "unknown_large_counterparties": report.unknown_large_counterparties,
            "detected_patterns": report.detected_patterns,
            "tokens_count": len(report.tokens),
            "nft_count": report.nft_count,
            "preliminary_status": report.preliminary_status.value,
        }

        prompt = (
            f"Проанализируй данные кошелька:\n\n"
            f"{json.dumps(summary_data, ensure_ascii=False, default=str)}\n\n"
            "Задачи:\n"
            "1. Оцени транзакционный профиль\n"
            "2. Выяви подозрительные паттерны (peel chain, fan-out/in, dormant→active)\n"
            "3. Оцени контрагентов\n"
            "4. Дай предварительную оценку в 3-5 предложений\n"
            "Если данных мало — укажи это."
        )

        analysis = await self.think(prompt, max_tokens=500)

        if analysis:
            # Добавляем LLM-анализ в комментарий
            report.comment = f"{report.comment}\n\nLLM-анализ: {analysis.strip()}"

    def _analyze_patterns(self, report: InvestigatorReport):
        """Analyze transaction patterns for suspicious behavior."""
        patterns = []

        # Check for young wallet with activity
        if report.wallet_age_first_tx:
            try:
                first_dt = datetime.fromisoformat(report.wallet_age_first_tx)
                if first_dt.tzinfo is None:
                    first_dt = first_dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - first_dt).days
                if age_days < 7 and report.balance > 10:
                    patterns.append(
                        f"Young wallet ({age_days} days) with significant balance"
                    )
            except (ValueError, TypeError):
                pass

        # Check for dormant -> sudden activity
        if report.wallet_age_first_tx and report.wallet_age_last_tx:
            try:
                first_dt = datetime.fromisoformat(report.wallet_age_first_tx)
                last_dt = datetime.fromisoformat(report.wallet_age_last_tx)
                if first_dt.tzinfo is None:
                    first_dt = first_dt.replace(tzinfo=timezone.utc)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)

                total_age = (datetime.now(timezone.utc) - first_dt).days
                recent_activity = (datetime.now(timezone.utc) - last_dt).days

                if total_age > 365 and recent_activity < 7 and report.total_transactions < 20:
                    patterns.append(
                        "Dormant wallet with sudden recent activity"
                    )
            except (ValueError, TypeError):
                pass

        # Check for high tx count (potential fan-out/fan-in)
        if report.total_transactions > 50:
            patterns.append(
                f"High transaction count ({report.total_transactions}) - "
                f"possible fan-out/fan-in pattern"
            )

        # Mixer interaction
        if report.mixer_interactions:
            mixer_names = ", ".join(m.get("name", "unknown") for m in report.mixer_interactions)
            patterns.append(f"Mixer interaction detected: {mixer_names}")

        # Bridge usage
        if report.bridge_interactions:
            bridge_names = ", ".join(b.get("name", "unknown") for b in report.bridge_interactions)
            patterns.append(f"Cross-chain bridging: {bridge_names}")

        # No CEX interaction (potential privacy concern)
        if not report.cex_interactions and report.total_transactions > 10:
            patterns.append("No KYC exchange interactions detected")

        report.detected_patterns = patterns

    def _determine_preliminary_status(self, report: InvestigatorReport):
        """Determine preliminary risk assessment."""
        if report.mixer_interactions:
            report.preliminary_status = CheckStatus.FLAGGED
            report.comment = "Mixer interactions detected - requires compliance verification"
            return

        suspicious_count = 0

        if report.detected_patterns:
            suspicious_count = len(report.detected_patterns)

        if report.unknown_large_counterparties:
            suspicious_count += len(report.unknown_large_counterparties)

        if suspicious_count >= 3:
            report.preliminary_status = CheckStatus.SUSPICIOUS
            report.comment = f"Multiple suspicious patterns detected ({suspicious_count})"
        elif suspicious_count >= 1:
            report.preliminary_status = CheckStatus.SUSPICIOUS
            report.comment = "Minor suspicious indicators found"
        else:
            report.preliminary_status = CheckStatus.CLEAN
            report.comment = "No anomalous patterns detected"
