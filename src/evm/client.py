"""EVM blockchain client for wallet information retrieval."""

from datetime import datetime
from typing import Optional, Dict, List
from web3 import Web3
from web3.exceptions import Web3Exception


# Network configurations
NETWORKS = {
    "ethereum": {
        "name": "Ethereum",
        "symbol": "ETH",
        "explorer": "https://etherscan.io",
        "decimals": 18
    },
    "bsc": {
        "name": "BSC",
        "symbol": "BNB",
        "explorer": "https://bscscan.com",
        "decimals": 18
    },
    "polygon": {
        "name": "Polygon",
        "symbol": "MATIC",
        "explorer": "https://polygonscan.com",
        "decimals": 18
    },
    "arbitrum": {
        "name": "Arbitrum",
        "symbol": "ETH",
        "explorer": "https://arbiscan.io",
        "decimals": 18
    },
    "optimism": {
        "name": "Optimism",
        "symbol": "ETH",
        "explorer": "https://optimistic.etherscan.io",
        "decimals": 18
    },
    "avalanche": {
        "name": "Avalanche",
        "symbol": "AVAX",
        "explorer": "https://snowtrace.io",
        "decimals": 18
    }
}


# Known exchange addresses (можно расширить)
KNOWN_EXCHANGES = {
    "Binance": [
        "0x28C6c06298d514Db089934071355E5743bf21d60",
        "0xdfd5293d8e347dfe59e90efd55b2956a1343963d",
        "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549",
    ],
    "Coinbase": [
        "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3",
        "0x503828976D22510aad0201ac7EC88293211D23Da",
    ],
    "Kraken": [
        "0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2",
        "0x0A869d79a7052C7f1b55a8EbAbbEa3420F0D1E13",
    ],
}


class EVMClient:
    """Client for interacting with EVM-compatible blockchains."""

    def __init__(self, rpc_url: str, network: str = "ethereum"):
        """Initialize EVM client.

        Args:
            rpc_url: EVM RPC endpoint URL
            network: Network identifier (ethereum, bsc, polygon, etc.)
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.network = network.lower()
        self.network_config = NETWORKS.get(self.network, NETWORKS["ethereum"])
        self.exchange_addresses = self._flatten_exchange_addresses()

    def _flatten_exchange_addresses(self) -> Dict[str, str]:
        """Flatten exchange addresses into a single dict."""
        result = {}
        for exchange, addresses in KNOWN_EXCHANGES.items():
            for address in addresses:
                result[address.lower()] = exchange
        return result

    def is_connected(self) -> bool:
        """Check if connection to RPC is established.

        Returns:
            True if connected, False otherwise
        """
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    def is_exchange_address(self, address: str) -> Optional[str]:
        """Check if address belongs to a known exchange.

        Args:
            address: EVM address to check

        Returns:
            Exchange name if found, None otherwise
        """
        return self.exchange_addresses.get(address.lower())

    async def get_balance(self, address: str) -> Optional[float]:
        """Get native token balance of an address.

        Args:
            address: EVM address

        Returns:
            Balance in native token or None if error
        """
        try:
            checksum_address = Web3.to_checksum_address(address)
            balance_wei = self.w3.eth.get_balance(checksum_address)

            # Convert from wei to token units
            decimals = self.network_config["decimals"]
            balance = balance_wei / (10 ** decimals)

            return balance
        except Exception as e:
            print(f"Error getting balance for {address}: {e}")
            return None

    async def get_transaction_count(self, address: str) -> int:
        """Get transaction count (nonce) for an address.

        Args:
            address: EVM address

        Returns:
            Number of transactions sent from this address
        """
        try:
            checksum_address = Web3.to_checksum_address(address)
            return self.w3.eth.get_transaction_count(checksum_address)
        except Exception as e:
            print(f"Error getting transaction count for {address}: {e}")
            return 0

    async def get_block_number(self) -> int:
        """Get current block number.

        Returns:
            Current block number
        """
        try:
            return self.w3.eth.block_number
        except Exception:
            return 0

    async def get_wallet_age(self, address: str) -> Optional[Dict]:
        """Calculate wallet age (approximation based on first transaction).

        Note: This is an approximation. Accurate age requires external API
        or blockchain indexer.

        Args:
            address: EVM address

        Returns:
            Dict with wallet age approximation or None
        """
        # For EVM chains, getting exact first transaction requires
        # scanning all blocks or using external API
        # Here we provide transaction count as a proxy
        tx_count = await self.get_transaction_count(address)

        if tx_count == 0:
            return None

        # Return transaction count for now
        # TODO: Integrate with Etherscan/similar API for accurate first tx
        return {
            "transaction_count": tx_count,
            "formatted": f"{tx_count} транзакций"
        }

    async def get_wallet_info(self, address: str) -> Dict:
        """Get comprehensive wallet information.

        Args:
            address: EVM address

        Returns:
            Dict with all wallet information
        """
        # Validate address
        if not Web3.is_address(address):
            return {"error": "Invalid EVM address"}

        # Get balance and transaction count
        balance = await self.get_balance(address)
        wallet_age = await self.get_wallet_age(address)

        # Check if exchange
        exchange = self.is_exchange_address(address)

        # Normalize address to checksum format
        checksum_address = Web3.to_checksum_address(address)

        return {
            "address": checksum_address,
            "network": self.network,
            "network_name": self.network_config["name"],
            "symbol": self.network_config["symbol"],
            "explorer": self.network_config["explorer"],
            "is_exchange": exchange is not None,
            "exchange_name": exchange,
            "balance": balance,
            "wallet_age": wallet_age,
            "last_transaction": None,  # Requires external API
        }
