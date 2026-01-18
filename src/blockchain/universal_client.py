"""Universal blockchain client that supports multiple networks."""

import re
from typing import Dict, Literal
from web3 import Web3
from ..solana.client import SolanaClient
from ..evm.client import EVMClient


NetworkType = Literal["solana", "evm", "unknown"]


def detect_address_type(address: str) -> NetworkType:
    """Detect blockchain type by address format.

    Args:
        address: Blockchain address

    Returns:
        Network type: "solana", "evm", or "unknown"
    """
    address = address.strip()

    # Check for EVM address (0x followed by 40 hex characters)
    if re.match(r'^0x[a-fA-F0-9]{40}$', address):
        return "evm"

    # Check for Solana address (base58, 32-44 characters)
    if re.match(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$', address):
        return "solana"

    # Try Web3 validation for EVM
    if Web3.is_address(address):
        return "evm"

    return "unknown"


class UniversalBlockchainClient:
    """Universal client that routes requests to appropriate blockchain client."""

    def __init__(
        self,
        solana_client: SolanaClient,
        ethereum_client: EVMClient = None,
        bsc_client: EVMClient = None,
        polygon_client: EVMClient = None,
        default_evm_client: EVMClient = None
    ):
        """Initialize universal blockchain client.

        Args:
            solana_client: Solana client instance
            ethereum_client: Ethereum client instance (optional)
            bsc_client: BSC client instance (optional)
            polygon_client: Polygon client instance (optional)
            default_evm_client: Default EVM client if specific network client not available
        """
        self.solana_client = solana_client
        self.ethereum_client = ethereum_client
        self.bsc_client = bsc_client
        self.polygon_client = polygon_client
        self.default_evm_client = default_evm_client or ethereum_client

        # Map of available EVM clients
        self.evm_clients = {}
        if ethereum_client:
            self.evm_clients["ethereum"] = ethereum_client
        if bsc_client:
            self.evm_clients["bsc"] = bsc_client
        if polygon_client:
            self.evm_clients["polygon"] = polygon_client

    def get_evm_client(self, network: str = None) -> EVMClient:
        """Get EVM client for specific network or default.

        Args:
            network: Network name (ethereum, bsc, polygon, etc.)

        Returns:
            EVM client instance
        """
        if network and network in self.evm_clients:
            return self.evm_clients[network]
        return self.default_evm_client

    async def get_wallet_info(self, address: str, network: str = None) -> Dict:
        """Get wallet information for any supported blockchain.

        Args:
            address: Blockchain address
            network: Optional specific network (for EVM addresses)

        Returns:
            Dict with wallet information including network type
        """
        # Detect address type
        address_type = detect_address_type(address)

        if address_type == "unknown":
            return {
                "error": "Unknown address format. Supported: Solana, Ethereum, BSC, Polygon"
            }

        # Route to appropriate client
        if address_type == "solana":
            info = await self.solana_client.get_wallet_info(address)
            if "error" not in info:
                info["network_type"] = "solana"
                info["network"] = "solana"
                info["network_name"] = "Solana"
                info["symbol"] = "SOL"
                info["explorer"] = "https://solscan.io"
            return info

        elif address_type == "evm":
            # Get appropriate EVM client
            evm_client = self.get_evm_client(network)
            info = await evm_client.get_wallet_info(address)

            if "error" not in info:
                info["network_type"] = "evm"

            return info

        return {"error": "Unsupported network type"}

    def classify_whale(self, balance: float, network_type: str = "solana") -> Dict:
        """Classify wallet based on balance.

        Args:
            balance: Balance amount
            network_type: Network type (currently only supports "solana")

        Returns:
            Dict with tier info
        """
        if network_type == "solana":
            return self.solana_client.classify_whale(balance)
        # For EVM networks, could add different classifications in future
        return None

    async def discover_random_address_by_tier(self, tier: str = "whale", network: str = "solana"):
        """Discover random address of specified tier.

        Args:
            tier: Tier to search for (mega_whale, whale, dolphin, fish, shrimp)
            network: Network to search on (currently only "solana" supported)

        Returns:
            Random address of specified tier or None
        """
        if network == "solana":
            return await self.solana_client.discover_random_address_by_tier(tier)
        # For EVM networks, could add discovery in future
        return None

    async def close(self):
        """Close all client connections."""
        if self.solana_client:
            await self.solana_client.close()

        # EVM clients don't need explicit closing
