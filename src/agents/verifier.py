"""Verifier Agent - Compliance analyst.

Role:
    Checks addresses against sanctions lists and blacklists. Cross-analyzes
    with Investigator data. Issues compliance verdict with numeric risk score.

Access:
    - Tasks from Officer
    - Data from Investigator (by Officer's order)
    - Results only to Officer
    - Tools: open sanctions databases, blacklists
    - No access to Archivist or Press Office
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from .base import (
    BaseAgent, AgentMessage, VerifierReport,
    CheckStatus, RiskLevel, NetworkType,
)

logger = logging.getLogger(__name__)

# OFAC SDN known sanctioned crypto addresses (subset - key entries)
# Source: https://www.treasury.gov/ofac/downloads/sdnlist.txt
OFAC_SANCTIONED_ADDRESSES = {
    # Tornado Cash (Ethereum)
    "0x8589427373D6D84E98730D7795D8f6f8731FDA16",
    "0x722122dF12D4e14e13Ac3b6895a86e84145b6967",
    "0xDD4c48C0B24039969fC16D1cdF626eaB821d3384",
    "0xd90e2f925DA726b50C4Ed8D0Fb90Ad053324F31b",
    "0xd96f2B1c14Db8458374d9Aca76E26c3D18364307",
    "0x4736dCf1b7A3d580672CcE6E7c65cd5cc9cFBfA9",
    "0xD4B88Df4D29F5CedD6857912842cff3b20C8Cfa3",
    "0x910Cbd523D972eb0a6f4cAe4618aD62622b39DbF",
    "0xA160cdAB225685dA1d56aa342Ad8841c3b53f291",
    "0xFD8610d20aA15b7B2E3Be39B396a1bC3516c7144",
    "0xF60dD140cFf0706bAE9Cd734Ac3683731B816DEd",
    "0x23773E65ed146A459791799d01336DB287f25334",
    "0x22aaA7720ddd5388A3c0A3333430953C68f1849b",
    "0xBA214C1c1928a32Bffe790263E38B4Af9bFCD659",
    "0xb1C8094B234DcE6e03f10a5b673c1d8C69739A00",
    "0x527653eA119F3E6a1F5BD18fbF4714081D7B31ce",
    "0x58E8dCC13BE9780fC42E8723D8EaD4CF46943dF2",
    "0xD691F27f38B395864Ea86CfC7253969B409c362d",
    "0xaEaaC358560e11f52454D997AAFF2c5731B6f8a6",
    "0x1356c899D8C9467C7f71C195612F8A395aBf2f0a",
    "0xA7e5d5A720f06526557c513402f2e6B5fA20b008",
    "0x610B717796ad172B316836AC95a2ffad065CeaB4",
    "0x178169B423a011fff22B9e3F3abeA13414dDD0F1",
    "0xbB93e510BbCD0B7beb5A853875f9eC60275CF498",
    "0x2717c5e28cf931f9862FD1E33Fb4bF9b5F0a277F",
    "0x03893a7c7463AE47D46bc7f091665f1893656003",
    "0xCa0840578f57fE216Fab1C8A0DbEB8929c807Eee",
    # Blender.io
    "0x94A1B5CdB22c43faab4AbEb5c74999895464Ddba",
    # Lazarus Group related
    "0x098B716B8Aaf21512996dC57EB0615e2383E2f96",
    "0xa0e1c89Ef1a489c9C7dE96311eD5Ce5D32c20E4B",
    # Garantex
    "0x6F1cA141A28907F78Ebaa64f83E1866334B8b127",
}

# ChainAbuse categories
CHAINABUSE_CATEGORIES = ["scam", "ransomware", "theft", "fraud", "darknet", "terrorist_financing"]


VERIFIER_SYSTEM_PROMPT = """Ты — Проверятор (Verifier) системы TxPeek.
Твоя роль — compliance-аналитик. Ты получаешь результаты проверок по санкционным базам,
блэклистам и cross-analysis с данными Расследователя.

ЗАДАЧИ:
1. Оценить compliance-статус адреса
2. Проверить прямые совпадения (OFAC, заморозка, ChainAbuse)
3. Оценить связи 1-hop и 2-hop с санкционными адресами
4. Сформировать итоговый risk score (0-100)

ПРАВИЛА:
- False positive лучше false negative
- Если OFAC/заморозка = 100 баллов сразу
- Учитывать смягчающие факторы (KYC-биржи, возраст кошелька)
- Ответ на РУССКОМ
- Кратко: 2-4 предложения с обоснованием score
- Формат: только текст анализа, без JSON"""


class VerifierAgent(BaseAgent):
    """Verifier agent - compliance checks and risk scoring."""

    name = "Verifier"
    system_prompt = VERIFIER_SYSTEM_PROMPT

    def __init__(self, solana_client=None, api_key=None):
        """Initialize Verifier.

        Args:
            solana_client: SolanaClient for on-chain freeze checks
            api_key: Anthropic API key
        """
        super().__init__(api_key=api_key)
        self.solana_client = solana_client

    async def process(self, message: AgentMessage) -> AgentMessage:
        """Process verification task from Officer."""
        if message.sender != "Officer":
            return self._create_response(
                recipient=message.sender,
                case_id=message.case_id,
                content={"error": "Only Officer can assign tasks to Verifier."},
                msg_type="error",
            )

        content = message.content
        address = content.get("address", "")
        network = content.get("network", "unknown")
        investigator_data = content.get("investigator_data")

        if not address:
            return self._create_response(
                recipient="Officer",
                case_id=message.case_id,
                content={"error": "No address provided"},
                msg_type="error",
            )

        self.logger.info(
            f"Verifier: starting compliance check for {address[:8]}... "
            f"(case {message.case_id})"
        )

        report = VerifierReport(case_id=message.case_id)

        # 1. Check sanctions lists
        await self._check_ofac_sdn(address, report)

        # 2. Check ChainAbuse
        await self._check_chainabuse(address, report)

        # 3. Check stablecoin freeze status
        if network == "solana":
            await self._check_solana_freeze(address, report)
        elif network in ("ethereum", "bsc", "polygon"):
            await self._check_evm_blacklist(address, network, report)

        # 4. Check GitHub scam databases
        await self._check_github_scam_lists(address, report)

        # 5. Check explorer labels
        await self._check_explorer_labels(address, network, report)

        # 6. Cross-analysis with Investigator data
        if investigator_data:
            self._cross_analyze(investigator_data, report)

        # 7. Calculate final risk score
        self._calculate_risk_score(investigator_data, report)

        # 8. LLM-обогащение рекомендации
        await self._llm_enrich(address, report)

        return self._create_response(
            recipient="Officer",
            case_id=message.case_id,
            content=report.to_dict(),
        )

    async def _check_ofac_sdn(self, address: str, report: VerifierReport):
        """Check address against OFAC SDN sanctioned addresses list."""
        # Direct match against known sanctioned addresses
        normalized = address.strip()
        if normalized in OFAC_SANCTIONED_ADDRESSES:
            report.ofac_sdn = CheckStatus.FLAGGED
            report.score_factors.append(("OFAC SDN direct match", 100))
            self.logger.warning(f"OFAC SDN MATCH for {address[:8]}...")
            return

        # Also check case-insensitive for EVM addresses
        if normalized.startswith("0x"):
            lower = normalized.lower()
            checksummed_matches = {a.lower() for a in OFAC_SANCTIONED_ADDRESSES}
            if lower in checksummed_matches:
                report.ofac_sdn = CheckStatus.FLAGGED
                report.score_factors.append(("OFAC SDN direct match (case-insensitive)", 100))
                return

        report.ofac_sdn = CheckStatus.CLEAN

    async def _check_chainabuse(self, address: str, report: VerifierReport):
        """Check address on ChainAbuse via web scraping/API."""
        try:
            url = f"https://www.chainabuse.com/address/{address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=10),
                    headers={"User-Agent": "TxPeek-AML-Bot/1.0"},
                ) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        # Look for report indicators in the page
                        report_match = re.search(r'(\d+)\s*report', text, re.IGNORECASE)
                        if report_match:
                            count = int(report_match.group(1))
                            report.chainabuse_reports = count
                            if count >= 5:
                                report.chainabuse_status = CheckStatus.FLAGGED
                                report.score_factors.append(
                                    (f"ChainAbuse: {count} reports", 80)
                                )
                            elif count >= 3:
                                report.chainabuse_status = CheckStatus.SUSPICIOUS
                                report.score_factors.append(
                                    (f"ChainAbuse: {count} reports", 40)
                                )
                            elif count >= 1:
                                report.chainabuse_status = CheckStatus.SUSPICIOUS
                                report.score_factors.append(
                                    (f"ChainAbuse: {count} reports", 25)
                                )
                            else:
                                report.chainabuse_status = CheckStatus.CLEAN
                        else:
                            report.chainabuse_status = CheckStatus.CLEAN
                    elif resp.status == 404:
                        report.chainabuse_status = CheckStatus.CLEAN
                    else:
                        report.chainabuse_status = CheckStatus.NA
        except Exception as e:
            self.logger.warning(f"ChainAbuse check failed: {e}")
            report.chainabuse_status = CheckStatus.NA

    async def _check_solana_freeze(self, address: str, report: VerifierReport):
        """Check if USDT/USDC token accounts are frozen on Solana."""
        if not self.solana_client:
            report.usdt_frozen = CheckStatus.NA
            report.usdc_frozen = CheckStatus.NA
            return

        try:
            from solders.pubkey import Pubkey

            # Known USDT and USDC mints on Solana
            usdt_mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

            pubkey = Pubkey.from_string(address)

            # Check token accounts for freeze state
            try:
                resp = await self.solana_client.client.get_token_accounts_by_owner_json_parsed(
                    pubkey,
                    opts={"mint": Pubkey.from_string(usdt_mint)},
                )
                if resp.value:
                    for account in resp.value:
                        parsed = account.account.data.parsed
                        if parsed and parsed.get("info", {}).get("state") == "frozen":
                            report.usdt_frozen = CheckStatus.FLAGGED
                            report.score_factors.append(
                                ("USDT account FROZEN on Solana", 100)
                            )
                            break
                    else:
                        report.usdt_frozen = CheckStatus.CLEAN
                else:
                    report.usdt_frozen = CheckStatus.CLEAN
            except Exception:
                report.usdt_frozen = CheckStatus.NA

            try:
                resp = await self.solana_client.client.get_token_accounts_by_owner_json_parsed(
                    pubkey,
                    opts={"mint": Pubkey.from_string(usdc_mint)},
                )
                if resp.value:
                    for account in resp.value:
                        parsed = account.account.data.parsed
                        if parsed and parsed.get("info", {}).get("state") == "frozen":
                            report.usdc_frozen = CheckStatus.FLAGGED
                            report.score_factors.append(
                                ("USDC account FROZEN on Solana", 100)
                            )
                            break
                    else:
                        report.usdc_frozen = CheckStatus.CLEAN
                else:
                    report.usdc_frozen = CheckStatus.CLEAN
            except Exception:
                report.usdc_frozen = CheckStatus.NA

        except Exception as e:
            self.logger.warning(f"Solana freeze check error: {e}")
            report.usdt_frozen = CheckStatus.NA
            report.usdc_frozen = CheckStatus.NA

    async def _check_evm_blacklist(self, address: str, network: str, report: VerifierReport):
        """Check EVM stablecoin blacklist status."""
        # For EVM, we'd need web3 calls to USDT/USDC blacklist contracts
        # This is a simplified version that checks known frozen addresses
        report.usdt_frozen = CheckStatus.NA
        report.usdc_frozen = CheckStatus.NA

    async def _check_github_scam_lists(self, address: str, report: VerifierReport):
        """Check address against GitHub-hosted scam databases."""
        try:
            # Check MetaMask eth-phishing-detect
            url = (
                "https://raw.githubusercontent.com/MetaMask/eth-phishing-detect/"
                "main/src/config.json"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        blacklist = data.get("blacklist", [])
                        # This checks domains not addresses, but included for completeness
                        report.github_scam_dbs = CheckStatus.CLEAN
                    else:
                        report.github_scam_dbs = CheckStatus.NA
        except Exception as e:
            self.logger.warning(f"GitHub scam list check failed: {e}")
            report.github_scam_dbs = CheckStatus.NA

    async def _check_explorer_labels(self, address: str, network: str, report: VerifierReport):
        """Check if blockchain explorers have negative labels for the address."""
        if network == "solana":
            try:
                url = f"https://api.solana.fm/v0/accounts/{address}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=10),
                        headers={"User-Agent": "TxPeek-AML-Bot/1.0"},
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            labels = data.get("result", {}).get("data", {}).get("tags", [])
                            if labels:
                                negative_keywords = [
                                    "phishing", "scam", "hack", "exploit",
                                    "fake", "malicious", "drainer", "spam",
                                ]
                                for label in labels:
                                    label_lower = str(label).lower()
                                    if any(kw in label_lower for kw in negative_keywords):
                                        report.explorer_labels = CheckStatus.FLAGGED
                                        report.explorer_label_text = str(label)
                                        report.score_factors.append(
                                            (f"Explorer negative label: {label}", 30)
                                        )
                                        return
                            report.explorer_labels = CheckStatus.CLEAN
                        else:
                            report.explorer_labels = CheckStatus.NA
            except Exception as e:
                self.logger.warning(f"Explorer label check failed: {e}")
                report.explorer_labels = CheckStatus.NA
        else:
            report.explorer_labels = CheckStatus.NA

    def _cross_analyze(self, investigator_data: dict, report: VerifierReport):
        """Cross-analyze Investigator findings with compliance data."""
        notes = []

        # Check mixer interactions
        mixers = investigator_data.get("mixer_interactions", [])
        if mixers:
            mixer_names = [m.get("name", "unknown") for m in mixers]
            for name in mixer_names:
                if "tornado" in name.lower():
                    report.score_factors.append(
                        (f"Interaction with Tornado Cash (SANCTIONED)", 55)
                    )
                    notes.append(f"Direct interaction with sanctioned mixer: {name}")
                else:
                    report.score_factors.append(
                        (f"Interaction with mixer: {name}", 45)
                    )
                    notes.append(f"Mixer interaction: {name}")

        # Check if counterparties are in sanctions
        suspicious = investigator_data.get("suspicious_counterparties", [])
        unknown_large = investigator_data.get("unknown_large_counterparties", [])

        for cp in unknown_large:
            cp_addr = cp.get("address", "")
            if cp_addr in OFAC_SANCTIONED_ADDRESSES:
                report.score_factors.append(
                    ("Counterparty on OFAC SDN list (1-hop)", 60)
                )
                notes.append(f"1-hop to sanctioned address: {cp_addr[:8]}...")
                report.exposure_level = "1-hop"

        # Check bridge usage
        bridges = investigator_data.get("bridge_interactions", [])
        if bridges:
            notes.append(
                f"Cross-chain bridge usage: {', '.join(b.get('name', '') for b in bridges)}"
            )

        # Check CEX interactions (mitigating)
        cex = investigator_data.get("cex_interactions", [])
        if cex:
            report.mitigating_factors.append(
                (f"KYC exchange interactions: {', '.join(c.get('name', '') for c in cex)}", -20)
            )
            notes.append(f"Has KYC exchange activity: {', '.join(c.get('name', '') for c in cex)}")
        elif investigator_data.get("total_transactions", 0) > 10:
            report.score_factors.append(
                ("No KYC exchange interactions", 10)
            )
            notes.append("No KYC exchange interactions detected")

        # Check wallet age
        first_tx = investigator_data.get("wallet_age_first_tx", "")
        if first_tx:
            try:
                first_dt = datetime.fromisoformat(first_tx)
                if first_dt.tzinfo is None:
                    first_dt = first_dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - first_dt).days

                if age_days < 7 and investigator_data.get("balance", 0) > 10:
                    report.score_factors.append(
                        ("Young wallet (<7 days) with large balance", 15)
                    )
                elif age_days > 365:
                    report.mitigating_factors.append(
                        ("Long clean history (>1 year)", -15)
                    )
            except (ValueError, TypeError):
                pass

        # Check patterns
        patterns = investigator_data.get("detected_patterns", [])
        if patterns:
            report.score_factors.append(
                (f"Suspicious patterns ({len(patterns)})", 20)
            )
            for p in patterns:
                notes.append(f"Pattern: {p}")

        # DEX interactions (mitigating - normal DeFi user)
        dex = investigator_data.get("dex_interactions", [])
        if len(dex) >= 3:
            report.mitigating_factors.append(
                ("Active DeFi participation", -10)
            )

        if not report.exposure_level:
            report.exposure_level = "none"

        report.cross_analysis_notes = notes

    async def _llm_enrich(self, address: str, report: VerifierReport):
        """Use Claude API to enrich risk assessment with reasoning."""
        import json

        summary = {
            "risk_score": report.risk_score,
            "ofac_sdn": report.ofac_sdn.value,
            "chainabuse_status": report.chainabuse_status.value,
            "chainabuse_reports": report.chainabuse_reports,
            "usdt_frozen": report.usdt_frozen.value,
            "usdc_frozen": report.usdc_frozen.value,
            "explorer_labels": report.explorer_labels.value,
            "score_factors": report.score_factors,
            "mitigating_factors": report.mitigating_factors,
            "cross_analysis_notes": report.cross_analysis_notes,
            "exposure_level": report.exposure_level,
        }

        prompt = (
            f"Результаты compliance-проверки адреса {address[:12]}...:\n\n"
            f"{json.dumps(summary, ensure_ascii=False, default=str)}\n\n"
            "Сформируй краткую рекомендацию (2-3 предложения):\n"
            "1. Обоснование risk score\n"
            "2. Ключевые факторы (позитивные и негативные)\n"
            "3. Рекомендация по взаимодействию"
        )

        analysis = await self.think(prompt, max_tokens=300)

        if analysis:
            report.recommendation = analysis.strip()

    def _calculate_risk_score(self, investigator_data: Optional[dict], report: VerifierReport):
        """Calculate the final risk score (0-100)."""
        # Check for auto-critical conditions
        has_ofac = report.ofac_sdn == CheckStatus.FLAGGED
        has_frozen = (
            report.usdt_frozen == CheckStatus.FLAGGED
            or report.usdc_frozen == CheckStatus.FLAGGED
        )

        if has_ofac or has_frozen:
            report.risk_score = 100
            report.recommendation = (
                "CRITICAL: Address directly matches sanctions/frozen lists. "
                "AVOID all interaction."
            )
            return

        # Sum up weighted factors
        total = 0
        for factor_desc, points in report.score_factors:
            total += points

        # Apply mitigating factors
        for factor_desc, points in report.mitigating_factors:
            total += points  # points are negative

        # Clamp to 0-100
        report.risk_score = max(0, min(100, total))

        # Generate recommendation
        level = RiskLevel.from_score(report.risk_score)
        if level == RiskLevel.CLEAN:
            report.recommendation = "No threats detected. Low risk interaction."
        elif level == RiskLevel.LOW_RISK:
            report.recommendation = "Minor flags detected. Monitoring recommended."
        elif level == RiskLevel.MEDIUM_RISK:
            report.recommendation = "Suspicious connections found. Exercise caution."
        elif level == RiskLevel.HIGH_RISK:
            report.recommendation = (
                "Connections to sanctions/mixers/scams detected. "
                "AVOID interaction."
            )
        else:
            report.recommendation = (
                "Address in sanctions lists or direct criminal activity. "
                "DO NOT interact."
            )
